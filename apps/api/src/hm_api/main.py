"""Composition root: cria a aplicação FastAPI do monolito."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI

from hm_api.modules import ROUTERS
from hm_identity import public as identity
from hm_platform import health
from hm_platform.auth import create_token_validator
from hm_platform.cache import create_redis
from hm_platform.db import create_engine, create_session_factory
from hm_platform.errors import PROBLEM_RESPONSES, install_error_handlers
from hm_platform.logs import AccessLogMiddleware, configure_logging
from hm_platform.settings import Settings, get_settings
from hm_platform.telemetry import Telemetry, create_telemetry
from hm_platform.tenancy import MembershipCache


def create_app(
    settings: Settings | None = None,
    *,
    http_transport: httpx.AsyncBaseTransport | None = None,
    telemetry: Telemetry | None = None,
) -> FastAPI:
    """Nos testes, ``http_transport`` serve um JWKS falso e ``telemetry`` exporta em memória."""
    settings = settings or get_settings()
    telemetry = telemetry or create_telemetry(settings.otel)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        engine = create_engine(settings.db, "app")
        redis = create_redis(settings.redis)
        telemetry.instrument_engine(engine)
        telemetry.instrument_redis(redis)
        async with httpx.AsyncClient(transport=http_transport) as http:
            telemetry.instrument_http(http)
            app.state.db_engine = engine
            app.state.redis = redis
            app.state.db_sessions = create_session_factory(engine)
            app.state.token_validator = create_token_validator(settings.oidc, http)
            # Portas da tenancy (design D6), implementadas pelo módulo identity.
            app.state.user_provisioner = identity.provision_user
            app.state.membership_cache = MembershipCache(
                redis,
                identity.get_membership_role,
                settings.redis.membership_ttl_seconds,
                meter=telemetry.meter_provider.get_meter("hm_platform.tenancy"),
            )
            try:
                yield
            finally:
                await redis.aclose()
                await engine.dispose()
                telemetry.shutdown()

    configure_logging(settings.log_level, logger_provider=telemetry.logger_provider)
    app = FastAPI(title="Home Manager API", version="0.1.0", lifespan=lifespan)
    app.state.settings = settings
    app.state.telemetry = telemetry
    app.include_router(health.router)
    for router in ROUTERS:
        app.include_router(router, responses=PROBLEM_RESPONSES)
    # Middlewares: o último registrado é o mais externo; a telemetria envolve todos.
    install_error_handlers(app)
    app.add_middleware(AccessLogMiddleware)
    telemetry.instrument_app(app)  # por último: o span do OTel envolve os demais middlewares
    return app


def create_production_app() -> FastAPI:
    """Factory do ``hm serve``: roda em cada worker do uvicorn (um processo cada)."""
    settings = get_settings()
    telemetry = create_telemetry(settings.otel)
    telemetry.set_global()
    return create_app(settings, telemetry=telemetry)
