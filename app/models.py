from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class Chunk(BaseModel):
    chunk_id: str
    doc_id: str
    doc_name: str
    text: str
    page: int = 0
    section_path: list[str] = Field(default_factory=list)
    manufacturer: str = "Siemens"
    model: str = "S7-1200"
    version: str = ""
    source_url: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)


class SearchHit(BaseModel):
    chunk: Chunk
    score: float
    dense_rank: int | None = None
    bm25_rank: int | None = None
    rerank_score: float | None = None


class SearchManualInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    query: str = Field(
        min_length=1,
        max_length=500,
        description="Manual question, keyword, fault symptom, or technical identifier.",
    )
    model: str = Field(
        default="S7-1200",
        min_length=1,
        max_length=100,
        description="Device model used to filter manual evidence.",
    )
    version: str = Field(
        default="",
        max_length=100,
        description="Optional firmware or manual version filter.",
    )
    top_k: int = Field(
        default=5,
        ge=1,
        le=20,
        description="Maximum number of evidence hits to return.",
    )


class LookupFaultCodeInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    code: str = Field(
        min_length=1,
        max_length=100,
        description="Exact equipment fault or alarm code, for example 16#80C8.",
    )
    model: str = Field(
        default="S7-1200",
        min_length=1,
        max_length=100,
        description="Device model associated with the fault code.",
    )
    version: str = Field(
        default="",
        max_length=100,
        description="Optional firmware or manual version filter.",
    )


class LookupParameterInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    name: str = Field(
        min_length=1,
        max_length=500,
        description="Parameter name, table field, or parameter-related query.",
    )
    model: str = Field(
        default="S7-1200",
        min_length=1,
        max_length=100,
        description="Device model associated with the parameter.",
    )
    version: str = Field(
        default="",
        max_length=100,
        description="Optional firmware or manual version filter.",
    )
    value: float | None = Field(
        default=None,
        description="Optional numeric value to compare with a known parameter range.",
    )


class GetDocumentPageInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    document_id: str | None = Field(
        default=None,
        min_length=1,
        max_length=500,
        description="Known document identifier. Provide this or document_name.",
    )
    document_name: str | None = Field(
        default=None,
        min_length=1,
        max_length=500,
        description="Known document filename. Provide this or document_id.",
    )
    page: int = Field(
        ge=1,
        le=100_000,
        description="One-based page number to retrieve from the allowed document corpus.",
    )

    @model_validator(mode="after")
    def require_document_reference(self) -> "GetDocumentPageInput":
        if not self.document_id and not self.document_name:
            raise ValueError("document_id or document_name is required")
        return self


class ToolCallTrace(BaseModel):
    """Serializable, sanitized execution facts for one registry call."""

    tool_name: str = ""
    tool: str = ""  # Backward-compatible name used by existing trace consumers.
    arguments: dict[str, Any] = Field(default_factory=dict)
    started_at: datetime
    latency_ms: float = 0.0
    executed: bool = True
    reused: bool = False
    deduplicated: bool = False
    planner_round: int | None = Field(default=None, ge=1)
    remaining_budget: dict[str, Any] = Field(default_factory=dict)
    success: bool = False
    result_count: int = Field(default=0, ge=0)
    error: str = ""

    @model_validator(mode="after")
    def synchronize_tool_names(self) -> "ToolCallTrace":
        name = self.tool_name or self.tool
        self.tool_name = name
        self.tool = name
        return self


class ToolResult(BaseModel):
    # ``tool`` and the text fields remain for compatibility with the existing
    # SQLiteToolbox and answer generator. New callers should use tool_name/data.
    tool_name: str = ""
    tool: str = ""
    success: bool = False
    data: Any = Field(default_factory=dict)
    result_count: int = Field(default=0, ge=0)
    content: str = ""
    evidence: list[SearchHit] = Field(default_factory=list)
    provenance: list[dict[str, Any]] = Field(default_factory=list)
    latency_ms: float = 0.0
    error: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)
    call_trace: ToolCallTrace | None = None

    @model_validator(mode="after")
    def synchronize_tool_names(self) -> "ToolResult":
        name = self.tool_name or self.tool
        self.tool_name = name
        self.tool = name
        return self


