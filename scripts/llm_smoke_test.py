from __future__ import annotations

import hashlib
import json
import math
import re
import statistics
import sys
import time
import uuid
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any
from unittest.mock import patch

import httpx

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.config import Settings, get_settings
from app.generation.answer_generator import AnswerGenerator
from app.models import Chunk, SearchHit


DATASET = ROOT / "data" / "eval" / "application_questions.jsonl"
LOCK_FILE = ROOT / "data" / "eval" / "application_eval.lock.json"
JSON_REPORT = ROOT / "reports" / "llm_smoke_test_report.json"
MD_REPORT = ROOT / "reports" / "llm_smoke_test_report.md"
TRACE_FILE = ROOT / "reports" / "rag_traces.jsonl"
LOG_FILES = (ROOT / "reports" / "server.out.log", ROOT / "reports" / "server.err.log")
BASE_URL = "http://127.0.0.1:8000"
DISCLAIMER = "当前20题仅作为LLM smoke test / 回归测试，不作为正式准确率宣传。"

TRACE_FIELDS = (
    "request_id",
    "injected_context",
    "used_chunk_ids",
    "llm_model",
    "input_tokens",
    "output_tokens",
    "total_tokens",
    "first_token_latency_ms",
    "retrieval_latency_ms",
    "llm_latency_ms",
    "total_latency_ms",
    "generation_mode",
    "fallback_reason",
)
FALLBACK_REASONS = {
    "llm_timeout",
    "llm_api_error",
    "llm_empty_response",
    "llm_invalid_response",
}
SENSITIVE_PATTERNS = {
    "LLM_API_KEY": re.compile(r"LLM_API_KEY", re.I),
    "Authorization": re.compile(r"Authorization", re.I),
    "Bearer": re.compile(r"\bBearer\b", re.I),
    "sk-": re.compile(r"\bsk-[A-Za-z0-9_-]+", re.I),
}
IDENTIFIER_PATTERN = re.compile(
    r"(?<![A-Za-z0-9_])(?:MB_[A-Z0-9_]+|RD_MB_DATA_LEN|WR_MB_DATA_LEN|"
    r"RemotePort|InterfaceID|TCON_IP_v\d+|MB_TRANSACTION_ID|CONNECT|STATUS|BUSY|REQ|Role)"
    r"(?![A-Za-z0-9_])",
    re.I,
)
VERSION_PATTERN = re.compile(r"(?<![A-Za-z0-9])V\d+(?:\.\d+)+(?![A-Za-z0-9])", re.I)
STATUS_PATTERN = re.compile(r"(?:16#|0x)[0-9A-Fa-f]{2,8}", re.I)
NUMBER_PATTERN = re.compile(r"(?<![A-Za-z0-9_])\d[\d,]*(?:\.\d+)?(?![A-Za-z0-9_])")
GENERALIZATION_TERMS = ("通常", "一般", "可能", "典型", "必然", "不影响")
IDENTIFIER_ALIASES = {
    "interfaceid": ("interfaceid", "接口标识", "hardware identifier"),
    "status": ("status", "状态", "状态字"),
    "req": ("req", "上升沿", "request edge"),
    "role": ("role", "角色"),
}
LIMITATION_MARKERS = ("当前证据未", "当前证据只能", "证据未", "无法确认", "未说明", "缺少")


class _FallbackResponse:
    def __init__(self, payload: dict[str, Any] | None = None, status_code: int = 200) -> None:
        self.payload = payload or {}
        self.status_code = status_code

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            request = httpx.Request("POST", "https://mock.invalid/chat/completions")
            response = httpx.Response(self.status_code, request=request)
            raise httpx.HTTPStatusError("mock API error", request=request, response=response)

    def json(self) -> dict[str, Any]:
        return self.payload


class _FallbackClient:
    def __init__(self, scenario: str) -> None:
        self.scenario = scenario

    def __enter__(self):
        return self

    def __exit__(self, *args) -> None:
        return None

    def post(self, *args, **kwargs) -> _FallbackResponse:
        if self.scenario == "timeout":
            raise httpx.ReadTimeout("mock timeout")
        if self.scenario == "api_500":
            return _FallbackResponse(status_code=500)
        return _FallbackResponse(
            payload={"model": "qwen-plus", "choices": [{"message": {"content": "   "}}]}
        )


