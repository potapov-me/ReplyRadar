"""Composition root — единственное место, где собираются все компоненты приложения."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

from telethon import TelegramClient

from replyradar.config import get_settings
from replyradar.db.pool import create_pool
from replyradar.ingestion.backfill import BackfillRunner
from replyradar.ingestion.listener import TelegramListener
from replyradar.llm.client import LLMClient
from replyradar.processing.engine import ProcessingEngine

if TYPE_CHECKING:
    import asyncpg

logger = logging.getLogger(__name__)


async def create_components() -> dict[str, Any]:
    """Создаёт и связывает все компоненты приложения при старте.

    Подключение к БД и Telegram нефатально: приложение стартует
    в любом случае, GET /status отражает реальное состояние.
    """
    settings = get_settings()

    # ── База данных ───────────────────────────────────────────────────────────
    pool: asyncpg.Pool | None = None
    db_error: str | None = None
    try:
        pool = await create_pool(settings.database.url)
    except Exception as exc:  # pylint: disable=broad-exception-caught
        db_error = str(exc)
        logger.warning("БД недоступна при старте: %s", exc)

    # ── Очередь для Processing Engine ────────────────────────────────────────
    queue: asyncio.Queue[int] = asyncio.Queue()

    # ── LLM client ────────────────────────────────────────────────────────────
    llm = LLMClient(settings.llm, settings.embedding)

    # ── Processing Engine ─────────────────────────────────────────────────────
    engine: ProcessingEngine | None = None
    if pool is not None:
        engine = ProcessingEngine(pool, queue, llm, settings.processing)
        await engine.start()

    # ── Telegram client ───────────────────────────────────────────────────────
    tg = settings.telegram
    session_path = str(Path(tg.session_dir) / tg.session_name)
    client = TelegramClient(session_path, tg.api_id, tg.api_hash)

    # ── Listener ──────────────────────────────────────────────────────────────
    listener: TelegramListener | None = None
    if tg.api_id != 0 and pool is not None:
        listener = TelegramListener(client, queue, pool)
        await listener.start()
    elif tg.api_id == 0:
        logger.info("Telegram не настроен (api_id=0). Установите TELEGRAM__API_ID в .env")

    # ── BackfillRunner ────────────────────────────────────────────────────────
    backfill_runner: BackfillRunner | None = None
    if pool is not None and listener is not None:
        backfill_runner = BackfillRunner(
            client,
            pool,
            concurrency=settings.processing.backfill_concurrency,
            batch_size=settings.processing.backfill_batch_size,
        )

    return {
        "pool": pool,
        "db_error": db_error,
        "queue": queue,
        "client": client,
        "listener": listener,
        "backfill_runner": backfill_runner,
        "llm": llm,
        "engine": engine,
    }


async def cleanup_components(components: dict[str, Any]) -> None:
    """Корректно завершает все компоненты при остановке."""
    engine: ProcessingEngine | None = components.get("engine")
    if engine is not None:
        await engine.stop()

    backfill_runner: BackfillRunner | None = components.get("backfill_runner")
    if backfill_runner is not None:
        await backfill_runner.stop()

    listener: TelegramListener | None = components.get("listener")
    if listener is not None:
        await listener.stop()

    pool: asyncpg.Pool | None = components.get("pool")
    if pool is not None:
        await pool.close()
