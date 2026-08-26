# AutoOps RAG Trace / Runtime Gap Analysis

> **Historical / stale / 历史版本分析。** 当前 Trace schema 和示例见 `docs/trace-example.md`。

> 目的：检查当前一次 `/api/chat` 问答请求的返回结构、Trace 落盘结构及 `static/index.html` 展示情况。本报告只做静态代码与现有 `rag_traces.jsonl` 样本核对，不修改业务代码。

## 1. 检查范围

| 层次 | 文件 / 数据 | 作用 |
|---|---|---|
| API 响应模型 | `app/models.py` | 定义 `ChatResponse`、`RuntimeStats`、`RagTraceResponse` |
| 请求组装 | `app/service.py` | 从 LangGraph state 生成 runtime 与 rag trace |
| Agent 节点 | `app/agent/graph.py` | 生成 `agent_trace`、`retrieval_trace`、`generation_usage` |
| 检索候选 | `app/retrieval/hybrid.py` | 生成 Dense、BM25、RRF 和最终 evidence 的候选明细 |
| Trace 持久化 | `app/tracing.py` | 脱敏后追加写入 `reports/rag_traces.jsonl` |
| 页面展示 | `static/index.html` | 展示 runtime、agent trace、rag trace、知识关系和 evidence |
| 实际样本 | `reports/rag_traces.jsonl` 最后一条 | 验证字段确实落盘及候选对象结构 |

## 2. 当前一次 `/api/chat` 的返回树

```text
ChatResponse
├─ request_id
├─ answer
├─ evidence[]
│  ├─ chunk
│  │  ├─ chunk_id / doc_id / doc_name / text / page / section_path
│  │  ├─ manufacturer / model / version / source_url
│  │  └─ metadata
│  ├─ score
│  ├─ dense_rank
│  ├─ bm25_rank
│  └─ rerank_score
├─ selected_tool
├─ evidence_sufficient
├─ warnings[]
├─ agent_trace[]
├─ knowledge_graph
├─ verified_solution_used
├─ runtime
└─ rag_trace
```

除了 `/api/chat` 内嵌的 `rag_trace`，当前还提供：

- `GET /api/traces/{request_id}`：按请求编号读取单条 Trace。
- `GET /api/traces/recent?limit=20`：读取最近 Trace。
- Trace 写盘前经过 `sanitize_trace()`，会删除 API key、Authorization、secret、password 等敏感键，并替换 Bearer、`sk-` 等凭据形文本。

## 3. Runtime 已有字段

`runtime` 当前共有 20 个字段。

| 字段 | 当前含义 / 来源 | 页面是否展示 |
|---|---|---:|
| `total_ms` | service 接收请求到保存会话、校验引用并组装响应的总耗时 | 是 |
| `context_turns_used` | 本次追问使用的历史轮数 | 否 |
| `context_chars` | 拼入检索问题的历史字符数 | 否 |
| `retrieval_rounds` | `agent_trace` 中 `hybrid_retrieval` 节点数量 | 是 |
| `retrieval_operations` | 当前按 `retrieval_rounds * 2` 推算 Dense + BM25 操作次数 | 否 |
| `structured_queries` | 选择工具不是 `search_manual` 时记 1 | 否 |
| `retrieval_latency_ms` | 所有检索轮累计耗时 | 否 |
| `external_llm_calls` | 外部模型实际调用次数 | 是 |
| `external_token_usage` | 外部模型总 token | 是 |
| `external_input_tokens` | 外部模型输入 token | 是 |
| `external_output_tokens` | 外部模型输出 token | 是 |
| `token_usage_available` | 供应商 usage 是否可解析 | 间接展示 |
| `token_usage_missing_reason` | token 缺失原因 | token 缺失时展示 |
| `first_token_latency_ms` | 首个输出可用耗时；非流式时等于完整响应首次可用耗时 | 否（runtime 区不展示） |
| `llm_latency_ms` | 外部模型调用总耗时 | 否 |
| `llm_model` | 最终模型、生成结果模型或配置主模型三者之一 | 否 |
| `attempted_models` | 本次按顺序尝试的模型 | 是 |
| `final_model` | 最终成功模型；本地回答为空 | 是 |
| `generation_mode` | `llm_grounded` 或 `local_extractive` | 是 |
| `generation_fallback_reason` | 外部模型降级原因 | 非空时展示 |

### Runtime 现状判断

- 基本的耗时、模型、调用次数和 token 已齐全。
- 页面 runtime 摘要只展示总耗时，未展示已返回的 `retrieval_latency_ms`、`llm_latency_ms` 和 `first_token_latency_ms`。
- `retrieval_operations` 是推算值，不是底层实际调用计数；若未来增加其他检索器，它会失真。
- `llm_model` 语义混合“实际模型”和“配置模型”。实际使用模型应以 `final_model` 为准；在本地降级样本中，`llm_model=qwen-plus`、`final_model=""` 是合法但容易误读的组合。

