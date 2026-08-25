# AutoOps RAG

基于 LangGraph 的轻量级 Agentic RAG 工业知识库系统，面向 Siemens S7-1200 与 Modbus 技术资料，提供可追溯的手册检索、参数查询和故障辅助分析。

当前应用与 API 版本为 `4.1.0`。

它不是完全自主 Agent：Intent Classifier、Tool Router 和 Bounded Query Planner 当前主要以 shadow 方式记录候选决策；Evidence-driven Iterative Retrieval 受开关和预算约束，默认关闭。真实主流程仍由固定、可审计的 LangGraph 状态机控制。

## 项目简介

工业手册篇幅长、表格多，故障码、参数名、版本和操作流程散落在不同章节。纯向量检索容易漏掉 `16#80C8`、`MB_CLIENT`、`Unit ID` 等精确标识，直接把检索结果交给大模型又可能产生无来源补充。

AutoOps RAG 将文档解析、混合检索、证据判断、生成、引用校验和 Trace 拆成显式节点：先确认范围和安全边界，再检索证据；证据不足时只执行有界改写，引用异常时降级到本地证据摘要。

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
| Hybrid Retrieval | Qdrant Dense Retrieval + BM25，使用 RRF 融合和轻量重排 |
| 可控工作流 | LangGraph 显式编排安全门控、结构化查询、检索、Evidence Gate、Rewrite、生成和 Citation Guard |
| 证据约束 | Evidence Gate 检查证据数量、相关度和技术标识符覆盖；证据不足时不允许模型自由补全 |
| 引用校验 | Citation Guard 校验回答引用是否来自本次 evidence，失败时降级为本地证据摘要 |
| 工具封装 | LangGraph 固定路由通过统一 Tool Registry 执行 `search_manual`、`lookup_fault_code`、`lookup_parameter` 和 `get_document_page`，统一校验参数、结果、Trace、预算与超时 |
| 本地 MCP | stdio MCP Server 暴露同一组四个工具，直接复用 Tool Registry 和 Service，不经过 FastAPI HTTP 接口 |
| Agentic Shadow | 规则式 Intent Classifier、Tool Router 和 Bounded Planner 生成候选计划，仅写入 Trace |
| 有界迭代检索 | 可选二次检索，受轮数、Rewrite、工具、LLM 和超时预算控制；默认关闭 |
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
    SAFE -->|"accepted"| SHADOW["Intent + Router + Planner (Shadow)"]
    SHADOW --> FIXED["Fixed Routing"]
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

1. FastAPI 接收问题并生成 `request_id`。
2. Service 处理会话上下文，调用 LangGraph。
3. Scope/Safety Gate 在检索和模型调用前短路危险请求、越界型号和资料不足的版本问题。
4. Shadow 层生成 intent、candidate plan 和 bounded structured plan，但不替代真实路由。
5. 固定路由通过 Tool Registry 执行结构化查询；`retrieve` 节点通过同一 Registry 执行一次 `search_manual`，进入 Dense + BM25 + RRF + rerank 检索。
6. Evidence Gate 判断证据是否足够，并记录原始缺失词、过滤后标识符和被忽略泛词。
7. 默认路径保留原有单次 Query Rewrite；实验性迭代检索只有在显式开启且预算允许时才补充一轮证据。
8. 证据充分时执行 grounded generation；模型不可用时按 fallback 链降级。
9. Citation Guard 校验引用，输出回答、证据、运行统计和完整 Trace。

## Agentic RAG 扩展能力

- `IntentClassifier`：规则式识别故障诊断、参数、表格、跨章节流程、版本、安全和越界意图，不调用 LLM。
- `ToolRouter`：为 intent 生成白名单候选工具序列；候选序列仅进入 shadow Trace，不决定当前真实路由。
- `BoundedQueryPlanner`：最多生成 3 个白名单候选步骤，带 `max_rounds`、`max_tool_calls` 和 `applied=false`；当前不执行这些步骤。
- `ToolRegistry`：注册四个带独立 Pydantic 输入模型的核心工具，统一处理参数校验、未知工具、`max_tool_calls`、单工具 timeout、异常和 ToolCallTrace。
- `SQLiteToolbox`：作为 Registry 中故障码和参数工具的底层实现，以统一 `ToolResult` 返回结构化 data、证据、provenance、耗时和错误。工具结果不能在没有可靠来源时直接成为最终事实。
- `DocumentPageService`：优先按已处理 chunk 的文档与页码定位证据，必要时只打开精确匹配 PDF 的指定页，不扫描整份 PDF。
- Iterative Retrieval：只在证据不足、存在有效技术标识符且预算允许时重试；`0`、`PLC`、手册、参数等泛词不能单独触发重试。

这些能力构成“轻量级 Agentic RAG”：系统能够分析意图、形成受约束计划、选择候选工具、评估证据并决定是否停止，但不允许开放式工具生成或无限循环。

## 为什么不是 naive RAG

naive RAG 通常是“一次向量检索 → 拼接 TopK → LLM 回答”。本项目额外处理了：

- 精确术语与自然语言并存，因此使用 Dense + BM25 + RRF；
- 表格行与表头容易分离，因此构建带表格元数据的行级切片；
- 证据可能不足，因此在生成前设置 Evidence Gate；
- 引用可能越界，因此生成后设置 Citation Guard；
- 工业请求存在安全和版本边界，因此安全检查位于检索和 LLM 之前；
- Agent 决策需要可解释，因此 shadow plan、budget、stop reason 和检索轮次全部进入 Trace。

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

