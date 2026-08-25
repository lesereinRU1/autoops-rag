from __future__ import annotations

import re
import time

from langgraph.graph import END, START, StateGraph

from app.agent.executor import ControlledAgentExecutor
from app.agent.state import AgentState
from app.agent.intent import classify_intent
from app.agent.iterative import (
    assess_evidence,
    budget_snapshot,
    build_retry_query,
    merge_evidence_rounds,
    retry_stop_reason,
    should_retry_retrieval,
)
from app.agent.planner import BoundedQueryPlanner
from app.agent.tool_registry import ToolRegistry
from app.agent.tool_router import candidate_tools, should_execute_planner
from app.agent.tools import format_verified_solution
from app.generation.citation_guard import validate_citations
from app.models import (
    LookupFaultCodeInput,
    LookupParameterInput,
    SearchManualInput,
    ToolResult,
)
from app.retrieval.query_expansion import expand_query
from app.safety import format_policy_refusal


PREFIXED_ALARM_PATTERN = re.compile(r"(?:16#|0x)([0-9A-Fa-f]{2,4})", re.I)
HEX_ALARM_PATTERN = re.compile(
    r"(?<![0-9A-Za-z])(?=[0-9A-Fa-f]{4}(?![0-9A-Za-z]))(?=[0-9A-Fa-f]*[A-Fa-f])([0-9A-Fa-f]{4})"
)
NUMERIC_ALARM_PATTERN = re.compile(r"(?<!\d)(\d{4})(?!\d)")
VALUE_PATTERN = re.compile(r"(-?\d+(?:\.\d+)?)\s*(ms|s|V|mA|baud|个)?", re.I)


def extract_alarm(question: str) -> str | None:
    prefixed = PREFIXED_ALARM_PATTERN.search(question)
    if prefixed:
        return prefixed.group(1)
    hex_like = HEX_ALARM_PATTERN.search(question)
    if hex_like:
        return hex_like.group(1)
    if any(word in question.lower() for word in ("故障码", "报错", "报码", "status", "error")):
        numeric = NUMERIC_ALARM_PATTERN.search(question.replace("S7-1200", ""))
        if numeric:
            return numeric.group(1)
    return None


