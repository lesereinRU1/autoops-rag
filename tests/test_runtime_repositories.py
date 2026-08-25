from __future__ import annotations

import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from app.agent.memory import MemoryStore
from app.config import Settings
from app.repositories import DatabaseSessionManager, create_runtime_database
from app.repositories.orm import Base
from scripts import run_formal_eval


def _database(tmp_path: Path):
    return create_runtime_database(
        backend="sqlite",
        sqlite_path=tmp_path / "runtime.db",
        pool_size=2,
        max_overflow=0,
    )


def _exercise_contract(database) -> None:
    repositories = database.repositories
    conversations = repositories.conversations
    conversations.upsert_session("contract-session", "S7-1200", "V4.6", "first")
    conversations.upsert_session("contract-session", "S7-1200", "V4.6", "updated")
    conversations.append_turn(
        "contract-session",
        "S7-1200",
        "V4.6",
        "question one",
        "answer one",
        "search_manual",
        ["chunk-1"],
    )
    conversations.append_turn(
        "contract-session",
        "S7-1200",
        "V4.6",
        "question two",
        "answer two",
        "lookup_parameter",
        ["chunk-2"],
    )
    turns = conversations.get_recent_turns(
        "contract-session", limit=2, ttl_hours=24
    )
    assert [turn["question"] for turn in turns] == ["question one", "question two"]
    assert turns[0]["source_chunk_ids"] == ["chunk-1"]

    feedback_id = repositories.feedback.save(
        {
            "session_id": "contract-session",
            "question": "question two",
            "answer": "answer two",
            "helpful": True,
            "reason": "grounded",
            "selected_tool": "lookup_parameter",
            "source_chunk_ids": ["chunk-2"],
        }
    )
    assert feedback_id > 0
    assert repositories.feedback.list_recent(1)[0]["helpful"] is True
    assert repositories.feedback.metrics()["helpful_rate"] == 1.0

    solution_id = repositories.verified_solutions.save(
        {
            "model": "S7-1200",
            "version": "V4.6",
            "problem": "16#80C8 communication timeout",
            "solution": "check the connection",
            "source_chunk_ids": ["chunk-1"],
            "confirmed_by": "contract-test",
        }
    )
    solutions = repositories.verified_solutions.list_recent("S7-1200", 10)
    assert solutions[0]["id"] == solution_id
    repositories.verified_solutions.record_reuse(
        solution_id, "contract-session", "same problem"
    )
    assert repositories.verified_solutions.metrics() == {
        "verified_solutions": 1,
        "verified_solution_reuse": 1,
    }

    trace = repositories.traces.append_metadata(
        {
            "request_id": "request-contract",
            "session_id": "contract-session",
            "created_at": "2026-08-25T12:00:00+00:00",
            "status": "completed",
            "query": "question two",
            "rewritten_queries": ["rewritten question"],
            "selected_tool": "lookup_parameter",
            "model": "qwen-plus",
            "provider": "fixture",
            "retrieval_latency_ms": 4.5,
            "llm_latency_ms": 10.0,
            "total_latency_ms": 20.0,
            "stop_reason": "evidence_sufficient",
            "token_usage": {"total_tokens": 30},
            "llm_api_key": "must-not-persist",
        }
    )
    assert trace["rewritten_query"] == "rewritten question"
    assert trace["token_usage"] == {"total_tokens": 30}
    assert "api_key" not in trace
    assert repositories.traces.get_by_request_id("request-contract") == trace
    assert repositories.traces.list_recent(1)[0]["request_id"] == "request-contract"
    assert repositories.traces.query(
        session_id="contract-session",
        status="completed",
        has_error=False,
        since=datetime(2026, 8, 25, 11, 0, tzinfo=timezone.utc),
    )[0]["request_id"] == "request-contract"

    run_id = repositories.evaluations.create_run(
        "contract evaluation",
        run_id="run-contract",
        metadata={"split": "test"},
    )
    first_record = repositories.evaluations.save_record(
        run_id,
        "case-1",
        category="semantic_query",
        status="completed",
        metrics={"recall@5": 1.0},
    )
    repeated_record = repositories.evaluations.save_record(
        run_id,
        "case-1",
        category="semantic_query",
        status="completed",
        metrics={"recall@5": 0.8},
    )
    assert first_record == repeated_record
    repositories.evaluations.complete_run(
        run_id, summary={"records": 1, "recall@5": 0.8}
    )
    summary = repositories.evaluations.get_run_summary(run_id)
    assert summary is not None
    assert summary["status"] == "completed"
    assert summary["record_count"] == 1
    assert summary["summary"]["recall@5"] == 0.8

    assert conversations.clear_session("contract-session") == 2
    assert conversations.get_recent_turns("contract-session") == []


def test_sqlite_repository_contract(tmp_path):
    database = _database(tmp_path)
    try:
        _exercise_contract(database)
        assert database.health() == {
            "backend": "sqlite",
            "status": "ok",
            "error_type": "",
        }
    finally:
        database.close()


def test_runtime_repository_sessions_return_connections_to_pool(tmp_path):
    database = _database(tmp_path)
    try:
        database.repositories.feedback.metrics()
        assert database.engine.pool.checkedout() == 0
    finally:
        database.close()


