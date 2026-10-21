import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from backend.rag.hybrid_retriever import hybrid_retriever

def test_hybrid_retrieval():
    hybrid_retriever.load_and_index_docs()

    # 测试问题 1: 固态硬盘与保修政策
    q1 = "我自己加装第二根固态硬盘，会不会影响全国联保？"
    res1 = hybrid_retriever.retrieve(q1, top_k=1)
    assert "不影响整机全国联保" in res1
    assert "M.2" in res1 or "固态" in res1
    print("[PASS] Test query 1 (SSD & Warranty) recalled accurately")

    # 测试问题 2: 快递物流时效
    q2 = "你们店发什么快递？今天买什么时候发货？"
    res2 = hybrid_retriever.retrieve(q2, top_k=1)
    assert "顺丰速运" in res2 or "顺丰特快" in res2
    print("[PASS] Test query 2 (Shipping & Express) recalled accurately")

    # 测试问题 3: 发热与狂暴模式
    q3 = "玩游戏的时候发热很大，风扇很响正常吗？"
    res3 = hybrid_retriever.retrieve(q3, top_k=1)
    assert "85℃~95℃" in res3 or "狂暴模式" in res3 or "过热自降频" in res3
    print("[PASS] Test query 3 (Cooling & Temperature) recalled accurately")

if __name__ == "__main__":
    test_hybrid_retrieval()
    print("\n[ALL PASS] Hybrid retriever tests passed successfully!")