def build_graph(service):
    configured_model = getattr(
        service.settings, "llm_primary_model", service.settings.llm_model
    )
    planner = BoundedQueryPlanner(
        max_agent_rounds=getattr(service.settings, "max_agent_rounds", 2),
        max_tool_calls=getattr(service.settings, "max_tool_calls", 4),
    )
    iterative_enabled = bool(
        getattr(service.settings, "enable_iterative_retrieval", False)
    )
    registry = getattr(service, "tool_registry", None)
    if registry is None and hasattr(service, "memory") and hasattr(service, "retriever"):
        registry = ToolRegistry.from_service(service)
    agent_executor = (
        ControlledAgentExecutor(registry, service.settings)
        if registry is not None and hasattr(registry, "validate_arguments")
        else None
    )
    routing_enabled = bool(
        getattr(service.settings, "enable_agentic_routing", False)
    )

    def emit_workflow_event(
        state: AgentState,
        stage: str,
        message: str,
        data: dict | None = None,
    ) -> None:
        callback = state.get("workflow_event_callback")
        if not callable(callback):
            return
        try:
            callback(stage, message, data or {})
        except Exception:
            # A disconnected UI observer must never alter the RAG result.
            return

    def analyze_request(state: AgentState) -> AgentState:
        emit_workflow_event(state, "analyzing", "正在分析问题、范围与安全边界")
        agent_started_at = time.monotonic()
        question = state["question"]
        policy_question = state.get("original_question", question)
        refusal = service.scope_refusal(
            policy_question,
            state.get("model", "S7-1200"),
            state.get("version", ""),
        )
        refusal_reason = refusal["reason"] if refusal else ""
        refusal_kind = refusal["kind"] if refusal else ""
        intent_result = classify_intent(
            policy_question,
            model=state.get("model", "S7-1200"),
            version=state.get("version", ""),
        )
        alarm = extract_alarm(question)
        parameter_words = (
            "范围", "上下限", "参数", "端口", "波特率", "unit id", "寄存器地址",
            "mb_data_len", "rd_mb_data_len", "wr_mb_data_len",
        )
        if alarm:
            tool = "lookup_fault_code"
            reason = f"检测到故障码 {alarm}，先查结构化故障码，再检索手册证据"
        elif any(word in question.lower() for word in parameter_words):
            tool = "lookup_parameter"
            reason = "检测到参数/范围意图，先查结构化参数，再检索版本化手册"
        else:
            tool = "search_manual"
            reason = "未检测到精确故障码或参数，执行混合语义检索"
        selected_tool = {
            "lookup_fault_code": "lookup_alarm_code",
            "lookup_parameter": "check_parameter_range",
        }.get(tool, tool)
        available_agent_tools = getattr(registry, "agent_names", None)
        candidate_plan = candidate_tools(
            intent_result["intent"],
            registered_tools=available_agent_tools,
        )
        planner_eligible = should_execute_planner(
            intent_result["intent"],
            fixed_tool=tool,
            has_policy_refusal=bool(refusal_reason),
        )
        planner_should_execute = routing_enabled and planner_eligible
        known_document_pages = [
            {
                "document_id": hit.chunk.doc_id,
                "document_name": hit.chunk.doc_name,
                "page": hit.chunk.page,
            }
            for hit in state.get("evidence", [])
        ]
        planner_preparation_error = ""
        try:
            structured_plan = planner.build_plan(
                query=policy_question,
                intent=intent_result["intent"],
                candidate_tools=candidate_plan,
                model=state.get("model", "S7-1200"),
                version=state.get("version", ""),
                known_document_pages=known_document_pages,
            ).model_dump(mode="json")
        except Exception as exc:
            structured_plan = {}
            planner_preparation_error = f"planner_build_failed:{type(exc).__name__}"

        kg = service.memory.expand_knowledge_graph(question)
        trace = [
            {
                "node": "query_analyze",
                "alarm_code": alarm or "",
                "parameter_intent": tool == "lookup_parameter",
                "device_model": state.get("model", "S7-1200"),
                "version": state.get("version", ""),
            },
            {
                "node": "route",
                "tool": selected_tool,
                "registry_tool": tool,
                "reason": reason,
            },
            {
                "node": "intent_classifier_shadow",
                "shadow": True,
                **intent_result,
            },
            {
                "node": (
                    "tool_router_controlled"
                    if planner_should_execute
                    else "tool_router_shadow"
                ),
                "shadow": not planner_should_execute,
                "configured_enabled": bool(
                    getattr(service.settings, "enable_agentic_routing", False)
                ),
                "applied": False,
                "intent": intent_result["intent"],
                "candidate_plan": candidate_plan,
            },
            {
                "node": (
                    "query_planner_candidate"
                    if planner_should_execute
                    else "query_planner_shadow"
                ),
                "shadow": not planner_should_execute,
                "configured_enabled": bool(
                    getattr(service.settings, "enable_agentic_routing", False)
                ),
                "applied": False,
                "plan": structured_plan,
                "preparation_error": planner_preparation_error,
            },
            {
                "node": "knowledge_graph",
                "matched_entities": [item["label"] for item in kg["matched_entities"]],
                "expanded_terms": kg["expansion_terms"],
                "relations": len(kg["relations"]),
            },
        ]
        trace.append(
            {
                "node": "scope_and_safety_gate",
                "accepted": not bool(refusal_reason),
                "category": refusal_kind,
                "reason": refusal_reason,
            }
        )
        if refusal_kind == "unsafe_request":
            initial_stop_reason = "safety_blocked"
        elif refusal_kind == "unanswerable_scope":
            initial_stop_reason = "out_of_scope"
        elif refusal_reason:
            initial_stop_reason = "insufficient_evidence"
        else:
            initial_stop_reason = ""
        if not refusal_reason:
            emit_workflow_event(
                state,
                "tool_selected",
                "已完成固定路由并选择受控工具",
                {"tool_name": tool, "selected_tool": selected_tool},
            )
        initial_tracking = {
            **state,
            "agent_started_at": agent_started_at,
            "round_count": 0,
            "retry_count": 0,
            "tool_calls": [],
        }
        return {
            "selected_tool": selected_tool,
            "execution_tool": tool,
            "intent": intent_result,
            "candidate_plan": candidate_plan,
            "plan": structured_plan,
            "route_reason": reason,
            "knowledge_graph": kg,
            "rewritten_query": question,
            "retry_count": 0,
            "agent_trace": trace,
            "verified_solution_used": False,
            "refusal_reason": refusal_reason,
            "refusal_kind": refusal_kind,
            "round_count": 0,
            "tool_calls": [],
            "rewritten_queries": [],
            "retrieval_rounds_trace": [],
            "evidence_assessments": [],
            "agent_started_at": agent_started_at,
            "stop_reason": initial_stop_reason,
            "budget": budget_snapshot(initial_tracking, service.settings),
            "agentic_routing_enabled": routing_enabled,
            "planner_should_execute": planner_should_execute,
            "planner_attempted": False,
            "planner_applied": False,
            "planner_fallback": False,
            "planner_fallback_reason": "",
            "planner_preparation_error": planner_preparation_error,
            "planner_round": 0,
            "tool_result_cache": {},
            "tool_call_signatures": [],
        }

    def after_policy_gate(state: AgentState) -> str:
        if state.get("refusal_reason"):
            return "generate_refusal"
        if state.get("planner_should_execute"):
            return "execute_agent_plan"
        return "execute"

    def execute_agent_plan(state: AgentState) -> AgentState:
        trace = list(state.get("agent_trace", []))
        fallback_reason = state.get("planner_preparation_error", "")
        outcome = None
        recovery_tool_calls = list(state.get("tool_calls", []))
        recovery_cache = dict(state.get("tool_result_cache", {}))
        recovery_signatures = list(state.get("tool_call_signatures", []))
        execution_state = {
            **state,
            "tool_calls": recovery_tool_calls,
            "tool_result_cache": recovery_cache,
            "tool_call_signatures": recovery_signatures,
        }
        if not fallback_reason and agent_executor is None:
            fallback_reason = "executor_unavailable"
        if not fallback_reason:
            try:
                outcome = agent_executor.execute_plan(
                    state.get("plan", {}), execution_state
                )
                fallback_reason = outcome.fallback_reason
            except Exception as exc:
                fallback_reason = f"executor_exception:{type(exc).__name__}"
                # ``call_or_reuse`` publishes each completed Registry result to
                # this shared cache before executor post-processing. Recover its
                # actual trace and signature so fallback keeps both exactly-once
                # execution and accurate request-level budget accounting.
                recorded_attempts = {
                    (str(item.get("tool_name", "")), str(item.get("started_at", "")))
                    for item in recovery_tool_calls
                    if isinstance(item, dict)
                }
                for signature, cached_result in recovery_cache.items():
                    cached_trace = getattr(cached_result, "call_trace", None)
                    if cached_trace is not None and cached_trace.executed:
                        try:
                            trace_payload = cached_trace.model_dump(mode="json")
                            identity = (
                                str(trace_payload.get("tool_name", "")),
                                str(trace_payload.get("started_at", "")),
                            )
                            if identity not in recorded_attempts:
                                recovery_tool_calls.append(trace_payload)
                                recorded_attempts.add(identity)
                        except Exception:
                            # Recovery bookkeeping is best-effort; the cached
                            # ToolResult still prevents a second Registry call.
                            pass
                    if signature not in recovery_signatures:
                        recovery_signatures.append(signature)

        applied = bool(outcome and outcome.applied)
        fallback = bool(fallback_reason or (outcome and outcome.fallback))
        planner_round = outcome.planner_round if outcome else 1
        tool_calls = (
            outcome.tool_calls if outcome else recovery_tool_calls
        )
        cache = (
            outcome.tool_result_cache
            if outcome
            else recovery_cache
        )
        signatures = (
            outcome.tool_call_signatures
            if outcome
            else recovery_signatures
        )
        evidence = outcome.evidence if outcome else list(state.get("evidence", []))
        result_parts = outcome.result_parts if outcome else []
        trace.append(
            {
                "node": "controlled_planner_execution",
                "planner_attempted": True,
                "planner_applied": applied,
                "planner_fallback": fallback,
                "fallback_reason": fallback_reason,
                "planner_round": planner_round,
                "input_summary": {
                    "intent": state.get("intent", {}).get("intent", ""),
                    "query_length": len(state.get("original_question", "")),
                    "model": state.get("model", "S7-1200"),
                    "has_version": bool(state.get("version", "")),
                },
                "candidate_plan": state.get("plan", {}),
                "applied_plan": state.get("plan", {}) if applied else {},
                "budget_snapshot": (
                    outcome.budget
                    if outcome
                    else budget_snapshot(
                        {**state, "planner_round": planner_round}, service.settings
                    )
                ),
            }
        )
        next_state = {
            **state,
            "planner_round": planner_round,
            "tool_calls": tool_calls,
            "tool_result_cache": cache,
            "retry_count": state.get("retry_count", 0),
        }
        return {
            "planner_attempted": True,
            "planner_applied": applied,
            "planner_fallback": fallback,
            "planner_fallback_reason": fallback_reason,
            "planner_round": planner_round,
            "agent_trace": trace,
            "tool_calls": tool_calls,
            "tool_result_cache": cache,
            "tool_call_signatures": signatures,
            "evidence": evidence,
            "tool_result": "\n\n".join(result_parts),
            "budget": budget_snapshot(next_state, service.settings),
        }

    def generate_refusal(state: AgentState) -> AgentState:
        reason = state.get("refusal_reason", "现有资料不足")
        kind = state.get("refusal_kind", "unanswerable_scope")
        emit_workflow_event(
            state,
            "generating",
            "安全或范围检查未通过，正在生成边界说明",
            {"refusal_kind": kind},
        )
        trace = list(state.get("agent_trace", []))
        trace.append({"node": "safe_refusal", "category": kind, "reason": reason})
        return {
            "answer": format_policy_refusal(
                kind, reason, state.get("model", "S7-1200")
            ),
            "evidence": [],
            "evidence_sufficient": False,
            "agent_trace": trace,
            "generation_usage": {
                "mode": "local_extractive",
                "external_calls": 0,
                "model": configured_model,
                "attempted_models": [],
                "final_model": "",
                "input_tokens": None,
                "output_tokens": None,
                "total_tokens": None,
                "token_usage_available": False,
                "token_usage_missing_reason": "policy_refusal",
                "first_token_latency_ms": None,
                "total_latency_ms": 0.0,
                "fallback_reason": "policy_refusal",
            },
            "retrieval_trace": {},
            "stop_reason": state.get("stop_reason") or "insufficient_evidence",
            "budget": budget_snapshot(state, service.settings),
        }

    def execute_tool(state: AgentState) -> AgentState:
        original_question = state["question"]
        model = state.get("model", "S7-1200")
        tool = state.get("execution_tool", state["selected_tool"])
        trace = list(state.get("agent_trace", []))
        tool_calls = list(state.get("tool_calls", []))
        result_parts: list[str] = []
        if state.get("tool_result"):
            result_parts.append(state["tool_result"])

        verified_started = time.perf_counter()
        verified = service.memory.find_verified_solution(original_question, model)
        verified_latency_ms = round((time.perf_counter() - verified_started) * 1000, 2)
        verified_used = verified is not None
        if verified:
            result_parts.append(format_verified_solution(verified))
            service.memory.record_solution_reuse(
                verified["id"], state.get("session_id", "demo"), original_question
            )
            trace.append(
                {
                    "node": "verified_memory",
                    "solution_id": verified["id"],
                    "similarity": verified["similarity"],
                    "latency_ms": verified_latency_ms,
                    "decision": "reuse_with_manual_verification",
                }
            )
        else:
            trace.append(
                {
                    "node": "verified_memory",
                    "latency_ms": verified_latency_ms,
                    "decision": "no_verified_match",
                }
            )

        result: ToolResult | None = None
        structured_arguments = None
        if tool == "lookup_fault_code":
            structured_arguments = LookupFaultCodeInput(
                    code=extract_alarm(original_question) or original_question,
                    model=model,
                    version=state.get("version", ""),
            )
        elif tool == "lookup_parameter":
            value_match = VALUE_PATTERN.search(
                original_question.replace("S7-1200", "")
            )
            structured_arguments = LookupParameterInput(
                    name=original_question,
                    model=model,
                    version=state.get("version", ""),
                    value=float(value_match.group(1)) if value_match else None,
            )
        cache = dict(state.get("tool_result_cache", {}))
        if registry is not None and structured_arguments is not None:
            if agent_executor is not None and state.get("planner_attempted"):
                result, cache, _ = agent_executor.call_or_reuse(
                    tool,
                    structured_arguments,
                    {**state, "tool_calls": tool_calls},
                    planner_round=max(int(state.get("planner_round", 0)), 1),
                )
            else:
                result = registry.execute(
                    tool,
                    structured_arguments,
                    tool_calls=tool_calls,
                    max_tool_calls=getattr(service.settings, "max_tool_calls", 4),
                )
        if result is not None:
            if result.content:
                result_parts.append(result.content)
            if result.call_trace is not None:
                tool_calls.append(result.call_trace.model_dump(mode="json"))

        trace.append(
            {
                "node": "tool_execute",
                "tool": tool,
                "deferred_to_retrieve": tool == "search_manual",
                "structured_result": bool(result_parts),
                "success": result.success if result is not None else True,
                "error": result.error if result is not None else "",
                "verified_solution_used": verified_used,
            }
        )
        next_state = {**state, "tool_calls": tool_calls}
        stop_reason = state.get("stop_reason", "")
        if result is not None and result.error == "max_tool_calls_reached":
            stop_reason = "max_tool_calls_reached"
        return {
            "tool_result": "\n\n".join(part for part in result_parts if part),
            "agent_trace": trace,
            "verified_solution_used": verified_used,
            "verified_source_chunk_ids": (
                list(verified.get("source_chunk_ids", [])) if verified else []
            ),
            "tool_calls": tool_calls,
            "tool_result_cache": cache,
            "stop_reason": stop_reason,
            "budget": budget_snapshot(next_state, service.settings),
        }

    def retrieve(state: AgentState) -> AgentState:
        query = state.get("rewritten_query", state["question"])
        model = state.get("model", "S7-1200")
        version = state.get("version", "")
        tool = state.get("execution_tool", state["selected_tool"])
        trace = list(state.get("agent_trace", []))
        emit_workflow_event(
            state,
            "retrieving",
            "正在通过 Tool Registry 检索手册证据",
            {"query": query, "round": int(state.get("round_count", 0)) + 1},
        )

        raw_kg_terms = state.get("knowledge_graph", {}).get("expansion_terms", [])
        # Graph expansion is intentionally conservative: broad one-hop expansion can
        # dilute role/address questions. Use it for exact alarm diagnosis; otherwise
        # keep the graph as explainable context and reserve expansion for a retry.
        kg_terms = raw_kg_terms[:3] if tool == "lookup_fault_code" else []
        search_query = " ".join([query, *kg_terms]).strip()
        expansion_terms = expand_query(search_query)[1] if service.settings.enable_query_expansion else []
        existing_tool_calls = list(state.get("tool_calls", []))
        cache = dict(state.get("tool_result_cache", {}))
        if registry is None:
            search_result = ToolResult(
                tool_name="search_manual",
                success=False,
                error="tool_registry_unavailable",
            )
        elif agent_executor is not None and state.get("planner_attempted"):
            try:
                search_result, cache, _ = agent_executor.call_or_reuse(
                    "search_manual",
                    SearchManualInput(
                        query=search_query,
                        model=model,
                        version=version,
                        top_k=5,
                    ),
                    {**state, "tool_calls": existing_tool_calls},
                    planner_round=max(int(state.get("planner_round", 0)), 1),
                )
            except Exception:
                search_result = ToolResult(
                    tool_name="search_manual",
                    success=False,
                    error="tool_execution_failed",
                )
        else:
            search_result = registry.execute(
                "search_manual",
                SearchManualInput(
                    query=search_query,
                    model=model,
                    version=version,
                    top_k=5,
                ),
                tool_calls=existing_tool_calls,
                max_tool_calls=getattr(service.settings, "max_tool_calls", 4),
            )
        new_evidence = list(search_result.evidence) if search_result.success else []
        retrieval_trace = dict(search_result.metadata.get("retrieval_trace", {}))
        emit_workflow_event(
            state,
            "reranking",
            "检索完成，正在评估融合排序结果",
            {
                "result_count": len(new_evidence),
                "success": search_result.success,
                "error": search_result.error,
            },
        )
        round_retrieval_ms = float(search_result.latency_ms)
        previous_retrieval_ms = float(state.get("retrieval_trace", {}).get("latency_ms", 0.0))
        retrieval_trace["round_latency_ms"] = round(round_retrieval_ms, 2)
        retrieval_trace["latency_ms"] = round(previous_retrieval_ms + round_retrieval_ms, 2)
        verified_source_chunk_ids = state.get("verified_source_chunk_ids", [])
        if verified_source_chunk_ids:
            verified_evidence = service.chunks_by_ids(verified_source_chunk_ids)
            seen: set[str] = set()
            new_evidence = [
                hit
                for hit in [*verified_evidence, *new_evidence]
                if not (hit.chunk.chunk_id in seen or seen.add(hit.chunk.chunk_id))
            ][:5]
        previous_evidence = list(state.get("evidence", []))
        evidence = (
            merge_evidence_rounds(previous_evidence, new_evidence)
            if (iterative_enabled or state.get("planner_attempted"))
            and previous_evidence
            else new_evidence
        )
        retrieval_trace["final_evidence"] = service.retriever._trace_hits(evidence)
        distinct_docs = len({hit.chunk.doc_id for hit in evidence})
        top_score = float(evidence[0].rerank_score or evidence[0].score) if evidence else 0.0
        next_round = int(state.get("round_count", 0)) + 1
        intent = state.get("intent", {})
        intent_name = intent.get("intent", "") if isinstance(intent, dict) else str(intent)
        assessment = assess_evidence(
            query,
            evidence,
            round_count=next_round,
            intent=intent_name,
            identifiers_supported=service.evidence_supports_query(query, evidence),
            apply_retry_filter=iterative_enabled,
        )
        identifiers_supported = bool(assessment["identifiers_supported"])
        sufficient = bool(assessment["sufficient"])
        tool_calls = existing_tool_calls
        if search_result.call_trace is not None:
            tool_call = search_result.call_trace.model_dump(mode="json")
            tool_call["round"] = next_round
            tool_calls.append(tool_call)
        decision_state = {
            **state,
            "evidence": evidence,
            "round_count": next_round,
            "tool_calls": tool_calls,
        }
        retry_allowed = should_retry_retrieval(
            decision_state, assessment, service.settings
        )
        tool_stop_reason = {
            "max_tool_calls_reached": "max_tool_calls_reached",
            "tool_timeout": "tool_timeout",
            "tool_execution_failed": "tool_error",
            "tool_registry_unavailable": "tool_error",
            "agent_timeout": "timeout_reached",
        }.get(search_result.error, "")
        if tool_stop_reason:
            stop_reason = tool_stop_reason
        elif sufficient:
            stop_reason = "evidence_sufficient"
        elif iterative_enabled and retry_allowed:
            stop_reason = ""
        elif iterative_enabled:
            stop_reason = retry_stop_reason(
                decision_state,
                service.settings,
                assessment=assessment,
            )
        elif not state.get("planner_attempted"):
            # Preserve the pre-Stage-G fixed workflow: with iterative retrieval
            # disabled it performs at most one legacy rewrite, independently of
            # the new controlled-Agent budget fields.
            stop_reason = (
                "insufficient_evidence"
                if int(state.get("retry_count", 0)) >= 1
                else ""
            )
        elif state.get("retry_count", 0) >= int(
            getattr(service.settings, "max_rewrites", 1)
        ):
            stop_reason = "max_rewrites_reached"
        else:
            current_budget = budget_snapshot(decision_state, service.settings)
            if current_budget["remaining_ms"] <= 0:
                stop_reason = "timeout_reached"
            elif current_budget["remaining_rounds"] <= 0:
                stop_reason = "max_rounds_reached"
            elif current_budget["remaining_tool_calls"] <= 0:
                stop_reason = "max_tool_calls_reached"
            elif current_budget["remaining_rewrites"] <= 0:
                stop_reason = "max_rewrites_reached"
            else:
                stop_reason = ""
        assessment = {
            **assessment,
            "retry_allowed": retry_allowed,
            "stop_reason": stop_reason,
        }
        assessments = [*state.get("evidence_assessments", []), assessment]
        round_trace = {
            "round": next_round,
            "query": state["question"],
            "rewritten_query": query if query != state["question"] else "",
            "evidence_count": len(evidence),
            "evidence_score": round(top_score, 8),
            "evidence_passed": sufficient,
            "stop_reason": stop_reason,
            "raw_missing_terms": assessment["raw_missing_terms"],
            "filtered_missing_terms": assessment["filtered_missing_terms"],
            "generic_terms_ignored": assessment["generic_terms_ignored"],
        }
        retrieval_rounds_trace = [
            *state.get("retrieval_rounds_trace", []),
            round_trace,
        ]
        trace.append(
            {
                "node": "hybrid_retrieval",
                "strategy": "dense+bm25+rrf+light_rerank",
                "query_expanded": bool(kg_terms),
                "hits": len(evidence),
                "distinct_documents": distinct_docs,
                "top_score": round(top_score, 6),
                "query_expansion_terms": expansion_terms,
                "tool_success": search_result.success,
                "tool_error": search_result.error,
            }
        )
        trace.append(
            {
                "node": "evidence_gate",
                "sufficient": sufficient,
                "identifiers_supported": identifiers_supported,
                "retry_count": state.get("retry_count", 0),
                "reason": assessment["reason"],
                "recommended_next_action": assessment["recommended_next_action"],
                "retry_eligible": assessment["retry_eligible"],
                "raw_missing_terms": assessment["raw_missing_terms"],
                "filtered_missing_terms": assessment["filtered_missing_terms"],
                "generic_terms_ignored": assessment["generic_terms_ignored"],
            }
        )
        next_state = {
            **decision_state,
            "evidence_assessments": assessments,
            "retrieval_rounds_trace": retrieval_rounds_trace,
        }
        return {
            "evidence": evidence,
            "evidence_sufficient": sufficient,
            "agent_trace": trace,
            "retrieval_trace": retrieval_trace,
            "round_count": next_round,
            "tool_calls": tool_calls,
            "tool_result_cache": cache,
            "evidence_assessments": assessments,
            "retrieval_rounds_trace": retrieval_rounds_trace,
            "stop_reason": stop_reason,
            "budget": budget_snapshot(next_state, service.settings),
        }

    def after_evidence_gate(state: AgentState) -> str:
        if state.get("stop_reason") in {
            "max_tool_calls_reached",
            "max_rounds_reached",
            "max_rewrites_reached",
            "tool_timeout",
            "tool_error",
            "timeout_reached",
        }:
            return "generate_answer"
        if iterative_enabled:
            if state.get("evidence_sufficient"):
                return "generate_answer"
            assessments = state.get("evidence_assessments", [])
            assessment = assessments[-1] if assessments else {}
            return (
                "rewrite"
                if should_retry_retrieval(state, assessment, service.settings)
                else "generate_answer"
            )
        legacy_rewrite_limit = (
            int(getattr(service.settings, "max_rewrites", 1))
            if state.get("planner_attempted")
            else 1
        )
        if state.get("evidence_sufficient") or state.get(
            "retry_count", 0
        ) >= legacy_rewrite_limit:
            return "generate_answer"
        return "rewrite"

    def rewrite(state: AgentState) -> AgentState:
        emit_workflow_event(
            state,
            "rewriting",
            "当前证据不足，正在执行有界问题改写",
            {"attempt": int(state.get("retry_count", 0)) + 1},
        )
        if iterative_enabled:
            assessments = state.get("evidence_assessments", [])
            assessment = assessments[-1] if assessments else {}
            rewritten_query = build_retry_query(state["question"], state, assessment)
        else:
            query = re.sub(r"(请问|麻烦|一下|应该如何|怎么办)", " ", state["question"])
            context = " ".join(
                filter(None, [state.get("model", ""), state.get("version", ""), "故障诊断 参数 手册"])
            )
            rewritten_query = f"{query.strip()} {context}"
        trace = list(state.get("agent_trace", []))
        retry_count = state.get("retry_count", 0) + 1
        trace.append(
            {
                "node": "query_rewrite",
                "attempt": retry_count,
                "mode": "iterative" if iterative_enabled else "legacy",
                "query": rewritten_query,
            }
        )
        rewritten_queries = [*state.get("rewritten_queries", []), rewritten_query]
        next_state = {
            **state,
            "retry_count": retry_count,
            "rewritten_queries": rewritten_queries,
        }
        return {
            "rewritten_query": rewritten_query,
            "retry_count": retry_count,
            "agent_trace": trace,
            "rewritten_queries": rewritten_queries,
            "budget": budget_snapshot(next_state, service.settings),
        }

    def generate_answer(state: AgentState) -> AgentState:
        emit_workflow_event(
            state,
            "generating",
            "正在基于已通过 Evidence Gate 的证据生成回答",
            {"evidence_count": len(state.get("evidence", []))},
        )
        outcome = service.generator.generate(
            state["question"],
            state.get("evidence", []),
            state.get("tool_result", ""),
            allow_llm=state.get("evidence_sufficient", False),
        )
        trace = list(state.get("agent_trace", []))
        trace.append(
            {
                "node": "answer_with_citations",
                "evidence_count": len(state.get("evidence", [])),
                "mode": outcome.mode,
                "fallback_reason": outcome.fallback_reason,
                "attempted_models": outcome.attempted_models,
                "final_model": outcome.final_model,
            }
        )
        stop_reason = state.get("stop_reason") or (
            "evidence_sufficient"
            if state.get("evidence_sufficient", False)
            else "insufficient_evidence"
        )
        next_state = {
            **state,
            "stop_reason": stop_reason,
        }
        return {
            "answer": outcome.answer,
            "agent_trace": trace,
            "generation_usage": {
                "mode": outcome.mode,
                "external_calls": outcome.external_calls,
                "model": outcome.model,
                "attempted_models": outcome.attempted_models,
                "final_model": outcome.final_model,
                "input_tokens": outcome.input_tokens,
                "output_tokens": outcome.output_tokens,
                "total_tokens": outcome.total_tokens,
                "token_usage_available": outcome.token_usage_available,
                "token_usage_missing_reason": outcome.token_usage_missing_reason,
                "first_token_latency_ms": outcome.first_token_latency_ms,
                "total_latency_ms": outcome.total_latency_ms,
                "fallback_reason": outcome.fallback_reason,
            },
            "stop_reason": stop_reason,
            "budget": budget_snapshot(
                next_state,
                service.settings,
                llm_calls_used=outcome.external_calls,
            ),
        }

    def citation_guard(state: AgentState) -> AgentState:
        evidence = state.get("evidence", [])
        answer = state.get("answer", "")
        emit_workflow_event(
            state,
            "citation_check",
            "正在执行 Citation Guard",
            {"evidence_count": len(evidence)},
        )
        valid, warnings = validate_citations(answer, evidence)
        trace = list(state.get("agent_trace", []))
        action = "accept"
        generation_usage = dict(state.get("generation_usage", {}))
        if not valid:
            fallback = service.generator.generate(
                state["question"],
                evidence,
                state.get("tool_result", ""),
                allow_llm=False,
            )
            answer = fallback.answer
            final_valid, final_warnings = validate_citations(answer, evidence)
            action = "fallback_local_extractive"
            warnings = final_warnings
            generation_usage.update(
                {
                    "mode": fallback.mode,
                    "final_model": "",
                    "fallback_reason": "citation_guard_failed",
                    "token_usage_missing_reason": "citation_guard_failed",
                }
            )
            valid = final_valid
        trace.append(
            {
                "node": "citation_guard",
                "valid": valid,
                "action": action,
                "warnings": warnings,
            }
        )
        return {
            "answer": answer,
            "agent_trace": trace,
            "citation_warnings": warnings,
            "generation_usage": generation_usage,
        }

    graph = StateGraph(AgentState)
    graph.add_node("analyze_request", analyze_request)
    graph.add_node("execute_tool", execute_tool)
    graph.add_node("execute_agent_plan", execute_agent_plan)
    graph.add_node("retrieve", retrieve)
    graph.add_node("rewrite", rewrite)
    graph.add_node("generate_answer", generate_answer)
    graph.add_node("citation_guard", citation_guard)
    graph.add_node("generate_refusal", generate_refusal)
    graph.add_edge(START, "analyze_request")
    graph.add_conditional_edges(
        "analyze_request",
        after_policy_gate,
        {
            "execute": "execute_tool",
            "execute_agent_plan": "execute_agent_plan",
            "generate_refusal": "generate_refusal",
        },
    )
    graph.add_edge("execute_agent_plan", "execute_tool")
    graph.add_edge("execute_tool", "retrieve")
    graph.add_conditional_edges(
        "retrieve",
        after_evidence_gate,
        {"generate_answer": "generate_answer", "rewrite": "rewrite"},
    )
    graph.add_edge("rewrite", "retrieve")
    graph.add_edge("generate_answer", "citation_guard")
    graph.add_edge("citation_guard", END)
    graph.add_edge("generate_refusal", END)
    return graph.compile()
