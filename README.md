# AutoOps RAG

基于 LangGraph 的轻量级 Agentic RAG 工业知识库系统，面向 Siemens S7-1200 与 Modbus 技术资料，提供可追溯的手册检索、参数查询和故障辅助分析。

当前应用与 API 版本为 `4.1.0`。

它不是完全自主 Agent：默认仍执行固定、可审计的 LangGraph 工作流；显式设置 `ENABLE_AGENTIC_ROUTING=true` 后，现有确定性有界问题规划器（Bounded Query Planner）只对表格定位、跨章节流程和版本核对等适用请求执行受控计划。它不调用 LLM 做规划，不能创建任意工具，任何校验、预算、超时或工具异常都会回退固定流程。

当前实现边界：

- **已真实实现**：FastAPI API、固定 LangGraph 主流程、工具注册中心（Tool Registry）、四个正式工具、feature-flagged 受控 Planner、本地 MCP stdio Server、React + TypeScript Demo、工作流级 SSE、运行数据访问层（Repository）以及轻量运行指标。
- **默认关闭 / experimental**：`ENABLE_AGENTIC_ROUTING=false` 时 Planner/Router 只记录候选决策；开启后也只允许确定性计划、Registry 白名单、统一 budget、timeout、去重和 fallback。Iterative Retrieval 仍须单独显式开启。
- **尚未实现**：LLM Planner、开放式工具循环、Multi-Agent、远程 HTTP MCP、LLM Token Streaming，以及生产级多实例监控与运维能力。

## 项目简介

工业手册篇幅长、表格多，故障码、参数名、版本和操作流程散落在不同章节。纯向量检索容易漏掉 `16#80C8`、`MB_CLIENT`、`Unit ID` 等精确标识，直接把检索结果交给大模型又可能产生无来源补充。

AutoOps RAG 将文档解析、混合检索、证据充分性判断（Evidence Gate）、生成、引用校验（Citation Guard）和 Trace 拆成显式步骤：先确认范围和安全边界，再检索证据；证据不足时只执行有界的问题改写（Query Rewrite），引用异常时通过降级机制（fallback）返回本地证据摘要。

当前数据审计结果：

- 16,969 个知识切片；
- 12,035 个表格行切片，覆盖 1,861 张表；
- 表格行、页码、章节、型号、版本、`chunk_id` 等元数据随证据保留。

数据来自本地合法取得的技术资料和项目补充材料，原始手册不随代码仓库分发。

## 技术栈

Python 3.11、FastAPI、LangGraph、MCP Python SDK、Qdrant、BGE/FastEmbed、BM25、RRF、PyMuPDF、SQLite、SQLAlchemy 2.x、Alembic、可选 PostgreSQL、React、TypeScript、Vite、Docker Compose、Pytest。

## 核心能力

| 能力 | 实现 |
|---|---|
| 文档结构化 | PyMuPDF 解析正文和表格，按页级文本与表格行构建切片并保留来源元数据 |
| Hybrid Retrieval | Qdrant Dense Retrieval + BM25，使用 RRF 融合和轻量 Rerank |
| 可控工作流 | LangGraph 显式编排安全门控、结构化查询、检索、Evidence Gate、Query Rewrite、生成和 Citation Guard |
| 证据约束 | Evidence Gate 检查证据数量、相关度和技术标识符覆盖；证据不足时不允许模型自由补全 |
| 引用校验 | Citation Guard 校验回答引用是否来自本次证据，失败时降级为本地证据摘要 |
| 工具封装 | LangGraph 固定路由通过 Tool Registry 执行 `search_manual`、`lookup_fault_code`、`lookup_parameter` 和 `get_document_page`，统一校验参数、结果、Trace、预算与超时 |
| 本地 MCP | stdio MCP Server 暴露同一组四个工具，直接复用 Tool Registry 和 Service，不经过 FastAPI HTTP 接口 |
| 受控 Agent | 默认仅记录候选计划；开启 `ENABLE_AGENTIC_ROUTING` 后，确定性 Planner 可在 Registry 白名单、统一预算、timeout、去重和 fallback 下执行适用请求 |
| 有界迭代检索 | 可选二次检索，受轮数、Query Rewrite、工具、LLM 和超时预算控制；默认关闭 |
| 可观测性 | Trace 记录检索候选、证据评估、候选计划、工具调用、预算、停止原因、模型和延迟 |
| Web 演示 | 新增 React + TypeScript 页面和 workflow SSE，可实时展示节点进度及最终 Answer、Citation、Evidence、Trace；原生 HTML/JavaScript 页面继续保留 |
| 运行数据 | Conversation、Feedback、Verified Solution、Trace metadata 和 Evaluation record 通过独立 Repository 接口访问；默认 SQLite，可选 PostgreSQL |
| 工程化 | FastAPI、Docker、模型 fallback、限流、自动化测试和多套离线评测脚本 |

## 系统架构

