import pytest
from backend.core.models.chat_schemas import ChatMessage
from backend.core.models.buyer_profile import BuyerProfile
from backend.agent.slot_extractor import slot_extractor
from backend.core.context_manager import (
    context_manager,
    count_tokens,
    count_message_tokens,
    count_messages_tokens
)
from backend.core.database import db

def test_token_counting():
    text_cn = "我是建筑系学生，预算7500，用来跑CAD和Lumion"
    tokens_cn = count_tokens(text_cn)
    assert tokens_cn > 10, f"Expected >10 tokens, got {tokens_cn}"

    text_en = "HP Omen 16 with RTX 4060 and 140W TGP"
    tokens_en = count_tokens(text_en)
    assert tokens_en > 5, f"Expected >5 tokens, got {tokens_en}"

    msg = {"role": "user", "content": text_cn}
    msg_tokens = count_message_tokens(msg)
    assert msg_tokens == tokens_cn + count_tokens("user") + 4

def test_20_turns_long_conversation_preserves_profile_and_respects_budget():
    """
    验收标准：
    构造 20 轮长对话（第 1 轮交代“我是建筑系学生，预算7500，用来跑CAD和Lumion”），
    到第 20 轮时总组装 Token 数 ≤ 1000，且组装出的 System 消息中依然完整包含第 1 轮提取的买家画像槽位！
    """
    # 第 1 轮：买家交代身份、预算与核心软件诉求
    turn1_query = "我是建筑系学生，预算7500，用来跑CAD和Lumion"
    profile = slot_extractor.extract_from_text(turn1_query)

    assert profile.identity == "建筑系学生"
    assert profile.budget_max == 7500.0
    assert any("CAD" in uc for uc in profile.use_cases)
    assert any("Lumion" in uc for uc in profile.use_cases)

    # 模拟第 1 轮到第 19 轮的多轮历史问答（共 19 轮问答 = 38 条消息）
    # 每条消息包含真实的客服专业解答（每条约 30~80 字），累积大量历史 Token
    qa_pairs = [
        ("我是建筑系学生，预算7500，用来跑CAD和Lumion",
         "同学您好！建筑学专业需要运行 CAD、Lumion 和 3dsMax，非常考验独立显卡光追算力与大内存容量。推荐您看下暗影精灵9系列。"),
        ("这款暗影精灵9屏幕色彩怎么样？",
         "暗影精灵9配备了 2.5K 240Hz 高刷电竞屏，支持 100% sRGB 高色域，色彩还原非常精准，建筑出图和渲染完全没有色差困扰。"),
        ("散热压得住吗？建模会不会过热降频？",
         "这款搭载了酷凉风暴散热技术，双风扇四出风口设计，显卡支持 140W 满血释放，长时间跑 Lumion 渲染也不会撞温度墙。"),
        ("接口够用吗？我想外接显示器和大容量移动硬盘。",
         "接口非常丰富，配备满速雷电4/全功能Type-C、HDMI 2.1视频输出，还有多个 USB-A 高速接口，外接 4K 显示器和双固态硬盘完全不用转接头。"),
        ("支持加装第二根固态吗？",
         "暗影精灵9内部配备了双 M.2 PCIe 4.0 固态硬盘插槽，支持加装第二根高速 NVMe SSD，非常适合存大型建筑模型和项目归档。"),
        ("原厂内存是单根还是双根？",
         "标配 16GB (8G*2) DDR5 双通道高频内存，主板有两个标准 SO-DIMM 内存插槽，后期最高支持自行拓展至 64GB。"),
        ("键盘打字手感怎么样？",
         "键盘支持全尺寸背光，键程适中回弹扎实，方向键是标准全高尺寸，日常绘图快捷键和写论文都非常顺手。"),
        ("机器重量大概多少？平时带去工作室方便吗？",
         "裸机重量约 2.3kg，对于 16.1 英寸满血性能游戏本来说便携度在正常水准，放在双肩包里带去设计工作室毫无压力。"),
        ("外壳材质是金属的吗？",
         "A面采用精致磨砂工艺金属材质，质感沉稳大气，兼顾了坚固度与防指纹效果，商务会议和日常自习都很体面。"),
        ("电池续航多久？断电能跑渲染吗？",
         "内置 83Wh 大容量电池，离电状态下日常文档与网页浏览约 4-6 小时。不过高性能渲染建议插电使用以保证 140W 满血性能。"),
        ("系统自带正版软件吗？",
         "出厂预装正版 Windows 11 家庭中文版，并且永久激活正版 Office 家庭和学生版，开箱联网激活即可使用。"),
        ("保修政策是怎样的？",
         "享受惠普官方全国联保服务，主要部件享受 2 年质保，支持惠普官方售后服务网点与全国上门快修服务。"),
        ("下单发什么快递？",
         "默认发顺丰速运或京东物流空运直达，支持防震原厂加固包装与开箱验机，保障贵重数码产品安全无损。"),
        ("付款后几天能送到？",
         "核心城市支持次日达或隔日达，一般 48 小时内送达。全国多地旗舰仓就近智能调拨发货。"),
        ("现在买有赠品吗？",
         "当前下单尊享限时开学季礼包，赠送原装电竞双肩背包和高精度游戏鼠标，数量有限送完即止。"),
        ("支持 7 天无理由退换吗？",
         "支持商品未激活未损坏情况下 7 天无理由退换，官方正品保障，让您选购无后顾之忧。"),
        ("支持分期免息吗？",
         "支持花呗与多家主流银行信用卡分期，部分活动期支持最高 6 期免息优惠，具体以收银台实付展示为准。"),
        ("如果买回去遇到软件安装问题能找你们吗？",
         "当然可以！惠普官方提供终身在线技术支持与驱动更新指导，微信与电话工程师随时为您远程排忧解难。"),
        ("好的，那目前仓库存货充足吗？",
         "您关注的这款目前官方现货在库，当天 16:00 前下单当天即可由就近仓安排打包发出。")
    ]

    history: list[ChatMessage] = []
    for q, a in qa_pairs:
        history.append(ChatMessage(role="user", content=q))
        history.append(ChatMessage(role="assistant", content=a))

    assert len(history) == 38, f"Expected 38 history messages, got {len(history)}"

    # 第 20 轮提问
    turn20_query = "那我现在下单可以领到优惠券并尽快发货吗？"

    # 获取商品事实与 RAG 知识
    product = db.get_product("HP-OMEN-16")
    anchor_fact = product.to_anchor_fact() if product else "【商品事实】暗影精灵9，配备双 M.2 插槽，140W 满血 TGP"
    rag_context = "【发货说明】顺丰次日达；【质保说明】全国联保2年。"

    # 执行组装
    assembled_messages = context_manager.assemble_messages(
        query=turn20_query,
        history=history,
        anchor_fact=anchor_fact,
        rag_context=rag_context,
        buyer_profile=profile,
        total_budget=1000
    )

    # 1. 验证总 Token 数不超过 1000 预算
    total_tokens = count_messages_tokens(assembled_messages)
    print(f"Turn 20 Assembled Total Tokens: {total_tokens}")
    assert total_tokens <= 1000, f"Total tokens {total_tokens} exceeded budget 1000!"

    # 2. 验证第一条必须是 system 消息
    assert assembled_messages[0]["role"] == "system"
    system_content = assembled_messages[0]["content"]

    # 3. 验证第 1 轮提取的买家画像槽位完整常驻在 system 中（严禁遗忘！）
    assert "建筑系学生" in system_content, "Buyer identity '建筑系学生' must be preserved!"
    assert "7500" in system_content, "Buyer budget '7500' must be preserved!"
    assert "CAD" in system_content or "Lumion" in system_content, "Buyer software use case must be preserved!"

    # 4. 验证历史消息经过 Token 预算裁剪：最早的第 1 轮问答已从滑动历史中移除（按 Token 边界淘汰）
    history_user_contents = [m["content"] for m in assembled_messages[1:-1] if m["role"] == "user"]
    assert turn1_query not in history_user_contents, "Oldest history message should have been pruned from sliding window!"

    # 5. 验证最后一条消息是当前的买家第 20 轮提问
    assert assembled_messages[-1]["role"] == "user"
    assert assembled_messages[-1]["content"] == turn20_query

def test_noise_filtering_in_history():
    messages = context_manager.assemble_messages(
        query="暗影精灵9显卡功耗多少？",
        history=[
            ChatMessage(role="user", content="在吗"),
            ChatMessage(role="assistant", content="在的呢，有什么可以帮您？"),
            ChatMessage(role="user", content="ok"),
            ChatMessage(role="assistant", content="好的"),
            ChatMessage(role="user", content="想了解下电脑"),
            ChatMessage(role="assistant", content="请问您的主要用途是？")
        ]
    )
    all_contents = [m["content"] for m in messages]
    assert "在吗" not in all_contents
    assert "ok" not in all_contents
    assert "好的" not in all_contents
    assert "想了解下电脑" in all_contents

