from __future__ import annotations

import json
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterator

from sqlalchemy import Engine, create_engine, delete, func, select, text
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import QueuePool

from app.repositories.interfaces import RuntimeRepositories
from app.repositories.orm import (
    AnswerFeedbackRow,
    Base,
    ConversationSessionRow,
    ConversationTurnRow,
    EvaluationRecordRow,
    EvaluationRunRow,
    SolutionReuseEventRow,
    TraceMetadataRow,
    VerifiedSolutionRow,
)
from app.tracing import sanitize_trace


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _json_object(value: str | None) -> dict[str, Any]:
    try:
        parsed = json.loads(value or "{}")
    except (TypeError, json.JSONDecodeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _json_list(value: str | None) -> list[Any]:
    try:
        parsed = json.loads(value or "[]")
    except (TypeError, json.JSONDecodeError):
        return []
    return parsed if isinstance(parsed, list) else []


def _datetime(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, str) and value:
        try:
            parsed = datetime.fromisoformat(value)
            return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
        except ValueError:
            pass
    return _now()


class DatabaseSessionManager:
    """Short-lived SQLAlchemy sessions with explicit commit/rollback/close."""

    def __init__(self, factory: sessionmaker[Session]) -> None:
        self.factory = factory

    @contextmanager
    def transaction(self) -> Iterator[Session]:
        session = self.factory()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()


class SQLAlchemyConversationRepository:
    def __init__(self, sessions: DatabaseSessionManager) -> None:
        self.sessions = sessions

    def upsert_session(
        self, session_id: str, model: str, version: str, summary: str
    ) -> None:
        with self.sessions.transaction() as db:
            row = db.get(ConversationSessionRow, session_id)
            if row is None:
                row = ConversationSessionRow(session_id=session_id, updated_at=_now())
                db.add(row)
            row.model = model
            row.version = version
            row.summary = summary[-2000:]
            row.updated_at = _now()

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
    ) -> int:
        keep = max(int(max_turns), 1)
        with self.sessions.transaction() as db:
            row = ConversationTurnRow(
                session_id=session_id,
                model=model,
                version=version,
                question=question,
                answer=answer,
                selected_tool=selected_tool,
                source_chunk_ids=_json(source_chunk_ids),
                created_at=_now(),
            )
            db.add(row)
            db.flush()
            stale_ids = select(ConversationTurnRow.id).where(
                ConversationTurnRow.session_id == session_id
            ).order_by(ConversationTurnRow.id.desc()).offset(keep)
            db.execute(
                delete(ConversationTurnRow).where(
                    ConversationTurnRow.id.in_(stale_ids)
                )
            )
            return int(row.id)

    def get_recent_turns(
        self, session_id: str, *, limit: int = 2, ttl_hours: int = 24
    ) -> list[dict[str, Any]]:
        cutoff = _now() - timedelta(hours=max(int(ttl_hours), 0))
        with self.sessions.transaction() as db:
            rows = list(
                db.scalars(
                    select(ConversationTurnRow)
                    .where(
                        ConversationTurnRow.session_id == session_id,
                        ConversationTurnRow.created_at >= cutoff,
                    )
                    .order_by(ConversationTurnRow.id.desc())
                    .limit(max(int(limit), 0))
                )
            )
            result = [self._turn_dict(row) for row in reversed(rows)]
        return result

    def clear_session(self, session_id: str) -> int:
        with self.sessions.transaction() as db:
            result = db.execute(
                delete(ConversationTurnRow).where(
                    ConversationTurnRow.session_id == session_id
                )
            )
            db.execute(
                delete(ConversationSessionRow).where(
                    ConversationSessionRow.session_id == session_id
                )
            )
            return int(result.rowcount or 0)

    @staticmethod
    def _turn_dict(row: ConversationTurnRow) -> dict[str, Any]:
        return {
            "id": row.id,
            "session_id": row.session_id,
            "model": row.model,
            "version": row.version,
            "question": row.question,
            "answer": row.answer,
            "selected_tool": row.selected_tool,
            "source_chunk_ids": _json_list(row.source_chunk_ids),
            "created_at": row.created_at.isoformat(),
        }