Safety Gate 拒绝路径会跳过工具和检索，异常路径以 `error` 结束。每个事件包含 `event`、`request_id`、`timestamp`、`stage`、`message` 和经过脱敏的 `data`；`completed.data.response` 是与 `/api/chat` 相同的完整 `ChatResponse`。页面基于该响应展示 Answer、可展开 Citation、Evidence 和 Trace，包括工具调用、改写、检索轮次、停止原因、延迟、模型/provider 表示及可用的 token usage。

当前是 workflow event streaming，不是 token-by-token streaming：LLM Client 仍使用非流式请求，最终回答随 `completed` 事件一次性返回。页面的“停止接收”使用浏览器 AbortController，只停止前端等待和连接；后端会尽快停止等待，但正在执行的同步检索或模型 I/O 可能短暂继续。Planner/Router 仍为 shadow；本地 MCP 继续作为独立 stdio 入口，不经 SSE。

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

当前边界：只实现本地 stdio transport，没有远程 HTTP MCP、认证、TLS 或多租户隔离；`get_document_page` 仍受现有精确文档匹配和页码约束，不能读取任意文件。Planner/Router 仍为 shadow，LangGraph 直接调用 Tool Registry，不通过 MCP 回调自身。因此系统仍不是 fully autonomous Agent，也不代表生产级远程 MCP 部署。

## Runtime Repository 与 PostgreSQL

阶段 D 只抽象运行型数据，不把整个项目强制迁到 PostgreSQL：

| 存储 | 当前职责 |
|---|---|
| Qdrant | Dense 向量检索；不迁 pgvector |
| SQLite 静态知识 | `alarm_codes`、`parameters`、`kg_nodes`、`kg_edges` 和可选手册表格行 |
| Runtime Repository | `conversation_memory`、`conversation_turns`、`answer_feedback`、`verified_solutions`、`solution_reuse_events`、`trace_metadata`、`evaluation_runs`、`evaluation_records` |
| JSONL / Markdown | 完整脱敏 RAG Trace 和离线评测报告，继续保留 |

运行数据由 `ConversationRepository`、`FeedbackRepository`、`VerifiedSolutionRepository`、`TraceRepository` 和 `EvaluationRepository` 分责；SQLAlchemy 实现使用短生命周期 Session，每次事务结束都会 commit 或 rollback 并关闭 Session。Service 和 Graph 不直接持有 ORM Session，也不写 SQL。

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

Trace 采用“数据库 metadata + JSONL 完整 payload”：Repository 保存 `request_id`、时间、`session_id`、状态、错误、query/rewrite、工具、模型、延迟、token usage 和 stop reason；完整 retrieval candidates/evidence 继续写脱敏 JSONL。Formal evaluation 仍生成原 JSON/Markdown，同时写 evaluation run/record metadata，不改变指标口径。

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

因此默认 API 不会让 Agentic Router、Planner 或 Iterative Retrieval 接管主流程。即使启用 Router 或 Planner 的配置开关，当前代码也只产生 shadow trace。固定 Graph 的真实工具调用已受 Registry 的 `max_tool_calls` 和单工具 timeout 约束；其他 Agent budget 字段继续约束迭代检索和生成阶段。

## 当前评测摘要

- Pytest：146 项通过，1 项 PostgreSQL integration test 因未配置专用测试 DSN 而跳过；原有 136 项全部保留并通过。
- Formal validation：60 题，0 validation errors；由于官方资料占比和独立复核数量尚未达到门槛，`ready_for_resume_accuracy_claim=false`。
- Ranking-only development：Strict Recall@5 1.0000、MRR@5 0.9343、nDCG@5 0.9377、Top1 Accuracy 0.8857。
- Agentic shadow：24 个 overlay case，Intent/Tool/Plan Valid 均为 1.0000；Budget/Whitelist/Loop Violation 均为 0。
- Iterative retrieval：过滤前 Retry Trigger Rate 0.0571，过滤后为 0；Unnecessary Retry Rate 从阶段 6 的 1.0000 降为 0；Loop/Safety/Out-of-scope Regression 均为 0。

Shadow 评测的 100% 只表示规则分类和候选计划符合 overlay 预期，不代表最终问答准确率。

## 风险与边界

- 当前资料范围集中于 S7-1200 / Modbus，不能直接外推到其他厂商或未知版本。
- 系统不连接 PLC，不执行下载、在线写寄存器、强制输出或旁路安全联锁。
- Formal 数据集包含 60 题，但官方资料占比仅 6%，独立复核题数为 20，尚不能宣传生产级准确率。
- Ranking-only 指标只评价人工 gold 是否进入 Top5 及其排序，不评价答案事实完整性。
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
│  ├─ retrieval/      # Dense、BM25、RRF、rerank
│  ├─ generation/     # 模型调用、fallback、Citation Guard
│  ├─ mcp/            # 本地 stdio MCP 协议适配层
│  ├─ repositories/   # 运行数据接口与 SQLAlchemy SQLite/PostgreSQL 实现
│  ├─ api.py          # FastAPI 接口
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
- `docs/eval-summary.md`：当前指标和口径
- `docs/trace-example.md`：可读 Trace 示例
- `docs/interview-notes.md`：面试讲解边界
- `reports/resume_materials.md`：简历与面试材料
- `docs/evaluation.md`：评测方法细节
- `docs/iterative-retrieval.md`：有界迭代检索说明

## License

项目代码采用 MIT License。Siemens 手册和其他第三方资料的权利归原权利方所有，不随本仓库重新分发；使用者需自行确认资料来源和许可。
