from __future__ import annotations

import argparse
import collections
import concurrent.futures
import json
import math
import os
import platform
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path
from datetime import datetime


ROOT = Path(__file__).resolve().parents[1]
EVAL_FILE = ROOT / "data" / "eval" / "gold_questions.jsonl"
REPORT_FILE = ROOT / "reports" / "runtime_benchmark.json"
REPORT_MARKDOWN_FILE = ROOT / "reports" / "runtime_benchmark.md"
API_URL = "http://127.0.0.1:8000"


def percentile(values: list[float], value: float) -> float:
    ordered = sorted(values)
    index = max(0, math.ceil(len(ordered) * value) - 1)
    return ordered[index]


def post_chat(question: dict, session_id: str, api_url: str) -> dict:
    payload = {
        "query": question["question"],
        "model": question.get("model", "S7-1200"),
        "version": "",
        "top_k": 5,
        "strategy": "hybrid",
        "session_id": session_id,
    }
    request = urllib.request.Request(
        f"{api_url}/api/chat",
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
        "retrieval_ms": data.get("runtime", {}).get("retrieval_latency_ms", 0.0),
        "llm_ms": data.get("runtime", {}).get("llm_latency_ms", 0.0),
        "external_llm_calls": data.get("runtime", {}).get("external_llm_calls", 0),
        "external_token_usage": data.get("runtime", {}).get("external_token_usage", 0),
        "generation_mode": data.get("runtime", {}).get("generation_mode", "unknown"),
        "fallback_reason": data.get("runtime", {}).get("generation_fallback_reason", ""),
    }


def post_search(question: dict, _session_id: str, api_url: str) -> dict:
    payload = {
        "query": question["question"],
        "model": question.get("model", "S7-1200"),
        "version": "",
        "top_k": 5,
        "strategy": "hybrid",
    }
    request = urllib.request.Request(
        f"{api_url}/api/search",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json; charset=utf-8"},
        method="POST",
    )
    started = time.perf_counter()
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            response.read()
            status = response.status
    except (urllib.error.URLError, TimeoutError) as exc:
        return {
            "ok": False,
            "status": 0,
            "latency_ms": (time.perf_counter() - started) * 1000,
            "error": str(exc),
        }
    latency_ms = (time.perf_counter() - started) * 1000
    return {
        "ok": status == 200,
        "status": status,
        "latency_ms": latency_ms,
        "service_ms": latency_ms,
        "retrieval_ms": latency_ms,
        "llm_ms": 0.0,
        "external_llm_calls": 0,
        "external_token_usage": 0,
        "generation_mode": "not_applicable",
        "fallback_reason": "",
    }


def clear_session(session_id: str, api_url: str) -> None:
    request = urllib.request.Request(
        f"{api_url}/api/sessions/{urllib.parse.quote(session_id)}", method="DELETE"
    )
    try:
        with urllib.request.urlopen(request, timeout=15):
            pass
    except urllib.error.URLError:
        pass


def run_level(
    questions: list[dict],
    concurrency: int,
    requests_count: int,
    endpoint: str,
    api_url: str,
) -> dict:
    work = [questions[index % len(questions)] for index in range(requests_count)]
    session_ids = [f"runtime-{concurrency}-{uuid.uuid4().hex}" for _ in work]
    wall_started = time.perf_counter()
    request_function = post_chat if endpoint == "chat" else post_search
    with concurrent.futures.ThreadPoolExecutor(max_workers=concurrency) as executor:
        futures = [
            executor.submit(request_function, question, session_id, api_url)
            for question, session_id in zip(work, session_ids, strict=True)
        ]
        results = [future.result() for future in futures]
    wall_seconds = time.perf_counter() - wall_started
    with concurrent.futures.ThreadPoolExecutor(max_workers=min(8, concurrency)) as executor:
        if endpoint == "chat":
            list(executor.map(lambda value: clear_session(value, api_url), session_ids))
    successes = [result for result in results if result["ok"]]
    latencies = [result["latency_ms"] for result in successes]
    service_times = [result["service_ms"] for result in successes]
    retrieval_times = [result["retrieval_ms"] for result in successes]
    llm_times = [result["llm_ms"] for result in successes]
    orchestration_times = [
        max(0.0, result["service_ms"] - result["retrieval_ms"] - result["llm_ms"])
        for result in successes
    ]
    generation_modes = collections.Counter(result["generation_mode"] for result in successes)
    fallback_reasons = collections.Counter(
        result["fallback_reason"] for result in successes if result["fallback_reason"]
    )
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
        "service_p95_ms": round(percentile(service_times, 0.95), 2),
        "retrieval_p50_ms": round(percentile(retrieval_times, 0.50), 2),
        "retrieval_p95_ms": round(percentile(retrieval_times, 0.95), 2),
        "llm_p50_ms": round(percentile(llm_times, 0.50), 2),
        "llm_p95_ms": round(percentile(llm_times, 0.95), 2),
        "orchestration_p50_ms": round(percentile(orchestration_times, 0.50), 2),
        "orchestration_p95_ms": round(percentile(orchestration_times, 0.95), 2),
        "external_llm_calls": sum(result["external_llm_calls"] for result in successes),
        "external_token_usage": sum(result["external_token_usage"] or 0 for result in successes),
        "generation_modes": dict(generation_modes),
        "fallback_reasons": dict(fallback_reasons),
        "errors": [result.get("error", f"HTTP {result['status']}") for result in results if not result["ok"]],
    }


