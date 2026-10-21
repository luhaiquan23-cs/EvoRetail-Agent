import sqlite3
from typing import List, Dict, Any
from backend.core.database import db

class CriticAgent:
    """
    离线流失诊断分析 Agent (Critic)
    分析真实买家会话日志，挖掘流失卡点与话术改进建议
    """
    def __init__(self):
        pass

    def analyze_recent_conversations(self, limit: int = 50) -> Dict[str, Any]:
        """拉取最近会话记录并执行流失归因诊断"""
        with db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
            SELECT session_id, spu_code, user_query, agent_response, prompt_version, cost_ms, created_at
            FROM conversation_logs
            ORDER BY id DESC
            LIMIT ?
            """, (limit,))
            rows = cursor.fetchall()

        total_analyzed = len(rows)
        diagnoses = []
        loss_categories = {
            "HARDWARE_UNCERTAINTY": 0,
            "PRICE_HESITATION": 0,
            "SPIN_MISSED_RECOMMENDATION": 0,
            "SMOOTH_CONVERSION": 0
        }

        for r in rows:
            query = r["user_query"]
            response = r["agent_response"]

            # 诊断卡点分类
            if "贵" in query or "便宜" in query or "优惠" in query:
                loss_categories["PRICE_HESITATION"] += 1
                suggestion = "买家表现出价格敏感，建议引导晒单赠送双肩包+鼠标等高价值赠品策略"
            elif "能不能玩" in query or "卡不卡" in query:
                loss_categories["HARDWARE_UNCERTAINTY"] += 1
                suggestion = "买家对游戏性能存在疑虑，建议强化 140W 满血显卡跑分与主流 3A 帧率实测数据"
            elif len(response) > 50 and not any(k in response for k in ["推荐", "建议", "您打算", "主要用于"]):
                loss_categories["SPIN_MISSED_RECOMMENDATION"] += 1
                suggestion = "回复仅单向解答了参数，缺少 SPIN 促单反问，建议追加场景需求探寻"
            else:
                loss_categories["SMOOTH_CONVERSION"] += 1
                suggestion = "会话解答完整且包含场景推荐"

            diagnoses.append({
                "session_id": r["session_id"],
                "spu_code": r["spu_code"],
                "query": query,
                "suggestion": suggestion
            })

        return {
            "total_analyzed": total_analyzed,
            "loss_categories": loss_categories,
            "sample_diagnoses": diagnoses[:5],
            "actionable_prompt_recommendations": [
                "针对价格犹豫客户，主动强调晒单赠送 399 元电竞外设大礼包",
                "对满血性能疑问，强化 140W 与主流 3A 大作高画质流畅说明",
                "在每次硬件参数解答后，增加一句场景用途反问（如：'您主要玩哪些游戏呢？'）"
            ]
        }

critic_agent = CriticAgent()

