import os
import json
import time
import asyncio
from typing import Dict, Any, List
from backend.eval.assertions import assert_hardware_specs, assert_risk_control, score_spin_progression
from backend.core.database import db
from backend.core.context_manager import context_manager
from backend.rag.hybrid_retriever import hybrid_retriever
from backend.core.llm_client import llm_adapter

DATASET_PATH = os.path.join(os.path.dirname(__file__), "../../data/golden_dataset_500.json")

class EvaluationHarness:
    """
    500 道金标自动化评测并发沙箱 (Golden Dataset Harness)
    包含：硬件规格绝对断言、平台风控红线一票否决、SPIN 销售推进表现打分
    """
    def __init__(self, dataset_path: str = DATASET_PATH):
        self.dataset_path = dataset_path

    def load_dataset(self) -> List[Dict[str, Any]]:
        if not os.path.exists(self.dataset_path):
            raise FileNotFoundError(f"未找到金标评测集: {self.dataset_path}")
        with open(self.dataset_path, "r", encoding="utf-8") as f:
            return json.load(f)

    async def _evaluate_single_case(self, case: Dict[str, Any], prompt_version: str = "v2.0.0", force_mock: bool = True) -> Dict[str, Any]:
        case_type = case["case_type"]
        spu_code = case.get("spu_code")
        query = case["query"]
        expected = case["expected_asserts"]

        # 1. 模拟组装上下文与事实
        anchor_fact = None
        if spu_code:
            product = db.get_product(spu_code)
            if product:
                anchor_fact = product.to_anchor_fact()

        rag_context = hybrid_retriever.retrieve(query, top_k=1)

        messages = context_manager.assemble_messages(
            query=query,
            history=[],
            anchor_fact=anchor_fact,
            rag_context=rag_context
        )

        # 2. 生成回复 (直接调用 llm_adapter 生成)
        reply_tokens = []
        async for token in llm_adapter.stream_chat(messages, force_mock=force_mock):
            reply_tokens.append(token)
        response_text = "".join(reply_tokens)

        # 3. 执行断言判定
        passed = True
        violation_type = None
        score = 100.0
        reason = ""

        if case_type == "HARDWARE_ASSERT":
            ok, msg = assert_hardware_specs(response_text, expected)
            if not ok:
                passed = False
                violation_type = "HARDWARE_ASSERT_FAILED"
                score = 0.0
                reason = msg
            else:
                score = 100.0
                reason = "硬件参数绝对断言通过"

        elif case_type == "RISK_CONTROL":
            ok, msg = assert_risk_control(response_text, expected.get("banned_words"))
            if not ok:
                passed = False
                violation_type = "RISK_CONTROL_VIOLATION"
                score = 0.0
                reason = msg
            else:
                score = 100.0
                reason = "零违规红线通过"

        elif case_type == "SPIN_STAGE":
            spin_score, msg = score_spin_progression(response_text, expected.get("spin_signals", []))
            score = spin_score
            passed = spin_score >= 80.0
            reason = msg

        return {
            "id": case["id"],
            "case_type": case_type,
            "passed": passed,
            "score": score,
            "weight": case.get("weight", 1),
            "violation_type": violation_type,
            "reason": reason
        }

    async def run_sandbox(self, concurrency: int = 25, sample_size: int = None, force_mock: bool = True) -> Dict[str, Any]:
        """
        高并发驱动沙箱回归测试
        """
        start_time = time.time()
        cases = self.load_dataset()
        if sample_size and sample_size < len(cases):
            cases = cases[:sample_size]

        total_cases = len(cases)
        semaphore = asyncio.Semaphore(concurrency)

        async def run_with_sem(c):
            async with semaphore:
                return await self._evaluate_single_case(c, force_mock=force_mock)

        # 并发执行全部用例
        results = await asyncio.gather(*(run_with_sem(c) for c in cases))

        # 统计汇总
        passed_count = sum(1 for r in results if r["passed"])
        zero_tolerance_violations = sum(1 for r in results if r["violation_type"] is not None)

        total_weight = sum(r["weight"] for r in results)
        weighted_score_sum = sum(r["score"] * r["weight"] for r in results)
        overall_score = round(weighted_score_sum / total_weight, 2) if total_weight > 0 else 0.0

        # 门禁裁决判定
        gatekeeper_approved = (zero_tolerance_violations == 0) and (overall_score >= 95.0)

        action = "AUTO_DEPLOYED_TO_ONLINE" if gatekeeper_approved else "REJECTED_ROLLBACK"

        cost_duration = round(time.time() - start_time, 2)

        report = {
            "status": "SUCCESS" if gatekeeper_approved else "FAILED",
            "candidate_version": context_manager.prompt_version,
            "total_cases": total_cases,
            "passed_cases": passed_count,
            "zero_tolerance_violations": zero_tolerance_violations,
            "overall_score": overall_score,
            "gatekeeper_threshold": 95.0,
            "gatekeeper_approved": gatekeeper_approved,
            "action": action,
            "cost_seconds": cost_duration,
            "breakdown": {
                "hardware_assert_pass_rate": round(
                    sum(1 for r in results if r["case_type"] == "HARDWARE_ASSERT" and r["passed"]) /
                    max(1, sum(1 for r in results if r["case_type"] == "HARDWARE_ASSERT")) * 100, 1
                ),
                "risk_control_pass_rate": round(
                    sum(1 for r in results if r["case_type"] == "RISK_CONTROL" and r["passed"]) /
                    max(1, sum(1 for r in results if r["case_type"] == "RISK_CONTROL")) * 100, 1
                ),
                "spin_average_score": round(
                    sum(r["score"] for r in results if r["case_type"] == "SPIN_STAGE") /
                    max(1, sum(1 for r in results if r["case_type"] == "SPIN_STAGE")), 1
                )
            }
        }

        return report

evaluation_harness = EvaluationHarness()

if __name__ == "__main__":
    report = asyncio.run(evaluation_harness.run_sandbox(concurrency=20, sample_size=50))
    print(json.dumps(report, ensure_ascii=False, indent=2))

