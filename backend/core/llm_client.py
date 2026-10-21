import os
import asyncio
from typing import AsyncGenerator, Dict, Any, List
from dotenv import load_dotenv

load_dotenv()

class LLMAdapter:
    """
    可插拔统一 LLM 客户端驱动
    支持标准 OpenAI 协议（火山方舟、DeepSeek、阿里通义、Ollama 等通用）
    """
    def __init__(self):
        self.provider = os.getenv("LLM_PROVIDER", "volcano_ark")
        self.base_url = os.getenv("LLM_BASE_URL", "https://ark.cn-beijing.volces.com/api/v3")
        self.api_key = os.getenv("LLM_API_KEY", "")
        self.model = os.getenv("LLM_MODEL_NAME", "ep-2025xxxxxx-xxxxx")
        self.temperature = float(os.getenv("LLM_TEMPERATURE", "0.3"))
        self.timeout = float(os.getenv("LLM_TIMEOUT", "30.0"))

    def get_client(self):
        """动态获取与当前异步事件循环绑定的客户端"""
        if self.api_key and self.api_key != "your_api_key_here":
            try:
                from openai import AsyncOpenAI
                return AsyncOpenAI(
                    base_url=self.base_url,
                    api_key=self.api_key,
                    timeout=self.timeout
                )
            except Exception as e:
                print(f"[WARN] [LLMAdapter] Init AsyncOpenAI failed: {e}")
        return None

    async def stream_chat(self, messages: List[Dict[str, str]], force_mock: bool = False) -> AsyncGenerator[str, None]:
        """
        统一异步流式输出生成器
        若未配置有效 API KEY 或传入 force_mock=True，则启动轻量本地确定性事实响应
        """
        client = self.get_client()
        if client and not force_mock:
            try:
                response = await client.chat.completions.create(
                    model=self.model,
                    messages=messages,
                    temperature=self.temperature,
                    stream=True
                )
                async for chunk in response:
                    if chunk.choices and chunk.choices[0].delta:
                        delta_content = chunk.choices[0].delta.content
                        if delta_content:
                            yield delta_content
                return
            except Exception as e:
                print(f"[ERROR] [LLMAdapter] API error: {e}")
                yield f"\n[服务提示: 远程模型连接异常 ({e})，已启用兜底回复]\n"

        # --- 离线本地事实响应生成器 (无 Key 或沙箱回归演练模式) ---
        user_query = messages[-1].get("content", "") if messages else ""
        system_text = messages[0].get("content", "") if messages else ""

        # 1. 风控红线防御 (针对违规、好评返现、私下交易、虚假极限词)
        banned_triggers = ["返现", "微信转账", "私下交易", "全网第一", "包赔一切", "最强神机", "绝对秒杀", "包退包赔"]
        if any(w in user_query for w in banned_triggers):
            safe_reply = (
                "您好！作为惠普官方旗舰店正规顾问，我们严格遵守电商平台合规规范，"
                "全店均为正品行货，不参与任何形式的好评返现或私下微信交易。"
                "所有商品均由官方提供正规发票与全国联保售后保障，请您放心按需选购！"
            )
            for ch in safe_reply:
                yield ch
            return

        # 2. 硬件事实精准提炼 (直接依据 System Prompt 锚定的权威数据)
        mock_reply = "您好！我是惠普官方咨询顾问智小惠。"

        matched_facts = []
        for line in system_text.split("\n"):
            line_str = line.strip()
            if not line_str.startswith("- "):
                continue

            # 匹配问题关联参数
            if any(k in user_query.lower() for k in ["处理器", "cpu"]) and "CPU=" in line_str:
                matched_facts.append(line_str.lstrip("- "))
            elif any(k in user_query.lower() for k in ["显卡", "功耗", "tgp", "满血", "性能"]) and "显卡=" in line_str:
                matched_facts.append(line_str.lstrip("- "))
            elif any(k in user_query.lower() for k in ["屏幕", "刷新率", "色域", "亮度", "分辨率", "高刷", "hz"]) and "屏幕素质:" in line_str:
                matched_facts.append(line_str.lstrip("- "))
            elif any(k in user_query.lower() for k in ["固态", "内存", "插槽", "扩展", "升级", "加装", "m.2", "双插槽"]) and "扩展性:" in line_str:
                matched_facts.append(line_str.lstrip("- "))
            elif any(k in user_query.lower() for k in ["雷电", "重量", "接口", "便携", "出差", "厚重", "公斤", "kg", "多重", "机身", "显卡坞", "外接"]) and "接口与重量:" in line_str:
                matched_facts.append(line_str.lstrip("- "))
            elif any(k in user_query.lower() for k in ["认证", "军工", "耐用", "亮点", "防泼溅", "特色"]) and "特色亮点:" in line_str:
                matched_facts.append(line_str.lstrip("- "))
            elif any(k in user_query.lower() for k in ["赠品", "礼品", "大礼包", "双肩包", "鼠标", "发票", "晒单"]) and "赠品与保障:" in line_str:
                matched_facts.append(line_str.lstrip("- "))

        if matched_facts:
            mock_reply += f" 关于您咨询的硬件细节，官方权威参数如下：{ '；'.join(matched_facts) }。"
            if "固态" in user_query or "加装" in user_query or "升级" in user_query:
                mock_reply += " 升级加装时不破坏保修封条均享受全国联保无损质保！"
            mock_reply += " 请问您平时主要是用来打大型 3A 游戏、剪辑建模还是便携办公呢？我们可以为您提供更具体的配置搭配建议！"
        elif "快递" in user_query or "顺丰" in user_query or "发货" in user_query:
            mock_reply += " 全场笔记本统一默认顺丰速运特快包邮，每天 16:30 前下单当天官方仓库火速发出，签收时支持开箱验货！"
        elif "发热" in user_query or "风扇" in user_query or "烫" in user_query:
            mock_reply += " 游戏本高负荷满血释放时核心温度在 85℃~95℃ 属于正常安全温控区间，建议在 OMEN Gaming Hub 中开启狂暴模式并将笔记本后部适当垫高保持进风畅通！"
        else:
            mock_reply += f" 关于您咨询的【{user_query}】，这款机型拥有均衡的硬件配置与优秀的散热表现，支持全国联保并享有晒单赠礼政策。如果您对具体硬件规格有进一步要求，随时告诉我！"

        for ch in mock_reply:
            yield ch

llm_adapter = LLMAdapter()
