"""Use-case: управление quarantine processing pipeline.

Мутации таблицы processing_quarantine идут только через этот модуль.
Чтение (list) — тоже здесь, чтобы routes не импортировали db.repos напрямую.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from replyradar.db.repos import quarantine as quarantine_repo

if TYPE_CHECKING:
    import asyncpg


async def list_quarantine_pending(
    pool: asyncpg.Pool,
    *,
    limit: int = 50,
    offset: int = 0,
) -> list[dict[str, Any]]:
    return await quarantine_repo.list_quarantine(pool, limit=limit, offset=offset)


async def reprocess_item(
    pool: asyncpg.Pool,
    quarantine_id: str,
) -> dict[str, Any] | None:
    """Помечает запись как reprocessed и очищает ошибку стадии.

    Возвращает запись или None если не найдена / уже обработана.
    """
    record = await quarantine_repo.resolve_quarantine(
        pool, quarantine_id=quarantine_id, resolution="reprocessed"
    )
    if record is None:
        return None

    stage: str = record["stage"]
    msg_id: int = record["message_id"]
    if stage == "classify":
        await pool.execute("UPDATE messages SET classify_error = NULL WHERE id = $1", msg_id)
    elif stage == "extract":
        await pool.execute("UPDATE messages SET extract_error = NULL WHERE id = $1", msg_id)
    elif stage == "embed":
        await pool.execute("UPDATE messages SET embed_error = NULL WHERE id = $1", msg_id)

    return record


async def skip_item(
    pool: asyncpg.Pool,
    quarantine_id: str,
) -> dict[str, Any] | None:
    """Помечает запись как skipped. Возвращает запись или None."""
    return await quarantine_repo.resolve_quarantine(
        pool, quarantine_id=quarantine_id, resolution="skipped"
    )
