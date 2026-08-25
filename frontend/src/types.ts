export interface Chunk {
  chunk_id: string;
  doc_id: string;
  doc_name: string;
  text: string;
  page: number;
  section_path: string[];
  manufacturer: string;
  model: string;
  version: string;
  source_url: string;
  metadata: Record<string, unknown>;
}

export interface SearchHit {
  chunk: Chunk;
  score: number;
  dense_rank: number | null;
  bm25_rank: number | null;
  rerank_score: number | null;
}

export interface RuntimeStats {
  total_ms: number;
  context_turns_used: number;
  context_chars: number;
  retrieval_rounds: number;
  retrieval_operations: number;
  structured_queries: number;
  retrieval_latency_ms: number;
  external_llm_calls: number;
  external_token_usage: number | null;
  external_input_tokens: number | null;
  external_output_tokens: number | null;
  token_usage_available: boolean;
  token_usage_missing_reason: string;
  first_token_latency_ms: number | null;
  llm_latency_ms: number;
  llm_model: string;
  attempted_models: string[];
  final_model: string;
  generation_mode: string;
  generation_fallback_reason: string;
}

export interface RagTrace {
  request_id: string;
  created_at: string;
  original_question: string;
  device_model: string;
  question_type: string;
  selected_tool: string;
  retrieval_strategy: string;
  query_rewrite_attempts: number;
  dense_topk: Record<string, unknown>[];
  bm25_topk: Record<string, unknown>[];
  rrf_topk: Record<string, unknown>[];
  final_evidence: Record<string, unknown>[];
  injected_context: Record<string, unknown>[];
  used_chunk_ids: string[];
  llm_model: string;
  attempted_models: string[];
  final_model: string;
  input_tokens: number | null;
  output_tokens: number | null;
  total_tokens: number | null;
  token_usage_available: boolean;
  token_usage_missing_reason: string;
  first_token_latency_ms: number | null;
  retrieval_latency_ms: number;
  llm_latency_ms: number;
  total_latency_ms: number;
  generation_mode: string;
  fallback_reason: string;
  refused: boolean;
  evidence_sufficient: boolean;
  warnings: string[];
  intent: Record<string, unknown>;
  plan: Record<string, unknown> | Record<string, unknown>[];
  candidate_plan: string[];
  tool_calls: Record<string, unknown>[];
  rounds: number;
  budget: Record<string, unknown>;
  stop_reason: string;
  evidence_assessments: Record<string, unknown>[];
  rewrite_triggered: boolean;
  rewritten_queries: string[];
  retrieval_rounds: Record<string, unknown>[];
}

export interface ChatResponse {
  request_id: string;
  answer: string;
  evidence: SearchHit[];
  selected_tool: string;
  evidence_sufficient: boolean;
  warnings: string[];
  agent_trace: Record<string, unknown>[];
  knowledge_graph: Record<string, unknown>;
  verified_solution_used: boolean;
  runtime: RuntimeStats;
  rag_trace: RagTrace;
}

export interface ChatRequest {
  query: string;
  model: string;
  version: string;
  top_k: number;
  strategy: "hybrid" | "dense" | "bm25";
  session_id: string;
}

export type WorkflowEventName =
  | "request_started"
  | "analyzing"
  | "tool_selected"
  | "retrieving"
  | "reranking"
  | "rewriting"
  | "generating"
  | "citation_check"
  | "completed"
  | "error";

export interface WorkflowEvent {
  event: WorkflowEventName;
  request_id: string;
  timestamp: string;
  stage: WorkflowEventName;
  message: string;
  data: Record<string, unknown>;
}
