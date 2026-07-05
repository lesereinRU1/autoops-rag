# Runtime Benchmark

- 场景：`hybrid_search_only`
- 接口：`/api/search`
- 外部 LLM 纳入压测：`false`
- 每档请求数：30（预热 3 次）
- 环境：Windows-11-10.0.26200-SP0 / AMD64 / 16 logical CPUs / Python 3.12.10

| 并发 | 成功率 | RPS | 客户端 P50/P95 | 检索 P50/P95 | LLM P50/P95 | 编排 P50/P95 |
|---:|---:|---:|---:|---:|---:|---:|
| 1 | 100.00% | 3.070 | 313.18/413.79 ms | 313.18/413.79 ms | 0.00/0.00 ms | 0.00/0.00 ms |
| 4 | 100.00% | 3.579 | 1031.93/1253.33 ms | 1031.93/1253.33 ms | 0.00/0.00 ms | 0.00/0.00 ms |
| 8 | 100.00% | 3.329 | 2299.00/2629.24 ms | 2299.00/2629.24 ms | 0.00/0.00 ms | 0.00/0.00 ms |

## 口径

- Results are from the current Windows single-machine environment.
- RPS is reported only with its endpoint and generation scenario; it is not a generic LLM throughput claim.
- Retrieval, external LLM, and orchestration latency are reported separately for /api/chat.
- The /api/search retrieval latency is measured at the client boundary and includes HTTP serialization overhead.
- Queries share a read lock; index rebuild and shutdown use an exclusive write lock.
- Local Qdrant supports one process only. Use Qdrant Server before adding multiple API workers.
- CPU embedding and SQLite writes can still limit throughput at higher concurrency.
- This benchmark measures industrial manual Q&A, not code repair tasks.
