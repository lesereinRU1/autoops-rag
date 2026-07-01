from __future__ import annotations

import json
import re
import threading
from pathlib import Path
from typing import Any


_SENSITIVE_KEY_PARTS = ("api_key", "apikey", "authorization", "secret", "password")
_SENSITIVE_TEXT_PATTERNS = (
    re.compile(r"\b(?:LLM_)?API[_-]?KEY\b\s*[:=]\s*\S+", re.I),
    re.compile(r"\bAuthorization\b\s*[:=]\s*(?:Bearer\s+)?\S+", re.I),
    re.compile(r"\bBearer\s+[A-Za-z0-9._~-]+", re.I),
    re.compile(r"\bsk-[A-Za-z0-9_-]+", re.I),
)


def sanitize_trace(value: Any) -> Any:
    """Remove credential-shaped fields before a trace reaches disk or an API response."""
    if isinstance(value, dict):
        clean: dict[str, Any] = {}
        for key, item in value.items():
            normalized = str(key).lower().replace("-", "_")
            if any(part in normalized for part in _SENSITIVE_KEY_PARTS):
                continue
            else:
                clean[str(key)] = sanitize_trace(item)
        return clean
    if isinstance(value, list):
        return [sanitize_trace(item) for item in value]
    if isinstance(value, tuple):
        return [sanitize_trace(item) for item in value]
    if isinstance(value, str):
        clean_text = value
        for pattern in _SENSITIVE_TEXT_PATTERNS:
            clean_text = pattern.sub("[REDACTED]", clean_text)
        return clean_text
    return value


class TraceStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    def append(self, trace: dict[str, Any]) -> dict[str, Any]:
        clean = sanitize_trace(trace)
        serialized = json.dumps(clean, ensure_ascii=False, separators=(",", ":"))
        with self._lock:
            with self.path.open("a", encoding="utf-8", newline="\n") as handle:
                handle.write(serialized + "\n")
        return clean

    def recent(self, limit: int = 20) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        with self._lock:
            lines = self.path.read_text(encoding="utf-8").splitlines()
        traces: list[dict[str, Any]] = []
        for line in reversed(lines):
            if not line.strip():
                continue
            try:
                value = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(value, dict):
                traces.append(value)
            if len(traces) >= limit:
                break
        return traces

    def get(self, request_id: str) -> dict[str, Any] | None:
        return next(
            (trace for trace in self.recent(limit=10_000) if trace.get("request_id") == request_id),
            None,
        )
