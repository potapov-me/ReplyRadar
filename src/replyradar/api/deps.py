from typing import Annotated

import asyncpg
from fastapi import Depends, Request


def _get_pool(request: Request) -> asyncpg.Pool:
    return request.app.state.pool  # type: ignore[no-any-return]


Pool = Annotated[asyncpg.Pool, Depends(_get_pool)]
