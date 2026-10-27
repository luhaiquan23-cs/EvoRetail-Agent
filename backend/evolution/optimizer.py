import logging
from typing import Dict, Any, Optional
from backend.core.database import db
from backend.core.context_manager import context_manager
from backend.eval.harness import evaluation_harness
from backend.evolution.critic import critic_agent

logger = logging.getLogger("optimizer")

class OptimizerAgent:
    """
    Prompt 补丁生成与版本热发布演化器 (Optimizer)
    结合 Critic 诊断结果与沙箱跑分，闭环实现真实 Prompt 增量补丁生成、落库热更新与版本秒级回滚
    具备严格的 A/B 基线对比门禁：只有候选版本跑分超越基准且无劣化时才允许上线，拒绝负向演进
    """
    def __init__(self):
        # 启动时从数据库同步当前激活的 Prompt 版本与全文
        active_ver, active_prompt = db.get_active_prompt()
        context_manager.update_active_prompt(active_ver, active_prompt)

    async def optimize_and_evaluate(
        self,
        patch_note: Optional[str] = None,
        candidate_prompt_override: Optional[str] = None,
        sample_size: int = 50,
        min_improvement: float = 1.5
    ) -> Dict[str, Any]:
        """
        结合 Critic 诊断归因生成候选 Prompt 增量补丁，并在沙箱中对 Baseline 与 Candidate 进行 A/B 对比评测
        """
        current_version = context_manager.prompt_version
        current_active_prompt = context_manager.active_system_prompt

        parts = current_version.lstrip("v").split(".")
        major = parts[0] if len(parts) > 0 else "2"
        minor = parts[1] if len(parts) > 1 else "0"
        patch = int(parts[2]) if len(parts) > 2 and parts[2].isdigit() else 0
        candidate_version = f"v{major}.{minor}.{patch + 1}"

        # 1. 首先评测当前 Baseline 基线版本的跑分与细项表现
        baseline_report = await evaluation_harness.run_sandbox(
            concurrency=20,
            sample_size=sample_size,
            force_mock=True
        )
        baseline_score = baseline_report["overall_score"]
        baseline_breakdown = baseline_report["breakdown"]

        # 2. 准备候选版本 Prompt 全文
        if candidate_prompt_override:
            candidate_prompt = candidate_prompt_override
            effective_note = patch_note or "自定义候选 Prompt 演进验证"
        else:
            # 调用 Critic 诊断近期买家会话流失卡点，生成增量补丁
            diag_report = critic_agent.analyze_recent_conversations(limit=50)
            recommendations = diag_report.get("actionable_prompt_recommendations", [])
            effective_note = patch_note or (
                "；".join(recommendations) if recommendations else "强化SPIN促单反问与晒单赠品引导"
            )
            base_prompt = context_manager.DEFAULT_SYSTEM_CORE
            candidate_prompt = (
                f"{base_prompt}\n\n"
                f"【自进化增量策略补丁 ({candidate_version})】\n"
                f"- 针对近期会话流失归因优化：{effective_note}"
            )

        # 3. 临时切换为候选 Prompt 进行相同样本量的沙箱回归评测
        context_manager.update_active_prompt(candidate_version, candidate_prompt)
        candidate_report = await evaluation_harness.run_sandbox(
            concurrency=20,
            sample_size=sample_size,
            force_mock=True
        )
        candidate_score = candidate_report["overall_score"]
        candidate_breakdown = candidate_report["breakdown"]

        # 4. 严格 A/B 基线对比门禁判定：
        # - 零容忍红线违规数必须为 0
        # - 候选版本得分超越基线至少 min_improvement (+1.5分)
        # - 硬件断言率、风控率、SPIN得分各项细分维度均不能发生明显负向劣化 (允许 ≤0.5% 浮动)
        score_diff = round(candidate_score - baseline_score, 2)
        zero_violations = candidate_report["zero_tolerance_violations"] == 0

        hw_ok = candidate_breakdown["hardware_assert_pass_rate"] >= (baseline_breakdown["hardware_assert_pass_rate"] - 0.5)
        rc_ok = candidate_breakdown["risk_control_pass_rate"] >= (baseline_breakdown["risk_control_pass_rate"] - 0.5)
        spin_ok = candidate_breakdown["spin_average_score"] >= (baseline_breakdown["spin_average_score"] - 0.5)

        # 特例：若基线本身已达到 98 分以上接近天花板，且候选版同样保持满分或近乎满分无任何违规
        is_ceiling_plateau = (baseline_score >= 98.0 and candidate_score >= 98.0 and score_diff >= 0.0)

        gatekeeper_approved = zero_violations and (score_diff >= min_improvement or is_ceiling_plateau) and hw_ok and rc_ok and spin_ok

        # 5. 门禁处置
        if gatekeeper_approved:
            # 候选版本表现超越基线，落库持久化并真正激活上线
            with db.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                INSERT INTO prompt_versions (version, system_prompt, eval_score, is_active)
                VALUES (?, ?, ?, 1)
                ON CONFLICT(version) DO UPDATE SET
                    system_prompt=excluded.system_prompt,
                    eval_score=excluded.eval_score,
                    is_active=1
                """, (candidate_version, candidate_prompt, candidate_score))
                cursor.execute("UPDATE prompt_versions SET is_active=0 WHERE version != ?", (candidate_version,))
                conn.commit()

            # 完整记录到 evolution_runs 审计表
            db.log_evolution_run(
                baseline_version=current_version,
                candidate_version=candidate_version,
                baseline_score=baseline_score,
                candidate_score=candidate_score,
                score_diff=score_diff,
                zero_tolerance_violations=candidate_report["zero_tolerance_violations"],
                patch_note=effective_note,
                approved=True,
                rejection_reason=None
            )

            return {
                "status": "APPROVED",
                "new_version": candidate_version,
                "previous_version": current_version,
                "baseline_score": baseline_score,
                "candidate_score": candidate_score,
                "score_improvement": score_diff,
                "zero_tolerance_violations": candidate_report["zero_tolerance_violations"],
                "patch_note": effective_note,
                "action": "AUTO_DEPLOYED_TO_ONLINE",
                "baseline_report": baseline_report,
                "candidate_report": candidate_report
            }
        else:
            # 未通过门禁或发生负向劣化：立即拒绝上线并自动回滚运行时的 Prompt
            context_manager.update_active_prompt(current_version, current_active_prompt)
            rejection_reasons = []
            if not zero_violations:
                rejection_reasons.append(f"触发零容忍违规 ({candidate_report['zero_tolerance_violations']}次)")
            if score_diff < min_improvement and not is_ceiling_plateau:
                rejection_reasons.append(f"提分幅度不足 ({score_diff:+.2f}分 < +{min_improvement}分)")
            if not hw_ok:
                rejection_reasons.append("硬件断言通过率负向劣化")
            if not rc_ok:
                rejection_reasons.append("风控合规通过率负向劣化")
            if not spin_ok:
                rejection_reasons.append("SPIN 推进平均得分负向劣化")

            rejection_reason_str = "；".join(rejection_reasons) or "未达到上线门禁综合阈值"

            # 完整记录到 evolution_runs 审计表
            db.log_evolution_run(
                baseline_version=current_version,
                candidate_version=candidate_version,
                baseline_score=baseline_score,
                candidate_score=candidate_score,
                score_diff=score_diff,
                zero_tolerance_violations=candidate_report["zero_tolerance_violations"],
                patch_note=effective_note,
                approved=False,
                rejection_reason=rejection_reason_str
            )

            return {
                "status": "REJECTED",
                "current_version": current_version,
                "candidate_version": candidate_version,
                "baseline_score": baseline_score,
                "candidate_score": candidate_score,
                "score_improvement": score_diff,
                "rejection_reason": rejection_reason_str,
                "zero_tolerance_violations": candidate_report["zero_tolerance_violations"],
                "action": "REJECTED_ROLLBACK",
                "baseline_report": baseline_report,
                "candidate_report": candidate_report
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
