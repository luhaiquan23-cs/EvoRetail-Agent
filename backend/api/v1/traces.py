import logging
from fastapi import APIRouter, HTTPException
from backend.core.tracer import tracer

logger = logging.getLogger("traces_api")

router = APIRouter(prefix="/traces", tags=["Traces"])

@router.get("/{trace_id}")
async def get_trace(trace_id: str):
    """
    根据 trace_id 查询单次问答的全链路追踪记录
    包含 prompt_version, llm_mode, tools_called, input_tokens, output_tokens, ttft_ms, total_cost_ms 等
    """
    record = await tracer.async_get_trace(trace_id)
    if not record:
        raise HTTPException(status_code=404, detail=f"Trace with ID '{trace_id}' not found")
    return record

