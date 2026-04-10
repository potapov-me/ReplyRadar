from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException

from replyradar.api.deps import Pool  # noqa: TC001
from replyradar.usecases import quarantine as quarantine_uc

router = APIRouter(prefix="/admin", tags=["admin"])


@router.get("/quarantine")
async def list_quarantine(
    pool: Pool,
    limit: int = 50,
    offset: int = 0,
) -> dict[str, Any]:
    items = await quarantine_uc.list_quarantine_pending(pool, limit=limit, offset=offset)
    return {"items": items, "count": len(items)}


@router.post("/quarantine/{quarantine_id}/reprocess")
async def reprocess_quarantine(quarantine_id: str, pool: Pool) -> dict[str, Any]:
    record = await quarantine_uc.reprocess_item(pool, quarantine_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Запись не найдена или уже проверена")
    return {"status": "reprocessed", "message_id": record["message_id"]}


@router.post("/quarantine/{quarantine_id}/skip")
async def skip_quarantine(quarantine_id: str, pool: Pool) -> dict[str, Any]:
    record = await quarantine_uc.skip_item(pool, quarantine_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Запись не найдена или уже проверена")
    return {"status": "skipped", "message_id": record["message_id"]}
