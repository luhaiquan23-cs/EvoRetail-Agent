import re
import json
import logging
from typing import Dict, Any, List, Optional
from backend.core.models.buyer_profile import BuyerProfile
from backend.agent.tools import resolve_spu, ALIAS_MAP
from backend.core.llm_client import llm_adapter

logger = logging.getLogger("slot_extractor")

SLOT_EXTRACTION_SYSTEM_PROMPT = """请从买家咨询文本中提取结构化需求槽位，并严格输出 JSON 对象：
{
  "budget_min": null 或数字,
  "budget_max": null 或数字,
  "identity": null 或字符串 (如 "学生", "建筑系学生", "设计师", "程序员", "商务人士"),
  "use_cases": ["用途1", "用途2"],
  "portability_priority": null 或 true 或 false,
  "candidate_spus": ["SPU编码"]
}"""

class SlotExtractor:
    """
    买家需求槽位抽取器 (规则确定性抽取 + 可选 LLM 结构化抽取双模式)
    从买家自然语言问答中实时提炼：预算上下限、身份角色、核心场景软件、便携偏好、候选机型
    """
    def extract_from_text(self, text: str) -> BuyerProfile:
        norm = text.strip()

        # 1. 预算抽取 (优先匹配区间，次之匹配单上限/下限)
        budget_min: Optional[float] = None
        budget_max: Optional[float] = None

        range_match = re.search(r'([1-9]\d{3,4})\s*(?:到|-|~|至)\s*([1-9]\d{3,4})\s*(?:元|块)?', norm)
        if range_match:
            budget_min = float(range_match.group(1))
            budget_max = float(range_match.group(2))
        else:
            explicit_budget = re.search(r'预算[在约为:：]?\s*([1-9]\d{3,4})', norm)
            if explicit_budget:
                budget_max = float(explicit_budget.group(1))
            else:
                max_match = re.search(r'([1-9]\d{3,4})\s*(?:以?内|元以?内|块以?内|以下|最多|左右|元|块)', norm)
                if max_match:
                    budget_max = float(max_match.group(1))

            min_match = re.search(r'(?:预算)?\s*([1-9]\d{3,4})\s*(?:以?上|起|至少)', norm)
            if min_match:
                budget_min = float(min_match.group(1))

        # 2. 身份角色标签
        identity: Optional[str] = None
        if "建筑系" in norm:
            identity = "建筑系学生"
        elif any(k in norm for k in ["学生", "大一", "大二", "大三", "大四", "考研", "高三", "孩子", "大学", "新生", "医学生", "后生"]):
            identity = "学生"
        elif any(k in norm for k in ["程序员", "开发", "写代码", "后端", "前端", "算法"]):
            identity = "程序员"
        elif any(k in norm for k in ["摄影师", "剪辑师", "设计师", "设计", "后期", "美术"]):
            identity = "设计师"
        elif any(k in norm for k in ["商务", "出差", "销售", "财务", "会计", "分析师", "差旅", "公司"]):
            identity = "商务人士"
        elif any(k in norm for k in ["老师", "教师"]):
            identity = "教师/白领"
        elif any(k in norm for k in ["店主", "电商"]):
            identity = "电商白领"

        # 3. 核心用途与软件
        use_cases: List[str] = []
        if "cad" in norm.lower() or "autocad" in norm.lower():
            use_cases.append("CAD建模")
        if "lumion" in norm.lower():
            use_cases.append("Lumion渲染")
        if any(k in norm.lower() for k in ["solidworks", "blender", "maya", "keyshot", "建模", "制图", "3d"]):
            use_cases.append("3D建模")
        if any(k in norm for k in ["黑神话", "赛博朋克", "3a", "gta", "魔兽", "暗黑"]):
            use_cases.append("3A游戏")
        if "英雄联盟" in norm or "lol" in norm.lower():
            use_cases.append("英雄联盟")
        if any(k in norm for k in ["瓦罗兰特", "cs2", "永劫无间", "pubg", "吃鸡", "dota", "apex", "电竞"]):
            use_cases.append("电竞网游")
        if any(k in norm for k in ["原神", "崩铁"]):
            use_cases.append("手游网游")
        if any(k in norm for k in ["4k", "高清视频"]):
            use_cases.append("4K剪辑")
        elif any(k in norm.lower() for k in ["剪辑", "pr", "premiere", "剪映", "ae", "达芬奇"]):
            use_cases.append("视频剪辑")
        if any(k in norm.lower() for k in ["lightroom", "调色", "ps", "修图", "修照片"]):
            use_cases.append("调色后期")
        if any(k in norm for k in ["写代码", "编程", "docker", "跑代码"]):
            use_cases.append("写代码")
        if any(k in norm.lower() for k in ["大模型", "stable diffusion", "ai", "深度学习"]):
            use_cases.append("AI开发")
        if any(k in norm for k in ["办公", "word", "excel", "网课", "文献", "文案", "课件", "炒股", "研报", "刷题"]):
            use_cases.append("轻办公")
        if "游戏" in norm and not any("游戏" in uc for uc in use_cases):
            use_cases.append("游戏")

        # 4. 便携诉求偏好
        portability_priority: Optional[bool] = None
        if any(k in norm for k in ["重量无所谓", "不在乎重量", "放在宿舍", "不经常带"]):
            portability_priority = False
        elif any(k in norm for k in ["轻薄", "便携", "出差", "带去图书馆", "带出门", "双肩包", "背着", "轻巧", "轻一点", "越轻越好"]):
            portability_priority = True

        # 5. 意向候选机型（模糊归一化，容忍空格与特殊符号）
        candidate_spus: List[str] = []
        norm_clean = re.sub(r"[\s\-_\(\)（）【】\[\]]+", "", norm.lower())
        sorted_aliases = sorted(ALIAS_MAP.items(), key=lambda x: len(x[0]), reverse=True)
        for alias, spu in sorted_aliases:
            alias_clean = re.sub(r"[\s\-_\(\)（）【】\[\]]+", "", alias.lower())
            if alias_clean in norm_clean:
                if spu not in candidate_spus:
                    candidate_spus.append(spu)

        return BuyerProfile(
            budget_min=budget_min,
            budget_max=budget_max,
            identity=identity,
            use_cases=use_cases,
            portability_priority=portability_priority,
            candidate_spus=candidate_spus
        )

    async def extract_with_llm(self, text: str, client: Any = None) -> BuyerProfile:
        """
        双模混合槽位抽取：先执行确定性规则抽取，若提供或配置了异步 LLM 客户端，则补充调用 LLM 提取复杂语义槽位并合并
        """
        profile = self.extract_from_text(text)
        active_client = client or llm_adapter.get_client()
        if not active_client:
            return profile

        try:
            resp = await active_client.chat.completions.create(
                model=llm_adapter.model,
                messages=[
                    {"role": "system", "content": SLOT_EXTRACTION_SYSTEM_PROMPT},
                    {"role": "user", "content": text}
                ],
                temperature=0.0
            )
            content = resp.choices[0].message.content.strip()
            if content.startswith("```"):
                content = content.strip("`").removeprefix("json").strip()
            data = json.loads(content)
            llm_profile = BuyerProfile.model_validate(data)
            profile.merge(llm_profile)
        except Exception as e:
            logger.warning(f"LLM slot extraction fallback to rule-only: {e}")

        return profile

slot_extractor = SlotExtractor()
