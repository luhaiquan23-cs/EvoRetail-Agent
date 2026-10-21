import os
import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from backend.core.database import db
from backend.rag.hybrid_retriever import hybrid_retriever
from backend.api.v1.chat import router as chat_router
from backend.api.v1.products import router as products_router
from backend.api.v1.evolution import router as evolution_router

app = FastAPI(
    title="3C Ecommerce Intelligent CS Agent",
    description="轻量开源自进化 3C 电商智能售前顾问系统",
    version="2.0.0"
)

# 允许跨域（供前端 React Web 访问）
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 注册 API 路由
app.include_router(chat_router, prefix="/api/v1")
app.include_router(products_router, prefix="/api/v1")
app.include_router(evolution_router, prefix="/api/v1")

@app.on_event("startup")
async def startup_event():
    """应用启动时自动检测并录入模拟商品数据与知识库"""
    products = db.list_products()
    if not products:
        print("[INFO] Database empty, seeding mock 3C product specs...")
        db.seed_mock_data()
    print("[INFO] Indexing knowledge documents with HybridRetriever (BM25 + Chroma)...")
    hybrid_retriever.load_and_index_docs()
    print("[INFO] 3C Ecommerce CS API server ready.")

@app.get("/health")
async def health_check():
    return {"status": "ok", "version": "2.0.0", "service": "3C-Ecommerce-Agent"}

if __name__ == "__main__":
    port = int(os.getenv("SERVER_PORT", "8000"))
    uvicorn.run("backend.api.server:app", host="0.0.0.0", port=port, reload=True)
