from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from datetime import datetime

    import asyncpg


async def save_message(
    pool: asyncpg.Pool,
    *,
    chat_id: int,
    telegram_msg_id: int,
    sender_id: int | None,
    sender_name: str | None,
    timestamp: datetime,
    text: str | None,
    reply_to_id: int | None,
) -> int | None:
    """INSERT с ON CONFLICT DO NOTHING.

    Возвращает DB id вставленной строки, либо None если дубль.
    """
    row = await pool.fetchrow(
        """
        INSERT INTO messages
            (chat_id, telegram_msg_id, sender_id, sender_name,
             timestamp, text, reply_to_id)
        VALUES ($1, $2, $3, $4, $5, $6, $7)
        ON CONFLICT (chat_id, telegram_msg_id) DO NOTHING
        RETURNING id
        """,
        chat_id,
        telegram_msg_id,
        sender_id,
        sender_name,
        timestamp,
        text,
        reply_to_id,
    )
    return row["id"] if row else None
