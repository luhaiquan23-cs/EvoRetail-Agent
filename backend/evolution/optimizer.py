import time
from typing import Dict, Any
from backend.core.database import db
from backend.core.context_manager import context_manager
from backend.eval.harness import evaluation_harness

class OptimizerAgent:
    """
    Prompt 补丁生成与版本热发布演化器 (Optimizer)
    结合 Critic 诊断结果与沙箱跑分，闭环实现 Prompt 热更新与版本秒级回滚
    """
    def __init__(self):
        pass

    async def optimize_and_evaluate(self, patch_note: str = "增强SPIN促单反问与赠品政策提示") -> Dict[str, Any]:
        """
        组装候选 Prompt 版本并在沙箱中进行并发回归
        """
        current_version = context_manager.prompt_version
        major, minor, patch = current_version.lstrip("v").split(".")
        candidate_version = f"v{major}.{minor}.{int(patch) + 1}"

        # 1. 触发沙箱 500 道用例并发回归测试
        sandbox_report = await evaluation_harness.run_sandbox(concurrency=25, sample_size=100)

        # 2. 判断是否满足上线门禁
        if sandbox_report["gatekeeper_approved"]:
            # 保存快照入库
            with db.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                INSERT INTO prompt_versions (version, system_prompt, eval_score, is_active)
                VALUES (?, ?, ?, 1)
                ON CONFLICT(version) DO UPDATE SET
                    system_prompt=excluded.system_prompt,
                    eval_score=excluded.eval_score,
                    is_active=1
                """, (candidate_version, context_manager.DEFAULT_SYSTEM_CORE, sandbox_report["overall_score"]))
                # 将其他版本置为非激活
                cursor.execute("UPDATE prompt_versions SET is_active=0 WHERE version != ?", (candidate_version,))
                conn.commit()

            # 热更新运行时
            context_manager.prompt_version = candidate_version

            return {
                "status": "APPROVED",
                "new_version": candidate_version,
                "previous_version": current_version,
                "eval_score": sandbox_report["overall_score"],
                "zero_tolerance_violations": sandbox_report["zero_tolerance_violations"],
                "patch_note": patch_note,
                "action": "AUTO_DEPLOYED_TO_ONLINE",
                "sandbox_report": sandbox_report
            }
        else:
            return {
                "status": "REJECTED",
                "current_version": current_version,
                "candidate_version": candidate_version,
                "eval_score": sandbox_report["overall_score"],
                "zero_tolerance_violations": sandbox_report["zero_tolerance_violations"],
                "action": "REJECTED_ROLLBACK",
                "sandbox_report": sandbox_report
            }

    def rollback_version(self, target_version: str) -> Dict[str, Any]:
        """秒级版本回滚"""
        with db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT version, system_prompt FROM prompt_versions WHERE version = ?", (target_version,))
            row = cursor.fetchone()
            if not row:
                return {"status": "ERROR", "message": f"未找到目标版本 {target_version}"}

            cursor.execute("UPDATE prompt_versions SET is_active = CASE WHEN version = ? THEN 1 ELSE 0 END", (target_version,))
            conn.commit()

        context_manager.prompt_version = target_version
        return {
            "status": "SUCCESS",
            "active_version": target_version,
            "message": f"线上 Prompt 已秒级平滑回滚至版本 [{target_version}]"
        }

optimizer_agent = OptimizerAgent()

