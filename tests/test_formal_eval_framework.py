from __future__ import annotations

import json
from pathlib import Path

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
