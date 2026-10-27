import os
import sys
import json
import uuid
import asyncio

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from fastapi.testclient import TestClient
from backend.api.server import app
from backend.core.database import db

def test_api():
    client = TestClient(app)

    # 1. 验证健康检查接口
    res = client.get("/health")
    assert res.status_code == 200
    assert res.json()["status"] == "ok"
    print("[PASS] GET /health passed")

    # 2. 验证商品列表接口
    res = client.get("/api/v1/products/list")
    assert res.status_code == 200
    products = res.json()["data"]
    assert len(products) >= 3
    print(f"[PASS] GET /api/v1/products/list passed, found {len(products)} products")

    # 3. 验证指定商品接口
    res = client.get("/api/v1/products/HP-VICTUS-16")
    assert res.status_code == 200
    detail = res.json()["data"]
    assert detail["hardware"]["tgp_watt"] == 140
    print("[PASS] GET /api/v1/products/HP-VICTUS-16 passed")

    # 4. 验证流式 SSE 问答接口
    chat_payload = {
        "session_id": "test_sess_001",
        "spu_code": "HP-VICTUS-16",
        "query": "这款光影精灵能自己加装第二根固态硬盘吗？",
        "history": []
    }
    with client.stream("POST", "/api/v1/chat/completions", json=chat_payload) as response:
        assert response.status_code == 200
        assert "text/event-stream" in response.headers["content-type"]
        chunks = []
        for line in response.iter_lines():
            if line:
                chunks.append(line)
        assert len(chunks) > 0
        assert any("[DONE]" in c for c in chunks)
        print(f"[PASS] POST /api/v1/chat/completions SSE stream passed ({len(chunks)} events)")

def test_chat_writes_conversation_log():
    client = TestClient(app)
    with db.get_connection() as conn:
        count_before = conn.execute("SELECT COUNT(*) FROM conversation_logs").fetchone()[0]

    unique_query = f"这款光影16屏幕亮度是多少尼特？unique_{uuid.uuid4().hex[:8]}"
    session_id = f"test_log_sess_{uuid.uuid4().hex[:8]}"
    chat_payload = {
        "session_id": session_id,
        "spu_code": "HP-VICTUS-16",
        "query": unique_query,
        "history": []
    }

    events = []
    with client.stream("POST", "/api/v1/chat/completions", json=chat_payload) as response:
        assert response.status_code == 200
        assert "text/event-stream" in response.headers["content-type"]
        for line in response.iter_lines():
            if line and line.startswith("data: "):
                data_str = line[len("data: "):].strip()
                if data_str != "[DONE]":
                    events.append(json.loads(data_str))

    # 断言 SSE 事件流里没有 error
    error_events = [e for e in events if e.get("type") == "error"]
    assert len(error_events) == 0, f"Found error events in SSE stream: {error_events}"

    # 断言最后有 meta 事件
    meta_events = [e for e in events if e.get("type") == "meta"]
    assert len(meta_events) > 0, "No meta event found in SSE stream"

    # 断言日志表行数 +1，且内容一致
    with db.get_connection() as conn:
        count_after = conn.execute("SELECT COUNT(*) FROM conversation_logs").fetchone()[0]
        latest_row = conn.execute("SELECT * FROM conversation_logs ORDER BY id DESC LIMIT 1").fetchone()

    assert count_after == count_before + 1, f"Expected {count_before + 1} logs, found {count_after}"
    assert latest_row["session_id"] == session_id
    assert latest_row["user_query"] == unique_query
    assert len(latest_row["agent_response"]) > 0
    print("[PASS] test_chat_writes_conversation_log passed, conversation correctly logged!")

def test_chat_tool_call_sse_event():
    client = TestClient(app)
    chat_payload = {
        "session_id": f"test_tool_{uuid.uuid4().hex[:8]}",
        "spu_code": "HP-VICTUS-16",
        "query": f"光影精灵16和暗影精灵16 Slim比哪个更轻？差多少钱？_{uuid.uuid4().hex[:6]}",
        "history": []
    }

    events = []
    with client.stream("POST", "/api/v1/chat/completions", json=chat_payload) as response:
        assert response.status_code == 200
        for line in response.iter_lines():
            if line and line.startswith("data: "):
                data_str = line[len("data: "):].strip()
                if data_str != "[DONE]":
                    events.append(json.loads(data_str))

    tool_events = [e for e in events if e.get("type") == "tool_call"]
    assert len(tool_events) >= 1, "Expected at least 1 tool_call event in SSE stream"
    assert tool_events[0]["tool_name"] == "compare_products"
    meta_event = next(e for e in events if e.get("type") == "meta")
    assert meta_event["tools_called_count"] >= 1
    print("[PASS] test_chat_tool_call_sse_event captured tool_call event in SSE stream!")

def test_chat_sessions_and_history_endpoints():
    client = TestClient(app)
    # 1. 验证获取会话列表接口
    res = client.get("/api/v1/chat/sessions")
    assert res.status_code == 200
    data = res.json()
    assert data["code"] == 200
    sessions = data["data"]
    assert isinstance(sessions, list)
    assert len(sessions) > 0
    first_session_id = sessions[0]["session_id"]
    assert "title_summary" in sessions[0]
    assert "message_count" in sessions[0]

    # 2. 验证根据 session_id 获取历史消息接口
    res_hist = client.get(f"/api/v1/chat/history?session_id={first_session_id}")
    assert res_hist.status_code == 200
    hist_data = res_hist.json()
    assert hist_data["code"] == 200
    assert hist_data["data"]["session_id"] == first_session_id
    messages = hist_data["data"]["messages"]
    assert isinstance(messages, list)
    assert len(messages) > 0
    assert messages[0]["role"] in ["user", "assistant"]

if __name__ == "__main__":
    test_api()
    test_chat_writes_conversation_log()
    test_chat_tool_call_sse_event()
    test_chat_sessions_and_history_endpoints()
    print("\n[ALL PASS] All API endpoints tested successfully!")

