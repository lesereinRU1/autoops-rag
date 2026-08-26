# Iterative Retrieval A/B Evaluation

> **Historical / stale / 历史版本结果。** 本报告使用旧 dataset hash，只用于解释 iterative development 过程，不代表当前 canonical formal evaluation。

> This report evaluates retrieval evidence only. It does not call an LLM or measure final answer accuracy.

- Split: `development`
- Dataset SHA-256: `e251df9e9e495644108773becc1880db35d4af0429068a42b881e4501bea4063`

## Metrics

| Metric | Value |
|---|---:|
| Total Cases | 35 |
| Retry Trigger Count Before Filtering | 2 |
| Retry Trigger Count After Filtering | 0 |
| Generic Term Retry Block Count | 2 |
| Retry Trigger Rate Before Filtering | 0.0571 |
| Retry Trigger Rate After Filtering | 0.0 |
| Retry Trigger Rate | 0.0 |
| Unnecessary Retry Count | 0 |
| Unnecessary Retry Rate | 0.0 |
| Filtered Missing Terms Avg | 0.0 |
| Generic Terms Ignored Avg | 0.0571 |
| Iterative Retrieval Gain | 0.0286 |
| Strict Recall@5 Baseline | 0.9714 |
| Strict Recall@5 Iterative | 1.0 |
| MRR@5 Baseline | 0.9057 |
| MRR@5 Iterative | 0.9343 |
| nDCG@5 Baseline | 0.9132 |
| nDCG@5 Iterative | 0.9377 |
| Top1 Accuracy Baseline | 0.8286 |
| Top1 Accuracy Iterative | 0.8857 |
| Avg Rounds | 1.0 |
| P50 Latency Baseline (ms) | 1239.71 |
| P95 Latency Baseline (ms) | 2468.94 |
| P50 Latency Iterative (ms) | 1236.2 |
| P95 Latency Iterative (ms) | 1373.76 |
| Budget Stop Count | 0 |
| Loop Violation Count | 0 |
| Safety Regression Count | 0 |
| Out-of-scope Regression Count | 0 |

## Interpretation

- Baseline mirrors the existing bounded one-rewrite behavior.
- Iterative mode retries only after an insufficient evidence assessment and merges both rounds by `chunk_id`.
- Identifier filtering is deterministic and rule-based; no LLM is used to decide retries.
- Generic terms such as `0`, `PLC`, `manual`, `手册` and broad device names do not justify a retry by themselves.
- Latency and retry rates must be considered alongside retrieval gain.
- Safety and out-of-scope cases are policy checks and never execute retrieval in this evaluation.
