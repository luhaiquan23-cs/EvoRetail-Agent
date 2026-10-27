import os
import logging
from typing import Optional
from fastapi import Header, HTTPException, status

logger = logging.getLogger("auth")

DEFAULT_DEV_ADMIN_TOKEN = "dev-secret-admin-token-2024"

def get_admin_token() -> str:
    """获取预期的管理员令牌"""
    token = os.getenv("ADMIN_API_TOKEN")
    if not token:
        logger.warning(
            "[SECURITY WARNING] ADMIN_API_TOKEN is not configured in environment. "
            f"Using insecure fallback developer token '{DEFAULT_DEV_ADMIN_TOKEN}'."
        )
        return DEFAULT_DEV_ADMIN_TOKEN
    return token

async def verify_admin_token(x_admin_token: Optional[str] = Header(None, alias="X-Admin-Token")):
    """
    敏感线上管理操作请求头鉴权
    校验请求头 X-Admin-Token，缺失或不匹配返回 HTTP 401
    """
    expected = get_admin_token()
    if not x_admin_token or x_admin_token != expected:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Unauthorized: Missing or invalid X-Admin-Token header"
        )
    return x_admin_token