class SQLAlchemyFeedbackRepository:
    def __init__(self, sessions: DatabaseSessionManager) -> None:
        self.sessions = sessions

    def save(self, payload: dict[str, Any]) -> int:
        with self.sessions.transaction() as db:
            row = AnswerFeedbackRow(
                session_id=payload.get("session_id", "demo"),
                question=payload["question"],
                answer=payload["answer"],
                helpful=bool(payload["helpful"]),
                reason=payload.get("reason", ""),
                selected_tool=payload.get("selected_tool", ""),
                source_chunk_ids=_json(payload.get("source_chunk_ids", [])),
                created_at=_now(),
            )
            db.add(row)
            db.flush()
            return int(row.id)

    def list_recent(self, limit: int = 20) -> list[dict[str, Any]]:
        with self.sessions.transaction() as db:
            rows = list(
                db.scalars(
                    select(AnswerFeedbackRow)
                    .order_by(AnswerFeedbackRow.id.desc())
                    .limit(max(int(limit), 0))
                )
            )
            return [
                {
                    "id": row.id,
                    "session_id": row.session_id,
                    "question": row.question,
                    "answer": row.answer,
                    "helpful": bool(row.helpful),
                    "reason": row.reason,
                    "selected_tool": row.selected_tool,
                    "source_chunk_ids": _json_list(row.source_chunk_ids),
                    "created_at": row.created_at.isoformat(),
                }
                for row in rows
            ]

    def metrics(self) -> dict[str, int | float | None]:
        with self.sessions.transaction() as db:
            total = int(db.scalar(select(func.count(AnswerFeedbackRow.id))) or 0)
            helpful = int(
                db.scalar(
                    select(func.count(AnswerFeedbackRow.id)).where(
                        AnswerFeedbackRow.helpful.is_(True)
                    )
                )
                or 0
            )
        return {
            "feedback_total": total,
            "helpful": helpful,
            "unhelpful": total - helpful,
            "helpful_rate": round(helpful / total, 4) if total else None,
        }


class SQLAlchemyVerifiedSolutionRepository:
    def __init__(self, sessions: DatabaseSessionManager) -> None:
        self.sessions = sessions

    def save(self, payload: dict[str, Any]) -> int:
        with self.sessions.transaction() as db:
            row = VerifiedSolutionRow(
                model=payload["model"],
                version=payload.get("version", ""),
                problem=payload["problem"],
                solution=payload["solution"],
                source_chunk_ids=_json(payload.get("source_chunk_ids", [])),
                confirmed_by=payload.get("confirmed_by", "user"),
                verified=True,
                created_at=_now(),
            )
            db.add(row)
            db.flush()
            return int(row.id)

    def list_recent(self, model: str, limit: int = 50) -> list[dict[str, Any]]:
        with self.sessions.transaction() as db:
            rows = list(
                db.scalars(
                    select(VerifiedSolutionRow)
                    .where(
                        VerifiedSolutionRow.verified.is_(True),
                        (VerifiedSolutionRow.model == model)
                        | (VerifiedSolutionRow.model == ""),
                    )
                    .order_by(VerifiedSolutionRow.id.desc())
                    .limit(max(int(limit), 0))
                )
            )
            return [
                {
                    "id": row.id,
                    "model": row.model,
                    "version": row.version,
                    "problem": row.problem,
                    "solution": row.solution,
                    "source_chunk_ids": _json_list(row.source_chunk_ids),
                    "confirmed_by": row.confirmed_by,
                    "verified": bool(row.verified),
                    "created_at": row.created_at.isoformat(),
                }
                for row in rows
            ]

    def record_reuse(
        self, solution_id: int, session_id: str, question: str
    ) -> None:
        with self.sessions.transaction() as db:
            db.add(
                SolutionReuseEventRow(
                    solution_id=solution_id,
                    session_id=session_id,
                    question=question,
                    created_at=_now(),
                )
            )

    def metrics(self) -> dict[str, int]:
        with self.sessions.transaction() as db:
            verified = int(
                db.scalar(
                    select(func.count(VerifiedSolutionRow.id)).where(
                        VerifiedSolutionRow.verified.is_(True)
                    )
                )
                or 0
            )
            reuse = int(db.scalar(select(func.count(SolutionReuseEventRow.id))) or 0)
        return {
            "verified_solutions": verified,
            "verified_solution_reuse": reuse,
        }


