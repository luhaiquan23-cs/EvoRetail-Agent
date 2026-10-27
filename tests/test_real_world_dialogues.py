import json
import pytest
import asyncio
import re
from backend.agent.runner import agent_runner
from backend.agent.tools import resolve_spu, ALIAS_MAP, compare_products, filter_products
from backend.agent.slot_extractor import SlotExtractor
from backend.guardrails.output_guard import output_guardrail
from backend.core.database import db
from backend.core.context_manager import ContextBudgetManager

def test_case_1_anti_hallucination_battery_80_hours():
    """
    用例 1：反常识超长续航提问（暗影精灵10电池续航能否达到80小时）
    验证：明确反驳“不能达到80小时”，不出现续航幻觉，不发生答非所问
    """
    async def _run():
        query = "你好，这款暗影精灵10旗舰版（HP-OMEN-10-PRO）的电池续航能达到 80 小时吗？"
        cm = ContextBudgetManager()
        messages = cm.assemble_messages(query=query, history=[])
        
        events = []
        async for ev in agent_runner.run(messages=messages, spu_code="HP-OMEN-10-PRO", force_mock=True):
            if ev["type"] == "chunk":
                events.append(ev["content"])
                
        reply = "".join(events)
        sanitized, _ = output_guardrail.guard_text(reply, spu_code="HP-OMEN-10-PRO")
        
        assert any(k in sanitized for k in ["无法达到 80 小时", "不能达到 80 小时", "无法达到", "不存在 80 小时"]), (
            f"必须正面纠正 80 小时续航荒谬性，实际回复: {sanitized}"
        )
    asyncio.run(_run())


def test_case_2_cross_laptop_comparison_math_and_upgrade_answer():
    """
    用例 2：战66五代与光影精灵16对比（加装固态与内存）
    验证：
    1. 战66价格为 4299（绝不被护栏篡改为 6999）
    2. 光影精灵16价格为 6999
    3. 差价正确计算为 2700 元
    4. 战66重量为 1.7kg，差重 0.6kg（绝不被篡改为 2.3kg）
    5. 正面回答支持双 M.2 固态与双通道内存加装
    """
    async def _run():
        query = "战66五代（HP-ZHAN-66-G5）和光影精灵16，能自己加装第二根固态硬盘和升级双通道内存吗？"
        cm = ContextBudgetManager()
        messages = cm.assemble_messages(query=query, history=[])
        
        # 模拟前端当前聚焦在 HP-VICTUS-16 页面
        events = []
        async for ev in agent_runner.run(messages=messages, spu_code="HP-VICTUS-16", force_mock=True):
            if ev["type"] == "chunk":
                events.append(ev["content"])
                
        raw_reply = "".join(events)
        # 经过护栏
        sanitized, guard_evs = output_guardrail.guard_text(raw_reply, spu_code="HP-VICTUS-16")
        
        # 检查战 66 的价格与重量
        assert "4299" in sanitized, f"战66价格 ¥4299 丢失，回复文本: {sanitized}"
        assert "6999" in sanitized, f"光影精灵16价格 ¥6999 丢失，回复文本: {sanitized}"
        assert "2700" in sanitized, f"差价 2700 元计算错误，回复文本: {sanitized}"
        assert "1.7kg" in sanitized or "1.7 kg" in sanitized, f"战66重量 1.7kg 丢失，回复文本: {sanitized}"
        assert "0.6kg" in sanitized or "0.6 kg" in sanitized, f"差重 0.6kg 计算错误或被篡改，回复文本: {sanitized}"
        assert "2.3kg" in sanitized, f"光影精灵16重量 2.3kg 必须存在"
        # 绝不能出现战66相对更轻 2.3kg 的荒唐现象
        assert "相对更轻 2.3kg" not in sanitized
        assert "加装" in sanitized and ("固态" in sanitized or "M.2" in sanitized)
    asyncio.run(_run())


def test_case_3_query_different_laptop_star_book_14():
    """
    用例 3：在光影精灵16页面询问星 Book Pro 14 是否为 140W 满血独显
    验证：
    1. 护栏不将星 Book Pro 14 篡改为 2.3kg 或 140W
    2. 不出现 '双 M.2 插槽（支持加装第二根固态） 插槽（仅支持替换升级）' 拼接语病
    """
    p_star = db.get_product("HP-STAR-BOOK-PRO-14")
    assert p_star is not None
    assert p_star.hardware.weight_kg == 1.44
    assert p_star.hardware.tgp_watt == 54
    assert p_star.hardware.m2_slots_total == 1

    sample_clause = "星 Book Pro 14（¥5499）重量仅 1.44kg，核显能效释放 54W，单 M.2 插槽（仅支持替换升级）。"
    # 即使默认传了 HP-VICTUS-16
    p_victus = db.get_product("HP-VICTUS-16")
    sanitized, evs = output_guardrail.guard_text(sample_clause, spu_code="HP-VICTUS-16", product=p_victus)
    
    assert "1.44kg" in sanitized, f"重量不应被篡改为 2.3kg，得到: {sanitized}"
    assert "54W" in sanitized, f"功耗不应被篡改为 140W，得到: {sanitized}"
    assert "5499" in sanitized, f"价格不应被篡改为 6999，得到: {sanitized}"
    assert "双 M.2 插槽（支持加装第二根固态） 插槽" not in sanitized, f"语病拼接存在: {sanitized}"


