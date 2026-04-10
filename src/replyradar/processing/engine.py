"""Processing Engine — оркестратор обработки сообщений (ADR-0003, ADR-0011).

Два источника задач:
  - realtime: asyncio.Queue, куда listener кладёт DB-id новых сообщений
  - backfill: периодический запрос к БД (classified_at IS NULL)

Приоритет realtime > backfill: backfill ждёт, пока queue непуста.

Таксономия ошибок (ADR-0011):
  - transient: retry до MAX_RETRIES, затем quarantine
  - permanent: quarantine сразу

Retry-счётчики живут в памяти (сбрасываются при перезапуске — приемлемо для MVP).
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any

from replyradar.db.repos import quarantine as quarantine_repo
from replyradar.llm.client import LLMError, PermanentLLMError, TransientLLMError
from replyradar.processing.classify import mark_classify_error, run_classify
from replyradar.processing.embed import mark_embed_error, run_embed
from replyradar.processing.extract import mark_extract_error, run_extract

if TYPE_CHECKING:
    from collections.abc import Callable, Coroutine

    import asyncpg

    from ..config import ProcessingConfig
    from ..llm.client import LLMClient

logger = logging.getLogger(__name__)

_BACKFILL_POLL_INTERVAL = 5.0  # секунд между проверками backlog

# Sentinel: _run_stage возвращает этот объект при ошибке/quarantine,
# чтобы отличить "стадия вернула None (void)" от "стадия не прошла".
_STAGE_FAILED: object = object()


class ProcessingEngine:  # pylint: disable=too-many-instance-attributes
    """Запускает и координирует realtime и backfill обработку сообщений."""

    def __init__(
        self,
        pool: asyncpg.Pool,
        queue: asyncio.Queue[int],
        llm: LLMClient,
        config: ProcessingConfig,
    ) -> None:
        self._pool = pool
        self._queue = queue
        self._llm = llm
        self._config = config
        self._max_retries = config.max_retries_before_quarantine
        self._backfill_wakeup = asyncio.Event()

        # (message_id, stage) -> retry_count в рамках текущей сессии
        self._retry_counts: dict[tuple[int, str], int] = {}

        self._running = False
        self._tasks: list[asyncio.Task[None]] = []

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._tasks = [
            asyncio.create_task(self._realtime_loop(), name="engine:realtime"),
            asyncio.create_task(self._backfill_loop(), name="engine:backfill"),
        ]
        logger.info("ProcessingEngine started")

    async def stop(self) -> None:
        self._running = False
        self._backfill_wakeup.set()
        for t in self._tasks:
            t.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks.clear()
        logger.info("ProcessingEngine stopped")

    def wake_backfill(self) -> None:
        """Форсирует ближайшую проверку backlog без ожидания poll interval."""
        logger.info("ProcessingEngine wake_backfill requested")
        self._backfill_wakeup.set()

    # ── loops ─────────────────────────────────────────────────────────────────

    async def _realtime_loop(self) -> None:
        while self._running:
            try:
                msg_id = await asyncio.wait_for(self._queue.get(), timeout=1.0)
            except TimeoutError:
                continue
            except asyncio.CancelledError:
                return

            try:
                await self._process_message(msg_id)
            except Exception:  # pylint: disable=broad-exception-caught
                logger.exception("realtime: необработанная ошибка msg_id=%d", msg_id)
            finally:
                self._queue.task_done()

    async def _backfill_loop(self) -> None:
        while self._running:
            if not self._queue.empty():
                await asyncio.sleep(0.1)
                continue

            rows = await self._pool.fetch(
                """
                SELECT m.id, m.chat_id, m.text, m.sender_name,
                       m.classified_at, m.is_signal,
                       m.embedded_at, m.extracted_at
                FROM messages m
                WHERE m.classified_at IS NULL
                  AND NOT EXISTS (
                      SELECT 1
                      FROM processing_quarantine q
                      WHERE q.message_id = m.id
                        AND q.stage = 'classify'
                        AND q.reviewed_at IS NULL
                  )
                   OR m.embedded_at IS NULL
                  AND NOT EXISTS (
                      SELECT 1
                      FROM processing_quarantine q
                      WHERE q.message_id = m.id
                        AND q.stage = 'embed'
                        AND q.reviewed_at IS NULL
                  )
                   OR (m.is_signal = true AND m.extracted_at IS NULL)
                  AND NOT EXISTS (
                      SELECT 1
                      FROM processing_quarantine q
                      WHERE q.message_id = m.id
                        AND q.stage = 'extract'
                        AND q.reviewed_at IS NULL
                  )
                ORDER BY m.timestamp ASC
                LIMIT $1
                """,
                self._config.backfill_batch_size,
            )

            if not rows:
                self._backfill_wakeup.clear()
                try:
                    await asyncio.wait_for(
                        self._backfill_wakeup.wait(),
                        timeout=_BACKFILL_POLL_INTERVAL,
                    )
                except TimeoutError:
                    pass
                continue

            logger.info("ProcessingEngine picked backlog batch size=%d", len(rows))

            for row in rows:
                if not self._queue.empty():
                    break

                try:
                    await self._process_row(dict(row))
                except Exception:  # pylint: disable=broad-exception-caught
                    logger.exception("backfill: необработанная ошибка msg_id=%d", row["id"])

            await asyncio.sleep(0)

    # ── processing ────────────────────────────────────────────────────────────

    async def _process_message(self, msg_id: int) -> None:
        row = await self._pool.fetchrow(
            """
            SELECT id, chat_id, text, sender_name,
                   classified_at, is_signal, embedded_at, extracted_at
            FROM messages
            WHERE id = $1
            """,
            msg_id,
        )
        if row is None:
            logger.warning("process_message: msg_id=%d не найден в БД", msg_id)
            return
        await self._process_row(dict(row))

    async def _process_row(self, row: dict[str, Any]) -> None:
        msg_id: int = row["id"]
        chat_id: int = row["chat_id"]
        text: str | None = row["text"]
        sender_name: str | None = row["sender_name"]

        # ── Classify ─────────────────────────────────────────────────────────
        if row["classified_at"] is None:
            result = await self._run_stage(
                msg_id=msg_id,
                stage="classify",
                make_coro=lambda: run_classify(
                    self._pool,
                    message_id=msg_id,
                    text=text,
                    sender_name=sender_name,
                    llm=self._llm,
                ),
                mark_error=lambda err: mark_classify_error(
                    self._pool, message_id=msg_id, error=err
                ),
            )
            if result is _STAGE_FAILED:
                return
            row["is_signal"] = result  # bool

        # ── Embed ─────────────────────────────────────────────────────────────
        if row["embedded_at"] is None:
            result = await self._run_stage(
                msg_id=msg_id,
                stage="embed",
                make_coro=lambda: run_embed(
                    self._pool, message_id=msg_id, text=text, llm=self._llm
                ),
                mark_error=lambda err: mark_embed_error(self._pool, message_id=msg_id, error=err),
            )
            if result is _STAGE_FAILED:
                return

        # ── Extract (только для сигналов) ─────────────────────────────────────
        if row.get("is_signal") and row["extracted_at"] is None:
            await self._run_stage(
                msg_id=msg_id,
                stage="extract",
                make_coro=lambda: run_extract(
                    self._pool,
                    message_id=msg_id,
                    chat_id=chat_id,
                    text=text,
                    sender_name=sender_name,
                    llm=self._llm,
                ),
                mark_error=lambda err: mark_extract_error(self._pool, message_id=msg_id, error=err),
            )

    async def _run_stage(
        self,
        *,
        msg_id: int,
        stage: str,
        make_coro: Callable[[], Coroutine[Any, Any, Any]],
        mark_error: Callable[[LLMError], Coroutine[Any, Any, None]],
    ) -> Any:
        """Запускает стадию с обработкой ошибок и quarantine-логикой.

        Возвращает результат корутины при успехе (может быть None для void).
        Возвращает _STAGE_FAILED при ошибке или quarantine.
        Корутина создаётся лениво — только если стадия не в quarantine.
        """
        if await quarantine_repo.is_quarantined(self._pool, message_id=msg_id, stage=stage):
            return _STAGE_FAILED

        try:
            result = await make_coro()
            self._retry_counts.pop((msg_id, stage), None)
            return result
        except PermanentLLMError as exc:
            logger.warning("permanent error msg_id=%d stage=%s: %s", msg_id, stage, exc)
            await mark_error(exc)
            count = self._retry_counts.get((msg_id, stage), 0)
            await quarantine_repo.send_to_quarantine(
                self._pool,
                message_id=msg_id,
                stage=stage,
                error_class="permanent",
                error_detail=str(exc),
                raw_llm_response=None,
                retry_count=count,
            )
            return _STAGE_FAILED
        except TransientLLMError as exc:
            count = self._retry_counts.get((msg_id, stage), 0) + 1
            self._retry_counts[(msg_id, stage)] = count
            logger.warning(
                "transient error msg_id=%d stage=%s attempt=%d/%d: %s",
                msg_id,
                stage,
                count,
                self._max_retries,
                exc,
            )
            await mark_error(exc)
            if count >= self._max_retries:
                await quarantine_repo.send_to_quarantine(
                    self._pool,
                    message_id=msg_id,
                    stage=stage,
                    error_class="transient",
                    error_detail=str(exc),
                    raw_llm_response=None,
                    retry_count=count,
                )
                self._retry_counts.pop((msg_id, stage), None)
            return _STAGE_FAILED
        except LLMError as exc:
            logger.error("unknown LLM error msg_id=%d stage=%s: %s", msg_id, stage, exc)
            await mark_error(exc)
            await quarantine_repo.send_to_quarantine(
                self._pool,
                message_id=msg_id,
                stage=stage,
                error_class="permanent",
                error_detail=str(exc),
                raw_llm_response=None,
                retry_count=0,
            )
            return _STAGE_FAILED