class SearchRequest(BaseModel):
    query: str = Field(
        min_length=1,
        max_length=500,
        description="要查询的问题",
        examples=["为什么设备手册写40001，而Modbus TCP报文地址常从0开始？"],
    )
    model: str = Field(default="S7-1200", description="设备型号", examples=["S7-1200"])
    version: str = Field(default="", description="固件或手册版本，不确定时留空")
    top_k: int = Field(default=5, ge=1, le=20, description="返回结果数量")
    strategy: str = Field(
        default="hybrid",
        pattern="^(hybrid|dense|bm25)$",
        description="检索方式：hybrid混合检索、dense向量检索、bm25关键词检索",
    )


class ChatRequest(SearchRequest):
    session_id: str = "demo"


class RuntimeStats(BaseModel):
    total_ms: float = Field(description="本次问答总耗时，单位为毫秒")
    context_turns_used: int = Field(description="本次追问使用的历史轮数")
    context_chars: int = Field(description="加入检索问题的历史字符数")
    retrieval_rounds: int = Field(description="混合检索执行轮数")
    retrieval_operations: int = Field(description="向量检索和BM25检索的执行次数之和")
    structured_queries: int = Field(description="故障码或参数数据库查询次数")
    retrieval_latency_ms: float = Field(description="本次向量、BM25、RRF和重排耗时，单位为毫秒")
    external_llm_calls: int = Field(description="外部大语言模型调用次数")
    external_token_usage: int | None = Field(description="外部模型token数；未接外部模型时为0，未返回用量时为空")
    external_input_tokens: int | None = Field(description="外部模型输入token数；未启用时为0")
    external_output_tokens: int | None = Field(description="外部模型输出token数；未启用时为0")
    token_usage_available: bool = Field(description="供应商是否返回了可解析的token用量")
    token_usage_missing_reason: str = Field(description="token用量缺失的明确原因；有用量时为空")
    first_token_latency_ms: float | None = Field(description="首个输出可用耗时；非流式时等于响应到达耗时")
    llm_latency_ms: float = Field(description="外部模型请求总耗时，单位为毫秒")
    llm_model: str = Field(description="本次配置或实际返回的外部模型名称")
    attempted_models: list[str] = Field(default_factory=list, description="本次按顺序尝试的外部模型")
    final_model: str = Field(default="", description="本次最终成功使用的模型；本地回答时为空")
    generation_mode: str = Field(description="回答方式：llm_grounded或local_extractive")
    generation_fallback_reason: str = Field(description="外部模型降级原因；没有降级时为空")


