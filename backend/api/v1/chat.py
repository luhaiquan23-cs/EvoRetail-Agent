import re
import time
import json
import logging
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from backend.core.models.chat_schemas import ChatCompletionRequest
from backend.core.database import db
from backend.core.cache import local_cache
from backend.core.context_manager import context_manager
from backend.core.llm_client import llm_adapter
from backend.rag.hybrid_retriever import hybrid_retriever
from backend.agent.runner import agent_runner
from backend.core.models.buyer_profile import BuyerProfile
from backend.agent.slot_extractor import slot_extractor
from backend.guardrails.output_guard import output_guardrail, CLAUSE_DELIMITERS
from backend.core.tracer import tracer
from backend.core.limiter import session_rate_limiter

logger = logging.getLogger("chat")

router = APIRouter(prefix="/chat", tags=["Chat"])

@router.post("/completions")
async def chat_completions(req: ChatCompletionRequest):
    # 0. 会话级滑动窗口限流保护 (15次/分钟)
    if not session_rate_limiter.is_allowed(req.session_id):
        raise HTTPException(
            status_code=429,
            detail=f"Rate limit exceeded: maximum {session_rate_limiter.max_requests} requests per minute for session '{req.session_id}'"
        )

    start_time = time.time()
    span = tracer.start_trace(
        session_id=req.session_id,
        spu_code=req.spu_code,
        prompt_version=context_manager.prompt_version
    )

    # 1. 查询高频问答缓存
    cached_reply = local_cache.get_answer(req.spu_code, req.query)
    if cached_reply:
        async def stream_cached():
            span.mark_first_token()
            cost_ms = int((time.time() - start_time) * 1000)
            chunk_size = 6
            for i in range(0, len(cached_reply), chunk_size):
                chunk = cached_reply[i:i+chunk_size]
                yield f"data: {json.dumps({'type': 'chunk', 'content': chunk}, ensure_ascii=False)}\n\n"

            in_tokens = context_manager.count_tokens(req.query)
            out_tokens = context_manager.count_tokens(cached_reply)
            total_tokens = in_tokens + out_tokens
            await span.async_finish(
                llm_mode="cache",
                input_tokens=in_tokens,
                output_tokens=out_tokens,
                is_cached=True
            )

            yield f"data: {json.dumps({'type': 'meta', 'trace_id': span.trace_id, 'prompt_version': context_manager.prompt_version, 'cost_ms': cost_ms, 'is_cached': True, 'llm_mode': 'cache', 'input_tokens': in_tokens, 'output_tokens': out_tokens, 'total_tokens': total_tokens}, ensure_ascii=False)}\n\n"
            yield "data: [DONE]\n\n"

        return StreamingResponse(
            stream_cached(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
                "X-Trace-Id": span.trace_id
            }
        )

    # 2. 买家画像提取与持久化长记忆管理 (跨轮不遗忘，异步非阻塞读写)
    buyer_profile = (await db.async_get_buyer_profile(req.session_id)) or BuyerProfile()
    extracted_profile = slot_extractor.extract_from_text(req.query)
    if not extracted_profile.is_empty():
        buyer_profile.merge(extracted_profile)
        await db.async_save_buyer_profile(req.session_id, buyer_profile)

    # 3. 事实直查：智能检测目标 SPU 规格并校验生成锚定事实块 (Pydantic 防幻觉通道)
    from backend.agent.tools import resolve_spu, ALIAS_MAP
    anchor_fact = None
    product = None

    # 优先检测买家 query 中是否明确提及了具体机型
    detected_spu = None
    query_clean = re.sub(r"[\s\-_\(\)（）【】\[\]]+", "", req.query.lower())
    sorted_aliases = sorted(ALIAS_MAP.items(), key=lambda x: len(x[0]), reverse=True)
    for alias, spu in sorted_aliases:
        alias_clean = re.sub(r"[\s\-_\(\)（）【】\[\]]+", "", alias.lower())
        if alias_clean in query_clean:
            detected_spu = spu
            break

    # 检查是否为跨机型对比或按预算全局筛选（此类意图下不强塞单一默认机型事实）
    is_comparison_or_filter = any(k in req.query for k in ["比", "对比", "哪个更", "选哪款", "推荐哪款", "求推荐", "多少钱以内", "预算"])
    target_spu = detected_spu or (req.spu_code if not is_comparison_or_filter else None)

    if target_spu:
        product = await db.async_get_product(target_spu)
        if product:
            anchor_fact = product.to_anchor_fact()

    # 4. 本地双引擎混合检索 (BM25 专有名词 + ChromaDB FastEmbed 向量)
    rag_context = hybrid_retriever.retrieve(req.query, top_k=2)

    # 5. 组装 1000 Token 预算消息序列 (常驻买家画像长记忆)
    messages = context_manager.assemble_messages(
        query=req.query,
        history=req.history,
        anchor_fact=anchor_fact,
        rag_context=rag_context,
        buyer_profile=buyer_profile
    )

    # 6. 驱动统一 Agent 决策与流式输出生成器 (输出端句级护栏保护)
    input_tokens = context_manager.count_messages_tokens(messages)

    async def sse_event_generator():
        full_reply_text = ""
        mode_holder = {"mode": "mock"}
        tools_called = []
        buffer = ""
        # 对比与全局筛选场景下不传递固定 product_item，由护栏针对每个子句独立识别机型实体
        product_item = product if target_spu and product and not is_comparison_or_filter else None
        try:
            async for event in agent_runner.run(
                messages=messages,
                spu_code=target_spu or req.spu_code,
                mode_holder=mode_holder
            ):
                span.mark_first_token()
                if event["type"] == "tool_call":
                    if buffer:
                        sanitized, triggered = output_guardrail.guard_text(
                            buffer,
                            session_id=req.session_id,
                            spu_code=req.spu_code,
                            product=product_item
                        )
                        if triggered:
                            span.record_guardrail(True)
                        full_reply_text += sanitized
                        yield f"data: {json.dumps({'type': 'chunk', 'content': sanitized}, ensure_ascii=False)}\n\n"
                        buffer = ""
                    tools_called.append(event)
                    span.record_tool_call(event)
                    yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
                elif event["type"] == "chunk":
                    buffer += event["content"]
                    while True:
                        split_match = CLAUSE_DELIMITERS.search(buffer)
                        if split_match:
                            del_end = split_match.end()
                            clause = buffer[:del_end]
                            buffer = buffer[del_end:]
                            sanitized, triggered = output_guardrail.guard_text(
                                clause,
                                session_id=req.session_id,
                                spu_code=req.spu_code,
                                product=product_item
                            )
                            if triggered:
                                span.record_guardrail(True)
                            full_reply_text += sanitized
                            yield f"data: {json.dumps({'type': 'chunk', 'content': sanitized}, ensure_ascii=False)}\n\n"
                        elif len(buffer) >= 120:
                            # 缓冲区过长未见标点，安全回退寻找词边界（避免在数字/单位中间腰斩）
                            cut_pos = 120
                            while cut_pos > 30 and (buffer[cut_pos-1].isalnum() or buffer[cut_pos-1] in "-_.*"):
                                cut_pos -= 1
                            if cut_pos <= 30:
                                cut_pos = 120
                            clause = buffer[:cut_pos]
                            buffer = buffer[cut_pos:]
                            sanitized, triggered = output_guardrail.guard_text(
                                clause,
                                session_id=req.session_id,
                                spu_code=req.spu_code,
                                product=product_item
                            )
                            if triggered:
                                span.record_guardrail(True)
                            full_reply_text += sanitized
                            yield f"data: {json.dumps({'type': 'chunk', 'content': sanitized}, ensure_ascii=False)}\n\n"
                        else:
                            break

            if buffer:
                sanitized, triggered = output_guardrail.guard_text(
                    buffer,
                    session_id=req.session_id,
                    spu_code=req.spu_code,
                    product=product_item
                )
                if triggered:
                    span.record_guardrail(True)
                full_reply_text += sanitized
                yield f"data: {json.dumps({'type': 'chunk', 'content': sanitized}, ensure_ascii=False)}\n\n"

            cost_ms = int((time.time() - start_time) * 1000)
            actual_llm_mode = mode_holder.get("mode", "mock")
            output_tokens = context_manager.count_tokens(full_reply_text)

            # 写入本地高频问答缓存 (1 小时 TTL)
            # fallback 回复绝不写入 DiskCache
            if actual_llm_mode != "fallback" and full_reply_text and not full_reply_text.startswith("\n[服务提示"):
                local_cache.set_answer(req.spu_code, req.query, full_reply_text)

            # 异步记录会话日志与全链路追踪记录到 SQLite
            try:
                await db.async_log_conversation(
                    session_id=req.session_id,
                    spu_code=req.spu_code,
                    query=req.query,
                    response=full_reply_text,
                    prompt_version=context_manager.prompt_version,
                    cost_ms=cost_ms
                )
            except Exception as log_err:
                logger.error(f"Failed to log conversation to SQLite: {log_err}")

            try:
                await span.async_finish(
                    llm_mode=actual_llm_mode,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    is_cached=False
                )
            except Exception as trace_err:
                logger.error(f"Failed to save trace to SQLite: {trace_err}")

            # 输出元数据与结束标识
            meta_info = {
                "type": "meta",
                "trace_id": span.trace_id,
                "prompt_version": context_manager.prompt_version,
                "cost_ms": cost_ms,
                "is_cached": False,
                "llm_mode": actual_llm_mode,
                "tools_called_count": len(tools_called),
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "total_tokens": input_tokens + output_tokens
            }
            yield f"data: {json.dumps(meta_info, ensure_ascii=False)}\n\n"
            yield "data: [DONE]\n\n"

        except Exception as e:
            err_info = {"type": "error", "message": str(e)}
            yield f"data: {json.dumps(err_info, ensure_ascii=False)}\n\n"
            yield "data: [DONE]\n\n"

    return StreamingResponse(
        sse_event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
            "X-Trace-Id": span.trace_id
        }
    )

