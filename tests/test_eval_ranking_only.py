from __future__ import annotations

from scripts.eval_ranking_only import aggregate, evaluate_row, render_markdown


def row(question_id: str, gold: list[str], category: str = "natural_language_rewrite") -> dict:
    return {
        "id": question_id,
        "question": f"问题 {question_id}",
        "category": category,
        "gold_chunk_ids": gold,
    }


def test_ranking_only_metrics_use_human_gold_and_top5() -> None:
    first = evaluate_row(row("q1", ["gold-a"]), ["gold-a", "x", "y", "z", "w"])
    second = evaluate_row(row("q2", ["gold-b"]), ["x", "gold-b", "y", "z", "w"])
    third = evaluate_row(row("q3", ["gold-c"]), ["x", "y", "z", "w", "v"])

    metrics = aggregate([first, second, third])

    assert metrics["strict_recall@5"] == 0.6667
    assert metrics["mrr@5"] == 0.5
    assert metrics["top1_accuracy"] == 0.3333
    assert metrics["gold_missing_top5"] == 1
    assert metrics["gold_in_top5_not_top1"] == 1


def test_multi_gold_requires_every_gold_in_top5() -> None:
    result = evaluate_row(
        row("q1", ["gold-a", "gold-b"], "cross_section_procedure"),
        ["gold-a", "x", "y", "z", "w"],
    )

    assert result["strict_recall@5"] == 0.0
    assert result["gold_rank"] == {"gold-a": 1, "gold-b": None}
    assert result["initial_reason"] == "query_too_broad"


def test_markdown_explicitly_excludes_llm_and_generation_quality() -> None:
    detail = evaluate_row(row("q1", ["gold-a"]), ["x", "gold-a", "y", "z", "w"])
    report = {
        "run_mode": "api",
        "strategy": "hybrid",
        "split": "development",
        "answerable_questions": 1,
        "skipped_non_answerable_questions": 0,
        "metrics": aggregate([detail]),
        "gold_missing_top5": [],
        "gold_in_top5_not_top1": [detail],
    }

    markdown = render_markdown(report)

    assert "ranking-only eval" in markdown
    assert "不调用外部 LLM" in markdown
    assert "不调用 `/api/chat`" in markdown
    assert "不代表最终生成质量" in markdown
