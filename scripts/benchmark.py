from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.config import get_settings

EVAL_FILE = ROOT / "data" / "eval" / "questions.jsonl"
REPORT_FILE = ROOT / "reports" / "retrieval_metrics.json"
DEFAULT_API_URL = "http://127.0.0.1:8000"


def api_health(api_url: str) -> dict | None:
    try:
        with urllib.request.urlopen(f"{api_url.rstrip('/')}/health", timeout=2) as response:
            return json.loads(response.read().decode("utf-8"))
    except (OSError, urllib.error.URLError, json.JSONDecodeError):
        return None


def api_search(api_url: str, question: str, model: str) -> list[dict]:
    body = json.dumps(
        {"query": question, "model": model, "version": "", "top_k": 5},
        ensure_ascii=False,
    ).encode("utf-8")
    request = urllib.request.Request(
        f"{api_url.rstrip('/')}/api/search",
        data=body,
        headers={"Content-Type": "application/json; charset=utf-8"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))["hits"]


def local_hit_text(hit) -> str:
    return f"{hit.chunk.doc_name} {hit.chunk.text}".lower()


def api_hit_text(hit: dict) -> str:
    chunk = hit["chunk"]
    return f"{chunk['doc_name']} {chunk['text']}".lower()


def main() -> None:
    parser = argparse.ArgumentParser(description="Run retrieval evaluation locally or through the running API")
    parser.add_argument("--mode", choices=["auto", "api", "local"], default="auto")
    parser.add_argument("--api-url", default=DEFAULT_API_URL)
    args = parser.parse_args()

    settings = get_settings()
    health = api_health(args.api_url)
    if args.mode == "api" and health is None:
        raise SystemExit("API mode requested, but the service is not running. Start it with .\\scripts\\start_background.ps1")
    if args.mode == "local" and health is not None:
        raise SystemExit("Local mode cannot open Qdrant while the service is running. Stop it first with .\\scripts\\stop.ps1")
    run_mode = "api" if args.mode == "api" or (args.mode == "auto" and health is not None) else "local"

    retriever = None
    if run_mode == "local":
        from app.retrieval.hybrid import HybridRetriever

        retriever = HybridRetriever(settings)

    rows = [json.loads(line) for line in EVAL_FILE.read_text(encoding="utf-8").splitlines() if line.strip()]
    reciprocal_ranks: list[float] = []
    recalls: list[float] = []
    latencies: list[float] = []
    details: list[dict] = []
    try:
        for row in rows:
            started = time.perf_counter()
            model = row.get("model", "S7-1200")
            if run_mode == "api":
                hits = api_search(args.api_url, row["question"], model)
            else:
                hits = retriever.search(row["question"], top_k=5, model=model)
            latencies.append((time.perf_counter() - started) * 1000)
            terms = [term.lower() for term in row["expected_terms"]]
            matched_ranks: list[int] = []
            for rank, hit in enumerate(hits, start=1):
                haystack = api_hit_text(hit) if run_mode == "api" else local_hit_text(hit)
                if any(term in haystack for term in terms):
                    matched_ranks.append(rank)
            recall = 1.0 if matched_ranks else 0.0
            rr = 1.0 / min(matched_ranks) if matched_ranks else 0.0
            recalls.append(recall)
            reciprocal_ranks.append(rr)
            details.append({"id": row["id"], "recall@5": recall, "reciprocal_rank": rr})
    finally:
        if retriever is not None:
            retriever.close()
    report = {
        "mode": run_mode,
        "questions": len(rows),
        "recall@5": statistics.fmean(recalls),
        "mrr@5": statistics.fmean(reciprocal_ranks),
        "latency_ms_p50": statistics.median(latencies),
        "latency_ms_max": max(latencies),
        "embedding_backend": health.get("embedding_backend", settings.embedding_backend) if health else settings.embedding_backend,
        "details": details,
    }
    REPORT_FILE.parent.mkdir(exist_ok=True)
    REPORT_FILE.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: v for k, v in report.items() if k != "details"}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
