import os
import sys
import json
import time
import argparse
import asyncio
from typing import Dict, Any, List

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from backend.agent.runner import agent_runner
from backend.agent.tools import resolve_spu
from backend.core.llm_client import llm_adapter

CASES_PATH = os.path.join(os.path.dirname(__file__), "../data/tool_routing_cases.json")
EVIDENCE_DIR = os.path.join(os.path.dirname(__file__), "../docs/evidence")

async def evaluate_tool_routing(mode: str = "mock") -> Dict[str, Any]:
    with open(CASES_PATH, "r", encoding="utf-8") as f:
        cases = json.load(f)

    force_mock = (mode == "mock")
    if mode == "live":
        client = llm_adapter.get_client()
        if not client:
            print("[WARN] LLM API Key 未配置，无法以 Live 模式运行，请在 .env 配置 LLM_API_KEY。")
            return {
                "error": "LLM_API_KEY_NOT_CONFIGURED",
                "message": "Live 模式需要有效的大模型 API Key",
                "mode": "live",
                "timestamp": time.strftime("%Y-%m-%d %H:%M:%S")
            }

    results = []
    correct_count = 0

    print(f"[*] 开始执行工具路由评测: 模式={mode}, 样本量={len(cases)} ...")
    start_time = time.time()

    for c in cases:
        query = c["query"]
        expected = c["expected_tool"]
        spu_cand = resolve_spu(query)

        messages = [{"role": "user", "content": query}]
        tools_called = []

        try:
            async for ev in agent_runner.run(
                messages=messages,
                spu_code=spu_cand,
                force_mock=force_mock
            ):
                if ev.get("type") == "tool_call":
                    tools_called.append(ev["tool_name"])
        except Exception as e:
            print(f"[!] Case {c['id']} run failed: {e}")

        # 判断是否命中了期望工具
        is_correct = (expected in tools_called)
        if is_correct:
            correct_count += 1

        results.append({
            "id": c["id"],
            "query": query,
            "expected_tool": expected,
            "actual_tools": tools_called,
            "is_correct": is_correct
        })

    total = len(cases)
    accuracy = round((correct_count / total) * 100, 2)
    duration = round(time.time() - start_time, 2)

    report = {
        "mode": mode,
        "llm_model": llm_adapter.model if mode == "live" else "Local_Intent_Tool_Router",
        "sample_size": total,
        "correct_count": correct_count,
        "accuracy_pct": accuracy,
        "duration_seconds": duration,
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "mismatches": [r for r in results if not r["is_correct"]]
    }

    os.makedirs(EVIDENCE_DIR, exist_ok=True)
    report_path = os.path.join(EVIDENCE_DIR, f"tool_routing_{mode}.json")
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    print(f"[OK] 评测完成! 准确率: {accuracy}% ({correct_count}/{total}), 耗时: {duration}s")
    print(f"[OK] 证据文件已归档至: {report_path}")
    return report

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Tool Routing Evaluation")
    parser.add_argument("--mode", choices=["mock", "live"], default="mock", help="运行模式")
    args = parser.parse_args()

    asyncio.run(evaluate_tool_routing(mode=args.mode))

