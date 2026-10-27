import os
import sys
import json
import logging
from typing import List, Dict, Any, Optional
from pydantic import BaseModel, Field
from backend.core.database import db
from backend.core.llm_client import llm_adapter

logger = logging.getLogger("critic")

class SessionDiagnosis(BaseModel):
    session_id: str = Field(..., description="会话唯一ID")
    spu_code: Optional[str] = Field(None, description="咨询商品编码")
    query: str = Field(..., description="买家提问")
    agent_response: str = Field(..., description="客服回复")
    loss_category: str = Field(..., description="归因分类")
    suggestion: str = Field(..., description="改进建议")
    is_loss: bool = Field(False, description="是否属于流失会话")
    evidence: str = Field("", description="失分事实证据")

class CriticReport(BaseModel):
    critic_mode: str = Field(..., description="'llm_judge' 或 'rule_heuristic'")
    total_analyzed: int = Field(..., description="分析的会话总量")
    loss_categories: Dict[str, int] = Field(default_factory=dict, description="各类流失卡点统计")
    loss_session_ids: List[str] = Field(default_factory=list, description="具体的失分会话 ID 证据列表")
    sample_diagnoses: List[SessionDiagnosis] = Field(default_factory=list, description="诊断详情样本")
    actionable_prompt_recommendations: List[str] = Field(default_factory=list, description="可落地的 Prompt 增量策略建议")


CRITIC_JUDGE_SYSTEM_PROMPT = """你是一名资深 3C 数码电商客服质量审计专家 (LLM-as-a-Judge)。
请对以下买家咨询与客服回复日志进行逐条深度流失归因诊断，并严格输出 JSON 格式。
归因分类 (loss_category) 必须属于以下四类之一：
- PRICE_HESITATION: 买家对价格敏感、嫌贵或要求优惠，但客服未充分引导赠品或免息政策
- HARDWARE_UNCERTAINTY: 买家对显卡功耗、3A游戏帧率、散热或扩展槽位存疑，客服解答不够透彻
- SPIN_MISSED_RECOMMENDATION: 客服仅机械回答参数，未主动反问买家使用场景或推进导购
- SMOOTH_CONVERSION: 客服解答专业准确且包含场景化引导

请严格按以下 JSON 结构返回：
{
  "diagnoses": [
    {
      "session_id": "...",
      "spu_code": "...",
      "query": "...",
      "agent_response": "...",
      "loss_category": "PRICE_HESITATION | HARDWARE_UNCERTAINTY | SPIN_MISSED_RECOMMENDATION | SMOOTH_CONVERSION",
      "is_loss": true,
      "evidence": "具体失分原因与原句引用",
      "suggestion": "针对性改进建议"
    }
  ],
  "actionable_prompt_recommendations": [
    "可落地的 System Prompt 增量策略建议 1",
    "可落地的 System Prompt 增量策略建议 2"
  ]
}"""


