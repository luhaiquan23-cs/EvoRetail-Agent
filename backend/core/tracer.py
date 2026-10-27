import time
import uuid
import logging
from typing import Optional, List, Dict, Any
from backend.core.database import db

logger = logging.getLogger("tracer")

class TraceSpan:
    """代表单次端到端请求的调用链路"""

    def __init__(
        self,
        session_id: str,
        spu_code: Optional[str] = None,
        prompt_version: str = "v2.0.0",
        trace_id: Optional[str] = None
    ):
        self.trace_id = trace_id or f"tr-{uuid.uuid4().hex[:12]}"
        self.session_id = session_id
        self.spu_code = spu_code
        self.prompt_version = prompt_version
        self.start_time = time.time()
        self.first_token_time: Optional[float] = None
        self.ttft_ms: int = 0
        self.total_cost_ms: int = 0
        self.llm_mode: str = "mock"
        self.tools_called: List[Dict[str, Any]] = []
        self.input_tokens: int = 0
        self.output_tokens: int = 0
        self.is_cached: bool = False
        self.guardrail_triggered: bool = False

    def mark_first_token(self):
        """记录流式输出首字产生耗时 (Time to First Token)"""
        if self.first_token_time is None:
            self.first_token_time = time.time()
            self.ttft_ms = max(1, int((self.first_token_time - self.start_time) * 1000))

    def record_tool_call(self, tool_event: Dict[str, Any]):
        """记录工具调用轨迹"""
        self.tools_called.append(tool_event)

    def record_guardrail(self, triggered: bool = True):
        """记录是否触发输出端护栏拦截或修正"""
        if triggered:
            self.guardrail_triggered = True

    def build_trace_dict(
        self,
        llm_mode: Optional[str] = None,
        input_tokens: Optional[int] = None,
        output_tokens: Optional[int] = None,
        is_cached: Optional[bool] = None
    ) -> Dict[str, Any]:
        """构建链路字典并计算总耗时"""
        end_time = time.time()
        self.total_cost_ms = max(1, int((end_time - self.start_time) * 1000))
        if self.ttft_ms == 0:
            self.ttft_ms = self.total_cost_ms

        if llm_mode is not None:
            self.llm_mode = llm_mode
        if input_tokens is not None:
            self.input_tokens = input_tokens
        if output_tokens is not None:
            self.output_tokens = output_tokens
        if is_cached is not None:
            self.is_cached = is_cached

        return {
            "trace_id": self.trace_id,
            "session_id": self.session_id,
            "spu_code": self.spu_code,
            "prompt_version": self.prompt_version,
            "llm_mode": self.llm_mode,
            "tools_called": self.tools_called,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "ttft_ms": self.ttft_ms,
            "total_cost_ms": self.total_cost_ms,
            "is_cached": self.is_cached,
            "guardrail_triggered": self.guardrail_triggered
        }

    def finish(
        self,
        llm_mode: Optional[str] = None,
        input_tokens: Optional[int] = None,
        output_tokens: Optional[int] = None,
        is_cached: Optional[bool] = None
    ) -> Dict[str, Any]:
        """同步落库保存"""
        trace_data = self.build_trace_dict(llm_mode, input_tokens, output_tokens, is_cached)
        db.save_trace(trace_data)
        return trace_data

    async def async_finish(
        self,
        llm_mode: Optional[str] = None,
        input_tokens: Optional[int] = None,
        output_tokens: Optional[int] = None,
        is_cached: Optional[bool] = None
    ) -> Dict[str, Any]:
        """异步非阻塞落库保存"""
        trace_data = self.build_trace_dict(llm_mode, input_tokens, output_tokens, is_cached)
        await db.async_save_trace(trace_data)
        return trace_data


class Tracer:
    """全链路追踪管理器单例"""

    def start_trace(
        self,
        session_id: str,
        spu_code: Optional[str] = None,
        prompt_version: str = "v2.0.0",
        trace_id: Optional[str] = None
    ) -> TraceSpan:
        """开启一条新的端到端追踪链"""
        return TraceSpan(
            session_id=session_id,
            spu_code=spu_code,
            prompt_version=prompt_version,
            trace_id=trace_id
        )

    def get_trace(self, trace_id: str) -> Optional[Dict[str, Any]]:
        """查询指定 trace_id 详情"""
        return db.get_trace(trace_id)

    async def async_get_trace(self, trace_id: str) -> Optional[Dict[str, Any]]:
        """异步查询指定 trace_id 详情"""
        return await db.async_get_trace(trace_id)


tracer = Tracer()

