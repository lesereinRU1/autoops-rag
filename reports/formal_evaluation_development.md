# Formal Evaluation Report

> 当前正式集仍未达到 readiness 门槛时，本报告只能用于开发诊断，不能作为简历准确率宣传。

## Core metrics

| Metric | Value |
|---|---:|
| `strict_recall@5` | 0.9714 |
| `mrr@5` | 0.9057 |
| `ndcg@5` | 0.9132 |
| `top1_accuracy` | 0.8286 |
| `claim_support_rate` | None |
| `unsupported_claim_count` | 0 |
| `citation_chunk_valid_rate` | 1.0 |
| `required_fact_exact_coverage` | 0.1582 |
| `required_fact_diagnostic_coverage` | 0.4633 |
| `unanswerable_refusal_accuracy` | 1.0 |
| `unsafe_refusal_accuracy` | 1.0 |
| `forbidden_fact_violation_count` | 0 |

`required_fact_exact_coverage` 保留历史完整子串口径。`required_fact_diagnostic_coverage` 使用离线确定性规范化、同义短语和原子事实匹配，只用于诊断，不作为最终准确率宣传。

required_fact_coverage 低不能直接等同于模型错误；必须区分 checker 误判、真实漏答、复合标签和 required_fact/gold 不对齐。

## Required fact diagnostic breakdown

| Type | Count |
|---|---:|
| exact_match | 28 |
| semantic_match | 54 |
| checker_false_negative | 54 |
| missing_from_answer | 57 |
| required_fact_too_broad | 10 |
| required_fact_not_directly_supported_by_gold | 28 |

## Per-question required fact coverage

| ID | Exact | Diagnostic | Facts |
|---|---:|---:|---:|
| formal_001 | 0.2500 | 0.5000 | 4 |
| formal_002 | 0.0000 | 0.2500 | 4 |
| formal_003 | 0.0000 | 0.5000 | 4 |
| formal_004 | 0.0000 | 0.0000 | 4 |
| formal_005 | 0.0000 | 1.0000 | 4 |
| formal_006 | N/A | N/A | 0 |
| formal_007 | N/A | N/A | 0 |
| formal_008 | 0.7500 | 1.0000 | 4 |
| formal_009 | 0.0000 | 0.2000 | 5 |
| formal_010 | N/A | N/A | 0 |
| formal_029 | N/A | N/A | 0 |
| formal_030 | N/A | N/A | 0 |
| formal_011 | 0.0000 | 0.2500 | 4 |
| formal_024 | 0.0000 | 0.0000 | 3 |
| formal_026 | 0.0000 | 0.5000 | 4 |
| formal_027 | 0.0000 | 0.0000 | 5 |
| formal_028 | 0.0000 | 0.3333 | 6 |
| formal_025 | 0.0000 | 0.4000 | 5 |
| formal_012 | 0.0000 | 0.0000 | 4 |
| formal_013 | 0.0000 | 0.6000 | 5 |
| formal_031 | 0.0000 | 0.8333 | 6 |
| formal_032 | 0.0000 | 0.2500 | 4 |
| formal_033 | 0.5000 | 0.5000 | 4 |
| formal_034 | 0.6000 | 0.8000 | 5 |
| formal_035 | 0.0000 | 0.2500 | 4 |
| formal_036 | 0.0000 | 0.6000 | 5 |
| formal_037 | 0.5000 | 1.0000 | 4 |
| formal_038 | 0.0000 | 0.2500 | 4 |
| formal_039 | 0.0000 | 0.6667 | 6 |
| formal_040 | 0.0000 | 1.0000 | 5 |
| formal_041 | 0.0000 | 0.4000 | 5 |
| formal_042 | 0.2000 | 0.6000 | 5 |
| formal_043 | 0.1667 | 0.3333 | 6 |
| formal_044 | 0.0000 | 0.2857 | 7 |
| formal_045 | 0.5000 | 0.5000 | 6 |
| formal_046 | 0.7143 | 0.7143 | 7 |
| formal_047 | 0.2500 | 0.2500 | 8 |
| formal_048 | 0.2500 | 0.3750 | 8 |
| formal_049 | 0.1667 | 0.5000 | 6 |
| formal_050 | 0.2857 | 0.4286 | 7 |

## Limitations

- Diagnostic matching is deterministic and does not call an LLM.
- Semantic matching is deliberately conservative and keeps atomic match evidence in JSON.
- A diagnostic match is counted only when the human gold text also supports the required fact.
- The legacy `required_fact_coverage` field remains an alias of exact coverage for compatibility.
