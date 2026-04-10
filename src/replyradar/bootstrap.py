"""Composition root — единственное место, где собираются все компоненты приложения."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from .config import get_settings
from .db.pool import create_pool

if TYPE_CHECKING:
    import asyncpg

logger = logging.getLogger(__name__)


async def create_components() -> dict[str, Any]:
    """Создаёт и связывает все компоненты приложения при старте.

    Подключение к БД нефатально: при недоступности Postgres приложение
    стартует, а GET /status отразит db="error".
    """
    settings = get_settings()
    pool: asyncpg.Pool | None = None
    db_error: str | None = None
    try:
        pool = await create_pool(settings.database.url)
    except Exception as exc:  # pylint: disable=broad-exception-caught
        db_error = str(exc)
        logger.warning("DB unavailable at startup: %s", exc)
    return {"pool": pool, "db_error": db_error}


async def cleanup_components(components: dict[str, Any]) -> None:
    """Корректно завершает все компоненты при остановке."""
    pool: asyncpg.Pool | None = components.get("pool")
    if pool is not None:
        await pool.close()
