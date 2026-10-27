import asyncio
import uuid
import pytest
from backend.core.database import db
from backend.core.models.buyer_profile import BuyerProfile

def test_async_concurrent_rw_50_coroutines():
    """
    验收标准：
    50 个异步协程并发写入会话日志与读取商品，成功率 100%，日志表精确新增 50 行，无锁库报错
    """
    async def _run():
        with db.get_connection() as conn:
            initial_count = conn.execute("SELECT COUNT(*) FROM conversation_logs").fetchone()[0]

        test_run_id = uuid.uuid4().hex[:8]

        async def worker(idx: int):
            # 1. 异步非阻塞读商品
            prod = await db.async_get_product("HP-VICTUS-16")
            assert prod is not None, "Product must exist"
            assert prod.spu_code == "HP-VICTUS-16"

            # 2. 异步非阻塞写会话留存日志
            session_id = f"async_test_{test_run_id}_{idx}"
            await db.async_log_conversation(
                session_id=session_id,
                spu_code="HP-VICTUS-16",
                user_query=f"并发测试提问 #{idx}: 这款显卡释放多少瓦？",
                agent_response=f"并发测试回复 #{idx}: 支持 140W 满血释放，搭配双 M.2 插槽！",
                prompt_version="v2.0.0",
                cost_ms=120
            )
            return True

        # 50 个协程并发调度执行
        try:
            tasks = [worker(i) for i in range(50)]
            results = await asyncio.gather(*tasks)

            # 断言 50 个协程全部成功 (100% 成功率，无 database is locked 报错)
            assert len(results) == 50
            assert all(r is True for r in results)

            with db.get_connection() as conn:
                final_count = conn.execute("SELECT COUNT(*) FROM conversation_logs").fetchone()[0]

            # 断言数据表精确新增 50 行
            assert final_count == initial_count + 50, (
                f"Expected {initial_count + 50} rows, but found {final_count} (delta: {final_count - initial_count})"
            )
        finally:
            with db.get_connection() as conn:
                conn.execute("DELETE FROM conversation_logs WHERE session_id LIKE ?", (f"async_test_{test_run_id}_%",))
                conn.commit()

    asyncio.run(_run())

def test_async_buyer_profile_concurrent_rw():
    """测试异步买家画像跨会话并发读写"""
    async def _run():
        run_tag = uuid.uuid4().hex[:8]
        async def profile_worker(idx: int):
            session_id = f"test_async_profile_{run_tag}_{idx}"
            profile = BuyerProfile(
                budget_max=6000.0 + idx * 100,
                identity="学生",
                use_cases=[f"用途_{idx}"]
            )
            ok = await db.async_save_buyer_profile(session_id, profile)
            assert ok is True

            read_back = await db.async_get_buyer_profile(session_id)
            assert read_back is not None
            assert read_back.budget_max == 6000.0 + idx * 100
            assert f"用途_{idx}" in read_back.use_cases
            return True

        try:
            tasks = [profile_worker(i) for i in range(15)]
            results = await asyncio.gather(*tasks)
            assert len(results) == 15
            assert all(r is True for r in results)
        finally:
            with db.get_connection() as conn:
                conn.execute("DELETE FROM buyer_profiles WHERE session_id LIKE ?", (f"test_async_profile_{run_tag}_%",))
                conn.commit()

    asyncio.run(_run())

