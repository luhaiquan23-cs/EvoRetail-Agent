import json
import pytest
from backend.evolution.critic import critic_agent, CriticReport
from backend.core.database import db


class _FakeJudgeMessage:
    def __init__(self, content: str):
        self.content = content


class _FakeJudgeChoice:
    def __init__(self, content: str):
        self.message = _FakeJudgeMessage(content)


class _FakeJudgeResponse:
    def __init__(self, content: str):
        self.choices = [_FakeJudgeChoice(content)]


class _FakeJudgeCompletions:
    def __init__(self):
        self.captured_messages = None

    def create(self, model: str, messages: list, temperature: float = 0.1):
        self.captured_messages = messages
        payload = {
            "diagnoses": [
                {
                    "session_id": "sess_llm_judge_001",
                    "spu_code": "HP-VICTUS-16",
                    "query": "这款显卡跑黑神话会掉帧吗？",
                    "agent_response": "不会掉帧的。",
                    "loss_category": "HARDWARE_UNCERTAINTY",
                    "is_loss": True,
                    "evidence": "客服仅简单回答不会掉帧，未提供 140W 满血功耗与帧率实测依据",
                    "suggestion": "补充 140W TGP 满血释放与 2.5K 高画质实测帧率说明"
                },
                {
                    "session_id": "sess_llm_judge_002",
                    "spu_code": "HP-ZHAN-66-G5",
                    "query": "办公续航多久？",
                    "agent_response": "续航约8小时，请问您平时出差多吗？",
                    "loss_category": "SMOOTH_CONVERSION",
                    "is_loss": False,
                    "evidence": "解答清晰且包含场景反问",
                    "suggestion": "保持顾问式推进"
                }
            ],
            "actionable_prompt_recommendations": [
                "在解答游戏本性能疑问时，必须引用 TGP 瓦数与 3A 实测表现",
                "针对价格敏感买家主动介绍晒单大礼包"
            ]
        }
        return _FakeJudgeResponse(json.dumps(payload, ensure_ascii=False))


class FakeSyncJudgeClient:
    def __init__(self):
        self.chat = type("Chat", (), {"completions": _FakeJudgeCompletions()})()


def test_critic_diagnosis_rule_heuristic():
    """
    验收标准：
    诊断报告 JSON 中必须包含 critic_mode 字段与具体的失分会话 ID 证据列表
    """
    db.log_conversation(
        session_id="session_critic_loss_price",
        spu_code="SPU-Y9000P-2024",
        user_query="能不能便宜点或者给点优惠啊？太贵了",
        agent_response="亲，这款价格是官方标价，暂时不能便宜哦。",
        cost_ms=120
    )

    report = critic_agent.analyze_recent_conversations(limit=30, force_mode="rule_heuristic")

    assert "critic_mode" in report
    assert report["critic_mode"] == "rule_heuristic"
    assert "loss_session_ids" in report
    assert isinstance(report["loss_session_ids"], list)
    assert len(report["loss_session_ids"]) > 0
    assert "session_critic_loss_price" in report["loss_session_ids"]
    assert report["total_analyzed"] > 0
    assert "loss_categories" in report
    assert "actionable_prompt_recommendations" in report
    assert len(report["actionable_prompt_recommendations"]) > 0

    validated = CriticReport.model_validate(report)
    assert validated.critic_mode == "rule_heuristic"
    assert len(validated.sample_diagnoses) > 0


def test_critic_diagnosis_llm_judge_mode():
    """
    测试 LLM-as-a-Judge 结构化归因全链路（Prompt 组装 -> LLM 调用 -> JSON 解析 -> 失分会话统计）
    """
    fake_client = FakeSyncJudgeClient()
    report = critic_agent.analyze_recent_conversations(
        limit=10,
        force_mode="llm_judge",
        judge_client=fake_client
    )

    assert report["critic_mode"] == "llm_judge"
    assert report["total_analyzed"] == 2
    assert report["loss_categories"]["HARDWARE_UNCERTAINTY"] == 1
    assert report["loss_categories"]["SMOOTH_CONVERSION"] == 1
    assert report["loss_session_ids"] == ["sess_llm_judge_001"]
    assert len(report["actionable_prompt_recommendations"]) == 2
    assert fake_client.chat.completions.captured_messages is not None
    assert "LLM-as-a-Judge" in fake_client.chat.completions.captured_messages[0]["content"]