```mermaid
flowchart LR
    U["Legacy Web / API Client"] --> API["FastAPI JSON API"]
    WEB["React Demo"] --> SSE["POST /api/chat/stream"]
    MC["External MCP Client"] --> MS["Local MCP Server (stdio)"]
    API --> SVC["AutoOps Service"]
    SSE --> SVC
    MS --> SVC
    SVC --> G["LangGraph Workflow"]
    G --> SAFE["Scope / Safety Gate"]
    SAFE -->|"blocked"| REFUSE["Safe Refusal"]
    SAFE -->|"accepted"| ROUTE["Rule-first Router"]
    ROUTE -->|"flag off / stable rule"| FIXED["Fixed Routing"]
    ROUTE -. "flag on + eligible" .-> PLAN["Bounded Planner + Executor"]
    PLAN -->|"validated / fallback"| FIXED
    FIXED --> TOOL["Tool Registry"]
    TOOL --> RET["Hybrid Retrieval / Static SQLite / Document Page"]
    RET --> D["Qdrant / BGE"]
    RET --> B["BM25"]
    D --> RRF["RRF + Light Rerank"]
    B --> RRF
    RRF --> EG["Evidence Gate"]
    EG -->|"sufficient"| GEN["Grounded Generation"]
    EG -. "gated and budgeted" .-> RW["Query Rewrite / Retry"]
    RW -.-> RET
    GEN --> CG["Citation Guard"]
    CG --> OUT["Answer + Evidence"]
    SVC --> REPO["Runtime Repository Interfaces"]
    REPO --> RSQL["SQLite (default)"]
    REPO --> PG["PostgreSQL (optional)"]
    G --> TRACE["RAG Trace"]
    TOOL --> TRACE
    RET --> TRACE
    EG --> TRACE
    CG --> TRACE
    TRACE --> JSONL["Full sanitized JSONL"]
    TRACE --> REPO
```

详细模块和边界见 `docs/architecture.md`。

## RAG 主流程

```text
用户请求 -> FastAPI -> Service -> LangGraph -> Tool Registry -> RAG/工具
        -> LLM 或本地证据摘要 -> Citation Guard -> 返回答案、证据和 Trace
```

1. FastAPI 接收问题并生成 `request_id`。
2. Service 处理会话上下文，调用 LangGraph。
3. Scope/Safety Gate 在检索和模型调用前短路危险请求、越界型号和资料不足的版本问题。
4. 规则优先：Safety、越界、明确故障码、明确参数和普通单步检索不进入真实 Planner。默认关闭时，Planner/Router 只记录候选计划。
5. 开启 `ENABLE_AGENTIC_ROUTING` 后，表格定位、跨章节流程和版本核对等适用请求可进入确定性 Planner；计划先经 Pydantic 和 Tool Registry 参数 Schema 双重校验，再由统一 executor 执行。
6. 固定路由或受控计划都通过同一 Tool Registry；计划已经执行的相同 `search_manual` 会在 `retrieve` 节点复用，不重复进行 Dense/BM25/RRF/Rerank，也不重复增加真实工具指标。
7. Evidence Gate 判断证据是否足够，并记录原始缺失词、过滤后标识符和被忽略泛词。
8. `ENABLE_AGENTIC_ROUTING=false` 且 Iterative Retrieval 关闭时，固定路径保留原有一次 Query Rewrite，不让新增 Agent budget 提前截断旧流程；Planner 实际参与后，Query Rewrite 才与它共用工具、轮数、改写次数和 Agent 检索/工具阶段的时间预算。
9. 证据充分时执行基于证据的生成（grounded generation）；模型不可用时按 fallback 链降级。
10. Citation Guard 校验引用，输出回答、证据、运行统计和完整 Trace。

## Agentic RAG 扩展能力

- `IntentClassifier`：规则式识别故障诊断、参数、表格、跨章节流程、版本、安全和越界意图，不调用 LLM。
- `ToolRouter`：规则优先选择是否进入 Planner，并按照当前 Tool Registry 的 `agent_names` 过滤候选；不维护第二套可执行白名单。
- `BoundedQueryPlanner`：不调用 LLM，最多生成 3 个严格 Pydantic `PlanStep`；每步包含 `tool_name`、`arguments`、`reason` 和 `expected_evidence`。
- `ControlledAgentExecutor`：统一负责计划校验、Registry 参数复核、request-scoped budget、timeout、调用签名、结果缓存、去重和 fallback。
- `ToolRegistry`：工具注册中心，登记四个带独立 Pydantic 输入模型的核心工具，并统一处理参数校验、未知工具、`max_tool_calls`、单工具 timeout、异常和 `ToolCallTrace`。
- `SQLiteToolbox`：结构化知识查询组件，作为 Registry 中故障码和参数工具的底层实现，以统一 `ToolResult` 返回结构化 data、证据、provenance、耗时和错误。工具结果不能在没有可靠来源时直接成为最终事实。
- `DocumentPageService`：原始页证据读取服务，优先按已处理 chunk 的文档与页码定位证据，必要时只打开精确匹配 PDF 的指定页，不扫描整份 PDF。
- Iterative Retrieval：只在证据不足、存在有效技术标识符且预算允许时重试；`0`、`PLC`、手册、参数等泛词不能单独触发重试。

