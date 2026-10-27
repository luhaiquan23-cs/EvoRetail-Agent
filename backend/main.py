"""
FastAPI 应用入口兼容模块
同时支持 `uvicorn backend.api.server:app` 与 `uvicorn backend.main:app` 启动。
"""
import os
import uvicorn
from backend.api.server import app, lifespan

__all__ = ["app", "lifespan"]

if __name__ == "__main__":
    port = int(os.getenv("SERVER_PORT", "8000"))
    uvicorn.run("backend.api.server:app", host="0.0.0.0", port=port, reload=True)

