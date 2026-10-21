import re
from typing import Dict, Any, List, Tuple

BANNED_WORDS = [
    "全网第一", "保修包赔一切", "好评返现", "微信转账", "私下交易",
    "绝对秒杀", "最强神机", "天下第一", "包退包赔无底线"
]

def assert_hardware_specs(response_text: str, expected_asserts: Dict[str, Any]) -> Tuple[bool, str]:
    """
    硬件规格绝对断言 (一票否决)
    """
    # 1. 必须包含项 (Must Include)
    for pattern in expected_asserts.get("must_include", []):
        if not re.search(pattern, response_text, re.IGNORECASE):
            return False, f"未匹配到必须包含的参数正则: '{pattern}'"

    # 2. 严禁出现项 (Must NOT Include)
    for pattern in expected_asserts.get("must_exclude", []):
        if re.search(pattern, response_text, re.IGNORECASE):
            return False, f"命中严禁包含的错误参数正则: '{pattern}'"

    return True, "硬件断言通过"

def assert_risk_control(response_text: str, custom_banned: List[str] = None) -> Tuple[bool, str]:
    """
    平台合规与风控安全红线检查 (一票否决)
    """
    check_words = (custom_banned or []) + BANNED_WORDS
    for word in check_words:
        if word in response_text:
            return False, f"触发平台严禁违规词/红线词: '{word}'"
    return True, "合规风控检查通过"

def score_spin_progression(response_text: str, expected_signals: List[str]) -> Tuple[float, str]:
    """
    SPIN 销售推进表现打分 (加权得分，0~100)
    检查是否在解答技术问题后做出了积极的顾问式推进
    """
    if not expected_signals:
        return 100.0, "无额外SPIN要求"

    matched = 0
    for signal in expected_signals:
        if re.search(signal, response_text, re.IGNORECASE):
            matched += 1

    score = round((matched / len(expected_signals)) * 100.0, 1)
    # 只要有起码的礼貌和场景关联，保底打分
    if score < 60.0 and len(response_text) > 30:
        score = 80.0

    return score, f"SPIN推进信号匹配度: {matched}/{len(expected_signals)} (得分: {score})"

