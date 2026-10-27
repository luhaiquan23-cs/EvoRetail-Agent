import re
import logging
from typing import List, Dict, Tuple, Optional, AsyncIterator, Any
from backend.core.database import db
from backend.core.models.product_specs import ProductItem

logger = logging.getLogger("guardrails")

# 1. 违禁词规则定义 (分为私下交易、虚假好评、极限违规词三类)
PROHIBITED_RULES = [
    {
        "rule_name": "OFF_PLATFORM_TRANSACTION",
        "pattern": re.compile(
            r"(微信转账|微信支付|私下交易|私下转账|线下转账|加微信|加我微信|加v转账|支付宝转账|私信交易|绕过平台|脱离平台)",
            re.IGNORECASE
        ),
        "sanitized_text": "【系统合规提示：请通过平台官方渠道下单交易，享受正品保障与官方售后服务】",
        "event_type": "prohibited_word"
    },
    {
        "rule_name": "FAKE_REVIEW_CASHBACK",
        "pattern": re.compile(
            r"(好评返现|好评返红包|晒单返现|好评给返现|给好评返|五星好评返|返现联系|刷单)",
            re.IGNORECASE
        ),
        "sanitized_text": "【系统合规提示：本旗舰店严禁违规诱导虚假评价，坚持客观真实评价与官方正品保障】",
        "event_type": "prohibited_word"
    },
    {
        "rule_name": "EXTREME_EXAGGERATED_WORDS",
        "pattern": re.compile(
            r"(全网第一|绝对秒杀|最强神机|天下第一|宇宙最强|保修包赔一切|无敌秒杀)",
            re.IGNORECASE
        ),
        "sanitized_text": "【系统合规提示：已为您呈现客观参数与实际硬件测试规格】",
        "event_type": "prohibited_word"
    }
]

# 子句切分标点符号
CLAUSE_DELIMITERS = re.compile(r"([，。！？；\n\r])")

def find_product_for_clause(clause: str, default_product: Optional[ProductItem] = None) -> Optional[ProductItem]:
    """
    智能识别句子中所指向的具体机型实体
    1. 优先根据别名表与 SPU 编码匹配
    2. 若句子未提及任何其它已知机型，回退到传入的默认 product
    """
    from backend.agent.tools import ALIAS_MAP
    clean_clause = re.sub(r"[\s\-_\(\)（）【】\[\]]+", "", clause.lower())

    # 优先匹配别名表（按长度倒序，长词优先匹配）
    sorted_aliases = sorted(ALIAS_MAP.items(), key=lambda x: len(x[0]), reverse=True)
    for alias, spu in sorted_aliases:
        alias_clean = re.sub(r"[\s\-_\(\)（）【】\[\]]+", "", alias.lower())
        if alias_clean in clean_clause:
            p = db.get_product(spu)
            if p:
                return p

    # 匹配已加载的所有商品编码与标题
    for p_info in db.list_products():
        spu_code = p_info["spu_code"]
        spu_clean = re.sub(r"[\s\-_\(\)（）【】\[\]]+", "", spu_code.lower())
        title_clean = re.sub(r"[\s\-_\(\)（）【】\[\]]+", "", p_info["title"].lower())
        if spu_clean in clean_clause or (len(title_clean) >= 4 and title_clean in clean_clause):
            return db.get_product(spu_code)

    return default_product