@router.get("/sessions")
async def get_chat_sessions(limit: int = 50):
    """获取所有历史会话列表（含首条提问摘要、咨询机型、消息总数与最后活跃时间）"""
    sessions = await db.async_list_sessions(limit=limit)
    return {
        "code": 200,
        "message": "success",
        "data": sessions
    }

@router.get("/history")
async def get_chat_history(session_id: str):
    """根据 session_id 获取指定会话的完整问答历史记录与买家画像"""
    if not session_id:
        raise HTTPException(status_code=400, detail="session_id is required")

    logs = await db.async_get_session_messages(session_id)
    profile = await db.async_get_buyer_profile(session_id)

    formatted_messages = []
    for log in logs:
        log_id = log["id"]
        # 买家提问
        if log.get("user_query"):
            formatted_messages.append({
                "id": f"hist_u_{log_id}",
                "role": "user",
                "content": log["user_query"],
                "created_at": log["created_at"]
            })
        # 智小惠客服回答
        if log.get("agent_response"):
            resp_tokens = context_manager.count_tokens(log["agent_response"])
            query_tokens = context_manager.count_tokens(log.get("user_query") or "")
            formatted_messages.append({
                "id": f"hist_a_{log_id}",
                "role": "assistant",
                "content": log["agent_response"],
                "meta": {
                    "prompt_version": log.get("prompt_version") or "v2.0.0",
                    "cost_ms": log.get("cost_ms", 0),
                    "llm_mode": "live",
                    "output_tokens": resp_tokens,
                    "input_tokens": query_tokens,
                    "total_tokens": resp_tokens + query_tokens
                },
                "created_at": log["created_at"]
            })

    profile_data = None
    if profile:
        profile_data = profile.model_dump() if hasattr(profile, "model_dump") else profile.dict()

    return {
        "code": 200,
        "message": "success",
        "data": {
            "session_id": session_id,
            "messages": formatted_messages,
            "buyer_profile": profile_data,
            "total_messages": len(formatted_messages)
        }
    }

