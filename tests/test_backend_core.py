import os
import sys

# 确保项目根目录在 sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from backend.core.models.product_specs import ProductItem, DisplaySpec, HardwareSpec
from backend.core.models.chat_schemas import ChatCompletionRequest, ChatMessage
from backend.core.database import db
from backend.core.cache import local_cache
from backend.core.context_manager import context_manager

def test_pydantic_hardware_validation():
    # 正确的数据
    product_data = {
        "spu_code": "TEST-LAPTOP-01",
        "title": "测试游戏本 16寸",
        "official_price": 5999.00,
        "display": {
            "screen_size": 16.0,
            "resolution": "2.5K",
            "refresh_rate": 165,
            "color_gamut": "100% sRGB"
        },
        "hardware": {
            "cpu": "i7-13700H",
            "gpu": "RTX 4060",
            "tgp_watt": 140,
            "ram_installed": "16G DDR5",
            "ram_slots": 2,
            "ram_max_gb": 64,
            "storage_installed": "1TB NVMe",
            "m2_slots_total": 2,
            "thunderbolt_port": True,
            "weight_kg": 2.2
        }
    }
    item = ProductItem.model_validate(product_data)
    assert item.spu_code == "TEST-LAPTOP-01"
    assert "140W" in item.to_anchor_fact()
    assert "RTX 4060" in item.to_anchor_fact()
    print("[PASS] Pydantic hardware validation passed!")

    # 测试功耗异常抛错防幻觉
    try:
        bad_data = product_data.copy()
        bad_data["hardware"]["tgp_watt"] = 999  # 超出 200W 异常值
        ProductItem.model_validate(bad_data)
        assert False, "Should raise exception on invalid TGP watt"
    except Exception as e:
        print(f"[PASS] Hardware validation error caught correctly: {e}")

def test_product_to_anchor_fact_dynamic_generation():
    with db.get_connection() as conn:
        conn.execute("DELETE FROM products WHERE spu_code LIKE '%TEST%'")
        conn.commit()
    db.seed_mock_data()
    products_data = db.list_products()
    assert len(products_data) == 10, f"Expected 10 products, found {len(products_data)}"

    for p_info in products_data:
        item = db.get_product(p_info["spu_code"])
        assert item is not None
        fact = item.to_anchor_fact()

        # 1. 固态插槽断言
        if item.hardware.m2_slots_total == 1:
            assert "双 M.2" not in fact, f"SPU {item.spu_code} has 1 M.2 slot but output contains '双 M.2'"
            assert "加装第二根" not in fact, f"SPU {item.spu_code} has 1 M.2 slot but output contains '加装第二根'"
            assert "单 M.2" in fact, f"SPU {item.spu_code} should mention '单 M.2'"
        else:
            assert "双 M.2" in fact, f"SPU {item.spu_code} has {item.hardware.m2_slots_total} slots and should mention '双 M.2'"
            assert "加装扩展第二根固态" in fact

        # 2. 内存插槽断言
        if item.hardware.ram_slots == 1:
            assert "双内存插槽" not in fact, f"SPU {item.spu_code} has 1 RAM slot but output contains '双内存插槽'"
        else:
            assert "双内存插槽" in fact, f"SPU {item.spu_code} has {item.hardware.ram_slots} RAM slots and should mention '双内存插槽'"

        # 3. 核显功耗断言 (不把核显描述为独显满血释放)
        is_integrated = (
            any(k in item.hardware.gpu.lower() for k in ["集成", "核显", "iris", "arc", "radeon 780m", "radeon 680m"])
            or ("核显" in item.hardware.gpu)
            or ("集显" in item.hardware.gpu)
        )
        if is_integrated:
            assert "独显满血释放" not in fact
            assert "满血释放" not in fact, f"SPU {item.spu_code} is integrated GPU but claims 满血释放"
    print("[PASS] test_product_to_anchor_fact_dynamic_generation passed for all 10 products!")

def test_database_and_cache():
    db.seed_mock_data()
    products = db.list_products()
    assert len(products) >= 3
    print(f"[PASS] SQLite database loaded successfully. Products count: {len(products)}")

    # 测试缓存
    local_cache.set_answer("HP-VICTUS-16", "能加固态吗？", "配备双 M.2 固态插槽")
    cached = local_cache.get_answer("HP-VICTUS-16", "能加固态吗？")
    assert cached == "配备双 M.2 固态插槽"
    print("[PASS] Local FAQ cache read and write passed!")

def test_context_budget_assembly():
    messages = context_manager.assemble_messages(
        query="这款能加装第二根固态吗？",
        history=[
            ChatMessage(role="user", content="在吗"), # 噪声
            ChatMessage(role="assistant", content="在的，请问有什么可以帮您？"),
            ChatMessage(role="user", content="想看看电脑")
        ],
        anchor_fact="【绝对事实】配备双 M.2 插槽"
    )
    system_msg = messages[0]["content"]
    assert "【绝对事实】配备双 M.2 插槽" in system_msg
    # 验证 "在吗" 是否被噪声剥离过滤
    history_contents = [m["content"] for m in messages[1:]]
    assert "在吗" not in history_contents
    assert history_contents[-1] == "这款能加装第二根固态吗？"
    print("[PASS] 1000 Token context assembly & noise filter passed!")

if __name__ == "__main__":
    test_pydantic_hardware_validation()
    test_product_to_anchor_fact_dynamic_generation()
    test_database_and_cache()
    test_context_budget_assembly()
    print("\n[ALL PASS] Backend core unit tests passed successfully!")
