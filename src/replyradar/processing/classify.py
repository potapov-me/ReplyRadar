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

from replyradar.llm.client import (
    LLMError,
    LLMUnavailableError,
    PermanentLLMError,
    TransientLLMError,
)

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

    result = await llm.classify(text, sender_name, context=context or [], msg_id=message_id)
    await _mark_success(pool, message_id=message_id, is_signal=result.is_signal)
    logger.debug("classify msg_id=%d is_signal=%s", message_id, result.is_signal)
    return result.is_signal


async def run_classify_batch(
    pool: asyncpg.Pool,
    *,
    messages: list[dict[str, str | int | None]],
    llm: LLMClient,
) -> list[int]:
    """Batch-классифицирует сообщения за один LLM-вызов.

    Сообщения без текста помечаются сразу (is_signal=False) без обращения к LLM.
    Возвращает список message_id, результат которых не удалось получить —
    caller должен обработать их поштучно через стандартный run_classify.

    Raises:
        LLMUnavailableError: LM Studio недоступен — engine должен остановить обработку.
    """
    if not messages:
        return []

    no_text: list[dict[str, str | int | None]] = [m for m in messages if not m.get("text")]
    need_llm: list[dict[str, str | int | None]] = [m for m in messages if m.get("text")]

    for m in no_text:
        await _mark_success(pool, message_id=int(m["id"]), is_signal=False)  # type: ignore[arg-type]
        logger.debug("classify batch no_text msg_id=%s", m["id"])

    if not need_llm:
        return []

    try:
        results = await llm.classify_batch(need_llm)  # type: ignore[arg-type]
    except LLMUnavailableError:
        raise
    except (PermanentLLMError, TransientLLMError) as exc:
        # Весь batch не прошёл: при Permanent — плохой ответ модели,
        # при Transient — rate limit / timeout на самом запросе.
        # В обоих случаях откатываемся на per-message: там живёт retry/quarantine.
        logger.warning(
            "classify batch %s (%d msgs), fallback to per-message: %s",
            type(exc).__name__,
            len(need_llm),
            exc,
        )
        return [int(m["id"]) for m in need_llm]  # type: ignore[arg-type]

    failed_ids: list[int] = []
    for msg, result in zip(need_llm, results, strict=False):
        msg_id = int(msg["id"])  # type: ignore[arg-type]
        if result is None:
            failed_ids.append(msg_id)
        else:
            await _mark_success(pool, message_id=msg_id, is_signal=result.is_signal)
            logger.debug("classify batch msg_id=%d is_signal=%s", msg_id, result.is_signal)

    if failed_ids:
        logger.warning(
            "classify batch: %d/%d items missing, will retry individually",
            len(failed_ids),
            len(need_llm),
        )
    else:
        logger.info("classify batch ok count=%d", len(need_llm))

    return failed_ids


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
