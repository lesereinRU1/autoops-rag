from __future__ import annotations

import argparse
import hashlib
import json
import math
import statistics
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

DEFAULT_DATASET = ROOT / "data" / "eval" / "formal_questions.jsonl"
DEFAULT_JSON_REPORT = ROOT / "reports" / "ranking_eval.json"
DEFAULT_MD_REPORT = ROOT / "reports" / "ranking_eval.md"
DEFAULT_API_URL = "http://127.0.0.1:8000"


def load_questions(dataset: Path, split: str) -> tuple[list[dict[str, Any]], int]:
    rows = [
        json.loads(line)
        for line in dataset.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    selected = [row for row in rows if split == "all" or row.get("split") == split]
    answerable = [row for row in selected if row.get("answerable")]
    for row in answerable:
        if not row.get("gold_chunk_ids"):
            raise ValueError(f"{row.get('id')}: answerable题缺少人工gold_chunk_ids")
        if row.get("gold_label_source") != "human_pre_labeled":
            raise ValueError(f"{row.get('id')}: gold不是human_pre_labeled，禁止参与ranking eval")
        if any(not str(chunk_id).strip() for chunk_id in row["gold_chunk_ids"]):
            raise ValueError(f"{row.get('id')}: gold_chunk_ids包含空值")
    return answerable, len(selected) - len(answerable)


def ndcg_at_5(top5: list[str], gold: set[str]) -> float:
    dcg = sum(
        1.0 / math.log2(rank + 1)
        for rank, chunk_id in enumerate(top5[:5], start=1)
        if chunk_id in gold
    )
    ideal_hits = min(5, len(gold))
    idcg = sum(1.0 / math.log2(rank + 1) for rank in range(1, ideal_hits + 1))
    return dcg / idcg if idcg else 0.0


def chunk_family(chunk_id: str) -> str:
    parts = chunk_id.rsplit("_", 2)
    return parts[0] if len(parts) == 3 else chunk_id


def initial_reason(row: dict[str, Any], top5: list[str], all_gold_in_top5: bool) -> str:
    gold = list(row["gold_chunk_ids"])
    if not all_gold_in_top5:
        if row.get("category") == "cross_section_procedure" and len(gold) > 1:
            return "query_too_broad"
        return "retrieval_miss"
    if row.get("category") == "cross_section_procedure" or len(gold) > 1:
        return "query_too_broad"
    if top5 and any(chunk_family(top5[0]) == chunk_family(item) for item in gold):
        return "chunk_text_too_similar"
    return "ranking_late"


def evaluate_row(row: dict[str, Any], top5: list[str]) -> dict[str, Any]:
    top5 = top5[:5]
    gold_ids = list(row["gold_chunk_ids"])
    gold = set(gold_ids)
    rank_map = {
        chunk_id: (top5.index(chunk_id) + 1 if chunk_id in top5 else None)
        for chunk_id in gold_ids
    }
    ranks = [rank for rank in rank_map.values() if rank is not None]
    strict = gold.issubset(set(top5))
    top1 = bool(top5 and top5[0] in gold)
    reason = initial_reason(row, top5, strict)
    return {
        "question_id": row["id"],
        "question": row["question"],
        "category": row["category"],
        "gold_chunk_ids": gold_ids,
        "top5_chunk_ids": top5,
        "gold_rank": rank_map,
        "strict_recall@5": float(strict),
        "reciprocal_rank@5": 1.0 / min(ranks) if ranks else 0.0,
        "ndcg@5": ndcg_at_5(top5, gold),
        "top1_correct": top1,
        "initial_reason": reason,
    }


def aggregate(details: list[dict[str, Any]]) -> dict[str, Any]:
    if not details:
        raise ValueError("没有可评估的answerable题目")
    missing = [item for item in details if item["strict_recall@5"] != 1.0]
    late = [
        item for item in details
        if item["strict_recall@5"] == 1.0 and not item["top1_correct"]
    ]
    return {
        "strict_recall@5": round(statistics.fmean(item["strict_recall@5"] for item in details), 4),
        "mrr@5": round(statistics.fmean(item["reciprocal_rank@5"] for item in details), 4),
        "ndcg@5": round(statistics.fmean(item["ndcg@5"] for item in details), 4),
        "top1_accuracy": round(statistics.fmean(float(item["top1_correct"]) for item in details), 4),
        "gold_missing_top5": len(missing),
        "gold_in_top5_not_top1": len(late),
    }


def api_is_ready(client: httpx.Client, api_url: str) -> bool:
    try:
        response = client.get(f"{api_url.rstrip('/')}/health", timeout=10)
        return response.status_code == 200
    except httpx.HTTPError:
        return False


def api_search(
    client: httpx.Client,
    api_url: str,
    row: dict[str, Any],
    strategy: str,
) -> list[str]:
    response = client.post(
        f"{api_url.rstrip('/')}/api/search",
        json={
            "query": row["question"],
            "model": row.get("device_model") or "S7-1200",
            "version": row.get("manual_version") or row.get("firmware_version") or "",
            "top_k": 5,
            "strategy": strategy,
        },
    )
    response.raise_for_status()
    return [hit["chunk"]["chunk_id"] for hit in response.json()["hits"][:5]]


def render_markdown(report: dict[str, Any]) -> str:
    metrics = report["metrics"]
    lines = [
        "# Ranking-only Evaluation",
        "",
        "> 本报告是 ranking-only eval，只评估检索排序，不调用外部 LLM，"
        "不调用 `/api/chat`，不生成答案，也不代表最终生成质量。",
        "",
        f"- 运行模式：`{report['run_mode']}`",
        f"- 检索策略：`{report['strategy']}`",
        f"- Split：`{report['split']}`",
        f"- 可回答题：{report['answerable_questions']}",
        f"- 跳过不可回答/危险题：{report['skipped_non_answerable_questions']}",
        "",
        "## Metrics",
        "",
        "| Metric | Value |",
        "|---|---:|",
        f"| Strict Recall@5 | {metrics['strict_recall@5']:.4f} |",
        f"| MRR@5 | {metrics['mrr@5']:.4f} |",
        f"| nDCG@5 | {metrics['ndcg@5']:.4f} |",
        f"| Top1 Accuracy | {metrics['top1_accuracy']:.4f} |",
        f"| Gold missing Top5 | {metrics['gold_missing_top5']} |",
        f"| Gold in Top5 but not Top1 | {metrics['gold_in_top5_not_top1']} |",
        "",
        "## Gold missing Top5",
        "",
    ]
    missing = report["gold_missing_top5"]
    if not missing:
        lines.append("无。")
    else:
        for item in missing:
            lines.extend(render_sample(item))
    lines.extend(["", "## Ranking late", ""])
    late = report["gold_in_top5_not_top1"]
    if not late:
        lines.append("无。")
    else:
        for item in late:
            lines.extend(render_sample(item))
    lines.extend(
        [
            "",
            "## Scope",
            "",
            "- 只读取人工预标注的 `gold_chunk_ids`，不会运行时生成 gold。",
            "- 只调用 `/api/search` 或本地 `HybridRetriever`，不会调用外部 LLM。",
            "- 本报告不修改检索排序权重、Prompt、安全拒答或正式评测集。",
            "- ranking-only 指标不代表回答忠实度、拒答质量或最终生成质量。",
            "",
        ]
    )
    return "\n".join(lines)


def render_sample(item: dict[str, Any]) -> list[str]:
    return [
        f"### {item['question_id']}",
        "",
        f"- 问题：{item['question']}",
        f"- Gold：`{json.dumps(item['gold_chunk_ids'], ensure_ascii=False)}`",
        f"- Top5：`{json.dumps(item['top5_chunk_ids'], ensure_ascii=False)}`",
        f"- Gold rank：`{json.dumps(item['gold_rank'], ensure_ascii=False)}`",
        f"- 初判原因：`{item['initial_reason']}`",
        "",
    ]


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(
        description="Evaluate retrieval ranking only; never call /api/chat or an external LLM."
    )
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--split", choices=("development", "test", "all"), default="development")
    parser.add_argument("--strategy", choices=("hybrid", "dense", "bm25"), default="hybrid")
    parser.add_argument("--mode", choices=("auto", "api", "local"), default="auto")
    parser.add_argument("--api-url", default=DEFAULT_API_URL)
    parser.add_argument("--json-output", type=Path, default=DEFAULT_JSON_REPORT)
    parser.add_argument("--md-output", type=Path, default=DEFAULT_MD_REPORT)
    args = parser.parse_args()

    dataset = args.dataset.resolve()
    before_hash = hashlib.sha256(dataset.read_bytes()).hexdigest()
    rows, skipped = load_questions(dataset, args.split)
    details: list[dict[str, Any]] = []
    latencies: list[float] = []

    with httpx.Client(timeout=120, trust_env=False) as client:
        ready = api_is_ready(client, args.api_url)
        if args.mode == "api" and not ready:
            raise SystemExit("API未运行；请先执行 .\\scripts\\start_background.ps1")
        if args.mode == "local" and ready:
            raise SystemExit("服务运行时不能用local模式打开Qdrant；请使用--mode api或先停止服务")
        run_mode = "api" if args.mode == "api" or (args.mode == "auto" and ready) else "local"

        retriever = None
        try:
            if run_mode == "local":
                from app.config import get_settings
                from app.retrieval.hybrid import HybridRetriever

                retriever = HybridRetriever(get_settings())
            for index, row in enumerate(rows, start=1):
                started = time.perf_counter()
                if run_mode == "api":
                    top5 = api_search(client, args.api_url, row, args.strategy)
                else:
                    hits = retriever.search_with_strategy(
                        row["question"],
                        strategy=args.strategy,
                        top_k=5,
                        model=row.get("device_model") or "S7-1200",
                        version=row.get("manual_version") or row.get("firmware_version") or "",
                    )
                    top5 = [hit.chunk.chunk_id for hit in hits[:5]]
                latencies.append(round((time.perf_counter() - started) * 1000, 2))
                details.append(evaluate_row(row, top5))
                print(f"[{index:03}/{len(rows):03}] {row['id']} top5={len(top5)}")
        finally:
            if retriever is not None:
                retriever.close()

    after_hash = hashlib.sha256(dataset.read_bytes()).hexdigest()
    if before_hash != after_hash:
        raise RuntimeError("formal_questions.jsonl在ranking eval期间发生变化，已停止写报告")

    metrics = aggregate(details)
    missing = [item for item in details if item["strict_recall@5"] != 1.0]
    late = [
        item for item in details
        if item["strict_recall@5"] == 1.0 and not item["top1_correct"]
    ]
    report = {
        "evaluation_type": "ranking_only_eval",
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "dataset": str(dataset),
        "dataset_sha256": before_hash,
        "split": args.split,
        "strategy": args.strategy,
        "run_mode": run_mode,
        "retrieval_endpoint": "/api/search" if run_mode == "api" else "local HybridRetriever",
        "external_llm_called": False,
        "chat_endpoint_called": False,
        "answers_generated": False,
        "answerable_questions": len(rows),
        "skipped_non_answerable_questions": skipped,
        "metrics": metrics,
        "latency_ms": {
            "p50": round(statistics.median(latencies), 2) if latencies else None,
            "p95": round(sorted(latencies)[max(0, math.ceil(len(latencies) * 0.95) - 1)], 2)
            if latencies else None,
        },
        "gold_missing_top5": missing,
        "gold_in_top5_not_top1": late,
        "details": details,
        "disclaimer": "本报告是ranking-only eval，不调用外部LLM，不代表最终生成质量。",
    }
    args.json_output.parent.mkdir(parents=True, exist_ok=True)
    args.md_output.parent.mkdir(parents=True, exist_ok=True)
    args.json_output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    args.md_output.write_text(render_markdown(report), encoding="utf-8")
    print(json.dumps({"metrics": metrics, "json": str(args.json_output), "md": str(args.md_output)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
