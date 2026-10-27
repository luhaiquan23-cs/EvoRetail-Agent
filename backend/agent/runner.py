import os
import time
import json
import re
import asyncio
from typing import Dict, Any, List, Optional, AsyncGenerator, Tuple

from backend.core.database import db
from backend.core.llm_client import llm_adapter
from backend.agent.tools import (
    AGENT_TOOLS_SCHEMA,
    AGENT_TOOLS_MAP,
    resolve_spu,
    compare_products,
    filter_products,
    get_product_detail,
    search_policy_kb,
    ALIAS_MAP
)

class AgentRunner:
    """
    ReAct / Tool Calling 智能体决策循环调度器
    1. 支持 OpenAI 标准 tools 协议的多步决策执行 (最多 5 步循环)
    2. 单工具执行具备 3 秒超时控制熔断
    3. 在离线 Mock 模式下内置确定性本地意图-工具路由器 (Local Intent Tool Router)
    """
    def __init__(self, max_steps: int = 5, tool_timeout: float = 3.0):
        self.max_steps = max_steps
        self.tool_timeout = tool_timeout

    def execute_tool_sync(self, tool_name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """同步执行工具函数"""
        tool_fn = AGENT_TOOLS_MAP.get(tool_name)
        if not tool_fn:
            return {"error": f"未知的工具名称: {tool_name}", "found": False}
        try:
            return tool_fn(**arguments)
        except Exception as e:
            return {"error": f"工具执行异常 ({tool_name}): {str(e)}", "found": False}

    async def execute_tool_async(self, tool_name: str, arguments: Dict[str, Any]) -> Tuple[Dict[str, Any], int]:
        """带超时控制的工具执行器"""
        start_t = time.time()
        try:
            # 在单独线程中运行工具避免阻塞事件循环，加超时
            res = await asyncio.wait_for(
                asyncio.to_thread(self.execute_tool_sync, tool_name, arguments),
                timeout=self.tool_timeout
            )
        except asyncio.TimeoutError:
            res = {"error": f"工具 '{tool_name}' 执行超时 (> {self.tool_timeout}s)", "found": False}
        except Exception as e:
            res = {"error": f"执行工具异常: {str(e)}", "found": False}

        cost_ms = int((time.time() - start_t) * 1000)
        return res, cost_ms

    async def run(
        self,
        messages: List[Dict[str, Any]],
        spu_code: Optional[str] = None,
        force_mock: bool = False,
        custom_client: Any = None,
        mode_holder: Optional[Dict[str, str]] = None
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """
        驱动 Agent 决策与执行流
        Yields:
          {"type": "tool_call", "tool_name": ..., "arguments": ..., "cost_ms": ..., "result": ...}
          {"type": "chunk", "content": ...}
        """
        client = custom_client or llm_adapter.get_client()
        user_query = messages[-1].get("content", "") if messages else ""

        # --- 模式 A: 真实大模型 OpenAI Tools 调用循环 ---
        if client and not force_mock:
            if mode_holder is not None:
                mode_holder["mode"] = "live"

            current_messages = list(messages)
            step = 0

            while step < self.max_steps:
                step += 1
                try:
                    stream_res = await client.chat.completions.create(
                        model=llm_adapter.model,
                        messages=current_messages,
                        tools=AGENT_TOOLS_SCHEMA,
                        temperature=llm_adapter.temperature,
                        stream=True
                    )

                    tool_calls_buffer: Dict[int, Dict[str, Any]] = {}
                    text_chunks = []

                    async for chunk in stream_res:
                        if not chunk.choices or not chunk.choices[0].delta:
                            continue
                        delta = chunk.choices[0].delta

                        # 1. 文本流式 chunk
                        if delta.content:
                            text_chunks.append(delta.content)
                            yield {"type": "chunk", "content": delta.content}

                        # 2. 工具调用增量拼装
                        if delta.tool_calls:
                            for tc in delta.tool_calls:
                                idx = tc.index if hasattr(tc, 'index') and tc.index is not None else 0
                                if idx not in tool_calls_buffer:
                                    tool_calls_buffer[idx] = {
                                        "id": getattr(tc, 'id', f"call_{step}_{idx}") or f"call_{step}_{idx}",
                                        "name": "",
                                        "arguments": ""
                                    }
                                if hasattr(tc, 'function') and tc.function:
                                    if tc.function.name:
                                        tool_calls_buffer[idx]["name"] += tc.function.name
                                    if tc.function.arguments:
                                        tool_calls_buffer[idx]["arguments"] += tc.function.arguments

                    # 如果没有工具调用，说明模型已经给出了最终回复
                    if not tool_calls_buffer:
                        llm_adapter.record_success()
                        return

                    # 存在工具调用，并发/顺序执行工具
                    for idx, call_info in tool_calls_buffer.items():
                        tool_name = call_info["name"]
                        try:
                            tool_args = json.loads(call_info["arguments"]) if call_info["arguments"] else {}
                        except Exception:
                            tool_args = {}

                        tool_res, tool_cost = await self.execute_tool_async(tool_name, tool_args)
                        yield {
                            "type": "tool_call",
                            "tool_name": tool_name,
                            "arguments": tool_args,
                            "cost_ms": tool_cost,
                            "result": tool_res
                        }

                        # 追加 assistant tool_calls 消息和 tool 结果回填
                        current_messages.append({
                            "role": "assistant",
                            "content": "".join(text_chunks) if text_chunks else None,
                            "tool_calls": [{
                                "id": call_info["id"],
                                "type": "function",
                                "function": {
                                    "name": tool_name,
                                    "arguments": call_info["arguments"]
                                }
                            }]
                        })
                        current_messages.append({
                            "role": "tool",
                            "tool_call_id": call_info["id"],
                            "name": tool_name,
                            "content": json.dumps(tool_res, ensure_ascii=False)
                        })
                    llm_adapter.record_success()

                except Exception as e:
                    print(f"[ERROR] [AgentRunner] Live loop exception at step {step}: {e}")
                    llm_adapter.record_failure()
                    if mode_holder is not None:
                        mode_holder["mode"] = "fallback"
                    yield {"type": "chunk", "content": f"\n[服务提示: 远程模型调用异常 ({e})，已切换本地兜底]\n"}
                    break

            if step >= self.max_steps:
                yield {"type": "chunk", "content": "\n[服务提示: 已达到工具调用最大步数上限 (5步)，为您提供当前阶段的分析总结]\n"}
                return

        # --- 模式 B: 本地确定性意图-工具路由器 (Local Intent Tool Router) ---
        if mode_holder is not None and mode_holder.get("mode") != "fallback":
            mode_holder["mode"] = "mock"

        # 1. 意图检测：跨机型对比
        # 扫描用户问题中提及的所有商品或别名（支持空格归一化模糊匹配）
        mentioned_spus = []
        user_q_clean = re.sub(r"[\s\-_\(\)（）【】\[\]]+", "", user_query.lower())
        sorted_aliases = sorted(ALIAS_MAP.items(), key=lambda x: len(x[0]), reverse=True)
        for alias, code in sorted_aliases:
            alias_clean = re.sub(r"[\s\-_\(\)（）【】\[\]]+", "", alias.lower())
            if alias_clean in user_q_clean:
                if code not in mentioned_spus:
                    mentioned_spus.append(code)

        for p in db.list_products():
            spu_clean = re.sub(r"[\s\-_\(\)（）【】\[\]]+", "", p["spu_code"].lower())
            title_clean = re.sub(r"[\s\-_\(\)（）【】\[\]]+", "", p["title"].lower())
            if spu_clean in user_q_clean or (len(title_clean) >= 4 and title_clean in user_q_clean):
                if p["spu_code"] not in mentioned_spus:
                    mentioned_spus.append(p["spu_code"])

        is_compare_intent = (
            len(mentioned_spus) >= 2 or
            (len(mentioned_spus) >= 1 and any(k in user_query for k in ["比", "对比", "哪个更", "差多少", "相比"]))
        )

        if is_compare_intent and len(mentioned_spus) >= 2:
            target_spus = mentioned_spus[:4]
            tool_args = {"spu_codes": target_spus}
            cmp_res, tool_cost = await self.execute_tool_async("compare_products", tool_args)
            yield {
                "type": "tool_call",
                "tool_name": "compare_products",
                "arguments": tool_args,
                "cost_ms": tool_cost,
                "result": cmp_res
            }

            if cmp_res.get("found"):
                t = cmp_res["comparison_table"]
                diff = cmp_res["diff_summary"]
                p1, p2 = t[0], t[1]

                # 价格对比描述
                if diff["price_diff_yuan"] == 0:
                    price_text = f"{p1['title']} 与 {p2['title']} 官方价均为 ¥{p1['official_price']:.2f}；"
                else:
                    cheaper_title = p1['title'] if diff['cheapest_spu'] == p1['spu_code'] else p2['title']
                    price_text = f"{p1['title']} 官方价 ¥{p1['official_price']:.2f}，{p2['title']} 官方价 ¥{p2['official_price']:.2f}，两款差价为 {diff['price_diff_yuan']:.0f} 元（{cheaper_title} 相对更亲民）；"

                # 重量对比描述
                if diff["weight_diff_kg"] == 0:
                    weight_text = f"两款机型重量相当（均为 {p1['weight_kg']}kg）；"
                else:
                    lightest_title = p1['title'] if diff['lightest_spu'] == p1['spu_code'] else p2['title']
                    weight_text = f"{p1['title']} 裸机重 {p1['weight_kg']}kg，{p2['title']} 裸机重 {p2['weight_kg']}kg，{lightest_title} 相对更轻 {diff['weight_diff_kg']}kg（移动便携更佳）；"

                reply = (
                    f"您好！我是惠普官方顾问智小惠。为您横向对比【{p1['title']}】与【{p2['title']}】：\n"
                    f"1. 价格与差价：{price_text}\n"
                    f"2. 重量与便携：{weight_text}\n"
                    f"3. 核心性能释放：{p1['title']} 为 {p1['cpu']} + {p1['gpu']} ({p1['tgp_watt']}W)，{p2['title']} 为 {p2['cpu']} + {p2['gpu']} ({p2['tgp_watt']}W)；\n"
                    f"4. 扩展与接口：{p1['title']}配备 {p1['ram_slots']}内存槽/{p1['m2_slots']}固态槽({p1['thunderbolt']})，{p2['title']}配备 {p2['ram_slots']}内存槽/{p2['m2_slots']}固态槽({p2['thunderbolt']})。\n"
                )
                if any(k in user_query for k in ["固态", "加装", "内存", "升级", "双通道"]):
                    reply += "【加装升级答复】：两款机型均配备 2 个内存插槽与 2 个 M.2 固态插槽，均支持自行开盖加装第二根固态硬盘并升级双通道内存，且享受官方 2 年全国联保支持自行开盖加装不影响整机质保！\n"
                reply += "两款机型均享受 2 年官方全国联保支持自行开盖加装固态不脱保。请问您平时是更看重 3A 游戏的画质帧率，还是更在乎日常出差或去图书馆的轻薄便携呢？"
                for ch in reply:
                    yield {"type": "chunk", "content": ch}
                return

        # 2. 意图检测：按预算/品类筛选
        budget_match = re.search(r'(?:预算)?\s*([1-9]\d{3,4})\s*(?:以?内|元|块|左右|下)', user_query)
        is_filter_intent = bool(budget_match) or any(k in user_query for k in ["推荐哪款", "选哪款", "求推荐", "多少钱以内"])

        if is_filter_intent:
            max_p = float(budget_match.group(1)) if budget_match else None
            cat = None
            if "轻薄" in user_query or "办公" in user_query:
                cat = "轻薄办公本"
            elif "游戏" in user_query or "电竞" in user_query:
                cat = "游戏笔记本"
            elif "设计" in user_query or "工作站" in user_query:
                cat = "工作站"

            tool_args = {"max_price": max_p, "category": cat}
            flt_res, tool_cost = await self.execute_tool_async("filter_products", tool_args)
            yield {
                "type": "tool_call",
                "tool_name": "filter_products",
                "arguments": tool_args,
                "cost_ms": tool_cost,
                "result": flt_res
            }

            matched_prods = flt_res.get("products", [])
            if matched_prods:
                reply = f"您好！为您筛选出符合条件（"
                if max_p:
                    reply += f"预算 ≤ ¥{max_p:.0f}"
                if cat:
                    reply += f"，品类: {cat}"
                reply += "）的高性价比在售机型：\n"
                for p in matched_prods[:3]:
                    reply += f"- 【{p['title']}】：官方售价 ¥{p['official_price']}，搭载 {p['cpu']} / {p['gpu']} ({p['tgp_watt']}W)，裸机仅重 {p['weight_kg']}kg；\n"
                reply += "全店均享官方正品发票与全国联保支持。请问您平时主要用来打游戏、剪辑视频还是移动便携办公呢？我们可以为您锁定最合适的一款！"
            else:
                reply = f"抱歉，在您指定的预算范围与筛选条件下暂未找到完全匹配的机型，建议您可以适当放宽预算要求，或告诉我您的主要用途，我为您精选推荐！"

            for ch in reply:
                yield {"type": "chunk", "content": ch}
            return

        # 3. 意图检测：售后政策、顺丰快递与质保知识库
        is_policy_intent = any(k in user_query for k in [
            "保修", "质保", "联保", "上门", "加装", "脱保", "顺丰", "快递", "发货", "开箱", "验机", "赠品", "大礼包", "发票"
        ])
        if is_policy_intent:
            tool_args = {"query": user_query}
            kb_res, tool_cost = await self.execute_tool_async("search_policy_kb", tool_args)
            yield {
                "type": "tool_call",
                "tool_name": "search_policy_kb",
                "arguments": tool_args,
                "cost_ms": tool_cost,
                "result": kb_res
            }

        # 4. 默认机型规格咨询
        if spu_code:
            tool_args = {"spu_code": spu_code}
            detail_res, tool_cost = await self.execute_tool_async("get_product_detail", tool_args)
            yield {
                "type": "tool_call",
                "tool_name": "get_product_detail",
                "arguments": tool_args,
                "cost_ms": tool_cost,
                "result": detail_res
            }

        # 调用本地事实生成器输出
        async for token in llm_adapter.stream_chat(messages, force_mock=True):
            yield {"type": "chunk", "content": token}

agent_runner = AgentRunner()
