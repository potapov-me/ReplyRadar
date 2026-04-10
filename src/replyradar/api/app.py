from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from ..bootstrap import cleanup_components, create_components
from .routes import admin, chats, imports, status


@asynccontextmanager
async def lifespan(application: FastAPI) -> AsyncGenerator[None]:
    components = await create_components()
    application.state.pool = components["pool"]
    application.state.db_error = components["db_error"]
    application.state.queue = components["queue"]
    application.state.client = components["client"]
    application.state.listener = components["listener"]
    application.state.backfill_runner = components["backfill_runner"]
    application.state.llm = components["llm"]
    application.state.engine = components["engine"]
    try:
        yield
    finally:
        await cleanup_components(components)


app = FastAPI(title="ReplyRadar", lifespan=lifespan)

app.include_router(status.router)
app.include_router(chats.router)
app.include_router(imports.router)
app.include_router(admin.router)
