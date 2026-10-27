import json
import re
from typing import Dict, Any, List, Optional
from pydantic import BaseModel, Field

from backend.core.database import db
from backend.core.models.product_specs import ProductItem
from backend.rag.hybrid_retriever import hybrid_retriever

# ---------------------------------------------------------
# 1. Pydantic 工具入参模型
# ---------------------------------------------------------

class GetProductDetailInput(BaseModel):
    spu_code: str = Field(..., description="商品 SPU 编码或型号名称 (如 HP-VICTUS-16 或 光影精灵16)")

class CompareProductsInput(BaseModel):
    spu_codes: List[str] = Field(..., description="待对比的 2~4 个商品 SPU 编码或型号名称列表")

class FilterProductsInput(BaseModel):
    max_price: Optional[float] = Field(None, description="最高预算上限 (元)")
    min_price: Optional[float] = Field(None, description="最低预算下限 (元)")
    category: Optional[str] = Field(None, description="品类偏好 (如 游戏笔记本 / 轻薄办公本 / 设计师工作站)")
    min_tgp_watt: Optional[int] = Field(None, description="最低 GPU 功耗要求 (W)")
    max_weight_kg: Optional[float] = Field(None, description="最大机身重量限制 (kg)")
    need_thunderbolt: Optional[bool] = Field(None, description="是否必须具备雷电4接口")

class SearchPolicyKbInput(BaseModel):
    query: str = Field(..., description="售后服务、发货政策、发票或质保相关的咨询问题")

# ---------------------------------------------------------
# 2. 辅助型号模糊解析器
# ---------------------------------------------------------

ALIAS_MAP = {
    "光影精灵16": "HP-VICTUS-16",
    "光影16": "HP-VICTUS-16",
    "victus 16": "HP-VICTUS-16",
    "victus16": "HP-VICTUS-16",
    "暗影精灵16 slim": "HP-OMEN-16-SLIM",
    "暗影精灵16slim": "HP-OMEN-16-SLIM",
    "暗影16 slim": "HP-OMEN-16-SLIM",
    "暗影16slim": "HP-OMEN-16-SLIM",
    "omen 16 slim": "HP-OMEN-16-SLIM",
    "omen16slim": "HP-OMEN-16-SLIM",
    "战66五代": "HP-ZHAN-66-G5",
    "战66 5代": "HP-ZHAN-66-G5",
    "战66六代": "HP-ZHAN-66-G5",
    "战66 6代": "HP-ZHAN-66-G5",
    "战66": "HP-ZHAN-66-G5",
    "暗影精灵10旗舰版": "HP-OMEN-10-PRO",
    "暗影精灵10 旗舰版": "HP-OMEN-10-PRO",
    "暗影10旗舰版": "HP-OMEN-10-PRO",
    "暗影10 pro": "HP-OMEN-10-PRO",
    "暗影精灵10 slim 14": "HP-OMEN-TRANSCEND-14",
    "暗影10 slim 14": "HP-OMEN-TRANSCEND-14",
    "transcend 14": "HP-OMEN-TRANSCEND-14",
    "战99": "HP-ZHAN-99-G5",
    "战 99": "HP-ZHAN-99-G5",
    "战99移动工作站": "HP-ZHAN-99-G5",
    "战 99 移动工作站": "HP-ZHAN-99-G5",
    "星book pro 14": "HP-STAR-BOOK-PRO-14",
    "星 book pro 14": "HP-STAR-BOOK-PRO-14",
    "星book 14": "HP-STAR-BOOK-PRO-14",
    "星book14": "HP-STAR-BOOK-PRO-14",
    "战x": "HP-ZHAN-X-14-G10",
    "战 x": "HP-ZHAN-X-14-G10",
    "光影精灵10": "HP-VICTUS-15-FA",
    "光影10": "HP-VICTUS-15-FA",
    "战66七代": "HP-ZHAN-66-G7-RYZEN",
    "战66 7代": "HP-ZHAN-66-G7-RYZEN",
    "战66七代锐龙版": "HP-ZHAN-66-G7-RYZEN",
    "战66 7代锐龙版": "HP-ZHAN-66-G7-RYZEN",
}