## 4. RAG Trace 已有字段

`rag_trace` 当前共有 31 个顶层字段。

### 4.1 请求与路由

| 字段 | 当前状态 |
|---|---|
| `request_id` | 已有，可关联 API 响应、文件 Trace 与查询接口 |
| `created_at` | 已有；实际在处理结束、组装 Trace 时写入 |
| `original_question` | 已有 |
| `device_model` | 已有 |
| `question_type` | 已有，但当前直接等于 `selected_tool`，不是独立问题分类 |
| `selected_tool` | 已有 |
| `retrieval_strategy` | 已有，但当前固定写成 `dense+bm25+rrf+light_rerank` |
| `query_rewrite_attempts` | 已有，按 `query_rewrite` 节点计数 |

### 4.2 检索链路

| 字段 | 当前状态 |
|---|---|
| `dense_topk` | 已有，实际最多记录 30 条 |
| `bm25_topk` | 已有，实际最多记录 30 条 |
| `rrf_topk` | 已有，实际最多记录 20 条 |
| `final_evidence` | 已有，通常为最终 Top5 |
| `injected_context` | 已有，保存传给生成器的 chunk 正文和来源信息 |
| `used_chunk_ids` | 已有，但实际值是全部最终 evidence chunk IDs，不等于答案实际引用 IDs |
| `retrieval_latency_ms` | 已有，所有检索轮累计耗时 |

Dense/BM25/RRF/final candidate 的每条对象已有：

```text
rank, chunk_id, doc_name, page, section_path,
score, dense_rank, bm25_rank, rerank_score
```

`injected_context` 的每条对象已有：

```text
source_number, chunk_id, doc_name, page, section_path, text
```

### 4.3 模型、token 与耗时

| 字段 | 当前状态 |
|---|---|
| `llm_model` | 已有；可能是最终模型，也可能是配置主模型 |
| `attempted_models` | 已有 |
| `final_model` | 已有 |
| `input_tokens` | 已有，可为空 |
| `output_tokens` | 已有，可为空 |
| `total_tokens` | 已有，可为空 |
| `token_usage_available` | 已有 |
| `token_usage_missing_reason` | 已有 |
| `first_token_latency_ms` | 已有，可为空 |
| `llm_latency_ms` | 已有 |
| `total_latency_ms` | 已有 |
| `generation_mode` | 已有 |
| `fallback_reason` | 已有 |

### 4.4 结果与安全

| 字段 | 当前状态 |
|---|---|
| `refused` | 已有，但当前把“命中 scope/safety gate”和“evidence_sufficient=false”都记为 true |
| `evidence_sufficient` | 已有 |
| `warnings` | 已有，来自引用校验 |

## 5. Agent Trace 已有节点与字段

`agent_trace` 是节点事件数组，不使用固定 Pydantic 子模型。当前可能出现：

| Node | 已有字段 |
|---|---|
| `conversation_context` | `turns_used`, `history_chars` |
| `route` | `tool`, `reason` |
| `knowledge_graph` | `matched_entities`, `expanded_terms`, `relations` |
| `scope_and_safety_gate` | `accepted`, `category`, `reason` |
| `safe_refusal` | `category`, `reason` |
| `verified_memory` | `solution_id`, `similarity`, `decision`，或只有 `decision` |
| `hybrid_retrieval` | `strategy`, `query_expanded`, `hits`, `distinct_documents`, `top_score`, `query_expansion_terms` |
| `evidence_gate` | `sufficient`, `identifiers_supported`, `retry_count` |
| `query_rewrite` | `attempt` |
| `answer_with_citations` | `evidence_count`, `mode`, `fallback_reason`, `attempted_models`, `final_model` |

这些事件足以解释主要流程，但缺少统一的事件时间戳、节点耗时、节点输入/输出摘要和异常字段。

## 6. `static/index.html` 当前实际展示

### 6.1 Runtime 摘要区

当前显示：

- 总耗时 `total_ms`
- 检索轮数 `retrieval_rounds`
- 实际模型 `final_model`
- 尝试模型 `attempted_models`
- 外部调用次数 `external_llm_calls`
- token 总数、输入、输出；或 token 缺失原因
- 生成方式 `generation_mode`
- 降级原因 `generation_fallback_reason`（非空时）

当前不显示：

- 历史轮数、历史字符数
- 检索操作数、结构化查询数
- 检索耗时、LLM 耗时、首 token 耗时
- `llm_model` 配置/候选模型字段

### 6.2 “执行过程” Agent Trace 区

