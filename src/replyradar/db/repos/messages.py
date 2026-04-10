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


async def save_messages_batch(
    pool: asyncpg.Pool,
    *,
    chat_id: int,
    telegram_msg_ids: list[int],
    sender_ids: list[int | None],
    sender_names: list[str | None],
    timestamps: list[datetime],
    texts: list[str | None],
    reply_ids: list[int | None],
) -> int:
    """Batch INSERT через UNNEST; возвращает число фактически вставленных строк (без конфликтов)."""
    if not telegram_msg_ids:
        return 0
    row = await pool.fetchrow(
        """
        WITH ins AS (
            INSERT INTO messages
                (chat_id, telegram_msg_id, sender_id, sender_name, timestamp, text, reply_to_id)
            SELECT $1, m.mid, m.sid, m.sname, m.ts, m.txt, m.rid
            FROM unnest(
                $2::bigint[],
                $3::bigint[],
                $4::text[],
                $5::timestamptz[],
                $6::text[],
                $7::bigint[]
            ) AS m(mid, sid, sname, ts, txt, rid)
            ON CONFLICT (chat_id, telegram_msg_id) DO NOTHING
            RETURNING id
        )
        SELECT count(*)::int AS inserted FROM ins
        """,
        chat_id,
        telegram_msg_ids,
        sender_ids,
        sender_names,
        timestamps,
        texts,
        reply_ids,
    )
    assert row is not None
    return int(row["inserted"])
