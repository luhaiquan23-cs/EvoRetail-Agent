import time
import threading
from collections import defaultdict, deque
from typing import Dict

class SlidingWindowRateLimiter:
    """
    基于滑动时间窗口的轻量高并发限流器
    支持按 session_id 或 IP 限制请求频次
    """

    def __init__(self, max_requests: int = 15, window_seconds: int = 60):
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self._records: Dict[str, deque] = defaultdict(deque)
        self._lock = threading.Lock()

    def is_allowed(self, key: str) -> bool:
        """检查指定 key 是否允许在当前滑动窗口内继续发起请求"""
        now = time.time()
        with self._lock:
            q = self._records[key]
            # 淘汰窗口期外的过期请求时间戳
            cutoff = now - self.window_seconds
            while q and q[0] <= cutoff:
                q.popleft()

            if len(q) < self.max_requests:
                q.append(now)
                return True
            return False

    def get_remaining(self, key: str) -> int:
        """获取当前 key 剩余可用配额"""
        now = time.time()
        with self._lock:
            q = self._records[key]
            cutoff = now - self.window_seconds
            while q and q[0] <= cutoff:
                q.popleft()
            return max(0, self.max_requests - len(q))

    def reset(self):
        """重置所有限流计数器"""
        with self._lock:
            self._records.clear()


# 全局默认会话级限流器（15次/分钟）
session_rate_limiter = SlidingWindowRateLimiter(max_requests=15, window_seconds=60)

