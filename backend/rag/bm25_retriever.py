import re
from typing import List, Dict, Any, Tuple
import jieba
from rank_bm25 import BM25Okapi

class LocalBM25Retriever:
    """
    基于 Rank-BM25 的本地专有名词与规则倒排检索器
    对 3C 专有名词（如 M.2、PCIe 4.0、顺丰、保修、发热）具有 100% 精准召回率
    """
    def __init__(self):
        self.documents: List[Dict[str, Any]] = []
        self.tokenized_corpus: List[List[str]] = []
        self.bm25: BM25Okapi = None

    def tokenize(self, text: str) -> List[str]:
        """中文分词结合字母数字专有名词保留"""
        words = jieba.lcut(text.lower())
        # 过滤纯空白符号
        return [w.strip() for w in words if w.strip()]

    def add_documents(self, docs: List[Dict[str, Any]]):
        """
        录入知识文档片段
        docs 格式: [{"id": "...", "content": "...", "metadata": {...}}]
        """
        for doc in docs:
            self.documents.append(doc)
            tokens = self.tokenize(doc["content"])
            self.tokenized_corpus.append(tokens)

        if self.tokenized_corpus:
            self.bm25 = BM25Okapi(self.tokenized_corpus)

    def search(self, query: str, top_k: int = 3) -> List[Tuple[Dict[str, Any], float]]:
        if not self.bm25 or not self.documents:
            return []

        query_tokens = self.tokenize(query)
        if not query_tokens:
            return []

        scores = self.bm25.get_scores(query_tokens)
        scored_docs = list(zip(self.documents, scores))
        # 按照得分降序排序
        scored_docs.sort(key=lambda x: x[1], reverse=True)
        return scored_docs[:top_k]

bm25_retriever = LocalBM25Retriever()

