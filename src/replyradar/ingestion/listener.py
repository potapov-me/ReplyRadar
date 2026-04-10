"""Realtime Telegram listener.

Подключается к аккаунту через Telethon, фильтрует новые сообщения
из мониторируемых чатов и кладёт их DB-id в asyncio.Queue для
дальнейшей обработки в Processing Engine.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC
from typing import TYPE_CHECKING

from telethon import TelegramClient, events
from telethon.tl.types import Message

from ..db.repos import chats as chats_repo
from ..db.repos import messages as messages_repo

if TYPE_CHECKING:
    import asyncio

    import asyncpg

logger = logging.getLogger(__name__)


class TelegramResolveError(Exception):
    """Поднимается когда listener подключён, но entity не найдена."""


@dataclass
class ListenerState:
    # not_configured | connecting | connected | not_authorized | error | disconnected
    status: str = "not_configured"
    error: str | None = None
    monitored_chats: set[int] = field(default_factory=set)  # telegram_ids


class TelegramListener:
    """Обёртка над TelegramClient для realtime-потока сообщений."""

    def __init__(
        self,
        client: TelegramClient,
        queue: asyncio.Queue[int],
        pool: asyncpg.Pool,
    ) -> None:
        self._client = client
        self._queue = queue
        self._pool = pool
        self.state = ListenerState()

    async def start(self) -> None:
        """Подключается к Telegram и регистрирует обработчик событий."""
        if not self._pool:
            logger.warning("Listener не запущен: БД недоступна")
            return

        self.state.status = "connecting"
        try:
            await self._client.connect()

            if not await self._client.is_user_authorized():
                self.state.status = "not_authorized"
                logger.warning(
                    "Telegram session не найден. "
                    "Запустите `python -m replyradar auth` для авторизации."
                )
                return

            # Загружаем уже мониторируемые чаты из БД
            monitored = await chats_repo.list_monitored(self._pool)
            self.state.monitored_chats = {c["telegram_id"] for c in monitored}

            self._client.add_event_handler(self._on_new_message, events.NewMessage())

            self.state.status = "connected"
            logger.info(
                "Telegram listener подключён, мониторируемых чатов: %d",
                len(self.state.monitored_chats),
            )
        except Exception as exc:  # noqa: BLE001
            self.state.status = "error"
            self.state.error = str(exc)
            logger.error("Telegram listener не запустился: %s", exc)

    async def stop(self) -> None:
        await self._client.disconnect()
        self.state.status = "disconnected"

    def add_monitored_chat(self, telegram_id: int) -> None:
        """Добавляет чат в фильтр realtime-событий без перезапуска."""
        self.state.monitored_chats.add(telegram_id)

    async def resolve_chat(self, telegram_id: int) -> str | None:
        """Проверяет существование чата и возвращает его название.

        Если listener не подключён — возвращает None (деградированный режим, ID без проверки).
        Если подключён, но entity не найдена — поднимает TelegramResolveError.
        """
        if self.state.status != "connected":
            return None
        try:
            entity = await self._client.get_entity(telegram_id)
            return getattr(entity, "title", None) or getattr(entity, "username", None)
        except Exception as exc:  # noqa: BLE001
            raise TelegramResolveError(str(exc)) from exc

    async def _on_new_message(self, event: events.NewMessage.Event) -> None:
        telegram_chat_id: int = event.chat_id
        if telegram_chat_id not in self.state.monitored_chats:
            return

        msg: Message = event.message
        if not isinstance(msg, Message):
            return

        row = await self._pool.fetchrow(
            "SELECT id FROM chats WHERE telegram_id = $1", telegram_chat_id
        )
        if row is None:
            return

        db_chat_id: int = row["id"]
        sender_name = await self._extract_sender_name(event)
        ts = msg.date
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=UTC)

        db_msg_id = await messages_repo.save_message(
            self._pool,
            chat_id=db_chat_id,
            telegram_msg_id=msg.id,
            sender_id=msg.sender_id,
            sender_name=sender_name,
            timestamp=ts,
            text=msg.text or None,
            reply_to_id=msg.reply_to_msg_id,
        )

        if db_msg_id is not None:
            await self._queue.put(db_msg_id)
            logger.debug("Новое сообщение id=%d добавлено в очередь", db_msg_id)

    @staticmethod
    async def _extract_sender_name(event: events.NewMessage.Event) -> str | None:
        try:
            sender = await event.get_sender()
            return getattr(sender, "username", None) or getattr(sender, "first_name", None)
        except Exception:  # noqa: BLE001
            return None
