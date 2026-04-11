"""Чтение и запись baseline.json для eval-стадий."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from pathlib import Path


def load(path: Path) -> dict[str, Any] | None:
    """Возвращает baseline как dict или None если файл не существует."""
    if not path.exists():
        return None
    try:
        data: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
        return data
    except (json.JSONDecodeError, OSError):
        return None


def save(path: Path, metrics: dict[str, Any]) -> None:
    """Записывает метрики в baseline.json с меткой времени."""
    data = {**metrics, "saved_at": datetime.now(UTC).isoformat()}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
