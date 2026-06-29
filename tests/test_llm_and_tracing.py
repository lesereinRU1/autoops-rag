from __future__ import annotations

from app.config import Settings
from app.generation.answer_generator import AnswerGenerator
from app.generation.llm_client import LLMClient, LLMClientError, LLMResult
from app.models import Chunk, SearchHit
from app.service import AutoOpsService
from app.tracing import TraceStore
from scripts.llm_smoke_test import evaluate_claims, run_fallback_mock_tests


def _hit() -> SearchHit:
    return SearchHit(
        chunk=Chunk(
            chunk_id="modbus_address_001",
            doc_id="manual",
            doc_name="Modbus/TCP with MB_CLIENT and MB_SERVER",
            text="40001 is a holding-register reference. The protocol data address starts at zero.",
            page=5,
            section_path=["Modbus TCP", "Addressing"],
        ),
        score=0.8,
    )


class _Response:
    def __init__(self, payload: dict) -> None:
        self.payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return self.payload


class _Client:
    def __init__(self, payload: dict) -> None:
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *args) -> None:
        return None

    def post(self, *args, **kwargs) -> _Response:
        return _Response(self.payload)


def test_non_streaming_llm_usage_is_parsed(monkeypatch):
    payload = {
        "model": "qwen-plus",
        "choices": [{"message": {"content": "回答"}}],
        "usage": {"prompt_tokens": 20, "completion_tokens": 8, "total_tokens": 28},
    }
    monkeypatch.setattr(
        "app.generation.llm_client.httpx.Client", lambda *args, **kwargs: _Client(payload)
    )
    result = LLMClient("https://example.invalid/v1", "test-only", "qwen-plus", 1).generate(
        "prompt", retries=0
    )
    assert result.token_usage_available is True
    assert (result.input_tokens, result.output_tokens, result.total_tokens) == (20, 8, 28)
    assert result.token_usage_missing_reason == ""


def test_missing_usage_has_machine_readable_reason(monkeypatch):
    payload = {"choices": [{"message": {"content": "回答"}}]}
    monkeypatch.setattr(
        "app.generation.llm_client.httpx.Client", lambda *args, **kwargs: _Client(payload)
    )
    result = LLMClient("https://example.invalid/v1", "test-only", "qwen-plus", 1).generate(
        "prompt", retries=0
    )
    assert result.token_usage_available is False
    assert result.total_tokens is None
    assert result.token_usage_missing_reason == "provider_did_not_return_usage"


def test_generator_success_is_grounded_and_records_calls():
    settings = Settings(
        _env_file=None,
        llm_enabled=True,
        llm_base_url="https://example.invalid/v1",
        llm_api_key="test-only",
        llm_model="qwen-plus",
    )
    generator = AnswerGenerator(settings)

    class FakeClient:
        def generate(self, prompt: str, retries: int = 1) -> LLMResult:
            assert "evidence 是唯一事实来源" in prompt
            return LLMResult(
                content=(
                    "1. 结论\n40001是参考编号。[来源1]\n"
                    "2. 原因\n报文偏移从0开始。[来源1]\n"
                    "3. 排查 / 换算建议\n核对地址表示法。[来源1]\n"
                    "4. 引用来源\n[来源1] chunk_id: modbus_address_001\n"
                    "5. 安全提示\n写入前核对手册。"
                ),
                calls=1,
                model="qwen-plus",
                input_tokens=30,
                output_tokens=20,
                total_tokens=50,
                token_usage_available=True,
                token_usage_missing_reason="",
                first_token_latency_ms=10.0,
                total_latency_ms=20.0,
            )

    generator.llm = FakeClient()
    outcome = generator.generate("为什么40001对应偏移0？", [_hit()])
    assert outcome.mode == "llm_grounded"
    assert outcome.external_calls == 1
    assert outcome.total_tokens == 50
    assert outcome.fallback_reason == ""


def test_generator_error_falls_back_with_reason():
    settings = Settings(
        _env_file=None,
        llm_enabled=True,
        llm_base_url="https://example.invalid/v1",
        llm_api_key="test-only",
    )
    generator = AnswerGenerator(settings)

    class FailingClient:
        def generate(self, prompt: str, retries: int = 1):
            raise LLMClientError("llm_api_error", attempts=2)

    generator.llm = FailingClient()
    outcome = generator.generate("为什么40001对应偏移0？", [_hit()])
    assert outcome.mode == "local_extractive"
    assert outcome.external_calls == 2
    assert outcome.fallback_reason == "llm_api_error"


def test_trace_is_jsonl_and_redacts_credentials(tmp_path):
    path = tmp_path / "rag_traces.jsonl"
    store = TraceStore(path)
    store.append(
        {
            "request_id": "request-1234",
            "llm_api_key": "fixture-token",
            "headers": {"Authorization": "Bearer fixture-token"},
        }
    )
    raw = path.read_text(encoding="utf-8")
    assert "fixture-token" not in raw
    assert len(raw.splitlines()) == 1
    assert store.get("request-1234")["llm_api_key"] == "[REDACTED]"


def test_unsafe_and_out_of_scope_requests_are_rejected_before_generation():
    service = object.__new__(AutoOpsService)
    service._chunk_by_id = {}
    assert service.scope_refusal_reason("请给出旁路联锁并强制输出的具体步骤", "S7-1200")
    assert service.scope_refusal_reason("三菱PLC故障怎么处理", "S7-1200")


def test_fallback_mock_matrix_preserves_evidence_and_citations():
    results = run_fallback_mock_tests()
    assert {item["actual_reason"] for item in results} == {
        "llm_timeout", "llm_api_error", "llm_empty_response"
    }
    assert all(item["passed"] for item in results)
    assert all(item["generation_mode"] == "local_extractive" for item in results)
    assert all(item["evidence_count"] == 1 and item["citation_preserved"] for item in results)


def test_claim_checker_returns_auditable_unsupported_detail():
    trace = {
        "injected_context": [
            {
                "source_number": 1,
                "chunk_id": "c1",
                "doc_name": "manual",
                "section_path": ["CONNECT"],
                "text": "CONNECT 使用 TCON_IP_v4，InterfaceID 取自硬件标识。",
            }
        ]
    }
    answer = (
        "1. 结论\nCONNECT 使用 TCON_IP_v3。[来源1]\n"
        "2. 原因\n当前证据只能说明 TCON_IP_v4。[来源1]\n"
        "3. 排查 / 换算建议\n核对 InterfaceID。[来源1]\n"
        "4. 引用来源\n[来源1]\n5. 安全提示\n不执行写入。"
    )
    checks, unsupported = evaluate_claims("q1", "CONNECT 类型？", answer, trace, False)
    assert checks
    assert unsupported
    assert unsupported[0]["question_id"] == "q1"
    assert unsupported[0]["category"] == "hallucination"
    assert unsupported[0]["cited_chunk_ids"] == ["c1"]
