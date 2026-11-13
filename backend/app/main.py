from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app import saude
from app.config import Settings
from app.db import criar_engine


def create_app(settings: Settings | None = None) -> FastAPI:
    """Monta a API. Rodar com: uvicorn --factory app.main:create_app"""
    settings = settings or Settings()
    engine = criar_engine(settings)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        yield
        engine.dispose()

    app = FastAPI(title="KasaOikos API", lifespan=lifespan)
    app.state.engine = engine
    app.include_router(saude.router)
    return app
