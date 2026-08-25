# Formal Evaluation Report

> 当前正式集仍未达到 readiness 门槛时，本报告只能用于开发诊断，不能作为简历准确率宣传。

## Dataset

- Version: `formal_eval_v1`
- SHA-256: `3b33876cd584e6215ef03a8bb07d0566aa57371957e606196c37b6f26641a4d9`
- Split: `test`
- Case count: `20`
- Status: `completed`

Retrieval 指标与最终回答质量指标分层报告；Retrieval Recall 不等于最终回答准确率。

## Processed corpus

- SHA-256: `090f5e5f416ea1762d4f71e7a28b10d0e7f083ef30ae04f3a305c1b6b769a213`
- Documents: `6`
- Chunks: `16945`
- Table chunks: `12011`
- Formal gold resolvable: `11/11`
- Selected split gold resolvable: `8/8`

## Retrieval Evaluation

| Metric | Value |
|---|---:|
| `strict_recall@5` | 0.8667 |
| `mrr@5` | 1.0 |
| `ndcg@5` | 0.9028 |
| `top1_accuracy` | 1.0 |
| `retrieval_hit_rate` | 1.0 |

`strict_recall@5` 要求 Top 5 覆盖该题全部人工 gold chunk；`retrieval_hit_rate` 只要求至少命中一个 gold chunk。两者都只衡量检索。

## End-to-End Rule Evaluation

| Metric | Value | Meaning |
|---|---:|---|
| `citation_correctness_rate` | 0.9286 | 引用是否真实映射到本次 Evidence 的 source/chunk/document/page |
| `required_fact_coverage` | 0.3929 | 规则型 required facts 覆盖率，不是最终回答准确率 |
| `required_fact_exact_coverage` | 0.1518 | 历史完整子串规则口径 |
| `required_fact_diagnostic_coverage` | 0.3929 | 确定性规范化和原子事实匹配，只用于诊断 |
| `technical_identifier_accuracy` | 0.6316 | 从 required_facts 自动抽取的技术标识精确匹配 |
| `multi_hop_evidence_coverage` | 1.0 | 仅统计有多个必要 gold evidence 的多跳题 |
| `refusal_accuracy` | 0.95 | 应拒答/应回答决策是否正确 |
| `false_accept_rate` | 0.0 | 应拒答却回答的比例 |
| `false_reject_rate` | 0.0667 | 应回答却拒答的比例 |
| `claim_support_rate` | null | 仅检查规则可识别的引用、标识符和数值，不代表完整 Answer Faithfulness |

精确技术标识的 gold 来源标记为 `derived from required_facts`；当前数据集没有人工结构化技术标识字段。
Required Fact Coverage 低不能直接等同于模型错误；还需区分 checker 误判、真实漏答、复合标签和 gold 对齐问题。

## Refusal confusion matrix

| Outcome | Count |
|---|---:|
| correct | 19 |
| false_accept | 0 |
| false_reject | 1 |

## By category

| Category | Cases | Recall@5 | MRR@5 | Citation | Required facts | Refusal |
|---|---:|---:|---:|---:|---:|---:|
| `fault_code` | 4 | 0.5 | 1.0 | 0.6667 | 0.2812 | 0.75 |
| `multi_hop` | 5 | 1.0 | 1.0 | 1.0 | 0.4762 | 1.0 |
| `out_of_scope` | 1 | null | null | null | null | 1.0 |
| `parameter` | 1 | 1.0 | 1.0 | 1.0 | 0.5 | 1.0 |
| `safety` | 2 | null | null | null | null | 1.0 |
| `semantic` | 4 | 1.0 | 1.0 | 1.0 | 0.3846 | 1.0 |
| `table` | 1 | 1.0 | 1.0 | 1.0 | 0.3333 | 1.0 |
| `unanswerable` | 2 | null | null | null | null | 1.0 |

小样本类别：`out_of_scope, parameter, safety, table, unanswerable`。该类别样本量较小，仅用于诊断，不代表稳定统计结论。

## Failure analysis

| Failure | Count |
|---|---:|
| `retrieval_miss` | 0 |
| `rerank_miss` | 0 |
| `evidence_insufficient` | 1 |
| `wrong_citation` | 1 |
| `hallucinated_fact` | 0 |
| `false_refusal` | 1 |
| `false_accept` | 0 |
| `tool_error` | 0 |
| `llm_error` | 0 |
| `request_error` | 0 |

## Limitations

- 本轮没有启用 LLM-as-a-judge；`llm_judge.enabled=false`。
- `claim_support_rate` 是窄范围、可审计的规则指标，不是完整 Answer Faithfulness。
- `required_fact_coverage` 是规则型 coverage，不是最终回答准确率。
- 技术标识由 `required_facts` 自动抽取，不是人工结构化 gold field。
- 多跳 Evidence coverage 只对至少两个必要 gold chunk 的题目计算，其他题为 null。
