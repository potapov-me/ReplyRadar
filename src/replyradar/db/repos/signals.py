"""Репозиторий сигналов: commitments, pending_replies, communication_risks.

Все write-операции идемпотентны через source_fingerprint (commitments/pending_replies)
или вставку без ON CONFLICT (communication_risks — дубли фильтруются по message_id+type).
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import asyncpg

    from ...llm.contracts.extract import (
        CommitmentItem,
        CommunicationRiskItem,
        PendingReplyItem,
    )


def _fingerprint(*parts: object) -> str:
    """SHA-256 первых 32 hex-символов от конкатенации строковых частей."""
    raw = ":".join(str(p) for p in parts)
    return hashlib.sha256(raw.encode()).hexdigest()[:32]


async def upsert_commitment(
    pool: asyncpg.Pool,
    *,
    chat_id: int,
    message_id: int,
    item: CommitmentItem,
    index: int,
    model: str,
    prompt_version: str,
) -> None:
    fp = _fingerprint(chat_id, message_id, "commitment", index)
    await pool.execute(
        """
        INSERT INTO commitments
            (source_fingerprint, chat_id, message_id, author, target, text,
             due_hint, status, status_changed_at, extraction_model, prompt_version)
        VALUES ($1, $2, $3, $4, $5, $6, $7, 'open', $8, $9, $10)
        ON CONFLICT (source_fingerprint) DO NOTHING
        """,
        fp,
        chat_id,
        message_id,
        item.author,
        item.target,
        item.text,
        item.due_hint,
        datetime.now(UTC),
        model,
        prompt_version,
    )


async def upsert_pending_reply(
    pool: asyncpg.Pool,
    *,
    chat_id: int,
    message_id: int,
    item: PendingReplyItem,
    index: int,
    model: str,
    prompt_version: str,
) -> None:
    fp = _fingerprint(chat_id, message_id, "pending_reply", index)
    await pool.execute(
        """
        INSERT INTO pending_replies
            (source_fingerprint, chat_id, message_id, reason, urgency,
             extraction_model, prompt_version)
        VALUES ($1, $2, $3, $4, $5, $6, $7)
        ON CONFLICT (source_fingerprint) DO NOTHING
        """,
        fp,
        chat_id,
        message_id,
        item.reason,
        item.urgency,
        model,
        prompt_version,
    )


async def upsert_communication_risk(
    pool: asyncpg.Pool,
    *,
    chat_id: int,
    message_id: int,
    item: CommunicationRiskItem,
    model: str,
    prompt_version: str,
) -> None:
    # Дедупликация по (message_id, type) — один риск одного типа на сообщение
    await pool.execute(
        """
        INSERT INTO communication_risks
            (chat_id, message_id, type, confidence, explanation,
             extraction_model, prompt_version)
        SELECT $1, $2, $3, $4, $5, $6, $7
        WHERE NOT EXISTS (
            SELECT 1 FROM communication_risks
            WHERE message_id = $2 AND type = $3
        )
        """,
        chat_id,
        message_id,
        item.type,
        item.confidence,
        item.explanation,
        model,
        prompt_version,
    )
