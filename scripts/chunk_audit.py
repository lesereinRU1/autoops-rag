from __future__ import annotations

import json
import math
import re
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CHUNKS_FILE = ROOT / "data" / "processed" / "chunks.jsonl"
REPORT_FILE = ROOT / "reports" / "chunk_length_audit.json"
TOKEN_PATTERN = re.compile(r"16#[0-9A-Fa-f]+|[\u4e00-\u9fff]|[A-Za-z]+(?:_[A-Za-z]+)*|\d+(?:\.\d+)?")


def percentile(values: list[int], percent: float) -> int:
    if not values:
        return 0
    ordered = sorted(values)
    index = max(0, math.ceil(percent * len(ordered)) - 1)
    return ordered[index]


def main() -> None:
    character_lengths: list[int] = []
    estimated_token_lengths: list[int] = []
    representations: Counter[str] = Counter()
    documents: Counter[str] = Counter()
    over_2000_characters: list[dict] = []
    over_600_estimated_tokens: list[dict] = []

    with CHUNKS_FILE.open("r", encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            chunk = json.loads(line)
            text = chunk.get("text", "")
            character_count = len(text)
            estimated_tokens = len(TOKEN_PATTERN.findall(text))
            character_lengths.append(character_count)
            estimated_token_lengths.append(estimated_tokens)
            representations[chunk.get("metadata", {}).get("representation", "narrative")] += 1
            documents[chunk.get("doc_name", "unknown")] += 1

            sample = {
                "chunk_id": chunk.get("chunk_id"),
                "document": chunk.get("doc_name"),
                "page": chunk.get("page"),
                "representation": chunk.get("metadata", {}).get("representation", "narrative"),
                "characters": character_count,
                "estimated_tokens": estimated_tokens,
            }
            if character_count > 2000:
                over_2000_characters.append(sample)
            if estimated_tokens > 600:
                over_600_estimated_tokens.append(sample)

    report = {
        "audit_scope": "current chunks.jsonl",
        "chunks": len(character_lengths),
        "character_length": {
            "minimum": min(character_lengths, default=0),
            "p50": percentile(character_lengths, 0.50),
            "p90": percentile(character_lengths, 0.90),
            "p95": percentile(character_lengths, 0.95),
            "p99": percentile(character_lengths, 0.99),
            "maximum": max(character_lengths, default=0),
            "over_2000": len(over_2000_characters),
        },
        "estimated_token_length": {
            "method": "按中文单字、英文单词、数字和十六进制故障码估算，不等同于向量模型的分词器",
            "p50": percentile(estimated_token_lengths, 0.50),
            "p90": percentile(estimated_token_lengths, 0.90),
            "p95": percentile(estimated_token_lengths, 0.95),
            "p99": percentile(estimated_token_lengths, 0.99),
            "maximum": max(estimated_token_lengths, default=0),
            "over_configured_600": len(over_600_estimated_tokens),
        },
        "representations": dict(representations),
        "documents": dict(documents),
        "findings": [
            "当前同一个text字段同时用于向量计算、BM25索引和回答证据展示。",
            "切分程序不拆分单个句子，因此超长句子或表格行可能超过配置上限。",
            "重建索引前，应在同一批人工标注问题上比较检索文本与展示文本分离的方案。",
        ],
        "recommended_experiment": {
            "baseline": "当前完整切片文本",
            "candidate": "保留完整展示文本，另建有长度上限的检索文本，并保留章节标题、表头和关键数值",
            "metrics": ["Recall@5", "MRR@10", "nDCG@10", "table-question Recall@5", "index size", "ingest time"],
            "acceptance_rule": "总体检索指标不下降且表格题召回不下降时才采用",
        },
        "largest_samples": sorted(
            over_2000_characters,
            key=lambda item: item["characters"],
            reverse=True,
        )[:20],
    }
    REPORT_FILE.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
