"""create runtime data repositories

Revision ID: 20260825_0001
Revises:
Create Date: 2026-08-25
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import context, op


revision: str = "20260825_0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _create_table(name: str, *columns, **kwargs) -> bool:
    existing = (
        set()
        if context.is_offline_mode()
        else set(sa.inspect(op.get_bind()).get_table_names())
    )
    if name in existing:
        return False
    op.create_table(name, *columns, **kwargs)
    return True


def _create_index(name: str, table: str, columns: list[str]) -> None:
    existing = (
        set()
        if context.is_offline_mode()
        else {
            item["name"]
            for item in sa.inspect(op.get_bind()).get_indexes(table)
        }
    )
    if name not in existing:
        op.create_index(name, table, columns, unique=False)


def upgrade() -> None:
    _create_table(
        "conversation_memory",
        sa.Column("session_id", sa.String(length=128), primary_key=True),
        sa.Column("model", sa.String(length=128), nullable=False),
        sa.Column("version", sa.String(length=128), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    _create_index(
        "ix_conversation_memory_updated_at", "conversation_memory", ["updated_at"]
    )

    _create_table(
        "conversation_turns",
        sa.Column("id", sa.Integer(), autoincrement=True, primary_key=True),
        sa.Column("session_id", sa.String(length=128), nullable=False),
        sa.Column("model", sa.String(length=128), nullable=False),
        sa.Column("version", sa.String(length=128), nullable=False),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("answer", sa.Text(), nullable=False),
        sa.Column("selected_tool", sa.String(length=128), nullable=False),
        sa.Column("source_chunk_ids", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    _create_index("ix_conversation_turns_session_id", "conversation_turns", ["session_id"])
    _create_index("ix_conversation_turns_created_at", "conversation_turns", ["created_at"])
    _create_index(
        "ix_conversation_turns_session_created",
        "conversation_turns",
        ["session_id", "created_at"],
    )

    _create_table(
        "verified_solutions",
        sa.Column("id", sa.Integer(), autoincrement=True, primary_key=True),
        sa.Column("model", sa.String(length=128), nullable=False),
        sa.Column("version", sa.String(length=128), nullable=False),
        sa.Column("problem", sa.Text(), nullable=False),
        sa.Column("solution", sa.Text(), nullable=False),
        sa.Column("source_chunk_ids", sa.Text(), nullable=False),
        sa.Column("confirmed_by", sa.String(length=128), nullable=False),
        sa.Column("verified", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    _create_index("ix_verified_solutions_model", "verified_solutions", ["model"])
    _create_index("ix_verified_solutions_verified", "verified_solutions", ["verified"])
    _create_index("ix_verified_solutions_created_at", "verified_solutions", ["created_at"])

    _create_table(
        "answer_feedback",
        sa.Column("id", sa.Integer(), autoincrement=True, primary_key=True),
        sa.Column("session_id", sa.String(length=128), nullable=False),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("answer", sa.Text(), nullable=False),
        sa.Column("helpful", sa.Boolean(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("selected_tool", sa.String(length=128), nullable=False),
        sa.Column("source_chunk_ids", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    _create_index("ix_answer_feedback_session_id", "answer_feedback", ["session_id"])
    _create_index("ix_answer_feedback_helpful", "answer_feedback", ["helpful"])
    _create_index("ix_answer_feedback_created_at", "answer_feedback", ["created_at"])

    _create_table(
        "solution_reuse_events",
        sa.Column("id", sa.Integer(), autoincrement=True, primary_key=True),
        sa.Column("solution_id", sa.Integer(), nullable=False),
        sa.Column("session_id", sa.String(length=128), nullable=False),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    _create_index("ix_solution_reuse_events_solution_id", "solution_reuse_events", ["solution_id"])
    _create_index("ix_solution_reuse_events_session_id", "solution_reuse_events", ["session_id"])
    _create_index("ix_solution_reuse_events_created_at", "solution_reuse_events", ["created_at"])

    _create_table(
        "trace_metadata",
        sa.Column("request_id", sa.String(length=128), primary_key=True),
        sa.Column("session_id", sa.String(length=128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("error", sa.Text(), nullable=False),
        sa.Column("query", sa.Text(), nullable=False),
        sa.Column("rewritten_query", sa.Text(), nullable=False),
        sa.Column("selected_tool", sa.String(length=128), nullable=False),
        sa.Column("model", sa.String(length=128), nullable=False),
        sa.Column("provider", sa.String(length=128), nullable=False),
        sa.Column("retrieval_latency_ms", sa.Float(), nullable=False),
        sa.Column("llm_latency_ms", sa.Float(), nullable=False),
        sa.Column("total_latency_ms", sa.Float(), nullable=False),
        sa.Column("stop_reason", sa.String(length=128), nullable=False),
        sa.Column("token_usage", sa.Text(), nullable=False),
    )
    _create_index("ix_trace_metadata_session_id", "trace_metadata", ["session_id"])
    _create_index("ix_trace_metadata_created_at", "trace_metadata", ["created_at"])
    _create_index("ix_trace_metadata_status", "trace_metadata", ["status"])
    _create_index("ix_trace_metadata_selected_tool", "trace_metadata", ["selected_tool"])
    _create_index(
        "ix_trace_metadata_session_created",
        "trace_metadata",
        ["session_id", "created_at"],
    )

    _create_table(
        "evaluation_runs",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("metadata_json", sa.Text(), nullable=False),
        sa.Column("summary_json", sa.Text(), nullable=False),
    )
    _create_index("ix_evaluation_runs_status", "evaluation_runs", ["status"])
    _create_index("ix_evaluation_runs_created_at", "evaluation_runs", ["created_at"])

    _create_table(
        "evaluation_records",
        sa.Column("id", sa.Integer(), autoincrement=True, primary_key=True),
        sa.Column(
            "run_id",
            sa.String(length=64),
            sa.ForeignKey("evaluation_runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("case_id", sa.String(length=128), nullable=False),
        sa.Column("category", sa.String(length=128), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("metrics_json", sa.Text(), nullable=False),
        sa.Column("error", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "run_id", "case_id", name="uq_evaluation_record_run_case"
        ),
    )
    _create_index("ix_evaluation_records_run_id", "evaluation_records", ["run_id"])
    _create_index("ix_evaluation_records_category", "evaluation_records", ["category"])
    _create_index("ix_evaluation_records_status", "evaluation_records", ["status"])
    _create_index("ix_evaluation_records_created_at", "evaluation_records", ["created_at"])


def downgrade() -> None:
    existing = (
        {
            "evaluation_records",
            "evaluation_runs",
            "trace_metadata",
            "solution_reuse_events",
            "answer_feedback",
            "verified_solutions",
            "conversation_turns",
            "conversation_memory",
        }
        if context.is_offline_mode()
        else set(sa.inspect(op.get_bind()).get_table_names())
    )
    for table in (
        "evaluation_records",
        "evaluation_runs",
        "trace_metadata",
        "solution_reuse_events",
        "answer_feedback",
        "verified_solutions",
        "conversation_turns",
        "conversation_memory",
    ):
        if table in existing:
            op.drop_table(table)
