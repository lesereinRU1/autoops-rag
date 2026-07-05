from scripts.benchmark_runtime import render_markdown


def test_runtime_benchmark_report_keeps_scenario_and_phase_boundaries():
    report = {
        "scenario": "chat_with_local_extractive_generation",
        "endpoint": "/api/chat",
        "includes_external_llm": False,
        "requests_per_level": 30,
        "warmup_requests": 3,
        "environment": {
            "os": "Windows-test",
            "machine": "AMD64",
            "logical_cpus": 8,
            "python": "3.11",
        },
        "levels": [
            {
                "concurrency": 8,
                "success_rate": 1.0,
                "throughput_rps": 4.5,
                "latency_p50_ms": 100.0,
                "latency_p95_ms": 200.0,
                "retrieval_p50_ms": 60.0,
                "retrieval_p95_ms": 120.0,
                "llm_p50_ms": 0.0,
                "llm_p95_ms": 0.0,
                "orchestration_p50_ms": 40.0,
                "orchestration_p95_ms": 80.0,
            }
        ],
        "notes": ["scenario-qualified throughput"],
    }

    markdown = render_markdown(report)

    assert "chat_with_local_extractive_generation" in markdown
    assert "外部 LLM 纳入压测：`false`" in markdown
    assert "检索 P50/P95" in markdown
    assert "LLM P50/P95" in markdown