def resolve_spu(identifier: str) -> Optional[str]:
    """将型号俗称或 SPU 编码标准化解析为真实的 SPU 编码（支持空格、连字符模糊归一化）"""
    norm = identifier.strip().upper()
    all_products = db.list_products()
    all_spus = [p["spu_code"] for p in all_products]

    if norm in all_spus:
        return norm

    # 去除空格、标点、连字符进行纯净归一化匹配
    norm_clean = re.sub(r"[\s\-_\(\)（）【】\[\]]+", "", identifier.strip().lower())

    # 查别名表（按别名长度倒序，长串优先匹配）
    sorted_aliases = sorted(ALIAS_MAP.items(), key=lambda x: len(x[0]), reverse=True)
    for alias, spu in sorted_aliases:
        alias_clean = re.sub(r"[\s\-_\(\)（）【】\[\]]+", "", alias.lower())
        if alias_clean in norm_clean or norm_clean in alias_clean:
            return spu

    # 模糊包含匹配商品库 title / SPU
    for p in all_products:
        title_clean = re.sub(r"[\s\-_\(\)（）【】\[\]]+", "", p["title"].lower())
        spu_clean = re.sub(r"[\s\-_\(\)（）【】\[\]]+", "", p["spu_code"].lower())
        if norm_clean in title_clean or spu_clean in norm_clean or norm_clean in spu_clean:
            return p["spu_code"]

    return None

# ---------------------------------------------------------
# 3. 核心工具执行函数
# ---------------------------------------------------------

def get_product_detail(spu_code: str) -> Dict[str, Any]:
    """
    根据 SPU 编码获取商品完整规格与防幻觉锚定事实
    """
    actual_spu = resolve_spu(spu_code) or spu_code
    product = db.get_product(actual_spu)
    if not product:
        return {
            "error": f"商品 '{spu_code}' 未找到，请核对商品型号是否在售",
            "found": False,
            "spu_code": spu_code
        }

    return {
        "found": True,
        "spu_code": product.spu_code,
        "title": product.title,
        "category": product.category,
        "official_price": product.official_price,
        "anchor_fact": product.to_anchor_fact(),
        "specs": product.model_dump()
    }

def compare_products(spu_codes: List[str]) -> Dict[str, Any]:
    """
    多款商品同字段横向对比表 (价格、CPU、GPU、TGP功耗、屏幕素质、插槽数、雷电接口、重量)
    """
    if not spu_codes or len(spu_codes) < 2:
        return {"error": "对比至少需要指定 2 款商品", "found": False}

    resolved_items: List[ProductItem] = []
    for code in spu_codes[:4]:
        spu = resolve_spu(code)
        if spu:
            item = db.get_product(spu)
            if item and item not in resolved_items:
                resolved_items.append(item)

    if len(resolved_items) < 2:
        return {
            "error": f"未能解析出至少 2 款有效在售机型进行对比 (输入: {spu_codes})",
            "found": False
        }

    table = []
    for item in resolved_items:
        table.append({
            "spu_code": item.spu_code,
            "title": item.title,
            "official_price": item.official_price,
            "cpu": item.hardware.cpu,
            "gpu": item.hardware.gpu,
            "tgp_watt": item.hardware.tgp_watt,
            "screen": f"{item.display.screen_size}寸 {item.display.resolution} {item.display.refresh_rate}Hz",
            "ram_slots": item.hardware.ram_slots,
            "m2_slots": item.hardware.m2_slots_total,
            "thunderbolt": "支持雷电4" if item.hardware.thunderbolt_port else "未配备雷电4",
            "weight_kg": item.hardware.weight_kg
        })

    # 计算关键差异摘要
    prices = [t["official_price"] for t in table]
    weights = [t["weight_kg"] for t in table]
    price_diff = round(max(prices) - min(prices), 2)
    weight_diff = round(max(weights) - min(weights), 2)

    diff_summary = {
        "price_diff_yuan": price_diff,
        "weight_diff_kg": weight_diff,
        "cheapest_spu": min(table, key=lambda x: x["official_price"])["spu_code"],
        "lightest_spu": min(table, key=lambda x: x["weight_kg"])["spu_code"]
    }

    return {
        "found": True,
        "comparison_count": len(table),
        "comparison_table": table,
        "diff_summary": diff_summary
    }

