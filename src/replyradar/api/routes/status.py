from fastapi import APIRouter

from ..deps import Pool

router = APIRouter()


@router.get("/status")
async def get_status(pool: Pool) -> dict:
    # Проверяем БД
    try:
        await pool.fetchval("SELECT 1")
        db_status = "writable"
    except Exception:
        db_status = "error"

    pipeline: dict = {
        "realtime_queue_depth": 0,
        "backlog_classify": 0,
        "backlog_extract": 0,
        "backlog_entity_extract": 0,
        "quarantine_size": 0,
    }

    if db_status == "writable":
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
        except Exception:
            # Таблицы ещё не созданы — нормально для первого запуска
            pass

    return {
        "telegram": "not_configured",
        "db": db_status,
        "lm_studio": "not_configured",
        "scheduler": "not_started",
        "pipeline": pipeline,
    }
