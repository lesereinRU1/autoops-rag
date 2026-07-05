from app.agent.state import agentic_state_defaults
from app.config import Settings
from app.models import RagTraceResponse


def test_agentic_state_defaults_are_fresh_and_disabled():
    first = agentic_state_defaults()
    second = agentic_state_defaults()

    assert first == {
        "intent": {},
        "plan": {},
        "candidate_plan": [],
        "tool_calls": [],
        "round_count": 0,
        "budget": {},
        "stop_reason": "",
        "evidence_assessments": [],
        "agentic_enabled": False,
    }
    first["plan"]["steps"] = [{"tool": "test-only"}]
    assert second["plan"] == {}


def test_agentic_configuration_is_disabled_and_bounded_by_default():
    settings = Settings(_env_file=None)

    assert settings.enable_agentic_rag is False
    assert settings.enable_agentic_routing is False
    assert settings.enable_agentic_planner is False
    assert settings.enable_sqlite_table_tool is False
    assert settings.enable_iterative_retrieval is False
    assert settings.max_agent_rounds == 2
    assert settings.max_tool_calls == 4
    assert settings.max_llm_calls == 2
    assert settings.agent_timeout_seconds == 60.0
    assert settings.max_rewrites == 1


def test_legacy_trace_deserializes_with_agentic_defaults():
    legacy_trace = {
        "request_id": "legacy-request",
        "created_at": "2026-07-05T00:00:00+08:00",
        "original_question": "legacy question",
        "device_model": "S7-1200",
        "question_type": "search_manual",
        "selected_tool": "search_manual",
        "retrieval_strategy": "dense+bm25+rrf+light_rerank",
        "query_rewrite_attempts": 0,
        "llm_model": "local",
        "input_tokens": None,
        "output_tokens": None,
        "total_tokens": None,
        "token_usage_available": False,
        "token_usage_missing_reason": "llm_disabled",
        "first_token_latency_ms": None,
        "total_latency_ms": 10.0,
        "generation_mode": "local_extractive",
        "fallback_reason": "llm_disabled",
        "refused": False,
        "evidence_sufficient": True,
    }

    trace = RagTraceResponse.model_validate(legacy_trace)

    assert trace.intent == {}
    assert trace.plan == {}
    assert trace.candidate_plan == []
    assert trace.tool_calls == []
    assert trace.rounds == 0
    assert trace.budget == {}
    assert trace.stop_reason == ""
    assert trace.evidence_assessments == []

    legacy_trace["plan"] = []
    assert RagTraceResponse.model_validate(legacy_trace).plan == []
