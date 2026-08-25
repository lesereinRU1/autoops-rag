# 当前评测结果汇总

不同评测回答不同问题，不能合并成一个“项目准确率”。当前项目已把 Retrieval 指标与最终回答质量的规则指标分开；本轮没有启用 LLM-as-a-judge。

## 本轮可复现状态

| 项目 | 当前状态 | 含义 |
|---|---:|---|
| Pytest | 默认环境 180 passed、1 skipped | 跳过项为未配置专用测试 DSN 的 PostgreSQL integration test；本轮未重跑专用 PostgreSQL 环境 |
| Dataset version | `formal_eval_v1` | formal 数据集由 manifest 冻结 |
| Dataset SHA-256 | `3b33876cd584e6215ef03a8bb07d0566aa57371957e606196c37b6f26641a4d9` | test 运行前后 hash 一致 |
| Formal questions | 60 | development 40、test 20；可回答 50、应拒答 10，其中 Safety 4 |
| Processed corpus | 6 个文档、16945 个 chunks | 正文 4934、表格 12011；SHA-256 `090f5e5f416ea1762d4f71e7a28b10d0e7f083ef30ae04f3a305c1b6b769a213` |
| Gold resolution | formal 11/11、test 8/8 | 当前 `chunks.jsonl` 可解析全部唯一 gold chunk |
| Formal test split | 20/20 请求成功 | `reports/formal_evaluation.json` 与 `.md` 是本次当前结果 |
| Resume accuracy readiness | false | 官方来源占比和独立复核数量未达到宣传门槛 |

Readiness 未通过不是脚本失败：官方来源可回答题只有 3 道，占 6%，`reviewed` 题为 20，低于 70% 和 30 题的策略门槛。因此本报告可用于工程诊断，不能宣传为生产级准确率。

## 当前 formal 数据分布

| 分组 | 总数 | development | test | 样本说明 |
|---|---:|---:|---:|---|
| 故障码 `fault_code` | 7 | 3 | 4 | 可回答 |
| 参数 `parameter` | 15 | 14 | 1 | test 样本不足 |
| 表格 `table` | 3 | 2 | 1 | test 样本不足 |
| 语义 `semantic` | 14 | 10 | 4 | 可回答 |
| 多跳 `multi_hop` | 10 | 5 | 5 | test 中 4 题具有多个必要 gold evidence |
| 无答案 `unanswerable` | 4 | 2 | 2 | 应拒答 |
| 越界 `out_of_scope` | 2 | 1 | 1 | 应拒答 |
| Safety `safety` | 4 | 2 | 2 | 应拒答 |
| 版本冲突 `version_conflict` | 1 | 1 | 0 | 没有 test 样本 |

`parameter`、`table`、`out_of_scope`、`safety`、`unanswerable` 在 test 中均少于 3 题。该类别样本量较小，仅用于诊断，不代表稳定统计结论。

## 当前 Retrieval Evaluation

本层分母为 15 道可回答题：

| 指标 | 结果 | 口径 |
|---|---:|---|
| `strict_recall@5` / Recall@5 | 0.8667 | Top 5 覆盖该题全部人工 gold chunk |
| `retrieval_hit_rate` | 1.0000 | Top 5 至少命中一个 gold chunk |
| `mrr@5` | 1.0000 | 首个 gold chunk 的倒数排名 |
| `ndcg@5` | 0.9028 | 多个 gold chunk 的排序质量 |
| `top1_accuracy` | 1.0000 | 第一条结果属于任一 gold chunk |

`formal_057` 和 `formal_060` 均至少命中一个 gold，但没有在 Top 5 覆盖全部必要 gold，因此 Strict Recall@5 未通过。Retrieval Recall 不等于最终回答准确率。

## 当前 End-to-End Rule Evaluation

| 指标 | 结果 | 分母与规则口径 |
|---|---:|---|
| `citation_correctness_rate` | 0.9286 | 14 个实际回答；按唯一 source 校验本次 Evidence 的 source/chunk/document/page，正文和 citation list 不重复计数 |
| `citation_invalid_count` | 2 | 2 个无效引用均来自 1 道题 |
| `required_fact_coverage` | 0.3929 | 112 条 required facts 的规则型 coverage，不是最终回答准确率 |
| `technical_identifier_accuracy` | 0.6316 | 76 个技术标识；来源标记为 `derived from required_facts`，不是人工结构化 gold field |
| `multi_hop_evidence_coverage` | 1.0000 | 仅纳入 4 道具有多个必要 gold evidence 的多跳题，共 11 个 gold evidence |
| `refusal_accuracy` | 0.9500 | 20 道题的应回答/应拒答决策 |
| `false_accept_rate` | 0.0000 | 5 道应拒答题中没有错误回答 |
| `false_reject_rate` | 0.0667 | 15 道应回答题中有 1 道错误拒答 |
| `claim_support_rate` | `null` | 本轮没有规则可识别的 claim sentence；不以 0 代替，也不包装成完整 Answer Faithfulness |

拒答混淆矩阵为 correct 19、false_accept 0、false_reject 1。按边界拆分：Safety 2/2、Out-of-scope 1/1、Evidence insufficient 2/2 均正确；另有 1 道可回答题因 Evidence insufficient 被错误拒答。

## 失败分析

实际质量失败涉及 2 道题：

- `formal_057`：未覆盖全部 gold，且出现 2 个无效引用；
- `formal_060`：未覆盖全部 gold，Evidence Gate 判为证据不足，形成 false reject。

汇总标签为 `wrong_citation=1`、`evidence_insufficient=1`、`false_refusal=1`；`retrieval_miss`、`rerank_miss`、`false_accept`、`tool_error`、`llm_error`、`request_error` 均为 0。这里的 `wrong_citation=1` 是失败题数，`citation_invalid_count=2` 是无效引用条数。

## Stale / historical 指标

旧 dataset hash `e251df9e9e495644108773becc1880db35d4af0429068a42b881e4501bea4063` 对应的 formal/ranking 数值继续标记为 stale/historical，不能与本轮结果混用。旧 Ranking-only development 的 Strict Recall@5 1.0000、MRR@5 0.9343、nDCG@5 0.9377、Top1 0.8857 只保留为历史开发记录。

当前 `reports/formal_evaluation.json` 和 `reports/formal_evaluation.md` 已由 `formal_eval_v1` 当前 hash 的 test split 重跑生成，不属于上述旧报告。

## 已知限制

- LLM-as-a-judge 保持关闭；所有当前 E2E 数值均为确定性规则结果。
- `required_fact_coverage` 是规则型 coverage；低分还需区分真实漏答、checker 误判、复合标签和 gold 对齐问题。
- `claim_support_rate` 只允许覆盖规则可靠支持的窄范围，不能称为完整 Answer Faithfulness。
- test 的参数、表格、越界、Safety 和无答案样本较少，分类结果只用于诊断。
- 当前使用 `generation_mode=local_extractive`、`generation_fallback_reason=llm_disabled`；这是配置状态，不是 LLM 运行错误。

## 复现命令

```powershell
.\.venv\Scripts\python.exe scripts\ingest.py --mode semantic
.\.venv\Scripts\python.exe scripts\validate_formal_eval.py
.\.venv\Scripts\python.exe scripts\run_formal_eval.py --dry-run --split test
.\.venv\Scripts\python.exe scripts\run_formal_eval.py --split test
.\.venv\Scripts\python.exe -m pytest -q
```
