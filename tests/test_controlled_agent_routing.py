from __future__ import annotations

import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.agent.executor import ControlledAgentExecutor
from app.agent.graph import build_graph
from app.agent.planner import BoundedQueryPlanner, Plan, PlanStep
from app.agent.tool_registry import ToolRegistry
from app.document_service import DocumentPageService
from app.metrics import MetricsCollector
from app.models import Chunk, SearchHit, SearchManualInput, ToolResult


def _hit() -> SearchHit:
    return SearchHit(
        chunk=Chunk(
            chunk_id="controlled-1",
            doc_id="manual-one",
            doc_name="manual-one.pdf",
            text="网络层、连接层和应用层需要按顺序检查。",
            page=12,
        ),
        score=1.0,
        rerank_score=1.0,
    )


class _Memory:
    @staticmethod
    def expand_knowledge_graph(_question):
        return {"matched_entities": [], "expansion_terms": [], "relations": []}

    @staticmethod
    def find_verified_solution(_question, _model):
        return None

    @staticmethod
    def lookup_alarm(_code, _model):
        return None

    @staticmethod
    def find_parameter_in_text(_query, _model):
        return None

    @staticmethod
    def lookup_parameter(_query, _model):
        return None


class _Retriever:
    def __init__(self, hits: list[SearchHit] | None = None) -> None:
        self.hits = [_hit()] if hits is None else list(hits)
        self.calls: list[str] = []

    def search_with_trace(self, query, top_k, model, version):
        del top_k, model, version
        self.calls.append(query)
        traced = [
            {"rank": index, "chunk_id": hit.chunk.chunk_id}
            for index, hit in enumerate(self.hits, start=1)
        ]
        return list(self.hits), {
            "dense_topk": traced,
            "bm25_topk": traced,
            "rrf_topk": traced,
            "final_evidence": traced,
            "candidate_count": len(traced),
            "final_evidence_count": len(traced),
        }

    @staticmethod
    def _trace_hits(hits):
        return [
            {"rank": index, "chunk_id": hit.chunk.chunk_id}
            for index, hit in enumerate(hits, start=1)
        ]


