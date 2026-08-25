from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class CitationReferenceResult(BaseModel):
    """One deduplicated citation target evaluated against this request's Evidence."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    reference_key: str
    source_index: int | None = None
    chunk_id: str | None = None
    document: str | None = None
    page: int | None = None
    valid: bool
    errors: list[str] = Field(default_factory=list)


class CitationEvaluation(BaseModel):
    """Rule result for citations that are applicable to a generated answer."""

    model_config = ConfigDict(extra="forbid")

    citation_valid: bool
    citation_invalid_count: int
    citation_reference_count: int
    citation_guard_fallback: bool
    references: list[CitationReferenceResult] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)


class TechnicalIdentifierEvaluation(BaseModel):
    """Exact identifier comparison derived from required_facts, not human fields."""

    model_config = ConfigDict(extra="forbid")

    source: Literal["derived from required_facts"] = "derived from required_facts"
    expected: dict[str, list[str]] = Field(default_factory=dict)
    matched: dict[str, list[str]] = Field(default_factory=dict)
    missing: dict[str, list[str]] = Field(default_factory=dict)
    matched_count: int
    total_count: int
    accuracy: float | None


class EvaluationCaseResult(BaseModel):
    """Stable per-case result; non-applicable values are serialized as JSON null."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    case_id: str
    question: str
    category: str
    category_group: str
    split: str
    answerable: bool
    expected_refusal: bool
    expected_refusal_type: str | None = None
    expected_tool: str
    selected_tool: str | None = None
    expected_tool_matched: bool | None = None
    request_id: str | None = None
    http_status: int | None = None

    evidence_chunk_ids: list[str] | None = None
    gold_chunk_ids: list[str] | None = None
    retrieval_hit: bool | None = None
    strict_recall_at_5: float | None = Field(default=None, alias="strict_recall@5")
    reciprocal_rank: float | None = None
    ndcg_at_5: float | None = Field(default=None, alias="ndcg@5")
    top1_correct: bool | None = None
    multi_hop_evidence_coverage: float | None = None
    multi_hop_evidence_matched: int | None = None
    multi_hop_evidence_total: int | None = None

    citation_valid: bool | None = None
    citation_invalid_count: int | None = None
    citation_reference_count: int | None = None
    citation_guard_fallback: bool | None = None
    citation_errors: list[str] | None = None
    citation_references: list[dict[str, Any]] | None = None

    required_fact_coverage: float | None = None
    required_fact_exact_coverage: float | None = None
    required_fact_hits: list[str] | None = None
    required_fact_exact_hits: list[str] | None = None
    required_fact_total: int | None = None
    required_fact_diagnostics: list[dict[str, Any]] | None = None

    technical_identifier_accuracy: float | None = None
    technical_identifier_source: str | None = None
    technical_identifier_expected: dict[str, list[str]] | None = None
    technical_identifier_matched: dict[str, list[str]] | None = None
    technical_identifier_missing: dict[str, list[str]] | None = None
    technical_identifier_matched_count: int | None = None
    technical_identifier_total_count: int | None = None

    refusal_correct: bool | None = None
    false_accept: bool | None = None
    false_reject: bool | None = None
    actual_refusal: bool | None = None
    actual_refusal_type: str | None = None

    claim_support_rate: float | None = None
    claim_checks: list[dict[str, Any]] | None = None
    unsupported_claims: list[dict[str, Any]] | None = None
    forbidden_fact_hits: list[str] | None = None
    forbidden_fact_checker_false_positives: list[dict[str, Any]] | None = None

    latency: float | None = Field(default=None, description="HTTP wall latency in milliseconds")
    retrieval_latency_ms: float | None = None
    llm_latency_ms: float | None = None
    total_latency_ms: float | None = None
    first_token_latency_ms: float | None = None
    generation_mode: str | None = None
    fallback_event: bool | None = None
    fallback_success: bool | None = None
    fallback_reason: str | None = None
    evidence_sufficient: bool | None = None
    stop_reason: str | None = None
    rewrite_count: int | None = None
    tool_calls: list[dict[str, Any]] | None = None
    failure_tags: list[str] = Field(default_factory=list)
    answer: str | None = None
    error: str | None = None
