import pytest
from fastapi.testclient import TestClient
from backend.api.server import app
from backend.core.limiter import SlidingWindowRateLimiter, session_rate_limiter

client = TestClient(app)

def test_sliding_window_rate_limiter_unit():
    """单元测试：滑动窗口限流器的基本放行与截断能力"""
    limiter = SlidingWindowRateLimiter(max_requests=5, window_seconds=10)
    key = "test_user_unit"
    for i in range(5):
        assert limiter.is_allowed(key) is True, f"Request {i+1} should be permitted"
    # 第 6 次超过限制
    assert limiter.is_allowed(key) is False
    assert limiter.get_remaining(key) == 0

def test_chat_rate_limiting_http_429():
    """
    验收标准：
    同一 session_id 高频刷接口触发 HTTP 429
    """
    session_rate_limiter.reset()
    target_session = "session_flood_test_429"
    payload = {
        "session_id": target_session,
        "spu_code": "SPU-Y9000P-2024",
        "query": "你好在吗？",
        "history": []
    }

    # 默认阈值 15 次/分钟：前 15 次请求均应被放行 (200 OK)
    for i in range(15):
        res = client.post("/api/v1/chat/completions", json=payload)
        assert res.status_code == 200, f"Request #{i+1} should be 200, got {res.status_code}"
        _ = res.text  # 必须完整消费流式响应，释放连接池避免连接泄漏

    # 第 16 次同 session 请求必须被拦截并返回 429 Too Many Requests
    flood_res = client.post("/api/v1/chat/completions", json=payload)
    assert flood_res.status_code == 429, f"Request #16 must trigger 429, got {flood_res.status_code}"
    assert "Rate limit exceeded" in flood_res.json().get("detail", "")

    # 另一个 session_id 不受影响，仍应被放行 (200 OK)
    other_payload = {
        "session_id": "session_normal_user_888",
        "spu_code": "SPU-Y9000P-2024",
        "query": "你好在吗？",
        "history": []
    }
    other_res = client.post("/api/v1/chat/completions", json=other_payload)
    assert other_res.status_code == 200
    _ = other_res.text
