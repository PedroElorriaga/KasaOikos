from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import saude
from app.autenticacao import ValidadorToken
from app.config import Settings
from app.db import criar_engine, criar_fabrica_sessoes
from app.observabilidade import (
    configurar_logs,
    configurar_tracing,
    instrumentar_app,
    registrar_log_de_acesso,
)
from app.usuarios import api as usuarios_api


def create_app(settings: Settings | None = None) -> FastAPI:
    """Monta a API. Rodar com: uvicorn --factory app.main:create_app"""
    settings = settings or Settings()
    configurar_logs()
    # Antes do engine: a instrumentação do SQLAlchemy envolve o `create_engine`.
    configurar_tracing(settings)
    engine = criar_engine(settings)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        yield
        engine.dispose()

    app = FastAPI(title="KasaOikos API", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        # O token vai no header Authorization; nenhum cookie é usado.
        allow_credentials=False,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
        allow_headers=["Authorization", "Content-Type"],
        max_age=600,
    )
    app.state.engine = engine
    app.state.fabrica_sessoes = criar_fabrica_sessoes(engine)
    app.state.validador_token = ValidadorToken(settings)
    app.include_router(saude.router)
    app.include_router(usuarios_api.router)
    registrar_log_de_acesso(app)
    # Por último: o middleware do OTel fica por fora; o log de acesso roda dentro do span.
    instrumentar_app(app)
    return app
