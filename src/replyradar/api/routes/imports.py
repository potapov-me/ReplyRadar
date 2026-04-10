from __future__ import annotations

import json
from typing import Annotated, Any

from fastapi import APIRouter, File, HTTPException, UploadFile

from replyradar.api.deps import Pool  # noqa: TC001
from replyradar.config import get_settings
from replyradar.ingestion.tg_export_parser import parse_export
from replyradar.usecases import imports as imports_uc

router = APIRouter()


@router.post("/import/telegram-export")
async def import_telegram_export(
    file: Annotated[UploadFile, File(description="result.json из Telegram Desktop Export")],
    pool: Pool,
    monitor: bool = False,
) -> list[dict[str, Any]]:
    """Импортирует историю чатов из result.json экспорта Telegram Desktop.

    Поддерживает два формата:
    - экспорт одного чата (messages на верхнем уровне) → список из одного элемента
    - полный экспорт аккаунта (chats.list) → список всех чатов включая left_chats

    Работает без активного Telegram-соединения.
    Идемпотентно: повторная загрузка того же файла не создаёт дублей.
    Если monitor=true — выставляет is_monitored=true для каждого чата.
    """
    settings = get_settings()
    max_bytes = settings.tg_import.max_file_size_mb * 1024 * 1024

    content = await file.read(max_bytes + 1)
    if len(content) > max_bytes:
        raise HTTPException(
            status_code=413,
            detail=f"Файл превышает {settings.tg_import.max_file_size_mb} МБ",
        )

    try:
        data = json.loads(content)
    except json.JSONDecodeError as exc:
        raise HTTPException(
            status_code=422,
            detail=f"Файл не является валидным JSON: {exc}",
        ) from exc

    if not isinstance(data, dict):
        raise HTTPException(status_code=422, detail="Ожидается JSON-объект верхнего уровня")

    try:
        parsed = parse_export(data)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    results = await imports_uc.import_telegram_export(pool, parsed, monitor=monitor)
    return [dict(r) for r in results]
