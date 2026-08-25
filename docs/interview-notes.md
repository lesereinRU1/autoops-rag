# AutoOps RAG 面试讲解笔记

## 项目亮点

1. **问题真实具体：** 工业手册中的精确故障码、参数表、版本和跨章节流程，不是通用聊天场景。
2. **数据处理可量化：** 16,969 个切片、12,035 个表格行、1,861 张表均来自现有审计报告。
3. **检索不是单一路径：** Dense + BM25 + RRF + rerank，同时覆盖语义改写与精确标识。
4. **生成有前后门控：** Evidence Gate 决定是否允许生成，Citation Guard 校验引用是否属于本次证据。
5. **Agentic 但可控：** Intent、Router、Planner、工具和 iterative controller 都有白名单、预算、stop reason 和 Trace。
6. **工程与评测分层：** API、Docker、Pytest、formal validation、ranking-only、shadow 和 iterative eval 各自回答不同问题。

## 可讲的技术难点

### 表格切片

难点不是把 PDF 转文字，而是表头、参数名、数值和版本不能被切散。可以讲如何保留 `table_id`、headers、row index、页码和型号，使表格行既能检索又能回到原文。

### Hybrid Retrieval

说明 Dense 擅长语义，BM25 擅长故障码和参数名，RRF 避免直接比较异构分数。不要只说“用了向量数据库”。

### Evidence Gate 校准

可以用阶段 6/7 的真实实验讲：旧 gate 因 `0`、`PLC` 触发两次无效 Rewrite；加入标识符过滤后，before/after trigger rate 从 5.71% 降为 0，并保持安全与循环回归为 0。重点是“减少误触发”，不是夸成“召回大幅提升”。

### 受控 Planner

解释默认为什么保持固定流程，以及 `ENABLE_AGENTIC_ROUTING=true` 后如何只让确定性 Planner 在 Registry 白名单、统一预算、timeout、去重和 fallback 下执行适用请求。不要把它说成 LLM Planner 或自主 Agent。

### Provenance

ToolResult 区分 content、evidence、provenance 和 metadata。SQLite 命中不等于可引用事实；只有真实来源才能进入答案证据。

## 不要夸大的地方

- 不要把 shadow Plan Valid 100% 当问答准确率；阶段 G 后旧表格工具预期已成为历史口径；
- 不要把 ranking Recall@5 当答案正确率；
- 不要声称 Planner 接管所有请求；它只在 feature flag 开启后处理适用 intent；
- 不要声称 iterative retrieval 已证明正向召回收益；
- 不要声称接入或控制真实 PLC；
- 不要声称企业生产落地或减少停机时间；
- 不要把自动 Citation Guard 说成逐句事实验证；
- 不要忽略 `ready_for_resume_accuracy_claim=false`。

## 推荐说法

- “这是基于 LangGraph 的受控 Agentic RAG，默认走固定流程，开启 feature flag 后只执行确定性白名单计划。”
- “在 35 道 development ranking-only 题上，Strict Recall@5 为 1.0，MRR@5 为 0.9343。”
- “Shadow Plan Valid 的 100% 只表示结构、预算和循环约束有效，不代表最终问答准确率。”
- “Evidence Gate 和 Citation Guard 分别约束生成前证据与生成后引用。”
- “迭代检索默认关闭，开启时有轮数、工具、LLM、Rewrite 和超时预算。”
- “结构化工具没有可靠 provenance 时不能直接作为最终事实。”
- “当前 formal 数据校验无错误，但官方来源占比和独立复核量尚未达到准确率宣传门槛。”

## 避免说法

| 避免说法 | 原因 | 替代说法 |
|---|---|---|
| 问答准确率 100% | 混淆 shadow 与端到端问答 | Shadow plan valid rate 只衡量结构与预算约束 |
| 完全自主 Agent | Planner 不是 LLM Planner，且只处理适用请求 | feature-flagged、受约束的 Agentic RAG |
| 生产级系统 | 无真实生产部署和业务指标 | 完成可复现的本地工程原型与内部评测 |
| 自动诊断 PLC 故障 | 系统只检索资料，不控制设备 | 提供带手册证据的故障辅助分析 |
| Citation 保证答案正确 | 只验证引用映射 | Citation Guard 防止引用本次 evidence 之外的来源 |
| 二次检索提升召回 | 当前过滤后无 retry-positive case | 二次检索框架已实现，当前实验先验证误触发与预算边界 |

## 建议讲解顺序

1. 先讲工业手册的表格、精确术语和安全边界；
2. 再讲文档解析和 Hybrid Retrieval；
3. 用 Evidence Gate / Citation Guard 解释为什么不直接交给 LLM；
4. 用受控 Planner、Registry 白名单、去重和 budget 解释“轻量级 Agentic”；
5. 最后展示 Trace 和三套互相隔离的评测；
6. 主动交代数据规模、readiness 和未完成项。

## 面试现场可画的最小流程

```text
Question
  → Safety Gate
  → Intent / Rule-first Router / Controlled Planner（可选）
  → Structured Tool + Hybrid Retrieval
  → Evidence Gate
  → bounded Rewrite（可选）
  → Grounded Generation
  → Citation Guard
  → Answer + Trace
```
