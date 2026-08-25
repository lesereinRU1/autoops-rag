# AutoOps RAG 架构说明

## 架构定位

AutoOps RAG 是基于 LangGraph 的轻量级、受控 Agentic RAG 工业知识库系统。真实问答始终保留固定状态机作为默认路径和 fallback；`ENABLE_AGENTIC_ROUTING=true` 时，现有确定性有界问题规划器（Bounded Query Planner）只对适用 intent 执行严格白名单计划。Planner 不调用 LLM，实验性迭代检索仍须独立开启。

```text
用户请求 -> FastAPI -> Service -> LangGraph -> 工具注册中心（Tool Registry）-> RAG/工具
        -> LLM 或本地证据摘要 -> 引用校验（Citation Guard）-> 返回答案、证据和 Trace
```

实现状态必须分开理解：

- **已真实实现**：固定 LangGraph 主流程、Tool Registry 与四个工具、feature-flagged 受控 Planner、本地 MCP stdio Server、React Demo、工作流级 SSE、SQLite/PostgreSQL Repository、Trace 和运行指标。
- **默认关闭 / experimental**：Planner/Router 在 flag=false 时只记录候选；flag=true 时仍受 Registry 白名单、统一 budget、timeout、去重和 fallback 限制。Iterative Retrieval 默认关闭。
- **尚未实现**：LLM Planner、开放式工具循环、Multi-Agent、远程 HTTP MCP、LLM Token Streaming，以及生产级多实例监控与运维能力。

```mermaid
flowchart TD
    Q["API / Legacy Web"] --> API["FastAPI JSON API"]
    WEB["React Demo"] --> SSE["Workflow SSE"]
    MCP["MCP Client"] --> MCPS["Local MCP stdio Server"]
    API --> SVC["Service Layer"]
    SSE --> SVC
    MCPS --> SVC
    SVC --> GRAPH["LangGraph Workflow"]

    GRAPH --> ANALYZE["analyze_request: policy gate + rule-first routing"]
    ANALYZE -->|"safety_risk / out_of_scope"| REFUSE["generate_refusal"]
    ANALYZE -->|"flag off / stable rule"| FIXED["execute_tool: fixed route"]
    ANALYZE -. "flag on + eligible" .-> PLAN["execute_agent_plan"]
    PLAN -->|"applied / fallback"| FIXED
    FIXED --> REGISTRY["Tool Registry"]
    REGISTRY --> SQLITE["SQLite Tools"]
    REGISTRY --> PAGE["Document Page Service"]
    REGISTRY --> SEARCH["retrieve: search_manual"]
    SEARCH --> DENSE["BGE + Qdrant"]
    SEARCH --> SPARSE["BM25"]
    DENSE --> FUSION["RRF + Light Rerank"]
    SPARSE --> FUSION
    FUSION --> GATE["Evidence Gate inside retrieve"]

    GATE -->|"sufficient"| GEN["Grounded Generation"]
    GATE -. "insufficient + enabled + budget available" .-> REWRITE["Query Rewrite"]
    REWRITE -.-> SEARCH
    GATE -->|"insufficient / budget stop"| LOCAL["Local Evidence Summary / Refusal"]

    GEN --> CITE["Citation Guard"]
    LOCAL --> CITE
    CITE --> OUT["Answer + Evidence + Runtime"]

    GRAPH --> TRACE["RAG Trace"]
    ANALYZE --> TRACE
    REGISTRY --> TRACE
    SEARCH --> TRACE
    GATE --> TRACE
    CITE --> TRACE
    SVC --> REPO["Runtime Repository"]
    REPO --> DB["SQLite / PostgreSQL"]
    SVC --> METRICS["MetricsCollector"]
```

## 核心模块职责

