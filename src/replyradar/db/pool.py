import asyncpg


async def create_pool(dsn: str) -> asyncpg.Pool:
    pool = await asyncpg.create_pool(dsn)
    assert pool is not None  # create_pool returns Pool | None but never None with valid DSN
    return pool
