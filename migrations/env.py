import asyncio
import os
import sys
from logging.config import fileConfig
from pathlib import Path

from alembic import context
from sqlalchemy.ext.asyncio import create_async_engine

# Позволяет импортировать пакет при запуске alembic из корня проекта
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = None


def _get_url() -> str:
    # Единый источник DSN: DATABASE__URL (pydantic-settings, приоритет) > DATABASE_URL > alembic.ini
    # DATABASE__URL — формат pydantic-settings с разделителем __, используется приложением
    url = os.environ.get("DATABASE__URL") or os.environ.get("DATABASE_URL")
    if url:
        # Нормализуем схему для asyncpg (SQLAlchemy async driver)
        return url.replace("postgresql://", "postgresql+asyncpg://", 1)
    return config.get_main_option("sqlalchemy.url")  # type: ignore[return-value]


def do_run_migrations(connection):  # type: ignore[no-untyped-def]
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    connectable = create_async_engine(_get_url())
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


def run_migrations_offline() -> None:
    context.configure(
        url=_get_url(),
        target_metadata=target_metadata,
        literal_binds=True,
    )
    with context.begin_transaction():
        context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