| 模块 | 它是干什么的 |
|---|---|
| FastAPI API 层 | 校验请求、生成 `request_id`，并提供 JSON、SSE、健康检查和指标接口。 |
| `AutoOpsService` | 连接 API、会话、LangGraph、Repository 与 Trace，并整理最终响应。 |
| LangGraph 工作流 | 用固定节点和条件边控制安全短路、工具、检索、改写、生成与引用校验。 |
| 工具注册中心（Tool Registry） | 登记四个正式工具，在统一入口完成参数校验、预算、超时、Trace 和指标结算。 |
| `HybridRetriever` | 执行 Dense、BM25、RRF 和 Rerank，返回带来源信息的手册证据。 |
| `AnswerGenerator` 与 Citation Guard | 基于证据生成回答，并检查引用编号是否属于本次证据。 |
| 数据访问层（Repository） | 用统一接口读写会话、反馈、人工确认方案、Trace metadata 和评测记录。 |
| 运行指标采集器（MetricsCollector） | 在当前进程内聚合请求、RAG、LLM、工具和延迟指标。 |
| MCP stdio Server | 把同一组 Tool Registry 能力暴露给本地 MCP Client，不复制业务逻辑。 |
| React Demo | 通过工作流级 SSE 展示执行阶段，最后显示完整答案、证据和 Trace。 |

## API 层

`app/api.py` 提供 FastAPI 接口，负责输入校验、请求编号、错误映射和响应模型：

- `POST /api/search`：只执行检索，不调用生成链路；
- `POST /api/chat`：执行完整问答状态机；
- `POST /api/chat/stream`：通过 SSE 推送工作流阶段事件，最终一次性返回完整回答；
- `GET /api/traces/{request_id}`：查询单次 Trace；
- `GET /api/traces/recent`：查询最近 Trace；
- `GET /metrics`、`GET /api/metrics/runtime`：分别返回 Prometheus 文本和运行指标 JSON；
- `/health/live`、`/health/ready`：进程和依赖就绪检查；
- 索引、反馈、人工确认方案和故障码等辅助接口。

API 层不决定 Agent 路由，核心编排交给 Service 和 LangGraph。

当前同时保留两套 Web 演示：FastAPI 继续托管原生 HTML/CSS/JavaScript 页面；`frontend/` 提供 React + TypeScript + Vite Demo，通过 `POST /api/chat/stream` 接收工作流级 SSE。当前 LLM 仍是非流式调用，SSE 只展示节点进度，最终答案在 `completed` 事件中一次性返回，不是 Token Streaming。

## Service 层

`app/service.py` 连接 API、会话上下文、MemoryStore、`ToolRegistry`、Retriever、`DocumentPageService`、Generator、Repository 和 TraceStore。它负责：

1. 解析短追问所需的有限会话上下文；
2. 调用 LangGraph 并汇总最终 state；
3. 构造 `ChatResponse`、运行统计和 `RagTraceResponse`；
4. 持久化脱敏 Trace，并把运行型 metadata 交给 Repository；
5. 暴露索引状态、反馈、人工确认方案和运行指标所需信息。

## LangGraph 工作流

`app/agent/graph.py` 将流程拆成显式节点：

```text
analyze_request
├─ [安全风险 / 超出范围] → generate_refusal → END
├─ [固定规则 / flag=false] → execute_tool
└─ [flag=true 且适用] → execute_agent_plan → execute_tool
→ retrieve
→ [证据不足且允许重试] rewrite → retrieve（有界）
→ [证据充分或停止重试] generate_answer
→ citation_guard
→ END
```

安全风险或超出资料范围的请求由 `analyze_request` 在检索和模型调用前短路。明确故障码、明确参数和普通手册查询继续走稳定规则；表格定位、跨章节流程和版本核对在 flag=true 时可进入 `execute_agent_plan`。计划中的 `search_manual` 若已执行，`retrieve` 会复用相同签名结果，不重复 Dense/BM25/RRF/Rerank；任何 Planner 异常都回到固定路径。

## Hybrid Retrieval

`app/retrieval/` 实现：

- BGE/FastEmbed 生成向量，Qdrant 执行 Dense Retrieval；
- BM25 捕获故障码、参数名、端口号等精确词；
- RRF 合并 Dense 与 Sparse 排名；
- 轻量 Rerank 生成最终 TopK；
- 每个 `SearchHit` 保留 `chunk_id`、文档、页码、章节、型号、版本和检索分数。

该组合用于解决“语义相似”和“精确标识”同时存在的问题。

## 证据充分性判断（Evidence Gate）

Evidence Gate 位于生成之前，负责判断当前证据是否足以支撑回答，并输出结构化 assessment：

- `sufficient`、`reason`、`score`、`evidence_count`；
- `raw_missing_terms`、`filtered_missing_terms`、`generic_terms_ignored`；
- `retry_eligible`、`recommended_next_action`。

