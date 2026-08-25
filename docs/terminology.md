# 项目术语对照表

这张表只解释项目里容易混淆的概念。RAG、Agent、MCP、LLM、API、SSE、Trace、BM25、RRF、Rerank、Docker 等行业通用词保持英文；代码类名、函数名、字段名、接口名和环境变量也保持原样。

| 文档中的说法 | 英文术语或代码对应 | 简单解释 |
|---|---|---|
| 证据充分性判断 | Evidence Gate | 在生成回答前判断当前证据是否足够；不足时只能有限改写、停止或返回保守结果。 |
| 引用校验 | Citation Guard | 检查回答里的来源编号是否属于本次检索证据；它不等于逐句事实审核。 |
| 工具注册中心 | Tool Registry / `ToolRegistry` | 四个正式工具的统一入口，集中处理参数校验、预算、超时、Trace 和指标结算。 |
| 数据访问层 | Repository | 把业务代码与 SQLite/PostgreSQL 读写细节隔开，例如 `ConversationRepository`。 |
| 问题改写 | Query Rewrite | 证据不足时生成补充检索语句；当前流程有次数限制，不是开放循环。 |
| 降级机制 | fallback | 主模型不可用或校验失败时，切换备用模型或本地证据摘要。 |
| 运行指标采集器 | `MetricsCollector` | 在当前进程内汇总请求、RAG、LLM、工具和延迟数据，不保存完整用户请求。 |
| 影子模式 | shadow | 生成并记录候选决策，但不接管真实执行路径。 |
| 工作流级 SSE | workflow event streaming | 推送 `retrieving`、`generating` 等阶段事件，最终答案仍一次性返回。 |
| 响应可用耗时 | `first_token_latency_ms` | 当前 LLM 非 Token Streaming，所以该字段不代表真实 TTFT。 |
| 工具调用记录 | `ToolCallTrace` | 记录工具名、参数、耗时、结果数、成功/失败和是否实际执行。 |
| 运行型数据 | Runtime Repository data | 会话、反馈、人工确认方案、Trace metadata 和评测记录；不包含 Qdrant 向量或原始手册。 |

## 实现状态词

- **已真实实现**：默认运行路径会实际执行并产生结果。
- **shadow / experimental**：只记录候选决策，或必须显式开启且受预算约束。
- **尚未实现**：仓库当前没有对应的可运行能力，文档不能把它写成现有功能。