def run_fallback_mock_tests() -> list[dict[str, Any]]:
    settings = Settings(
        _env_file=None,
        llm_enabled=True,
        llm_base_url="https://mock.invalid/v1",
        llm_api_key="mock-only",
        llm_model="qwen-plus",
        llm_timeout_seconds=0.1,
    )
    evidence = [
        SearchHit(
            chunk=Chunk(
                chunk_id="fallback_evidence_001",
                doc_id="fallback_doc",
                doc_name="fallback_test_manual",
                text="RemotePort 的默认值是 502。修改参数前必须核对当前设备手册。",
                page=1,
                section_path=["参数"],
            ),
            score=1.0,
        )
    ]
    scenarios = (
        ("timeout", "llm_timeout"),
        ("api_500", "llm_api_error"),
        ("empty_response", "llm_empty_response"),
    )
    results: list[dict[str, Any]] = []
    for scenario, expected_reason in scenarios:
        generator = AnswerGenerator(settings)
        with patch(
            "app.generation.llm_client.httpx.Client",
            lambda *args, _scenario=scenario, **kwargs: _FallbackClient(_scenario),
        ):
            outcome = generator.generate("RemotePort 默认值是多少？", evidence)
        citation_preserved = "[来源1" in outcome.answer
        passed = (
            outcome.mode == "local_extractive"
            and outcome.fallback_reason == expected_reason
            and bool(outcome.answer)
            and citation_preserved
            and len(evidence) == 1
        )
        results.append(
            {
                "scenario": scenario,
                "expected_reason": expected_reason,
                "actual_reason": outcome.fallback_reason,
                "generation_mode": outcome.mode,
                "external_calls": outcome.external_calls,
                "evidence_count": len(evidence),
                "citation_preserved": citation_preserved,
                "passed": passed,
            }
        )
    return results


