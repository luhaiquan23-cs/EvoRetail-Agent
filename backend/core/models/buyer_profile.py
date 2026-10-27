import json
from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field

class BuyerProfile(BaseModel):
    """
    买家画像结构化槽位模型
    跨多轮会话持久化存储，解决长会话历史截断导致的买家预算/身份/核心诉求遗忘问题
    """
    budget_min: Optional[float] = Field(None, description="预算下限 (元)")
    budget_max: Optional[float] = Field(None, description="预算上限 (元)")
    identity: Optional[str] = Field(None, description="买家身份标签 (如 学生/建筑系学生/程序员/设计师/商务人士)")
    use_cases: List[str] = Field(default_factory=list, description="核心使用场景与软件需求 (如 3A游戏/CAD建模/剪辑/办公)")
    portability_priority: Optional[bool] = Field(None, description="是否优先要求便携轻薄")
    candidate_spus: List[str] = Field(default_factory=list, description="买家已明确表现出兴趣的候选机型")

    def merge(self, other: "BuyerProfile") -> "BuyerProfile":
        """
        合并增量买家画像槽位:
        - 预算、身份、便携偏好支持新信息改口覆盖
        - 使用场景与候选机型去重追加
        """
        if other.budget_max is not None:
            self.budget_max = other.budget_max
        if other.budget_min is not None:
            self.budget_min = other.budget_min
        if other.identity is not None:
            self.identity = other.identity
        if other.portability_priority is not None:
            self.portability_priority = other.portability_priority

        for uc in other.use_cases:
            if uc not in self.use_cases:
                self.use_cases.append(uc)

        for spu in other.candidate_spus:
            if spu not in self.candidate_spus:
                self.candidate_spus.append(spu)

        return self

    def is_empty(self) -> bool:
        return (
            self.budget_min is None
            and self.budget_max is None
            and self.identity is None
            and not self.use_cases
            and self.portability_priority is None
            and not self.candidate_spus
        )

    def to_prompt_context(self) -> str:
        """
        序列化为 System Prompt 格式的买家画像槽位记忆块 (常驻 System 区，严禁在滑动历史中丢弃)
        """
        if self.is_empty():
            return ""

        parts = []
        if self.identity:
            parts.append(f"买家身份: {self.identity}")

        if self.budget_min is not None and self.budget_max is not None:
            parts.append(f"预算范围: ¥{self.budget_min:.0f} ~ ¥{self.budget_max:.0f}")
        elif self.budget_max is not None:
            parts.append(f"预算上限: ¥{self.budget_max:.0f} 以内")
        elif self.budget_min is not None:
            parts.append(f"预算下限: ¥{self.budget_min:.0f} 以上")

        if self.use_cases:
            parts.append(f"核心用途/软件: {', '.join(self.use_cases)}")

        if self.portability_priority is not None:
            parts.append("便携诉求: 重点考虑轻薄便携" if self.portability_priority else "便携诉求: 重视性能释放，接受正常游戏本机重")

        if self.candidate_spus:
            parts.append(f"意向候选机型: {', '.join(self.candidate_spus)}")

        return "【买家已交代核心诉求画像（长记忆常驻，严禁违背或反复询问）】\n- " + " | ".join(parts) + "\n"

