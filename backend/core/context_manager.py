import re
import logging
from typing import List, Dict, Optional, Union, Any
from backend.core.models.chat_schemas import ChatMessage
from backend.core.models.buyer_profile import BuyerProfile

logger = logging.getLogger(__name__)

# 尝试导入 tiktoken；若环境不可用则降级至精确 BPE 规则估算器
try:
    import tiktoken
    _cl100k_encoder = tiktoken.get_encoding("cl100k_base")

    def count_tokens(text: str) -> int:
        if not text:
            return 0
        return len(_cl100k_encoder.encode(text))
except Exception:
    def count_tokens(text: str) -> int:
        if not text:
            return 0
        # cl100k_base 分词特征估算：中文单字约 1.1~1.3 Token，英文单字约 1.2 Token，符号标点 1 Token
        chinese_chars = len(re.findall(r'[\u4e00-\u9fff]', text))
        english_words = len(re.findall(r'[a-zA-Z0-9]+', text))
        symbols = len(re.findall(r'[^\w\s]', text))
        spaces = len(re.findall(r'\s+', text))
        tokens = int(chinese_chars * 1.15 + english_words * 1.25 + symbols * 1.0 + spaces * 0.2)
        return max(1, tokens)

def count_message_tokens(msg: Dict[str, str]) -> int:
    """计算单条 OpenAI 消息的 Token 开销（含 <|im_start|>{role} 等元数据开销约 4 Token）"""
    role = msg.get("role", "")
    content = msg.get("content", "")
    return count_tokens(content) + count_tokens(role) + 4

def count_messages_tokens(messages: List[Dict[str, str]]) -> int:
    """计算消息列表的总 Token 数（加 2 Token 的 assistant 引导开销）"""
    if not messages:
        return 0
    return sum(count_message_tokens(m) for m in messages) + 2

# 停用/无实质信息助词正则（噪声剥离）
TRIVIAL_WORDS_PATTERN = re.compile(r"^(在吗|在不|你好呀|好的|行吧|知道了|谢谢|嗯嗯|哦哦|收到|好的呢|ok|yes)$", re.IGNORECASE)

class ContextBudgetManager:
    """
    1000 Token 上下文预算账户管理
    [1] 核心锚定区: ~400 Token (人设、SPIN 策略、风控红线，支持从数据库动态热加载与回滚)
        + 买家画像槽位区 (长记忆常驻，严禁在滑动历史中丢失)
    [2] 事实注入区: ~300 Token (Pydantic 校验规格 + 知识库匹配 + 工具返回)
    [3] 滑动历史区: ~300 Token (按 Token 边界自底向上剔除过早历史)
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

    @staticmethod
    def count_tokens(text: str) -> int:
        return count_tokens(text)

    @staticmethod
    def count_messages_tokens(messages: List[Dict[str, str]]) -> int:
        return count_messages_tokens(messages)

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
        rag_context: Optional[str] = None,
        buyer_profile: Optional[Union[BuyerProfile, str]] = None,
        tool_results: Optional[str] = None,
        total_budget: int = 1000,
        system_budget: int = 400,
        facts_budget: int = 300,
        history_budget: int = 300
    ) -> List[Dict[str, str]]:
        # 1. 核心人设与买家画像区 (常驻区，严禁丢失)
        system_blocks = [self.active_system_prompt]

        if buyer_profile:
            if isinstance(buyer_profile, BuyerProfile):
                profile_context = buyer_profile.to_prompt_context()
            else:
                profile_context = str(buyer_profile).strip()
            if profile_context:
                system_blocks.append(profile_context)

        # 2. 事实与工具注入区 (预算控制 ~300 Token)
        fact_blocks = []
        if anchor_fact and anchor_fact.strip():
            fact_blocks.append(anchor_fact.strip())
        if rag_context and rag_context.strip():
            fact_blocks.append(f"【参考服务与售后知识】\n{rag_context.strip()}")
        if tool_results and tool_results.strip():
            fact_blocks.append(f"【实时工具查询结果】\n{tool_results.strip()}")

        if fact_blocks:
            fact_text = "\n\n".join(fact_blocks)
            # 事实区 Token 限制
            if count_tokens(fact_text) > facts_budget:
                if anchor_fact:
                    system_blocks.append(anchor_fact.strip())
                    remaining_fact_tokens = facts_budget - count_tokens(anchor_fact)
                    if remaining_fact_tokens > 50 and rag_context:
                        clipped_rag = rag_context[:remaining_fact_tokens * 2]
                        system_blocks.append(f"【参考服务与售后知识】\n{clipped_rag}")
                else:
                    system_blocks.append(fact_text[:facts_budget * 2])
            else:
                system_blocks.append(fact_text)

        assembled_system = "\n\n".join(system_blocks)
        system_msg = {"role": "system", "content": assembled_system}
        system_tokens = count_message_tokens(system_msg)

        # 3. 当前买家提问
        cleaned_query = query.strip()
        query_msg = {"role": "user", "content": cleaned_query}
        query_tokens = count_message_tokens(query_msg)

        # 4. 滑动历史区 (预算 ~300 Token，且受总预算限制: total_budget - system - query)
        max_history_budget = min(history_budget, max(0, total_budget - system_tokens - query_tokens - 2))

        # 过滤噪声历史
        valid_history: List[Dict[str, str]] = []
        for msg in history:
            stripped_content = self.strip_noise(msg.content)
            if stripped_content:
                valid_history.append({"role": msg.role, "content": stripped_content})

        # 从最近的历史开始逆向纳入，超出 Token 预算边界即停止
        kept_history: List[Dict[str, str]] = []
        current_history_tokens = 0

        for msg in reversed(valid_history):
            msg_tokens = count_message_tokens(msg)
            if current_history_tokens + msg_tokens <= max_history_budget:
                kept_history.insert(0, msg)
                current_history_tokens += msg_tokens
            else:
                break

        final_messages = [system_msg] + kept_history + [query_msg]
        return final_messages

context_manager = ContextBudgetManager()