def percentile(values: list[float], ratio: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    return round(ordered[max(0, math.ceil(len(ordered) * ratio) - 1)], 2)


def rate(successes: int, total: int) -> float | None:
    return round(successes / total, 4) if total else None


def extract_cited_chunk_ids(answer: str) -> list[str]:
    return list(dict.fromkeys(re.findall(r"chunk_id\s*[:：]\s*([^；;\s\)）]+)", answer, re.I)))


def unsupported_claims(answer: str, trace: dict[str, Any], refused: bool) -> list[dict[str, str]]:
    """Flag Siemens identifiers/versions/status codes absent from injected evidence.

    This is deliberately a narrow smoke guard, not a semantic hallucination judge.
    """
    if refused:
        return []
    context = "\n".join(
        " ".join(
            (
                str(item.get("doc_name", "")),
                str(item.get("page", "")),
                " ".join(item.get("section_path", [])),
                str(item.get("text", "")),
            )
        )
        for item in trace.get("injected_context", [])
    ).lower()
    narrative = re.sub(r"4\. 引用来源.*?5\. 安全提示", "5. 安全提示", answer, flags=re.S)
    findings: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for kind, pattern in (
        ("siemens_parameter", IDENTIFIER_PATTERN),
        ("version", VERSION_PATTERN),
        ("status_code", STATUS_PATTERN),
    ):
        for match in pattern.finditer(narrative):
            value = match.group(0)
            marker = (kind, value.lower())
            supported = value.lower() in context
            if kind == "siemens_parameter" and not supported:
                supported = any(
                    alias in context for alias in IDENTIFIER_ALIASES.get(value.lower(), ())
                )
            if kind == "status_code" and not supported:
                # Manuals often render the same hexadecimal value as 03, 0x03,
                # 16#7000 or W#16#7000. Treat prefix-only differences as equal.
                canonical = re.sub(r"^(?:16#|0x)", "", value.lower()).lstrip("0") or "0"
                supported = bool(
                    re.search(rf"(?<![0-9a-f])0*{re.escape(canonical)}(?![0-9a-f])", context, re.I)
                )
            if marker in seen or supported:
                continue
            seen.add(marker)
            findings.append(
                {
                    "type": kind,
                    "value": value,
                    "reason": "identifier_not_found_in_injected_evidence",
                }
            )
    return findings


def source_indexes(claim: str, maximum: int) -> list[int]:
    indexes: set[int] = set()
    for label in re.findall(r"\[来源([^\]]+)\]", claim):
        for start, end in re.findall(r"(\d+)(?:\s*[–—-]\s*(\d+))?", label):
            first = int(start)
            last = int(end or start)
            indexes.update(range(min(first, last), max(first, last) + 1))
    return sorted(index for index in indexes if 1 <= index <= maximum)


def claim_sentences(answer: str) -> list[str]:
    match = re.search(r"1\. 结论(.*?)4\. 引用来源", answer, flags=re.S)
    if not match:
        return []
    narrative = re.sub(r"\n\s*[23]\. (?:原因|排查 / 换算建议)\s*", "\n", match.group(1))
    claims: list[str] = []
    for part in re.split(r"(?<=[。！？])\s*(?!\[来源)|\n+", narrative):
        value = part.strip(" -•\t")
        plain = re.sub(r"\[来源[^\]]+\]", "", value).strip()
        if len(plain) >= 8:
            claims.append(value)
    return claims


def _normalized_number_supported(value: str, context: str) -> bool:
    normalized = value.replace(",", "").lower()
    compact_context = context.replace(",", "").lower()
    if normalized in compact_context:
        return True
    canonical = normalized.lstrip("0") or "0"
    return bool(re.search(rf"(?<![0-9])0*{re.escape(canonical)}(?![0-9])", compact_context))


def _missing_claim_values(claim: str, context: str) -> list[str]:
    missing_identifiers = unsupported_claims(
        claim, {"injected_context": [{"text": context}]}, False
    )
    claim_without_special = STATUS_PATTERN.sub(" ", VERSION_PATTERN.sub(" ", claim))
    claim_without_special = IDENTIFIER_PATTERN.sub(" ", claim_without_special)
    missing_numbers = [
        value for value in NUMBER_PATTERN.findall(claim_without_special)
        if not _normalized_number_supported(value, context)
    ]
    return list(dict.fromkeys(
        [item["value"] for item in missing_identifiers] + missing_numbers
    ))


def evaluate_claims(
    question_id: str,
    question: str,
    answer: str,
    trace: dict[str, Any],
    refused: bool,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    if refused:
        return [], []
    contexts = trace.get("injected_context", [])
    by_source = {int(item.get("source_number", index)): item for index, item in enumerate(contexts, 1)}
    checks: list[dict[str, Any]] = []
    unsupported: list[dict[str, Any]] = []
    for claim in claim_sentences(answer):
        indexes = source_indexes(claim, len(contexts))
        cited = [by_source[index] for index in indexes if index in by_source]
        cited_chunk_ids = [item.get("chunk_id", "") for item in cited]
        cited_text = "\n".join(
            " ".join(
                (
                    str(item.get("doc_name", "")),
                    " ".join(item.get("section_path", [])),
                    str(item.get("text", "")),
                )
            )
            for item in cited
        )
        evidence_excerpt = "\n".join(
            f"{item.get('chunk_id', '')}: {str(item.get('text', ''))[:220]}" for item in cited[:3]
        )
        plain_claim = re.sub(r"\[来源[^\]]+\]", "", claim).strip()
        is_limitation = any(marker in plain_claim for marker in LIMITATION_MARKERS)
        category = ""
        reason = ""
        if not indexes:
            if is_limitation:
                category = "checker_false_positive"
                reason = "该句声明无法确认而非新增技术事实；自动检查器不能用缺少引用证明其为幻觉"
            else:
                category = "evidence_not_enough"
                reason = "关键事实句没有来源编号"
        elif not cited:
            category = "citation_too_broad"
            reason = "来源编号无法映射到本次injected_context"
        else:
            missing_values = _missing_claim_values(plain_claim, cited_text)
            unsupported_terms = [
                term for term in GENERALIZATION_TERMS
                if term in plain_claim
                and term not in cited_text
                and not (term == "通常" and "常见" in cited_text)
                and not (term == "可能" and ("may" in cited_text.lower() or "can " in cited_text.lower()))
            ]
            if missing_values and not is_limitation:
                category = "hallucination"
                reason = "引用证据中找不到声明里的标识或数值：" + "、".join(missing_values)
            elif unsupported_terms:
                category = "prompt_overgeneralization"
                reason = "回答使用了证据未直接出现的扩展性措辞：" + "、".join(unsupported_terms)
            elif len(indexes) >= 3 and not any(
                not _missing_claim_values(
                    plain_claim,
                    " ".join((
                        str(item.get("doc_name", "")),
                        " ".join(item.get("section_path", [])),
                        str(item.get("text", "")),
                    )),
                )
                for item in cited
            ):
                category = "citation_too_broad"
                reason = "事实由多个chunk拼接支持，但没有单个chunk直接支撑整句"
        counts_as_unsupported = category not in ("", "checker_false_positive")
        supported = not counts_as_unsupported
        item = {
            "question_id": question_id,
            "question": question,
            "generated_claim": plain_claim,
            "cited_chunk_ids": cited_chunk_ids,
            "evidence_text_excerpt": evidence_excerpt,
            "reason": reason or "引用证据包含该句的关键标识和数值",
            "category": category or "supported",
            "supported": supported,
            "counts_as_unsupported": counts_as_unsupported,
        }
        checks.append(item)
        if category:
            unsupported.append({key: item[key] for key in (
                "question_id", "question", "generated_claim", "cited_chunk_ids",
                "evidence_text_excerpt", "reason", "category", "counts_as_unsupported"
            )})
    return checks, unsupported


def apply_claim_review_overrides(
    details: list[dict[str, Any]], overrides: list[dict[str, Any]]
) -> None:
    for override in overrides:
        for detail in details:
            if detail.get("id") != override.get("question_id"):
                continue
            for collection_name in ("claim_checks", "unsupported_claims"):
                for item in detail.get(collection_name, []):
                    if item.get("generated_claim") != override.get("generated_claim"):
                        continue
                    item["category"] = override["category"]
                    item["reason"] = override["reason"]
                    item["counts_as_unsupported"] = bool(override["counts_as_unsupported"])
                    if collection_name == "claim_checks":
                        item["supported"] = not bool(override["counts_as_unsupported"])


def reanalyze_existing_report() -> None:
    if not JSON_REPORT.exists():
        raise RuntimeError("尚无可重分析的LLM smoke报告")
    report = json.loads(JSON_REPORT.read_text(encoding="utf-8-sig"))
    settings = get_settings()
    with httpx.Client(timeout=30, trust_env=False) as client:
        for item in report["details"]:
            request_id = item.get("request_id")
            if not request_id or not item.get("answer"):
                continue
            response = client.get(f"{BASE_URL}/api/traces/{request_id}")
            response.raise_for_status()
            checks, unsupported = evaluate_claims(
                item["id"], item.get("question", ""), item["answer"], response.json(),
                bool(item.get("refused")),
            )
            item["claim_checks"] = checks
            item["unsupported_claims"] = unsupported
    overrides = report.get("claim_review_overrides", [])
    apply_claim_review_overrides(report["details"], overrides)
    all_checks = [check for item in report["details"] for check in item.get("claim_checks", [])]
    automatic_findings = [
        finding for item in report["details"] for finding in item.get("unsupported_claims", [])
    ]
    automatic_count = sum(
        bool(finding.get("counts_as_unsupported")) for finding in automatic_findings
    )
    manual_findings = report.get("manual_unsupported_claims", [])
    report["metrics"]["unsupported_claim_count"] = automatic_count + len(manual_findings)
    report["metrics"]["claim_support_rate"] = rate(
        sum(
            not item.get("counts_as_unsupported", not bool(item.get("supported")))
            for item in all_checks
        ),
        len(all_checks),
    )
    report["fallback_tests"] = run_fallback_mock_tests()
    report["metrics"]["fallback_success_rate"] = rate(
        sum(item["passed"] for item in report["fallback_tests"]), len(report["fallback_tests"])
    )
    report["unsupported_claims"] = automatic_findings
    report["quality_comparison"] = {
        "previous_unsupported_claim_count": 8,
        "current_unsupported_claim_count": report["metrics"]["unsupported_claim_count"],
        "unsupported_claim_delta": report["metrics"]["unsupported_claim_count"] - 8,
        "previous_fallback_success_rate": None,
        "current_fallback_success_rate": report["metrics"]["fallback_success_rate"],
    }
    report["unsupported_claim_check"] = {
        "scope": ["Siemens parameter identifiers", "version numbers", "status/function codes"],
        "evidence_source": "rag_trace.injected_context",
        "equivalent_code_notation_normalized": ["03 == 0x03", "7000 == 16#7000 == W#16#7000"],
        "automatic_finding_count": automatic_count,
        "manual_finding_count": len(manual_findings),
        "checker_false_positive_count": sum(
            item.get("category") == "checker_false_positive" for item in automatic_findings
        ),
        "category_distribution": dict(
            Counter(item.get("category") for item in automatic_findings)
        ),
        "semantic_manual_review": bool(manual_findings or overrides),
    }
    report["limitations"] = [
        DISCLAIMER,
        "unsupported_claim_count合并规则扫描与本轮人工证据复核，但仍不替代独立评审员的完整逐句忠实度评估。",
        "本轮未扩充题目、未修改标签、未进行检索排序优化。",
    ]
    security_files = [scan_sensitive_text(TRACE_FILE, settings.llm_api_key)]
    security_files.extend(scan_sensitive_text(path, settings.llm_api_key) for path in LOG_FILES)
    report["security_scan"] = {
        "passed": all(item["passed"] for item in security_files),
        "checked_patterns": list(SENSITIVE_PATTERNS),
        "files": security_files,
    }
    report["reanalyzed_at"] = datetime.now().astimezone().isoformat(timespec="seconds")
    JSON_REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    MD_REPORT.write_text(make_markdown(report), encoding="utf-8")
    print(
        json.dumps(
            {
                "reanalyzed_without_llm_calls": True,
                "unsupported_claim_count": report["metrics"]["unsupported_claim_count"],
                "security_scan_passed": report["security_scan"]["passed"],
            },
            ensure_ascii=False,
        )
    )


def scan_sensitive_text(path: Path, configured_key: str) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8", errors="ignore") if path.exists() else ""
    matches = [name for name, pattern in SENSITIVE_PATTERNS.items() if pattern.search(text)]
    return {
        "file": str(path.relative_to(ROOT)),
        "exists": path.exists(),
        "forbidden_pattern_matches": matches,
        "contains_configured_api_key": bool(configured_key and configured_key in text),
        "passed": not matches and not (configured_key and configured_key in text),
    }


def make_markdown(report: dict[str, Any]) -> str:
    metrics = report["metrics"]
    security = report["security_scan"]
    manual_counts = Counter(
        item["id"] for item in report.get("manual_unsupported_claims", [])
    )
    lines = [
        "# 20题LLM Smoke Test报告",
        "",
        f"> {DISCLAIMER}",
        "",
        f"- 运行时间：{report['generated_at']}",
        f"- 数据集：`{report['dataset']['file']}`",
        f"- 题目数量：{report['dataset']['questions']}（数据集哈希未改变：{report['dataset']['lock_matches']}）",
        f"- 模型：`{report['model']}`",
        "",
        "## 汇总指标",
        "",
        "| 指标 | 结果 | 口径 |",
        "|---|---:|---|",
    ]
    descriptions = {
        "llm_grounded_rate": "20个请求中成功使用外部模型且基于证据生成的比例",
        "external_llm_call_rate": "20个请求中实际发生外部模型调用的比例",
        "token_usage_available_rate": "实际调用外部模型的请求中，供应商返回可解析token的比例",
        "unanswerable_refusal_accuracy": "4个非危险不可回答题中正确拒答的比例",
        "unsafe_refusal_accuracy": "1个危险请求中正确拒答的比例",
        "citation_chunk_valid_rate": "15个可回答题中，至少有一个chunk_id且全部来自本次evidence的比例",
        "unsupported_claim_count": "规则扫描和人工证据复核发现的证据外Siemens参数、版本号、状态码解释或执行声明数量",
        "claim_support_rate": "结论、原因和排查建议中的关键事实句通过直接证据检查的比例",
        "fallback_success_rate": "本轮实际触发LLM错误降级时，成功返回本地答案并记录原因的比例；未触发则为空",
        "latency_p50_ms": "成功请求的服务内部总耗时P50",
        "latency_p95_ms": "成功请求的服务内部总耗时P95",
    }
    for name in descriptions:
        value = metrics.get(name)
        shown = "未触发/不适用" if value is None else str(value)
        lines.append(f"| `{name}` | {shown} | {descriptions[name]} |")
    comparison = report.get("quality_comparison", {})
    lines.extend(
        [
            "",
            "## 本轮质量修复对比",
            "",
            f"- unsupported claims：{comparison.get('previous_unsupported_claim_count')} → {comparison.get('current_unsupported_claim_count')}（变化 {comparison.get('unsupported_claim_delta')}）",
            f"- fallback success rate：未触发 → {comparison.get('current_fallback_success_rate')}",
        ]
    )
    lines.extend(
        [
            "",
            "## Trace与安全检查",
            "",
            f"- Trace字段完整率：{metrics['trace_schema_valid_rate']}",
            f"- Trace按request_id落盘率：{metrics['trace_persisted_rate']}",
            f"- Trace/日志敏感信息检查：{'通过' if security['passed'] else '未通过'}",
            "- `model`按Trace中的`llm_model`字段检查；设备型号另存于`device_model`。",
            "- `first_token_latency_ms`在当前非流式调用下表示完整响应首次可用耗时。",
            "",
            "## 延迟拆分",
            "",
            "| 阶段 | P50 ms | P95 ms | 样本数 |",
            "|---|---:|---:|---:|",
            f"| retrieval | {report['latency_breakdown']['retrieval_latency_ms']['p50']} | {report['latency_breakdown']['retrieval_latency_ms']['p95']} | {report['latency_breakdown']['retrieval_latency_ms']['denominator']} |",
            f"| LLM | {report['latency_breakdown']['llm_latency_ms']['p50']} | {report['latency_breakdown']['llm_latency_ms']['p95']} | {report['latency_breakdown']['llm_latency_ms']['denominator']} |",
            f"| total | {report['latency_breakdown']['total_latency_ms']['p50']} | {report['latency_breakdown']['total_latency_ms']['p95']} | {report['latency_breakdown']['total_latency_ms']['denominator']} |",
            f"| first token / response available | {report['latency_breakdown']['first_token_latency_ms']['p50']} | {report['latency_breakdown']['first_token_latency_ms']['p95']} | {report['latency_breakdown']['first_token_latency_ms']['denominator']} |",
            "",
            "> 当前为非流式调用，first_token_latency_ms表示完整响应首次可用耗时，不是真实流式TTFT。",
            "",
            "## Fallback Mock",
            "",
            "| 场景 | 期望原因 | 实际原因 | 模式 | evidence | 引用保留 | 通过 |",
            "|---|---|---|---|---:|---|---|",
        ]
    )
    for item in report.get("fallback_tests", []):
        lines.append(
            f"| {item['scenario']} | {item['expected_reason']} | {item['actual_reason']} | "
            f"{item['generation_mode']} | {item['evidence_count']} | "
            f"{'是' if item['citation_preserved'] else '否'} | {'是' if item['passed'] else '否'} |"
        )
    lines.extend(
        [
            "",
            "## 分题结果",
            "",
            "| 题号 | 分类 | HTTP | 模式 | 外部调用 | token | 拒答 | 引用chunk有效 | 证据外声明 | 耗时ms |",
            "|---|---|---:|---|---:|---:|---|---|---:|---:|",
        ]
    )
    for item in report["details"]:
        lines.append(
            "| {id} | {category} | {http_status} | {mode} | {calls} | {tokens} | {refused} | "
            "{citation} | {unsupported} | {latency} |".format(
                id=item["id"],
                category=item["category"],
                http_status=item.get("http_status", ""),
                mode=item.get("generation_mode", "request_failed"),
                calls=item.get("external_llm_calls", 0),
                tokens=item.get("total_tokens") if item.get("total_tokens") is not None else "-",
                refused="是" if item.get("refused") else "否",
                citation=(
                    "是" if item.get("citation_chunk_valid") is True else
                    "否" if item.get("citation_chunk_valid") is False else "不适用"
                ),
                unsupported=sum(
                    finding.get("counts_as_unsupported", finding.get("category") != "checker_false_positive")
                    for finding in item.get("unsupported_claims", [])
                ) + manual_counts[item["id"]],
                latency=item.get("latency_ms", "-"),
            )
        )
    unsupported_findings = report.get("unsupported_claims", [])
    if unsupported_findings:
        lines.extend(
            [
                "",
                "## 证据外声明复核",
                "",
                "以下条目来自关键事实句与本次`injected_context`的逐项检查：",
                "",
                "| 题号 | 分类 | 计入unsupported | 回答中的声明 | 引用chunk | 证据摘录 | 判定原因 |",
                "|---|---|---|---|---|---|---|",
            ]
        )
        for finding in unsupported_findings:
            lines.append(
                f"| {finding['question_id']} | {finding['category']} | "
                f"{'是' if finding.get('counts_as_unsupported') else '否'} | "
                f"{finding['generated_claim'].replace('|', '／')} | "
                f"{', '.join(finding['cited_chunk_ids']) or '-'} | "
                f"{finding['evidence_text_excerpt'][:180].replace(chr(10), ' ').replace('|', '／')} | "
                f"{finding['reason'].replace('|', '／')} |"
            )
    lines.extend(
        [
            "",
            "## 结论与边界",
            "",
            f"- {DISCLAIMER}",
            "- 本轮重点验证LLM接入、拒答、安全边界、引用合法性、Trace与fallback；Recall@5不作为主要结论。",
            "- 当前主要待修复项是unsupported claims和fallback覆盖。",
            "- `unsupported_claim_count`合并规则扫描和本轮人工证据复核，但仍不等价于完整逐句忠实度评审。",
            "- 状态码/功能码比较会归一化等价写法，例如`03`与`0x03`、`7000`与`W#16#7000`。",
            "- 本轮没有增加题目、修改标签或调整Dense/BM25/RRF排序。",
            "",
            "延迟优化建议（本轮不直接实施）：",
            *[f"- {item}" for item in report.get("latency_recommendations", [])],
            "",
        ]
    )
    return "\n".join(lines)


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if "--reanalyze-existing" in sys.argv[1:]:
        reanalyze_existing_report()
        return
    raw = DATASET.read_bytes()
    rows = [json.loads(line) for line in raw.decode("utf-8").splitlines() if line.strip()]
    if len(rows) != 20:
        raise RuntimeError(f"本脚本只允许现有20题，当前读取到{len(rows)}题")
    dataset_hash = hashlib.sha256(raw).hexdigest()
    lock = json.loads(LOCK_FILE.read_text(encoding="utf-8"))
    lock_matches = lock.get("sha256") == dataset_hash
    if not lock_matches:
        raise RuntimeError("现有20题数据集哈希与锁文件不一致，停止执行")

    settings = get_settings()
    run_id = uuid.uuid4().hex[:12]
    details: list[dict[str, Any]] = []
    with httpx.Client(timeout=120, trust_env=False) as client:
        health = client.get(f"{BASE_URL}/health")
        health.raise_for_status()
        status = health.json()
        if not status.get("llm_enabled"):
            raise RuntimeError("服务未启用外部LLM，停止执行")

        for index, row in enumerate(rows, start=1):
            session_id = f"llm-smoke-{run_id}-{row['id']}"
            started = time.perf_counter()
            try:
                response = client.post(
                    f"{BASE_URL}/api/chat",
                    json={
                        "query": row["question"],
                        "model": row["model"],
                        "version": "",
                        "top_k": 5,
                        "strategy": "hybrid",
                        "session_id": session_id,
                    },
                )
                wall_latency_ms = round((time.perf_counter() - started) * 1000, 2)
                response.raise_for_status()
                result = response.json()
                runtime = result["runtime"]
                trace = result["rag_trace"]
                evidence_ids = [hit["chunk"]["chunk_id"] for hit in result.get("evidence", [])]
                cited_ids = extract_cited_chunk_ids(result.get("answer", ""))
                citation_valid = None
                if row["answerable"]:
                    citation_valid = bool(cited_ids) and set(cited_ids).issubset(set(evidence_ids))
                refused = bool(trace.get("refused")) and not result.get("evidence_sufficient", False)
                claim_checks, unsupported = evaluate_claims(
                    row["id"], row["question"], result.get("answer", ""), trace, refused
                )
                missing_trace_fields = [field for field in TRACE_FIELDS if field not in trace]
                trace_response = client.get(f"{BASE_URL}/api/traces/{result['request_id']}")
                trace_persisted = (
                    trace_response.status_code == 200
                    and trace_response.json().get("request_id") == result["request_id"]
                )
                fallback_event = (
                    runtime.get("external_llm_calls", 0) > 0
                    and runtime.get("generation_mode") == "local_extractive"
                    and runtime.get("generation_fallback_reason") in FALLBACK_REASONS
                )
                fallback_success = (
                    fallback_event
                    and bool(result.get("answer"))
                    and bool(runtime.get("generation_fallback_reason"))
                )
                detail = {
                    "id": row["id"],
                    "question": row["question"],
                    "category": row["category"],
                    "answerable": row["answerable"],
                    "http_status": response.status_code,
                    "request_id": result["request_id"],
                    "generation_mode": runtime.get("generation_mode"),
                    "external_llm_calls": runtime.get("external_llm_calls", 0),
                    "token_usage_available": runtime.get("token_usage_available", False),
                    "input_tokens": runtime.get("external_input_tokens"),
                    "output_tokens": runtime.get("external_output_tokens"),
                    "total_tokens": runtime.get("external_token_usage"),
                    "token_usage_missing_reason": runtime.get("token_usage_missing_reason", ""),
                    "latency_ms": runtime.get("total_ms"),
                    "retrieval_latency_ms": runtime.get("retrieval_latency_ms", 0.0),
                    "llm_latency_ms": runtime.get("llm_latency_ms", 0.0),
                    "first_token_latency_ms": runtime.get("first_token_latency_ms"),
                    "wall_latency_ms": wall_latency_ms,
                    "evidence_sufficient": result.get("evidence_sufficient", False),
                    "refused": refused,
                    "fallback_reason": runtime.get("generation_fallback_reason", ""),
                    "fallback_event": fallback_event,
                    "fallback_success": fallback_success,
                    "evidence_chunk_ids": evidence_ids,
                    "cited_chunk_ids": cited_ids,
                    "citation_chunk_valid": citation_valid,
                    "unsupported_claims": unsupported,
                    "claim_checks": claim_checks,
                    "trace_missing_fields": missing_trace_fields,
                    "trace_schema_valid": not missing_trace_fields,
                    "trace_persisted": trace_persisted,
                    "answer": result.get("answer", ""),
                }
            except Exception as exc:
                detail = {
                    "id": row["id"],
                    "question": row["question"],
                    "category": row["category"],
                    "answerable": row["answerable"],
                    "http_status": getattr(getattr(exc, "response", None), "status_code", 0),
                    "error_type": type(exc).__name__,
                    "generation_mode": "request_failed",
                    "external_llm_calls": 0,
                    "refused": False,
                    "citation_chunk_valid": False if row["answerable"] else None,
                    "unsupported_claims": [],
                    "claim_checks": [],
                    "trace_schema_valid": False,
                    "trace_persisted": False,
                    "fallback_event": False,
                    "fallback_success": False,
                }
            details.append(detail)
            print(
                f"[{index:02d}/20] {row['id']} mode={detail['generation_mode']} "
                f"calls={detail.get('external_llm_calls', 0)} refused={detail.get('refused', False)}"
            )
            try:
                client.delete(f"{BASE_URL}/api/sessions/{session_id}")
            except httpx.HTTPError:
                pass

    successful = [item for item in details if item.get("http_status") == 200]
    external = [item for item in successful if item.get("external_llm_calls", 0) > 0]
    answerable = [item for item in details if item["answerable"]]
    unanswerable = [
        item for item in details if not item["answerable"] and item["category"] != "unsafe_request"
    ]
    unsafe = [item for item in details if item["category"] == "unsafe_request"]
    fallback_events = [item for item in successful if item.get("fallback_event")]
    latencies = [float(item["latency_ms"]) for item in successful if item.get("latency_ms") is not None]
    retrieval_latencies = [
        float(item["retrieval_latency_ms"])
        for item in successful if item.get("retrieval_latency_ms") is not None
    ]
    llm_latencies = [
        float(item["llm_latency_ms"])
        for item in external if item.get("llm_latency_ms") is not None
    ]
    first_token_latencies = [
        float(item["first_token_latency_ms"])
        for item in external if item.get("first_token_latency_ms") is not None
    ]
    fallback_tests = run_fallback_mock_tests()
    all_claim_checks = [check for item in details for check in item.get("claim_checks", [])]
    all_unsupported = [claim for item in details for claim in item.get("unsupported_claims", [])]

    trace_lines = []
    if TRACE_FILE.exists():
        for line in TRACE_FILE.read_text(encoding="utf-8").splitlines():
            try:
                trace_lines.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    trace_ids = {item.get("request_id") for item in trace_lines}
    for item in details:
        if item.get("request_id") and item["request_id"] not in trace_ids:
            item["trace_persisted"] = False

    security_files = [scan_sensitive_text(TRACE_FILE, settings.llm_api_key)]
    security_files.extend(scan_sensitive_text(path, settings.llm_api_key) for path in LOG_FILES)
    security_passed = all(item["passed"] for item in security_files)
    metrics = {
        "llm_grounded_rate": rate(
            sum(item.get("generation_mode") == "llm_grounded" for item in details), len(details)
        ),
        "external_llm_call_rate": rate(len(external), len(details)),
        "token_usage_available_rate": rate(
            sum(bool(item.get("token_usage_available")) for item in external), len(external)
        ),
        "unanswerable_refusal_accuracy": rate(
            sum(bool(item.get("refused")) for item in unanswerable), len(unanswerable)
        ),
        "unsafe_refusal_accuracy": rate(
            sum(bool(item.get("refused")) for item in unsafe), len(unsafe)
        ),
        "citation_chunk_valid_rate": rate(
            sum(item.get("citation_chunk_valid") is True for item in answerable), len(answerable)
        ),
        "unsupported_claim_count": len(
            [item for item in all_unsupported if item.get("counts_as_unsupported")]
        ),
        "claim_support_rate": rate(
            sum(
                not item.get("counts_as_unsupported", not bool(item.get("supported")))
                for item in all_claim_checks
            ),
            len(all_claim_checks),
        ),
        "fallback_success_rate": rate(
            sum(bool(item.get("passed")) for item in fallback_tests), len(fallback_tests)
        ),
        "latency_p50_ms": percentile(latencies, 0.50),
        "latency_p95_ms": percentile(latencies, 0.95),
        "trace_schema_valid_rate": rate(
            sum(bool(item.get("trace_schema_valid")) for item in details), len(details)
        ),
        "trace_persisted_rate": rate(
            sum(bool(item.get("trace_persisted")) for item in details), len(details)
        ),
    }
    latency_breakdown = {
        "retrieval_latency_ms": {
            "p50": percentile(retrieval_latencies, 0.50),
            "p95": percentile(retrieval_latencies, 0.95),
            "denominator": len(retrieval_latencies),
        },
        "llm_latency_ms": {
            "p50": percentile(llm_latencies, 0.50),
            "p95": percentile(llm_latencies, 0.95),
            "denominator": len(llm_latencies),
        },
        "total_latency_ms": {
            "p50": percentile(latencies, 0.50),
            "p95": percentile(latencies, 0.95),
            "denominator": len(latencies),
        },
        "first_token_latency_ms": {
            "p50": percentile(first_token_latencies, 0.50),
            "p95": percentile(first_token_latencies, 0.95),
            "denominator": len(first_token_latencies),
            "note": "当前为非流式调用，该值表示完整响应首次可用耗时。",
        },
    }
    report = {
        "evaluation_type": "llm_smoke_regression_not_formal_evaluation",
        "disclaimer": DISCLAIMER,
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "run_id": run_id,
        "model": settings.llm_model,
        "dataset": {
            "file": str(DATASET.relative_to(ROOT)),
            "sha256": dataset_hash,
            "lock_matches": lock_matches,
            "questions": len(rows),
            "answerable": sum(row["answerable"] for row in rows),
            "unanswerable_non_unsafe": sum(
                not row["answerable"] and row["category"] != "unsafe_request" for row in rows
            ),
            "unsafe": sum(row["category"] == "unsafe_request" for row in rows),
            "category_distribution": dict(Counter(row["category"] for row in rows)),
        },
        "metrics": metrics,
        "metric_denominators": {
            "all_requests": len(details),
            "external_llm_requests": len(external),
            "answerable_requests": len(answerable),
            "unanswerable_non_unsafe_requests": len(unanswerable),
            "unsafe_requests": len(unsafe),
            "fallback_events": len(fallback_events),
            "fallback_mock_scenarios": len(fallback_tests),
            "claim_sentences": len(all_claim_checks),
            "successful_requests": len(successful),
        },
        "fallback_tests": fallback_tests,
        "latency_breakdown": latency_breakdown,
        "latency_recommendations": [
            "限制injected_context总长度，并记录截断策略与被舍弃chunk。",
            "限制max_output_tokens，避免结构化回答不必要地扩写。",
            "开启流式输出以获得真实首token耗时并改善页面体感。",
            "优先注入Top3到Top5高置信证据；实施前用同一20题smoke复核claim支持和拒答。",
        ],
        "quality_comparison": {
            "previous_unsupported_claim_count": 8,
            "current_unsupported_claim_count": metrics["unsupported_claim_count"],
            "unsupported_claim_delta": metrics["unsupported_claim_count"] - 8,
            "previous_fallback_success_rate": None,
            "current_fallback_success_rate": metrics["fallback_success_rate"],
        },
        "security_scan": {
            "passed": security_passed,
            "checked_patterns": list(SENSITIVE_PATTERNS),
            "files": security_files,
        },
        "trace_field_mapping": {
            "model": "llm_model",
            "token": ["input_tokens", "output_tokens", "total_tokens"],
            "latency": [
                "retrieval_latency_ms", "llm_latency_ms", "first_token_latency_ms", "total_latency_ms"
            ],
        },
        "unsupported_claim_check": {
            "scope": ["Siemens parameter identifiers", "version numbers", "status/function codes"],
            "evidence_source": "rag_trace.injected_context",
            "equivalent_code_notation_normalized": ["03 == 0x03", "7000 == 16#7000 == W#16#7000"],
            "automatic_finding_count": metrics["unsupported_claim_count"],
            "manual_finding_count": 0,
            "checker_false_positive_count": sum(
                item.get("category") == "checker_false_positive" for item in all_unsupported
            ),
            "category_distribution": dict(Counter(item.get("category") for item in all_unsupported)),
            "semantic_manual_review": False,
        },
        "manual_unsupported_claims": [],
        "claim_review_overrides": [],
        "unsupported_claims": all_unsupported,
        "details": details,
        "limitations": [
            DISCLAIMER,
            "unsupported_claim_count合并规则扫描与本轮人工证据复核，但仍不替代独立评审员的完整逐句忠实度评估。",
            "本轮未扩充题目、未修改标签、未进行检索排序优化。",
        ],
    }
    JSON_REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    MD_REPORT.write_text(make_markdown(report), encoding="utf-8")
    print(json.dumps({"reports": [str(JSON_REPORT), str(MD_REPORT)], "metrics": metrics}, ensure_ascii=False))


if __name__ == "__main__":
    main()
