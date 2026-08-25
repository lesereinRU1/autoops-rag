from __future__ import annotations

import json
from pathlib import Path

from app.evaluation.end_to_end import (
    aggregate_results,
    dataset_sha256,
    error_case,
    evaluate_case,
    evaluate_citations,
    refusal_outcome,
    validate_dataset_manifest,
)
from app.evaluation.technical_identifier_checker import evaluate_technical_identifiers


def _evidence(
    chunk_id: str = "chunk-1", document: str = "manual-one.pdf", page: int = 12
) -> dict:
    return {
        "chunk": {
            "chunk_id": chunk_id,
            "doc_id": "doc-1",
            "doc_name": document,
            "text": "16#80C8 表示通信超时。RemotePort 为 502。",
            "page": page,
            "section_path": ["故障码"],
        },
        "score": 1.0,
    }


def _row(
    *,
    case_id: str = "formal-test",
    category: str = "alarm_code",
    answerable: bool = True,
    gold: list[str] | None = None,
    required_facts: list[str] | None = None,
) -> dict:
    return {
        "id": case_id,
        "question": "16#80C8 是什么？",
        "category": category,
        "answerable": answerable,
        "expected_tool": "search_manual",
        "gold_chunk_ids": (gold if gold is not None else ["chunk-1"]) if answerable else [],
        "required_facts": (
            required_facts
            if required_facts is not None
            else (["16#80C8 表示通信超时", "RemotePort 为 502"] if answerable else [])
        ),
        "forbidden_facts": [],
        "split": "test",
    }


def _response(
    *,
    answer: str = (
        "1. 结论\n16#80C8 表示通信超时。[来源1]\n"
        "2. 原因\nRemotePort 为 502。[来源1]\n"
        "3. 排查 / 换算建议\n核对参数。[来源1]\n"
        "4. 引用来源\n- [来源1] chunk_id: chunk-1；文档: manual-one.pdf；第12页\n"
        "5. 安全提示\n按规程操作。"
    ),
    evidence: list[dict] | None = None,
    refused: bool = False,
    stop_reason: str = "evidence_sufficient",
) -> dict:
    evidence = [_evidence()] if evidence is None else evidence
    return {
        "request_id": "request-1",
        "answer": answer,
        "evidence": evidence,
        "selected_tool": "search_manual",
        "evidence_sufficient": not refused,
        "agent_trace": [{"node": "citation_guard", "valid": True, "action": "accept"}],
        "runtime": {
            "retrieval_latency_ms": 10.0,
            "llm_latency_ms": 20.0,
            "total_ms": 35.0,
            "first_token_latency_ms": 20.0,
            "external_llm_calls": 1,
            "generation_mode": "llm_grounded",
            "generation_fallback_reason": "",
        },
        "rag_trace": {
            "refused": refused,
            "stop_reason": stop_reason,
            "query_rewrite_attempts": 0,
            "tool_calls": [],
            "rrf_topk": [{"chunk_id": item["chunk"]["chunk_id"]} for item in evidence],
        },
    }


def test_citation_correct_and_manifest_duplicate_is_counted_once() -> None:
    answer = (
        "事实。[来源1：manual-one.pdf，第12页]\n"
        "4. 引用来源\n- [来源1] chunk_id: chunk-1；文档: manual-one.pdf；第12页"
    )

    result = evaluate_citations(answer, [_evidence()])

    assert result.citation_valid is True
    assert result.citation_invalid_count == 0
    assert result.citation_reference_count == 1
    assert len(result.references) == 1


def test_citation_to_non_evidence_chunk_is_invalid() -> None:
    answer = "事实。[来源1]\n- [来源1] chunk_id: not-in-evidence；文档: manual-one.pdf；第12页"

    result = evaluate_citations(answer, [_evidence()])

    assert result.citation_valid is False
    assert result.citation_invalid_count == 1
    assert any("chunk_id" in error for error in result.errors)


def test_nonexistent_source_number_is_invalid() -> None:
    result = evaluate_citations("事实。[来源9]", [_evidence()])

    assert result.citation_valid is False
    assert result.citation_invalid_count == 1
    assert any("outside" in error for error in result.errors)


