"""Стадия Embed — создаёт векторный эмбеддинг сообщения.

Запускается после classify (для всех сообщений).
Флаги на messages: embedded_at, embed_error, embedding.

asyncpg не знает о типе vector — передаём вектор как строку '[x,y,z,...]' с ::vector каст в SQL.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from replyradar.llm.client import LLMError, TransientLLMError

if TYPE_CHECKING:
    import asyncpg

    from ..llm.client import LLMClient

logger = logging.getLogger(__name__)


async def run_embed(
    pool: asyncpg.Pool,
    *,
    message_id: int,
    text: str | None,
    llm: LLMClient,
) -> None:
    """Создаёт эмбеддинг для сообщения и сохраняет в БД.

    Raises:
        LLMError: пробрасывает вызывающему.
    """
    if not text:
        await _mark_success(pool, message_id=message_id, vector=None)
        return

    vector = await llm.embed(text, msg_id=message_id)
    await _mark_success(pool, message_id=message_id, vector=vector)
    logger.debug("embed msg_id=%d dims=%d", message_id, len(vector))


async def mark_embed_error(
    pool: asyncpg.Pool,
    *,
    message_id: int,
    error: LLMError,
) -> None:
    prefix = "transient" if isinstance(error, TransientLLMError) else "permanent"
    await pool.execute(
        "UPDATE messages SET embed_error = $1 WHERE id = $2",
        f"{prefix}:{error!s}",
        message_id,
    )


async def _mark_success(
    pool: asyncpg.Pool,
    *,
    message_id: int,
    vector: list[float] | None,
) -> None:
    if vector is not None:
        # pgvector принимает строковое представление '[x,y,z,...]'
        vec_str = "[" + ",".join(str(v) for v in vector) + "]"
        await pool.execute(
            """
            UPDATE messages
            SET embedding = $1::vector,
                embedded_at = $2,
                embed_error = NULL
            WHERE id = $3
            """,
            vec_str,
            datetime.now(UTC),
            message_id,
        )
    else:
        await pool.execute(
            """
            UPDATE messages
            SET embedded_at = $1, embed_error = NULL
            WHERE id = $2
            """,
            datetime.now(UTC),
            message_id,
        )
