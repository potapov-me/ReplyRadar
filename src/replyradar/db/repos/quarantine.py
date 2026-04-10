"""Репозиторий processing_quarantine.

Сообщение попадает в quarantine двумя путями (ADR-0011):
  - transient-ошибка после MAX_RETRIES попыток
  - permanent-ошибка с первой попытки
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import asyncpg


async def send_to_quarantine(  # pylint: disable=too-many-arguments
    pool: asyncpg.Pool,
    *,
    message_id: int,
    stage: str,
    error_class: str,
    error_detail: str,
    raw_llm_response: str | None,
    retry_count: int,
) -> str:
    """Создаёт запись в processing_quarantine. Возвращает UUID записи."""
    row = await pool.fetchrow(
        """
        INSERT INTO processing_quarantine
            (message_id, stage, error_class, error_detail,
             raw_llm_response, retry_count, quarantined_at)
        VALUES ($1, $2, $3, $4, $5, $6, $7)
        RETURNING id::text
        """,
        message_id,
        stage,
        error_class,
        error_detail,
        raw_llm_response,
        retry_count,
        datetime.now(UTC),
    )
    assert row is not None
    return str(row["id"])


async def is_quarantined(
    pool: asyncpg.Pool,
    *,
    message_id: int,
    stage: str,
) -> bool:
    """Возвращает True если сообщение уже в quarantine для данной стадии (reviewed_at IS NULL)."""
    val = await pool.fetchval(
        """
        SELECT EXISTS(
            SELECT 1 FROM processing_quarantine
            WHERE message_id = $1 AND stage = $2 AND reviewed_at IS NULL
        )
        """,
        message_id,
        stage,
    )
    return bool(val)


async def list_quarantine(
    pool: asyncpg.Pool,
    *,
    limit: int = 50,
    offset: int = 0,
) -> list[dict[str, Any]]:
    rows = await pool.fetch(
        """
        SELECT id::text, message_id, stage, error_class, error_detail,
               raw_llm_response, retry_count, quarantined_at, reviewed_at, resolution
        FROM processing_quarantine
        WHERE reviewed_at IS NULL
        ORDER BY quarantined_at DESC
        LIMIT $1 OFFSET $2
        """,
        limit,
        offset,
    )
    return [dict(r) for r in rows]


async def resolve_quarantine(
    pool: asyncpg.Pool,
    *,
    quarantine_id: str,
    resolution: str,  # 'reprocessed' | 'skipped' | 'fixed_manually'
) -> dict[str, Any] | None:
    """Помечает запись quarantine как проверенную. Возвращает обновлённую запись или None."""
    row = await pool.fetchrow(
        """
        UPDATE processing_quarantine
        SET reviewed_at = $1, resolution = $2
        WHERE id = $3::uuid AND reviewed_at IS NULL
        RETURNING id::text, message_id, stage, resolution, reviewed_at
        """,
        datetime.now(UTC),
        resolution,
        quarantine_id,
    )
    return dict(row) if row else None
