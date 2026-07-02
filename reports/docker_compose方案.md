# AutoOps RAG Docker Compose 方案

> 本报告只分析容器化方案。本轮未修改业务代码、评测数据、README，也未新增 Dockerfile、`docker-compose.yml` 或 `.dockerignore`。

## 1. 当前启动方式

### 1.1 FastAPI 入口

应用入口为：

```text
app.main:app
```

`app/main.py` 只从 `app.api` 导出 FastAPI 实例：

```python
from app.api import app
```

当前 Web 页面、中文接口页和 Swagger 分别位于：

```text
/
/docs
/swagger
```

### 1.2 Uvicorn 命令

本机前台脚本 `scripts/start.ps1` 和后台脚本 `scripts/start_background.ps1` 最终执行：

```powershell
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

容器中必须改为监听所有容器网卡：

```text
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
```

仅设置 `APP_HOST=0.0.0.0` 不会自动改变显式 uvicorn 参数，因此 Dockerfile/Compose command 仍需写 `--host 0.0.0.0`。

初期建议只运行 1 个 uvicorn worker。Qdrant Server 可以支持多进程，但项目仍使用本地 SQLite 保存会话、反馈和已验证方案，多 worker 需要另行验证 SQLite 写并发与进程内限流行为。

### 1.3 依赖安装

完整环境：

```text
pip install -r requirements.txt
```

包含 FastAPI、Uvicorn、qdrant-client、FastEmbed、PyMuPDF、jieba、rank-bm25、LangGraph、httpx、NumPy 和 Pytest。

最小环境：

```text
pip install -r requirements-minimal.txt
```

最小环境不安装 FastEmbed，配合 `EMBEDDING_BACKEND=hash` 运行，适合功能演示，不应使用其指标代表完整检索效果。

Docker 默认建议安装 `requirements.txt`，保持与当前 FastEmbed 运行方式一致。如果目标只是 CI 或无模型下载的离线演示，可以另建 minimal target，但不应在第一版 Compose 中同时维护两套复杂构建。

### 1.4 `.env.example` 环境变量

当前变量可以分成五组。

#### App

```text
APP_HOST
APP_PORT
MAX_CONCURRENT_QUERIES
REQUEST_TIMEOUT_SECONDS
RATE_LIMIT_PER_MINUTE
```

#### Embedding / Reranker

```text
EMBEDDING_BACKEND
EMBEDDING_MODEL
EMBEDDING_DIM
ENABLE_RERANKER
RERANKER_MODEL
ENABLE_QUERY_EXPANSION
```

#### Ingestion

```text
ENABLE_TABLE_EXTRACTION
CHUNK_SIZE
CHUNK_OVERLAP
```

#### Qdrant

```text
QDRANT_COLLECTION
QDRANT_URL
QDRANT_API_KEY
```

#### LLM

```text
LLM_ENABLED
LLM_BASE_URL
LLM_API_KEY
MODEL_NAME
MODEL_FALLBACKS
LLM_TIMEOUT_SECONDS
```

Compose 中应通过 `env_file: .env` 注入这些值，同时用 `environment` 覆盖容器网络相关变量：

```text
APP_HOST=0.0.0.0
APP_PORT=8000
QDRANT_URL=http://qdrant:6333
```

`QDRANT_URL` 不能写 `http://127.0.0.1:6333`，因为 app 容器中的 localhost 指向 app 自己，不是 qdrant 容器。

## 2. 当前 Qdrant 使用方式

### 2.1 Embedded / local 模式

当前 `.env.example` 默认：

```text
QDRANT_URL=
```

当 `QDRANT_URL` 为空时，`VectorStore` 使用：

```python
QdrantClient(path=str(settings.qdrant_path))
```

本地路径为：

```text
D:\autoops-rag\storage\qdrant
```

对应代码路径是项目根目录下的：

```text
storage/qdrant
```

这种方式适合当前 Windows 单机、单 Python 进程运行，不需要单独安装 Qdrant Server。

### 2.2 Server 模式

当 `QDRANT_URL` 非空时，项目使用：

```python
QdrantClient(
    url=settings.qdrant_url,
    api_key=settings.qdrant_api_key or None,
    timeout=settings.request_timeout_seconds,
)
```

因此业务代码已经具备切换到 Qdrant Server 的能力。Compose 只需设置：

```text
QDRANT_URL=http://qdrant:6333
```

无需改动检索、排序、Prompt 或 API。