def test_session_manager_rolls_back_and_closes_when_commit_fails():
    class FailingSession:
        rollback_called = False
        close_called = False

        def commit(self):
            raise RuntimeError("commit failed")

        def rollback(self):
            self.rollback_called = True

        def close(self):
            self.close_called = True

    session = FailingSession()
    manager = DatabaseSessionManager(lambda: session)  # type: ignore[arg-type]
    with pytest.raises(RuntimeError, match="commit failed"):
        with manager.transaction():
            pass
    assert session.rollback_called is True
    assert session.close_called is True


def test_memory_store_keeps_static_and_runtime_compatibility(tmp_path):
    seed = Path(__file__).resolve().parents[1] / "data" / "seed"
    path = tmp_path / "combined-compatible.db"
    memory = MemoryStore(path, seed)
    try:
        memory.save_turn(
            "memory-session",
            "S7-1200",
            "",
            "question",
            "answer",
            "search_manual",
            ["chunk-1"],
        )
        assert memory.lookup_alarm("80C8") is not None
        assert memory.recent_turns("memory-session")[0]["question"] == "question"
        with sqlite3.connect(path) as connection:
            tables = {
                row[0]
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                )
            }
        assert {"alarm_codes", "parameters", "kg_nodes", "kg_edges"} <= tables
        assert {"conversation_memory", "conversation_turns", "trace_metadata"} <= tables
    finally:
        memory.close()


def test_database_backend_config_defaults_to_sqlite():
    settings = Settings(_env_file=None)
    assert settings.database_backend == "sqlite"
    assert settings.postgres_dsn == ""


def test_database_backend_config_accepts_postgres():
    settings = Settings(
        _env_file=None,
        database_backend="postgres",
        postgres_dsn="postgresql://user:password@localhost:5432/autoops",
    )
    assert settings.database_backend == "postgres"


def test_database_backend_config_rejects_unknown_value():
    with pytest.raises(ValidationError):
        Settings(_env_file=None, database_backend="mysql")


def test_postgres_engine_is_lazy_and_uses_psycopg(tmp_path):
    database = create_runtime_database(
        backend="postgres",
        sqlite_path=tmp_path / "unused.db",
        postgres_dsn="postgresql://user:password@127.0.0.1:5432/autoops",
        initialize_schema=False,
    )
    try:
        assert database.backend == "postgres"
        assert database.engine.dialect.name == "postgresql"
        assert database.engine.url.drivername == "postgresql+psycopg"
    finally:
        database.close()


def test_postgres_backend_requires_valid_dsn(tmp_path):
    with pytest.raises(ValueError, match="POSTGRES_DSN is required"):
        create_runtime_database(
            backend="postgres",
            sqlite_path=tmp_path / "unused.db",
            postgres_dsn="",
        )
    with pytest.raises(ValueError, match="PostgreSQL URL"):
        create_runtime_database(
            backend="postgres",
            sqlite_path=tmp_path / "unused.db",
            postgres_dsn="sqlite:///not-postgres.db",
        )


def test_formal_evaluation_keeps_reports_and_persists_only_metadata(
    monkeypatch, tmp_path
):
    path = tmp_path / "evaluation-runtime.db"
    settings = SimpleNamespace(
        database_backend="sqlite",
        sqlite_path=path,
        postgres_dsn="",
        database_pool_size=2,
        database_max_overflow=0,
        database_pool_timeout_seconds=5.0,
        database_connect_timeout_seconds=1.0,
    )
    monkeypatch.setattr(run_formal_eval, "get_settings", lambda: settings)
    report = {
        "status": "completed",
        "run_id": "formal-run-test",
        "generated_at": "2026-08-25T12:00:00+00:00",
        "dataset": {"selected_split": "test"},
        "ready_for_resume_accuracy_claim": False,
        "metrics": {"strict_recall@5": 0.8},
        "metric_denominators": {"answerable": 1},
        "details": [
            {
                "id": "case-1",
                "category": "semantic_query",
                "http_status": 200,
                "strict_recall@5": 1.0,
                "answer": "large answer remains in the JSON report only",
            }
        ],
    }
    assert run_formal_eval.persist_evaluation_metadata(report) is True

    database = create_runtime_database(backend="sqlite", sqlite_path=path)
    try:
        summary = database.repositories.evaluations.get_run_summary(
            "formal-run-test"
        )
        assert summary is not None
        assert summary["record_count"] == 1
        with sqlite3.connect(path) as connection:
            stored = connection.execute(
                "SELECT metrics_json FROM evaluation_records WHERE case_id='case-1'"
            ).fetchone()[0]
        assert "strict_recall@5" in stored
        assert "large answer" not in stored
    finally:
        database.close()


@pytest.mark.postgres_integration
def test_postgres_repository_contract_when_dedicated_test_dsn_is_provided(tmp_path):
    dsn = os.getenv("AUTOOPS_POSTGRES_TEST_DSN", "").strip()
    if not dsn:
        pytest.skip("AUTOOPS_POSTGRES_TEST_DSN is not configured")
    database_name = dsn.rsplit("/", 1)[-1].split("?", 1)[0].lower()
    if "test" not in database_name:
        pytest.skip("refusing DDL unless the PostgreSQL database name contains 'test'")
    database = create_runtime_database(
        backend="postgres",
        sqlite_path=tmp_path / "unused.db",
        postgres_dsn=dsn,
        initialize_schema=True,
    )
    try:
        _exercise_contract(database)
    finally:
        Base.metadata.drop_all(database.engine)
        database.close()
