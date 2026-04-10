"""Стадия Classify — определяет, является ли сообщение signal.

Флаги на messages:
  - classified_at  : timestamp успешной классификации
  - classify_error : описание ошибки при сбое
  - is_signal      : результат классификации
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

PROMPT_VERSION = "classify-v1"


async def run_classify(
    pool: asyncpg.Pool,
    *,
    message_id: int,
    text: str | None,
    sender_name: str | None,
    llm: LLMClient,
    context: list[dict[str, str | None]] | None = None,
) -> bool:
    """Запускает classify-стадию для одного сообщения.

    Возвращает is_signal.
    При ошибке пробрасывает LLMError — engine решает что делать.
    """
    if not text:
        # Сообщения без текста (медиа, сервисные) — не сигнал
        await _mark_success(pool, message_id=message_id, is_signal=False)
        return False

    result = await llm.classify(text, sender_name, context=context or [])
    await _mark_success(pool, message_id=message_id, is_signal=result.is_signal)
    logger.debug("classify msg_id=%d is_signal=%s", message_id, result.is_signal)
    return result.is_signal


async def mark_classify_error(
    pool: asyncpg.Pool,
    *,
    message_id: int,
    error: LLMError,
) -> None:
    prefix = "transient" if isinstance(error, TransientLLMError) else "permanent"
    await pool.execute(
        "UPDATE messages SET classify_error = $1 WHERE id = $2",
        f"{prefix}:{error!s}",
        message_id,
    )


async def _mark_success(
    pool: asyncpg.Pool,
    *,
    message_id: int,
    is_signal: bool,
) -> None:
    await pool.execute(
        """
        UPDATE messages
        SET is_signal = $1,
            classified_at = $2,
            classify_error = NULL
        WHERE id = $3
        """,
        is_signal,
        datetime.now(UTC),
        message_id,
    )