### 2.3 是否应切换到 Qdrant Server

结论分场景：

| 场景 | 推荐方式 |
|---|---|
| 当前 Windows 单进程开发 | Embedded Qdrant，简单、依赖少 |
| Docker Compose | Qdrant Server |
| App 多进程或多副本 | Qdrant Server |
| 单次 pytest / 小型本地实验 | Embedded Qdrant |

Compose 中 app、索引初始化和 Qdrant 是不同进程。若多个容器同时把同一宿主目录作为 embedded storage 打开，会产生文件锁冲突甚至存储损坏风险。Qdrant Server 将存储所有权收敛到一个服务，是更合适的容器拓扑。

不要把现有 `storage/qdrant` 目录直接挂到 Qdrant Server 的 `/qdrant/storage`。Embedded local 数据格式和 Server 容器存储应视为两套实例，首次迁移应通过 `scripts/ingest.py` 重新建立 collection。

## 3. Docker Compose 设计

### 3.1 运行服务

推荐两个长期运行服务，加一个一次性初始化服务：

```text
qdrant       长期运行，保存向量 collection
index-init   一次性任务，缺少 collection 时执行 ingestion
app          长期运行，提供 FastAPI 和静态页面
```

`index-init` 与 `app` 使用同一个 app image。它不是第三套业务服务，只是首次启动的索引准备任务。

依赖关系：

```text
qdrant healthy
    ↓
index-init completed successfully
    ↓
app starts
```

Compose v2 可以使用 `depends_on.condition`：

- `qdrant`: `service_healthy`
- `index-init`: `service_completed_successfully`

### 3.2 App 服务

建议配置：

```yaml
app:
  build: .
  command: python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
  env_file:
    - .env
  environment:
    APP_HOST: 0.0.0.0
    APP_PORT: 8000
    QDRANT_URL: http://qdrant:6333
  ports:
    - "127.0.0.1:8000:8000"
```

首版只绑定到宿主机 `127.0.0.1`，避免局域网默认暴露。若确实需要局域网访问，再显式改为 `8000:8000` 并增加认证、反向代理和访问控制。

App 需要访问：

- `data/processed/chunks.jsonl`：BM25 和 chunk metadata。
- `data/seed/*.json`：故障码、参数和轻量知识关系。
- `storage/autoops.db`：SQLite 会话、反馈和已验证方案。
- `models/`：FastEmbed / reranker 缓存。
- `reports/`：RAG Trace 和运行报告。

### 3.3 Qdrant 服务

建议固定到与 `qdrant-client==1.14.3` 兼容、经过验证的 Qdrant 1.14.x 镜像标签，不要直接使用 `latest`。实际实现前需要确认官方镜像中可用的准确 tag。

概念配置：

```yaml
qdrant:
  image: qdrant/qdrant:<verified-1.14.x-tag>
  volumes:
    - qdrant_data:/qdrant/storage
  ports:
    - "127.0.0.1:6333:6333"
```

App 通过 Compose 内部网络访问 `qdrant:6333`。宿主机 6333 端口仅用于本地调试，可以在最小安全配置中不暴露；只暴露 App 的 8000 端口也能正常运行。

Qdrant 的 6334 gRPC 端口当前项目没有使用，不必对宿主机暴露。若后续客户端启用 gRPC，再单独增加。

### 3.4 Index init 服务

现有 `scripts/ingest.py --mode semantic` 会以 `rebuild=True` 重建 collection。不能在每次 app 重启时无条件执行，否则启动会重复解析资料、计算 embedding 并重建索引。

推荐 `index-init` 行为：

1. 等待 Qdrant health check 通过。
2. 查询 `QDRANT_COLLECTION` 是否存在且 point count 大于 0。
3. 同时确认 `/app/data/processed/chunks.jsonl` 存在。
4. 两者均有效时直接退出 0。
5. collection 或 chunks 缺失时才执行：

```text
python scripts/ingest.py --mode semantic
```

第一版可把这个检查写在 Compose 的一次性 command 中，不改业务代码。若 command 过长，再在后续增加一个部署脚本；不要把检查塞进 FastAPI import 或每次请求路径。

现有 `scripts/reconcile_index.py` 直接使用 embedded `QdrantClient(path=...)`，不适合在 Qdrant Server Compose 中作为初始化检查，除非后续单独改造为同时支持 URL。

### 3.5 Volumes

推荐：

