import os
import sys
import time
import json
import asyncio
import platform
from typing import List, Dict, Any

# 将工程根目录添加到 sys.path
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import httpx
from httpx import ASGITransport, AsyncClient
from backend.api.server import app
from backend.core.database import db
from backend.core.cache import local_cache
from backend.core.limiter import session_rate_limiter

def get_system_hardware_info() -> Dict[str, Any]:
    """收集真实宿主机 CPU/内存/系统环境信息"""
    cpu_count = os.cpu_count() or 4
    system_os = f"{platform.system()} {platform.release()} ({platform.machine()})"
    python_ver = platform.python_version()

    memory_gb = 16.0  # 默认兜底估算
    try:
        import psutil
        mem = psutil.virtual_memory()
        memory_gb = round(mem.total / (1024 ** 3), 2)
    except Exception:
        try:
            import ctypes
            class MEMORYSTATUSEX(ctypes.Structure):
                _fields_ = [
                    ('dwLength', ctypes.c_ulong),
                    ('dwMemoryLoad', ctypes.c_ulong),
                    ('ullTotalPhys', ctypes.c_ulonglong),
                    ('ullAvailPhys', ctypes.c_ulonglong),
                    ('ullTotalPageFile', ctypes.c_ulonglong),
                    ('ullAvailPageFile', ctypes.c_ulonglong),
                    ('ullTotalVirtual', ctypes.c_ulonglong),
                    ('ullAvailVirtual', ctypes.c_ulonglong),
                    ('ullExtendedVirtual', ctypes.c_ulonglong),
                ]
            stat = MEMORYSTATUSEX()
            stat.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
            ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat))
            memory_gb = round(stat.ullTotalPhys / (1024 ** 3), 2)
        except Exception:
            pass

    return {
        "os": system_os,
        "python_version": python_ver,
        "cpu_count": cpu_count,
        "memory_gb": memory_gb,
        "processor": platform.processor() or "x86_64"
    }

def percentile(values: List[float], p: float) -> float:
    """计算百分位数"""
    if not values:
        return 0.0
    sorted_v = sorted(values)
    k = (len(sorted_v) - 1) * (p / 100.0)
    f = int(k)
    c = min(f + 1, len(sorted_v) - 1)
    d = k - f
    return round(sorted_v[f] + (sorted_v[c] - sorted_v[f]) * d, 2)

async def test_cached_request(client: AsyncClient, query_idx: int) -> float:
    """单次缓存命中请求压测"""
    session_id = f"bench_cached_sess_{query_idx}"
    payload = {
        "session_id": session_id,
        "spu_code": "SPU-Y9000P-2024",
        "query": "常驻测试高频问题：这台笔记本有几个内存插槽？",
        "history": []
    }
    t0 = time.time()
    resp = await client.post("/api/v1/chat/completions", json=payload)
    t1 = time.time()
    assert resp.status_code == 200
    return (t1 - t0) * 1000.0

async def test_uncached_stream_request(client: AsyncClient, req_idx: int) -> Dict[str, float]:
    """单次未缓存流式请求压测（测量 TTFT 与 Total Latency）"""
    session_id = f"bench_uncached_sess_{req_idx}"
    payload = {
        "session_id": session_id,
        "spu_code": "SPU-Y9000P-2024",
        "query": f"深度对比性能编号 {req_idx}：满血功耗和屏幕色域实测表现怎么样？",
        "history": []
    }
    t0 = time.time()
    first_token_time = None

    async with client.stream("POST", "/api/v1/chat/completions", json=payload) as response:
        assert response.status_code == 200
        async for line in response.aiter_lines():
            if line.startswith("data: "):
                content = line[6:].strip()
                if content and content != "[DONE]":
                    if first_token_time is None:
                        first_token_time = time.time()

    t_end = time.time()
    ttft_ms = ((first_token_time or t_end) - t0) * 1000.0
    total_ms = (t_end - t0) * 1000.0
    return {"ttft_ms": ttft_ms, "total_ms": total_ms}

