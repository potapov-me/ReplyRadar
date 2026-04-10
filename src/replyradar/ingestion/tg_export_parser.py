"""Парсер формата Telegram Desktop Export (result.json).

Нормализует сырой JSON экспорта к типизированным доменным объектам.
Не зависит от БД и не делает IO — только разбор данных.

Поддерживаемые форматы:
- Экспорт одного чата: корень содержит поле ``messages``
- Полный экспорт аккаунта: корень содержит поле ``chats`` (+ опционально ``left_chats``)
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

# Типы чатов, для которых telegram_id хранится без префикса -100 в экспорте,
# но с -100 в MTProto API (ADR-0017)
_SUPERGROUP_TYPES = frozenset(
    {"public_supergroup", "private_supergroup", "public_channel", "private_channel"}
)


@dataclass(frozen=True)
class ParsedMessage:
    telegram_msg_id: int
    timestamp: datetime
    sender_id: int | None
    sender_name: str | None
    text: str | None
    reply_to_id: int | None


@dataclass(frozen=True)
class ParsedChat:
    telegram_id: int
    title: str | None
    messages: list[ParsedMessage]


def parse_export(data: dict[str, Any]) -> list[ParsedChat]:
    """Разбирает dict из result.json экспорта Telegram Desktop.

    Поддерживает оба формата:
    - одиночный чат (``messages`` на верхнем уровне) → список из одного элемента
    - полный экспорт аккаунта (``chats.list``) → список всех чатов включая ``left_chats``

    Raises:
        ValueError: если структура не распознана как Telegram Desktop Export.
    """
    if "messages" in data:
        return [_parse_single_chat(data)]

    if "chats" in data:
        return _parse_account_export(data)

    raise ValueError(
        "Неверный формат: не найдено ни поле 'messages' (экспорт одного чата), "
        "ни поле 'chats' (полный экспорт аккаунта). "
        "Ожидается result.json из Telegram Desktop."
    )


# ---------------------------------------------------------------------------
# Внутренние функции
# ---------------------------------------------------------------------------


def _parse_account_export(data: dict[str, Any]) -> list[ParsedChat]:
    """Разбирает полный экспорт аккаунта: chats.list + left_chats.list."""
    results: list[ParsedChat] = []

    for section_key in ("chats", "left_chats"):
        section = data.get(section_key)
        if not isinstance(section, dict):
            continue
        for raw_chat in section.get("list", []):
            if not isinstance(raw_chat, dict):
                continue
            try:
                results.append(_parse_single_chat(raw_chat))
            except ValueError:
                continue  # пропускаем чаты с некорректной структурой

    if not results:
        raise ValueError("Экспорт не содержит ни одного чата с сообщениями.")

    return results


def _parse_single_chat(data: dict[str, Any]) -> ParsedChat:
    """Разбирает объект одного чата (с полем ``messages`` на верхнем уровне)."""
    if "messages" not in data:
        raise ValueError("Неверный формат: поле 'messages' не найдено.")

    chat_id = data.get("id")
    if not isinstance(chat_id, int):
        raise ValueError("Неверный формат: поле 'id' отсутствует или не является числом.")

    chat_type = data.get("type", "")
    telegram_id = _normalize_telegram_id(chat_type, chat_id)
    title = data.get("name") or None

    messages: list[ParsedMessage] = []
    for raw in data["messages"]:
        if not isinstance(raw, dict):
            continue
        if raw.get("type") != "message":
            continue  # service messages (join/leave/pin/etc.) пропускаем

        msg_id = raw.get("id")
        if not isinstance(msg_id, int):
            continue

        date_str = raw.get("date")
        if not date_str:
            continue
        try:
            timestamp = _parse_date(str(date_str))
        except (ValueError, TypeError):
            continue

        messages.append(
            ParsedMessage(
                telegram_msg_id=msg_id,
                timestamp=timestamp,
                sender_id=_parse_sender_id(raw.get("from_id")),
                sender_name=raw.get("from") or None,
                text=_parse_text(raw.get("text")),
                reply_to_id=raw.get("reply_to_message_id"),
            )
        )

    return ParsedChat(telegram_id=telegram_id, title=title, messages=messages)


def _normalize_telegram_id(chat_type: str, chat_id: int) -> int:
    """Добавляет префикс -100 для supergroup/channel (ADR-0017)."""
    if chat_type in _SUPERGROUP_TYPES and chat_id > 0:
        return int(f"-100{chat_id}")
    return chat_id


def _parse_sender_id(from_id: str | None) -> int | None:
    """Извлекает числовой ID из строки вида 'user123456789' или 'channel123456789'."""
    if not from_id:
        return None
    digits = re.sub(r"^\D+", "", from_id)
    return int(digits) if digits else None


def _parse_text(raw: str | list[Any] | None) -> str | None:
    """Нормализует поле text: строка или список форматированных блоков → plain text."""
    if raw is None:
        return None
    if isinstance(raw, str):
        return raw or None
    # list of str | {"type": ..., "text": ...}
    parts: list[str] = []
    for item in raw:
        if isinstance(item, str):
            parts.append(item)
        elif isinstance(item, dict):
            parts.append(item.get("text", ""))
    result = "".join(parts)
    return result or None


def _parse_date(date_str: str) -> datetime:
    """Разбирает ISO 8601 дату из экспорта. Telegram хранит время в UTC."""
    dt = datetime.fromisoformat(date_str)
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt
