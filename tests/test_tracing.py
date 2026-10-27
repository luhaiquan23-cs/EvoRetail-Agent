import json
import pytest
from fastapi.testclient import TestClient
from backend.api.server import app
from backend.core.limiter import session_rate_limiter

client = TestClient(app)

def test_full_link_tracing_and_api():
    """
    验收标准：
    发起一次对话后，调用 GET /api/v1/traces/{trace_id} 能查到完整的链路追踪记录，各字段真实非空
    """
    session_rate_limiter.reset()
    payload = {
        "session_id": "session_tracing_test_001",
        "spu_code": "SPU-Y9000P-2024",
        "query": "这款拯救者玩黑神话悟空卡不卡？屏幕素质怎么样？",
        "history": []
    }

    # 1. 发起流式对话请求
    response = client.post("/api/v1/chat/completions", json=payload)
    assert response.status_code == 200
    assert "X-Trace-Id" in response.headers, "Response header must contain X-Trace-Id"
    trace_id_header = response.headers["X-Trace-Id"]
    assert trace_id_header.startswith("tr-")

    # 2. 解析 SSE 流中最后返回的 meta 事件
    meta_event = None
    chunks = []
    for line in response.text.split("\n"):
        line = line.strip()
        if line.startswith("data: "):
            content = line[6:]
            if content == "[DONE]":
                continue
            try:
                data = json.loads(content)
                if data.get("type") == "meta":
                    meta_event = data
                elif data.get("type") == "chunk":
                    chunks.append(data.get("content", ""))
            except json.JSONDecodeError:
                pass

    assert meta_event is not None, "SSE stream must yield a meta event"
    assert meta_event.get("trace_id") == trace_id_header
    assert len(chunks) > 0

    # 3. 通过 GET /api/v1/traces/{trace_id} 查询持久化记录
    trace_res = client.get(f"/api/v1/traces/{trace_id_header}")
    assert trace_res.status_code == 200, f"Expected 200, got {trace_res.status_code}"
    trace_data = trace_res.json()

    # 4. 严格校验各追踪指标真实非空
    assert trace_data["trace_id"] == trace_id_header
    assert trace_data["session_id"] == "session_tracing_test_001"
    assert trace_data["spu_code"] == "SPU-Y9000P-2024"
    assert trace_data["prompt_version"] != ""
    assert trace_data["llm_mode"] in ["mock", "live", "fallback", "cache"]
    assert isinstance(trace_data["tools_called"], list)
    assert trace_data["input_tokens"] > 0, "Input tokens must be counted"
    assert trace_data["output_tokens"] > 0, "Output tokens must be counted"
    assert trace_data["ttft_ms"] > 0, "TTFT must be measured"
    assert trace_data["total_cost_ms"] >= trace_data["ttft_ms"]
    assert "created_at" in trace_data

def test_trace_not_found():
    """查询不存在的 trace_id 应返回 404"""
    res = client.get("/api/v1/traces/tr-nonexistent-9999")
    assert res.status_code == 404
    assert "not found" in res.json().get("detail", "").lower()
