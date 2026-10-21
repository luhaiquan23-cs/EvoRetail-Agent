from typing import List, Optional
from pydantic import BaseModel, Field

class ChatMessage(BaseModel):
    role: str = Field(..., description="user / assistant / system")
    content: str = Field(..., description="消息内容")

class ChatCompletionRequest(BaseModel):
    session_id: str = Field("default_session", description="会话ID")
    spu_code: Optional[str] = Field(None, description="当前咨询的商品 SPU 编码")
    query: str = Field(..., min_length=1, description="买家提问原话")
    history: List[ChatMessage] = Field(default_factory=list, description="近期历史问答")

class ChatMeta(BaseModel):
    prompt_version: str = "v2.0.0"
    cost_ms: int = 0
    is_cached: bool = False
    tokens_used: Optional[int] = None

