import os
import sys
import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from backend.core.database import db
from backend.agent.tools import (
    get_product_detail,
    compare_products,
    filter_products,
    search_policy_kb,
    resolve_spu,
    AGENT_TOOLS_SCHEMA,
    AGENT_TOOLS_MAP
)

def test_agent_tools_schema_validity():
    assert len(AGENT_TOOLS_SCHEMA) == 4
    for tool_def in AGENT_TOOLS_SCHEMA:
        assert tool_def["type"] == "function"
        fn_name = tool_def["function"]["name"]
        assert fn_name in AGENT_TOOLS_MAP
        assert "description" in tool_def["function"]
        assert "parameters" in tool_def["function"]

def test_filter_products_max_price():
    db.seed_mock_data()
    # 1. 调用 filter_products(max_price=6000)
    result = filter_products(max_price=6000)
    assert result["total_matched"] > 0
    for p in result["products"]:
        assert p["official_price"] <= 6000, f"Product {p['spu_code']} price {p['official_price']} > 6000"

    # 2. 与直接查询 SQLite 比对
    with db.get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT spu_code FROM products WHERE is_active = 1 AND official_price <= 6000 ORDER BY official_price ASC")
        db_spus = [r["spu_code"] for r in cursor.fetchall()]

    tool_spus = [p["spu_code"] for p in result["products"]]
    assert tool_spus == db_spus, f"Tool result {tool_spus} != DB result {db_spus}"
    print(f"[PASS] filter_products(max_price=6000) matched {len(tool_spus)} products, perfectly identical to SQLite query.")

def test_compare_products_details_and_diff():
    res = compare_products(["HP-VICTUS-16", "HP-OMEN-16-SLIM"])
    assert res["found"] is True
    assert res["comparison_count"] == 2

    table = res["comparison_table"]
    spus = [t["spu_code"] for t in table]
    assert "HP-VICTUS-16" in spus
    assert "HP-OMEN-16-SLIM" in spus

    victus = next(t for t in table if t["spu_code"] == "HP-VICTUS-16")
    omen = next(t for t in table if t["spu_code"] == "HP-OMEN-16-SLIM")

    assert victus["official_price"] == 6999.00
    assert victus["weight_kg"] == 2.3
    assert victus["thunderbolt"] == "未配备雷电4"

    assert omen["official_price"] == 8999.00
    assert omen["weight_kg"] == 2.1
    assert omen["thunderbolt"] == "支持雷电4"

    diff = res["diff_summary"]
    assert diff["price_diff_yuan"] == 2000.00
    assert diff["weight_diff_kg"] == 0.2
    assert diff["cheapest_spu"] == "HP-VICTUS-16"
    assert diff["lightest_spu"] == "HP-OMEN-16-SLIM"

    # 测试模糊别名解析对比
    fuzzy_res = compare_products(["光影精灵16", "暗影精灵16 Slim"])
    assert fuzzy_res["found"] is True
    assert fuzzy_res["diff_summary"]["price_diff_yuan"] == 2000.00
    print("[PASS] compare_products passed with exact price and weight diff calculation.")

def test_get_product_detail_not_exist():
    res = get_product_detail("NOT-EXIST")
    assert res["found"] is False
    assert "error" in res
    assert "未找到" in res["error"]

    # 正常存在的商品
    ok_res = get_product_detail("HP-STAR-BOOK-PRO-14")
    assert ok_res["found"] is True
    assert ok_res["spu_code"] == "HP-STAR-BOOK-PRO-14"
    assert "anchor_fact" in ok_res
    print("[PASS] get_product_detail non-existent handling and normal lookup verified.")

def test_search_policy_kb():
    res = search_policy_kb("加装固态影响保修吗？")
    assert res["hits_count"] > 0
    assert len(res["results"]) > 0
    print(f"[PASS] search_policy_kb retrieved {res['hits_count']} relevant policy chunks.")

if __name__ == "__main__":
    test_agent_tools_schema_validity()
    test_filter_products_max_price()
    test_compare_products_details_and_diff()
    test_get_product_detail_not_exist()
    test_search_policy_kb()
    print("\n[ALL PASS] All agent tools unit tests passed successfully!")