| Volume / mount | 容器路径 | 用途 | 建议 |
|---|---|---|---|
| `qdrant_data` | `/qdrant/storage` | Qdrant Server 数据 | named volume，只有 qdrant 服务挂载 |
| `app_state` | `/app/storage` | SQLite、PID 等 app 状态 | named volume；外部 Qdrant 模式下不保存向量数据 |
| `processed_data` | `/app/data/processed` | chunks、表格缓存 | named volume，index-init 写、app 读 |
| `model_cache` | `/app/models` | embedding/reranker 模型缓存 | named volume，避免每次重建镜像下载 |
| `trace_reports` | `/app/reports` | RAG Trace 和运行报告 | named volume；调试时可改为宿主目录 bind mount |
| `./data/raw` | `/app/data/raw:ro` | 原始 PDF、补充 Markdown、sources manifest | Windows bind mount，只读 |

`data/seed` 建议作为经过审核的小型运行数据复制进 image；如果当前仍不准备提交，可临时只读挂载 `./data/seed:/app/data/seed:ro`，但公开仓库的一键启动会依赖宿主机已有 seed 文件。

Raw 数据不应进入镜像层。镜像上传到 registry 后很难撤回已进入历史层的手册或敏感资料，使用只读运行时挂载更安全。

### 3.6 Ports

最小端口方案：

| 服务 | 容器端口 | 宿主机端口 | 是否必须暴露 |
|---|---:|---:|---|
| app | 8000 | `127.0.0.1:8000` | 是 |
| qdrant REST | 6333 | `127.0.0.1:6333` | 否，仅本地调试需要 |
| qdrant gRPC | 6334 | 不暴露 | 否，当前未使用 |

App 与 Qdrant 通过 Compose 默认内部网络通信，不需要把 6333 暴露到公网。

### 3.7 `env_file`

Compose 使用：

```yaml
env_file:
  - .env
```

注意：

- `.env` 只在运行时由 Compose 读取，不通过 `COPY` 放进镜像。
- `.env` 必须继续被 Git 忽略。
- `docker inspect` 仍可能看到普通环境变量。对于共享服务器，应改用 Docker secrets 或外部 secret manager；本地开发阶段可先使用 `env_file`。
- Compose 文件只写变量名或无敏感默认值，不写真实 API Key。
- `QDRANT_API_KEY` 在仅本机内部网络的最小方案中可以为空；如果 Qdrant 端口对外暴露，需要再设计认证。

## 4. 一键启动与初始化边界

目标命令：

```text
docker compose up --build
```

为了让这个命令第一次和后续都安全，`index-init` 必须是“缺失才建”，不能每次无条件 rebuild。

推荐状态判断：

| processed chunks | Qdrant collection | 行为 |
|---|---|---|
| 不存在 | 不存在 | 从 raw 解析、切分并入库 |
| 存在 | 不存在 | 使用 chunks 或重新 ingestion 建立 Qdrant；具体方案需保证 embedding 配置一致 |
| 不存在 | 存在 | 判为不一致，不启动 app；提示重新初始化两个 volume |
| 存在 | 存在且 count > 0 | 跳过初始化，启动 app |

如果 embedding backend、dimension、chunk 参数或 collection 名变化，应显式执行重建命令，而不是静默复用旧 collection。

推荐 README 给出重置方式：

```text
docker compose down
docker compose down -v   # 明确说明：会删除 Qdrant、processed、model cache 和 SQLite 等 named volumes
```

`down -v` 是破坏性操作，不能放在普通停止命令中。

## 5. 风险分析

### 5.1 Windows 路径

当前 PowerShell 脚本硬编码 `D:\autoops-rag`，不能直接在 Linux 容器中运行。Compose 应使用容器路径 `/app`，并直接执行 Python/Uvicorn 命令，不调用 `start.ps1`、`start_background.ps1` 或 `setup_d_drive.ps1`。

宿主 bind mount 使用相对路径：

```yaml
volumes:
  - ./data/raw:/app/data/raw:ro
```

这样从 `D:\autoops-rag` 执行 Compose 时由 Docker Desktop 解析路径。需要确认 D 盘已允许 Docker Desktop 文件共享。中文文件名、长路径、CRLF shell 脚本和 NTFS 权限也应在实际实现时验证。

### 5.2 Embedded Qdrant 多进程占用

