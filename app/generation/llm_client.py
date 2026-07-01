from __future__ import annotations

import time
from dataclasses import dataclass
from dataclasses import field
from typing import Any

import httpx


@dataclass
class LLMResult:
    content: str
    calls: int
    model: str
    input_tokens: int | None
    output_tokens: int | None
    total_tokens: int | None
    token_usage_available: bool
    token_usage_missing_reason: str
    first_token_latency_ms: float | None
    total_latency_ms: float
    attempted_models: list[str] = field(default_factory=list)
    final_model: str = ""
    fallback_reason: str = ""


class LLMClientError(RuntimeError):
    def __init__(
        self,
        reason: str,
        attempts: int,
        attempted_models: list[str] | None = None,
        final_model: str = "",
        total_latency_ms: float = 0.0,
    ) -> None:
        super().__init__(reason)
        self.reason = reason
        self.attempts = attempts
        self.attempted_models = list(attempted_models or [])
        self.final_model = final_model
        self.total_latency_ms = total_latency_ms


def _int_or_none(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _parse_usage(payload: dict[str, Any]) -> tuple[int | None, int | None, int | None, bool, str]:
    """Parse OpenAI-compatible token usage without inventing missing values."""
    usage = payload.get("usage")
    if not isinstance(usage, dict) or not usage:
        return None, None, None, False, "provider_did_not_return_usage"

    input_tokens = _int_or_none(usage.get("prompt_tokens", usage.get("input_tokens")))
    output_tokens = _int_or_none(usage.get("completion_tokens", usage.get("output_tokens")))
    total_tokens = _int_or_none(usage.get("total_tokens"))
    if total_tokens is None and input_tokens is not None and output_tokens is not None:
        total_tokens = input_tokens + output_tokens
    if input_tokens is None or output_tokens is None or total_tokens is None:
        return input_tokens, output_tokens, total_tokens, False, "usage_parse_failed"
    return input_tokens, output_tokens, total_tokens, True, ""


_UNAVAILABLE_MARKERS = (
    "quota exceeded",
    "quota_exceeded",
    "insufficient quota",
    "insufficient_quota",
    "insufficient balance",
    "resourceexhausted",
    "resource_exhausted",
    "throttling",
    "throttled",
    "rate limit",
    "rate_limit",
    "too many requests",
    "额度不足",
    "余额不足",
    "限流",
)


def _response_text(response: Any) -> str:
    try:
        payload = response.json()
        return json_dumps(payload).lower()
    except (AttributeError, TypeError, ValueError):
        return str(getattr(response, "text", "")).lower()


def json_dumps(value: Any) -> str:
    """Serialize provider errors for classification only; the value is never logged."""
    import json

    return json.dumps(value, ensure_ascii=False, default=str)


def _model_unavailable_reason(response: Any) -> str:
    status_code = int(getattr(response, "status_code", 200) or 200)
    if status_code < 400:
        try:
            payload = response.json()
        except (AttributeError, TypeError, ValueError):
            return ""
        if not isinstance(payload, dict) or "error" not in payload:
            return ""
    text = _response_text(response)
    if status_code == 429 or any(marker in text for marker in ("rate limit", "rate_limit", "throttl", "限流")):
        return "llm_rate_limited"
    if status_code == 402 or any(
        marker in text
        for marker in (
            "quota exceeded",
            "quota_exceeded",
            "insufficient quota",
            "insufficient_quota",
            "insufficient balance",
            "resourceexhausted",
            "resource_exhausted",
            "额度不足",
            "余额不足",
        )
    ):
        return "llm_quota_exceeded"
    if status_code == 403:
        return "llm_model_forbidden"
    if any(marker in text for marker in _UNAVAILABLE_MARKERS):
        return "llm_model_unavailable"
    return ""


class LLMClient:
    """Small non-streaming OpenAI-compatible client used by the RAG generator."""

    def __init__(
        self,
        base_url: str,
        api_key: str,
        model: str,
        timeout: float,
        fallback_models: list[str] | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.timeout = timeout
        self.models = list(dict.fromkeys([model, *(fallback_models or [])]))

    def generate(self, prompt: str, retries: int = 1) -> LLMResult:
        """Try each configured model once; retries is retained for API compatibility."""
        url = self.base_url + "/chat/completions"
        started = time.perf_counter()
        attempted_models: list[str] = []
        last_reason = "llm_api_error"

        # `retries` previously retried the same model. It is intentionally ignored now:
        # every candidate model is attempted at most once in this fallback sequence.
        del retries
        # The desktop environment may expose a stale HTTPS proxy. DashScope works over
        # a direct TLS connection here, so do not inherit proxy variables.
        with httpx.Client(timeout=self.timeout, trust_env=False) as client:
            for model in self.models:
                attempted_models.append(model)
                response_started = time.perf_counter()
                try:
                    response = client.post(
                        url,
                        headers={
                            "Authorization": f"Bearer {self.api_key}",
                            "Content-Type": "application/json",
                        },
                        json={
                            "model": model,
                            "messages": [{"role": "user", "content": prompt}],
                            "temperature": 0.1,
                            "stream": False,
                        },
                    )
                    unavailable_reason = _model_unavailable_reason(response)
                    if unavailable_reason:
                        last_reason = unavailable_reason
                        continue
                    response.raise_for_status()
                    try:
                        payload = response.json()
                    except (TypeError, ValueError) as exc:
                        raise LLMClientError(
                            "llm_invalid_response",
                            len(attempted_models),
                            attempted_models,
                            "",
                            (time.perf_counter() - started) * 1000,
                        ) from exc
                    if not isinstance(payload, dict):
                        raise LLMClientError(
                            "llm_invalid_response",
                            len(attempted_models),
                            attempted_models,
                            "",
                            (time.perf_counter() - started) * 1000,
                        )

                    choices = payload.get("choices")
                    if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
                        raise LLMClientError(
                            "llm_invalid_response",
                            len(attempted_models),
                            attempted_models,
                            "",
                            (time.perf_counter() - started) * 1000,
                        )
                    message = choices[0].get("message")
                    if not isinstance(message, dict) or not isinstance(message.get("content"), str):
                        raise LLMClientError(
                            "llm_invalid_response",
                            len(attempted_models),
                            attempted_models,
                            "",
                            (time.perf_counter() - started) * 1000,
                        )
                    content = message["content"].strip()
                    if not content:
                        raise LLMClientError(
                            "llm_empty_response",
                            len(attempted_models),
                            attempted_models,
                            "",
                            (time.perf_counter() - started) * 1000,
                        )

                    input_tokens, output_tokens, total_tokens, usage_ok, usage_reason = _parse_usage(payload)
                    total_latency_ms = (time.perf_counter() - started) * 1000
                    return LLMResult(
                        content=content,
                        calls=len(attempted_models),
                        model=str(payload.get("model") or model),
                        input_tokens=input_tokens,
                        output_tokens=output_tokens,
                        total_tokens=total_tokens,
                        token_usage_available=usage_ok,
                        token_usage_missing_reason=usage_reason,
                        # In non-streaming mode the first observable token arrives with the response.
                        first_token_latency_ms=(time.perf_counter() - response_started) * 1000,
                        total_latency_ms=total_latency_ms,
                        attempted_models=list(attempted_models),
                        final_model=str(payload.get("model") or model),
                        fallback_reason=last_reason if len(attempted_models) > 1 else "",
                    )
                except httpx.TimeoutException as exc:
                    raise LLMClientError(
                        "llm_timeout",
                        len(attempted_models),
                        attempted_models,
                        "",
                        (time.perf_counter() - started) * 1000,
                    ) from exc
                except httpx.HTTPError as exc:
                    raise LLMClientError(
                        "llm_api_error",
                        len(attempted_models),
                        attempted_models,
                        "",
                        (time.perf_counter() - started) * 1000,
                    ) from exc

        raise LLMClientError(
            last_reason,
            len(attempted_models),
            attempted_models,
            "",
            (time.perf_counter() - started) * 1000,
        )
