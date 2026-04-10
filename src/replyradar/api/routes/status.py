from __future__ import annotations

from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, Request

if TYPE_CHECKING:
    import asyncpg

router = APIRouter()


@router.get("/status")
async def get_status(request: Request) -> dict[str, Any]:
    pool: asyncpg.Pool | None = request.app.state.pool
    db_error: str | None = request.app.state.db_error

    # ── состояние БД ──────────────────────────────────────────────────────────
    if pool is None:
        db_status = "error"
    else:
        try:
            await pool.fetchval("SELECT 1")
            db_status = "writable"
        except Exception:  # pylint: disable=broad-exception-caught
            db_status = "error"

    # ── backlog из БД (нули при недоступной базе) ─────────────────────────────
    pipeline: dict[str, Any] = {
        "realtime_queue_depth": 0,
        "backlog_classify": 0,
        "backlog_extract": 0,
        "backlog_entity_extract": 0,
        "quarantine_size": 0,
    }

    if pool is not None and db_status == "writable":
        try:
            pipeline["backlog_classify"] = (
                await pool.fetchval("SELECT COUNT(*) FROM messages WHERE classified_at IS NULL")
                or 0
            )
            pipeline["backlog_extract"] = (
                await pool.fetchval(
                    "SELECT COUNT(*) FROM messages WHERE is_signal = true AND extracted_at IS NULL"
                )
                or 0
            )
            pipeline["backlog_entity_extract"] = (
                await pool.fetchval(
                    "SELECT COUNT(*) FROM messages WHERE entities_extracted_at IS NULL"
                )
                or 0
            )
            pipeline["quarantine_size"] = (
                await pool.fetchval(
                    "SELECT COUNT(*) FROM processing_quarantine WHERE reviewed_at IS NULL"
                )
                or 0
            )
        except Exception:  # pylint: disable=broad-exception-caught
            # Таблицы ещё не созданы — нормально до первого alembic upgrade head
            pass

    response: dict[str, Any] = {
        "telegram": "not_configured",
        "db": db_status,
        "lm_studio": "not_configured",
        "scheduler": "not_started",
        "pipeline": pipeline,
    }
    if db_error:
        response["db_detail"] = db_error
    return response