def test_missing_citation_is_invalid() -> None:
    result = evaluate_citations("回答给出了技术结论，但没有引用。", [_evidence()])

    assert result.citation_valid is False
    assert result.citation_invalid_count == 1
    assert any("no citation" in error for error in result.errors)


def test_document_and_page_must_match_indexed_evidence() -> None:
    result = evaluate_citations(
        "事实。[来源1：wrong.pdf，第99页]", [_evidence()]
    )

    assert result.citation_valid is False
    assert result.citation_invalid_count == 1
    assert any("document" in error for error in result.errors)
    assert any("page" in error for error in result.errors)


def test_display_document_name_maps_back_to_raw_evidence_document() -> None:
    result = evaluate_citations(
        "事实。[来源1：项目补充：Modbus 地址与数据检查，第1页]",
        [_evidence(document="autoops_Modbus地址与数据检查.md", page=1)],
    )

    assert result.citation_valid is True


def test_citation_guard_fallback_is_recorded() -> None:
    result = evaluate_citations(
        "事实。[来源1]",
        [_evidence()],
        agent_trace=[
            {
                "node": "citation_guard",
                "valid": True,
                "action": "fallback_local_extractive",
            }
        ],
    )

    assert result.citation_guard_fallback is True


def test_refusal_confusion_matrix_cases() -> None:
    assert refusal_outcome(answerable=False, actual_refusal=True) == (True, False, None)
    assert refusal_outcome(answerable=False, actual_refusal=False) == (False, True, None)
    assert refusal_outcome(answerable=True, actual_refusal=True) == (False, None, True)
    assert refusal_outcome(answerable=True, actual_refusal=False) == (True, None, False)


def test_required_facts_full_and_partial_coverage() -> None:
    row = _row()
    full = evaluate_case(
        row,
        _response(),
        wall_latency_ms=40.0,
        gold_chunk_texts={"chunk-1": _evidence()["chunk"]["text"]},
    )
    partial_response = _response(
        answer=(
            "1. 结论\n16#80C8 表示通信超时。[来源1]\n"
            "2. 原因\n当前证据未提供其他参数。[来源1]\n"
            "3. 排查 / 换算建议\n核对手册。[来源1]\n"
            "4. 引用来源\n- [来源1] chunk_id: chunk-1；文档: manual-one.pdf；第12页\n"
            "5. 安全提示\n按规程操作。"
        )
    )
    partial = evaluate_case(
        row,
        partial_response,
        wall_latency_ms=40.0,
        gold_chunk_texts={"chunk-1": _evidence()["chunk"]["text"]},
    )

    assert full.required_fact_coverage == 1.0
    assert partial.required_fact_coverage == 0.5
    assert full.required_fact_coverage != full.strict_recall_at_5 or full.strict_recall_at_5 == 1.0


def test_exact_fault_code_parameter_and_value_are_derived_from_required_facts() -> None:
    result = evaluate_technical_identifiers(
        ["故障码 16#80C8 表示超时", "RemotePort 为 502"],
        "16#80c8 表示超时，RemotePort 应设置为 502。",
    )

    assert result.source == "derived from required_facts"
    assert result.accuracy == 1.0
    assert result.expected["fault_code"] == ["16#80C8"]
    assert result.expected["parameter"] == ["RemotePort"]
    assert result.expected["value"] == ["502"]

    partial = evaluate_technical_identifiers(
        ["故障码 16#80C8 表示超时", "RemotePort 为 502"],
        "只确认了 16#80C8。",
    )
    assert partial.accuracy is not None
    assert 0.0 < partial.accuracy < 1.0
    assert partial.missing["parameter"] == ["RemotePort"]
    assert partial.missing["value"] == ["502"]


def test_multi_hop_coverage_requires_multiple_gold_evidence() -> None:
    single = evaluate_case(
        _row(category="cross_section_procedure", gold=["chunk-1"]),
        _response(),
        wall_latency_ms=40.0,
        gold_chunk_texts={"chunk-1": _evidence()["chunk"]["text"]},
    )
    multiple = evaluate_case(
        _row(category="cross_section_procedure", gold=["chunk-1", "chunk-2"]),
        _response(),
        wall_latency_ms=40.0,
        gold_chunk_texts={"chunk-1": _evidence()["chunk"]["text"], "chunk-2": "第二步"},
    )

    assert single.multi_hop_evidence_coverage is None
    assert multiple.multi_hop_evidence_coverage == 0.5
    assert multiple.multi_hop_evidence_total == 2