- Embedded storage 只能由一个 owner 稳定访问。
- 不要让 app、index-init 和另一个维护容器同时以 `QdrantClient(path=...)` 打开同一目录。
- 不要把宿主 `storage/qdrant` 同时挂载给 app 和 qdrant server。
- Compose 使用 Qdrant Server 后，所有容器只通过 HTTP 访问 qdrant 服务。

### 5.3 API Key 进入镜像

- Dockerfile 不得 `COPY .env`。
- 不使用 `ARG LLM_API_KEY`；build arg 也可能留在构建记录中。
- `.dockerignore` 必须排除 `.env`、`.env.*` 和可能的密钥文件。
- 构建日志、测试输出和 image label 不得打印密钥。
- Runtime Trace 已有脱敏，但容器日志和异常堆栈仍需检查。

### 5.4 Raw 数据

- 原始 PDF 不复制进镜像。
- 通过宿主只读 bind mount 或受控数据 volume 提供。
- 公开镜像不能包含受版权保护手册。
- 项目补充 Markdown 和 `sources.json` 是否复制进 image，应先确认来源、许可和是否包含私有经验。
- 没有 raw 数据且 Qdrant/processed volumes 也是空时，一键初始化无法完成，应该输出明确错误而不是启动一个空壳页面。

### 5.5 索引一致性

- BM25 读取 `/app/data/processed/chunks.jsonl`，Qdrant Server 保存 dense vectors；二者必须来自同一次切分和 embedding 配置。
- 只恢复 Qdrant volume、不恢复 processed volume，或反过来，都会造成稀疏/稠密索引不一致。
- changing `EMBEDDING_DIM`、`EMBEDDING_MODEL`、`CHUNK_SIZE`、`CHUNK_OVERLAP`、表格抽取配置后应完整重建。

### 5.6 首次模型下载

- FastEmbed/reranker 首次启动可能下载较大模型，耗时和网络失败会影响 init service。
- `model_cache` 应持久化。
- 不建议把模型权重打入应用镜像，镜像会过大且更新困难。
- 如需离线部署，应另行准备可审计的模型缓存分发方案。

### 5.7 SQLite 和容器副本

- `storage/autoops.db` 保存会话、反馈和已验证方案。
- 首版只运行一个 app replica。
- 多副本共享一个 SQLite 文件不适合作为默认方案；若未来水平扩展，再评估外部数据库，不在 v28 顺手引入 Redis/MySQL。

## 6. 推荐最小实现文件

### 6.1 `Dockerfile`

推荐职责：

1. 使用固定 Python 3.11 slim 基础镜像。
2. 设置 `/app` 为工作目录。
3. 先复制 requirements 并安装依赖，利用构建缓存。
4. 安装 FastEmbed/ONNX 运行所需的最少系统库，例如 `libgomp1`；具体列表以实际构建测试为准。
5. 复制 `app/`、`static/`、必要 scripts 和经审核的 `data/seed/`。
6. 创建 `/app/data/raw`、`/app/data/processed`、`/app/storage`、`/app/models`、`/app/reports`。
7. 使用非 root 用户运行；确保 named volume 挂载目录有写权限。
8. `EXPOSE 8000`。
9. 默认 command 为 uvicorn `app.main:app --host 0.0.0.0 --port 8000`。

Dockerfile 不应运行 ingestion。构建镜像和生成业务索引是两个生命周期，raw 数据也不应进入 image layer。

### 6.2 `docker-compose.yml`

推荐包含：

- `qdrant`：固定版本镜像、health check、`qdrant_data`。
- `index-init`：复用 app image，缺少索引才执行 ingestion，成功后退出。
- `app`：等待 qdrant healthy 和 index-init completed，使用 `.env`，覆盖 `QDRANT_URL`，暴露 8000。
- named volumes：qdrant、processed、app state、model cache、trace reports。
- raw bind mount：只读。
- 默认单 app replica。

### 6.3 `.dockerignore`

至少排除：

```dockerignore
.git
.gitignore
.env
.env.*
.venv
venv
__pycache__
*.py[cod]
.pytest_cache
.cache
.tmp
models
storage
data/raw
data/processed
reports/rag_traces.jsonl
reports/*.json
reports/*.csv
reports/*.log
reports/*.err.log
reports/*.out.log
```

如果 Docker build 不在镜像内运行测试，还可以排除：

```dockerignore
tests
docs
reports
data/eval
```

但 `data/seed` 不能在计划复制进镜像时被排除。

特别要求：使用外部 Qdrant Server 时，`storage/qdrant` 必须排除；推荐直接排除整个 `storage`，运行时通过 `app_state` volume 创建 SQLite。

