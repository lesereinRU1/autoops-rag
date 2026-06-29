from __future__ import annotations

import time
from dataclasses import dataclass
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


class LLMClientError(RuntimeError):
    def __init__(self, reason: str, attempts: int) -> None:
        super().__init__(reason)
        self.reason = reason
        self.attempts = attempts


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


class LLMClient:
    """Small non-streaming OpenAI-compatible client used by the RAG generator."""

    def __init__(self, base_url: str, api_key: str, model: str, timeout: float) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.timeout = timeout

    def generate(self, prompt: str, retries: int = 1) -> LLMResult:
        url = self.base_url + "/chat/completions"
        started = time.perf_counter()
        attempts = 0
        last_reason = "llm_api_error"

        for attempt in range(retries + 1):
            attempts += 1
            response_started = time.perf_counter()
            try:
                # The desktop environment may expose a stale HTTPS proxy. DashScope
                # works over a direct TLS connection here, so do not inherit proxy
                # variables that can terminate the handshake before any HTTP response.
                with httpx.Client(timeout=self.timeout, trust_env=False) as client:
                    response = client.post(
                        url,
                        headers={
                            "Authorization": f"Bearer {self.api_key}",
                            "Content-Type": "application/json",
                        },
                        json={
                            "model": self.model,
                            "messages": [{"role": "user", "content": prompt}],
                            "temperature": 0.1,
                            "stream": False,
                        },
                    )
                response.raise_for_status()
                try:
                    payload = response.json()
                except (TypeError, ValueError):
                    last_reason = "llm_invalid_response"
                    raise LLMClientError(last_reason, attempts)
                if not isinstance(payload, dict):
                    last_reason = "llm_invalid_response"
                    raise LLMClientError(last_reason, attempts)

                choices = payload.get("choices")
                if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
                    last_reason = "llm_invalid_response"
                    raise LLMClientError(last_reason, attempts)
                message = choices[0].get("message")
                if not isinstance(message, dict) or not isinstance(message.get("content"), str):
                    last_reason = "llm_invalid_response"
                    raise LLMClientError(last_reason, attempts)
                content = message["content"].strip()
                if not content:
                    last_reason = "llm_empty_response"
                    raise LLMClientError(last_reason, attempts)

                input_tokens, output_tokens, total_tokens, usage_ok, usage_reason = _parse_usage(payload)
                total_latency_ms = (time.perf_counter() - started) * 1000
                return LLMResult(
                    content=content,
                    calls=attempts,
                    model=str(payload.get("model") or self.model),
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    total_tokens=total_tokens,
                    token_usage_available=usage_ok,
                    token_usage_missing_reason=usage_reason,
                    # In non-streaming mode the first observable token arrives with the response.
                    first_token_latency_ms=(time.perf_counter() - response_started) * 1000,
                    total_latency_ms=total_latency_ms,
                )
            except httpx.TimeoutException:
                last_reason = "llm_timeout"
            except httpx.HTTPError:
                last_reason = "llm_api_error"
            except LLMClientError as exc:
                last_reason = exc.reason

            if attempt < retries:
                time.sleep(0.25 * (attempt + 1))

        raise LLMClientError(last_reason, attempts)
