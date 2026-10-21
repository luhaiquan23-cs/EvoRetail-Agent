import os
import hashlib
from typing import Optional

DEFAULT_CACHE_DIR = os.getenv("CACHE_DIR", os.path.join(os.path.dirname(__file__), "../../data/cache"))

class LocalCache:
    def __init__(self, cache_dir: Optional[str] = None):
        self.cache_dir = cache_dir or DEFAULT_CACHE_DIR
        os.makedirs(self.cache_dir, exist_ok=True)
        try:
            import diskcache
            self._cache = diskcache.Cache(self.cache_dir)
            self._is_diskcache = True
        except ImportError:
            # 轻量内存 Fallback 保证无额外安装时也能运行
            self._cache = {}
            self._is_diskcache = False

    def _generate_key(self, spu_code: Optional[str], query: str) -> str:
        # 去除所有空白和常见标点进行标准化
        normalized = "".join(c for c in query.lower() if c.isalnum() or '\u4e00' <= c <= '\u9fff')
        query_hash = hashlib.md5(normalized.encode("utf-8")).hexdigest()
        return f"faq:{spu_code or 'general'}:{query_hash}"

    def get_answer(self, spu_code: Optional[str], query: str) -> Optional[str]:
        key = self._generate_key(spu_code, query)
        if self._is_diskcache:
            return self._cache.get(key)
        return self._cache.get(key)

    def set_answer(self, spu_code: Optional[str], query: str, answer: str, expire: int = 3600):
        key = self._generate_key(spu_code, query)
        if self._is_diskcache:
            self._cache.set(key, answer, expire=expire)
        else:
            self._cache[key] = answer

    def invalidate_spu(self, spu_code: str):
        """当 SPU 商品规格更新时清理缓存"""
        if self._is_diskcache:
            keys_to_del = [k for k in self._cache if str(k).startswith(f"faq:{spu_code}:")]
            for k in keys_to_del:
                del self._cache[k]
        else:
            keys_to_del = [k for k in self._cache if str(k).startswith(f"faq:{spu_code}:")]
            for k in keys_to_del:
                del self._cache[k]

local_cache = LocalCache()

