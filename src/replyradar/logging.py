"""Централизованная конфигурация логирования (ADR-0019).

Единственное место, где настраиваются handlers и форматы.
Вызывается один раз при старте — из main.py (uvicorn) и __main__.py (CLI).

Инварианты:
  - Тексты сообщений никогда не попадают в лог — только ID, метрики, статусы.
  - Уровень и формат задаются через config (LOG__LEVEL, LOG__FORMAT в .env).
  - Шумные сторонние библиотеки ограничены WARNING.
"""

from __future__ import annotations

import logging
import logging.config
import sys
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .config import LogConfig

# Библиотеки с избыточным DEBUG/INFO-шумом: опускаем до WARNING
_NOISY_THIRD_PARTY: tuple[str, ...] = (
    "telethon",
    "litellm",
    "litellm.utils",
    "litellm.main",
    "httpx",
    "httpcore",
    "asyncpg",
    "uvicorn.access",  # HTTP access log остаётся, но не нужен в business логах
)

_TEXT_FORMAT = "%(asctime)s %(levelname)-8s [%(name)s] %(message)s"
_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"


def configure_logging(config: LogConfig | None = None) -> None:
    """Настраивает корневой логгер приложения.

    Если config=None — читает настройки из get_settings() автоматически.
    Это позволяет вызывать функцию до и после инициализации Settings.
    """
    if config is None:
        from .config import get_settings  # noqa: PLC0415
        config = get_settings().log

    level = _parse_level(config.level)

    handler = _make_json_handler(level) if config.format == "json" else _make_text_handler(level)

    # ── корневой логгер replyradar ─────────────────────────────────────────────
    app_logger = logging.getLogger("replyradar")
    app_logger.handlers = [handler]
    app_logger.setLevel(level)
    app_logger.propagate = False  # не дублируем в root logger

    # ── подавление шума сторонних библиотек ───────────────────────────────────
    for name in _NOISY_THIRD_PARTY:
        logging.getLogger(name).setLevel(logging.WARNING)

    # ── uvicorn: если его handlers уже настроены — переиспользуем ──────────────
    _sync_uvicorn_format(handler)


def _parse_level(level_str: str) -> int:
    level = getattr(logging, level_str.upper(), None)
    if not isinstance(level, int):
        logging.warning("Неизвестный уровень логирования: %r, используется INFO", level_str)
        return logging.INFO
    return level


def _make_text_handler(level: int) -> logging.StreamHandler:  # type: ignore[type-arg]
    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(level)
    handler.setFormatter(logging.Formatter(_TEXT_FORMAT, datefmt=_DATE_FORMAT))
    return handler


def _make_json_handler(level: int) -> logging.StreamHandler:  # type: ignore[type-arg]
    try:
        from pythonjsonlogger.json import JsonFormatter  # noqa: PLC0415
        formatter = JsonFormatter(
            fmt="%(asctime)s %(levelname)s %(name)s %(message)s",
            datefmt=_DATE_FORMAT,
            rename_fields={"levelname": "level", "asctime": "ts", "name": "logger"},
        )
    except ImportError:
        # python-json-logger не установлен — fallback на text
        logging.warning("python-json-logger не найден, используется text format")
        return _make_text_handler(level)

    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(level)
    handler.setFormatter(formatter)
    return handler


def _sync_uvicorn_format(app_handler: logging.Handler) -> None:
    """Приводит formatter uvicorn-логгеров к тому же формату что и replyradar."""
    for name in ("uvicorn", "uvicorn.error"):
        uv_logger = logging.getLogger(name)
        if uv_logger.handlers:
            for h in uv_logger.handlers:
                h.setFormatter(app_handler.formatter)
