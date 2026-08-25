# RAG Trace 结构示例

Trace 用于回答“这一次请求具体经过了哪些步骤、用了哪些证据、为什么停止”。下面是脱敏、手工构造的结构示例，用于说明字段关系；它不是线上日志，也不包含真实用户问题、账号、设备地址或密钥。示例字段与当前 `RagTraceResponse` schema 兼容。

```json
{
  "request_id": "demo-trace-20260706-001",
  "created_at": "2026-07-06T10:30:00.000+08:00",
  "original_question": "通信失败时应该如何分层排查？",
  "device_model": "S7-1200",
  "question_type": "search_manual",
  "selected_tool": "search_manual",
  "retrieval_strategy": "dense+bm25+rrf+light_rerank",
  "query_rewrite_attempts": 0,
  "dense_topk": [
    {"rank": 1, "chunk_id": "manual_demo_0003", "page": 42, "score": 0.81}
  ],
  "bm25_topk": [
    {"rank": 1, "chunk_id": "manual_demo_0003", "page": 42, "score": 8.23}
  ],
  "rrf_topk": [
    {"rank": 1, "chunk_id": "manual_demo_0003", "page": 42, "score": 0.0328}
  ],
  "final_evidence": [
    {
      "rank": 1,
      "chunk_id": "manual_demo_0003",
      "doc_name": "S7-1200 Modbus Manual",
      "page": 42,
      "section_path": ["Diagnostics", "Status codes"],
      "score": 0.0328,
      "rerank_score": 0.91
    }
  ],
  "injected_context": [
    {
      "source_index": 1,
      "chunk_id": "manual_demo_0003",
      "doc_name": "S7-1200 Modbus Manual",
      "page": 42
    }
  ],
  "used_chunk_ids": ["manual_demo_0003"],
  "llm_model": "local",
  "attempted_models": [],
  "final_model": "",
  "input_tokens": null,
  "output_tokens": null,
  "total_tokens": null,
  "token_usage_available": false,
  "token_usage_missing_reason": "llm_disabled",
  "first_token_latency_ms": null,
  "retrieval_latency_ms": 318.4,
  "llm_latency_ms": 0.0,
  "total_latency_ms": 364.7,
  "generation_mode": "local_extractive",
  "fallback_reason": "llm_disabled",
  "refused": false,
  "evidence_sufficient": true,
  "warnings": [],
  "intent": {
    "intent": "cross_section_procedure",
    "confidence": 0.88,
    "matched_keywords": ["分层排查"],
    "reason": "检测到需要跨章节组织的流程或分层排查意图"
  },
  "candidate_plan": [
    "search_manual",
    "get_document_page"
  ],
  "plan": {
    "intent": "cross_section_procedure",
    "steps": [
      {
        "step_id": 1,
        "tool_name": "search_manual",
        "arguments": {
          "query": "通信失败时应该如何分层排查？",
          "model": "S7-1200",
          "version": "",
          "top_k": 5
        },
        "reason": "检索跨章节流程的官方手册证据",
        "expected_evidence": "manual_evidence"
      }
    ],
    "allow_generation": true,
    "need_evidence_gate": true,
    "max_rounds": 1,
    "max_tool_calls": 1
  },
  "planner_attempted": true,
  "planner_applied": true,
  "planner_fallback": false,
  "planner_fallback_reason": "",
  "planner_round": 1,
  "tool_calls": [
    {
      "tool_name": "search_manual",
      "tool": "search_manual",
      "arguments": {
        "query": "通信失败时应该如何分层排查？",
        "model": "S7-1200",
        "version": "",
        "top_k": 5
      },
      "started_at": "2026-07-06T10:30:00.010+08:00",
      "latency_ms": 318.4,
      "executed": true,
      "reused": false,
      "deduplicated": false,
      "planner_round": 1,
      "success": true,
      "result_count": 5,
      "error": ""
    },
    {
      "tool_name": "search_manual",
      "tool": "search_manual",
      "arguments": {
        "query": "通信失败时应该如何分层排查？",
        "model": "S7-1200",
        "version": "",
        "top_k": 5
      },
      "started_at": "2026-07-06T10:30:00.020+08:00",
      "latency_ms": 0.0,
      "executed": false,
      "reused": true,
      "deduplicated": true,
      "planner_round": 1,
      "success": true,
      "result_count": 5,
      "error": "",
      "round": 1
    }
  ],
  "rounds": 1,
  "budget": {
    "max_rounds": 2,
    "max_tool_calls": 4,
    "max_llm_calls": 2,
    "timeout_seconds": 60.0,
    "tool_timeout_seconds": 30.0,
    "max_rewrites": 1,
    "rounds_used": 1,
    "retrieval_rounds_used": 1,
    "planner_rounds_used": 1,
    "tool_calls_used": 1,
    "llm_calls_used": 0,
    "rewrites_used": 0,
    "remaining_rounds": 1,
    "remaining_tool_calls": 3,
    "remaining_rewrites": 1,
    "remaining_ms": 59638.8,
    "elapsed_ms": 361.2
  },
  "stop_reason": "evidence_sufficient",
  "evidence_assessments": [
    {
      "round": 1,
      "sufficient": true,
      "reason": "sufficient",
      "score": 0.91,
      "evidence_count": 5,
      "raw_missing_terms": [],
      "filtered_missing_terms": [],
      "generic_terms_ignored": [],
      "retry_eligible": false,
      "recommended_next_action": "generate",
      "retry_allowed": false,
      "stop_reason": "evidence_sufficient"
    }
  ],
  "rewrite_triggered": false,
  "rewritten_queries": [],
  "retrieval_rounds": [
    {
      "round": 1,
      "query": "通信失败时应该如何分层排查？",
      "rewritten_query": "",
      "evidence_count": 5,
      "evidence_score": 0.91,
      "evidence_passed": true,
      "stop_reason": "evidence_sufficient",
      "raw_missing_terms": [],
      "filtered_missing_terms": [],
      "generic_terms_ignored": []
    }
  ]
}
```

