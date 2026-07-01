# Formal Evaluation Report

> 当前正式集仍未达到 readiness 门槛时，本报告只能用于开发诊断，不能作为简历准确率宣传。

## Core metrics

| Metric | Value |
|---|---:|
| `strict_recall@5` | 0.8667 |
| `mrr@5` | 1.0 |
| `ndcg@5` | 0.9256 |
| `top1_accuracy` | 1.0 |
| `claim_support_rate` | None |
| `unsupported_claim_count` | 0 |
| `citation_chunk_valid_rate` | 1.0 |
| `required_fact_exact_coverage` | 0.1518 |
| `required_fact_diagnostic_coverage` | 0.4196 |
| `unanswerable_refusal_accuracy` | 1.0 |
| `unsafe_refusal_accuracy` | 1.0 |
| `forbidden_fact_violation_count` | 0 |

`required_fact_exact_coverage` 保留历史完整子串口径。`required_fact_diagnostic_coverage` 使用离线确定性规范化、同义短语和原子事实匹配，只用于诊断，不作为最终准确率宣传。

required_fact_coverage 低不能直接等同于模型错误；必须区分 checker 误判、真实漏答、复合标签和 required_fact/gold 不对齐。

## Required fact diagnostic breakdown

| Type | Count |
|---|---:|
| exact_match | 17 |
| semantic_match | 30 |
| checker_false_negative | 30 |
| missing_from_answer | 42 |
| required_fact_too_broad | 15 |
| required_fact_not_directly_supported_by_gold | 8 |

## Per-question required fact coverage

| ID | Exact | Diagnostic | Facts |
|---|---:|---:|---:|
| formal_051 | 0.1667 | 0.1667 | 6 |
| formal_052 | 0.1667 | 0.3333 | 6 |
| formal_053 | 0.5000 | 0.5000 | 6 |
| formal_054 | 0.5714 | 0.5714 | 7 |
| formal_055 | 0.5000 | 0.5000 | 6 |
| formal_056 | 0.5714 | 0.5714 | 7 |
| formal_057 | 0.0000 | 0.5000 | 8 |
| formal_058 | 0.0000 | 0.7143 | 7 |
| formal_059 | 0.0000 | 0.1250 | 8 |
| formal_060 | 0.0000 | 0.0000 | 9 |
| formal_061 | 0.0000 | 0.5714 | 7 |
| formal_062 | 0.0000 | 0.5000 | 6 |
| formal_063 | 0.1111 | 0.1111 | 9 |
| formal_064 | N/A | N/A | 0 |
| formal_065 | N/A | N/A | 0 |
| formal_066 | N/A | N/A | 0 |
| formal_067 | N/A | N/A | 0 |
| formal_068 | N/A | N/A | 0 |
| formal_069 | 0.0000 | 0.8000 | 10 |
| formal_070 | 0.0000 | 0.4000 | 10 |

## Limitations

- Diagnostic matching is deterministic and does not call an LLM.
- Semantic matching is deliberately conservative and keeps atomic match evidence in JSON.
- A diagnostic match is counted only when the human gold text also supports the required fact.
- The legacy `required_fact_coverage` field remains an alias of exact coverage for compatibility.