def test_case_4_budget_filter_under_5000_compliance():
    """
    用例 4：预算 5000 以内推荐
    验证：
    1. filter_products 返回的机型价格严格 <= 5000
    2. 本地意图筛选返回机型官方价绝不出现 ¥6999
    """
    flt = filter_products(max_price=5000.0)
    assert flt["total_matched"] > 0
    for p in flt["products"]:
        assert p["official_price"] <= 5000.0, f"机型 {p['spu_code']} 价格 {p['official_price']} 超出 5000"

    async def _run():
        query = "如果我预算压到 5000 以内，平时基本不玩大型游戏，只要轻薄便携、续航长，换成哪款"
        cm = ContextBudgetManager()
        messages = cm.assemble_messages(query=query, history=[])
        
        events = []
        async for ev in agent_runner.run(messages=messages, spu_code="HP-VICTUS-16", force_mock=True):
            if ev["type"] == "chunk":
                events.append(ev["content"])
                
        reply = "".join(events)
        sanitized, _ = output_guardrail.guard_text(reply, spu_code="HP-VICTUS-16")
        
        # 筛选出的机型价格应该 <= 5000 (例如 4199 或 4299)，绝不能被护栏覆写为 6999
        assert ("4199" in sanitized or "4299" in sanitized), f"5000以内机型售价未展示: {sanitized}"
        # 绝不能对 5000 预算买家声称 6999 的机型符合预算
        assert "官方售价 ¥6999" not in sanitized
    asyncio.run(_run())


def test_case_5_space_insensitive_spu_resolution():
    """
    用例 5：型号归一化（带空格与括号的别名解析）
    验证：
    1. '暗影精灵 16 Slim' 准确解析为 HP-OMEN-16-SLIM（绝不被解析为暗影精灵10）
    2. '战 99 移动工作站' 准确解析为 HP-ZHAN-99-G5
    3. SlotExtractor 在自然语言中同时提取两者
    """
    assert resolve_spu("暗影精灵 16 Slim") == "HP-OMEN-16-SLIM"
    assert resolve_spu("暗影精灵16 Slim") == "HP-OMEN-16-SLIM"
    assert resolve_spu("战 99 移动工作站") == "HP-ZHAN-99-G5"
    assert resolve_spu("战99 移动工作站") == "HP-ZHAN-99-G5"

    extractor = SlotExtractor()
    query = "请帮我对比一下【暗影精灵 16 Slim】和【战 99 移动工作站】"
    profile = extractor.extract_from_text(query)
    
    assert "HP-OMEN-16-SLIM" in profile.candidate_spus, f"未提取到 HP-OMEN-16-SLIM: {profile.candidate_spus}"
    assert "HP-ZHAN-99-G5" in profile.candidate_spus, f"未提取到 HP-ZHAN-99-G5: {profile.candidate_spus}"


def test_case_6_no_2240hz_table_chunking_bug():
    """
    用例 6：Markdown 表格流式分片绝不腰斩数字产生 2240Hz 荒谬参数
    """
    async def _run():
        table_row = "| **屏幕刷新率** | 16.1 英寸 2.5K（2560×1440）**240Hz** | 16.0 英寸 2.5K（2560×1600）16:10 **60Hz** |\n"
        
        # 模拟逐字/逐小 chunk 流式下发
        async def mock_stream():
            for i in range(0, len(table_row), 3):
                yield table_row[i:i+3]
                
        p_omen = db.get_product("HP-OMEN-16-SLIM")
        collected = []
        async for chunk in output_guardrail.guard_stream(mock_stream(), spu_code="HP-OMEN-16-SLIM", product=p_omen):
            collected.append(chunk)
            
        full_text = "".join(collected)
        assert "2240Hz" not in full_text, f"2240Hz 刷新率腰斩 Bug 仍存在: {full_text}"
        assert "240Hz" in full_text, f"原始 240Hz 应保持完整: {full_text}"
        assert "60Hz" in full_text, f"原始 60Hz 应保持完整: {full_text}"
    asyncio.run(_run())

