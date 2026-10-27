import asyncio
import uuid
import pytest
from backend.guardrails.output_guard import output_guardrail
from backend.core.database import db

async def mock_async_stream(chunks: list[str]):
    for chunk in chunks:
        await asyncio.sleep(0.001)
        yield chunk

def test_cross_chunk_split_prohibited_words_interception():
    """
    验收标准：
    跨 token 拆分的违禁词拦截率 100%
    """
    async def _run():
        test_cases = [
            (
                ["您可以", "直接加", "微", "信", "转", "账购买，享受内部折扣。"],
                "微信转账",
                "OFF_PLATFORM_TRANSACTION"
            ),
            (
                ["收到货后", "给个", "五星", "好", "评", "返", "现", "20元现金红包。"],
                "好评返现",
                "FAKE_REVIEW_CASHBACK"
            ),
            (
                ["这款机器", "在游戏本里是", "全", "网", "第", "一", "，", "绝", "对", "秒", "杀", "同价位所有机型。"],
                "全网第一",
                "EXTREME_EXAGGERATED_WORDS"
            )
        ]

        for chunks, prohibited_keyword, expected_rule in test_cases:
            session_id = f"test_guard_{uuid.uuid4().hex[:8]}"
            stream = mock_async_stream(chunks)
            collected = []
            async for out_chunk in output_guardrail.guard_stream(stream, session_id=session_id):
                collected.append(out_chunk)
            full_output = "".join(collected)

            # 1. 断言流式重组后绝不包含原违禁词 (100% 拦截)
            assert prohibited_keyword not in full_output, f"Prohibited word '{prohibited_keyword}' leaked into output!"

            # 2. 断言包含系统合规安全提示
            assert "系统合规提示" in full_output

            # 3. 验证 SQLite 数据库是否持久化记录了该拦截事件
            events = db.get_guardrail_events(session_id=session_id)
            assert len(events) >= 1
            assert events[0]["rule_name"] == expected_rule
            assert events[0]["event_type"] == "prohibited_word"

    asyncio.run(_run())

def test_normal_compliant_stream_lossless_passthrough():
    """
    验收标准：
    正常合规回复经过缓冲器后逐字无损输出
    """
    async def _run():
        normal_chunks = [
            "暗影精灵9", "配备了", "i7-14700HX", "处理器与",
            "RTX 4060", "独显，", "支持", "140W", "满血功耗释放；",
            "同时拥有", "双 M.2 固态插槽，", "后期升级拓展非常方便！"
        ]
        expected_full_text = "".join(normal_chunks)

        session_id = f"test_lossless_{uuid.uuid4().hex[:8]}"
        stream = mock_async_stream(normal_chunks)
        collected = []
        async for out_chunk in output_guardrail.guard_stream(stream, session_id=session_id):
            collected.append(out_chunk)

        result_text = "".join(collected)
        # 断言输出字符完全一致，逐字无损
        assert result_text == expected_full_text, f"Mismatch:\nExpected: {expected_full_text}\nGot: {result_text}"

        # 断言未触发任何拦截事件
        events = db.get_guardrail_events(session_id=session_id)
        assert len(events) == 0

    asyncio.run(_run())