这些能力构成“受控 Agent”：系统能够在显式开关下执行确定性计划，但固定工作流始终保留为 fallback；它不允许开放式工具生成、任意 SQL、外部 Web、系统状态修改或无限循环。

## 为什么不是 naive RAG

naive RAG 通常是“一次向量检索 → 拼接 TopK → LLM 回答”。本项目额外处理了：

- 精确术语与自然语言并存，因此使用 Dense + BM25 + RRF；
- 表格行与表头容易分离，因此构建带表格元数据的行级切片；
- 证据可能不足，因此在生成前设置 Evidence Gate；
- 引用可能越界，因此生成后设置 Citation Guard；
- 工业请求存在安全和版本边界，因此安全检查位于检索和 LLM 之前；
- Agent 决策需要可解释，因此 candidate/applied plan、budget、fallback reason、复用状态、stop reason 和检索轮次全部进入 Trace。

## 本地启动

要求：Windows PowerShell、Python 3.11；Docker Compose 为可选方案。

```powershell
Set-Location D:\autoops-rag
Copy-Item .env.example .env
Set-ExecutionPolicy -Scope Process Bypass
.\scripts\setup_d_drive.ps1
.\scripts\start_background.ps1
```

服务地址：

- 项目页面：`http://127.0.0.1:8000/`
- API 文档：`http://127.0.0.1:8000/docs`
- Swagger：`http://127.0.0.1:8000/swagger`
- 就绪检查：`http://127.0.0.1:8000/health/ready`

停止服务：

```powershell
.\scripts\stop.ps1
```

Docker 启动：

```powershell
docker compose config --quiet
docker compose up --build -d
```

## React + SSE Demo

`frontend/` 是独立的 React + TypeScript + Vite 工程。原生页面仍保留在 `http://127.0.0.1:8000/`，React 页面作为新入口，不替换旧页面。

开发模式需要分别启动后端和前端：

```powershell
# 仓库根目录
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000

# 新终端
Set-Location frontend
npm install
npm run dev
```

访问 `http://127.0.0.1:5173/demo/`。Vite 默认把 `/api` 和 `/health` 代理到本地 8000 端口，因此不需要开放跨域；如果后端运行在其他可信地址，可复制 `frontend/.env.example` 并设置 `VITE_API_BASE_URL`。

生产构建验证和 FastAPI 静态入口：

```powershell
Set-Location frontend
npm run typecheck
npm run build
Set-Location ..
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

构建完成后访问 `http://127.0.0.1:8000/demo`。`frontend/dist` 是本地构建产物，不提交仓库；当前 Dockerfile/Compose 没有强制加入 Node 构建阶段，Docker 启动仍以 API、旧页面和 MCP 业务能力为主。

React 页面通过 `POST /api/chat/stream` 接收以下稳定 SSE 事件：

```text
request_started -> analyzing -> tool_selected -> retrieving -> reranking
                -> rewriting（仅证据不足时）
                -> generating -> citation_check -> completed
```

安全门控（Safety Gate）拒绝路径会跳过工具和检索，异常路径以 `error` 结束。每个事件包含 `event`、`request_id`、`timestamp`、`stage`、`message` 和经过脱敏的 `data`；`completed.data.response` 是与 `/api/chat` 相同的完整 `ChatResponse`。页面基于该响应展示 Answer、可展开 Citation、Evidence 和 Trace，包括工具调用、问题改写、检索轮次、停止原因、延迟、模型/provider 表示及可用的 Token 消耗（token usage）。

当前是工作流事件流（workflow event streaming），不是 Token Streaming：LLM Client 仍使用非流式请求，最终回答随 `completed` 事件一次性返回。页面的“停止接收”使用浏览器 AbortController，只停止前端等待和连接；后端会尽快停止等待，但正在执行的同步检索或模型 I/O 可能短暂继续。受控 Planner 是否执行由后端 feature flag 决定；本地 MCP 继续作为独立 stdio 入口，不经 SSE。

## 本地 MCP Server

项目已提供基于官方 MCP Python SDK 的本地 stdio Server。它与 FastAPI 是并列入口，共用 `AutoOpsService`、`ToolRegistry`、Retriever、SQLite 和 `DocumentPageService`；MCP 层不调用 `/api/chat` 或 `/api/search`，也不复制检索、SQL 或 PDF 解析逻辑。

从仓库根目录启动 Server：

```powershell
.\.venv\Scripts\python.exe -m app.mcp.server
```

stdio Server 启动后会等待 MCP Client 通过标准输入/输出通信，不提供 HTTP 端口。通常不需要手工先启动它，下面的独立示例会自动创建 Server 子进程、列出工具，并调用故障码查询和手册检索：

```powershell
.\.venv\Scripts\python.exe examples\mcp_client.py
```

| MCP 工具 | 用途 |
|---|---|
| `search_manual` | 通过现有 Hybrid Retriever 检索手册证据 |
| `lookup_fault_code` | 精确查询结构化故障码记录 |
| `lookup_parameter` | 查询设备参数或表格字段 |
| `get_document_page` | 按已知文档 ID/名称和页码读取允许范围内的原始证据 |

