"""initial schema

Revision ID: 0001
Revises:
Create Date: 2026-04-10

"""
from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # pgcrypto — источник gen_random_uuid() на Postgres < 13.
    # На Postgres 13+ функция встроена, но расширение безвредно.
    # vector — pgvector, обязателен для столбцов vector(768).
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    # ── chats ────────────────────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE chats (
            id              BIGSERIAL PRIMARY KEY,
            telegram_id     BIGINT UNIQUE NOT NULL,
            title           TEXT,
            is_monitored    BOOLEAN NOT NULL DEFAULT FALSE,
            history_loaded  BOOLEAN NOT NULL DEFAULT FALSE,
            created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """)

    # ── messages ─────────────────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE messages (
            id                      BIGSERIAL PRIMARY KEY,
            chat_id                 BIGINT NOT NULL REFERENCES chats(id) ON DELETE CASCADE,
            telegram_msg_id         BIGINT NOT NULL,
            sender_id               BIGINT,
            sender_name             TEXT,
            timestamp               TIMESTAMPTZ NOT NULL,
            text                    TEXT,
            reply_to_id             BIGINT,
            is_signal               BOOLEAN,
            classified_at           TIMESTAMPTZ,
            classify_error          TEXT,
            extracted_at            TIMESTAMPTZ,
            extract_error           TEXT,
            embedded_at             TIMESTAMPTZ,
            embed_error             TEXT,
            embedding               vector(768),
            entities_extracted_at   TIMESTAMPTZ,
            entities_extract_error  TEXT,
            UNIQUE(chat_id, telegram_msg_id)
        )
    """)
    op.execute("CREATE INDEX ix_messages_chat_id ON messages(chat_id)")
    op.execute("CREATE INDEX ix_messages_classified_at ON messages(classified_at) WHERE classified_at IS NULL")
    op.execute("CREATE INDEX ix_messages_extracted_at ON messages(extracted_at) WHERE is_signal = true AND extracted_at IS NULL")
    op.execute("CREATE INDEX ix_messages_entities_extracted_at ON messages(entities_extracted_at) WHERE entities_extracted_at IS NULL")

    # ── chat_summaries ───────────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE chat_summaries (
            chat_id              BIGINT PRIMARY KEY REFERENCES chats(id) ON DELETE CASCADE,
            summary              TEXT,
            key_topics           TEXT[],
            importance_score     FLOAT,
            updated_at           TIMESTAMPTZ,
            model                TEXT,
            prompt_version       TEXT,
            source_window_start  TIMESTAMPTZ,
            source_window_end    TIMESTAMPTZ,
            is_full_rebuild      BOOLEAN,
            embedding            vector(768)
        )
    """)

    # ── entities ─────────────────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE entities (
            id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            entity_type       TEXT NOT NULL CHECK (entity_type IN ('person', 'organization')),
            canonical_name    TEXT NOT NULL,
            aliases           TEXT[],
            telegram_ids      BIGINT[],
            status            TEXT NOT NULL DEFAULT 'candidate'
                                   CHECK (status IN ('candidate', 'active', 'muted')),
            status_changed_at TIMESTAMPTZ,
            activated_by      TEXT,
            mention_count     INT NOT NULL DEFAULT 0,
            version           INT NOT NULL DEFAULT 1,
            first_seen_at     TIMESTAMPTZ,
            updated_at        TIMESTAMPTZ,
            embedding         vector(768)
        )
    """)
    op.execute("CREATE INDEX ix_entities_status ON entities(status)")

    # ── entity_facts ─────────────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE entity_facts (
            id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            entity_id           UUID NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
            fact_type           TEXT NOT NULL,
            fact_key            TEXT,
            fact_value          TEXT NOT NULL,
            source_type         TEXT NOT NULL,
            said_by_entity_id   UUID REFERENCES entities(id),
            message_id          BIGINT REFERENCES messages(id),
            chat_id             BIGINT REFERENCES chats(id),
            base_confidence     FLOAT,
            corroboration_count INT NOT NULL DEFAULT 0,
            contradiction_count INT NOT NULL DEFAULT 0,
            first_seen_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            last_confirmed_at   TIMESTAMPTZ,
            superseded_by       UUID REFERENCES entity_facts(id),
            extraction_model    TEXT,
            prompt_version      TEXT,
            embedding           vector(768)
        )
    """)
    op.execute("CREATE INDEX ix_entity_facts_entity_id ON entity_facts(entity_id)")

    # ── entity_relations ─────────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE entity_relations (
            id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            entity_a_id         UUID NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
            relation_type       TEXT NOT NULL,
            entity_b_id         UUID NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
            is_directional      BOOLEAN NOT NULL DEFAULT TRUE,
            claim_text          TEXT,
            source_type         TEXT NOT NULL,
            said_by_entity_id   UUID REFERENCES entities(id),
            message_id          BIGINT REFERENCES messages(id),
            chat_id             BIGINT REFERENCES chats(id),
            base_confidence     FLOAT,
            corroboration_count INT NOT NULL DEFAULT 0,
            contradiction_count INT NOT NULL DEFAULT 0,
            first_seen_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            last_confirmed_at   TIMESTAMPTZ,
            expired_at          TIMESTAMPTZ,
            superseded_by       UUID REFERENCES entity_relations(id),
            extraction_model    TEXT,
            prompt_version      TEXT
        )
    """)
    op.execute("CREATE INDEX ix_entity_relations_a ON entity_relations(entity_a_id)")
    op.execute("CREATE INDEX ix_entity_relations_b ON entity_relations(entity_b_id)")

    # ── entity_fact_sources ──────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE entity_fact_sources (
            fact_id     UUID NOT NULL REFERENCES entity_facts(id) ON DELETE CASCADE,
            message_id  BIGINT NOT NULL REFERENCES messages(id),
            seen_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            PRIMARY KEY (fact_id, message_id)
        )
    """)

    # ── entity_relation_sources ──────────────────────────────────────────────
    op.execute("""
        CREATE TABLE entity_relation_sources (
            relation_id UUID NOT NULL REFERENCES entity_relations(id) ON DELETE CASCADE,
            message_id  BIGINT NOT NULL REFERENCES messages(id),
            seen_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            PRIMARY KEY (relation_id, message_id)
        )
    """)

    # ── processing_quarantine ────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE processing_quarantine (
            id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            message_id       BIGINT REFERENCES messages(id),
            stage            TEXT NOT NULL,
            error_class      TEXT NOT NULL,
            error_detail     TEXT,
            raw_llm_response TEXT,
            retry_count      INT NOT NULL DEFAULT 0,
            quarantined_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            reviewed_at      TIMESTAMPTZ,
            resolution       TEXT
        )
    """)

    # ── entity_audit_log ─────────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE entity_audit_log (
            id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            entity_id     UUID NOT NULL REFERENCES entities(id),
            action        TEXT NOT NULL,
            actor         TEXT NOT NULL,
            version_from  INT,
            version_to    INT,
            payload       JSONB,
            created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """)
    op.execute("CREATE INDEX ix_entity_audit_log_entity_id ON entity_audit_log(entity_id)")

    # ── commitments ──────────────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE commitments (
            id                 UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            source_fingerprint TEXT UNIQUE NOT NULL,
            closure_reason     TEXT,
            chat_id            BIGINT REFERENCES chats(id),
            message_id         BIGINT REFERENCES messages(id),
            author             TEXT,
            target             TEXT,
            text               TEXT,
            due_hint           TEXT,
            status             TEXT,
            status_changed_at  TIMESTAMPTZ,
            superseded_at      TIMESTAMPTZ,
            inactive_reason    TEXT,
            extraction_model   TEXT,
            prompt_version     TEXT,
            embedding          vector(768)
        )
    """)

    # ── pending_replies ──────────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE pending_replies (
            id                 UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            source_fingerprint TEXT UNIQUE NOT NULL,
            chat_id            BIGINT REFERENCES chats(id),
            message_id         BIGINT REFERENCES messages(id),
            reason             TEXT,
            urgency            TEXT,
            resolved_at        TIMESTAMPTZ,
            superseded_at      TIMESTAMPTZ,
            inactive_reason    TEXT,
            extraction_model   TEXT,
            prompt_version     TEXT
        )
    """)

    # ── communication_risks ──────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE communication_risks (
            id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            chat_id          BIGINT REFERENCES chats(id),
            message_id       BIGINT REFERENCES messages(id),
            type             TEXT,
            confidence       FLOAT,
            explanation      TEXT,
            expired_at       TIMESTAMPTZ,
            extraction_model TEXT,
            prompt_version   TEXT
        )
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS communication_risks")
    op.execute("DROP TABLE IF EXISTS pending_replies")
    op.execute("DROP TABLE IF EXISTS commitments")
    op.execute("DROP TABLE IF EXISTS entity_audit_log")
    op.execute("DROP TABLE IF EXISTS processing_quarantine")
    op.execute("DROP TABLE IF EXISTS entity_relation_sources")
    op.execute("DROP TABLE IF EXISTS entity_fact_sources")
    op.execute("DROP TABLE IF EXISTS entity_relations")
    op.execute("DROP TABLE IF EXISTS entity_facts")
    op.execute("DROP TABLE IF EXISTS entities")
    op.execute("DROP TABLE IF EXISTS chat_summaries")
    op.execute("DROP TABLE IF EXISTS messages")
    op.execute("DROP TABLE IF EXISTS chats")