class RagTraceResponse(BaseModel):
    request_id: str
    session_id: str = ""
    created_at: str
    original_question: str
    device_model: str
    question_type: str
    selected_tool: str
    retrieval_strategy: str
    query_rewrite_attempts: int
    dense_topk: list[dict[str, Any]] = Field(default_factory=list)
    bm25_topk: list[dict[str, Any]] = Field(default_factory=list)
    rrf_topk: list[dict[str, Any]] = Field(default_factory=list)
    final_evidence: list[dict[str, Any]] = Field(default_factory=list)
    injected_context: list[dict[str, Any]] = Field(default_factory=list)
    used_chunk_ids: list[str] = Field(default_factory=list)
    llm_model: str
    attempted_models: list[str] = Field(default_factory=list)
    final_model: str = ""
    input_tokens: int | None
    output_tokens: int | None
    total_tokens: int | None
    token_usage_available: bool
    token_usage_missing_reason: str
    first_token_latency_ms: float | None
    retrieval_latency_ms: float = 0.0
    llm_latency_ms: float = 0.0
    total_latency_ms: float
    generation_mode: str
    fallback_reason: str
    refused: bool
    evidence_sufficient: bool
    warnings: list[str] = Field(default_factory=list)
    intent: dict[str, Any] = Field(default_factory=dict)
    plan: dict[str, Any] | list[dict[str, Any]] = Field(default_factory=dict)
    candidate_plan: list[str] = Field(default_factory=list)
    tool_calls: list[dict[str, Any]] = Field(default_factory=list)
    rounds: int = 0
    budget: dict[str, Any] = Field(default_factory=dict)
    stop_reason: str = ""
    evidence_assessments: list[dict[str, Any]] = Field(default_factory=list)
    rewrite_triggered: bool = False
    rewritten_queries: list[str] = Field(default_factory=list)
    retrieval_rounds: list[dict[str, Any]] = Field(default_factory=list)
    planner_attempted: bool = False
    planner_applied: bool = False
    planner_fallback: bool = False
    planner_fallback_reason: str = ""
    planner_round: int = 0


class ChatResponse(BaseModel):
    request_id: str
    answer: str
    evidence: list[SearchHit]
    selected_tool: str
    evidence_sufficient: bool
    warnings: list[str] = Field(default_factory=list)
    agent_trace: list[dict[str, Any]] = Field(default_factory=list)
    knowledge_graph: dict[str, Any] = Field(default_factory=dict)
    verified_solution_used: bool = False
    runtime: RuntimeStats
    rag_trace: RagTraceResponse


WorkflowEventName = Literal[
    "request_started",
    "analyzing",
    "tool_selected",
    "retrieving",
    "reranking",
    "rewriting",
    "generating",
    "citation_check",
    "completed",
    "error",
]


class WorkflowEvent(BaseModel):
    """Stable wire format for the local React workflow event stream."""

    event: WorkflowEventName
    request_id: str
    timestamp: datetime
    stage: WorkflowEventName
    message: str
    data: dict[str, Any] = Field(default_factory=dict)


class VerifiedSolutionRequest(BaseModel):
    model: str
    version: str = ""
    problem: str
    solution: str
    source_chunk_ids: list[str]
    confirmed_by: str = "user"


class FeedbackRequest(BaseModel):
    session_id: str = "demo"
    question: str = Field(min_length=1, max_length=1000)
    answer: str = Field(min_length=1)
    helpful: bool
    reason: str = Field(default="", max_length=1000)
    selected_tool: str = ""
    source_chunk_ids: list[str] = Field(default_factory=list)


class SearchResponse(BaseModel):
    query: str = Field(description="原始问题")
    strategy: str = Field(description="本次使用的检索方式")
    hits: list[SearchHit] = Field(description="按相关度排序的手册证据")


class IndexStatusResponse(BaseModel):
    embedding_backend: str = Field(description="向量计算后端")
    embedding_model: str = Field(description="向量模型")
    collection: str = Field(description="Qdrant集合名称")
    qdrant_mode: str = Field(description="Qdrant运行方式：local或server")
    query_expansion_enabled: bool = Field(description="是否启用中英文领域词扩展")
    bm25_enabled: bool = Field(description="是否启用 BM25 稀疏检索")
    max_concurrent_queries: int = Field(description="检索问答最大并发数")
    request_timeout_seconds: float = Field(description="检索问答超时时间，单位为秒")
    rate_limit_per_minute: int = Field(description="单个客户端每分钟请求上限")
    indexed_chunks: int = Field(description="Qdrant中的切片数量")
    table_row_chunks: int = Field(description="表格行切片数量")
    structured_tables: int = Field(description="解析出的表格数量")
    raw_files: int = Field(description="原始资料目录中的文件数量")
    active_sources: int = Field(description="当前入库的官方资料数量")
    current_sources: int = Field(description="标记为当前版本的资料数量")
    latest_checked_at: str = Field(description="资料最近核对日期")
    llm_enabled: bool = Field(description="是否配置外部大语言模型")
    llm_model: str = Field(description="配置的外部大语言模型名称")
    llm_model_fallbacks: list[str] = Field(default_factory=list, description="按顺序备用的外部模型")
    database_backend: str = Field(default="sqlite", description="运行型数据后端")
    database_status: str = Field(default="ok", description="运行型数据库依赖状态")
    database_error_type: str = Field(default="", description="数据库不可用时的异常类型，不含凭据或连接串")


