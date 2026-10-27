import json
import os
import pytest
from backend.guardrails.output_guard import output_guardrail
from backend.core.database import db

def test_numeric_guard_on_benchmark_cases():
    """
    验收标准：
    在 data/guard_numeric_cases.json（≥30 条正反例）上，
    参数造假反例拦截率 100%，正例误杀率 0%
    """
    cases_path = os.path.join(os.path.dirname(__file__), "../data/guard_numeric_cases.json")
    with open(cases_path, "r", encoding="utf-8") as f:
        cases = json.load(f)

    assert len(cases) >= 30, f"Expected at least 30 test cases, found {len(cases)}"

    positives = [c for c in cases if not c.get("is_negative", False)]
    negatives = [c for c in cases if c.get("is_negative", False)]

    assert len(positives) >= 10, f"Expected at least 10 positive cases, got {len(positives)}"
    assert len(negatives) >= 10, f"Expected at least 10 negative cases, got {len(negatives)}"

    # 1. 验证反例（造假参数）拦截率 100%
    intercepted_negatives = 0
    negative_failures = []

    for case in negatives:
        spu_code = case["spu_code"]
        product = db.get_product(spu_code)
        assert product is not None, f"Product {spu_code} must exist in DB!"

        sanitized, events = output_guardrail.guard_text(
            case["input_text"],
            spu_code=spu_code,
            product=product
        )

        if len(events) > 0 and sanitized != case["input_text"]:
            intercepted_negatives += 1
            if "expected_conflict_rule" in case:
                actual_rules = [e["rule_name"] for e in events]
                assert case["expected_conflict_rule"] in actual_rules, (
                    f"Expected rule {case['expected_conflict_rule']} but got {actual_rules}"
                )
        else:
            negative_failures.append({
                "spu": spu_code,
                "input": case["input_text"],
                "description": case.get("description")
            })

    negative_recall = (intercepted_negatives / len(negatives)) * 100.0
    print(f"\n[Negative Recall] {intercepted_negatives}/{len(negatives)} ({negative_recall:.2f}%)")
    assert negative_recall == 100.0, f"Negative recall failed: {negative_failures}"

    # 2. 验证正例（正确参数）误杀率 0%
    false_positives = []
    for case in positives:
        spu_code = case["spu_code"]
        product = db.get_product(spu_code)
        assert product is not None, f"Product {spu_code} must exist in DB!"

        sanitized, events = output_guardrail.guard_text(
            case["input_text"],
            spu_code=spu_code,
            product=product
        )

        if len(events) > 0 or sanitized != case["input_text"]:
            false_positives.append({
                "spu": spu_code,
                "input": case["input_text"],
                "events": events,
                "sanitized": sanitized
            })

    false_positive_rate = (len(false_positives) / len(positives)) * 100.0
    print(f"[False Positive Rate] {len(false_positives)}/{len(positives)} ({false_positive_rate:.2f}%)")
    assert false_positive_rate == 0.0, f"False positives detected: {false_positives}"

    # 沉淀评测证据文件
    evidence_dir = os.path.join(os.path.dirname(__file__), "../docs/evidence")
    os.makedirs(evidence_dir, exist_ok=True)
    evidence_path = os.path.join(evidence_dir, "guard_numeric_accuracy.json")
    with open(evidence_path, "w", encoding="utf-8") as f:
        json.dump({
            "total_cases": len(cases),
            "negative_cases": len(negatives),
            "positive_cases": len(positives),
            "negative_interception_rate": negative_recall,
            "false_positive_rate": false_positive_rate,
            "status": "PASSED_100_PERCENT"
        }, f, ensure_ascii=False, indent=2)

