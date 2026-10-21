import time
import json
from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from backend.core.models.chat_schemas import ChatCompletionRequest
from backend.core.database import db
from backend.core.cache import local_cache
from backend.core.context_manager import context_manager
from backend.core.llm_client import llm_adapter
from backend.rag.hybrid_retriever import hybrid_retriever

router = APIRouter(prefix="/chat", tags=["Chat"])

@router.post("/completions")
async def chat_completions(req: ChatCompletionRequest):
    start_time = time.time()

    # 1. 查询高频问答缓存
    cached_reply = local_cache.get_answer(req.spu_code, req.query)
    if cached_reply:
        async def stream_cached():
            cost_ms = int((time.time() - start_time) * 1000)
            chunk_size = 6
            for i in range(0, len(cached_reply), chunk_size):
                chunk = cached_reply[i:i+chunk_size]
                yield f"data: {json.dumps({'type': 'chunk', 'content': chunk}, ensure_ascii=False)}\n\n"
            yield f"data: {json.dumps({'type': 'meta', 'prompt_version': context_manager.prompt_version, 'cost_ms': cost_ms, 'is_cached': True}, ensure_ascii=False)}\n\n"
            yield "data: [DONE]\n\n"

        return StreamingResponse(stream_cached(), media_type="text/event-stream")

    # 2. 事实直查：提取 SPU 规格并校验生成锚定事实块 (Pydantic 防幻觉通道)
    anchor_fact = None
    if req.spu_code:
        product = db.get_product(req.spu_code)
        if product:
            anchor_fact = product.to_anchor_fact()

    # 3. 本地双引擎混合检索 (BM25 专有名词 + ChromaDB FastEmbed 向量)
    rag_context = hybrid_retriever.retrieve(req.query, top_k=2)

    # 4. 组装 1000 Token 预算消息序列
    messages = context_manager.assemble_messages(
        query=req.query,
        history=req.history,
        anchor_fact=anchor_fact,
        rag_context=rag_context
    )

    # 4. 驱动统一 LLM 流式输出生成器
    async def sse_event_generator():
        full_reply_text = ""
        try:
            async for token in llm_adapter.stream_chat(messages):
                full_reply_text += token
                yield f"data: {json.dumps({'type': 'chunk', 'content': token}, ensure_ascii=False)}\n\n"

            cost_ms = int((time.time() - start_time) * 1000)

            # 写入本地高频问答缓存 (1 小时 TTL)
            if full_reply_text and not full_reply_text.startswith("\n[服务提示"):
                local_cache.set_answer(req.spu_code, req.query, full_reply_text)

            # 异步记录会话日志到 SQLite
            db.log_conversation(
                session_id=req.session_id,
                spu_code=req.spu_code,
                user_query=req.query,
                agent_response=full_reply_text,
                prompt_version=context_manager.prompt_version,
                cost_ms=cost_ms
            )

            # 输出元数据与结束标识
            meta_info = {
                "type": "meta",
                "prompt_version": context_manager.prompt_version,
                "cost_ms": cost_ms,
                "is_cached": False
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
            "X-Accel-Buffering": "no"
        }
    )