def test_category_summary_and_retrieval_e2e_metrics_are_separate() -> None:
    valid = evaluate_case(
        _row(),
        _response(),
        wall_latency_ms=40.0,
        gold_chunk_texts={"chunk-1": _evidence()["chunk"]["text"]},
    )
    wrong_citation = evaluate_case(
        _row(case_id="formal-wrong", category="official_parameter"),
        _response(answer="事实。[来源9]"),
        wall_latency_ms=40.0,
        gold_chunk_texts={"chunk-1": _evidence()["chunk"]["text"]},
    )

    summary = aggregate_results([valid, wrong_citation])

    assert set(summary["by_category"]) == {"fault_code", "parameter"}
    assert summary["overall"]["strict_recall@5"] == 1.0
    assert summary["overall"]["citation_correctness_rate"] == 0.5
    assert "citation_correctness_rate" not in summary["retrieval_evaluation"]["metrics"]
    assert "strict_recall@5" not in summary["end_to_end_evaluation"]["metrics"]
    assert summary["failure_analysis"]["wrong_citation"] == 1


def test_failure_analysis_distinguishes_retrieval_and_rerank_miss() -> None:
    response = _response(evidence=[_evidence("chunk-1")])
    response["rag_trace"]["rrf_topk"] = [{"chunk_id": "chunk-2"}]
    result = evaluate_case(
        _row(gold=["chunk-2"]),
        response,
        wall_latency_ms=40.0,
        gold_chunk_texts={"chunk-2": "必要证据"},
    )

    summary = aggregate_results([result])
    assert summary["failure_analysis"]["retrieval_miss"] == 1
    assert summary["failure_analysis"]["rerank_miss"] == 1


def test_llm_disabled_is_not_an_llm_error_but_real_llm_failure_is() -> None:
    disabled_response = _response()
    disabled_response["runtime"].update(
        {
            "external_llm_calls": 0,
            "generation_mode": "local_extractive",
            "generation_fallback_reason": "llm_disabled",
        }
    )
    disabled = evaluate_case(
        _row(),
        disabled_response,
        wall_latency_ms=40.0,
        gold_chunk_texts={"chunk-1": _evidence()["chunk"]["text"]},
    )

    timeout_response = _response()
    timeout_response["runtime"].update(
        {
            "generation_mode": "local_extractive",
            "generation_fallback_reason": "llm_timeout",
        }
    )
    timeout = evaluate_case(
        _row(case_id="timeout"),
        timeout_response,
        wall_latency_ms=40.0,
        gold_chunk_texts={"chunk-1": _evidence()["chunk"]["text"]},
    )

    assert "llm_error" not in disabled.failure_tags
    assert "llm_error" in timeout.failure_tags


def test_expected_evidence_insufficient_refusal_is_not_a_failure() -> None:
    result = evaluate_case(
        _row(category="unanswerable_version", answerable=False),
        _response(
            answer="当前证据不足，无法回答。",
            evidence=[],
            refused=True,
            stop_reason="insufficient_evidence",
        ),
        wall_latency_ms=5.0,
        gold_chunk_texts={},
    )

    assert result.refusal_correct is True
    assert "evidence_insufficient" not in result.failure_tags


def test_refusal_types_and_null_fields_are_preserved() -> None:
    safety_row = _row(category="unsafe_request", answerable=False)
    safety = evaluate_case(
        safety_row,
        _response(answer="拒绝执行危险操作。", evidence=[], refused=True, stop_reason="safety_blocked"),
        wall_latency_ms=5.0,
        gold_chunk_texts={},
    )
    failed = error_case(_row(), RuntimeError("offline"))
    payload = failed.model_dump(mode="json", by_alias=True)

    assert safety.expected_refusal_type == "safety"
    assert safety.actual_refusal_type == "safety"
    assert safety.citation_valid is None
    assert safety.false_accept is False
    assert safety.false_reject is None
    assert payload["citation_valid"] is None
    assert payload["retrieval_hit"] is None
    assert payload["tool_calls"] is None
    assert payload["error"].startswith("RuntimeError")