- 页面通过通用 `showTrace()` 展示每个节点的全部键值。
- route、knowledge graph、verified memory、hybrid retrieval、evidence gate、rewrite、generation 等主要节点有中文标签。
- `scope_and_safety_gate`、`safe_refusal` 没有中文 node label。
- `query_expansion_terms`、`identifiers_supported`、`accepted`、`category`、`attempted_models`、`final_model`、`fallback_reason` 等没有中文 key label，会直接显示英文键名。

### 6.3 “查看 RAG Trace”区

当前显示：

1. 请求：`request_id`、`original_question`、`selected_tool`。
2. 检索链路：`retrieval_strategy`、改写次数，以及 Dense/BM25/RRF/final 数量。
3. 生成：`final_model`、`attempted_models`、`generation_mode`、token、`first_token_latency_ms`、`total_latency_ms`、`fallback_reason`。
4. 使用切片：`used_chunk_ids`。
5. 注入上下文：每条的 `chunk_id`、`doc_name`、`page`、完整 `text`。

当前不显示但 API 已返回：

- `created_at`
- `device_model`
- `question_type`
- `llm_model`
- Dense/BM25/RRF 每条候选的 ID、rank 和 score；目前只显示数量
- `final_evidence` 每条的 rank/score
- `injected_context.section_path`
- `retrieval_latency_ms`
- `llm_latency_ms`
- `refused`
- `evidence_sufficient`
- `warnings`

### 6.4 其他页面区域

- 回答正文：展示 `answer`。
- 参考依据：展示 evidence 的文档名、页码、最终相关度、chunk ID、表格 ID 和最多 700 字原文。
- 知识关系：展示 `knowledge_graph.matched_entities` 和 `relations`。
- 页面未单独展示顶层 `request_id`、`selected_tool`、`evidence_sufficient`、`warnings`、`verified_solution_used`；其中前两项可在 RAG/Agent Trace 间接看到。

## 7. 返回结构中的缺失字段

以下是当前 runtime/rag trace **没有返回**、但对审计、性能诊断或 bad case 分析有价值的字段。这里只列差距，不在本轮实现。

### 7.1 请求上下文缺失

| 建议字段 | 价值 |
|---|---|
| `session_id` 或脱敏后的 `session_hash` | 串联同一多轮会话；直接保存原值可能有隐私风险，建议 hash |
| `firmware_version` / 请求 `version` | 判断版本过滤和跨版本拒答是否正确 |
| `requested_top_k` | 解释 final evidence 数量与评测口径 |
| `request_strategy` | 区分请求的 dense/bm25/hybrid；当前 Trace 只写固定策略 |
| `resolved_question` | 查看加入会话上下文后真正送去路由/检索的问题 |
| `rewritten_queries[]` | 记录每轮 rewrite 后的实际检索 query；当前只有次数 |
| `request_started_at` / `completed_at` | 当前只有处理结束附近生成的 `created_at`，无法准确表示起止时间 |

### 7.2 检索诊断缺失

| 建议字段 | 价值 |
|---|---|
| `dense_latency_ms`, `bm25_latency_ms`, `rrf_latency_ms`, `rerank_latency_ms` | 区分各检索阶段性能瓶颈 |
| `retrieval_rounds[]` | 把每轮 query、候选、耗时和 gate 决策关联起来；当前多轮候选会被最后一轮覆盖 |
| `model_filter`, `version_filter` | 核对 metadata filter 是否实际生效 |
| `rrf_score` | 当前融合分数复用通用 `score`，语义不直观 |
| `candidate_pool_size` / `rerank_input_ids` | 判断 gold 是 retrieval miss 还是 ranking late |
| `evidence_gate_reason` / `thresholds` | 目前只有 bool 和 agent trace 的少量字段，缺少阈值与未通过原因 |
| `actual_cited_chunk_ids` | 区分“注入证据”与“回答真正引用证据”；当前 `used_chunk_ids` 是全部 evidence |
| `citation_validation` | 建议包含合法引用数、无效引用、未引用关键句；当前只有 `warnings` 文本 |

### 7.3 生成诊断缺失

| 建议字段 | 价值 |
|---|---|
| `model_attempts[]` | 每个模型的开始时间、耗时、结果、错误类别、token；当前只有模型名列表和最终原因 |
| `provider` | 区分百炼或其他 OpenAI-compatible provider，不记录 API key/base URL |
| `streaming` | 解释 `first_token_latency_ms` 的语义 |
| `finish_reason` | 区分正常结束、长度截断、内容过滤 |
| `max_output_tokens`, `temperature` | 复现实验和解释 token/稳定性；避免保存敏感配置 |
| `prompt_version` / `prompt_hash` | 关联 Prompt 版本，不保存完整 Prompt |
| `injected_context_chars` / `injected_context_tokens` | 解释输入 token 和延迟，不同于 runtime 的历史上下文字符数 |
| `answer_hash` 或脱敏后的 `answer_snapshot` | Trace 当前不保存最终答案，独立查询 Trace 时难以确认对应输出 |
| `fallback_chain_exhausted` | 明确区分单模型降级和所有模型均失败 |