class HealthResponse(IndexStatusResponse):
    status: str = Field(description="服务状态", examples=["ok"])
    metrics_collector_initialized: bool = Field(
        default=True, description="进程内运行指标收集器是否已初始化"
    )
    active_requests: int = Field(
        default=0, ge=0, description="当前正在处理且纳入运行指标的 HTTP 请求数"
    )


class LivenessResponse(BaseModel):
    status: str = Field(description="进程存活状态", examples=["ok"])


class IngestResponse(BaseModel):
    documents: int = Field(description="处理的文档数量")
    chunks: int = Field(description="生成的切片数量")
    mode: str = Field(description="切分方式")
    embedding_backend: str = Field(description="向量计算后端")
    collection: str = Field(description="Qdrant集合名称")


class AlarmResponse(BaseModel):
    code: str = Field(description="故障码", examples=["16#80C8"])
    title: str = Field(description="故障名称")
    meaning: str = Field(description="故障含义")
    causes: list[str] = Field(description="常见原因")
    checks: list[str] = Field(description="建议检查项")
    model: str = Field(description="适用型号")
    source: str = Field(description="资料来源")


class SavedSolutionResponse(BaseModel):
    saved: bool = Field(description="是否保存成功")
    solution_id: int = Field(description="方案编号")
    verified: bool = Field(description="是否经过人工确认")


class SavedFeedbackResponse(BaseModel):
    saved: bool = Field(description="是否保存成功")
    feedback_id: int = Field(description="反馈编号")


class BusinessMetricsResponse(BaseModel):
    feedback_total: int = Field(description="反馈总数")
    helpful: int = Field(description="有帮助数量")
    unhelpful: int = Field(description="无帮助数量")
    helpful_rate: float | None = Field(description="有帮助比例；没有反馈时为空")
    verified_solutions: int = Field(description="人工确认方案数量")
    verified_solution_reuse: int = Field(description="已确认方案使用次数")


class MetricsWindowInfo(BaseModel):
    latency_sample_limit: int = Field(
        ge=1, description="每类延迟最多保留的最近样本数"
    )
    percentile_scope: Literal["most_recent_samples"] = Field(
        description="P50/P95/P99 的样本范围"
    )
    percentile_method: Literal["nearest_rank"] = Field(
        description="窗口分位数算法"
    )
    percentiles_are_lifetime: Literal[False] = Field(
        description="明确分位数不是全生命周期统计"
    )


class RuntimeMetricsResponse(BaseModel):
    window: MetricsWindowInfo
    request: dict[str, Any]
    latency: dict[str, dict[str, int | float | None]]
    rag: dict[str, Any]
    llm: dict[str, int | float | None]
    tools: dict[str, Any]


class GraphEntity(BaseModel):
    id: str
    type: str
    label: str


class GraphRelation(BaseModel):
    source: str
    relation: str
    target: str
    provenance: str


class GraphContextResponse(BaseModel):
    matched_entities: list[GraphEntity] = Field(description="问题中匹配到的实体")
    relations: list[GraphRelation] = Field(description="相关关系")
    expansion_terms: list[str] = Field(description="可用于补充检索的词")


class ClearedSessionResponse(BaseModel):
    cleared: bool = Field(description="是否完成清理")
    removed_turns: int = Field(description="删除的会话轮数")