def test_refusal_summary_distinguishes_all_boundary_types() -> None:
    cases = []
    for case_id, category, stop_reason, refused in (
        ("safety", "unsafe_request", "safety_blocked", True),
        ("scope", "unanswerable_scope", "out_of_scope", False),
        ("missing", "unanswerable_version", "insufficient_evidence", True),
    ):
        cases.append(
            evaluate_case(
                _row(case_id=case_id, category=category, answerable=False),
                _response(
                    answer="拒答。" if refused else "错误地给出答案。",
                    evidence=[],
                    refused=refused,
                    stop_reason=stop_reason,
                ),
                wall_latency_ms=5.0,
                gold_chunk_texts={},
            )
        )

    summary = aggregate_results(cases)

    assert summary["refusal_by_type"]["safety"]["correct"] == 1
    assert summary["refusal_by_type"]["out_of_scope"]["false_accept"] == 1
    assert summary["refusal_by_type"]["evidence_insufficient"]["correct"] == 1
    assert summary["overall"]["refusal_confusion_matrix"] == {
        "correct": 2,
        "false_accept": 1,
        "false_reject": 0,
    }


def test_answerable_refusal_is_false_reject() -> None:
    result = evaluate_case(
        _row(),
        _response(answer="证据不足，无法回答。", evidence=[], refused=True, stop_reason="insufficient_evidence"),
        wall_latency_ms=5.0,
        gold_chunk_texts={"chunk-1": _evidence()["chunk"]["text"]},
    )

    assert result.refusal_correct is False
    assert result.false_accept is None
    assert result.false_reject is True
    assert result.citation_valid is None


def test_dataset_hash_and_manifest_validation_are_stable(tmp_path: Path) -> None:
    dataset = tmp_path / "formal.jsonl"
    row = {"id": "case-1", "split": "test"}
    dataset.write_text(json.dumps(row) + "\n", encoding="utf-8")
    digest = dataset_sha256(dataset)
    manifest = {
        "dataset_version": "formal_eval_v1",
        "sha256": digest,
        "case_count": 1,
        "splits": {"test": 1},
    }

    assert dataset_sha256(dataset) == digest
    assert validate_dataset_manifest(manifest, dataset, [row]) == []
    dataset.write_text(json.dumps({"id": "case-2", "split": "test"}) + "\n", encoding="utf-8")
    assert "hash mismatch" in "\n".join(
        validate_dataset_manifest(manifest, dataset, [{"id": "case-2", "split": "test"}])
    )


def test_formal_eval_dry_run_does_not_call_api_or_create_metrics(
    tmp_path: Path, monkeypatch
) -> None:
    from scripts import run_formal_eval

    output = tmp_path / "dry-run.json"
    markdown = tmp_path / "dry-run.md"
    readiness = tmp_path / "readiness.json"
    monkeypatch.setattr(run_formal_eval, "CHUNKS_FILE", tmp_path / "missing-chunks.jsonl")
    monkeypatch.setattr(
        "sys.argv",
        [
            "run_formal_eval.py",
            "--dry-run",
            "--split",
            "test",
            "--output",
            str(output),
            "--markdown-output",
            str(markdown),
            "--readiness-output",
            str(readiness),
        ],
    )

    assert run_formal_eval.main() == 0
    report = json.loads(output.read_text(encoding="utf-8"))
    assert report["status"] == "dry_run"
    assert report["execution_ready"] is False
    assert report["metrics"] == {}
    assert report["dataset"]["version"] == "formal_eval_v1"
    assert report["dataset"]["case_count"] == 20
    assert report["dataset"]["file"] == "data/eval/formal_questions.jsonl"
    assert report["readiness"]["manifest"] == "data/eval/formal_eval_manifest.json"
    assert "没有生成任何新的" in markdown.read_text(encoding="utf-8")
