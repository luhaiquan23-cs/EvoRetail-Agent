import os
import pytest
from fastapi.testclient import TestClient
from backend.api.server import app
from backend.core.database import db
from backend.api.auth import DEFAULT_DEV_ADMIN_TOKEN

client = TestClient(app)

def test_rollback_auth_missing_token_returns_401():
    """
    验收标准：
    不带 X-Admin-Token 调用 /api/v1/evolution/rollback 返回 401，数据库激活版本不被篡改
    """
    orig_version, _ = db.get_active_prompt()
    target_version = "v1.0.0" if orig_version != "v1.0.0" else "v1.5.0"

    # 1. 不带 Token 发起请求
    resp = client.post("/api/v1/evolution/rollback", json={"target_version": target_version})
    assert resp.status_code == 401, f"Expected 401, got {resp.status_code}"
    assert "Unauthorized" in resp.json().get("detail", "")

    # 2. 验证数据库中处于激活状态的 Prompt 版本未被篡改
    curr_version, _ = db.get_active_prompt()
    assert curr_version == orig_version, f"Version should not change! Expected {orig_version}, got {curr_version}"

def test_rollback_auth_wrong_token_returns_401():
    """
    验收标准：
    携带错误 Token 调用 /api/v1/evolution/rollback 返回 401，数据库激活版本不被篡改
    """
    orig_version, _ = db.get_active_prompt()
    target_version = "v1.0.0" if orig_version != "v1.0.0" else "v1.5.0"

    headers = {"X-Admin-Token": "completely-invalid-attacker-token"}
    resp = client.post("/api/v1/evolution/rollback", json={"target_version": target_version}, headers=headers)
    assert resp.status_code == 401
    assert "Unauthorized" in resp.json().get("detail", "")

    curr_version, _ = db.get_active_prompt()
    assert curr_version == orig_version

def test_rollback_auth_correct_token_returns_200():
    """
    验收标准：
    带正确 Token 调用返回 200，并成功生效回滚
    """
    orig_version, _ = db.get_active_prompt()
    target_version = "v1.5.0" if orig_version != "v1.5.0" else "v2.0.0"

    headers = {"X-Admin-Token": DEFAULT_DEV_ADMIN_TOKEN}
    resp = client.post("/api/v1/evolution/rollback", json={"target_version": target_version}, headers=headers)
    assert resp.status_code == 200
    res_data = resp.json()
    assert res_data["code"] == 200

    curr_version, _ = db.get_active_prompt()
    assert curr_version == target_version

    # 恢复原状
    client.post("/api/v1/evolution/rollback", json={"target_version": orig_version}, headers=headers)

def test_products_sync_requires_admin_token():
    """测试商品更新接口必须受 X-Admin-Token 保护"""
    sample_product = db.get_product("HP-VICTUS-16")
    assert sample_product is not None
    product_payload = sample_product.model_dump()
    product_payload["spu_code"] = "HP-AUTH-TEST-SYNC"
    product_payload["title"] = "鉴权测试机型"

    # 无 Token 返回 401
    resp_unauth = client.post("/api/v1/products/sync", json=product_payload)
    assert resp_unauth.status_code == 401, f"Expected 401, got {resp_unauth.status_code}"

    # 有合法 Token 返回 200
    resp_auth = client.post(
        "/api/v1/products/sync",
        json=product_payload,
        headers={"X-Admin-Token": DEFAULT_DEV_ADMIN_TOKEN}
    )
    assert resp_auth.status_code == 200, f"Expected 200, got {resp_auth.status_code}"
    assert resp_auth.json()["code"] == 200

    # 清理测试数据，保持基准商品池恒定为 10 款
    with db.get_connection() as conn:
        conn.execute("DELETE FROM products WHERE spu_code = 'HP-AUTH-TEST-SYNC'")
        conn.commit()
