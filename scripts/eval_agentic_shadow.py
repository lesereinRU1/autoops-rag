from __future__ import annotations

import argparse
import hashlib
import json
import statistics
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.agent.intent import classify_intent
from app.agent.planner import BoundedQueryPlanner
from app.agent.tool_router import TOOL_WHITELIST, candidate_tools


DEFAULT_DATASET = ROOT / "data" / "eval" / "agentic_cases.jsonl"
DEFAULT_SCHEMA = ROOT / "data" / "eval" / "agentic_cases.schema.json"
DEFAULT_JSON_REPORT = ROOT / "reports" / "agentic_shadow_eval.json"
DEFAULT_MD_REPORT = ROOT / "reports" / "agentic_shadow_eval.md"


def load_cases(path: Path) -> tuple[list[dict[str, Any]], list[str]]:
    cases: list[dict[str, Any]] = []
    errors: list[str] = []
    if not path.exists():
        return cases, [f"数据集不存在：{path}"]
    for line_number, line in enumerate(
        path.read_text(encoding="utf-8-sig").splitlines(), start=1
    ):
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
        cases.append(value)
    return cases, errors


def validate_cases(
    cases: list[dict[str, Any]], schema: dict[str, Any]
) -> list[str]:
    errors: list[str] = []
    required = set(schema.get("required", []))
    properties = schema.get("properties", {})
    allowed_fields = set(properties)
    allowed_intents = set(properties["expected_intent"].get("enum", []))
    allowed_tools = set(
        properties["expected_tools"].get("items", {}).get("enum", [])
    )
    seen_ids: set[str] = set()
    distribution: Counter[str] = Counter()
    for index, case in enumerate(cases, start=1):
        case_id = str(case.get("id") or f"line-{index}")
        missing = sorted(required - set(case))
        if missing:
            errors.append(f"{case_id}：缺少字段：{', '.join(missing)}")
            continue
        extras = sorted(set(case) - allowed_fields)
        if schema.get("additionalProperties") is False and extras:
            errors.append(f"{case_id}：包含未声明字段：{', '.join(extras)}")
        if case_id in seen_ids:
            errors.append(f"重复id：{case_id}")
        seen_ids.add(case_id)
        if not case_id or not str(case.get("question", "")).strip():
            errors.append(f"{case_id}：id和question不能为空")
        intent = case.get("expected_intent")
        if intent not in allowed_intents:
            errors.append(f"{case_id}：expected_intent无效：{intent!r}")
        else:
            distribution[str(intent)] += 1
        tools = case.get("expected_tools")
        if not isinstance(tools, list):
            errors.append(f"{case_id}：expected_tools必须是数组")
            continue
        if len(tools) != len(set(tools)):
            errors.append(f"{case_id}：expected_tools包含重复工具")
        invalid_tools = [tool for tool in tools if tool not in allowed_tools]
        if invalid_tools:
            errors.append(f"{case_id}：包含非白名单工具：{invalid_tools}")
        if not isinstance(case.get("allow_generation"), bool):
            errors.append(f"{case_id}：allow_generation必须是布尔值")
        if not isinstance(case.get("safety_expected"), bool):
            errors.append(f"{case_id}：safety_expected必须是布尔值")
        policy_intent = intent in {"safety_risk", "out_of_scope"}
        if policy_intent and (tools or case.get("allow_generation") is not False):
            errors.append(f"{case_id}：安全或越界案例不得配置工具或允许生成")
        if bool(case.get("safety_expected")) != (intent == "safety_risk"):
            errors.append(f"{case_id}：safety_expected与expected_intent不一致")

    for intent in sorted(allowed_intents):
        if distribution[intent] < 3:
            errors.append(
                f"{intent}案例不足3条：当前{distribution[intent]}条"
            )
    return errors


def _rate(numerator: int, denominator: int) -> float | None:
    return round(numerator / denominator, 4) if denominator else None


