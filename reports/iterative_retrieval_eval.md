# Iterative Retrieval A/B Evaluation

> This report evaluates retrieval evidence only. It does not call an LLM or measure final answer accuracy.

- Split: `development`
- Dataset SHA-256: `e251df9e9e495644108773becc1880db35d4af0429068a42b881e4501bea4063`

## Metrics

| Metric | Value |
|---|---:|
| Total Cases | 35 |
| Retry Trigger Rate | 0.0571 |
| Unnecessary Retry Rate | 1.0 |
| Iterative Retrieval Gain | 0.0 |
| Strict Recall@5 Baseline | 0.9714 |
| Strict Recall@5 Iterative | 0.9714 |
| MRR@5 Baseline | 0.9057 |
| MRR@5 Iterative | 0.9343 |
| nDCG@5 Baseline | 0.9132 |
| nDCG@5 Iterative | 0.9302 |
| Top1 Accuracy Baseline | 0.8286 |
| Top1 Accuracy Iterative | 0.8857 |
| Avg Rounds | 1.0571 |
| P50 Latency Baseline (ms) | 336.03 |
| P95 Latency Baseline (ms) | 696.16 |
| P50 Latency Iterative (ms) | 336.03 |
| P95 Latency Iterative (ms) | 630.64 |
| Budget Stop Count | 1 |
| Loop Violation Count | 0 |
| Safety Regression Count | 0 |
| Out-of-scope Regression Count | 0 |

## Interpretation

- Baseline mirrors the existing bounded one-rewrite behavior.
- Iterative mode retries only after an insufficient evidence assessment and merges both rounds by `chunk_id`.
- Latency and retry rates must be considered alongside retrieval gain.
- Safety and out-of-scope cases are policy checks and never execute retrieval in this evaluation.
