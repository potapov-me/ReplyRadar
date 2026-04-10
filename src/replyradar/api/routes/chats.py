from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from replyradar.api.deps import (
    Pool,  # noqa: TC001  # FastAPI evaluates this at runtime via get_type_hints()
)
from replyradar.ingestion.listener import TelegramResolveError
from replyradar.usecases import chats as chats_uc

router = APIRouter()
logger = logging.getLogger(__name__)


@router.post("/chats/{telegram_id}/monitor")
async def monitor_chat(telegram_id: int, request: Request, pool: Pool) -> dict[str, Any]:
    """Регистрирует Telegram-чат для мониторинга.

    Idempotent: повторный вызов не создаёт дубликатов.
    """
    listener = getattr(request.app.state, "listener", None)
    if listener is None or listener.state.status != "connected":
        raise HTTPException(status_code=503, detail="Telegram listener не подключён")

    try:
        title = await listener.resolve_chat(telegram_id)
    except TelegramResolveError as exc:
        raise HTTPException(
            status_code=422,
            detail=f"Telegram ID {telegram_id} не найден или недоступен: {exc}",
        ) from exc

    chat = await chats_uc.monitor_chat(pool, telegram_id, title)
    listener.add_monitored_chat(telegram_id)

    return chat


class BackfillRequest(BaseModel):
    telegram_id: int | None = None  # None = все мониторируемые чаты


@router.post("/backfill", status_code=202)
async def start_backfill(
    body: BackfillRequest,
    request: Request,
    pool: Pool,
) -> dict[str, Any]:
    """Запускает ingestion backfill через Telegram или DB-only обработку backlog.

    Если Telegram listener подключён — загружает историю чатов через Telethon.
    Если listener недоступен — не падает, а будит Processing Engine, чтобы тот
    немедленно забрал backlog уже существующих сообщений из БД.
    """
    listener = getattr(request.app.state, "listener", None)
    backfill_runner = getattr(request.app.state, "backfill_runner", None)
    engine = getattr(request.app.state, "engine", None)

    if listener is not None and getattr(listener.state, "status", None) == "connected":
        if backfill_runner is None:
            raise HTTPException(status_code=503, detail="BackfillRunner не инициализирован")

        if body.telegram_id is not None:
            row = await pool.fetchrow(
                "SELECT * FROM chats WHERE telegram_id = $1 AND is_monitored = true",
                body.telegram_id,
            )
            if row is None:
                raise HTTPException(
                    status_code=404,
                    detail="Чат не найден или не мониторируется. Сначала: POST /chats/{id}/monitor",
                )
            chats = [dict(row)]
        else:
            chats = await chats_uc.list_monitored_chats(pool)
            if not chats:
                raise HTTPException(status_code=404, detail="Нет мониторируемых чатов")

        started = backfill_runner.start(chats)
        logger.info(
            "backfill requested mode=telegram started=%d telegram_ids=%s",
            started,
            [c["telegram_id"] for c in chats],
        )
        return {
            "accepted": True,
            "mode": "telegram",
            "started": started,
            "telegram_ids": [c["telegram_id"] for c in chats],
        }

    if engine is None:
        raise HTTPException(
            status_code=503,
            detail="Processing engine не инициализирован",
        )

    if body.telegram_id is not None:
        row = await pool.fetchrow(
            "SELECT * FROM chats WHERE telegram_id = $1",
            body.telegram_id,
        )
        if row is None:
            raise HTTPException(
                status_code=404,
                detail="Чат не найден в БД. Сначала импортируйте историю или подключите monitor",
            )
        chats = [dict(row)]
    else:
        chats = await chats_uc.list_monitored_chats(pool)
        if not chats:
            # DB-only режим будит global backlog processing, даже если чаты не monitor=true.
            engine.wake_backfill()
            logger.info("backfill requested mode=database started=1 telegram_ids=[]")
            return {
                "accepted": True,
                "mode": "database",
                "started": 1,
                "telegram_ids": [],
            }

    engine.wake_backfill()
    logger.info(
        "backfill requested mode=database started=1 telegram_ids=%s",
        [c["telegram_id"] for c in chats],
    )
    return {
        "accepted": True,
        "mode": "database",
        "started": 1,
        "telegram_ids": [c["telegram_id"] for c in chats],
    }


@router.get("/backfill/status")
async def get_backfill_status(request: Request) -> dict[str, Any]:
    backfill_runner = getattr(request.app.state, "backfill_runner", None)
    if backfill_runner is None:
        return {"status": "idle", "chats": []}
    return backfill_runner.get_status()  # type: ignore[no-any-return]