四个工具的 `inputSchema` 直接来自现有 Pydantic 输入模型；响应同时包含 JSON 文本 `content` 和完整 `ToolResult` 结构化内容，保留 evidence、provenance、Trace、耗时和错误。每个 MCP 进程只初始化一套 Service/Registry，多个调用复用该实例，退出时统一释放 Retriever 和工具线程池。

当前边界：只实现本地 stdio transport，没有远程 HTTP MCP、认证、TLS 或多租户隔离；`get_document_page` 仍受现有精确文档匹配和页码约束，不能读取任意文件。LangGraph 的受控 Planner 与 MCP 共用 Tool Registry，但不会通过 MCP 回调自身。因此系统仍不是 fully autonomous Agent，也不代表生产级远程 MCP 部署。

## 运行数据访问层（Runtime Repository）与 PostgreSQL

阶段 D 只抽象运行型数据，不把整个项目强制迁到 PostgreSQL：

| 存储 | 当前职责 |
|---|---|
| Qdrant | Dense 向量检索；不迁 pgvector |
| SQLite 静态知识 | `alarm_codes`、`parameters`、`kg_nodes`、`kg_edges` 和可选手册表格行 |
| Runtime Repository | `conversation_memory`、`conversation_turns`、`answer_feedback`、`verified_solutions`、`solution_reuse_events`、`trace_metadata`、`evaluation_runs`、`evaluation_records` |
| JSONL / Markdown | 完整脱敏 RAG Trace 和离线评测报告，继续保留 |

运行数据由 `ConversationRepository`、`FeedbackRepository`、`VerifiedSolutionRepository`、`TraceRepository` 和 `EvaluationRepository` 分责；这些代码类名保持原样。SQLAlchemy 实现使用短生命周期 Session，每次事务结束都会 commit 或 rollback 并关闭 Session。Service 和 Graph 不直接持有 ORM Session，也不写 SQL。

默认配置不需要 PostgreSQL：

```text
DATABASE_BACKEND=sqlite
POSTGRES_DSN=
DATABASE_POOL_SIZE=5
DATABASE_MAX_OVERFLOW=10
DATABASE_POOL_TIMEOUT_SECONDS=30
DATABASE_CONNECT_TIMEOUT_SECONDS=3
```

SQLite 默认继续使用 `storage/autoops.db`，但静态知识与运行数据已由不同 class 管理，因此旧本地数据不需要强制搬迁。切换 PostgreSQL 时只切换运行数据：

```powershell
$env:DATABASE_BACKEND = "postgres"
$env:POSTGRES_DSN = "postgresql+psycopg://autoops:autoops-local-only@127.0.0.1:5432/autoops"
```

PostgreSQL schema 由 Alembic 管理，应用不会在 PostgreSQL 上自动 `create_all`：

```powershell
.\.venv\Scripts\python.exe -m alembic upgrade head
.\.venv\Scripts\python.exe -m alembic current
.\.venv\Scripts\python.exe -m alembic downgrade -1
```

`downgrade` 会删除运行型表，应只在确认可丢弃对应运行数据时执行。Initial migration 不迁移或删除现有 SQLite 数据，也不涉及 alarm、parameter、KG、Qdrant 或文档 chunks。

可选 Docker PostgreSQL 使用独立 override，不影响默认 Compose：

```powershell
docker compose -f docker-compose.yml -f docker-compose.postgres.yml up -d postgres
$env:DATABASE_BACKEND = "postgres"
$env:POSTGRES_DSN = "postgresql+psycopg://autoops:autoops-local-only@127.0.0.1:5432/autoops"
.\.venv\Scripts\python.exe -m alembic upgrade head
docker compose -f docker-compose.yml -f docker-compose.postgres.yml up --build -d
```

`/health` 和 `/api/index/status` 会分别返回 `database_backend`、`database_status` 与脱敏的 `database_error_type`。运行数据库短暂不可用时，会话上下文、会话写入和 Trace metadata 会降级，不阻断静态手册检索；显式 Feedback/Verified Solution 写入仍会返回失败，不能伪装成已保存。

Trace 采用“数据库 metadata + JSONL 完整 payload”：Repository 保存 `request_id`、时间、`session_id`、状态、错误、query/rewrite、工具、模型、延迟、Token 消耗和 stop reason；完整 retrieval candidates/evidence 继续写脱敏 JSONL。Formal evaluation 仍生成 JSON/Markdown，同时只向 EvaluationRepository 写 run metadata、逐题状态/关键指标和汇总；Retrieval 历史口径保持不变，E2E 规则指标单独报告。

当前 PostgreSQL 支持是单实例、同步 SQLAlchemy 和基础连接池方案，不包含高可用、备份恢复、读写分离、远程密钥管理或生产级运维承诺。

## 测试与评测

