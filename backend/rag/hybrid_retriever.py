import os
import re
from typing import List, Dict, Any, Tuple
from backend.rag.bm25_retriever import bm25_retriever
from backend.rag.chroma_store import chroma_store

DOCS_DIR = os.path.join(os.path.dirname(__file__), "../../data/knowledge_docs")

class HybridRetriever:
    """
    双引擎混合检索器 (BM25 专有名词倒排 + ChromaDB 语义向量)
    结合 RRF (Reciprocal Rank Fusion) 排名融合算法
    """
    def __init__(self, rrf_k: int = 60):
        self.rrf_k = rrf_k
        self._is_initialized = False

    def load_and_index_docs(self, docs_dir: str = DOCS_DIR):
        """解析并切分本地 Markdown 知识文档入库"""
        if not os.path.exists(docs_dir):
            return

        all_chunks: List[Dict[str, Any]] = []
        chunk_idx = 1

        for fname in os.listdir(docs_dir):
            if not fname.endswith(".md") and not fname.endswith(".txt"):
                continue
            fpath = os.path.join(docs_dir, fname)
            with open(fpath, "r", encoding="utf-8") as f:
                content = f.read()

            # 按二级标题 '## ' 划分知识块
            sections = re.split(r'\n(?=##\s+)', content)
            for sec in sections:
                cleaned_sec = sec.strip()
                if len(cleaned_sec) > 15:  # 忽略太短片段
                    chunk_id = f"chunk_{fname}_{chunk_idx}"
                    all_chunks.append({
                        "id": chunk_id,
                        "content": cleaned_sec,
                        "metadata": {"source": fname, "chunk_index": chunk_idx}
                    })
                    chunk_idx += 1

        if all_chunks:
            # 1. 注入 BM25
            bm25_retriever.add_documents(all_chunks)
            # 2. 注入 Chroma 向量库
            chroma_store.add_documents(all_chunks)
            print(f"[OK] HybridRetriever successfully indexed {len(all_chunks)} knowledge chunks.")

        self._is_initialized = True

    def retrieve(self, query: str, top_k: int = 2) -> str:
        """
        执行双引擎召回并通过 RRF 算法合并，返回控制在 150 Token 左右的精准知识片段
        """
        if not self._is_initialized:
            self.load_and_index_docs()

        # 1. BM25 专有名词召回 Top 3
        bm25_results = bm25_retriever.search(query, top_k=3)
        # 2. Chroma 向量语义召回 Top 3
        chroma_results = chroma_store.search(query, top_k=3)

        # 3. RRF (Reciprocal Rank Fusion) 打分合并
        doc_scores: Dict[str, float] = {}
        doc_map: Dict[str, Dict[str, Any]] = {}

        for rank, (doc, _) in enumerate(bm25_results):
            doc_id = doc["id"]
            doc_map[doc_id] = doc
            doc_scores[doc_id] = doc_scores.get(doc_id, 0.0) + (1.0 / (self.rrf_k + rank + 1))

        for rank, (doc, _) in enumerate(chroma_results):
            doc_id = doc["id"]
            doc_map[doc_id] = doc
            doc_scores[doc_id] = doc_scores.get(doc_id, 0.0) + (1.0 / (self.rrf_k + rank + 1))

        # 按照 RRF 得分降序排序
        sorted_doc_ids = sorted(doc_scores.keys(), key=lambda d_id: doc_scores[d_id], reverse=True)

        if not sorted_doc_ids:
            return ""

        # 提取 Top K 最相关的片段合并
        selected_chunks = []
        for d_id in sorted_doc_ids[:top_k]:
            raw_text = doc_map[d_id]["content"]
            # 简化掉过多 markdown 标题符号
            simplified = re.sub(r'#+\s*', '', raw_text).strip()
            selected_chunks.append(simplified)

        return "\n\n".join(selected_chunks)

hybrid_retriever = HybridRetriever()

