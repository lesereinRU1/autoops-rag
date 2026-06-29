from __future__ import annotations

import argparse
import concurrent.futures
import json
import math
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
EVAL_FILE = ROOT / "data" / "eval" / "gold_questions.jsonl"
REPORT_FILE = ROOT / "reports" / "runtime_benchmark.json"
API_URL = "http://127.0.0.1:8000"


def percentile(values: list[float], value: float) -> float:
    ordered = sorted(values)
    index = max(0, math.ceil(len(ordered) * value) - 1)
    return ordered[index]


def post_chat(question: dict, session_id: str) -> dict:
    payload = {
        "query": question["question"],
        "model": question.get("model", "S7-1200"),
        "version": "",
        "top_k": 5,
        "strategy": "hybrid",
        "session_id": session_id,
    }
    request = urllib.request.Request(
        f"{API_URL}/api/chat",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json; charset=utf-8"},
        method="POST",
    )
    started = time.perf_counter()
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            data = json.loads(response.read().decode("utf-8"))
            status = response.status
    except (urllib.error.URLError, TimeoutError) as exc:
        return {"ok": False, "status": 0, "latency_ms": (time.perf_counter() - started) * 1000, "error": str(exc)}
    return {
        "ok": status == 200,
        "status": status,
        "latency_ms": (time.perf_counter() - started) * 1000,
        "service_ms": data.get("runtime", {}).get("total_ms", 0.0),
        "external_llm_calls": data.get("runtime", {}).get("external_llm_calls", 0),
        "external_token_usage": data.get("runtime", {}).get("external_token_usage", 0),
    }


def clear_session(session_id: str) -> None:
    request = urllib.request.Request(
        f"{API_URL}/api/sessions/{urllib.parse.quote(session_id)}", method="DELETE"
    )
    try:
        with urllib.request.urlopen(request, timeout=15):
            pass
    except urllib.error.URLError:
        pass


def run_level(questions: list[dict], concurrency: int, requests_count: int) -> dict:
    work = [questions[index % len(questions)] for index in range(requests_count)]
    session_ids = [f"runtime-{concurrency}-{uuid.uuid4().hex}" for _ in work]
    wall_started = time.perf_counter()
    with concurrent.futures.ThreadPoolExecutor(max_workers=concurrency) as executor:
        futures = [
            executor.submit(post_chat, question, session_id)
            for question, session_id in zip(work, session_ids, strict=True)
        ]
        results = [future.result() for future in futures]
    wall_seconds = time.perf_counter() - wall_started
    with concurrent.futures.ThreadPoolExecutor(max_workers=min(8, concurrency)) as executor:
        list(executor.map(clear_session, session_ids))
    successes = [result for result in results if result["ok"]]
    latencies = [result["latency_ms"] for result in successes]
    service_times = [result["service_ms"] for result in successes]
    return {
        "concurrency": concurrency,
        "requests": requests_count,
        "successes": len(successes),
        "success_rate": round(len(successes) / requests_count, 4),
        "wall_seconds": round(wall_seconds, 3),
        "throughput_rps": round(len(successes) / wall_seconds, 3),
        "latency_p50_ms": round(percentile(latencies, 0.50), 2),
        "latency_p95_ms": round(percentile(latencies, 0.95), 2),
        "latency_max_ms": round(max(latencies), 2),
        "service_p50_ms": round(percentile(service_times, 0.50), 2),
        "external_llm_calls": sum(result["external_llm_calls"] for result in successes),
        "external_token_usage": sum(result["external_token_usage"] or 0 for result in successes),
        "errors": [result.get("error", f"HTTP {result['status']}") for result in results if not result["ok"]],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="测试问答接口在1/4/8并发下的耗时和吞吐量")
    parser.add_argument("--requests", type=int, default=12, help="每个并发级别的请求数")
    args = parser.parse_args()
    with urllib.request.urlopen(f"{API_URL}/health", timeout=10) as response:
        health = json.loads(response.read().decode("utf-8"))
    questions = [
        json.loads(line)
        for line in EVAL_FILE.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    report = {
        "endpoint": "/api/chat",
        "corpus_chunks": health["indexed_chunks"],
        "embedding_backend": health["embedding_backend"],
        "llm_enabled": health["llm_enabled"],
        "qdrant_mode": health.get("qdrant_mode", "unknown"),
        "max_concurrent_queries": health.get("max_concurrent_queries"),
        "request_timeout_seconds": health.get("request_timeout_seconds"),
        "rate_limit_per_minute": health.get("rate_limit_per_minute"),
        "levels": [run_level(questions, level, args.requests) for level in (1, 4, 8)],
        "notes": [
            "Results are from the current Windows single-machine environment.",
            "Queries share a read lock; index rebuild and shutdown use an exclusive write lock.",
            "Local Qdrant supports one process only. Use Qdrant Server before adding multiple API workers.",
            "CPU embedding and SQLite writes can still limit throughput at higher concurrency.",
            "This benchmark measures industrial manual Q&A, not code repair tasks.",
        ],
    }
    REPORT_FILE.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
