"""Use-cases для работы с чатами (command path).

Мутации таблицы chats проходят только через этот модуль.
Читает состояние через db/repos/chats.py.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from replyradar.db.repos import chats as chats_repo

if TYPE_CHECKING:
    import asyncpg


async def monitor_chat(
    pool: asyncpg.Pool,
    telegram_id: int,
    title: str | None,
) -> dict[str, Any]:
    """Регистрирует чат для мониторинга.

    Idempotent: повторный вызов обновляет title если он не был известен ранее.
    """
    chat = await chats_repo.get_or_create_chat(pool, telegram_id, title)
    await chats_repo.set_monitored(pool, telegram_id, monitored=True)
    chat["is_monitored"] = True
    return chat


async def list_monitored_chats(pool: asyncpg.Pool) -> list[dict[str, Any]]:
    return await chats_repo.list_monitored(pool)
