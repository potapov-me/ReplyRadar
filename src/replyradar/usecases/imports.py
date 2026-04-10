"""Use-case: импорт истории чатов из Telegram Desktop Export.

Мутации таблиц chats и messages проходят только через этот модуль.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, TypedDict

from ..db.repos import chats as chats_repo
from ..db.repos import messages as messages_repo

if TYPE_CHECKING:
    import asyncpg

    from ..ingestion.tg_export_parser import ParsedChat


class ImportResult(TypedDict):
    telegram_id: int
    title: str | None
    is_monitored: bool
    messages_parsed: int
    messages_imported: int
    messages_skipped: int


async def import_telegram_export(
    pool: asyncpg.Pool,
    parsed_chats: list[ParsedChat],
    *,
    monitor: bool,
) -> list[ImportResult]:
    """Сохраняет чаты и сообщения из разобранного экспорта Telegram Desktop.

    Идемпотентно: дубли сообщений игнорируются через ON CONFLICT DO NOTHING.
    Если monitor=True — выставляет is_monitored=true для каждого чата.
    """
    results: list[ImportResult] = []
    for parsed in parsed_chats:
        result = await _import_one(pool, parsed, monitor=monitor)
        results.append(result)
    return results


async def _import_one(
    pool: asyncpg.Pool,
    parsed: ParsedChat,
    *,
    monitor: bool,
) -> ImportResult:
    chat = await chats_repo.get_or_create_chat(pool, parsed.telegram_id, parsed.title)
    chat_id: int = chat["id"]

    if monitor:
        await chats_repo.set_monitored(pool, parsed.telegram_id, monitored=True)

    is_monitored: bool = monitor or bool(chat["is_monitored"])

    imported = await messages_repo.save_messages_batch(
        pool,
        chat_id=chat_id,
        telegram_msg_ids=[m.telegram_msg_id for m in parsed.messages],
        sender_ids=[m.sender_id for m in parsed.messages],
        sender_names=[m.sender_name for m in parsed.messages],
        timestamps=[m.timestamp for m in parsed.messages],
        texts=[m.text for m in parsed.messages],
        reply_ids=[m.reply_to_id for m in parsed.messages],
    )
    total = len(parsed.messages)

    return ImportResult(
        telegram_id=parsed.telegram_id,
        title=parsed.title,
        is_monitored=is_monitored,
        messages_parsed=total,
        messages_imported=imported,
        messages_skipped=total - imported,
    )
