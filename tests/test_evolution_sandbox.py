import os
import sys
import pytest
import asyncio

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from fastapi.testclient import TestClient
from backend.api.server import app
from backend.eval.assertions import assert_hardware_specs, assert_risk_control, score_spin_progression
from backend.eval.harness import evaluation_harness
from backend.evolution.critic import critic_agent
from backend.evolution.optimizer import optimizer_agent

def test_assertions():
    # 1. 硬件断言
    sample_text = "光影精灵16配备双 M.2 插槽，支持加装第二根固态，显卡具备 140W 满血释放！"
    ok, msg = assert_hardware_specs(sample_text, {
        "must_include": ["双 M.2|2个 M.2", "140W"],
        "must_exclude": ["不支持加装", "120W"]
    })
    assert ok, f"Hardware assertion failed: {msg}"

    bad_text = "这款光影精灵不支持加装固态，显卡只有 120W。"
    bad_ok, _ = assert_hardware_specs(bad_text, {
        "must_include": ["双 M.2"],
        "must_exclude": ["不支持加装"]
    })
    assert not bad_ok, "Should fail on wrong specs"

    # 2. 违禁词红线
    safe_text = "我们保证提供正品行货与全国联保服务。"
    risk_ok, _ = assert_risk_control(safe_text)
    assert risk_ok

    risky_text = "亲，好评返现 50 元，加微信转账给您！"
    risk_failed, risk_msg = assert_risk_control(risky_text)
    assert not risk_failed
    assert "违规词" in risk_msg

    # 3. SPIN 打分
    spin_text = "这款显卡为 140W 满血释放，主流 3A 大作高画质流畅运行！请问您平时主要玩哪些游戏呢？"
    score, _ = score_spin_progression(spin_text, ["140W|满血", "3A|游戏", "哪些游戏|用途"])
    assert score >= 90.0
    print("[PASS] Assertion rules verified.")

def test_sandbox_harness():
    report = asyncio.run(evaluation_harness.run_sandbox(concurrency=20, sample_size=30))
    assert report["total_cases"] == 30
    assert report["zero_tolerance_violations"] == 0
    assert report["overall_score"] >= 95.0
    assert report["gatekeeper_approved"] is True
    print(f"[PASS] Sandbox harness run: Score={report['overall_score']}, Approved={report['gatekeeper_approved']}")

def test_critic_and_optimizer():
    diag = critic_agent.analyze_recent_conversations(limit=20)
    assert "loss_categories" in diag
    assert "actionable_prompt_recommendations" in diag
    print("[PASS] Critic agent diagnosis verified.")

    # 测试版本回滚
    rollback_res = optimizer_agent.rollback_version("v2.0.0")
    assert rollback_res["status"] == "SUCCESS"
    assert rollback_res["active_version"] == "v2.0.0"
    print("[PASS] Optimizer rollback verified.")

def test_evolution_api():
    client = TestClient(app)
    # 验证沙箱运行接口
    res = client.post("/api/v1/evolution/run-sandbox", json={"concurrency": 15, "sample_size": 20})
    assert res.status_code == 200
    data = res.json()["data"]
    assert data["status"] == "SUCCESS"
    assert data["gatekeeper_approved"] is True

    # 验证诊断接口
    res_diag = client.post("/api/v1/evolution/diagnose")
    assert res_diag.status_code == 200
    assert "loss_categories" in res_diag.json()["data"]

    # 验证版本列表
    res_ver = client.get("/api/v1/evolution/versions")
    assert res_ver.status_code == 200
    print("[PASS] Evolution API endpoints verified.")

if __name__ == "__main__":
    test_assertions()
    test_sandbox_harness()
    test_critic_and_optimizer()
    test_evolution_api()
    print("\n[ALL PASS] Golden dataset evaluation & evolution verified successfully!")

