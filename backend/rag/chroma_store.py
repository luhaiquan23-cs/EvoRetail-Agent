import os
from typing import List, Dict, Any, Tuple
import chromadb
from fastembed import TextEmbedding

DEFAULT_CHROMA_DIR = os.path.join(os.path.dirname(__file__), "../../data/chroma_db")

class LocalChromaStore:
    """
    本地嵌入式 ChromaDB 向量知识库
    基于 FastEmbed (BAAI/bge-small-zh-v1.5) 中文轻量 ONNX 模型进行向量化
    """
    def __init__(self, persist_dir: str = DEFAULT_CHROMA_DIR):
        self.persist_dir = persist_dir
        os.makedirs(self.persist_dir, exist_ok=True)
        self.client = chromadb.PersistentClient(path=self.persist_dir)
        self.collection = self.client.get_or_create_collection(
            name="ecommerce_knowledge_zh",
            metadata={"hnsw:space": "cosine"}
        )
        self.embedding_model = TextEmbedding("BAAI/bge-small-zh-v1.5")

    def embed_texts(self, texts: List[str]) -> List[List[float]]:
        """批量获取中文文本的向量表示"""
        embeddings = list(self.embedding_model.embed(texts))
        return [emb.tolist() for emb in embeddings]

    def add_documents(self, docs: List[Dict[str, Any]]):
        """
        向 Chroma 集合增量导入中文知识片段
        docs: [{"id": "...", "content": "...", "metadata": {...}}]
        """
        if not docs:
            return

        ids = [doc["id"] for doc in docs]
        documents = [doc["content"] for doc in docs]
        metadatas = [doc.get("metadata", {}) for doc in docs]

        # 本地 CPU ONNX 生成高质量中文向量
        embeddings = self.embed_texts(documents)

        self.collection.upsert(
            ids=ids,
            documents=documents,
            embeddings=embeddings,
            metadatas=metadatas
        )

    def search(self, query: str, top_k: int = 3) -> List[Tuple[Dict[str, Any], float]]:
        """语义向量检索"""
        try:
            query_vector = self.embed_texts([query])[0]
            results = self.collection.query(
                query_embeddings=[query_vector],
                n_results=top_k
            )
            items = []
            if results and results["documents"] and results["documents"][0]:
                for idx, doc_text in enumerate(results["documents"][0]):
                    doc_id = results["ids"][0][idx]
                    metadata = results["metadatas"][0][idx] if results["metadatas"] else {}
                    distance = results["distances"][0][idx] if results.get("distances") else 0.5
                    # cosine distance to similarity
                    similarity = max(0.0, 1.0 - distance)
                    items.append(({"id": doc_id, "content": doc_text, "metadata": metadata}, similarity))
            return items
        except Exception as e:
            print(f"[WARN] Chroma query error: {e}")
            return []

chroma_store = LocalChromaStore()
