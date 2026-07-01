from __future__ import annotations

from app.evaluation.required_fact_checker import diagnose_required_fact
from scripts.run_formal_eval import render_markdown_report, validate_formal_citations


def test_semantic_checker_matches_synonym_and_reordered_chinese() -> None:
    fact = "应确认对端正在运行并监听正确接口"
    answer = "排查时需核对对端设备是否正在运行并监听正确接口。"
    gold = "排查时先确认对端正在运行并监听正确接口。"

    result = diagnose_required_fact(fact, answer, gold)

    assert result.exact_match is False
    assert result.semantic_match is True
    assert result.diagnostic_covered is True
    assert result.match_type == "semantic_match"
    assert result.classification == "checker_false_negative"


def test_semantic_checker_matches_required_fact_split_across_answer_lines() -> None:
    fact = "应核对网络可达性、端口、Unit ID 以及请求是否超出对端寄存器范围"
    answer = "\n".join(
        (
            "核对网络可达性。",
            "核对端口。",
            "核对 Unit ID。",
            "确认请求是否超出对端寄存器范围。",
        )
    )
    gold = "再核对网络可达性、端口、Unit ID，以及请求是否超出对端寄存器范围。"

    result = diagnose_required_fact(fact, answer, gold)

    assert result.semantic_match is True
    assert result.diagnostic_covered is True
    assert all(item["matched"] for item in result.answer_atomic_matches)


def test_semantic_checker_does_not_cover_completely_missing_fact() -> None:
    fact = "不要通过无限重试掩盖持续通信故障"
    answer = "核对端口和 Unit ID。"
    gold = "不要通过无限重试掩盖持续通信故障。"

    result = diagnose_required_fact(fact, answer, gold)

    assert result.diagnostic_covered is False
    assert result.classification == "missing_from_answer"


def test_partial_compound_fact_is_reported_as_too_broad_not_covered() -> None:
    fact = "应记录远端 IP、端口、Unit ID、功能码和数据长度"
    answer = "记录远端 IP 和端口。"
    gold = "记录远端 IP、端口、Unit ID、功能码和数据长度。"

    result = diagnose_required_fact(fact, answer, gold)

    assert result.diagnostic_covered is False
    assert result.required_fact_too_broad is True
    assert result.classification == "required_fact_too_broad"


def test_fact_not_supported_by_gold_is_never_diagnostic_covered() -> None:
    fact = "需要确认请求没有超出对端寄存器范围"
    answer = "需要确认请求没有超出对端寄存器范围。"
    gold = "请求数量必须与接收缓冲区的数据类型和容量匹配。"

    result = diagnose_required_fact(fact, answer, gold)

    assert result.exact_match is True
    assert result.diagnostic_covered is False
    assert result.gold_directly_supports is False
    assert result.classification == "required_fact_not_directly_supported_by_gold"


def test_markdown_report_shows_exact_and_diagnostic_metrics() -> None:
    report = {
        "metrics": {
            "required_fact_exact_coverage": 0.16,
            "required_fact_diagnostic_coverage": 0.67,
        },
        "required_fact_diagnostics_summary": {
            "exact_match": 18,
            "semantic_match": 57,
            "checker_false_negative": 57,
            "missing_from_answer": 14,
            "required_fact_too_broad": 7,
            "required_fact_not_directly_supported_by_gold": 16,
        },
        "details": [],
    }

    markdown = render_markdown_report(report)

    assert "required_fact_exact_coverage" in markdown
    assert "required_fact_diagnostic_coverage" in markdown
    assert "只用于诊断" in markdown
    assert "不能直接等同于模型错误" in markdown


def test_formal_citation_checker_accepts_numbered_local_fallback_sources() -> None:
    evidence_ids = ["chunk_001", "chunk_002"]
    answer = "核对通信参数。[来源2：通信故障排查流程，第1页]"

    assert validate_formal_citations(answer, evidence_ids) is True


def test_formal_citation_checker_rejects_out_of_range_numbered_source() -> None:
    evidence_ids = ["chunk_001", "chunk_002"]
    answer = "核对通信参数。[来源3：不存在的证据]"

    assert validate_formal_citations(answer, evidence_ids) is False