全部测试与 formal 数据校验：

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe scripts\validate_formal_eval.py
```

Ranking-only eval：

```powershell
.\.venv\Scripts\python.exe scripts\eval_ranking_only.py --mode local --split development
```

Formal evaluation 先做 dry-run；它只校验 `formal_eval_v1` manifest、dataset hash、split 和运行前置条件，不调用 API、不生成指标：

```powershell
.\.venv\Scripts\python.exe scripts\run_formal_eval.py --dry-run --split test
.\.venv\Scripts\python.exe scripts\run_formal_eval.py --split test
```

Formal evaluation 分为两层：Retrieval Evaluation 保留 Strict Recall@5、MRR@5、nDCG@5 和 Top1；End-to-End Rule Evaluation 计算 Citation Correctness、Required Fact Coverage、精确技术标识、多跳 Evidence coverage 和 Refusal Correctness。Retrieval Recall 不等于最终回答准确率。

Agentic shadow eval：

```powershell
.\.venv\Scripts\python.exe scripts\eval_agentic_shadow.py
```

Iterative retrieval A/B eval：

```powershell
.\.venv\Scripts\python.exe scripts\eval_iterative_retrieval.py
```

最新指标、口径与不可宣传项见 `docs/eval-summary.md`。

## 查看 Trace

`POST /api/chat` 返回 `request_id` 和 `rag_trace`。也可以查询：

```powershell
Invoke-RestMethod "http://127.0.0.1:8000/api/traces/$requestId"
Invoke-RestMethod "http://127.0.0.1:8000/api/traces/recent?limit=20"
```

Trace 包含 `selected_tool`、intent、candidate plan、structured plan、检索候选、evidence assessments、rewritten queries、retrieval rounds、tool calls、budget 和 stop reason。结构示例见 `docs/trace-example.md`。

## 当前默认配置

```text
LLM_ENABLED=false
ENABLE_AGENTIC_RAG=false
ENABLE_AGENTIC_ROUTING=false
ENABLE_AGENTIC_PLANNER=false
ENABLE_SQLITE_TABLE_TOOL=false
ENABLE_ITERATIVE_RETRIEVAL=false
MAX_AGENT_ROUNDS=2
MAX_TOOL_CALLS=4
MAX_LLM_CALLS=2
AGENT_TIMEOUT_SECONDS=60
TOOL_TIMEOUT_SECONDS=30
MAX_REWRITES=1
DATABASE_BACKEND=sqlite
```

`ENABLE_AGENTIC_ROUTING=false` 时 API 保持固定 Graph，Planner/Router 只产生候选 Trace；在 Iterative Retrieval 也关闭时，新增 Agent budget 不会改变旧固定路径的一次 Query Rewrite、检索、Evidence Gate 和 Citation Guard 行为。Trace 会继续包含扩展后的候选 Plan 与预算字段，因此不承诺 Trace payload 与阶段 G 前逐字节一致。设置为 `true` 后，仅适用 intent 进入受控 Planner；明确故障码、明确参数、普通单步检索、Safety 和 Out-of-scope 仍走稳定规则。`ENABLE_AGENTIC_PLANNER` 是旧的 shadow 配置兼容项，不是当前真实执行开关。

受控执行只允许 Tool Registry 标记的 `search_manual`、`lookup_fault_code`、`lookup_parameter`、`get_document_page`。请求级预算统一限制 `MAX_AGENT_ROUNDS`、`MAX_TOOL_CALLS`、`MAX_REWRITES` 和 `TOOL_TIMEOUT_SECONDS`；`AGENT_TIMEOUT_SECONDS` 是从 Agent 分析开始计算、用于限制 Planner 工具执行及后续检索/改写是否继续的剩余时间，不是覆盖 LLM、Citation Guard 或整个 HTTP 生命周期的硬 deadline。完全相同的工具名与规范化参数只真正执行一次。结构化故障码/参数结果只是线索，最终回答仍必须经过手册 Evidence Gate 和 Citation Guard；`get_document_page` 只能使用已有 Evidence 中明确出现的文档与页码。

## 可观测性（Observability）

### 这套监控是做什么的

这套轻量监控用于回答三个问题：系统处理了多少请求、请求是否成功，以及主要耗时发生在检索、Rerank、LLM 还是工具调用阶段。运行指标采集器（MetricsCollector）在当前进程内汇总数据，不改变 RAG 主流程。

```text
业务请求 -> FastAPI 中间件 -> Service / LangGraph / Tool / LLM
        -> Trace（单次请求明细）+ 运行指标采集器（MetricsCollector，多请求汇总）
        -> /metrics 和 /api/metrics/runtime
