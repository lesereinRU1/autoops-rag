# 当前事实与验证状态

> 这是项目公开文档中“当前状态”的唯一人工可读事实源。评测的机器可读事实源仍是 `reports/formal_evaluation.json`。其他使用不同 dataset hash、corpus 数量、测试数量或 Stage G 前 Planner 口径的材料均属于 **Historical / stale / 历史版本结果**。

## 当前版本与实现边界

- 应用与 API 版本：`4.1.0`
- 默认路径：固定、可审计的 LangGraph 工作流
- 可选受控执行：`ENABLE_AGENTIC_ROUTING=true` 时，确定性 `BoundedQueryPlanner` 只对适用 intent 执行 Registry 白名单计划
- Planner 不是 LLM Planner，不是完全自主 Agent，也不是 Multi-Agent
- MCP：本地 stdio Server，共享同一 `ToolRegistry`
- Web：React + TypeScript Demo 使用 workflow-level SSE；最终回答在 `completed` 事件一次性返回，不是 Token Streaming
- 运行数据：默认 SQLite，可选 PostgreSQL；Qdrant 与静态领域数据不强制迁移
- Metrics：单进程内存指标，P50/P95/P99 使用最近最多 1000 个样本的滚动窗口

## 当前 processed corpus

以下数量来自本轮使用的 `data/processed/chunks.jsonl`：

| 项目 | 当前值 |
|---|---:|
| 文档 | 6 |
| chunks | 16,945 |
| 正文 chunks | 4,934 |
| 表格行 chunks | 12,011 |
| 结构化表格 | 1,856 |
| 覆盖表格页 | 1,064 |
| corpus SHA-256 | `090f5e5f416ea1762d4f71e7a28b10d0e7f083ef30ae04f3a305c1b6b769a213` |

原始手册、`chunks.jsonl`、Qdrant 数据和数据库不随 Git 仓库分发。该 hash 用于固定本次 canonical evaluation 的 corpus 身份，不表示 GitHub clone 后自动包含该数据。

## 最近一次真实自动化验证

| 项目 | 结果 | 说明 |
|---|---|---|
| Pytest | `206 passed, 1 skipped` | skip 为未设置 `AUTOOPS_POSTGRES_TEST_DSN` 的 PostgreSQL integration test |
| Formal test requests | `20/20` 完成 | 当前 `formal_eval_v1` test split |
| Gold resolution | formal `11/11`、test `8/8` | 对当前 processed corpus 可解析 |

阶段 D 已单独完成过真实 PostgreSQL validation；上表的当前默认 Pytest 没有设置专用 PostgreSQL 测试 DSN，因此不能把该次默认运行写成新的 PostgreSQL 全量验证。

## 当前 canonical formal evaluation

- Dataset：`formal_eval_v1`
- Dataset SHA-256：`3b33876cd584e6215ef03a8bb07d0566aa57371957e606196c37b6f26641a4d9`
- Split：`test`
- Cases：20
- Canonical report：`reports/formal_evaluation.json` 与 `reports/formal_evaluation.md`
- Generation mode：`local_extractive`
- `LLM_ENABLED=false`
- LLM-as-a-judge：关闭

本轮 End-to-End 指标衡量本地抽取式回答和规则型校验结果，不是外部 LLM Answer Quality，也不能称为生产准确率。

### Retrieval Evaluation

| 指标 | 当前值 | 分母/含义 |
|---|---:|---|
| Strict Recall@5 | 0.8667 | 15 道可回答题；Top 5 必须覆盖全部必要 gold chunks |
| MRR@5 | 1.0000 | 15 道可回答题；首个 gold 的倒数排名 |
| nDCG@5 | 0.9028 | 15 道可回答题；多个 gold 的排序质量 |
| Top1 Accuracy | 1.0000 | 15 道可回答题；第一条是否属于任一 gold |

### End-to-End Rule Evaluation

| 指标 | 当前值 | 分母/准确含义 |
|---|---:|---|
| Citation Correctness | 0.9286 | 14 个实际回答；引用是否映射到本次 Evidence |
| Required Fact Coverage | 0.3929 | 112 条 required facts 的规则型 coverage，不是最终回答准确率 |
| Technical Identifier Accuracy | 0.6316 | 76 个标识；`derived from required_facts`，不是人工结构化 gold field |
| Refusal Accuracy | 0.9500 | 20 题的应回答/应拒答决策 |
| False Accept Rate | 0.0000 | 应拒答却回答 |
| False Reject Rate | 0.0667 | 应回答却拒答 |
| Multi-hop Evidence Coverage | 1.0000 | 仅 4 个存在多个必要 gold evidence 的适用样本 |
| Claim Support Rate | `null` | 未包装成完整 Answer Faithfulness |

Retrieval Recall 不等于最终回答准确率。参数、表格、越界、Safety 和无答案类别样本均少于 3 题，只用于诊断，不代表稳定统计结论。官方来源可回答题只有 3 道，占 6%，因此 `ready_for_resume_accuracy_claim=false`。

## 历史材料规则

出现以下任一情况的报告或截图必须标记为 **Historical / stale / 历史版本结果**：

- dataset hash 为 `e251df9e...` 或其他非当前 hash；
- corpus 为 16,969 / 12,035 / 1,861；
- Pytest 为 53、104、180 或 196；
- 把 Planner/Router 描述为只能 shadow、不能真实执行；
- 把旧 `claim_support_rate` 包装为完整 Answer Faithfulness；
- 使用 Stage G 前已移除的 Agent 工具期望，例如 `lookup_table_rows`。

历史结果可以用于解释演进过程，但不能与当前 canonical formal evaluation 混用。