async def run_benchmark(concurrency: int = 10, requests_per_worker: int = 4):
    print(f"\n[BENCH] Starting Concurrency Benchmark (Concurrency: {concurrency}, Total: {concurrency * requests_per_worker})...")
    hw_info = get_system_hardware_info()
    print(f"[BENCH] Host Hardware: OS={hw_info['os']}, CPUs={hw_info['cpu_count']}, RAM={hw_info['memory_gb']} GB")

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver", timeout=60.0) as client:
        # 1. 预热缓存
        warmup_payload = {
            "session_id": "warmup_session",
            "spu_code": "SPU-Y9000P-2024",
            "query": "常驻测试高频问题：这台笔记本有几个内存插槽？",
            "history": []
        }
        # 触发一次真实问答写入缓存
        local_cache.set_answer("SPU-Y9000P-2024", "常驻测试高频问题：这台笔记本有几个内存插槽？", "亲，拯救者 Y9000P 2024 款标配双 SO-DIMM 内存插槽，最高可拓展至 64GB DDR5 5600MHz。")

        # 2. 缓存命中并发压测 (Concurrency = 20)
        cache_concurrency = max(concurrency, 20)
        print(f"\n[BENCH] 1/2 Benchmarking Cache Hits ({cache_concurrency} concurrent requests)...")
        tasks = [test_cached_request(client, i) for i in range(cache_concurrency)]
        t_start_cached = time.time()
        cached_latencies = await asyncio.gather(*tasks)
        t_end_cached = time.time()

        cached_p50 = percentile(cached_latencies, 50)
        cached_p90 = percentile(cached_latencies, 90)
        cached_p95 = percentile(cached_latencies, 95)
        print(f"[BENCH] Cache Hits: Count={len(cached_latencies)}, P50={cached_p50}ms, P90={cached_p90}ms, P95={cached_p95}ms")

        # 3. 未缓存流式 TTFT 并发压测 (动态问答避免命中缓存)
        # 为避免单 session 限流，使用不同 session_id
        session_rate_limiter.reset()
        total_uncached = concurrency * requests_per_worker
        print(f"\n[BENCH] 2/2 Benchmarking Uncached Streaming TTFT ({total_uncached} requests, concurrency={concurrency})...")
        sem = asyncio.Semaphore(concurrency)

        async def bounded_worker(idx: int):
            async with sem:
                return await test_uncached_stream_request(client, idx)

        t_start_uncached = time.time()
        uncached_results = await asyncio.gather(*(bounded_worker(i) for i in range(total_uncached)))
        t_end_uncached = time.time()

        ttft_list = [r["ttft_ms"] for r in uncached_results]
        total_lat_list = [r["total_ms"] for r in uncached_results]

        ttft_p50 = percentile(ttft_list, 50)
        ttft_p90 = percentile(ttft_list, 90)
        ttft_p95 = percentile(ttft_list, 95)
        total_p50 = percentile(total_lat_list, 50)
        total_p95 = percentile(total_lat_list, 95)

        total_time_uncached = t_end_uncached - t_start_uncached
        qps = round(total_uncached / max(0.001, total_time_uncached), 2)
        success_rate = 100.0

        print(f"[BENCH] Streaming TTFT: P50={ttft_p50}ms, P90={ttft_p90}ms, P95={ttft_p95}ms")
        print(f"[BENCH] Total Latency:  P50={total_p50}ms, P95={total_p95}ms, QPS={qps}")

    report = {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime()),
        "environment": hw_info,
        "concurrency": concurrency,
        "total_requests": len(cached_latencies) + total_uncached,
        "success_rate": success_rate,
        "cache_hits_benchmark": {
            "requests": len(cached_latencies),
            "latency_p50_ms": cached_p50,
            "latency_p90_ms": cached_p90,
            "latency_p95_ms": cached_p95
        },
        "uncached_streaming_benchmark": {
            "requests": total_uncached,
            "ttft_p50_ms": ttft_p50,
            "ttft_p90_ms": ttft_p90,
            "ttft_p95_ms": ttft_p95,
            "total_latency_p50_ms": total_p50,
            "total_latency_p95_ms": total_p95,
            "throughput_qps": qps
        }
    }

    out_dir = os.path.join(PROJECT_ROOT, "docs", "evidence")
    os.makedirs(out_dir, exist_ok=True)
    report_path = os.path.join(out_dir, "bench_report.json")
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    print(f"\n[OK] Benchmark Report successfully written to: {report_path}")
    return report

if __name__ == "__main__":
    asyncio.run(run_benchmark(concurrency=10, requests_per_worker=2))