class SQLAlchemyTraceRepository:
    def __init__(self, sessions: DatabaseSessionManager) -> None:
        self.sessions = sessions

    def append_metadata(self, payload: dict[str, Any]) -> dict[str, Any]:
        clean = sanitize_trace(payload)
        rewritten = clean.get("rewritten_query") or clean.get("rewritten_queries") or ""
        if isinstance(rewritten, list):
            rewritten = rewritten[-1] if rewritten else ""
        token_usage = clean.get("token_usage", {})
        with self.sessions.transaction() as db:
            row = db.get(TraceMetadataRow, clean["request_id"])
            if row is None:
                row = TraceMetadataRow(request_id=clean["request_id"], created_at=_now())
                db.add(row)
            row.session_id = str(clean.get("session_id", ""))
            row.created_at = _datetime(clean.get("created_at"))
            row.status = str(clean.get("status", "completed"))
            row.error = str(clean.get("error", ""))
            row.query = str(clean.get("query") or clean.get("original_question", ""))
            row.rewritten_query = str(rewritten)
            row.selected_tool = str(clean.get("selected_tool", ""))
            row.model = str(clean.get("model") or clean.get("llm_model", ""))
            row.provider = str(clean.get("provider", ""))
            row.retrieval_latency_ms = float(clean.get("retrieval_latency_ms", 0.0) or 0.0)
            row.llm_latency_ms = float(clean.get("llm_latency_ms", 0.0) or 0.0)
            row.total_latency_ms = float(clean.get("total_latency_ms", 0.0) or 0.0)
            row.stop_reason = str(clean.get("stop_reason", ""))
            row.token_usage = _json(token_usage if isinstance(token_usage, dict) else {})
        return self.get_by_request_id(clean["request_id"]) or {}

    def get_by_request_id(self, request_id: str) -> dict[str, Any] | None:
        with self.sessions.transaction() as db:
            row = db.get(TraceMetadataRow, request_id)
            return self._dict(row) if row is not None else None

    def list_recent(self, limit: int = 20) -> list[dict[str, Any]]:
        return self.query(limit=limit)

    def query(
        self,
        *,
        session_id: str = "",
        status: str = "",
        has_error: bool | None = None,
        since: datetime | None = None,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        statement = select(TraceMetadataRow)
        if session_id:
            statement = statement.where(TraceMetadataRow.session_id == session_id)
        if status:
            statement = statement.where(TraceMetadataRow.status == status)
        if has_error is True:
            statement = statement.where(TraceMetadataRow.error != "")
        elif has_error is False:
            statement = statement.where(TraceMetadataRow.error == "")
        if since is not None:
            statement = statement.where(TraceMetadataRow.created_at >= _datetime(since))
        with self.sessions.transaction() as db:
            rows = list(
                db.scalars(
                    statement
                    .order_by(TraceMetadataRow.created_at.desc())
                    .limit(max(int(limit), 0))
                )
            )
            return [self._dict(row) for row in rows]

    @staticmethod
    def _dict(row: TraceMetadataRow) -> dict[str, Any]:
        return {
            "request_id": row.request_id,
            "session_id": row.session_id,
            "created_at": row.created_at.isoformat(),
            "status": row.status,
            "error": row.error,
            "query": row.query,
            "rewritten_query": row.rewritten_query,
            "selected_tool": row.selected_tool,
            "model": row.model,
            "provider": row.provider,
            "retrieval_latency_ms": row.retrieval_latency_ms,
            "llm_latency_ms": row.llm_latency_ms,
            "total_latency_ms": row.total_latency_ms,
            "stop_reason": row.stop_reason,
            "token_usage": _json_object(row.token_usage),
        }


class SQLAlchemyEvaluationRepository:
    def __init__(self, sessions: DatabaseSessionManager) -> None:
        self.sessions = sessions

    def create_run(
        self,
        name: str,
        *,
        metadata: dict[str, Any] | None = None,
        run_id: str | None = None,
    ) -> str:
        identifier = run_id or uuid.uuid4().hex
        with self.sessions.transaction() as db:
            row = db.get(EvaluationRunRow, identifier)
            if row is None:
                row = EvaluationRunRow(
                    id=identifier,
                    name=name,
                    status="running",
                    created_at=_now(),
                    completed_at=None,
                    metadata_json=_json(sanitize_trace(metadata or {})),
                    summary_json="{}",
                )
                db.add(row)
        return identifier

    def save_record(
        self,
        run_id: str,
        case_id: str,
        *,
        category: str,
        status: str,
        metrics: dict[str, Any] | None = None,
        error: str = "",
    ) -> int:
        with self.sessions.transaction() as db:
            row = db.scalar(
                select(EvaluationRecordRow).where(
                    EvaluationRecordRow.run_id == run_id,
                    EvaluationRecordRow.case_id == case_id,
                )
            )
            if row is None:
                row = EvaluationRecordRow(
                    run_id=run_id,
                    case_id=case_id,
                    created_at=_now(),
                )
                db.add(row)
            row.category = category
            row.status = status
            row.metrics_json = _json(sanitize_trace(metrics or {}))
            row.error = error
            db.flush()
            return int(row.id)

    def complete_run(
        self,
        run_id: str,
        *,
        status: str = "completed",
        summary: dict[str, Any] | None = None,
    ) -> None:
        with self.sessions.transaction() as db:
            row = db.get(EvaluationRunRow, run_id)
            if row is None:
                raise KeyError(f"evaluation run not found: {run_id}")
            row.status = status
            row.completed_at = _now()
            row.summary_json = _json(sanitize_trace(summary or {}))

    def get_run_summary(self, run_id: str) -> dict[str, Any] | None:
        with self.sessions.transaction() as db:
            row = db.get(EvaluationRunRow, run_id)
            if row is None:
                return None
            record_count = int(
                db.scalar(
                    select(func.count(EvaluationRecordRow.id)).where(
                        EvaluationRecordRow.run_id == run_id
                    )
                )
                or 0
            )
            return {
                "run_id": row.id,
                "name": row.name,
                "status": row.status,
                "created_at": row.created_at.isoformat(),
                "completed_at": row.completed_at.isoformat() if row.completed_at else None,
                "metadata": _json_object(row.metadata_json),
                "summary": _json_object(row.summary_json),
                "record_count": record_count,
            }


class RuntimeDatabase:
    def __init__(self, engine: Engine, backend: str, *, initialize_schema: bool) -> None:
        self.engine = engine
        self.backend = backend
        if initialize_schema:
            Base.metadata.create_all(engine)
        factory = sessionmaker(
            bind=engine,
            class_=Session,
            expire_on_commit=False,
            autoflush=True,
        )
        self.sessions = DatabaseSessionManager(factory)
        self.repositories = RuntimeRepositories(
            conversations=SQLAlchemyConversationRepository(self.sessions),
            feedback=SQLAlchemyFeedbackRepository(self.sessions),
            verified_solutions=SQLAlchemyVerifiedSolutionRepository(self.sessions),
            traces=SQLAlchemyTraceRepository(self.sessions),
            evaluations=SQLAlchemyEvaluationRepository(self.sessions),
        )

    def health(self) -> dict[str, str]:
        try:
            with self.engine.connect() as connection:
                connection.execute(text("SELECT 1"))
            return {"backend": self.backend, "status": "ok", "error_type": ""}
        except Exception as exc:
            return {
                "backend": self.backend,
                "status": "unavailable",
                "error_type": type(exc).__name__,
            }

    def close(self) -> None:
        self.engine.dispose()


def normalize_postgres_dsn(dsn: str) -> str:
    value = dsn.strip()
    if value.startswith("postgres://"):
        return "postgresql+psycopg://" + value[len("postgres://") :]
    if value.startswith("postgresql://"):
        return "postgresql+psycopg://" + value[len("postgresql://") :]
    return value


def create_runtime_database(
    *,
    backend: str,
    sqlite_path: Path,
    postgres_dsn: str = "",
    pool_size: int = 5,
    max_overflow: int = 10,
    pool_timeout_seconds: float = 30.0,
    connect_timeout_seconds: float = 3.0,
    initialize_schema: bool | None = None,
) -> RuntimeDatabase:
    selected = backend.strip().lower()
    if selected not in {"sqlite", "postgres"}:
        raise ValueError("DATABASE_BACKEND must be 'sqlite' or 'postgres'")
    if selected == "sqlite":
        path = sqlite_path.resolve()
        path.parent.mkdir(parents=True, exist_ok=True)
        url = f"sqlite+pysqlite:///{path.as_posix()}"
        engine = create_engine(
            url,
            connect_args={"check_same_thread": False},
            poolclass=QueuePool,
            pool_size=max(int(pool_size), 1),
            max_overflow=max(int(max_overflow), 0),
            pool_timeout=max(float(pool_timeout_seconds), 0.1),
            pool_pre_ping=True,
        )
    else:
        url = normalize_postgres_dsn(postgres_dsn)
        if not url:
            raise ValueError("POSTGRES_DSN is required when DATABASE_BACKEND=postgres")
        if not url.startswith("postgresql+psycopg://"):
            raise ValueError("POSTGRES_DSN must use a PostgreSQL URL")
        engine = create_engine(
            url,
            connect_args={
                "connect_timeout": max(int(float(connect_timeout_seconds)), 1)
            },
            pool_size=max(int(pool_size), 1),
            max_overflow=max(int(max_overflow), 0),
            pool_timeout=max(float(pool_timeout_seconds), 0.1),
            pool_pre_ping=True,
        )
    should_initialize = selected == "sqlite" if initialize_schema is None else initialize_schema
    return RuntimeDatabase(engine, selected, initialize_schema=should_initialize)


def create_runtime_database_from_settings(settings: Any) -> RuntimeDatabase:
    return create_runtime_database(
        backend=settings.database_backend,
        sqlite_path=settings.sqlite_path,
        postgres_dsn=settings.postgres_dsn,
        pool_size=settings.database_pool_size,
        max_overflow=settings.database_max_overflow,
        pool_timeout_seconds=settings.database_pool_timeout_seconds,
        connect_timeout_seconds=settings.database_connect_timeout_seconds,
    )