规则式过滤会忽略 `0`、`PLC`、手册、参数、故障等泛词，同时保留 `MB_CLIENT`、`16#80C8`、`ID`、`IP`、`PORT`、`502` 等有区分度标识。判断不调用 LLM，也不生成虚假 evidence score。

## 问题改写（Query Rewrite）

默认主流程保留原有一次 Query Rewrite，不形成开放循环。实验模式下，Query Rewrite 使用过滤后的缺失标识符构建补充查询，并重新走同一套 Hybrid Retrieval；没有另写检索系统。

## 引用校验（Citation Guard）

`app/generation/citation_guard.py` 检查回答中的引用是否对应本次 evidence。校验失败时不继续让模型自由修补，而是降级为本地证据摘要。`used_chunk_ids` 表示注入或使用的候选证据，不等同于逐句事实正确性。

## Trace

Trace 覆盖四类信息：

- 路由：`selected_tool`、intent、candidate plan、structured plan；
- 检索：Dense/BM25/RRF TopK、final evidence、rewritten queries、retrieval rounds；
- 控制：evidence assessments、tool calls、budget、stop reason；
- 生成：模型、降级机制（fallback）、Token、延迟、引用警告和最终 evidence；`first_token_latency_ms` 当前表示“响应可用耗时（当前不代表真实 TTFT）”，因为 LLM 不是 Token Streaming。

Trace 用于区分 retrieval miss、ranking late、证据不足、预算停止、模型降级和引用异常，不是简单日志拼接。

## 受控 Agent 层

### 意图分类器（Intent Classifier）

规则式分类八类 intent：故障诊断、参数、表格、跨章节流程、版本、普通手册、安全风险和越界。输出置信度、命中关键词和原因，不调用 LLM。

### 工具路由器（Tool Router）

根据 intent 生成候选工具序列，并以当前 Tool Registry 的 `agent_names` 过滤。默认只写入 Trace；开启 routing 后，仍只有 `table_lookup`、`cross_section_procedure`、`version_resolution` 等适用 intent 可以进入 executor。

### 有界问题规划器（Bounded Query Planner）

生成最多 3 步的严格 Pydantic `Plan`。每个 `PlanStep` 包含 `step_id`、`tool_name`、`arguments`、`reason` 和 `expected_evidence`；Plan 还包含 `intent`、`allow_generation`、`need_evidence_gate`、`max_rounds` 和 `max_tool_calls`。Planner 不调用 LLM，安全和越界 intent 不生成执行步骤。

### 受控执行器（ControlledAgentExecutor）

`app/agent/executor.py` 是唯一的计划执行边界：再次调用 Tool Registry 的严格输入 Schema 校验参数，使用请求级 budget，生成稳定工具签名，缓存 `ToolResult`，并在重复调用时标记 `reused` / `deduplicated`。Registry 一旦返回 `ToolResult`，结果会先发布到请求级恢复缓存，再进行 Trace 后处理；因此后处理异常进入固定 fallback 时仍会复用已有结果。计划校验、未知工具、非法参数、timeout、预算或执行异常都会写入 fallback Trace，而不会把请求变成 500。

## 工具层（Tool Layer）

### 工具注册中心（Tool Registry）

`app/agent/tool_registry.py` 是四个正式工具的统一执行入口：它保留 `ToolRegistry` 类名和工具函数名原样，并统一完成 Pydantic 参数校验、工具预算、单工具超时、错误处理、`ToolCallTrace` 与工具指标结算。

### ToolResult

`app/models.py` 定义四个独立 Pydantic 输入模型，以及统一 `ToolResult` 和 `ToolCallTrace`。规范结果字段包括 `tool_name`、`success`、`data`、`result_count`、`error` 和 `latency_ms`；旧的 `tool`、`content`、`evidence`、`provenance`、`metadata` 字段继续兼容。真实固定 Graph 已使用该返回类型。

### SQLiteToolbox

`app/agent/tools.py` 封装：

- `lookup_fault_code`；
- `lookup_parameter`；
- `lookup_table_rows`。

查询复用 MemoryStore，用户输入始终作为参数传入，不生成 SQL、不执行写操作。结构化记录没有 `source/page/chunk_id` 时只能作为 metadata 或候选上下文，不能直接包装成最终可引用事实。

