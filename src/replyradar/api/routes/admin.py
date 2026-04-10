from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException

from ...db.repos import quarantine as quarantine_repo
from ..deps import Pool  # noqa: TC001

router = APIRouter(prefix="/admin", tags=["admin"])


@router.get("/quarantine")
async def list_quarantine(
    pool: Pool,
    limit: int = 50,
    offset: int = 0,
) -> dict[str, Any]:
    items = await quarantine_repo.list_quarantine(pool, limit=limit, offset=offset)
    return {"items": items, "count": len(items)}


@router.post("/quarantine/{quarantine_id}/reprocess")
async def reprocess_quarantine(quarantine_id: str, pool: Pool) -> dict[str, Any]:
    """Помечает запись как reprocessed, очищает ошибку стадии — message вернётся в backfill."""
    record = await quarantine_repo.resolve_quarantine(
        pool, quarantine_id=quarantine_id, resolution="reprocessed"
    )
    if record is None:
        raise HTTPException(status_code=404, detail="Запись не найдена или уже проверена")

    # Очищаем ошибку стадии — message снова попадёт в backfill
    stage: str = record["stage"]
    msg_id: int = record["message_id"]
    if stage == "classify":
        await pool.execute("UPDATE messages SET classify_error = NULL WHERE id = $1", msg_id)
    elif stage == "extract":
        await pool.execute("UPDATE messages SET extract_error = NULL WHERE id = $1", msg_id)
    elif stage == "embed":
        await pool.execute("UPDATE messages SET embed_error = NULL WHERE id = $1", msg_id)

    return {"status": "reprocessed", "message_id": msg_id}


@router.post("/quarantine/{quarantine_id}/skip")
async def skip_quarantine(quarantine_id: str, pool: Pool) -> dict[str, Any]:
    record = await quarantine_repo.resolve_quarantine(
        pool, quarantine_id=quarantine_id, resolution="skipped"
    )
    if record is None:
        raise HTTPException(status_code=404, detail="Запись не найдена или уже проверена")

    return {"status": "skipped", "message_id": record["message_id"]}
