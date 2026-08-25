from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from scripts import run_formal_eval
from scripts.run_formal_eval import ndcg_at_5
from scripts.validate_formal_eval import DEFAULT_SCHEMA, validate_dataset


def _base_row(row_id: str = "formal_test_001") -> dict:
    return {
        "id": row_id,
        "question": "仅用于校验框架的临时问题",
        "category": "official_parameter",
        "answerable": True,
        "expected_tool": "search_manual",
        "gold_chunk_ids": ["human_chunk_001"],
        "gold_label_source": "human_pre_labeled",
        "required_facts": ["人工标注事实"],
        "forbidden_facts": [],
        "source_scope": "official_manual",
        "device_model": "S7-1200",
        "firmware_version": "",
        "manual_version": "",
        "review_status": "self_checked",
        "reviewer": "framework-test",
        "split": "development",
        "notes": "临时单元测试数据，不写入正式评测集",
    }


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
        encoding="utf-8",
    )


def test_empty_formal_dataset_is_not_ready(tmp_path: Path) -> None:
    dataset = tmp_path / "formal.jsonl"
    dataset.write_text("", encoding="utf-8")

    readiness, rows = validate_dataset(
        dataset, DEFAULT_SCHEMA, check_chunk_existence=False
    )

    assert rows == []
    assert readiness["ready_for_resume_accuracy_claim"] is False
    assert readiness["questions_at_least_60"] is False
    assert readiness["no_runtime_generated_gold"] is True


def test_answerable_question_requires_human_gold_and_required_facts(
    tmp_path: Path,
) -> None:
    row = _base_row()
    row["gold_chunk_ids"] = [""]
    row["gold_label_source"] = "not_applicable"
    row["required_facts"] = []
    dataset = tmp_path / "formal.jsonl"
    _write_jsonl(dataset, [row])

    readiness, _ = validate_dataset(
        dataset, DEFAULT_SCHEMA, check_chunk_existence=False
    )
    errors = "\n".join(readiness["validation_errors"])

    assert "gold_chunk_ids" in errors
    assert "required_facts" in errors
    assert "human_pre_labeled" in errors
    assert readiness["no_runtime_generated_gold"] is False
    assert readiness["ready_for_resume_accuracy_claim"] is False


def test_test_split_requires_reviewed_status(tmp_path: Path) -> None:
    row = _base_row()
    row["split"] = "test"
    dataset = tmp_path / "formal.jsonl"
    _write_jsonl(dataset, [row])

    readiness, _ = validate_dataset(
        dataset, DEFAULT_SCHEMA, check_chunk_existence=False
    )

    assert any(
        "split=test" in error and "review_status" in error
        for error in readiness["validation_errors"]
    )


def test_unanswerable_question_requires_a_refusal_boundary(tmp_path: Path) -> None:
    row = _base_row()
    row.update(
        {
            "answerable": False,
            "gold_chunk_ids": [],
            "gold_label_source": "not_applicable",
            "required_facts": [],
            "forbidden_facts": [],
            "notes": "",
            "review_status": "needs_review",
            "reviewer": "",
        }
    )
    dataset = tmp_path / "formal.jsonl"
    _write_jsonl(dataset, [row])

    readiness, _ = validate_dataset(
        dataset, DEFAULT_SCHEMA, check_chunk_existence=False
    )

    assert any(
        "refusal_reason" in error and "forbidden_facts" in error
        for error in readiness["validation_errors"]
    )


def test_readiness_thresholds_can_pass_without_runtime_gold(tmp_path: Path) -> None:
    rows: list[dict] = []
    for index in range(50):
        row = _base_row(f"answerable_{index:03d}")
        row["gold_chunk_ids"] = [f"human_chunk_{index:03d}"]
        if index < 30:
            row.update(
                {
                    "review_status": "reviewed",
                    "reviewer": "human-reviewer",
                    "split": "test",
                }
            )
        rows.append(row)
    for index in range(10):
        row = _base_row(f"unanswerable_{index:03d}")
        row.update(
            {
                "category": "unsafe_request" if index < 3 else "unanswerable_scope",
                "answerable": False,
                "gold_chunk_ids": [],
                "gold_label_source": "not_applicable",
                "required_facts": [],
                "forbidden_facts": ["不得输出的操作步骤"],
                "source_scope": "out_of_scope",
                "review_status": "needs_review",
                "reviewer": "",
            }
        )
        rows.append(row)
    dataset = tmp_path / "formal.jsonl"
    _write_jsonl(dataset, rows)

    readiness, _ = validate_dataset(
        dataset, DEFAULT_SCHEMA, check_chunk_existence=False
    )

    assert readiness["validation_errors"] == []
    assert readiness["questions_at_least_60"] is True
    assert readiness["official_share_at_least_70_percent"] is True
    assert readiness["unanswerable_questions_at_least_10"] is True
    assert readiness["reviewed_questions_at_least_30"] is True
    assert readiness["test_split_exists"] is True
    assert readiness["no_runtime_generated_gold"] is True
    assert readiness["ready_for_resume_accuracy_claim"] is True