## 如何阅读

1. `selected_tool` 保留固定路由的兼容值；`candidate_plan` 和 `plan` 是严格候选计划。通过 `planner_attempted`、`planner_applied`、`planner_fallback` 和 `planner_fallback_reason` 判断本次计划是否真实执行；flag=false 时它们保持默认值。
2. `evidence_assessments` 是证据充分性判断（Evidence Gate）的记录，用来解释证据为何通过或为何需要停止/重试。
3. `rewrite_triggered`、`rewritten_queries` 和 `retrieval_rounds` 展示有界的问题改写（Query Rewrite）与检索轮次。
4. `budget` 记录统一的轮数、工具、改写、单工具 timeout 和 Agent 检索/工具阶段的剩余时间；`agent_timeout_seconds` 不代表覆盖 LLM、Citation Guard 或 HTTP 全生命周期的硬 deadline。`stop_reason` 给出最终停止原因。工具调用中的 `reused=true` / `deduplicated=true` 表示结果来自请求级缓存，没有重复执行 Registry handler；因此示例中的两条 `search_manual` Trace 只有第一条 `executed=true`。
5. `final_evidence`、`injected_context` 和 `used_chunk_ids` 用于追踪实际注入的证据来源。
6. `first_token_latency_ms` 当前应读作“响应可用耗时（当前不代表真实 TTFT）”；LLM 不是 Token Streaming，因此该字段不是严格的首 Token 延迟。

## 引用如何表示

当前 Trace schema 没有独立的 `citations` 字段。引用体现在 `ChatResponse.answer` 的来源标记，以及 Trace 中的 `final_evidence`、`injected_context`、`used_chunk_ids` 和 `warnings`。例如回答可以是：

```text
该状态表示通信伙伴未在监控时间内响应，应先核对对端运行状态、网络可达性和连接参数。[来源1：S7-1200 Modbus Manual，第42页]
```

这段文本也是结构示例；引用校验（Citation Guard）实际检查来源编号能否映射到本次证据。引用有效不自动等于每个事实都正确，仍需 claim-level 评测和人工复核。