def run_evaluation(
    dataset: Path = DEFAULT_DATASET,
    schema_path: Path = DEFAULT_SCHEMA,
    *,
    max_agent_rounds: int = 2,
    max_tool_calls: int = 4,
) -> dict[str, Any]:
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    cases, parse_errors = load_cases(dataset)
    errors = [*parse_errors, *validate_cases(cases, schema)]
    if errors:
        raise ValueError("Agentic shadow数据校验失败：\n" + "\n".join(errors))

    planner = BoundedQueryPlanner(
        max_agent_rounds=max_agent_rounds,
        max_tool_calls=max_tool_calls,
    )
    details: list[dict[str, Any]] = []
    whitelist_violation_count = 0
    budget_violation_count = 0
    loop_violation_count = 0
    unnecessary_tool_count = 0

    for case in cases:
        intent_result = classify_intent(
            case["question"],
            model=case.get("model", "S7-1200"),
            version=case.get("version", ""),
        )
        candidates = candidate_tools(intent_result["intent"])
        plan = planner.build_plan(
            query=case["question"],
            intent=intent_result["intent"],
            candidate_tools=candidates,
        )
        steps = plan["steps"]
        actual_tools = [step.get("tool", "") for step in steps]
        invalid_tools = [tool for tool in actual_tools if tool not in TOOL_WHITELIST]
        whitelist_violation_count += len(invalid_tools)

        step_ids = [step.get("step_id") for step in steps]
        actions = [step.get("action") for step in steps]
        loop_violation = (
            step_ids != list(range(1, len(steps) + 1))
            or len(actions) != len(set(actions))
        )
        loop_violation_count += int(loop_violation)

        budget_violation = any(
            (
                len(steps) > planner.MAX_STEPS,
                len(steps) > planner.max_tool_calls,
                plan.get("max_tool_calls", 0) > planner.max_tool_calls,
                plan.get("max_tool_calls") != len(steps),
                plan.get("max_rounds", 0) > planner.max_agent_rounds,
            )
        )
        budget_violation_count += int(budget_violation)

        expected_policy_block = case["expected_intent"] in {
            "safety_risk",
            "out_of_scope",
        }
        policy_plan_valid = not expected_policy_block or (
            not steps and plan.get("allow_generation") is False
        )
        plan_valid = (
            not invalid_tools
            and not budget_violation
            and not loop_violation
            and policy_plan_valid
            and plan.get("routing_mode") == "shadow"
            and plan.get("applied") is False
        )
        unnecessary_tool = (
            case["expected_intent"] == "general_manual_search"
            and actual_tools != ["search_manual"]
        )
        unnecessary_tool_count += int(unnecessary_tool)
        details.append(
            {
                "id": case["id"],
                "question": case["question"],
                "expected_intent": case["expected_intent"],
                "actual_intent": intent_result["intent"],
                "intent_correct": intent_result["intent"]
                == case["expected_intent"],
                "confidence": intent_result["confidence"],
                "matched_keywords": intent_result["matched_keywords"],
                "candidate_tools": candidates,
                "expected_tools": case["expected_tools"],
                "actual_tools": actual_tools,
                "tool_selection_correct": actual_tools
                == case["expected_tools"],
                "plan_valid": plan_valid,
                "safety_block_correct": (
                    not steps and plan.get("allow_generation") is False
                    if case["expected_intent"] == "safety_risk"
                    else None
                ),
                "out_of_scope_block_correct": (
                    not steps and plan.get("allow_generation") is False
                    if case["expected_intent"] == "out_of_scope"
                    else None
                ),
                "unnecessary_tool": unnecessary_tool,
                "budget_violation": budget_violation,
                "whitelist_violations": invalid_tools,
                "loop_violation": loop_violation,
                "plan": plan,
                "notes": case.get("notes", ""),
            }
        )

    safety = [
        item for item in details if item["expected_intent"] == "safety_risk"
    ]
    out_of_scope = [
        item for item in details if item["expected_intent"] == "out_of_scope"
    ]
    general = [
        item
        for item in details
        if item["expected_intent"] == "general_manual_search"
    ]
    step_counts = [len(item["plan"]["steps"]) for item in details]
    metric_reasons: dict[str, str] = {}
    if not safety:
        metric_reasons["safety_block_plan_accuracy"] = "没有safety_risk案例"
    if not out_of_scope:
        metric_reasons["out_of_scope_block_plan_accuracy"] = "没有out_of_scope案例"
    if not general:
        metric_reasons["unnecessary_tool_rate"] = "没有general_manual_search案例"

    return {
        "evaluation_type": "agentic_shadow_plan_eval",
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "dataset": {
            "file": str(dataset),
            "sha256": hashlib.sha256(dataset.read_bytes()).hexdigest(),
            "schema": str(schema_path),
            "intent_distribution": dict(
                Counter(case["expected_intent"] for case in cases)
            ),
        },
        "execution": {
            "api_called": False,
            "retrieval_called": False,
            "llm_called": False,
            "tools_executed": False,
            "routing_mode": "shadow",
            "planner_applied": False,
            "max_agent_rounds": planner.max_agent_rounds,
            "max_tool_calls": planner.max_tool_calls,
            "max_plan_steps": planner.MAX_STEPS,
        },
        "metrics": {
            "total_cases": len(details),
            "intent_accuracy": _rate(
                sum(item["intent_correct"] for item in details), len(details)
            ),
            "tool_selection_accuracy": _rate(
                sum(item["tool_selection_correct"] for item in details),
                len(details),
            ),
            "plan_valid_rate": _rate(
                sum(item["plan_valid"] for item in details), len(details)
            ),
            "safety_block_plan_accuracy": _rate(
                sum(item["safety_block_correct"] is True for item in safety),
                len(safety),
            ),
            "out_of_scope_block_plan_accuracy": _rate(
                sum(
                    item["out_of_scope_block_correct"] is True
                    for item in out_of_scope
                ),
                len(out_of_scope),
            ),
            "avg_plan_steps": round(statistics.mean(step_counts), 4)
            if step_counts
            else None,
            "max_plan_steps": max(step_counts) if step_counts else None,
            "unnecessary_tool_rate": _rate(
                unnecessary_tool_count, len(general)
            ),
            "budget_violation_count": budget_violation_count,
            "tool_whitelist_violation_count": whitelist_violation_count,
            "loop_violation_count": loop_violation_count,
        },
        "metric_unavailable_reasons": metric_reasons,
        "metric_definitions": {
            "intent_accuracy": "预测intent与人工expected_intent完全一致的比例。",
            "tool_selection_accuracy": "结构化plan工具序列与人工expected_tools完全一致的比例。",
            "plan_valid_rate": "步骤、白名单、预算、安全阻断、shadow模式和applied=false均满足约束的比例。",
            "unnecessary_tool_rate": "general_manual_search生成非单一search_manual计划的比例。",
            "loop_violation_count": "step_id非连续或同一action在单个线性计划中重复的案例数。",
        },
        "details": details,
        "disclaimer": (
            "本评测仅检查规则式Intent、候选路由和Bounded Planner的影子计划质量；"
            "不调用API、检索、工具或LLM，不代表最终问答准确率。"
        ),
    }


