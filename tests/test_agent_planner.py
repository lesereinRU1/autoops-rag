import pytest
from pydantic import ValidationError

from app.agent.planner import BoundedQueryPlanner, Plan
from app.agent.tool_router import candidate_tools


@pytest.mark.parametrize(
    ("intent", "expected_tools"),
    [
        ("alarm_diagnosis", ["lookup_fault_code", "search_manual"]),
        ("parameter_lookup", ["lookup_parameter", "search_manual"]),
        ("table_lookup", ["search_manual"]),
        ("cross_section_procedure", ["search_manual"]),
        ("version_resolution", ["search_manual"]),
        ("general_manual_search", ["search_manual"]),
    ],
)
def test_bounded_planner_builds_strict_schema_plan(intent, expected_tools):
    planner = BoundedQueryPlanner(max_agent_rounds=2, max_tool_calls=4)

    plan = planner.build_plan(
        query="test query",
        intent=intent,
        candidate_tools=candidate_tools(intent),
    )

    assert isinstance(plan, Plan)
    assert [step.tool_name for step in plan.steps] == expected_tools
    assert plan.allow_generation is True
    assert plan.need_evidence_gate is True
    assert all(step.arguments for step in plan.steps)
    assert all(step.reason and step.expected_evidence for step in plan.steps)


@pytest.mark.parametrize("intent", ["safety_risk", "out_of_scope"])
def test_policy_intents_cannot_plan_tools_or_generation(intent):
    planner = BoundedQueryPlanner(max_agent_rounds=2, max_tool_calls=4)

    plan = planner.build_plan(
        query="blocked query",
        intent=intent,
        candidate_tools=["search_manual", "lookup_fault_code"],
    )

    assert plan.steps == []
    assert plan.allow_generation is False
    assert plan.need_evidence_gate is False
    assert plan.max_rounds == 0
    assert plan.max_tool_calls == 0


def test_plan_is_limited_by_steps_tool_budget_round_budget_and_whitelist():
    planner = BoundedQueryPlanner(max_agent_rounds=0, max_tool_calls=1)

    plan = planner.build_plan(
        query="16#80C8",
        intent="alarm_diagnosis",
        candidate_tools=[
            "lookup_fault_code",
            "search_manual",
            "not_a_real_tool",
        ],
    )

    assert len(plan.steps) == 1
    assert len(plan.steps) <= planner.MAX_STEPS
    assert plan.max_tool_calls == 1
    assert plan.max_tool_calls <= planner.max_tool_calls
    assert plan.max_rounds == 0
    assert plan.max_rounds <= planner.max_agent_rounds
    assert all(step.tool_name in candidate_tools("alarm_diagnosis") for step in plan.steps)
    assert "not_a_real_tool" not in str(plan)


def test_plan_schema_rejects_extra_fields_and_non_sequential_steps():
    with pytest.raises(ValidationError):
        Plan.model_validate(
            {
                "intent": "general_manual_search",
                "steps": [
                    {
                        "step_id": 2,
                        "tool_name": "search_manual",
                        "arguments": {"query": "test"},
                        "reason": "test",
                        "expected_evidence": "manual_evidence",
                    }
                ],
                "allow_generation": True,
                "need_evidence_gate": True,
                "max_rounds": 1,
                "max_tool_calls": 1,
                "unexpected": True,
            }
        )
