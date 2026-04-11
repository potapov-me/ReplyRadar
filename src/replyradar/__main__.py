"""CLI точка входа: python -m replyradar <command>"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path


async def _cmd_auth() -> None:
    """Интерактивная авторизация Telethon. Создаёт .session файл."""
    from telethon import TelegramClient  # noqa: PLC0415

    from .config import get_settings  # noqa: PLC0415

    settings = get_settings()
    tg = settings.telegram

    if tg.api_id == 0 or not tg.api_hash:
        print(
            "ERROR: Задайте TELEGRAM__API_ID и TELEGRAM__API_HASH в .env\n"
            "       Получить на https://my.telegram.org → API development tools"
        )
        sys.exit(1)

    session_path = str(Path(tg.session_dir) / tg.session_name)
    print(f"Session path: {session_path}.session")

    client = TelegramClient(session_path, tg.api_id, tg.api_hash)
    await client.start()  # интерактивный ввод номера телефона и кода
    me = await client.get_me()
    print(f"Авторизован как: {getattr(me, 'username', None) or getattr(me, 'first_name', None)}")
    await client.disconnect()


async def _cmd_eval(stage: str, *, update_baseline: bool) -> int:
    """Запускает eval для указанной стадии. Возвращает exit code."""
    from .config import get_settings  # noqa: PLC0415
    from .llm.client import LLMClient, LLMUnavailableError  # noqa: PLC0415

    settings = get_settings()
    llm = LLMClient(settings.llm, settings.embedding)

    print("Проверяем доступность LM Studio...")
    if not await llm.check_health():
        print("ERROR: LM Studio недоступна. Запустите и загрузите модель.")
        return 1

    if stage == "classify":
        from .eval.classify import run  # noqa: PLC0415
    elif stage == "extract":
        from .eval.extract import run  # noqa: PLC0415
    else:
        print(f"ERROR: неизвестная стадия '{stage}'. Доступны: classify, extract")
        return 1

    try:
        return await run(llm, update_baseline=update_baseline)
    except LLMUnavailableError as exc:
        print(f"ERROR: LLM стала недоступна в процессе eval: {exc}")
        return 1


def main() -> None:
    from .logging import configure_logging  # noqa: PLC0415
    configure_logging()

    parser = argparse.ArgumentParser(
        prog="replyradar",
        description="ReplyRadar — навигация по Telegram-перепискам",
    )
    subparsers = parser.add_subparsers(dest="command", metavar="<command>")

    subparsers.add_parser("auth", help="Авторизовать Telegram-аккаунт (создать .session файл)")

    eval_parser = subparsers.add_parser(
        "eval", help="Запустить offline-eval стадии LLM (требует LM Studio)"
    )
    eval_parser.add_argument(
        "stage",
        choices=["classify", "extract"],
        help="Стадия для оценки",
    )
    eval_parser.add_argument(
        "--update-baseline",
        action="store_true",
        help="Перезаписать baseline текущими результатами",
    )

    args = parser.parse_args()

    if args.command == "auth":
        asyncio.run(_cmd_auth())
    elif args.command == "eval":
        code = asyncio.run(_cmd_eval(args.stage, update_baseline=args.update_baseline))
        sys.exit(code)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