def render_markdown(report: dict[str, Any]) -> str:
    metrics = report["metrics"]

    def display(value: Any) -> str:
        if value is None:
            return "N/A"
        if isinstance(value, float):
            return f"{value:.4f}"
        return str(value)

    labels = (
        ("total_cases", "Total Cases"),
        ("intent_accuracy", "Intent Accuracy"),
        ("tool_selection_accuracy", "Tool Selection Accuracy"),
        ("plan_valid_rate", "Plan Valid Rate"),
        ("safety_block_plan_accuracy", "Safety Block Plan Accuracy"),
        ("out_of_scope_block_plan_accuracy", "Out-of-scope Block Plan Accuracy"),
        ("avg_plan_steps", "Avg Plan Steps"),
        ("max_plan_steps", "Max Plan Steps"),
        ("unnecessary_tool_rate", "Unnecessary Tool Rate"),
        ("budget_violation_count", "Budget Violation Count"),
        ("tool_whitelist_violation_count", "Tool Whitelist Violation Count"),
        ("loop_violation_count", "Loop Violation Count"),
    )
    lines = [
        "# Agentic Shadow Plan Evaluation",
        "",
        "> 本报告只评估影子Intent、候选工具与Bounded Planner，不代表最终问答准确率。",
        "",
        "- API调用：否",
        "- 检索调用：否",
        "- 工具执行：否",
        "- LLM调用：否",
        "- Planner应用到真实路由：否",
        "",
        "## Metrics",
        "",
        "| Metric | Value |",
        "|---|---:|",
    ]
    lines.extend(
        f"| {label} | {display(metrics[key])} |" for key, label in labels
    )
    reasons = report.get("metric_unavailable_reasons", {})
    if reasons:
        lines.extend(
            ["", "## N/A原因", "", *[f"- `{key}`：{reason}" for key, reason in reasons.items()]]
        )
    lines.extend(
        [
            "",
            "## 指标边界",
            "",
            *[
                f"- `{key}`：{definition}"
                for key, definition in report["metric_definitions"].items()
            ],
            "",
            report["disclaimer"],
            "",
        ]
    )
    return "\n".join(lines)


def write_reports(
    report: dict[str, Any], json_output: Path, md_output: Path
) -> None:
    json_output.parent.mkdir(parents=True, exist_ok=True)
    md_output.parent.mkdir(parents=True, exist_ok=True)
    json_output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    md_output.write_text(render_markdown(report), encoding="utf-8")


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(
        description="离线评估Agentic shadow intent、工具候选和Bounded Planner"
    )
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--schema", type=Path, default=DEFAULT_SCHEMA)
    parser.add_argument("--json-output", type=Path, default=DEFAULT_JSON_REPORT)
    parser.add_argument("--md-output", type=Path, default=DEFAULT_MD_REPORT)
    parser.add_argument("--max-agent-rounds", type=int, default=2)
    parser.add_argument("--max-tool-calls", type=int, default=4)
    args = parser.parse_args()
    try:
        report = run_evaluation(
            args.dataset.resolve(),
            args.schema.resolve(),
            max_agent_rounds=args.max_agent_rounds,
            max_tool_calls=args.max_tool_calls,
        )
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    write_reports(report, args.json_output.resolve(), args.md_output.resolve())
    print(
        json.dumps(
            {
                "metrics": report["metrics"],
                "json": str(args.json_output.resolve()),
                "md": str(args.md_output.resolve()),
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
