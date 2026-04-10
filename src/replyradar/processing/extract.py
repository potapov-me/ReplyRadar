"""Стадия Extract — извлекает commitments, pending_replies, communication_risks.

Запускается только если is_signal = true.
Флаги на messages: extracted_at, extract_error.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from replyradar.db.repos import signals as signals_repo
from replyradar.llm.client import LLMError, TransientLLMError

if TYPE_CHECKING:
    import asyncpg

    from ..llm.client import LLMClient

logger = logging.getLogger(__name__)

PROMPT_VERSION = "extract-v1"
MODEL_TAG = "local-model"


async def run_extract(  # pylint: disable=too-many-arguments
    pool: asyncpg.Pool,
    *,
    message_id: int,
    chat_id: int,
    text: str | None,
    sender_name: str | None,
    llm: LLMClient,
) -> None:
    """Запускает extract-стадию для одного сообщения.

    Raises:
        LLMError: пробрасывает вызывающему.
    """
    if not text:
        await _mark_success(pool, message_id=message_id)
        return

    result = await llm.extract(text, sender_name)

    for i, commitment in enumerate(result.commitments):
        await signals_repo.upsert_commitment(
            pool,
            chat_id=chat_id,
            message_id=message_id,
            item=commitment,
            index=i,
            model=MODEL_TAG,
            prompt_version=PROMPT_VERSION,
        )

    for i, reply in enumerate(result.pending_replies):
        await signals_repo.upsert_pending_reply(
            pool,
            chat_id=chat_id,
            message_id=message_id,
            item=reply,
            index=i,
            model=MODEL_TAG,
            prompt_version=PROMPT_VERSION,
        )

    for risk in result.communication_risks:
        await signals_repo.upsert_communication_risk(
            pool,
            chat_id=chat_id,
            message_id=message_id,
            item=risk,
            model=MODEL_TAG,
            prompt_version=PROMPT_VERSION,
        )

    logger.debug(
        "extract msg_id=%d commitments=%d pending=%d risks=%d",
        message_id,
        len(result.commitments),
        len(result.pending_replies),
        len(result.communication_risks),
    )

    await _mark_success(pool, message_id=message_id)


async def mark_extract_error(
    pool: asyncpg.Pool,
    *,
    message_id: int,
    error: LLMError,
) -> None:
    prefix = "transient" if isinstance(error, TransientLLMError) else "permanent"
    await pool.execute(
        "UPDATE messages SET extract_error = $1 WHERE id = $2",
        f"{prefix}:{error!s}",
        message_id,
    )


async def _mark_success(pool: asyncpg.Pool, *, message_id: int) -> None:
    await pool.execute(
        """
        UPDATE messages
        SET extracted_at = $1, extract_error = NULL
        WHERE id = $2
        """,
        datetime.now(UTC),
        message_id,
    )
