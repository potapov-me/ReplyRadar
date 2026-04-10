from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from ..bootstrap import cleanup_components, create_components
from .routes import status


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None]:
    components = await create_components()
    app.state.pool = components["pool"]  # asyncpg.Pool | None
    app.state.db_error = components["db_error"]  # str | None
    try:
        yield
    finally:
        await cleanup_components(components)


app = FastAPI(title="ReplyRadar", lifespan=lifespan)

app.include_router(status.router)
