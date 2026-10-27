import re
from typing import List, Dict, Optional
from backend.core.models.chat_schemas import ChatMessage

# 停用/无实质信息助词正则（噪声剥离）
TRIVIAL_WORDS_PATTERN = re.compile(r"^(在吗|在不|你好呀|好的|行吧|知道了|谢谢|嗯嗯|哦哦|收到|好的呢|ok|yes)$", re.IGNORECASE)

class ContextBudgetManager:
    """
    1000 Token 上下文预算账户管理
    [1] 核心锚定区: ~400 Token (人设、SPIN 策略、风控红线，支持从数据库动态热加载与回滚)
    [2] 事实注入区: ~300 Token (Pydantic 校验规格 + 知识库匹配)
    [3] 滑动历史区: ~300 Token (最多保留 2-3 轮精简对话，超额滑动去噪)
    """

    DEFAULT_SYSTEM_CORE = """
你是【惠普 3C 数码官方旗舰店金牌客服 - 智小惠】。你的首要使命是为买家提供准确、专业、严谨且热情的选购咨询。

【行为准则与红线（绝对一票否决）】
1. 绝对参数防幻觉：针对处理器型号、显卡功耗(TGP)、M.2 插槽数量、雷电4接口、屏幕刷新率等硬件参数，必须以【咨询商品规格事实】为准，严禁编造或推测。未标明的信息请诚实说明。
2. 平台合规红线：严禁出现“全网第一”、“绝对秒杀”、“最强神机”、“保修包赔一切”等极限词；严禁提及“微信转账”、“私下交易”或“好评返现”。
3. 顾问式销售 (SPIN/FAB)：在正面准确解答买家硬件疑问后，自然关联使用场景（如打 3A 游戏、剪辑建模、便携出差），并适时引导下一步需求或提示官方售后保障与限时赠品。
""".strip()

    def __init__(self, prompt_version: str = "v2.0.0", system_prompt: Optional[str] = None):
        self.prompt_version = prompt_version
        self.active_system_prompt = (system_prompt or self.DEFAULT_SYSTEM_CORE).strip()

    def update_active_prompt(self, version: str, system_prompt: str):
        """运行时热更新激活的 Prompt 版本与核心指令文本"""
        self.prompt_version = version
        if system_prompt and len(system_prompt.strip()) > 20:
            self.active_system_prompt = system_prompt.strip()
        else:
            self.active_system_prompt = self.DEFAULT_SYSTEM_CORE

    def strip_noise(self, text: str) -> Optional[str]:
        """清洗买家回复中的纯噪声短语"""
        cleaned = text.strip()
        if TRIVIAL_WORDS_PATTERN.match(cleaned):
            return None
        return cleaned

    def assemble_messages(
        self,
        query: str,
        history: List[ChatMessage],
        anchor_fact: Optional[str] = None,
        rag_context: Optional[str] = None
    ) -> List[Dict[str, str]]:
        # 1. 核心系统提示词 (锚定区 - 使用当前动态激活的 System Prompt)
        system_blocks = [self.active_system_prompt]

        # 2. 事实注入区 (SPU 规格直查 + 检索内容)
        if anchor_fact:
            system_blocks.append(anchor_fact.strip())
        if rag_context:
            system_blocks.append(f"【参考服务与售后知识】\n{rag_context.strip()}")

        assembled_system = "\n\n".join(system_blocks)

        final_messages = [{"role": "system", "content": assembled_system}]

        # 3. 滑动历史区 (执行噪声过滤与轮次控制，限制在最近 4 条消息以内)
        valid_history: List[Dict[str, str]] = []
        for msg in history[-6:]:  # 先截取最近几条
            stripped_content = self.strip_noise(msg.content)
            if stripped_content:
                valid_history.append({"role": msg.role, "content": stripped_content})

        # 只保留最近 2-3 轮有效问答 (最多 4 条)
        final_messages.extend(valid_history[-4:])

        # 4. 当前买家提问
        final_messages.append({"role": "user", "content": query.strip()})

        return final_messages

context_manager = ContextBudgetManager()
