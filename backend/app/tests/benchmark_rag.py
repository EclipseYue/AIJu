"""
RAG Benchmark — measures retrieval accuracy across chunk sizes.

Usage:
    cd backend
    python -m app.tests.benchmark_rag

Requires the API server to be running on http://localhost:8000
(or set AIJU_API_BASE env variable).

Outputs hit@3 / hit@5 per chunk_size config, plus a summary table
suitable for pasting into docs/需求分析.md or Agent 架构说明.md.
"""

import asyncio
import os
import sys
import time

API_BASE = os.getenv("AIJU_API_BASE", "http://localhost:8000")

# ── Benchmark cases ──
# (question, expected_chapter_keyword)
# Designed for the 3 loaded medical textbooks:
#   01_局部解剖学, 02_组织学与胚胎学, 04_医学微生物学
CASES = [
    ("细菌的基本结构有哪些？", "细菌的形态与结构"),
    ("什么是细胞壁？", "细菌的形态与结构"),
    ("肽聚糖是什么？", "细菌的形态与结构"),
    ("病毒的基本性状是什么？", "病毒的基本性状"),
    ("细菌的感染与免疫机制是什么？", "细菌的感染与免疫"),
    ("肠杆菌科有哪些特征？", "肠杆菌科"),
    ("什么是螺旋体？", "螺旋体"),
    ("细菌的特殊结构包括哪些？", "细菌的形态与结构"),
    ("什么是人体的分部？", "分部"),
    ("解剖器械的使用方法是什么？", "解剖器械"),
]


async def query_rag(question: str, top_k: int, textbook_ids: list[str] | None = None) -> dict:
    """Call the RAG query endpoint."""
    import json
    import urllib.request

    payload = json.dumps({
        "question": question,
        "top_k": top_k,
        "textbook_ids": textbook_ids or [],
    }).encode("utf-8")
    req = urllib.request.Request(
        f"{API_BASE}/api/rag/query",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read())


async def index_rag(textbook_ids: list[str], chunk_size: int) -> dict:
    """Rebuild the RAG index with the given chunk_size."""
    import json
    import urllib.request

    payload = json.dumps({
        "textbook_ids": textbook_ids,
        "chunk_size": chunk_size,
        "overlap_size": max(50, chunk_size // 8),
    }).encode("utf-8")
    req = urllib.request.Request(
        f"{API_BASE}/api/rag/index",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        return json.loads(resp.read())


def hit_at_k(result: dict, expected_keyword: str, k: int) -> bool:
    """Check if any of the top-k citations contain the expected keyword."""
    citations = result.get("citations", [])[:k]
    return any(expected_keyword in c.get("chapter", "") for c in citations)


async def run_benchmark(chunk_size: int = 650) -> dict[str, float]:
    """Run all cases and return hit@k scores."""
    # Index with current chunk_size
    textbook_ids = ["book_aa8ecf95", "book_bf090a58", "book_0070a22f"]
    index_res = await index_rag(textbook_ids, chunk_size)
    print(f"  Indexed {index_res['chunk_count']} chunks (chunk_size={chunk_size})")

    hit3_count = 0
    hit5_count = 0
    total = len(CASES)
    results: list[tuple[str, bool, bool]] = []

    for question, expected in CASES:
        try:
            result = await query_rag(question, top_k=5)
            h3 = hit_at_k(result, expected, 3)
            h5 = hit_at_k(result, expected, 5)
            if h3:
                hit3_count += 1
            if h5:
                hit5_count += 1
            results.append((question, h3, h5))
        except Exception as exc:
            print(f"  FAIL [{question}]: {exc}")

    hit3 = hit3_count / total if total else 0
    hit5 = hit5_count / total if total else 0

    # Print per-case results
    for q, h3, h5 in results:
        status = "✅" if h3 else ("⚠" if h5 else "❌")
        print(f"  {status} {q[:30]:30s}  hit@3={'Y' if h3 else 'N'}  hit@5={'Y' if h5 else 'N'}")

    return {"chunk_size": chunk_size, "total": total, "hit@3": round(hit3, 3), "hit@5": round(hit5, 3)}


async def main() -> None:
    print("=" * 60)
    print("AIJu RAG Benchmark")
    print("=" * 60)
    print()

    configs = [300, 650, 900]
    all_results: list[dict] = []

    for cs in configs:
        print(f"\n── chunk_size = {cs} ──")
        t0 = time.monotonic()
        result = await run_benchmark(chunk_size=cs)
        elapsed = time.monotonic() - t0
        result["elapsed_s"] = round(elapsed, 1)
        all_results.append(result)
        print(f"  Time: {elapsed:.1f}s")
        print(f"  hit@3: {result['hit@3']:.1%}  hit@5: {result['hit@5']:.1%}")

    # Summary table
    print("\n" + "=" * 60)
    print("Summary Table (paste into docs)")
    print("=" * 60)
    print(f"{'chunk_size':>12} | {'hit@3':>8} | {'hit@5':>8} | {'time':>8} | {'chunks':>8}")
    print("-" * 55)
    for r in all_results:
        print(
            f"{r['chunk_size']:>12} | "
            f"{r['hit@3']:>8.1%} | "
            f"{r['hit@5']:>8.1%} | "
            f"{r.get('elapsed_s', 0):>7.1f}s | "
            f"{r.get('total', 0):>8}"
        )


if __name__ == "__main__":
    asyncio.run(main())
