from fastapi import APIRouter, HTTPException, Depends
from backend.core.models.product_specs import ProductItem
from backend.core.database import db
from backend.core.cache import local_cache
from backend.api.auth import verify_admin_token

router = APIRouter(prefix="/products", tags=["Products"])

@router.get("/list")
async def list_products():
    """获取所有在售 3C 商品列表与规格参数"""
    return {"code": 200, "data": await db.async_list_products()}

@router.get("/{spu_code}")
async def get_product_detail(spu_code: str):
    """获取指定 SPU 的详细硬件规格"""
    product = await db.async_get_product(spu_code)
    if not product:
        raise HTTPException(status_code=404, detail=f"未找到 SPU 为 {spu_code} 的商品")
    return {"code": 200, "data": product.model_dump()}

@router.post("/sync", dependencies=[Depends(verify_admin_token)])
async def sync_product(payload: ProductItem):
    """
    PIM 强类型规格同步入库通道 (需管理员鉴权)
    经 Pydantic 校验通过后更新数据库，并广播失效本地该商品的问答缓存
    """
    await db.async_save_product(payload)
    local_cache.invalidate_spu(payload.spu_code)
    return {
        "code": 200,
        "message": f"SPU [{payload.spu_code}] 规格已通过 Pydantic v2 强校验并成功更新，缓存已同步失效",
        "data": payload.model_dump()
    }

