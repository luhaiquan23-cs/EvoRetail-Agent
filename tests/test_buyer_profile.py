import os
import sys
import uuid
import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from backend.core.database import db
from backend.core.models.buyer_profile import BuyerProfile

def test_buyer_profile_merge_and_overwrite():
    # 1. 首次提取买家画像
    p1 = BuyerProfile(
        budget_max=6000.0,
        identity="大学生",
        use_cases=["日常办公", "英雄联盟"],
        portability_priority=True,
        candidate_spus=["HP-ZHAN-66-G5"]
    )
    assert p1.budget_max == 6000.0
    assert len(p1.use_cases) == 2

    # 2. 增量更新：买家改口提高预算到 8000，且追加了新的游戏需求
    p2 = BuyerProfile(
        budget_max=8000.0,
        use_cases=["英雄联盟", "黑神话悟空", "剪映剪辑"],
        candidate_spus=["HP-VICTUS-16"]
    )
    p1.merge(p2)

    # 验证预算上限成功改口覆盖
    assert p1.budget_max == 8000.0
    # 验证身份与便携优先原样保留
    assert p1.identity == "大学生"
    assert p1.portability_priority is True
    # 验证使用场景去重追加 (2 + 2 = 4)
    assert len(p1.use_cases) == 4
    assert "黑神话悟空" in p1.use_cases
    assert "英雄联盟" in p1.use_cases
    # 验证候选机型去重追加
    assert len(p1.candidate_spus) == 2
    assert "HP-VICTUS-16" in p1.candidate_spus
    print("[PASS] BuyerProfile merge and overwrite logic verified.")

def test_buyer_profile_to_prompt_context():
    p = BuyerProfile(
        identity="建筑系学生",
        budget_max=7500.0,
        use_cases=["CAD建模", "Lumion渲染"],
        portability_priority=False
    )
    ctx = p.to_prompt_context()
    assert "建筑系学生" in ctx
    assert "7500" in ctx
    assert "CAD建模" in ctx
    assert "Lumion渲染" in ctx
    assert "长记忆常驻" in ctx
    print("[PASS] BuyerProfile to_prompt_context formatting verified.")

def test_buyer_profile_sqlite_persistence():
    session_id = f"sess_profile_test_{uuid.uuid4().hex[:8]}"

    # 1. 保存
    p = BuyerProfile(
        budget_min=4000.0,
        budget_max=6500.0,
        identity="独立设计师",
        use_cases=["Photoshop", "Lightroom调色"],
        portability_priority=True,
        candidate_spus=["HP-STAR-BOOK-PRO-14"]
    )
    db.save_buyer_profile(session_id, p)

    # 2. 读取并比对
    loaded = db.get_buyer_profile(session_id)
    assert loaded is not None
    assert loaded.identity == "独立设计师"
    assert loaded.budget_min == 4000.0
    assert loaded.budget_max == 6500.0
    assert "Lightroom调色" in loaded.use_cases
    assert loaded.portability_priority is True
    assert loaded.candidate_spus == ["HP-STAR-BOOK-PRO-14"]

    # 3. 再次更新后读取
    p.merge(BuyerProfile(budget_max=7200.0, use_cases=["Blender简模"]))
    db.save_buyer_profile(session_id, p)

    reloaded = db.get_buyer_profile(session_id)
    assert reloaded is not None
    assert reloaded.budget_max == 7200.0
    assert len(reloaded.use_cases) == 3
    print("[PASS] BuyerProfile SQLite cross-request persistence verified.")

if __name__ == "__main__":
    test_buyer_profile_merge_and_overwrite()
    test_buyer_profile_to_prompt_context()
    test_buyer_profile_sqlite_persistence()
    print("\n[ALL PASS] All buyer profile unit tests passed successfully!")

