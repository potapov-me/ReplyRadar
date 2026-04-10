from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import asyncpg


async def get_or_create_chat(
    pool: asyncpg.Pool,
    telegram_id: int,
    title: str | None,
) -> dict[str, Any]:
    """Upsert чата по telegram_id. Возвращает строку таблицы."""
    row = await pool.fetchrow(
        """
        INSERT INTO chats (telegram_id, title)
        VALUES ($1, $2)
        ON CONFLICT (telegram_id) DO UPDATE
            SET title = COALESCE(EXCLUDED.title, chats.title)
        RETURNING *
        """,
        telegram_id,
        title,
    )
    assert row is not None
    return dict(row)


async def set_monitored(pool: asyncpg.Pool, telegram_id: int, *, monitored: bool) -> None:
    await pool.execute(
        "UPDATE chats SET is_monitored = $1 WHERE telegram_id = $2",
        monitored,
        telegram_id,
    )


async def list_monitored(pool: asyncpg.Pool) -> list[dict[str, Any]]:
    rows = await pool.fetch("SELECT * FROM chats WHERE is_monitored = true ORDER BY id")
    return [dict(r) for r in rows]


async def mark_history_loaded(pool: asyncpg.Pool, chat_db_id: int) -> None:
    await pool.execute(
        "UPDATE chats SET history_loaded = true WHERE id = $1",
        chat_db_id,
    )
