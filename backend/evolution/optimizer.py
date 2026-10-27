from typing import Dict, Any
from backend.core.database import db
from backend.core.context_manager import context_manager
from backend.eval.harness import evaluation_harness
from backend.evolution.critic import critic_agent


class OptimizerAgent:
    """
    Prompt 补丁生成与版本热发布演化器 (Optimizer)
    结合 Critic 诊断结果与沙箱跑分，闭环实现真实 Prompt 增量补丁生成、落库热更新与版本秒级回滚
    """
    def __init__(self):
        # 启动时从数据库同步当前激活的 Prompt 版本与全文
        active_ver, active_prompt = db.get_active_prompt()
        context_manager.update_active_prompt(active_ver, active_prompt)

    async def optimize_and_evaluate(self, patch_note: str = None) -> Dict[str, Any]:
        """
        结合 Critic 诊断归因生成候选 Prompt 增量补丁，并在沙箱中进行高并发回归
        """
        current_version = context_manager.prompt_version
        parts = current_version.lstrip("v").split(".")
        major = parts[0] if len(parts) > 0 else "2"
        minor = parts[1] if len(parts) > 1 else "0"
        patch = int(parts[2]) if len(parts) > 2 and parts[2].isdigit() else 0
        candidate_version = f"v{major}.{minor}.{patch + 1}"

        # 1. 调用 Critic 诊断近期买家会话流失卡点，生成真实增量补丁
        diag_report = critic_agent.analyze_recent_conversations(limit=50)
        recommendations = diag_report.get("actionable_prompt_recommendations", [])
        effective_note = patch_note or (
            "；".join(recommendations) if recommendations else "强化SPIN促单反问与晒单赠品引导"
        )

        # 基于基础核心 Prompt 构建包含增量策略补丁的新版 System Prompt 全文
        base_prompt = context_manager.DEFAULT_SYSTEM_CORE
        candidate_prompt = (
            f"{base_prompt}\n\n"
            f"【自进化增量策略补丁 ({candidate_version})】\n"
            f"- 针对近期会话流失归因优化：{effective_note}"
        )

        # 临时切换候选 Prompt 进行沙箱 500 道金标回归测试
        previous_prompt = context_manager.active_system_prompt
        context_manager.update_active_prompt(candidate_version, candidate_prompt)

        sandbox_report = await evaluation_harness.run_sandbox(concurrency=25, sample_size=100)

        # 2. 判断是否满足上线门禁
        if sandbox_report["gatekeeper_approved"]:
            # 保存真实候选 Prompt 全文快照入库并激活
            with db.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                INSERT INTO prompt_versions (version, system_prompt, eval_score, is_active)
                VALUES (?, ?, ?, 1)
                ON CONFLICT(version) DO UPDATE SET
                    system_prompt=excluded.system_prompt,
                    eval_score=excluded.eval_score,
                    is_active=1
                """, (candidate_version, candidate_prompt, sandbox_report["overall_score"]))
                cursor.execute("UPDATE prompt_versions SET is_active=0 WHERE version != ?", (candidate_version,))
                conn.commit()

            return {
                "status": "APPROVED",
                "new_version": candidate_version,
                "previous_version": current_version,
                "eval_score": sandbox_report["overall_score"],
                "zero_tolerance_violations": sandbox_report["zero_tolerance_violations"],
                "patch_note": effective_note,
                "action": "AUTO_DEPLOYED_TO_ONLINE",
                "sandbox_report": sandbox_report
            }
        else:
            # 未通过门禁，立即回退内存中的 Prompt
            context_manager.update_active_prompt(current_version, previous_prompt)
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
        """秒级版本回滚（同时回滚数据库状态与运行时生效的 System Prompt 文本）"""
        with db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT version, system_prompt FROM prompt_versions WHERE version = ?", (target_version,))
            row = cursor.fetchone()
            if not row:
                return {"status": "ERROR", "message": f"未找到目标版本 {target_version}"}

            cursor.execute("UPDATE prompt_versions SET is_active = CASE WHEN version = ? THEN 1 ELSE 0 END", (target_version,))
            conn.commit()

        # 真正将运行时激活的 Prompt 文本切换为目标版本的 system_prompt
        context_manager.update_active_prompt(target_version, row["system_prompt"])
        return {
            "status": "SUCCESS",
            "active_version": target_version,
            "message": f"线上 Prompt 已秒级平滑回滚至版本 [{target_version}]"
        }


optimizer_agent = OptimizerAgent()
