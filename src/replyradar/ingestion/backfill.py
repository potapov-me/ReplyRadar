"""Backfill исторических сообщений через Telethon iter_messages.

BackfillRunner запускает задачи для каждого чата в виде asyncio.Task,
ограничивает параллелизм через Semaphore (backfill_concurrency),
обрабатывает сообщения батчами по backfill_batch_size и предоставляет
статус для GET /backfill/status.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from telethon.tl.types import Message

from ..db.repos import chats as chats_repo
from ..db.repos import messages as messages_repo

if TYPE_CHECKING:
    import asyncpg
    from telethon import TelegramClient

logger = logging.getLogger(__name__)


@dataclass
class ChatBackfillState:
    chat_db_id: int
    telegram_id: int
    status: str = "pending"  # pending | running | completed | error
    messages_saved: int = 0
    started_at: datetime | None = None
    completed_at: datetime | None = None
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "telegram_id": self.telegram_id,
            "status": self.status,
            "messages_saved": self.messages_saved,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "error": self.error,
        }


async def _flush_buffer(
    pool: asyncpg.Pool,
    chat_db_id: int,
    buffer: list[Message],
) -> int:
    """Сохраняет батч сообщений, возвращает число вставленных строк (без дублей)."""
    saved = 0
    for msg in buffer:
        sender_name: str | None = None
        if msg.sender_id:
            try:
                sender = await msg.get_sender()
                sender_name = getattr(sender, "username", None) or getattr(
                    sender, "first_name", None
                )
            except Exception:  # noqa: BLE001
                pass

        ts = msg.date
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=UTC)

        db_msg_id = await messages_repo.save_message(
            pool,
            chat_id=chat_db_id,
            telegram_msg_id=msg.id,
            sender_id=msg.sender_id,
            sender_name=sender_name,
            timestamp=ts,
            text=msg.text or None,
            reply_to_id=msg.reply_to_msg_id,
        )
        if db_msg_id is not None:
            saved += 1
    return saved


async def _backfill_one_chat(
    client: TelegramClient,
    pool: asyncpg.Pool,
    state: ChatBackfillState,
    *,
    sem: asyncio.Semaphore,
    batch_size: int,
) -> None:
    """Загружает историю одного чата от старых к новым, батчами."""
    async with sem:
        state.status = "running"
        state.started_at = datetime.now(tz=UTC)
        logger.info("Backfill начат: telegram_id=%d", state.telegram_id)

        try:
            buffer: list[Message] = []

            async for msg in client.iter_messages(state.telegram_id, reverse=True):
                if not isinstance(msg, Message):
                    continue
                buffer.append(msg)

                if len(buffer) >= batch_size:
                    state.messages_saved += await _flush_buffer(pool, state.chat_db_id, buffer)
                    buffer.clear()
                    await asyncio.sleep(0)  # уступаем event loop для realtime

            if buffer:
                state.messages_saved += await _flush_buffer(pool, state.chat_db_id, buffer)

            await chats_repo.mark_history_loaded(pool, state.chat_db_id)
            state.status = "completed"
            state.completed_at = datetime.now(tz=UTC)
            logger.info(
                "Backfill завершён: telegram_id=%d, сохранено=%d",
                state.telegram_id,
                state.messages_saved,
            )
        except Exception as exc:  # noqa: BLE001
            state.status = "error"
            state.error = str(exc)
            logger.error("Backfill ошибка telegram_id=%d: %s", state.telegram_id, exc)


class BackfillRunner:
    """Координатор backfill-задач с ограничением параллелизма и батчевой обработкой."""

    def __init__(
        self,
        client: TelegramClient,
        pool: asyncpg.Pool,
        *,
        concurrency: int = 1,
        batch_size: int = 20,
    ) -> None:
        self._client = client
        self._pool = pool
        self._batch_size = batch_size
        self._sem = asyncio.Semaphore(concurrency)
        self._states: dict[int, ChatBackfillState] = {}  # keyed by telegram_id
        self._tasks: dict[int, asyncio.Task[None]] = {}

    def start(self, chats: list[dict[str, Any]]) -> int:
        """Запускает backfill для переданных чатов.

        Идемпотентно: уже работающие задачи не перезапускаются.
        Concurrency ограничивается через Semaphore — задачи создаются все,
        но выполняются не более чем concurrency штук одновременно.
        Возвращает количество newly-started задач.
        """
        started = 0
        for chat in chats:
            tg_id: int = chat["telegram_id"]
            existing = self._tasks.get(tg_id)
            if existing and not existing.done():
                continue  # уже в очереди или выполняется

            state = ChatBackfillState(chat_db_id=chat["id"], telegram_id=tg_id)
            self._states[tg_id] = state
            self._tasks[tg_id] = asyncio.create_task(
                _backfill_one_chat(
                    self._client,
                    self._pool,
                    state,
                    sem=self._sem,
                    batch_size=self._batch_size,
                ),
                name=f"backfill-{tg_id}",
            )
            started += 1
        return started

    def get_status(self) -> dict[str, Any]:
        running = any(not t.done() for t in self._tasks.values())
        return {
            "status": "running" if running else "idle",
            "chats": [s.to_dict() for s in self._states.values()],
        }

    async def stop(self) -> None:
        """Отменяет все активные задачи и ждёт их завершения."""
        for task in self._tasks.values():
            if not task.done():
                task.cancel()
        if self._tasks:
            await asyncio.gather(*self._tasks.values(), return_exceptions=True)