def warm_up(questions: list[dict], count: int, endpoint: str, api_url: str) -> None:
    request_function = post_chat if endpoint == "chat" else post_search
    for index in range(count):
        session_id = f"warmup-{uuid.uuid4().hex}"
        result = request_function(questions[index % len(questions)], session_id, api_url)
        if endpoint == "chat":
            clear_session(session_id, api_url)
        if not result["ok"]:
            raise RuntimeError(f"warm-up request failed: {result.get('error', result['status'])}")


def render_markdown(report: dict) -> str:
    lines = [
        "# Runtime Benchmark",
        "",
        f"- 场景：`{report['scenario']}`",
        f"- 接口：`{report['endpoint']}`",
        f"- 外部 LLM 纳入压测：`{str(report['includes_external_llm']).lower()}`",
        f"- 每档请求数：{report['requests_per_level']}（预热 {report['warmup_requests']} 次）",
        f"- 环境：{report['environment']['os']} / {report['environment']['machine']} / "
        f"{report['environment']['logical_cpus']} logical CPUs / Python {report['environment']['python']}",
        "",
        "| 并发 | 成功率 | RPS | 客户端 P50/P95 | 检索 P50/P95 | LLM P50/P95 | 编排 P50/P95 |",
        "|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for item in report["levels"]:
        lines.append(
            f"| {item['concurrency']} | {item['success_rate']:.2%} | {item['throughput_rps']:.3f} | "
            f"{item['latency_p50_ms']:.2f}/{item['latency_p95_ms']:.2f} ms | "
            f"{item['retrieval_p50_ms']:.2f}/{item['retrieval_p95_ms']:.2f} ms | "
            f"{item['llm_p50_ms']:.2f}/{item['llm_p95_ms']:.2f} ms | "
            f"{item['orchestration_p50_ms']:.2f}/{item['orchestration_p95_ms']:.2f} ms |"
        )
    lines.extend(
        [
            "",
            "## 口径",
            "",
            *[f"- {note}" for note in report["notes"]],
            "",
        ]
    )
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="分场景测试检索或问答接口的吞吐与阶段耗时")
    parser.add_argument("--requests", type=int, default=30, help="每个并发级别的请求数")
    parser.add_argument("--warmup", type=int, default=3, help="正式计时前的预热请求数")
    parser.add_argument("--endpoint", choices=("search", "chat"), default="chat")
    parser.add_argument("--concurrency", default="1,4,8", help="逗号分隔的并发级别")
    parser.add_argument("--api-url", default=API_URL)
    parser.add_argument("--output", type=Path, default=REPORT_FILE)
    args = parser.parse_args()
    with urllib.request.urlopen(f"{args.api_url}/health", timeout=10) as response:
        health = json.loads(response.read().decode("utf-8"))
    questions = [
        json.loads(line)
        for line in EVAL_FILE.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    levels = [int(value.strip()) for value in args.concurrency.split(",") if value.strip()]
    warm_up(questions, args.warmup, args.endpoint, args.api_url)
    includes_external_llm = args.endpoint == "chat" and bool(health["llm_enabled"])
    scenario = (
        "hybrid_search_only"
        if args.endpoint == "search"
        else "chat_with_external_llm" if includes_external_llm else "chat_with_local_extractive_generation"
    )
    report = {
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "scenario": scenario,
        "endpoint": f"/api/{args.endpoint}",
        "includes_external_llm": includes_external_llm,
        "requests_per_level": args.requests,
        "warmup_requests": args.warmup,
        "environment": {
            "os": platform.platform(),
            "machine": platform.machine(),
            "processor": platform.processor(),
            "logical_cpus": os.cpu_count(),
            "python": platform.python_version(),
            "python_executable": sys.executable,
        },
        "dataset": {
            "file": str(EVAL_FILE.relative_to(ROOT)),
            "questions": len(questions),
        },
        "corpus_chunks": health["indexed_chunks"],
        "embedding_backend": health["embedding_backend"],
        "llm_enabled": health["llm_enabled"],
        "qdrant_mode": health.get("qdrant_mode", "unknown"),
        "max_concurrent_queries": health.get("max_concurrent_queries"),
        "request_timeout_seconds": health.get("request_timeout_seconds"),
        "rate_limit_per_minute": health.get("rate_limit_per_minute"),
        "levels": [
            run_level(questions, level, args.requests, args.endpoint, args.api_url)
            for level in levels
        ],
        "notes": [
            "Results are from the current Windows single-machine environment.",
            "RPS is reported only with its endpoint and generation scenario; it is not a generic LLM throughput claim.",
            "Retrieval, external LLM, and orchestration latency are reported separately for /api/chat.",
            "The /api/search retrieval latency is measured at the client boundary and includes HTTP serialization overhead.",
            "Queries share a read lock; index rebuild and shutdown use an exclusive write lock.",
            "Local Qdrant supports one process only. Use Qdrant Server before adding multiple API workers.",
            "CPU embedding and SQLite writes can still limit throughput at higher concurrency.",
            "This benchmark measures industrial manual Q&A, not code repair tasks.",
        ],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    markdown_output = args.output.with_suffix(".md")
    markdown_output.write_text(render_markdown(report), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