def filter_products(
    max_price: Optional[float] = None,
    min_price: Optional[float] = None,
    category: Optional[str] = None,
    min_tgp_watt: Optional[int] = None,
    max_weight_kg: Optional[float] = None,
    need_thunderbolt: Optional[bool] = None
) -> Dict[str, Any]:
    """
    多维属性筛选符合条件的商品列表，并按价格升序排序
    """
    raw_products = db.list_products()
    matched = []

    for item in raw_products:
        spu = item["spu_code"]
        product = db.get_product(spu)
        if not product:
            continue

        price = product.official_price
        if max_price is not None and price > max_price:
            continue
        if min_price is not None and price < min_price:
            continue
        if category and category not in product.category and category not in product.title:
            continue
        if min_tgp_watt is not None and product.hardware.tgp_watt < min_tgp_watt:
            continue
        if max_weight_kg is not None and product.hardware.weight_kg > max_weight_kg:
            continue
        if need_thunderbolt is not None and bool(product.hardware.thunderbolt_port) != need_thunderbolt:
            continue

        matched.append({
            "spu_code": product.spu_code,
            "title": product.title,
            "category": product.category,
            "official_price": product.official_price,
            "cpu": product.hardware.cpu,
            "gpu": product.hardware.gpu,
            "tgp_watt": product.hardware.tgp_watt,
            "weight_kg": product.hardware.weight_kg,
            "m2_slots": product.hardware.m2_slots_total,
            "thunderbolt": product.hardware.thunderbolt_port
        })

    matched.sort(key=lambda x: x["official_price"])

    return {
        "total_matched": len(matched),
        "filters_applied": {
            "max_price": max_price,
            "min_price": min_price,
            "category": category,
            "min_tgp_watt": min_tgp_watt,
            "max_weight_kg": max_weight_kg,
            "need_thunderbolt": need_thunderbolt
        },
        "products": matched
    }

def search_policy_kb(query: str) -> Dict[str, Any]:
    """
    售后政策与售后知识库混合检索
    """
    results = hybrid_retriever.retrieve(query, top_k=3)
    return {
        "query": query,
        "hits_count": len(results),
        "results": results
    }

# ---------------------------------------------------------
# 4. OpenAI Tools JSON Schema 声明与映射表
# ---------------------------------------------------------

AGENT_TOOLS_SCHEMA = [
    {
        "type": "function",
        "function": {
            "name": "get_product_detail",
            "description": "获取单个商品的完整规格事实与权威数据。当买家咨询某一款具体笔记本的详细参数、扩展性或赠品时调用。",
            "parameters": {
                "type": "object",
                "properties": {
                    "spu_code": {
                        "type": "string",
                        "description": "商品 SPU 编码或型号名称 (如 HP-VICTUS-16 或 光影精灵16)"
                    }
                },
                "required": ["spu_code"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "compare_products",
            "description": "对 2~4 款商品进行横向多维度参数对比 (差价、重量差、性能、屏幕、接口)。当买家在多款商品间犹豫、纠结或询问哪款更轻、差多少钱时调用。",
            "parameters": {
                "type": "object",
                "properties": {
                    "spu_codes": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "待对比的 2~4 个型号或 SPU 列表 (如 ['光影精灵16', '暗影精灵16 Slim'])"
                    }
                },
                "required": ["spu_codes"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "filter_products",
            "description": "根据买家的预算范围 (最高价/最低价)、品类要求 (轻薄办公/游戏本/工作站)、显卡功耗、重量便携性、雷电接口等条件筛选在售商品。",
            "parameters": {
                "type": "object",
                "properties": {
                    "max_price": {"type": "number", "description": "最高预算 (元)"},
                    "min_price": {"type": "number", "description": "最低预算 (元)"},
                    "category": {"type": "string", "description": "品类或用途分类"},
                    "min_tgp_watt": {"type": "integer", "description": "最低 GPU 释放功耗 (W)"},
                    "max_weight_kg": {"type": "number", "description": "最大裸机重量 (kg)"},
                    "need_thunderbolt": {"type": "boolean", "description": "是否需要雷电4接口"}
                }
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "search_policy_kb",
            "description": "检索惠普官方售前售后知识库，包括退换货政策、全国联保政策、加装固态保修规则、顺丰发货时效、晒单赠品领取规则等。",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "检索问题"
                    }
                },
                "required": ["query"]
            }
        }
    }
]

AGENT_TOOLS_MAP = {
    "get_product_detail": get_product_detail,
    "compare_products": compare_products,
    "filter_products": filter_products,
    "search_policy_kb": search_policy_kb
}

