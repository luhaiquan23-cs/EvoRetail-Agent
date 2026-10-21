import os
import sys
import asyncio

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from fastapi.testclient import TestClient
from backend.api.server import app

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

if __name__ == "__main__":
    test_api()
    print("\n[ALL PASS] All API endpoints tested successfully!")

