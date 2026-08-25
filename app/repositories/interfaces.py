from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol


class ConversationRepository(Protocol):
    def upsert_session(
        self, session_id: str, model: str, version: str, summary: str
    ) -> None: ...

    def append_turn(
        self,
        session_id: str,
        model: str,
        version: str,
        question: str,
        answer: str,
        selected_tool: str,
        source_chunk_ids: list[str],
        *,
        max_turns: int = 20,
    ) -> int: ...

    def get_recent_turns(
        self, session_id: str, *, limit: int = 2, ttl_hours: int = 24
    ) -> list[dict[str, Any]]: ...

    def clear_session(self, session_id: str) -> int: ...


class FeedbackRepository(Protocol):
    def save(self, payload: dict[str, Any]) -> int: ...

    def list_recent(self, limit: int = 20) -> list[dict[str, Any]]: ...

    def metrics(self) -> dict[str, int | float | None]: ...


class VerifiedSolutionRepository(Protocol):
    def save(self, payload: dict[str, Any]) -> int: ...

    def list_recent(self, model: str, limit: int = 50) -> list[dict[str, Any]]: ...

    def record_reuse(
        self, solution_id: int, session_id: str, question: str
    ) -> None: ...

    def metrics(self) -> dict[str, int]: ...


class TraceRepository(Protocol):
    def append_metadata(self, payload: dict[str, Any]) -> dict[str, Any]: ...

    def get_by_request_id(self, request_id: str) -> dict[str, Any] | None: ...

    def list_recent(self, limit: int = 20) -> list[dict[str, Any]]: ...

    def query(
        self,
        *,
        session_id: str = "",
        status: str = "",
        has_error: bool | None = None,
        since: datetime | None = None,
        limit: int = 20,
    ) -> list[dict[str, Any]]: ...


class EvaluationRepository(Protocol):
    def create_run(
        self,
        name: str,
        *,
        metadata: dict[str, Any] | None = None,
        run_id: str | None = None,
    ) -> str: ...

    def save_record(
        self,
        run_id: str,
        case_id: str,
        *,
        category: str,
        status: str,
        metrics: dict[str, Any] | None = None,
        error: str = "",
    ) -> int: ...

    def complete_run(
        self,
        run_id: str,
        *,
        status: str = "completed",
        summary: dict[str, Any] | None = None,
    ) -> None: ...

    def get_run_summary(self, run_id: str) -> dict[str, Any] | None: ...


@dataclass(frozen=True)
class RuntimeRepositories:
    conversations: ConversationRepository
    feedback: FeedbackRepository
    verified_solutions: VerifiedSolutionRepository
    traces: TraceRepository
    evaluations: EvaluationRepository