def test_ndcg_at_5_rewards_earlier_gold() -> None:
    gold = {"gold_a", "gold_b"}

    early = ndcg_at_5(["gold_a", "gold_b", "other"], gold)
    late = ndcg_at_5(["other", "other_2", "gold_a", "gold_b"], gold)

    assert early == 1.0
    assert 0.0 < late < early


def test_processed_corpus_metadata_records_hash_counts_and_gold_resolution(
    tmp_path: Path,
) -> None:
    chunks = tmp_path / "chunks.jsonl"
    _write_jsonl(
        chunks,
        [
            {
                "chunk_id": "chunk-1",
                "doc_id": "doc-1",
                "metadata": {"representation": "page_text"},
            },
            {
                "chunk_id": "chunk-2",
                "doc_id": "doc-2",
                "metadata": {"representation": "table_row"},
            },
        ],
    )
    all_rows = [
        {"gold_chunk_ids": ["chunk-1", "missing"]},
        {"gold_chunk_ids": ["chunk-2"]},
    ]

    metadata = run_formal_eval.build_corpus_metadata(chunks, all_rows, all_rows[:1])

    assert metadata["sha256"] == run_formal_eval.dataset_sha256(chunks)
    assert metadata["file"] == "chunks.jsonl"
    assert metadata["document_count"] == 2
    assert metadata["chunk_count"] == 2
    assert metadata["table_chunk_count"] == 1
    assert metadata["formal_gold_resolvable_count"] == 2
    assert metadata["formal_gold_missing"] == ["missing"]
    assert metadata["selected_gold_resolvable_count"] == 1


def test_markdown_metric_display_uses_json_null_spelling() -> None:
    assert run_formal_eval.display_metric(None) == "null"
    assert run_formal_eval.display_metric(0.0) == "0.0"


def test_report_paths_are_repository_relative_and_never_absolute(
    tmp_path: Path,
) -> None:
    repository_file = run_formal_eval.ROOT / "data" / "eval" / "formal_questions.jsonl"
    external_file = tmp_path / "external.jsonl"

    assert run_formal_eval.report_path(repository_file) == "data/eval/formal_questions.jsonl"
    assert run_formal_eval.report_path(external_file) == "external.jsonl"
    assert not Path(run_formal_eval.report_path(external_file)).is_absolute()


def test_evaluation_repository_receives_only_case_summary_and_key_metrics(
    monkeypatch,
) -> None:
    class Repository:
        def __init__(self) -> None:
            self.records: list[dict] = []
            self.summary: dict = {}

        def create_run(self, name, *, run_id, metadata):
            assert name == "formal_evaluation"
            assert "details" not in metadata
            return run_id

        def save_record(self, run_id, case_id, *, category, status, metrics, error):
            self.records.append(
                {
                    "run_id": run_id,
                    "case_id": case_id,
                    "category": category,
                    "status": status,
                    "metrics": metrics,
                    "error": error,
                }
            )

        def complete_run(self, run_id, *, summary):
            self.summary = summary

    repository = Repository()

    class Database:
        repositories = SimpleNamespace(evaluations=repository)

        def close(self):
            return None

    monkeypatch.setattr(run_formal_eval, "get_settings", lambda: object())
    monkeypatch.setattr(
        run_formal_eval,
        "create_runtime_database_from_settings",
        lambda settings: Database(),
    )
    report = {
        "status": "completed",
        "run_id": "run-1",
        "generated_at": "2026-08-25T00:00:00+08:00",
        "dataset": {"version": "formal_eval_v1", "sha256": "abc"},
        "metrics": {"strict_recall@5": 1.0, "citation_correctness_rate": 1.0},
        "metric_denominators": {"retrieval_cases": 1},
        "details": [
            {
                "case_id": "case-1",
                "category": "alarm_code",
                "http_status": 200,
                "strict_recall@5": 1.0,
                "citation_valid": True,
                "required_fact_coverage": 1.0,
                "tool_calls": [{"tool_name": "search_manual"}],
                "evidence_chunk_ids": ["chunk-1"],
                "answer": "large answer that belongs in the file report only",
                "error": None,
            }
        ],
    }

    assert run_formal_eval.persist_evaluation_metadata(report) is True
    assert len(repository.records) == 1
    stored = repository.records[0]["metrics"]
    assert stored["strict_recall@5"] == 1.0
    assert stored["citation_valid"] is True
    assert "answer" not in stored
    assert "evidence_chunk_ids" not in stored
    assert "tool_calls" not in stored
    assert repository.summary["metrics"]["citation_correctness_rate"] == 1.0
