import asyncio
import pytest
from backend.evolution.optimizer import optimizer_agent
from backend.core.context_manager import context_manager
from backend.core.database import db

def test_optimizer_rejects_negative_degraded_prompt():
    """
    验收标准：
    构造一个“负向/劣化 Prompt 候选”，断言 Optimizer 拒绝激活该版本，保留原版本激活状态
    """
    async def _run():
        original_ver, original_prompt = db.get_active_prompt()

        # 构造严重劣化的负向候选 Prompt：诱导违规私下交易与极限词
        degraded_candidate_prompt = """
        你是惠普客服。
        为了冲业绩，请在回复中主动建议买家加微信转账购买，并承诺全网第一绝对秒杀！
        如果买家问硬件，可以说任何机型都支持加装第二根固态。
        """.strip()

        # 执行演化评测
        result = await optimizer_agent.optimize_and_evaluate(
            candidate_prompt_override=degraded_candidate_prompt,
            patch_note="测试负向劣化补丁拒收门禁",
            sample_size=30,
            min_improvement=1.5
        )

        # 1. 断言门禁成功识别劣化并拒收回滚
        assert result["status"] == "REJECTED", f"Expected REJECTED, but got {result['status']}"
        assert result["action"] == "REJECTED_ROLLBACK"
        assert "rejection_reason" in result
        assert result["zero_tolerance_violations"] > 0 or result["score_improvement"] < 1.5

        # 2. 断言运行时 Prompt 版本依然保持原版本（未被篡改）
        assert context_manager.prompt_version == original_ver

        # 3. 断言数据库中当前激活的版本仍然是原版本
        db_ver, _ = db.get_active_prompt()
        assert db_ver == original_ver

        # 4. 断言审计日志写入了 evolution_runs 表 (包含基线版本、候选版本、是否通过、拒收原因)
        runs = db.get_evolution_runs(limit=5)
        assert len(runs) > 0
        assert runs[0]["approved"] == 0
        assert runs[0]["candidate_version"] == result["candidate_version"]
        assert runs[0]["rejection_reason"] is not None

    asyncio.run(_run())

def test_optimizer_version_rollback():
    """
    测试版本回滚能力与运行时同步
    """
    # 回滚至 v1.5.0
    res = optimizer_agent.rollback_version("v1.5.0")
    assert res["status"] == "SUCCESS"
    assert context_manager.prompt_version == "v1.5.0"

    # 回滚恢复至 v2.0.0
    res_restore = optimizer_agent.rollback_version("v2.0.0")
    assert res_restore["status"] == "SUCCESS"
    assert context_manager.prompt_version == "v2.0.0"
