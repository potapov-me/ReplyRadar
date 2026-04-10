"""Composition root — единственное место, где собираются все компоненты приложения."""

from __future__ import annotations

from typing import TYPE_CHECKING

from .config import get_settings
from .db.pool import create_pool

if TYPE_CHECKING:
    import asyncpg


async def create_components() -> dict:
    """Создаёт и связывает все компоненты приложения при старте."""
    settings = get_settings()
    pool = await create_pool(settings.database.url)
    return {"pool": pool}


async def cleanup_components(components: dict) -> None:
    """Корректно завершает все компоненты при остановке."""
    pool: asyncpg.Pool = components["pool"]
    await pool.close()
