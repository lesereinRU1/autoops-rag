import json
from collections import Counter

from app.agent.tool_router import TOOL_WHITELIST
from scripts.eval_agentic_shadow import (
    DEFAULT_DATASET,
    DEFAULT_SCHEMA,
    load_cases,
    run_evaluation,
    validate_cases,
    write_reports,
)


def test_agentic_cases_validate_and_cover_every_intent():
    schema = json.loads(DEFAULT_SCHEMA.read_text(encoding="utf-8"))
    cases, parse_errors = load_cases(DEFAULT_DATASET)

    assert parse_errors == []
    assert validate_cases(cases, schema) == []
    assert len(cases) == 24
    distribution = Counter(case["expected_intent"] for case in cases)
    assert set(distribution) == set(
        schema["properties"]["expected_intent"]["enum"]
    )
    assert all(count >= 3 for count in distribution.values())


def test_shadow_eval_has_no_policy_whitelist_budget_or_loop_violations():
    report = run_evaluation()
    metrics = report["metrics"]

    assert metrics["total_cases"] == 24
    assert metrics["budget_violation_count"] == 0
    assert metrics["tool_whitelist_violation_count"] == 0
    assert metrics["loop_violation_count"] == 0
    assert report["execution"]["api_called"] is False
    assert report["execution"]["retrieval_called"] is False
    assert report["execution"]["llm_called"] is False
    assert report["execution"]["tools_executed"] is False
    assert report["execution"]["planner_applied"] is False
    assert all(
        step["tool"] in TOOL_WHITELIST
        for detail in report["details"]
        for step in detail["plan"]["steps"]
    )


def test_safety_and_out_of_scope_cases_are_blocked_without_tools():
    report = run_evaluation()
    policy_details = [
        detail
        for detail in report["details"]
        if detail["expected_intent"] in {"safety_risk", "out_of_scope"}
    ]

    assert len(policy_details) == 6
    assert all(detail["actual_tools"] == [] for detail in policy_details)
    assert all(
        detail["plan"]["allow_generation"] is False
        for detail in policy_details
    )
    assert report["metrics"]["safety_block_plan_accuracy"] == 1.0
    assert report["metrics"]["out_of_scope_block_plan_accuracy"] == 1.0


def test_shadow_eval_reports_can_be_written(tmp_path):
    report = run_evaluation()
    json_output = tmp_path / "agentic_shadow_eval.json"
    md_output = tmp_path / "agentic_shadow_eval.md"

    write_reports(report, json_output, md_output)

    saved = json.loads(json_output.read_text(encoding="utf-8"))
    markdown = md_output.read_text(encoding="utf-8")
    assert saved["metrics"]["loop_violation_count"] == 0
    assert "不代表最终问答准确率" in markdown
    assert "Planner应用到真实路由：否" in markdown
