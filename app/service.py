from __future__ import annotations

import json
import re
import time
from datetime import datetime

from app.agent.graph import build_graph
from app.agent.memory import MemoryStore
from app.config import PROJECT_ROOT, get_settings
from app.concurrency import ReadWriteLock
from app.generation.answer_generator import AnswerGenerator
from app.generation.citation_guard import validate_citations
from app.ingestion.pipeline import ingest_corpus
from app.models import ChatRequest, ChatResponse, Chunk, FeedbackRequest, SearchHit, VerifiedSolutionRequest
from app.retrieval.hybrid import HybridRetriever
from app.retrieval.query_expansion import technical_terms
from app.safety import is_unsafe_operation_request
from app.tracing import TraceStore


class AutoOpsService:
    def __init__(self) -> None:
        self.settings = get_settings()
        self.memory = MemoryStore(self.settings.sqlite_path, self.settings.data_dir / "seed")
        self.generator = AnswerGenerator(self.settings)
        self.retriever = HybridRetriever(self.settings)
        self._chunk_by_id = self._load_chunk_map()
        self._known_alarm_codes = {
            value.upper().replace("16#", "")
            for chunk in self._chunk_by_id.values()
            for value in re.findall(r"16#[0-9A-Fa-f]{2,4}", chunk.text)
        }
        self.graph = build_graph(self)
        self.access = ReadWriteLock()
        self.traces = TraceStore(PROJECT_ROOT / "reports" / "rag_traces.jsonl")

    def scope_refusal(
        self, question: str, model: str, version: str = ""
    ) -> dict[str, str] | None:
        lowered = question.lower()
        if is_unsafe_operation_request(question):
            return {
                "kind": "unsafe_request",
                "reason": "请求涉及强制控制、旁路安全保护、在线写入或省略现场安全程序",
            }

        unsupported_brands = (
            "allen-bradley", "controllogix", "rockwell", "三菱", "fx5u",
            "欧姆龙", "施耐德", "schneider", "台达", "汇川", "abb",
        )
        if any(value.lower() in lowered for value in unsupported_brands):
            return {
                "kind": "unanswerable_scope",
                "reason": "当前知识库没有目标厂商或型号的对应资料，不能套用 Siemens S7-1200 的证据",
            }

        normalized_model = re.sub(r"[\s_-]", "", model.lower())
        if normalized_model and "s71200" not in normalized_model:
            return {
                "kind": "unanswerable_scope",
                "reason": f"当前知识库没有 {model} 的对应资料，不能套用其他型号的证据",
            }

        version_text = " ".join(filter(None, (question, version)))
        requested_versions = set(
            re.findall(r"(?<![A-Za-z0-9])V\d+(?:\.\d+)+", version_text, re.I)
        )
        requested_versions.update(
            f"V{value}"
            for value in re.findall(
                r"(?:固件|手册)(?:版本)?\s*(\d+(?:\.\d+)+)", version_text, re.I
            )
        )
        if requested_versions:
            available = {
                chunk.version.lower()
                for chunk in self._chunk_by_id.values()
                if chunk.model.lower() == model.lower() and chunk.version
            }
            for requested in sorted(requested_versions):
                if not any(requested.lower() in version for version in available):
                    return {
                        "kind": "unanswerable_version",
                        "reason": f"当前索引没有 {model} {requested} 对应资料，不能套用其他版本的证据",
                    }

        alarm_values = re.findall(r"16#([0-9A-Fa-f]{2,4})", question)
        for value in alarm_values:
            if value.upper() not in self._known_alarm_codes and not self.memory.lookup_alarm(value, model):
                return {
                    "kind": "unanswerable_scope",
                    "reason": f"当前资料未收录故障码 16#{value.upper()}，不能借用其他状态码解释",
                }
        return None

    def scope_refusal_reason(
        self, question: str, model: str, version: str = ""
    ) -> str | None:
        decision = self.scope_refusal(question, model, version)
        return decision["reason"] if decision else None

    @staticmethod
    def evidence_supports_query(query: str, evidence: list[SearchHit]) -> bool:
        if not evidence:
            return False
        identifiers = technical_terms(query) - {"1200", "1500"}
        if not identifiers:
            return True
        evidence_terms = set().union(*(technical_terms(hit.chunk.text) for hit in evidence))
        supported = len(identifiers & evidence_terms)
        return supported / len(identifiers) >= 0.75

    def find_parameter(self, query: str, model: str) -> dict | None:
        return self.memory.find_parameter_in_text(query, model)

    def _load_chunk_map(self) -> dict[str, Chunk]:
        if not self.settings.chunks_file.exists():
            return {}
        with self.settings.chunks_file.open("r", encoding="utf-8") as handle:
            chunks = [Chunk.model_validate(json.loads(line)) for line in handle if line.strip()]
        return {chunk.chunk_id: chunk for chunk in chunks}

    def chunks_by_ids(self, chunk_ids: list[str]) -> list[SearchHit]:
        return [
            SearchHit(chunk=self._chunk_by_id[cid], score=1.0, rerank_score=1.0)
            for cid in chunk_ids
            if cid in self._chunk_by_id
        ]

    def search(
        self, query: str, top_k: int, model: str, version: str, strategy: str = "hybrid"
    ) -> list[SearchHit]:
        with self.access.read():
            return self.retriever.search_with_strategy(
                query, strategy=strategy, top_k=top_k, model=model, version=version
            )

    @staticmethod
    def _context_items(evidence: list[SearchHit]) -> list[dict]:
        return [
            {
                "source_number": index,
                "chunk_id": hit.chunk.chunk_id,
                "doc_name": hit.chunk.doc_name,
                "page": hit.chunk.page,
                "section_path": hit.chunk.section_path,
                "text": hit.chunk.text,
            }
            for index, hit in enumerate(evidence, start=1)
        ]

    def chat(self, request: ChatRequest, request_id: str) -> ChatResponse:
        started = time.perf_counter()
        original_question = request.query
        resolved_question, context_turns_used = self.memory.build_followup_query(
            request.session_id, original_question
        )
        graph_input = request.model_dump()
        graph_input.pop("query")
        graph_input["question"] = resolved_question
        graph_input["original_question"] = original_question
        with self.access.read():
            state = self.graph.invoke(graph_input)
        _, warnings = validate_citations(state["answer"], state.get("evidence", []))
        trace = list(state.get("agent_trace", []))
        if context_turns_used:
            trace.insert(
                0,
                {
                    "node": "conversation_context",
                    "turns_used": context_turns_used,
                    "history_chars": len(resolved_question) - len(original_question),
                },
            )
        retrieval_rounds = sum(item.get("node") == "hybrid_retrieval" for item in trace)
        selected_tool = state.get("selected_tool", "search_manual")
        generation_usage = state.get("generation_usage", {})
        evidence = state.get("evidence", [])
        source_chunk_ids = [hit.chunk.chunk_id for hit in evidence]
        self.memory.save_session(
            request.session_id,
            request.model,
            request.version,
            f"Q: {original_question}\nA: {state['answer']}",
        )
        self.memory.save_turn(
            request.session_id,
            request.model,
            request.version,
            original_question,
            state["answer"],
            selected_tool,
            source_chunk_ids,
        )
        total_ms = round((time.perf_counter() - started) * 1000, 2)
        fallback_reason = generation_usage.get("fallback_reason", "")
        token_usage_available = bool(generation_usage.get("token_usage_available", False))
        token_usage_missing_reason = generation_usage.get("token_usage_missing_reason", "")
        if not token_usage_available and not token_usage_missing_reason:
            token_usage_missing_reason = "provider_did_not_return_usage"
        retrieval_trace = state.get("retrieval_trace", {})
        rag_trace = {
            "request_id": request_id,
            "created_at": datetime.now().astimezone().isoformat(timespec="milliseconds"),
            "original_question": original_question,
            "device_model": request.model,
            "question_type": selected_tool,
            "selected_tool": selected_tool,
            "retrieval_strategy": "dense+bm25+rrf+light_rerank",
            "query_rewrite_attempts": sum(
                item.get("node") == "query_rewrite" for item in trace
            ),
            "dense_topk": retrieval_trace.get("dense_topk", []),
            "bm25_topk": retrieval_trace.get("bm25_topk", []),
            "rrf_topk": retrieval_trace.get("rrf_topk", []),
            "final_evidence": self.retriever._trace_hits(evidence),
            "injected_context": self._context_items(evidence),
            "used_chunk_ids": source_chunk_ids,
            "llm_model": generation_usage.get("model") or self.settings.llm_model,
            "input_tokens": generation_usage.get("input_tokens"),
            "output_tokens": generation_usage.get("output_tokens"),
            "total_tokens": generation_usage.get("total_tokens"),
            "token_usage_available": token_usage_available,
            "token_usage_missing_reason": token_usage_missing_reason,
            "first_token_latency_ms": generation_usage.get("first_token_latency_ms"),
            "retrieval_latency_ms": float(retrieval_trace.get("latency_ms", 0.0)),
            "llm_latency_ms": round(float(generation_usage.get("total_latency_ms", 0.0)), 2),
            "total_latency_ms": total_ms,
            "generation_mode": generation_usage.get("mode", "local_extractive"),
            "fallback_reason": fallback_reason,
            "refused": bool(state.get("refusal_reason")) or not state.get("evidence_sufficient", False),
            "evidence_sufficient": state.get("evidence_sufficient", False),
            "warnings": warnings,
        }
        rag_trace = self.traces.append(rag_trace)
        return ChatResponse(
            request_id=request_id,
            answer=state["answer"],
            evidence=evidence,
            selected_tool=selected_tool,
            evidence_sufficient=state.get("evidence_sufficient", False),
            warnings=warnings,
            agent_trace=trace,
            knowledge_graph=state.get("knowledge_graph", {}),
            verified_solution_used=state.get("verified_solution_used", False),
            runtime={
                "total_ms": total_ms,
                "context_turns_used": context_turns_used,
                "context_chars": len(resolved_question) - len(original_question),
                "retrieval_rounds": retrieval_rounds,
                "retrieval_operations": retrieval_rounds * 2,
                "structured_queries": int(selected_tool != "search_manual"),
                "retrieval_latency_ms": float(retrieval_trace.get("latency_ms", 0.0)),
                "external_llm_calls": generation_usage.get("external_calls", 0),
                "external_token_usage": generation_usage.get("total_tokens"),
                "external_input_tokens": generation_usage.get("input_tokens"),
                "external_output_tokens": generation_usage.get("output_tokens"),
                "token_usage_available": token_usage_available,
                "token_usage_missing_reason": token_usage_missing_reason,
                "first_token_latency_ms": generation_usage.get("first_token_latency_ms"),
                "llm_latency_ms": round(float(generation_usage.get("total_latency_ms", 0.0)), 2),
                "llm_model": generation_usage.get("model") or self.settings.llm_model,
                "generation_mode": generation_usage.get("mode", "local_extractive"),
                "generation_fallback_reason": fallback_reason,
            },
            rag_trace=rag_trace,
        )

    def get_trace(self, request_id: str) -> dict | None:
        return self.traces.get(request_id)

    def recent_traces(self, limit: int = 20) -> list[dict]:
        return self.traces.recent(limit)

    def clear_session(self, session_id: str) -> int:
        return self.memory.clear_session(session_id)

    def reindex(self, mode: str = "semantic") -> dict:
        with self.access.write():
            self.retriever.close()
            result = ingest_corpus(mode=mode, rebuild=True)
            self.retriever = HybridRetriever(self.settings)
            self._chunk_by_id = self._load_chunk_map()
            self._known_alarm_codes = {
                value.upper().replace("16#", "")
                for chunk in self._chunk_by_id.values()
                for value in re.findall(r"16#[0-9A-Fa-f]{2,4}", chunk.text)
            }
            self.graph = build_graph(self)
            return result

    def save_solution(self, request: VerifiedSolutionRequest) -> int:
        valid_ids: set[str] = set()
        if self.settings.chunks_file.exists():
            with self.settings.chunks_file.open("r", encoding="utf-8") as handle:
                valid_ids = {json.loads(line)["chunk_id"] for line in handle if line.strip()}
        invalid = set(request.source_chunk_ids) - valid_ids
        if invalid:
            raise ValueError(f"以下引用不存在，拒绝保存：{', '.join(sorted(invalid))}")
        return self.memory.save_verified_solution(request.model_dump())

    def save_feedback(self, request: FeedbackRequest) -> int:
        return self.memory.save_feedback(request.model_dump())

    def graph_context(self, query: str) -> dict:
        return self.memory.expand_knowledge_graph(query)

    def status(self) -> dict:
        sources_file = self.settings.raw_dir / "sources.json"
        sources = json.loads(sources_file.read_text(encoding="utf-8")) if sources_file.exists() else []
        active_sources = [item for item in sources if item.get("ingest")]
        table_chunks = [
            chunk for chunk in self._chunk_by_id.values()
            if chunk.metadata.get("representation") == "table_row"
        ]
        return {
            "project_root": str(self.settings.data_dir.parent),
            "embedding_backend": self.retriever.vector.backend_name,
            "embedding_model": self.settings.embedding_model,
            "collection": self.settings.qdrant_collection,
            "qdrant_mode": self.retriever.vector.storage_mode,
            "query_expansion_enabled": self.settings.enable_query_expansion,
            "max_concurrent_queries": self.settings.max_concurrent_queries,
            "request_timeout_seconds": self.settings.request_timeout_seconds,
            "rate_limit_per_minute": self.settings.rate_limit_per_minute,
            "indexed_chunks": self.retriever.vector.count(),
            "table_row_chunks": len(table_chunks),
            "structured_tables": len(
                {chunk.metadata.get("table_id") for chunk in table_chunks if chunk.metadata.get("table_id")}
            ),
            "raw_files": len([p for p in self.settings.raw_dir.iterdir() if p.is_file()]),
            "active_sources": len(active_sources),
            "current_sources": len(
                [item for item in active_sources if str(item.get("status", "")).startswith("current")]
            ),
            "latest_checked_at": max((item.get("checked_at", "") for item in sources), default=""),
            "llm_enabled": bool(
                self.settings.llm_enabled
                and self.settings.llm_base_url
                and self.settings.llm_api_key
            ),
            "llm_model": self.settings.llm_model,
        }

    def close(self) -> None:
        with self.access.write():
            self.retriever.close()
