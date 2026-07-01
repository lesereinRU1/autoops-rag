from __future__ import annotations

import re
import time

from langgraph.graph import END, START, StateGraph

from app.agent.state import AgentState
from app.agent.tools import format_alarm, format_parameter, format_verified_solution
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
    def parse(state: AgentState) -> AgentState:
        question = state["question"]
        policy_question = state.get("original_question", question)
        refusal = service.scope_refusal(
            policy_question,
            state.get("model", "S7-1200"),
            state.get("version", ""),
        )
        refusal_reason = refusal["reason"] if refusal else ""
        refusal_kind = refusal["kind"] if refusal else ""
        alarm = extract_alarm(question)
        parameter_words = (
            "范围", "上下限", "参数", "端口", "波特率", "unit id", "寄存器地址",
            "mb_data_len", "rd_mb_data_len", "wr_mb_data_len",
        )
        if alarm:
            tool = "lookup_alarm_code"
            reason = f"检测到故障码 {alarm}，先查结构化故障码，再检索手册证据"
        elif any(word in question.lower() for word in parameter_words):
            tool = "check_parameter_range"
            reason = "检测到参数/范围意图，先查结构化参数，再检索版本化手册"
        else:
            tool = "search_manual"
            reason = "未检测到精确故障码或参数，执行混合语义检索"

        kg = service.memory.expand_knowledge_graph(question)
        trace = [
            {"node": "route", "tool": tool, "reason": reason},
            {
                "node": "knowledge_graph",
                "matched_entities": [item["label"] for item in kg["matched_entities"]],
                "expanded_terms": kg["expansion_terms"],
                "relations": len(kg["relations"]),
            },
        ]
        if refusal_reason:
            trace.append(
                {
                    "node": "scope_and_safety_gate",
                    "accepted": False,
                    "category": refusal_kind,
                    "reason": refusal_reason,
                }
            )
        return {
            "selected_tool": tool,
            "route_reason": reason,
            "knowledge_graph": kg,
            "rewritten_query": question,
            "retry_count": 0,
            "agent_trace": trace,
            "verified_solution_used": False,
            "refusal_reason": refusal_reason,
            "refusal_kind": refusal_kind,
        }

    def after_parse(state: AgentState) -> str:
        return "generate_refusal" if state.get("refusal_reason") else "execute"

    def generate_refusal(state: AgentState) -> AgentState:
        reason = state.get("refusal_reason", "现有资料不足")
        kind = state.get("refusal_kind", "unanswerable_scope")
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
                "model": service.settings.llm_model,
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
        }

    def execute(state: AgentState) -> AgentState:
        query = state.get("rewritten_query", state["question"])
        original_question = state["question"]
        model = state.get("model", "S7-1200")
        version = state.get("version", "")
        tool = state["selected_tool"]
        trace = list(state.get("agent_trace", []))
        result_parts: list[str] = []

        verified = service.memory.find_verified_solution(original_question, model)
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
                    "decision": "reuse_with_manual_verification",
                }
            )
        else:
            trace.append({"node": "verified_memory", "decision": "no_verified_match"})

        if tool == "lookup_alarm_code":
            record = service.memory.lookup_alarm(extract_alarm(query) or query, model)
            result_parts.append(format_alarm(record))
        elif tool == "check_parameter_range":
            value_match = VALUE_PATTERN.search(query.replace("S7-1200", ""))
            value = float(value_match.group(1)) if value_match else None
            record = service.find_parameter(query, model)
            result_parts.append(format_parameter(record, value))

        raw_kg_terms = state.get("knowledge_graph", {}).get("expansion_terms", [])
        # Graph expansion is intentionally conservative: broad one-hop expansion can
        # dilute role/address questions. Use it for exact alarm diagnosis; otherwise
        # keep the graph as explainable context and reserve expansion for a retry.
        kg_terms = raw_kg_terms[:3] if tool == "lookup_alarm_code" else []
        search_query = " ".join([query, *kg_terms]).strip()
        expansion_terms = expand_query(search_query)[1] if service.settings.enable_query_expansion else []
        retrieval_started = time.perf_counter()
        evidence, retrieval_trace = service.retriever.search_with_trace(
            search_query, top_k=5, model=model, version=version
        )
        round_retrieval_ms = (time.perf_counter() - retrieval_started) * 1000
        previous_retrieval_ms = float(state.get("retrieval_trace", {}).get("latency_ms", 0.0))
        retrieval_trace["round_latency_ms"] = round(round_retrieval_ms, 2)
        retrieval_trace["latency_ms"] = round(previous_retrieval_ms + round_retrieval_ms, 2)
        if verified:
            verified_evidence = service.chunks_by_ids(verified.get("source_chunk_ids", []))
            seen: set[str] = set()
            evidence = [
                hit
                for hit in [*verified_evidence, *evidence]
                if not (hit.chunk.chunk_id in seen or seen.add(hit.chunk.chunk_id))
            ][:5]
            retrieval_trace["final_evidence"] = service.retriever._trace_hits(evidence)
        distinct_docs = len({hit.chunk.doc_id for hit in evidence})
        top_score = float(evidence[0].rerank_score or evidence[0].score) if evidence else 0.0
        identifiers_supported = service.evidence_supports_query(query, evidence)
        sufficient = bool(evidence) and top_score > 0.01 and identifiers_supported
        trace.append(
            {
                "node": "hybrid_retrieval",
                "strategy": "dense+bm25+rrf+light_rerank",
                "query_expanded": bool(kg_terms),
                "hits": len(evidence),
                "distinct_documents": distinct_docs,
                "top_score": round(top_score, 6),
                "query_expansion_terms": expansion_terms,
            }
        )
        trace.append(
            {
                "node": "evidence_gate",
                "sufficient": sufficient,
                "identifiers_supported": identifiers_supported,
                "retry_count": state.get("retry_count", 0),
            }
        )
        return {
            "tool_result": "\n\n".join(part for part in result_parts if part),
            "evidence": evidence,
            "evidence_sufficient": sufficient,
            "agent_trace": trace,
            "verified_solution_used": verified_used,
            "retrieval_trace": retrieval_trace,
        }

    def after_execute(state: AgentState) -> str:
        if state.get("evidence_sufficient") or state.get("retry_count", 0) >= 1:
            return "generate_answer"
        return "rewrite"

    def rewrite(state: AgentState) -> AgentState:
        query = re.sub(r"(请问|麻烦|一下|应该如何|怎么办)", " ", state["question"])
        context = " ".join(
            filter(None, [state.get("model", ""), state.get("version", ""), "故障诊断 参数 手册"])
        )
        trace = list(state.get("agent_trace", []))
        trace.append({"node": "query_rewrite", "attempt": state.get("retry_count", 0) + 1})
        return {
            "rewritten_query": f"{query.strip()} {context}",
            "retry_count": state.get("retry_count", 0) + 1,
            "agent_trace": trace,
        }

    def generate_answer(state: AgentState) -> AgentState:
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
            }
        )
        return {
            "answer": outcome.answer,
            "agent_trace": trace,
            "generation_usage": {
                "mode": outcome.mode,
                "external_calls": outcome.external_calls,
                "model": outcome.model,
                "input_tokens": outcome.input_tokens,
                "output_tokens": outcome.output_tokens,
                "total_tokens": outcome.total_tokens,
                "token_usage_available": outcome.token_usage_available,
                "token_usage_missing_reason": outcome.token_usage_missing_reason,
                "first_token_latency_ms": outcome.first_token_latency_ms,
                "total_latency_ms": outcome.total_latency_ms,
                "fallback_reason": outcome.fallback_reason,
            },
        }

    graph = StateGraph(AgentState)
    graph.add_node("parse", parse)
    graph.add_node("execute", execute)
    graph.add_node("rewrite", rewrite)
    graph.add_node("generate_answer", generate_answer)
    graph.add_node("generate_refusal", generate_refusal)
    graph.add_edge(START, "parse")
    graph.add_conditional_edges(
        "parse", after_parse, {"execute": "execute", "generate_refusal": "generate_refusal"}
    )
    graph.add_conditional_edges(
        "execute",
        after_execute,
        {"generate_answer": "generate_answer", "rewrite": "rewrite"},
    )
    graph.add_edge("rewrite", "execute")
    graph.add_edge("generate_answer", END)
    graph.add_edge("generate_refusal", END)
    return graph.compile()