```

请求指标覆盖业务 API，但排除静态资源、Demo、OpenAPI/文档、健康检查、`/api/index/status` 和指标接口自身。一次 `/api/chat/stream` 无论产生多少个 SSE 事件都只结算一次；SSE 超时或内部错误虽然通过 HTTP 200 返回安全的 `error` 事件，仍会计入失败或超时。MCP stdio 调用不计入 HTTP 请求指标。

### 能看到哪些指标

HTTP 请求指标：

| 中文名称 | 英文变量名 | 一句话解释 |
| --- | --- | --- |
| 请求总数 | `request_total` | 系统一共结算了多少次业务 HTTP 请求。 |
| 成功请求数 | `request_success_total` | 有多少次业务请求成功完成。 |
| 失败请求数 | `request_error_total` | 有多少次业务请求以错误结束。 |
| 超时请求数 | `request_timeout_total` | 有多少次业务请求因超时结束。 |
| 当前正在处理的请求数 | `active_requests` | 此刻仍在处理中、尚未结算的业务请求有多少。 |
| 请求错误分类 | `errors_by_category` | 失败请求按有限、固定的错误类别分别计数。 |
| 请求耗时 | `request_ms` | 记录业务请求从开始到结算的总耗时。 |

RAG 与检索指标：

| 中文名称 | 英文变量名 | 一句话解释 |
| --- | --- | --- |
| RAG 请求数 | `rag_request_total` | 一共有多少次请求进入了 RAG 结果结算。 |
| 问题改写次数（Query Rewrite） | `rewrite_total` | 工作流一共执行了多少次 Query Rewrite。 |
| 问题改写请求数 | `rewrite_request_total` | 有多少个请求至少执行过一次 Query Rewrite。 |
| 改写率 | `rewrite_rate` | 多少请求因为证据不足等原因触发了 Query Rewrite。 |
| 拒答次数（refusal） | `refusal_total` | 有多少次请求因安全、范围或证据原因返回拒答。 |
| 拒答率 | `refusal_rate` | 拒答请求占全部 RAG 请求的比例。 |
| 证据不足次数（evidence insufficient） | `evidence_insufficient_total` | 有多少次最终结果被判定为证据不足。 |
| 引用校验失败次数（citation failure） | `citation_guard_failure_total` | 有多少次回答没有通过 Citation Guard 引用校验。 |
| 降级/备用模型次数（fallback） | `fallback_total` | 主模型失败后使用备用模型的次数。 |
| 降级率 | `fallback_rate` | 多少次 RAG 请求使用了降级/备用模型。 |
| 检索请求数（retrieval） | `retrieval_request_total` | 每次实际执行 `search_manual` 计一次，问题改写后再次检索会另计一次。 |
| 检索候选数 | `retrieved_candidate_count` | 检索与融合阶段一共返回了多少候选片段。 |
| 最终证据数 | `final_evidence_count` | 最终保留并交给回答阶段的证据片段有多少。 |
| 检索耗时 | `retrieval_ms` | 记录一次 `search_manual` 的完整检索耗时，不会把 Dense、BM25、RRF 和 Rerank 分别重复计成检索请求。 |
| Dense/BM25/RRF/Rerank 耗时 | `dense_ms` / `bm25_ms` / `fusion_ms` / `rerank_ms` | 分别记录 Dense、BM25、RRF 融合和 Rerank 阶段的耗时。 |
| Planner 尝试/应用/回退次数 | `planner_attempt_total` / `planner_applied_total` / `planner_fallback_total` | 分别表示多少请求尝试、成功应用或回退了受控计划。 |
| Planner 错误次数 | `planner_error_total` | 计划解析、Schema、未知工具、timeout 或 executor 异常导致回退的次数。 |
| Agent 轮数 | `agent_round_total` | 所有受控 Planner 请求实际使用轮数的累计值。 |
| 工具复用次数 | `tool_reuse_total` | 相同签名的工具结果被请求级缓存复用、没有再次真实执行的次数。 |
| 预算耗尽次数 | `budget_exhausted_total` | 因轮数、工具次数、改写次数或 Agent 检索/工具阶段时间预算停止的请求数。 |

LLM 与工具指标：

| 中文名称 | 英文变量名 | 一句话解释 |
| --- | --- | --- |
| LLM 调用次数 | `llm_call_total` | 系统一共尝试调用了多少次 LLM。 |
| LLM 错误次数 | `llm_error_total` | 有多少次 LLM 调用最终失败。 |
| LLM 降级次数 | `llm_fallback_total` | 有多少次 LLM 调用切换到了降级/备用模型（fallback）。 |
| LLM 耗时 | `llm_ms` | 记录 LLM 请求到完整响应可用的耗时。 |
| Token 消耗（token usage） | `input_tokens` / `output_tokens` / `total_tokens` | 分别记录输入、输出和总 Token 数；缺少 Provider 用量时不会猜测。 |
| 有 Token 数据的请求数 | `token_usage_request_total` | 有多少次请求真实返回了 `total_tokens`，它也是平均 Token 数的分母。 |
| 平均 Token 数 | `average_total_tokens` | 仅对真实返回 Token 消耗的请求计算平均值。 |
| 工具调用尝试次数（tool call attempts） | `tool_call_total` | 四个正式工具到达 Tool Registry 统一完成点的尝试次数；包含 unknown tool、参数非法或预算拒绝等 `executed=false` 尝试，不等于 handler 真实执行次数。 |
| 工具成功/失败/超时次数 | `tool_success_total` / `tool_error_total` / `tool_timeout_total` | 分别表示工具调用成功、失败和超时的次数。 |
| MCP 工具调用次数 | `mcp_tool_call_total` | 通过 MCP 发起的工具调用次数；它不会让通用工具计数重复累加。 |
| 工具耗时 | `tool_ms` | 记录工具调用耗时，并按固定工具名分别汇总。 |

### `/metrics` 是什么

`GET /metrics` 返回 Prometheus 兼容的文本格式（Prometheus-compatible text exposition），方便外部采集器读取计数和延迟数据。项目当前只提供这个端点，没有随项目启动 Prometheus Server 或 Grafana，也不代表已经搭建生产级监控平台。

### `/api/metrics/runtime` 是什么

`GET /api/metrics/runtime` 返回适合人和 Web 页面阅读的 JSON，按 `request`、`latency`、`rag`、`llm`、`tools` 五组展示运行指标，并通过 `window` 说明延迟窗口配置。`GET /api/metrics/business` 仍是原有的业务反馈与已验证方案指标，职责和返回结构不变。

### P50/P95/P99 怎么理解

延迟分位数（P50/P95/P99）用于描述“大多数请求有多快”，不是成功率：

- P50 延迟：50% 的请求耗时低于或等于这个值，也可理解为典型请求耗时。
- P95 延迟：95% 的请求耗时低于或等于这个值，适合观察较慢请求。
- P99 延迟：99% 的请求耗时低于或等于这个值，适合观察尾部慢请求。

`METRICS_LATENCY_WINDOW_SIZE` 默认是 `1000`。这些分位数使用最近最多 1000 个样本的滚动窗口（rolling window），并采用 nearest-rank 算法；API 字段为 `rolling_p50_ms`、`rolling_p95_ms`、`rolling_p99_ms`。它们不是进程启动以来的全生命周期分位数。延迟的 `count`、`sum` 和 `average` 仍从当前进程启动后累计。

### Trace 和 Metrics 有什么区别

- Trace（请求追踪）回答“这一次请求发生了什么”：脱敏后的完整 payload 写入本地 JSONL，运行数据库只保存 metadata，可以包含 query、候选证据、工具参数、停止原因和模型用量。
- Metrics（运行指标）回答“整体运行得怎么样”：只保存聚合计数、数值样本和固定低基数分类，不保存 request ID、完整 query、用户文本、API Key、异常消息或完整 Trace。
- 运行指标不会扫描 JSONL，也不会在每次请求时查询 SQLite/PostgreSQL；当前进程重启后，内存中的指标会清零。

### 当前限制

- 运行指标是单进程视角，多 worker 或独立 MCP stdio 进程的指标不会自动合并。
- 外部 Provider 当前没有可靠、统一的规范字段，因此没有按 provider/model 建立指标标签。
- `first_token_latency_ms` 应理解为“响应可用耗时（当前不代表真实 TTFT）”：当前 LLM 使用非流式请求，不是 Token Streaming，只有完整响应返回后才可用，因此它不是真正的首 Token 延迟（Time to First Token, TTFT）。
- 这套能力定位为轻量运行观测，不代表生产级监控体系。

### 面试快速解释版

1. 这套可观测性分为单请求追踪 Trace 和多请求聚合 Metrics。
2. 请求总数、成功、失败、超时和处理中请求都在统一位置一次性结算。
3. RAG 指标能看问题改写、拒答、证据不足、引用失败和模型降级。
4. 每次真实执行 `search_manual` 才计一次检索，内部四阶段不会重复计数。
5. 工具调用只在 Tool Registry 完成点计数，MCP 只标记调用来源。
6. `/metrics` 给 Prometheus 采集，`/api/metrics/runtime` 给人和页面读取 JSON。
7. P50/P95/P99 是最近 1000 个样本滚动窗口的延迟分位数，不是全生命周期统计。
8. 当前 LLM 非 Token Streaming，所以 `first_token_latency_ms` 实际表示完整响应可用耗时，不代表真实 TTFT。
9. 指标保存在当前进程内，重启会清零，多进程之间暂不自动合并。

## 当前评测摘要

- Pytest：默认环境 196 项通过，1 项 PostgreSQL integration test 因未配置专用测试 DSN 而跳过；本轮未重跑专用 PostgreSQL 环境。
- Formal dataset：`formal_eval_v1`，60 题，development 40 / test 20；SHA-256 为 `3b33876cd584e6215ef03a8bb07d0566aa57371957e606196c37b6f26641a4d9`。跳过 chunk 存在性检查时为 0 validation errors；由于官方资料占比和独立复核数量不足，`ready_for_resume_accuracy_claim=false`。
- 当前 processed corpus 由 6 个文档生成 16945 个 chunks（正文 4934、表格 12011），SHA-256 为 `090f5e5f416ea1762d4f71e7a28b10d0e7f083ef30ae04f3a305c1b6b769a213`；formal gold 11/11、test gold 8/8 可解析。
- 冻结 test split 20 题已真实运行：Retrieval 的 Strict Recall@5 0.8667、MRR@5 1.0000、nDCG@5 0.9028、Top1 Accuracy 1.0000；End-to-End 规则指标为 Citation Correctness 0.9286、Required Fact Coverage 0.3929、Technical Identifier Accuracy 0.6316、Refusal Accuracy 0.9500、false accept 0、false reject 0.0667，多跳 Evidence Coverage 1.0000（仅 4 个适用样本）。
- 旧 Ranking-only development 数值（Strict Recall@5 1.0000、MRR@5 0.9343、nDCG@5 0.9377、Top1 0.8857）来自旧 dataset hash `e251df9e...`，属于 stale/historical，不能继续作为当前正式结果。
- 新 E2E Schema 分开报告 `citation_correctness_rate`、规则型 `required_fact_coverage`、`technical_identifier_accuracy`、`multi_hop_evidence_coverage`、`refusal_accuracy`、`false_accept_rate` 和 `false_reject_rate`；不适用字段为 `null`。
- `claim_support_rate` 本轮为 `null`，不以 0 代替，也不包装成完整 Answer Faithfulness；本轮未启用 LLM-as-a-judge。
- test 中参数、表格、越界、Safety、无答案类别均少于 3 题。该类别样本量较小，仅用于诊断，不代表稳定统计结论。
- Agentic shadow：阶段 G 代码下的只读临时重跑为 24 个 overlay case，Intent Accuracy 1.0000、Tool Selection Accuracy 0.8750、Plan Valid 1.0000，Budget/Whitelist/Loop Violation 均为 0。3 个旧表格 case 仍期待已从 Router 移除的 `lookup_table_rows`，因此版本化旧报告的 Tool Selection 1.0000 属于阶段 G 前历史结果；本阶段没有为追分修改该 overlay 数据集。
- Iterative retrieval：过滤前 Retry Trigger Rate 0.0571，过滤后为 0；Unnecessary Retry Rate 从阶段 6 的 1.0000 降为 0；Loop/Safety/Out-of-scope Regression 均为 0。

Shadow Plan Valid 的 100% 只表示计划结构、预算和循环约束有效，不代表最终问答准确率。

## 风险与边界

- 当前资料范围集中于 S7-1200 / Modbus，不能直接外推到其他厂商或未知版本。
- 系统不连接 PLC，不执行下载、在线写寄存器、强制输出或旁路安全联锁。
- Formal 数据集包含 60 题，但官方资料占比仅 6%，独立复核题数为 20，尚不能宣传生产级准确率。
- Ranking-only 指标只评价人工 gold 是否进入 Top5 及其排序，不评价答案事实完整性。
- 旧 hash `e251df9e...` 对应的 formal/ranking 结果必须标记为 stale/historical；当前 `reports/formal_evaluation.*` 已由 `formal_eval_v1` 当前 hash 的 test split 重跑生成。
- Required Fact Coverage 是规则型 coverage，不是最终回答准确率；从 `required_facts` 提取的技术标识必须标记 `derived from required_facts`。
- 只有至少两个必要 gold evidence 的多跳题才计算 multi-hop evidence coverage，其余为 `null`。
- Shadow eval 不调用检索、工具或 LLM，不是端到端问答评测。
- Iterative development 集校准后没有触发真实二次检索，证明了误触发减少，但仍需补充 retry-positive 数据验证召回收益。
- SQLite 工具记录如果不能映射到可靠 `source/page/chunk_id`，只能作为候选信息，不能伪装成可引用事实。
- SSE 当前提供工作流阶段事件，不提供逐 token 输出；客户端断开不能强制终止已经进入底层线程的同步 I/O。
- PostgreSQL 是可选运行数据 backend；完整 Trace 仍依赖本地 JSONL，尚不适合无共享文件系统的多实例部署。
- 延迟来自本地 Windows 环境，会随硬件、缓存、模型和 Qdrant 状态变化。

## 项目结构

```text
autoops-rag/
├─ app/
│  ├─ agent/          # LangGraph、intent、planner、tools、iterative controller
│  ├─ ingestion/      # PDF 与表格解析、切片
│  ├─ retrieval/      # Dense、BM25、RRF、Rerank
│  ├─ generation/     # 模型调用、fallback、Citation Guard
│  ├─ mcp/            # 本地 stdio MCP 协议适配层
│  ├─ repositories/   # 运行数据接口与 SQLAlchemy SQLite/PostgreSQL 实现
│  ├─ api.py          # FastAPI 接口
│  ├─ metrics.py      # 进程内运行指标、rolling window 与 Prometheus exposition
│  ├─ service.py      # 服务编排
│  └─ tracing.py      # Trace 脱敏与持久化
├─ data/eval/         # Formal 与 Agentic overlay 数据
├─ docs/              # 架构、评测、Trace 和面试材料
├─ frontend/          # React + TypeScript + Vite Workflow Demo
├─ alembic/           # 运行型表 schema migration
├─ docker-compose.postgres.yml # 可选 PostgreSQL override
├─ reports/           # 审计与评测报告
├─ examples/          # 本地 MCP Client 示例
├─ scripts/           # 初始化、启动、索引和评测脚本
└─ tests/             # 单元、回归和安全测试
```

## 相关文档

- `docs/architecture.md`：系统架构与数据流
- `docs/terminology.md`：容易混淆的项目术语与实现状态说明
- `docs/eval-summary.md`：当前指标和口径
- `docs/trace-example.md`：可读 Trace 示例
- `docs/interview-notes.md`：面试讲解边界
- `reports/resume_materials.md`：简历与面试材料
- `docs/evaluation.md`：评测方法细节
- `docs/iterative-retrieval.md`：有界迭代检索说明

## License

项目代码采用 MIT License。Siemens 手册和其他第三方资料的权利归原权利方所有，不随本仓库重新分发；使用者需自行确认资料来源和许可。
