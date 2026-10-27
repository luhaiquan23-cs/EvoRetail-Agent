import os
import sys
import json
import pytest
import asyncio

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from backend.core.database import db
from backend.agent.runner import agent_runner, AgentRunner
from tests.fakes.fake_llm import FakeAsyncOpenAIClient

def test_agent_runner_compare_products_mock():
    async def _run():
        db.seed_mock_data()
        messages = [
            {"role": "user", "content": "光影精灵16和暗影精灵16 Slim比哪个更轻？差多少钱？"}
        ]

        events = []
        async for ev in agent_runner.run(messages=messages, force_mock=True):
            events.append(ev)

        # 1. 验证真实调用了 compare_products 工具
        tool_events = [e for e in events if e.get("type") == "tool_call"]
        assert len(tool_events) >= 1
        cmp_call = next(e for e in tool_events if e["tool_name"] == "compare_products")
        assert "HP-VICTUS-16" in cmp_call["arguments"]["spu_codes"]
        assert "HP-OMEN-16-SLIM" in cmp_call["arguments"]["spu_codes"]
        assert cmp_call["result"]["found"] is True

        # 2. 验证回答文本包含真实重量与差价
        chunks = [e["content"] for e in events if e.get("type") == "chunk"]
        full_text = "".join(chunks)
        assert "2.3kg" in full_text
        assert "2.1kg" in full_text
        assert "2000" in full_text
        print("[PASS] AgentRunner cross-model comparison (Mock mode) verified with exact weight and price diff.")

    asyncio.run(_run())

def test_agent_runner_filter_budget_mock():
    async def _run():
        messages = [
            {"role": "user", "content": "预算5500以内想买台轻薄本，推荐哪款？"}
        ]

        events = []
        async for ev in agent_runner.run(messages=messages, force_mock=True):
            events.append(ev)

        tool_events = [e for e in events if e.get("type") == "tool_call"]
        assert len(tool_events) >= 1
        flt_call = next(e for e in tool_events if e["tool_name"] == "filter_products")
        assert flt_call["arguments"]["max_price"] == 5500.0
        assert flt_call["arguments"]["category"] == "轻薄办公本"
        assert flt_call["result"]["total_matched"] > 0

        chunks = [e["content"] for e in events if e.get("type") == "chunk"]
        full_text = "".join(chunks)
        assert "5500" in full_text or "符合条件" in full_text
        print("[PASS] AgentRunner budget filter (Mock mode) verified with filter_products tool call.")

    asyncio.run(_run())

def test_agent_runner_infinite_tool_loop_termination():
    async def _run():
        fake_client = FakeAsyncOpenAIClient(behavior="infinite_tools")
        runner = AgentRunner(max_steps=5)
        messages = [{"role": "user", "content": "我想咨询惠普售后政策"}]

        events = []
        async for ev in runner.run(messages=messages, custom_client=fake_client):
            events.append(ev)

        tool_events = [e for e in events if e.get("type") == "tool_call"]
        assert len(tool_events) == 5, f"Expected exactly 5 tool calls before termination, got {len(tool_events)}"

        chunks = [e["content"] for e in events if e.get("type") == "chunk"]
        full_text = "".join(chunks)
        assert "已达到工具调用最大步数上限 (5步)" in full_text
        print("[PASS] AgentRunner infinite loop terminated strictly at max_steps=5.")

    asyncio.run(_run())

def test_agent_runner_single_tool_then_text_live():
    async def _run():
        fake_client = FakeAsyncOpenAIClient(behavior="single_tool_then_text")
        runner = AgentRunner(max_steps=5)
        messages = [{"role": "user", "content": "光影16和暗影16 Slim哪个更轻？"}]

        events = []
        async for ev in runner.run(messages=messages, custom_client=fake_client):
            events.append(ev)

        tool_events = [e for e in events if e.get("type") == "tool_call"]
        assert len(tool_events) == 1
        assert tool_events[0]["tool_name"] == "compare_products"

        chunks = [e["content"] for e in events if e.get("type") == "chunk"]
        full_text = "".join(chunks)
        assert "对比完成" in full_text
        print("[PASS] AgentRunner single tool then text (Live simulated) verified.")

    asyncio.run(_run())

if __name__ == "__main__":
    test_agent_runner_compare_products_mock()
    test_agent_runner_filter_budget_mock()
    test_agent_runner_infinite_tool_loop_termination()
    test_agent_runner_single_tool_then_text_live()
    print("\n[ALL PASS] All agent runner tests passed successfully!")
