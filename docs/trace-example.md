# RAG Trace 结构示例

下面是脱敏、手工构造的结构示例，用于说明字段关系；它不是线上日志，也不包含真实用户问题、账号、设备地址或密钥。示例字段与当前 `RagTraceResponse` schema 兼容。

```json
{
  "request_id": "demo-trace-20260706-001",
  "created_at": "2026-07-06T10:30:00.000+08:00",
  "original_question": "16#80C8 应优先检查哪些通信条件？",
  "device_model": "S7-1200",
  "question_type": "lookup_alarm_code",
  "selected_tool": "lookup_alarm_code",
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
    "intent": "alarm_diagnosis",
    "confidence": 0.95,
    "matched_keywords": ["16#80C8"],
    "reason": "matched fault-code pattern"
  },
  "candidate_plan": [
    "lookup_fault_code",
    "search_manual"
  ],
  "plan": {
    "intent": "alarm_diagnosis",
    "steps": [
      {
        "step_id": 1,
        "action": "lookup_fault_code",
        "tool": "lookup_fault_code",
        "purpose": "查询结构化故障码记录"
      },
      {
        "step_id": 2,
        "action": "search_manual",
        "tool": "search_manual",
        "purpose": "检索手册证据"
      }
    ],
    "allow_generation": true,
    "need_evidence_gate": true,
    "max_rounds": 1,
    "max_tool_calls": 2,
    "routing_mode": "shadow",
    "applied": false
  },
  "tool_calls": [
    {
      "tool_name": "lookup_fault_code",
      "tool": "lookup_fault_code",
      "arguments": {"code": "80C8", "model": "S7-1200", "version": ""},
      "started_at": "2026-07-06T10:30:00.010+08:00",
      "latency_ms": 0.8,
      "executed": true,
      "success": true,
      "result_count": 1,
      "error": ""
    },
    {
      "tool_name": "search_manual",
      "tool": "search_manual",
      "arguments": {"query": "16#80C8 应优先检查哪些通信条件？", "model": "S7-1200", "version": "", "top_k": 5},
      "started_at": "2026-07-06T10:30:00.020+08:00",
      "latency_ms": 318.4,
      "executed": true,
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
    "max_rewrites": 1,
    "rounds_used": 1,
      "tool_calls_used": 2,
    "llm_calls_used": 0,
    "rewrites_used": 0,
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
      "query": "16#80C8 应优先检查哪些通信条件？",
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

1. `selected_tool` 是当前真实固定路由选择；`candidate_plan` 和 `plan` 是 shadow 结果，`plan.applied=false` 表示没有接管执行。
2. `evidence_assessments` 解释证据为何通过或为何需要停止/重试。
3. `rewrite_triggered`、`rewritten_queries` 和 `retrieval_rounds` 展示有界检索轮次。
4. `budget` 记录上限与已使用次数；`stop_reason` 给出最终停止原因。
5. `final_evidence`、`injected_context` 和 `used_chunk_ids` 用于追踪注入来源。

## 引用如何表示

当前 Trace schema 没有独立的 `citations` 字段。引用体现在 `ChatResponse.answer` 的来源标记，以及 Trace 中的 `final_evidence`、`injected_context`、`used_chunk_ids` 和 `warnings`。例如回答可以是：

```text
该状态表示通信伙伴未在监控时间内响应，应先核对对端运行状态、网络可达性和连接参数。[来源1：S7-1200 Modbus Manual，第42页]
```

这段文本也是结构示例；`Citation Guard` 实际校验的是来源编号能否映射到本次 evidence。引用有效不自动等于每个事实都正确，仍需 claim-level 评测和人工复核。
