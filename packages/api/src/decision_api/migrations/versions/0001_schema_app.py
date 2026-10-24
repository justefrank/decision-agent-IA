"""Schéma app initial (MVP v5) et droits de app_rw.

Révision : 0001
Précédente :
Exécutée par app_owner (propriétaire du schéma app, créé par infra/postgres/init).
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

UPGRADE = r"""
CREATE TABLE app.conversation (
    id          uuid PRIMARY KEY,
    user_id     text NOT NULL,                       -- claim sub (Keycloak), sans FK
    title       text,
    created_at  timestamptz NOT NULL DEFAULT now(),
    updated_at  timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX conversation_user_created_idx ON app.conversation (user_id, created_at DESC);
CREATE INDEX conversation_user_updated_idx ON app.conversation (user_id, updated_at DESC);

CREATE TABLE app.message (
    id               uuid PRIMARY KEY,
    conversation_id  uuid NOT NULL REFERENCES app.conversation (id) ON DELETE CASCADE,
    role             text NOT NULL CHECK (role IN ('user', 'assistant')),
    content          text NOT NULL,
    structured_json  jsonb,                          -- AssistantMessage complet (filtré à la lecture)
    trace_id         text,
    latency_ms       integer CHECK (latency_ms IS NULL OR latency_ms >= 0),
    created_at       timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX message_conversation_created_idx ON app.message (conversation_id, created_at);
CREATE INDEX message_created_idx ON app.message (created_at) WHERE role = 'assistant';

-- Journal technique en ajout seul : une ligne par appel d'outil ou par appel LLM (tool = 'llm').
CREATE TABLE app.query_log (
    id                  bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    ts                  timestamptz NOT NULL DEFAULT now(),
    trace_id            text NOT NULL,
    step                integer NOT NULL,
    attempt             integer NOT NULL DEFAULT 0,
    user_ref            text,                        -- HMAC-SHA256(sub, log_pseudonym_key)
    conversation_id     uuid,                        -- sans FK : le journal survit à la suppression
    question_hash       text,                        -- HMAC-SHA256 de la question ; jamais le texte
    tool                text NOT NULL,
    status              text NOT NULL CHECK (status IN ('ok', 'error', 'blocked')),
    error_class         text,
    sql                 text,
    row_count           integer,
    truncated           boolean,
    duration_ms         integer NOT NULL CHECK (duration_ms >= 0),
    model_requested     text,
    model_served        text,
    effort              text,
    stop_reason         text,
    request_id          text,
    ttft_ms             integer,
    tokens_in           integer,
    tokens_out          integer,
    tokens_cache_read   integer,
    tokens_cache_write  integer,
    cost_usd            numeric(10, 6),
    prompt_version      text,
    semantic_version    text
);
CREATE INDEX query_log_ts_idx ON app.query_log (ts);
CREATE INDEX query_log_user_ts_idx ON app.query_log (user_ref, ts);
CREATE INDEX query_log_trace_step_idx ON app.query_log (trace_id, step);

CREATE TABLE app.feedback (
    id                uuid PRIMARY KEY,
    ts                timestamptz NOT NULL DEFAULT now(),
    user_id           text NOT NULL,
    message_id        uuid NOT NULL REFERENCES app.message (id) ON DELETE CASCADE,
    category          text NOT NULL CHECK (category IN ('chiffre_faux', 'mauvaise_comprehension',
                                                        'periode_ou_perimetre', 'refus_injustifie', 'autre')),
    comment           text CHECK (comment IS NULL OR length(comment) <= 2000),
    consent_question  boolean NOT NULL DEFAULT false,
    question_text     text,
    status            text NOT NULL DEFAULT 'nouveau' CHECK (status IN ('nouveau', 'traite', 'rejete')),
    reject_reason     text,
    promoted_to_dev   boolean NOT NULL DEFAULT false,
    handled_by        text,
    handled_at        timestamptz,
    CONSTRAINT feedback_question_consent CHECK (question_text IS NULL OR consent_question),
    CONSTRAINT feedback_reject_reason CHECK (status <> 'rejete' OR reject_reason IS NOT NULL),
    CONSTRAINT feedback_promotion_consent CHECK (NOT promoted_to_dev OR question_text IS NOT NULL)
);
CREATE INDEX feedback_status_ts_idx ON app.feedback (status, ts DESC);
CREATE INDEX feedback_message_idx ON app.feedback (message_id);

CREATE TABLE app.eval_run (
    id              bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    ts              timestamptz NOT NULL DEFAULT now(),
    split           text NOT NULL CHECK (split IN ('dev', 'test')),
    prompt_version  text,
    semantic_version text,
    model_id        text,
    git_sha         text,
    data_hash       text,
    reference_date  date,
    n               integer NOT NULL CHECK (n >= 0),
    n_correct       integer NOT NULL CHECK (n_correct >= 0),
    ci_low          double precision,
    ci_high         double precision,
    cache_off       boolean NOT NULL DEFAULT false,
    pass3           double precision,
    pass1           double precision,
    ablation        text,
    report          jsonb
);
CREATE INDEX eval_run_ts_idx ON app.eval_run (ts DESC);

CREATE TABLE app.eval_result (
    id           bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    run_id       bigint NOT NULL REFERENCES app.eval_run (id) ON DELETE CASCADE,
    question_id  text NOT NULL,
    category     text,
    trap         text,
    passes       integer NOT NULL CHECK (passes BETWEEN 0 AND 3),
    expected     jsonb,
    got          jsonb
);
CREATE INDEX eval_result_run_idx ON app.eval_result (run_id);

-- Journal des consultations du journal d'audit (ajout seul).
CREATE TABLE app.audit_access_log (
    id               bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    ts               timestamptz NOT NULL DEFAULT now(),
    actor_sub        text NOT NULL,
    actor_role       text NOT NULL,
    action           text NOT NULL,
    target_trace_id  text,
    details          jsonb
);
CREATE INDEX audit_access_log_ts_idx ON app.audit_access_log (ts);

CREATE TABLE app.analysis (
    id                uuid PRIMARY KEY,
    ts                timestamptz NOT NULL DEFAULT now(),
    period_start      date NOT NULL,
    period_end        date NOT NULL CHECK (period_end >= period_start),
    region            text,
    semantic_version  text NOT NULL,
    model_id          text,
    payload           jsonb NOT NULL,
    data_hash         text NOT NULL,
    trace_id          text
);
CREATE INDEX analysis_lookup_idx
    ON app.analysis (period_start, period_end, (coalesce(region, '')), semantic_version, data_hash, ts DESC);

-- Droits (posés ici, pas dans l'init Postgres : les tables n'existent qu'après migration).
REVOKE ALL ON ALL TABLES IN SCHEMA app FROM PUBLIC;
GRANT SELECT, INSERT, UPDATE, DELETE ON app.conversation, app.message, app.feedback, app.analysis TO app_rw;
GRANT SELECT, INSERT ON app.query_log, app.audit_access_log, app.eval_run, app.eval_result TO app_rw;
GRANT USAGE ON ALL SEQUENCES IN SCHEMA app TO app_rw;
"""

DOWNGRADE = r"""
DROP TABLE IF EXISTS app.analysis, app.audit_access_log, app.eval_result, app.eval_run,
    app.feedback, app.query_log, app.message, app.conversation CASCADE;
"""


def _run(script: str) -> None:
    # asyncpg prépare chaque requête : une instruction par appel.
    for statement in script.split(";\n"):
        if statement.strip():
            op.execute(statement)


def upgrade() -> None:
    _run(UPGRADE)


def downgrade() -> None:
    _run(DOWNGRADE)
