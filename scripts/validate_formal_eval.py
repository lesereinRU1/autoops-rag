from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATASET = ROOT / "data" / "eval" / "formal_questions.jsonl"
DEFAULT_SCHEMA = ROOT / "data" / "eval" / "formal_questions.schema.json"
DEFAULT_REPORT = ROOT / "reports" / "formal_eval_readiness.json"
CHUNKS_FILE = ROOT / "data" / "processed" / "chunks.jsonl"
RUNTIME_GOLD_MARKERS = (
    "runtime_generated",
    "generated_from_retrieval",
    "retrieved_at_runtime",
    "auto_generated_gold",
    "运行时生成",
    "从检索结果生成",
)


def load_jsonl(path: Path) -> tuple[list[dict[str, Any]], list[str]]:
    rows: list[dict[str, Any]] = []
    errors: list[str] = []
    if not path.exists():
        return rows, [f"数据集不存在：{path}"]
    for line_number, line in enumerate(path.read_text(encoding="utf-8-sig").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError as exc:
            errors.append(f"第{line_number}行不是有效JSON：{exc.msg}")
            continue
        if not isinstance(value, dict):
            errors.append(f"第{line_number}行必须是JSON对象")
            continue
        value["_line_number"] = line_number
        rows.append(value)
    return rows, errors


def known_chunk_ids(path: Path = CHUNKS_FILE) -> set[str]:
    if not path.exists():
        return set()
    ids: set[str] = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            ids.add(str(json.loads(line)["chunk_id"]))
        except (json.JSONDecodeError, KeyError, TypeError):
            continue
    return ids


def validate_rows(
    rows: list[dict[str, Any]],
    schema: dict[str, Any],
    *,
    check_chunk_existence: bool = True,
) -> tuple[list[str], list[str], bool]:
    errors: list[str] = []
    warnings: list[str] = []
    required = set(schema.get("required", []))
    properties = schema.get("properties", {})
    allowed_categories = set(properties.get("category", {}).get("enum", []))
    allowed_tools = set(properties.get("expected_tool", {}).get("enum", []))
    allowed_scopes = set(properties.get("source_scope", {}).get("enum", []))
    allowed_reviews = set(properties.get("review_status", {}).get("enum", []))
    allowed_splits = set(properties.get("split", {}).get("enum", []))
    allowed_gold_sources = set(properties.get("gold_label_source", {}).get("enum", []))
    chunks = known_chunk_ids() if check_chunk_existence else set()
    seen_ids: set[str] = set()
    no_runtime_generated_gold = True

    for row in rows:
        line = row.get("_line_number", "?")
        row_id = str(row.get("id", f"line-{line}"))
        missing = sorted(required - set(row))
        if missing:
            errors.append(f"{row_id}（第{line}行）缺少字段：{', '.join(missing)}")
            continue
        if row_id in seen_ids:
            errors.append(f"重复id：{row_id}")
        seen_ids.add(row_id)
        if not str(row.get("question", "")).strip():
            errors.append(f"{row_id}：question不能为空")
        for field, allowed in (
            ("category", allowed_categories),
            ("expected_tool", allowed_tools),
            ("source_scope", allowed_scopes),
            ("review_status", allowed_reviews),
            ("split", allowed_splits),
            ("gold_label_source", allowed_gold_sources),
        ):
            if row.get(field) not in allowed:
                errors.append(f"{row_id}：{field}值无效：{row.get(field)!r}")
        if not isinstance(row.get("answerable"), bool):
            errors.append(f"{row_id}：answerable必须为布尔值")
            continue
        for field in ("gold_chunk_ids", "required_facts", "forbidden_facts"):
            values = row.get(field)
            if not isinstance(values, list):
                errors.append(f"{row_id}：{field}必须为数组")
                continue
            if any(not isinstance(value, str) or not value.strip() for value in values):
                errors.append(f"{row_id}：{field}不能包含空字符串或非字符串")
            if len(values) != len(set(values)):
                errors.append(f"{row_id}：{field}包含重复项")

        gold = row.get("gold_chunk_ids", [])
        required_facts = row.get("required_facts", [])
        forbidden_facts = row.get("forbidden_facts", [])
        if row["answerable"]:
            if not gold:
                errors.append(f"{row_id}：answerable=true时gold_chunk_ids不能为空")
            if not required_facts:
                errors.append(f"{row_id}：answerable=true时required_facts不能为空")
            if row.get("gold_label_source") != "human_pre_labeled":
                errors.append(f"{row_id}：可回答题gold_label_source必须为human_pre_labeled")
                no_runtime_generated_gold = False
        else:
            if gold:
                errors.append(f"{row_id}：answerable=false时gold_chunk_ids必须为空")
            if row.get("gold_label_source") != "not_applicable":
                errors.append(f"{row_id}：不可回答题gold_label_source必须为not_applicable")
                no_runtime_generated_gold = False
            has_reason = bool(str(row.get("refusal_reason", "")).strip())
            has_notes = bool(str(row.get("notes", "")).strip())
            if not (has_reason or forbidden_facts or has_notes):
                errors.append(f"{row_id}：不可回答题必须填写refusal_reason、forbidden_facts或notes")

        if row.get("split") == "test" and row.get("review_status") != "reviewed":
            errors.append(f"{row_id}：split=test时review_status必须为reviewed")
        if row.get("review_status") in {"self_checked", "reviewed"} and not str(
            row.get("reviewer", "")
        ).strip():
            errors.append(f"{row_id}：已检查题必须填写reviewer")
        serialized = json.dumps(row, ensure_ascii=False).lower()
        if any(marker.lower() in serialized for marker in RUNTIME_GOLD_MARKERS):
            errors.append(f"{row_id}：检测到运行时/自动生成gold的标记，正式评测禁止使用")
            no_runtime_generated_gold = False
        if check_chunk_existence and row["answerable"] and gold:
            unknown = sorted(set(gold) - chunks)
            if unknown:
                errors.append(f"{row_id}：gold_chunk_ids在当前索引中不存在：{', '.join(unknown)}")

    if not rows:
        warnings.append("formal_questions.jsonl当前为空；可以继续人工标注，但尚不能运行正式评测")
    return errors, warnings, no_runtime_generated_gold


def build_readiness(
    rows: list[dict[str, Any]],
    errors: list[str],
    warnings: list[str],
    no_runtime_generated_gold: bool,
    dataset_path: Path,
) -> dict[str, Any]:
    clean_rows = [{key: value for key, value in row.items() if key != "_line_number"} for row in rows]
    answerable = [row for row in clean_rows if row.get("answerable") is True]
    unanswerable = [row for row in clean_rows if row.get("answerable") is False]
    official = [row for row in answerable if row.get("source_scope") == "official_manual"]
    reviewed = [row for row in clean_rows if row.get("review_status") == "reviewed"]
    official_share = len(official) / len(answerable) if answerable else 0.0
    gates = {
        "questions_at_least_60": len(clean_rows) >= 60,
        "official_share_at_least_70_percent": official_share >= 0.70,
        "unanswerable_questions_at_least_10": len(unanswerable) >= 10,
        "reviewed_questions_at_least_30": len(reviewed) >= 30,
        "test_split_exists": any(row.get("split") == "test" for row in clean_rows),
        "no_runtime_generated_gold": no_runtime_generated_gold,
    }
    ready = all(gates.values()) and not errors
    raw = dataset_path.read_bytes() if dataset_path.exists() else b""
    return {
        "evaluation_type": "formal_eval_readiness",
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "dataset": {
            "file": str(dataset_path.relative_to(ROOT)) if dataset_path.is_relative_to(ROOT) else str(dataset_path),
            "sha256": hashlib.sha256(raw).hexdigest(),
            "questions": len(clean_rows),
            "answerable": len(answerable),
            "unanswerable": len(unanswerable),
            "unsafe": sum(row.get("category") == "unsafe_request" for row in clean_rows),
            "official_answerable": len(official),
            "official_share": round(official_share, 4),
            "reviewed": len(reviewed),
            "test_split": sum(row.get("split") == "test" for row in clean_rows),
            "category_distribution": dict(Counter(row.get("category") for row in clean_rows)),
            "split_distribution": dict(Counter(row.get("split") for row in clean_rows)),
            "review_status_distribution": dict(
                Counter(row.get("review_status") for row in clean_rows)
            ),
        },
        **gates,
        "ready_for_resume_accuracy_claim": ready,
        "validation_errors": errors,
        "warnings": warnings,
        "policy": {
            "gold_chunk_ids": "human_pre_labeled_only",
            "runtime_gold_generation": "forbidden",
            "smoke_dataset_is_formal_dataset": False,
        },
    }


def validate_dataset(
    dataset: Path = DEFAULT_DATASET,
    schema_path: Path = DEFAULT_SCHEMA,
    *,
    check_chunk_existence: bool = True,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    rows, parse_errors = load_jsonl(dataset)
    row_errors, warnings, no_runtime_generated_gold = validate_rows(
        rows, schema, check_chunk_existence=check_chunk_existence
    )
    errors = [*parse_errors, *row_errors]
    readiness = build_readiness(rows, errors, warnings, no_runtime_generated_gold, dataset)
    return readiness, rows


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="校验人工预标注的正式评测集并输出readiness")
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--schema", type=Path, default=DEFAULT_SCHEMA)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--skip-chunk-existence-check", action="store_true")
    args = parser.parse_args()
    readiness, _ = validate_dataset(
        args.dataset.resolve(),
        args.schema.resolve(),
        check_chunk_existence=not args.skip_chunk_existence_check,
    )
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(readiness, ensure_ascii=False, indent=2), encoding="utf-8")
    print(
        json.dumps(
            {
                "questions": readiness["dataset"]["questions"],
                "validation_errors": len(readiness["validation_errors"]),
                "ready_for_resume_accuracy_claim": readiness[
                    "ready_for_resume_accuracy_claim"
                ],
                "report": str(args.report),
            },
            ensure_ascii=False,
        )
    )
    return 1 if readiness["validation_errors"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