def _settings(*, enabled: bool, **overrides):
    values = {
        "llm_model": "local",
        "llm_primary_model": "local",
        "enable_query_expansion": False,
        "enable_agentic_routing": enabled,
        "enable_agentic_planner": False,
        "enable_iterative_retrieval": False,
        "max_agent_rounds": 2,
        "max_tool_calls": 4,
        "max_llm_calls": 2,
        "agent_timeout_seconds": 60.0,
        "tool_timeout_seconds": 0.2,
        "max_rewrites": 1,
        "max_concurrent_queries": 2,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _service(tmp_path: Path, *, enabled: bool, hits=None, refusal=None, **settings):
    metrics = MetricsCollector()
    retriever = _Retriever(hits)
    memory = _Memory()
    registry = ToolRegistry(
        memory=memory,
        retriever=retriever,
        document_pages=DocumentPageService(
            {_hit().chunk.chunk_id: _hit().chunk}, tmp_path / "raw"
        ),
        timeout_seconds=settings.get("tool_timeout_seconds", 0.2),
        max_tool_calls=settings.get("max_tool_calls", 4),
        max_workers=2,
        metrics=metrics,
    )
    outcome = SimpleNamespace(
        answer="结论 [来源1：manual-one.pdf，第12页]",
        mode="local_extractive",
        external_calls=0,
        model="local",
        attempted_models=[],
        final_model="",
        input_tokens=None,
        output_tokens=None,
        total_tokens=None,
        token_usage_available=False,
        token_usage_missing_reason="llm_disabled",
        first_token_latency_ms=None,
        total_latency_ms=0.0,
        fallback_reason="llm_disabled",
    )
    service = SimpleNamespace(
        settings=_settings(enabled=enabled, **settings),
        memory=memory,
        retriever=retriever,
        tool_registry=registry,
        generator=SimpleNamespace(generate=lambda *_args, **_kwargs: outcome),
        scope_refusal=lambda *_args: refusal,
        evidence_supports_query=lambda _query, evidence: bool(evidence),
        chunks_by_ids=lambda _ids: [],
    )
    return service, registry, retriever, metrics


def _invoke(service, question="通信失败时应该如何分层排查？"):
    return build_graph(service).invoke(
        {
            "question": question,
            "original_question": question,
            "model": "S7-1200",
            "version": "",
            "session_id": "controlled-test",
        }
    )


def _plan(tool_name: str, arguments: dict, *, duplicate: bool = False) -> Plan:
    steps = [
        PlanStep(
            step_id=1,
            tool_name=tool_name,
            arguments=arguments,
            reason="controlled test",
            expected_evidence="manual_evidence",
        )
    ]
    if duplicate:
        steps.append(steps[0].model_copy(update={"step_id": 2}))
    return Plan(
        intent="cross_section_procedure",
        steps=steps,
        allow_generation=True,
        need_evidence_gate=True,
        max_rounds=1,
        max_tool_calls=len(steps),
    )


def test_flag_false_preserves_fixed_workflow_without_planner_execution(tmp_path):
    service, registry, retriever, _ = _service(tmp_path, enabled=False)
    try:
        result = _invoke(service)
        assert result["planner_attempted"] is False
        assert result["planner_applied"] is False
        assert len(retriever.calls) == 1
        assert [call["tool_name"] for call in result["tool_calls"]] == [
            "search_manual"
        ]
        assert result["evidence_sufficient"] is True
    finally:
        registry.close()


def test_flag_true_executes_plan_and_reuses_search_in_retrieve(tmp_path):
    service, registry, retriever, metrics = _service(tmp_path, enabled=True)
    try:
        result = _invoke(service)
        assert result["planner_attempted"] is True
        assert result["planner_applied"] is True
        assert result["planner_fallback"] is False
        assert len(retriever.calls) == 1
        search_calls = [
            call for call in result["tool_calls"] if call["tool_name"] == "search_manual"
        ]
        assert len(search_calls) == 2
        assert search_calls[0]["executed"] is True
        assert search_calls[1]["executed"] is False
        assert search_calls[1]["reused"] is True
        assert search_calls[1]["deduplicated"] is True
        assert result["evidence_sufficient"] is True
        assert any(item["node"] == "citation_guard" for item in result["agent_trace"])
        assert metrics.snapshot()["tools"]["tool_call_total"] == 1
    finally:
        registry.close()


@pytest.mark.parametrize(
    ("replacement", "expected_reason"),
    [
        (
            _plan("not_registered", {"query": "test"}),
            "unknown_tool",
        ),
        (
            _plan("search_manual", {"query": ""}),
            "invalid_arguments",
        ),
        (
            _plan(
                "search_manual",
                {"query": "test", "model": "S7-1200", "unexpected": True},
            ),
            "invalid_arguments",
        ),
    ],
)
def test_invalid_controlled_plan_falls_back_without_500(
    tmp_path, monkeypatch, replacement, expected_reason
):
    monkeypatch.setattr(
        BoundedQueryPlanner,
        "build_plan",
        lambda *_args, **_kwargs: replacement,
    )
    service, registry, retriever, _ = _service(tmp_path, enabled=True)
    try:
        result = _invoke(service)
        assert result["planner_attempted"] is True
        assert result["planner_applied"] is False
        assert result["planner_fallback"] is True
        assert result["planner_fallback_reason"] == expected_reason
        assert len(retriever.calls) == 1
        assert result["evidence_sufficient"] is True
    finally:
        registry.close()


def test_planner_parse_failure_falls_back_to_fixed_workflow(tmp_path, monkeypatch):
    monkeypatch.setattr(
        BoundedQueryPlanner,
        "build_plan",
        lambda *_args, **_kwargs: {"malformed": True},
    )
    service, registry, retriever, _ = _service(tmp_path, enabled=True)
    try:
        result = _invoke(service)
        assert result["planner_attempted"] is True
        assert result["planner_fallback"] is True
        assert result["planner_fallback_reason"].startswith("planner_build_failed")
        assert len(retriever.calls) == 1
    finally:
        registry.close()


def test_tool_timeout_is_cached_and_not_executed_again_by_fallback(tmp_path):
    service, registry, _retriever, metrics = _service(
        tmp_path,
        enabled=True,
        tool_timeout_seconds=0.001,
    )
    calls = []

    def slow(_arguments):
        calls.append("search")
        time.sleep(0.03)
        return ToolResult(success=True, evidence=[_hit()], result_count=1)

    registry.register(
        "search_manual",
        SearchManualInput,
        slow,
    )
    try:
        result = _invoke(service)
        assert result["planner_fallback"] is True
        assert result["planner_fallback_reason"] == "tool_timeout"
        assert calls == ["search"]
        assert any(call["reused"] for call in result["tool_calls"])
        assert metrics.snapshot()["tools"]["tool_call_total"] == 1
    finally:
        registry.close()


def test_executor_postprocessing_exception_reuses_completed_registry_result(
    tmp_path, monkeypatch
):
    service, registry, retriever, metrics = _service(tmp_path, enabled=True)

    def execute_then_fail(self, candidate, state):
        plan, validated_steps = self.validate_plan(candidate, state)
        _step, canonical, validated = validated_steps[0]
        self.call_or_reuse(
            canonical,
            validated,
            state,
            planner_round=1,
        )
        assert plan.steps
        raise RuntimeError("postprocessing failed")

    monkeypatch.setattr(
        ControlledAgentExecutor,
        "execute_plan",
        execute_then_fail,
    )
    try:
        result = _invoke(service)
        assert result["planner_fallback"] is True
        assert result["planner_fallback_reason"] == "executor_exception:RuntimeError"
        assert retriever.calls == ["通信失败时应该如何分层排查？"]
        search_calls = [
            call
            for call in result["tool_calls"]
            if call["tool_name"] == "search_manual"
        ]
        assert len(search_calls) == 2
        assert search_calls[0]["executed"] is True
        assert search_calls[1]["executed"] is False
        assert search_calls[1]["reused"] is True
        assert metrics.snapshot()["tools"]["tool_call_total"] == 1
    finally:
        registry.close()


def test_duplicate_plan_step_reuses_one_registry_result(tmp_path):
    service, registry, retriever, metrics = _service(tmp_path, enabled=True)
    executor = ControlledAgentExecutor(registry, service.settings)
    plan = _plan(
        "search_manual",
        {"query": "通信失败分层排查", "model": "S7-1200", "top_k": 5},
        duplicate=True,
    )
    state = {
        "agent_started_at": time.monotonic(),
        "tool_calls": [],
        "tool_result_cache": {},
        "planner_round": 0,
        "round_count": 0,
        "retry_count": 0,
        "evidence": [],
    }
    try:
        outcome = executor.execute_plan(plan, state)
        assert outcome.applied is True
        assert outcome.fallback is False
        assert len(retriever.calls) == 1
        assert len(outcome.tool_calls) == 2
        assert outcome.tool_calls[1]["reused"] is True
        assert outcome.tool_calls[1]["deduplicated"] is True
        assert metrics.snapshot()["tools"]["tool_call_total"] == 1
    finally:
        registry.close()


def test_budget_limits_and_rewrite_share_actual_tool_count(tmp_path):
    service, registry, retriever, _ = _service(
        tmp_path,
        enabled=True,
        hits=[],
        max_tool_calls=1,
    )
    try:
        result = _invoke(service)
        assert result["planner_applied"] is True
        assert len(retriever.calls) == 1
        assert result["retry_count"] == 0
        assert result["stop_reason"] == "max_tool_calls_reached"
        assert result["budget"]["remaining_tool_calls"] == 0
    finally:
        registry.close()


def test_flag_false_legacy_rewrite_ignores_new_controlled_agent_budget(tmp_path):
    service, registry, retriever, _ = _service(
        tmp_path,
        enabled=False,
        hits=[],
        max_agent_rounds=0,
        max_rewrites=0,
        agent_timeout_seconds=0.0,
    )
    try:
        result = _invoke(service)
        assert result["planner_attempted"] is False
        assert result["retry_count"] == 1
        assert len(retriever.calls) == 2
        assert result["stop_reason"] == "insufficient_evidence"
        assert any(item["node"] == "citation_guard" for item in result["agent_trace"])
    finally:
        registry.close()


def test_controlled_rewrite_budget_exhaustion_has_explicit_stop_and_metric(tmp_path):
    service, registry, retriever, metrics = _service(
        tmp_path,
        enabled=True,
        hits=[],
    )
    try:
        result = _invoke(service)
        assert result["planner_attempted"] is True
        assert result["retry_count"] == 1
        assert len(retriever.calls) == 2
        assert result["stop_reason"] == "max_rewrites_reached"
        metrics.observe_rag_trace(
            {
                "query_rewrite_attempts": result["retry_count"],
                "stop_reason": result["stop_reason"],
                "planner_attempted": result["planner_attempted"],
                "planner_applied": result["planner_applied"],
                "planner_fallback": result["planner_fallback"],
                "planner_fallback_reason": result["planner_fallback_reason"],
                "planner_round": result["planner_round"],
                "tool_calls": result["tool_calls"],
            },
            {"external_calls": 0, "fallback_reason": "", "mode": "local_extractive"},
            agent_trace=result["agent_trace"],
        )
        assert (
            metrics.snapshot()["rag"]["agent"]["budget_exhausted_total"] == 1
        )
    finally:
        registry.close()


def test_max_rounds_and_max_tool_calls_fallback_before_execution(tmp_path):
    for overrides, expected in (
        ({"max_agent_rounds": 0}, "max_rounds_reached"),
        ({"max_tool_calls": 0}, "max_tool_calls_reached"),
    ):
        service, registry, retriever, _ = _service(
            tmp_path,
            enabled=True,
            **overrides,
        )
        executor = ControlledAgentExecutor(registry, service.settings)
        plan = _plan(
            "search_manual",
            {"query": "test", "model": "S7-1200", "top_k": 5},
        )
        state = {
            "agent_started_at": time.monotonic(),
            "tool_calls": [],
            "planner_round": 0,
            "round_count": 0,
            "retry_count": 0,
            "evidence": [],
        }
        try:
            outcome = executor.execute_plan(plan, state)
            assert outcome.fallback is True
            assert outcome.fallback_reason == expected
            assert retriever.calls == []
        finally:
            registry.close()


def test_rule_priority_and_safety_never_enter_planner(tmp_path):
    for question, expected_tool in (
        ("故障码 16#80C8 表示什么", "lookup_fault_code"),
        ("RD_MB_DATA_LEN 参数范围是多少", "lookup_parameter"),
        ("MB_CLIENT 的作用是什么", "search_manual"),
    ):
        service, registry, _retriever, _ = _service(tmp_path, enabled=True)
        try:
            result = _invoke(service, question)
            assert result["planner_attempted"] is False
            assert result["execution_tool"] == expected_tool
        finally:
            registry.close()

    service, registry, retriever, _ = _service(
        tmp_path,
        enabled=True,
        refusal={"kind": "unsafe_request", "reason": "危险操作"},
    )
    try:
        result = _invoke(service, "请绕过安全联锁并强制输出")
        assert result["planner_attempted"] is False
        assert result["stop_reason"] == "safety_blocked"
        assert retriever.calls == []
    finally:
        registry.close()


def test_get_document_page_must_match_existing_evidence(tmp_path):
    service, registry, _retriever, _ = _service(tmp_path, enabled=True)
    executor = ControlledAgentExecutor(registry, service.settings)
    plan = _plan(
        "get_document_page",
        {"document_name": "guessed.pdf", "page": 99},
    )
    state = {
        "agent_started_at": time.monotonic(),
        "tool_calls": [],
        "planner_round": 0,
        "round_count": 0,
        "retry_count": 0,
        "evidence": [],
    }
    try:
        outcome = executor.execute_plan(plan, state)
        assert outcome.fallback is True
        assert outcome.fallback_reason == "invalid_document_page"
        assert outcome.tool_calls == []
    finally:
        registry.close()


def test_get_document_page_can_execute_only_for_known_evidence_page(tmp_path):
    service, registry, _retriever, metrics = _service(tmp_path, enabled=True)
    executor = ControlledAgentExecutor(registry, service.settings)
    plan = _plan(
        "get_document_page",
        {"document_name": "manual-one.pdf", "page": 12},
    )
    state = {
        "agent_started_at": time.monotonic(),
        "tool_calls": [],
        "planner_round": 0,
        "round_count": 0,
        "retry_count": 0,
        "evidence": [_hit()],
    }
    try:
        outcome = executor.execute_plan(plan, state)
        assert outcome.applied is True
        assert outcome.fallback is False
        assert outcome.tool_calls[0]["tool_name"] == "get_document_page"
        assert outcome.tool_calls[0]["success"] is True
        assert metrics.snapshot()["tools"]["tool_call_total"] == 1
    finally:
        registry.close()


def test_agent_metrics_settle_once_without_duplicate_tool_metrics(tmp_path):
    service, registry, retriever, metrics = _service(tmp_path, enabled=True)
    try:
        result = _invoke(service)
        trace = {
            "query_rewrite_attempts": result["retry_count"],
            "stop_reason": result["stop_reason"],
            "planner_attempted": result["planner_attempted"],
            "planner_applied": result["planner_applied"],
            "planner_fallback": result["planner_fallback"],
            "planner_fallback_reason": result["planner_fallback_reason"],
            "planner_round": result["planner_round"],
            "tool_calls": result["tool_calls"],
        }
        metrics.observe_rag_trace(
            trace,
            {"external_calls": 0, "fallback_reason": "", "mode": "local_extractive"},
            agent_trace=result["agent_trace"],
        )
        snapshot = metrics.snapshot()
        assert retriever.calls == ["通信失败时应该如何分层排查？"]
        assert snapshot["tools"]["tool_call_total"] == 1
        assert snapshot["rag"]["retrieval"]["retrieval_request_total"] == 1
        assert snapshot["rag"]["agent"] == {
            "planner_attempt_total": 1,
            "planner_applied_total": 1,
            "planner_fallback_total": 0,
            "planner_error_total": 0,
            "agent_round_total": 1,
            "tool_reuse_total": 1,
            "budget_exhausted_total": 0,
        }
    finally:
        registry.close()