### 6.4 README 补充

README 需要增加“Docker Compose 启动”小节，包含：

1. Docker Desktop / Docker Compose v2 要求。
2. `Copy-Item .env.example .env`，并说明真实密钥不提交。
3. raw 数据准备方式和版权说明。
4. 一键启动命令：`docker compose up --build`。
5. 页面地址：`http://127.0.0.1:8000`。
6. 查看状态：`docker compose ps`、`docker compose logs -f app`。
7. 普通停止：`docker compose down`。
8. 显式重建索引/清理 volume 的命令和数据丢失警告。
9. Compose 使用 Qdrant Server，而原生 PowerShell 默认仍可使用 embedded Qdrant。
10. 不在默认启动时运行 full formal eval，避免外部模型额度消耗。

## 7. 不应复制进镜像的文件

| 路径 | 原因 |
|---|---|
| `.env` | 含 LLM/API 凭据 |
| `.venv/` | 宿主 Windows 虚拟环境与 Linux image 不兼容，且体积大 |
| `__pycache__/`, `*.pyc` | 宿主解释器缓存，无复现价值 |
| `.git/` | 包含完整历史、分支和可能已删除的敏感内容 |
| `data/raw/` | 原始手册体积和版权风险，应运行时只读挂载 |
| `data/processed/` | 派生 chunks 与表格缓存，应由 init service 写入 volume |
| `models/` | 模型缓存体积大，应通过 named volume 持久化 |
| `storage/` | 宿主 SQLite、PID 和 embedded Qdrant 数据，不可直接复制 |
| `storage/qdrant/` | 使用外部 Qdrant Server 后不能复用 embedded storage |
| `reports/rag_traces.jsonl` | 可能包含真实问题和证据正文 |
| 服务日志、评测原始 JSON/CSV | 运行产物，可能含路径或请求内容 |

`.env.example` 可以保留在仓库供用户复制，但不需要进入运行镜像。

## 8. 推荐实施顺序

实际进入 v28 实现时建议分四步：

1. **镜像可启动**：完成 Dockerfile 和 `.dockerignore`，使用 hash embedding 做快速构建验证。
2. **Qdrant Server 连通**：Compose 启动 qdrant 与 app，确认 `QDRANT_URL=http://qdrant:6333`、health 和空索引状态。
3. **初始化与持久化**：增加 conditional index-init，挂载 raw/processed/model/qdrant/app-state volumes，验证第二次 `up` 不重建索引。
4. **完整能力验证**：切到 FastEmbed，验证首页、search、chat、Trace、fallback、重启持久化和 53 个 pytest；formal eval 只做结构校验，不默认调用外部 LLM。

每一步都应检查镜像层和日志中没有 `.env`、API Key、raw PDF 或宿主 `storage/qdrant`。

## 9. 验收建议

未来 Compose 实现至少验证：

```text
docker compose config
docker compose build
docker compose up
GET /health -> 200
POST /api/search -> 返回真实 evidence
POST /api/chat -> 返回 answer/runtime/rag_trace
docker compose restart app -> Qdrant point count 不变
docker compose down && docker compose up -> SQLite/Qdrant/processed 数据仍存在
```

还应验证：

- 第二次启动不重复 ingestion。
- app 容器不挂载 `qdrant_data`。
- index-init 不使用 embedded `storage/qdrant`。
- image history 不包含密钥。
- raw mount 缺失时给出明确失败原因。
- Qdrant 未就绪时 app 不抢先启动。
- `docker compose down -v` 的破坏性影响在 README 中明确说明。

## 10. 结论

- 当前项目原生运行默认使用 embedded Qdrant，路径为 `storage/qdrant`，适合 Windows 单进程开发。
- Docker Compose 更适合使用 Qdrant Server。代码已经通过 `QDRANT_URL` 支持，不需要修改检索业务逻辑。
- 最小运行拓扑是两个长期服务（app、qdrant）加一个条件式一次性 index-init。
- App 暴露 8000；Qdrant 6333 只在需要宿主调试时绑定，6334 当前不需要。
- 原始 PDF、宿主 embedded storage、模型缓存和 `.env` 都不进入镜像，分别通过只读 bind mount、named volumes 和 runtime env 提供。
- 真正的一键启动关键不是写出 Compose YAML，而是保证首次缺索引时能初始化、后续启动不会无条件重建，并确保 Qdrant 与 processed chunks 保持一致。

