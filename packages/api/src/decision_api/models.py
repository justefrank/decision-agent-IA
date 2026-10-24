"""Tables du schéma `app` (SQLAlchemy Core). La migration Alembic 0001 en est la définition faisant foi."""

from __future__ import annotations

from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    MetaData,
    Numeric,
    Table,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID

metadata = MetaData(schema="app")

conversation = Table(
    "conversation",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True),
    Column("user_id", Text, nullable=False),  # claim sub, sans FK (pas de table utilisateurs)
    Column("title", Text),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("updated_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
)

message = Table(
    "message",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True),
    Column(
        "conversation_id",
        UUID(as_uuid=True),
        ForeignKey("app.conversation.id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column("role", Text, nullable=False),  # user | assistant
    Column("content", Text, nullable=False),
    Column("structured_json", JSONB),
    Column("trace_id", Text),
    Column("latency_ms", Integer),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
)

query_log = Table(
    "query_log",
    metadata,
    Column("id", BigInteger, primary_key=True, autoincrement=True),
    Column("ts", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("trace_id", Text, nullable=False),
    Column("step", Integer, nullable=False),
    Column("attempt", Integer, nullable=False, server_default="0"),
    Column("user_ref", Text),
    Column("conversation_id", UUID(as_uuid=True)),
    Column("question_hash", Text),
    Column("tool", Text, nullable=False),
    Column("status", Text, nullable=False),
    Column("error_class", Text),
    Column("sql", Text),
    Column("row_count", Integer),
    Column("truncated", Boolean),
    Column("duration_ms", Integer, nullable=False),
    Column("model_requested", Text),
    Column("model_served", Text),
    Column("effort", Text),
    Column("stop_reason", Text),
    Column("request_id", Text),
    Column("ttft_ms", Integer),
    Column("tokens_in", Integer),
    Column("tokens_out", Integer),
    Column("tokens_cache_read", Integer),
    Column("tokens_cache_write", Integer),
    Column("cost_usd", Numeric(10, 6)),
    Column("prompt_version", Text),
    Column("semantic_version", Text),
)

feedback = Table(
    "feedback",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True),
    Column("ts", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("user_id", Text, nullable=False),
    Column(
        "message_id", UUID(as_uuid=True), ForeignKey("app.message.id", ondelete="CASCADE"), nullable=False
    ),
    Column("category", Text, nullable=False),
    Column("comment", Text),
    Column("consent_question", Boolean, nullable=False, server_default="false"),
    Column("question_text", Text),
    Column("status", Text, nullable=False, server_default="nouveau"),
    Column("reject_reason", Text),
    Column("promoted_to_dev", Boolean, nullable=False, server_default="false"),
    Column("handled_by", Text),
    Column("handled_at", DateTime(timezone=True)),
)

eval_run = Table(
    "eval_run",
    metadata,
    Column("id", BigInteger, primary_key=True, autoincrement=True),
    Column("ts", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("split", Text, nullable=False),
    Column("prompt_version", Text),
    Column("semantic_version", Text),
    Column("model_id", Text),
    Column("git_sha", Text),
    Column("data_hash", Text),
    Column("reference_date", Date),
    Column("n", Integer, nullable=False),
    Column("n_correct", Integer, nullable=False),
    Column("ci_low", Float),
    Column("ci_high", Float),
    Column("cache_off", Boolean, nullable=False, server_default="false"),
    Column("pass3", Float),
    Column("pass1", Float),
    Column("ablation", Text),
    Column("report", JSONB),
)

eval_result = Table(
    "eval_result",
    metadata,
    Column("id", BigInteger, primary_key=True, autoincrement=True),
    Column("run_id", BigInteger, ForeignKey("app.eval_run.id", ondelete="CASCADE"), nullable=False),
    Column("question_id", Text, nullable=False),
    Column("category", Text),
    Column("trap", Text),
    Column("passes", Integer, nullable=False),
    Column("expected", JSONB),
    Column("got", JSONB),
)

audit_access_log = Table(
    "audit_access_log",
    metadata,
    Column("id", BigInteger, primary_key=True, autoincrement=True),
    Column("ts", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("actor_sub", Text, nullable=False),
    Column("actor_role", Text, nullable=False),
    Column("action", Text, nullable=False),
    Column("target_trace_id", Text),
    Column("details", JSONB),
)

analysis = Table(
    "analysis",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True),
    Column("ts", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("period_start", Date, nullable=False),
    Column("period_end", Date, nullable=False),
    Column("region", Text),
    Column("semantic_version", Text, nullable=False),
    Column("model_id", Text),
    Column("payload", JSONB, nullable=False),
    Column("data_hash", Text, nullable=False),
    Column("trace_id", Text),
)