class CriticAgent:
    """
    离线流失诊断分析 Agent (Critic)
    支持双模式：
    1. LLM-as-a-Judge 深度上下文归因 (llm_judge)：调用大模型对多轮会话进行语义归因与 JSON 解析
    2. 多特征规则与启发式语义分析 (rule_heuristic)：确定性特征规则分析
    """
    def __init__(self, judge_client: Any = None):
        self.judge_client = judge_client

    def _get_sync_judge_client(self):
        if self.judge_client is not None:
            return self.judge_client
        if os.getenv("LLM_FORCE_MOCK") == "true":
            return None
        if "pytest" in sys.modules and os.getenv("LLM_ENABLE_LIVE_TESTS") != "true":
            return None
        api_key = os.getenv("LLM_API_KEY") or os.getenv("ARK_API_KEY") or ""
        if api_key and api_key != "your_api_key_here":
            try:
                import httpx
                from openai import OpenAI
                http_proxy = os.getenv("HTTPS_PROXY") or os.getenv("HTTP_PROXY") or os.getenv("LLM_PROXY")
                http_client = httpx.Client(
                    proxy=http_proxy,
                    trust_env=bool(http_proxy),
                    timeout=15.0
                )
                return OpenAI(
                    base_url=llm_adapter.base_url,
                    api_key=api_key,
                    timeout=15.0,
                    http_client=http_client
                )
            except Exception as e:
                logger.warning(f"Init sync OpenAI client for Critic failed: {e}")
        return None

    def _analyze_with_llm_judge(self, rows: List[Any], client: Any) -> Optional[CriticReport]:
        """真实调用 LLM-as-a-Judge 对会话样本进行结构化语义归因"""
        sample_logs = [
            {
                "session_id": r["session_id"],
                "spu_code": r["spu_code"],
                "query": r["user_query"] or "",
                "agent_response": r["agent_response"] or ""
            }
            for r in rows[:15]
        ]
        messages = [
            {"role": "system", "content": CRITIC_JUDGE_SYSTEM_PROMPT},
            {"role": "user", "content": json.dumps(sample_logs, ensure_ascii=False)}
        ]
        try:
            resp = client.chat.completions.create(
                model=llm_adapter.model,
                messages=messages,
                temperature=0.1
            )
            raw_content = resp.choices[0].message.content.strip()
            if raw_content.startswith("```"):
                raw_content = raw_content.strip("`").removeprefix("json").strip()
            parsed = json.loads(raw_content)

            loss_categories = {
                "HARDWARE_UNCERTAINTY": 0,
                "PRICE_HESITATION": 0,
                "SPIN_MISSED_RECOMMENDATION": 0,
                "SMOOTH_CONVERSION": 0
            }
            loss_session_ids: List[str] = []
            diagnoses: List[SessionDiagnosis] = []

            for item in parsed.get("diagnoses", []):
                cat = item.get("loss_category", "SMOOTH_CONVERSION")
                if cat not in loss_categories:
                    cat = "SMOOTH_CONVERSION"
                loss_categories[cat] += 1
                is_loss = bool(item.get("is_loss", cat != "SMOOTH_CONVERSION"))
                sid = item.get("session_id", "unknown")
                if is_loss and sid not in loss_session_ids:
                    loss_session_ids.append(sid)
                diagnoses.append(SessionDiagnosis(
                    session_id=sid,
                    spu_code=item.get("spu_code"),
                    query=item.get("query", ""),
                    agent_response=item.get("agent_response", ""),
                    loss_category=cat,
                    suggestion=item.get("suggestion", ""),
                    is_loss=is_loss,
                    evidence=item.get("evidence", "")
                ))

            recommendations = parsed.get("actionable_prompt_recommendations") or [
                "针对价格敏感买家主动强化晒单外设礼包与免息权益说明",
                "解答硬件参数后追加一句场景化用途反问以推进导购转化"
            ]

            return CriticReport(
                critic_mode="llm_judge",
                total_analyzed=len(diagnoses),
                loss_categories=loss_categories,
                loss_session_ids=loss_session_ids,
                sample_diagnoses=diagnoses[:10],
                actionable_prompt_recommendations=recommendations
            )
        except Exception as e:
            logger.warning(f"LLM Judge execution failed, falling back to rule_heuristic: {e}")
            return None

    def _analyze_with_rules(self, rows: List[Any], mode_label: str = "rule_heuristic") -> CriticReport:
        """多特征规则与启发式归因分析"""
        total_analyzed = len(rows)
        diagnoses: List[SessionDiagnosis] = []
        loss_categories = {
            "HARDWARE_UNCERTAINTY": 0,
            "PRICE_HESITATION": 0,
            "SPIN_MISSED_RECOMMENDATION": 0,
            "SMOOTH_CONVERSION": 0
        }
        loss_session_ids: List[str] = []

        for r in rows:
            query = r["user_query"] or ""
            response = r["agent_response"] or ""
            session_id = r["session_id"]
            spu_code = r["spu_code"]

            is_loss = False
            evidence = ""

            if any(k in query for k in ["贵", "便宜", "优惠", "少点", "降价", "折扣"]):
                loss_categories["PRICE_HESITATION"] += 1
                suggestion = "买家表现出价格敏感，建议主动引导晒单赠送双肩包+鼠标等高价值赠品与分期免息策略"
                loss_category = "PRICE_HESITATION"
                is_loss = True
                evidence = f"买家提问包含价格敏感词: '{query}'"
            elif any(k in query for k in ["能不能玩", "卡不卡", "跑得动吗", "发热", "掉帧"]):
                loss_categories["HARDWARE_UNCERTAINTY"] += 1
                suggestion = "买家对游戏性能存在疑虑，建议强化满血功耗释放与主流 3A 帧率实测数据"
                loss_category = "HARDWARE_UNCERTAINTY"
                is_loss = True
                evidence = f"买家对硬件算力存疑: '{query}'"
            elif len(response) > 50 and not any(k in response for k in ["推荐", "建议", "您打算", "主要用于", "玩什么", "做设计"]):
                loss_categories["SPIN_MISSED_RECOMMENDATION"] += 1
                suggestion = "客服仅单向解答了参数，缺少顾问式 SPIN 反问，建议在解答后主动引导下一步需求"
                loss_category = "SPIN_MISSED_RECOMMENDATION"
                is_loss = True
                evidence = "客服回复偏单向应答，未探寻场景需求"
            else:
                loss_categories["SMOOTH_CONVERSION"] += 1
                suggestion = "会话解答完整且包含场景推荐或顺畅导购"
                loss_category = "SMOOTH_CONVERSION"
                is_loss = False
                evidence = "服务平稳，问答闭环"

            if is_loss and session_id not in loss_session_ids:
                loss_session_ids.append(session_id)

            diag = SessionDiagnosis(
                session_id=session_id,
                spu_code=spu_code,
                query=query,
                agent_response=response,
                loss_category=loss_category,
                suggestion=suggestion,
                is_loss=is_loss,
                evidence=evidence
            )
            diagnoses.append(diag)

        recommendations = [
            "针对价格犹豫客户，主动强调晒单赠送 399 元电竞外设大礼包与分期免息权益",
            "对满血性能疑问，强化 140W 与主流 3A 大作高画质流畅实测帧率说明",
            "在每次硬件参数解答后，增加一句场景用途反问（如：'请问您平时主要玩哪些游戏呢？'）"
        ]

        return CriticReport(
            critic_mode=mode_label,
            total_analyzed=total_analyzed,
            loss_categories=loss_categories,
            loss_session_ids=loss_session_ids,
            sample_diagnoses=diagnoses[:10],
            actionable_prompt_recommendations=recommendations
        )

    def analyze_recent_conversations(
        self,
        limit: int = 50,
        force_mode: Optional[str] = None,
        judge_client: Any = None
    ) -> Dict[str, Any]:
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

        client = judge_client or self._get_sync_judge_client()
        if force_mode == "rule_heuristic":
            report = self._analyze_with_rules(rows, mode_label="rule_heuristic")
            return report.model_dump()

        if client is not None and force_mode in (None, "llm_judge"):
            llm_report = self._analyze_with_llm_judge(rows, client)
            if llm_report is not None:
                return llm_report.model_dump()

        # 若无可用 LLM 客户端但调用方显式指定 force_mode="llm_judge"，如实降级或使用规则分析
        fallback_mode = "llm_judge" if force_mode == "llm_judge" else "rule_heuristic"
        report = self._analyze_with_rules(rows, mode_label=fallback_mode)
        return report.model_dump()


critic_agent = CriticAgent()