当前 Tool Registry 注册并允许受控 Planner 执行 `search_manual`、`lookup_fault_code`、`lookup_parameter` 和 `get_document_page`。故障码与参数工具复用 `SQLiteToolbox`，检索复用 `HybridRetriever.search_with_trace()`，文档页工具优先复用已处理 chunks。`lookup_table_rows` 仍只属于 SQLiteToolbox 的独立能力与测试，不进入 Router 或真实 Planner；`lookup_verified_solution` 仍是固定 Graph 内部逻辑，不是 Registry 工具。

对外 `selected_tool` 暂时保留 `lookup_alarm_code` 和 `check_parameter_range` 旧值，以兼容现有 API、会话记录和评测数据；Graph State 的 `execution_tool` 与 ToolCallTrace 使用 `lookup_fault_code` 和 `lookup_parameter` 规范名称。

## 数据访问层（Repository）

`app/repositories/` 为会话、反馈、人工确认方案、Trace metadata 和评测记录提供统一读写接口。`ConversationRepository` 等类名保持原样；默认实现使用 SQLite，也可以通过 `DATABASE_BACKEND=postgres` 切换运行型数据到 PostgreSQL。Qdrant 和静态知识表不随之迁移。

## 运行指标采集器（MetricsCollector）

`app/metrics.py` 在当前进程内聚合 HTTP、RAG、检索、LLM 和工具指标，并通过 `/metrics` 与 `/api/metrics/runtime` 暴露结果。P50/P95/P99 使用最近最多 1000 个样本的滚动窗口，不是全生命周期分位数；多 worker 和独立 MCP 进程的指标不会自动合并。

`tool_call_total` 表示 Tool Registry 统一完成点收到的工具调用尝试次数，包含 unknown tool、参数非法或预算拒绝等 `executed=false` 尝试；它不等于 handler 真实执行次数。只有 `executed=true` 的 `search_manual` 才会增加 `retrieval_request_total`。

## MCP 与 Web 入口

- `app/mcp/server.py` 是本地 MCP stdio 协议适配层，复用 Service 与 Tool Registry；它没有实现远程 HTTP MCP、认证、TLS 或多租户隔离。
- `frontend/` 是 React + TypeScript Demo，通过工作流级 SSE 展示阶段事件；当前不是 LLM Token Streaming。
- `static/` 是继续保留的原生 HTML/CSS/JavaScript 页面，不需要 React 构建即可使用。

## Iterative Retrieval

### 默认关闭

`ENABLE_ITERATIVE_RETRIEVAL=false`。关闭时不引入新增循环，也不改变 `/api/chat`、`/api/search` 的默认路径。

### 开关与条件

开启后必须同时满足：证据不足、assessment 建议重试、存在有效缺失标识符、非安全/越界请求、预算未耗尽且未超时。

### Budget 控制

```text
max_agent_rounds = 2
max_tool_calls = 4
max_llm_calls = 2
agent_timeout_seconds = 60
max_rewrites = 1
```

Registry 在每次真实工具执行前强制检查 `max_tool_calls`，被预算拒绝的调用会生成 `executed=false` 的 ToolCallTrace，但不会执行 handler，也不会增加已执行工具数。每个工具还受 `TOOL_TIMEOUT_SECONDS` 约束。现有 agent budget snapshot 复用这些 Trace 统计，并继续判断实验性迭代检索是否还能重试。

`agent_timeout_seconds` 从 Agent 分析开始计时，用于限制受控 Planner 工具的可用 timeout，以及后续检索/Query Rewrite 是否继续；它不包围 LLM 生成、Citation Guard 或整个 HTTP 请求，不是全链路硬 deadline。`ENABLE_AGENTIC_ROUTING=false` 且 Iterative Retrieval 关闭时，新增受控 Agent budget 不会提前截断旧固定流程原有的一次 Query Rewrite。

### Stop Reason

可能的停止原因包括：

- `evidence_sufficient`；
- `generic_terms_only`；
- `max_rounds_reached`；
- `max_rewrites_reached`；
- `max_tool_calls_reached`；
- `timeout_reached`；
- `safety_blocked`；
- `out_of_scope`；
- `insufficient_evidence`。

这套机制的目标是可解释地停止，而不是让 Agent 持续“再试一次”。
