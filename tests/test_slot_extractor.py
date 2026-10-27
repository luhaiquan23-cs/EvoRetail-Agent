import os
import sys
import json
import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from backend.agent.slot_extractor import slot_extractor

CASES_PATH = os.path.join(os.path.dirname(__file__), "../data/slot_cases.json")
EVIDENCE_PATH = os.path.join(os.path.dirname(__file__), "../docs/evidence/slot_extraction_accuracy.json")

def test_slot_extractor_on_benchmark_cases():
    with open(CASES_PATH, "r", encoding="utf-8") as f:
        cases = json.load(f)

    total_fields = 0
    correct_fields = 0
    case_results = []

    for c in cases:
        query = c["query"]
        expected = c["expected"]
        profile = slot_extractor.extract_from_text(query)

        field_hits = {}
        for field, exp_val in expected.items():
            total_fields += 1
            if field == "budget_max":
                match = (profile.budget_max == exp_val)
            elif field == "budget_min":
                match = (profile.budget_min == exp_val)
            elif field == "identity":
                match = (profile.identity == exp_val)
            elif field == "portability_priority":
                match = (profile.portability_priority == exp_val)
            elif field == "candidate_spu":
                match = (exp_val in profile.candidate_spus)
            elif field == "use_cases":
                # 检查是否命中了至少一个期望的用途
                match = any(uc in profile.use_cases for uc in exp_val)
            else:
                match = False

            if match:
                correct_fields += 1
            field_hits[field] = {"expected": exp_val, "matched": match}

        case_results.append({
            "id": c["id"],
            "query": query,
            "field_hits": field_hits,
            "extracted_profile": profile.model_dump()
        })

    accuracy = round((correct_fields / total_fields) * 100, 2)
    print(f"\n[OK] Slot Extraction Accuracy: {accuracy}% ({correct_fields}/{total_fields} fields correct)")

    report = {
        "sample_size": len(cases),
        "total_fields": total_fields,
        "correct_fields": correct_fields,
        "accuracy_pct": accuracy,
        "results": case_results
    }
    os.makedirs(os.path.dirname(EVIDENCE_PATH), exist_ok=True)
    with open(EVIDENCE_PATH, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    assert accuracy >= 85.0, f"Slot extraction accuracy {accuracy}% below 85% threshold"


def test_slot_extractor_llm_hybrid_mode():
    """测试可选 LLM 结构化槽位抽取与规则融合双模式"""
    import asyncio

    class _FakeSlotCompletions:
        async def create(self, model: str, messages: list, temperature: float = 0.0):
            data = {
                "budget_min": 6000,
                "budget_max": 8500,
                "identity": "建筑系学生",
                "use_cases": ["Rhino犀牛建模", "Lumion渲染"],
                "portability_priority": False,
                "candidate_spus": ["HP-ZHAN-99-G5"]
            }
            msg = type("Msg", (), {"content": json.dumps(data, ensure_ascii=False)})()
            choice = type("Choice", (), {"message": msg})()
            return type("Resp", (), {"choices": [choice]})()

    fake_async_client = type("Client", (), {"chat": type("Chat", (), {"completions": _FakeSlotCompletions()})()})()

    async def _run():
        profile = await slot_extractor.extract_with_llm(
            "平时在工作室用Rhino画图，希望稳定一点",
            client=fake_async_client
        )
        assert profile.budget_max == 8500
        assert profile.identity == "建筑系学生"
        assert "Rhino犀牛建模" in profile.use_cases
        assert "HP-ZHAN-99-G5" in profile.candidate_spus

    asyncio.run(_run())


if __name__ == "__main__":
    test_slot_extractor_on_benchmark_cases()
    test_slot_extractor_llm_hybrid_mode()
    print("\n[ALL PASS] Slot extractor test passed successfully!")