### 7.4 安全与结果语义缺失

| 建议字段 | 价值 |
|---|---|
| `outcome` | 建议枚举 `answered`、`insufficient_evidence`、`policy_refusal`、`error` |
| `refusal_kind` | 区分 unsafe、scope、version、证据不足；当前 `refused` 混合多种情况 |
| `refusal_reason` | 支持拒答 bad case 分析 |
| `http_status` / `error_type` | Trace 只在成功组装响应时落盘，缺少异常请求观测 |
| `verified_solution_id` | 顶层只有 `verified_solution_used`，Trace 中仅 agent event 可能包含 ID |
| `cache_hit` / `cache_key_hash` | 判断 embedding、检索或生成缓存对耗时的影响；不保存原始敏感 key |

### 7.5 Runtime 性能缺失

| 建议字段 | 价值 |
|---|---|
| `routing_latency_ms` | 路由、知识关系和 policy gate 耗时 |
| `memory_latency_ms` | 多轮记忆读取、验证方案查询及会话保存耗时 |
| `citation_validation_latency_ms` | 区分回答后校验成本 |
| `trace_persistence_latency_ms` | 区分 JSONL 写入成本 |
| `non_retrieval_non_llm_latency_ms` | 解释 `total_ms - retrieval - llm` 的剩余耗时 |
| `external_cost` 或估算成本 | 额度/费用观察；必须标明是供应商返回还是本地估算 |

## 8. 已有但语义需要澄清的字段

这些不是“字段缺失”，但当前命名可能造成误读：

1. `question_type`：当前就是 `selected_tool`，不是 alarm/table/version/unsafe 等独立分类。
2. `used_chunk_ids`：当前是所有 final evidence IDs，不保证答案实际引用。
3. `refused`：当前 `refusal_reason` 非空或 `evidence_sufficient=false` 都会变成 true，混合 policy refusal 与资料不足。
4. `llm_model`：可能表示最终模型，也可能只表示配置模型；`final_model` 才是实际成功模型。
5. `created_at`：在请求处理结束后组装 Trace 时生成，更接近“Trace 创建时间”，不是请求开始时间。
6. `first_token_latency_ms`：非流式时是完整响应首次可用时间，页面仍统一写“首字耗时”。
7. `retrieval_strategy`：当前在 service 中固定写入，未从实际请求或 retriever 动态生成。
8. `retrieval_operations`：按轮数乘 2 推算，并非真实 instrumentation。

## 9. Gap 优先级建议

### P0：直接影响 bad case 判断

1. `resolved_question`、每轮 `rewritten_query`。
2. `actual_cited_chunk_ids`，与 injected/final evidence 分开。
3. Dense/BM25/RRF/rerank 分阶段耗时与候选 rank 流转。
4. `refusal_kind` 与明确 `outcome`。
5. `model_attempts[]` 的逐模型结果和耗时。
6. `citation_validation` 结构化结果。

### P1：提升复现和性能分析

1. 请求 version、top_k、strategy 和脱敏 session 标识。
2. Prompt 版本/hash、生成参数、finish reason、streaming 标识。
3. routing、memory、citation validation、trace persistence 耗时。
4. injected context 字符数/token 数。

### P2：页面展示补齐

1. 页面展示 retrieval 与 LLM 耗时拆分。
2. 展开 Dense/BM25/RRF candidate，而不是只显示数量。
3. 展示 `evidence_sufficient`、warnings、refusal kind。
4. 给安全拒答节点和未翻译字段补中文标签。

## 10. 结论

当前 Trace 已覆盖请求编号、原问题、工具路由、三路检索候选、最终 evidence、注入上下文、模型切换、token、耗时、降级、证据充分性和引用警告，基础链路不是空壳。主要缺口不在“有没有 Trace”，而在三个方面：

1. **无法完整复现实际查询**：缺少 resolved/rewrite 后的查询文本和请求 version/top_k。
2. **无法精确区分召回与排序问题**：候选已有，但缺少逐轮、逐阶段耗时和更明确的 rank 流转/候选池信息。
3. **注入、引用和拒答语义混在一起**：`used_chunk_ids` 不等于真实引用，`refused` 不区分 policy 与 evidence insufficient。

页面已经能展示模型、token、总耗时、生成方式和注入证据，但大量后端已有字段仍未显示，特别是检索/LLM 分段耗时、候选明细、证据充分性和 warnings。
