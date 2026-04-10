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
                await pool.fetchval(
                    """
                    SELECT COUNT(*)
                    FROM messages m
                    WHERE m.classified_at IS NULL
                      AND NOT EXISTS (
                          SELECT 1
                          FROM processing_quarantine q
                          WHERE q.message_id = m.id
                            AND q.stage = 'classify'
                            AND q.reviewed_at IS NULL
                      )
                    """
                )
                or 0
            )
            pipeline["backlog_extract"] = (
                await pool.fetchval(
                    """
                    SELECT COUNT(*)
                    FROM messages m
                    WHERE m.is_signal = true
                      AND m.extracted_at IS NULL
                      AND NOT EXISTS (
                          SELECT 1
                          FROM processing_quarantine q
                          WHERE q.message_id = m.id
                            AND q.stage = 'extract'
                            AND q.reviewed_at IS NULL
                      )
                    """
                )
                or 0
            )
            pipeline["backlog_entity_extract"] = (
                await pool.fetchval(
                    """
                    SELECT COUNT(*)
                    FROM messages
                    WHERE entities_extracted_at IS NULL
                    """
                )
                or 0
            )
            pipeline["quarantine_size"] = (
                await pool.fetchval(
                    "SELECT COUNT(*) FROM processing_quarantine WHERE reviewed_at IS NULL"
                )
                or 0
            )
            queue = getattr(request.app.state, "queue", None)
            if queue is not None:
                pipeline["realtime_queue_depth"] = queue.qsize()
        except Exception:  # pylint: disable=broad-exception-caught
            # Таблицы ещё не созданы — нормально до первого alembic upgrade head
            pass

    # ── состояние Telegram ────────────────────────────────────────────────────
    listener = getattr(request.app.state, "listener", None)
    if listener is not None:
        telegram_status: str = listener.state.status
        telegram_detail: str | None = listener.state.error
    else:
        telegram_status = "not_configured"
        telegram_detail = None

    # ── состояние LM Studio ───────────────────────────────────────────────────
    llm = getattr(request.app.state, "llm", None)
    if llm is not None:
        lm_studio_status = "reachable" if await llm.check_health() else "unreachable"
    else:
        lm_studio_status = "not_configured"

    response: dict[str, Any] = {
        "telegram": telegram_status,
        "db": db_status,
        "lm_studio": lm_studio_status,
        "scheduler": "not_started",
        "pipeline": pipeline,
    }
    if telegram_detail:
        response["telegram_detail"] = telegram_detail
    if db_error:
        response["db_detail"] = db_error
    return response
