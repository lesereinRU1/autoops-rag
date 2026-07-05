from types import SimpleNamespace

from app.agent.iterative import retry_stop_reason, should_retry_retrieval


def _config(**overrides):
    values = {
        "enable_iterative_retrieval": True,
        "max_agent_rounds": 2,
        "max_tool_calls": 4,
        "max_llm_calls": 2,
        "agent_timeout_seconds": 60.0,
        "max_rewrites": 1,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


ASSESSMENT = {
    "sufficient": False,
    "reason": "missing_identifier",
    "filtered_missing_terms": ["MB_CLIENT"],
    "retry_eligible": True,
    "recommended_next_action": "rewrite_and_retry",
}


def test_retry_requires_feature_flag_and_insufficient_evidence():
    state = {"round_count": 1, "retry_count": 0, "tool_calls": [], "agent_started_at": 10.0}
    assert should_retry_retrieval(state, ASSESSMENT, _config(), now=11.0)
    assert not should_retry_retrieval(state, ASSESSMENT, _config(enable_iterative_retrieval=False), now=11.0)
    assert not should_retry_retrieval(state, {**ASSESSMENT, "sufficient": True}, _config(), now=11.0)


def test_round_rewrite_tool_and_timeout_budgets_stop_retry():
    base = {"round_count": 1, "retry_count": 0, "tool_calls": [], "agent_started_at": 10.0}

    state = {**base, "round_count": 2}
    assert not should_retry_retrieval(state, ASSESSMENT, _config(), now=11.0)
    assert retry_stop_reason(state, _config(), now=11.0) == "max_rounds_reached"

    state = {**base, "retry_count": 1}
    assert not should_retry_retrieval(state, ASSESSMENT, _config(), now=11.0)
    assert retry_stop_reason(state, _config(), now=11.0) == "max_rewrites_reached"

    state = {**base, "tool_calls": [{"tool": "x"}] * 4}
    assert not should_retry_retrieval(state, ASSESSMENT, _config(), now=11.0)
    assert retry_stop_reason(state, _config(), now=11.0) == "max_tool_calls_reached"

    assert not should_retry_retrieval(base, ASSESSMENT, _config(), now=70.0)
    assert retry_stop_reason(base, _config(), now=70.0) == "timeout_reached"


def test_policy_intents_cannot_retry():
    base = {"round_count": 1, "retry_count": 0, "tool_calls": [], "agent_started_at": 10.0}
    safety = {**base, "intent": {"intent": "safety_risk"}}
    out = {**base, "intent": {"intent": "out_of_scope"}}
    assert not should_retry_retrieval(safety, ASSESSMENT, _config(), now=11.0)
    assert not should_retry_retrieval(out, ASSESSMENT, _config(), now=11.0)
    assert retry_stop_reason(safety, _config(), now=11.0) == "safety_blocked"
    assert retry_stop_reason(out, _config(), now=11.0) == "out_of_scope"