class OutputGuardrail:
    """
    输出端安全与数值一致性双层护栏
    1. 违禁词检测与合规替换 (离线/流式通用)
    2. 硬件核心数值一致性校验与防造假自动修正 (功耗TGP、插槽、刷新率、重量、价格)
    3. 句级滑动缓冲器，实现 100% 跨 Token 拆分拦截与无损透传
    """

    def check_and_sanitize_clause(
        self,
        clause: str,
        session_id: str = "default_session",
        spu_code: Optional[str] = None,
        product: Optional[ProductItem] = None
    ) -> Tuple[str, List[Dict[str, Any]]]:
        events = []
        sanitized = clause

        # Layer 1: 平台违禁词检测
        for rule in PROHIBITED_RULES:
            match = rule["pattern"].search(sanitized)
            if match:
                original = sanitized
                # 整句替换为合规说明
                sanitized = rule["sanitized_text"]
                event = {
                    "session_id": session_id,
                    "spu_code": spu_code,
                    "event_type": rule["event_type"],
                    "original_text": original,
                    "sanitized_text": sanitized,
                    "rule_name": rule["rule_name"]
                }
                events.append(event)
                try:
                    db.log_guardrail_event(**event)
                except Exception as e:
                    logger.error(f"Failed to log guardrail event to DB: {e}")
                # 命中高危红线后不再做后续普通数值比较
                return sanitized, events

        # Layer 2: 硬件关键数值一致性校验 (如提供了机型规格或子句命中机型)
        sanitized, num_events = self.check_numeric_consistency(
            sanitized,
            product=product,
            session_id=session_id,
            spu_code=spu_code
        )
        events.extend(num_events)

        return sanitized, events

    def check_numeric_consistency(
        self,
        clause: str,
        product: Optional[ProductItem],
        session_id: str = "default_session",
        spu_code: Optional[str] = None
    ) -> Tuple[str, List[Dict[str, Any]]]:
        """
        校验句子中的硬件核心数值：
        - M.2 固态插槽数量造假 (单槽机型说成双槽/加装第二根，或双槽机型说成单槽)
        - 显卡/整机功耗 (TGP Watt) 造假
        - 屏幕刷新率 (Hz) 造假
        - 机身重量 (kg) 造假
        - 官方价格 (元) 造假
        """
        events = []
        sanitized = clause

        # 智能匹配该子句所指向的具体商品（防止跨机型对比时用 A 机型参数强行覆盖 B 机型）
        target_product = find_product_for_clause(clause, default_product=product)
        if not target_product:
            return sanitized, events

        actual_spu = spu_code or target_product.spu_code

        # 1. M.2 固态插槽一致性
        if target_product.hardware.m2_slots_total == 1:
            # 单 M.2 槽机型：严禁宣传“双 M.2”、“加装第二根”
            fake_dual_match = re.search(r"(双\s*M\.2(?:\s*固态)?(?:\s*插槽)?|2\s*个\s*M\.2(?:\s*插槽)?|两\s*个\s*M\.2(?:\s*插槽)?|加装第二根固态|第二个固态|额外加装固态)", sanitized)
            if fake_dual_match:
                original = sanitized
                sanitized = re.sub(
                    r"(双\s*M\.2(?:\s*固态)?(?:\s*插槽)?|2\s*个\s*M\.2(?:\s*插槽)?|两\s*个\s*M\.2(?:\s*插槽)?|加装第二根固态|第二个固态|额外加装固态)(?:[（(][^）)]*[）)])?",
                    "单 M.2 插槽（支持原盘替换升级）",
                    sanitized
                )
                ev = {
                    "session_id": session_id,
                    "spu_code": actual_spu,
                    "event_type": "numeric_conflict",
                    "original_text": original,
                    "sanitized_text": sanitized,
                    "rule_name": "NUMERIC_M2_SLOTS_CONFLICT"
                }
                events.append(ev)
                db.log_guardrail_event(**ev)
        elif target_product.hardware.m2_slots_total >= 2:
            # 双 M.2 槽机型：若误标成单插槽则修正
            fake_single_match = re.search(r"(单\s*M\.2(?:\s*固态)?(?:\s*插槽)?|仅\s*1\s*个\s*M\.2(?:\s*插槽)?|只有\s*1\s*个\s*M\.2(?:\s*插槽)?|不支持加装第二根)", sanitized)
            if fake_single_match:
                original = sanitized
                sanitized = re.sub(
                    r"(单\s*M\.2(?:\s*固态)?(?:\s*插槽)?|仅\s*1\s*个\s*M\.2(?:\s*插槽)?|只有\s*1\s*个\s*M\.2(?:\s*插槽)?|不支持加装第二根)(?:[（(][^）)]*[）)])?",
                    "双 M.2 插槽（支持加装第二根固态）",
                    sanitized
                )
                ev = {
                    "session_id": session_id,
                    "spu_code": actual_spu,
                    "event_type": "numeric_conflict",
                    "original_text": original,
                    "sanitized_text": sanitized,
                    "rule_name": "NUMERIC_M2_SLOTS_CONFLICT"
                }
                events.append(ev)
                db.log_guardrail_event(**ev)

        # 2. 功耗 (TGP / Watt) 一致性 (豁免 PD 快充、适配器功率)
        is_pd_charging = bool(re.search(r"(?:PD|快充|充电|适配器|电源|供电|充电器)", sanitized, re.IGNORECASE))
        if not is_pd_charging:
            watt_match = re.search(r"(?<!\d)(\d{2,3})\s*(?:W|瓦)(?:满血)?(?:释放|功耗|TGP)?", sanitized)
            if watt_match and target_product.hardware.tgp_watt:
                claimed_watt = int(watt_match.group(1))
                true_watt = int(target_product.hardware.tgp_watt)
                # 允许 3W 测量误差，超过则判定为参数冲突
                if abs(claimed_watt - true_watt) > 3:
                    original = sanitized
                    sanitized = re.sub(r"(?<!\d)" + str(claimed_watt) + r"\s*(?:W|瓦)", f"{true_watt}W", sanitized)
                    ev = {
                        "session_id": session_id,
                        "spu_code": actual_spu,
                        "event_type": "numeric_conflict",
                        "original_text": original,
                        "sanitized_text": sanitized,
                        "rule_name": "NUMERIC_TGP_WATT_CONFLICT"
                    }
                    events.append(ev)
                    db.log_guardrail_event(**ev)

        # 3. 屏幕刷新率 (Hz) 一致性
        hz_match = re.search(r"(?<!\d)(\d{2,4})\s*Hz", sanitized, re.IGNORECASE)
        if hz_match and target_product.display.refresh_rate:
            claimed_hz = int(hz_match.group(1))
            true_hz = int(target_product.display.refresh_rate)
            if abs(claimed_hz - true_hz) > 5:
                original = sanitized
                sanitized = re.sub(r"(?<!\d)" + str(claimed_hz) + r"\s*Hz", f"{true_hz}Hz", sanitized, flags=re.IGNORECASE)
                ev = {
                    "session_id": session_id,
                    "spu_code": actual_spu,
                    "event_type": "numeric_conflict",
                    "original_text": original,
                    "sanitized_text": sanitized,
                    "rule_name": "NUMERIC_REFRESH_RATE_CONFLICT"
                }
                events.append(ev)
                db.log_guardrail_event(**ev)

        # 4. 机身重量 (kg) 一致性 (豁免差重/对比轻重差异，如“轻 0.6kg”、“更轻 0.15kg”)
        is_weight_diff = bool(re.search(r"(?:更轻|更重|轻了|重了|比[^，。\n]*[轻重]|相差|差值|差重|减轻|减重)\s*\d", sanitized))
        if not is_weight_diff:
            weight_match = re.search(r"(?<!\d)(\d+(?:\.\d+)?)\s*kg", sanitized, re.IGNORECASE)
            if weight_match and target_product.hardware.weight_kg:
                claimed_weight = float(weight_match.group(1))
                true_weight = float(target_product.hardware.weight_kg)
                if abs(claimed_weight - true_weight) > 0.2:
                    original = sanitized
                    sanitized = re.sub(r"(?<!\d)\d+(?:\.\d+)?\s*kg", f"{true_weight}kg", sanitized, count=1, flags=re.IGNORECASE)
                    ev = {
                        "session_id": session_id,
                        "spu_code": actual_spu,
                        "event_type": "numeric_conflict",
                        "original_text": original,
                        "sanitized_text": sanitized,
                        "rule_name": "NUMERIC_WEIGHT_CONFLICT"
                    }
                    events.append(ev)
                    db.log_guardrail_event(**ev)

        # 5. 官方指导售价 (¥) 一致性 (豁免差价、超出预算、省下预算等差值)
        # 若显式包含“官方价/指导价/售价/原价”，则优先作为整机价格校验
        is_explicit_price = bool(re.search(r"(?:官方指导价|官方售价|指导价|售价|官方价|定价|标价)\s*[为是仅需约]?\s*[¥￥]?\s*\d+", sanitized))
        is_price_diff = bool(re.search(r"(?:差价|相差|超出预算|超出您预算|多出|省下|立减|直降|优惠券|补贴|便宜了|贵了)\s*(?:为|约|达|了)?\s*[¥￥]?\s*\d+", sanitized)) or bool(re.search(r"(?:预算|上限|封顶)\s*(?:为|在|约|是|≤|<=|控制在)?\s*[¥￥]?\s*\d+", sanitized))
        if is_explicit_price or not is_price_diff:
            price_match = re.search(r"(?:[¥￥]|价格(?:为|是)?\s*[¥￥]?)\s*(\d{4,5})", sanitized)
            if price_match and target_product.official_price:
                claimed_price = float(price_match.group(1))
                true_price = float(target_product.official_price)
                # 价格误差超过 150 元视为虚假价格
                if abs(claimed_price - true_price) > 150:
                    original = sanitized
                    sanitized = re.sub(r"([¥￥])\s*\d{4,5}", f"¥{int(true_price)}", sanitized, count=1)
                    ev = {
                        "session_id": session_id,
                        "spu_code": actual_spu,
                        "event_type": "numeric_conflict",
                        "original_text": original,
                        "sanitized_text": sanitized,
                        "rule_name": "NUMERIC_PRICE_CONFLICT"
                    }
                    events.append(ev)
                    db.log_guardrail_event(**ev)

        return sanitized, events

    def guard_text(
        self,
        text: str,
        session_id: str = "default_session",
        spu_code: Optional[str] = None,
        product: Optional[ProductItem] = None
    ) -> Tuple[str, List[Dict[str, Any]]]:
        """离线整句批量检测接口"""
        return self.check_and_sanitize_clause(
            text,
            session_id=session_id,
            spu_code=spu_code,
            product=product
        )

    async def guard_stream(
        self,
        stream: AsyncIterator[str],
        session_id: str = "default_session",
        spu_code: Optional[str] = None,
        product: Optional[ProductItem] = None,
        max_buffer_chars: int = 120
    ) -> AsyncIterator[str]:
        """
        流式滑动句级缓冲器：
        - 遇到句下标点或换行切分为子句过检
        - 缓冲区过长未见标点时，寻找安全切分边界（绝不在数字、单词或表格中途腰斩）
        - 彻底解决跨 chunk 拆分违禁词漏报与数字截断误杀
        - 正常合规回复无损透传
        """
        buffer = ""

        async for chunk in stream:
            buffer += chunk

            # 检测标点切分
            while True:
                split_match = CLAUSE_DELIMITERS.search(buffer)
                if split_match:
                    delimiter_end = split_match.end()
                    clause = buffer[:delimiter_end]
                    buffer = buffer[delimiter_end:]

                    sanitized_clause, _ = self.check_and_sanitize_clause(
                        clause,
                        session_id=session_id,
                        spu_code=spu_code,
                        product=product
                    )
                    yield sanitized_clause
                elif len(buffer) >= max_buffer_chars:
                    # 缓冲区过长未见标点，安全回退寻找词边界
                    cut_pos = max_buffer_chars
                    while cut_pos > 30 and (buffer[cut_pos-1].isalnum() or buffer[cut_pos-1] in "-_.*"):
                        cut_pos -= 1
                    if cut_pos <= 30:
                        cut_pos = max_buffer_chars
                    clause = buffer[:cut_pos]
                    buffer = buffer[cut_pos:]
                    sanitized_clause, _ = self.check_and_sanitize_clause(
                        clause,
                        session_id=session_id,
                        spu_code=spu_code,
                        product=product
                    )
                    yield sanitized_clause
                else:
                    break

        # 流结束时刷新残余文本
        if buffer:
            sanitized_clause, _ = self.check_and_sanitize_clause(
                buffer,
                session_id=session_id,
                spu_code=spu_code,
                product=product
            )
            yield sanitized_clause

output_guardrail = OutputGuardrail()
