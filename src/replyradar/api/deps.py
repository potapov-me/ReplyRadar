from typing import Annotated

import asyncpg
from fastapi import Depends, HTTPException, Request


def _get_pool(request: Request) -> asyncpg.Pool:
    pool = request.app.state.pool
    if pool is None:
        raise HTTPException(status_code=503, detail="База данных недоступна")
    return pool


Pool = Annotated[asyncpg.Pool, Depends(_get_pool)]
