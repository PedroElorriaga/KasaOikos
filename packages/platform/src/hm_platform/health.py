"""Health checks (spec platform/observability): sem autenticação e sem lar ativo.

- ``/health/live``: o processo está atendendo (para o orquestrador reiniciar se não estiver).
- ``/health/ready``: banco e cache acessíveis (para tirar a instância do balanceamento).
"""

import asyncio
from collections.abc import Awaitable, Callable

from fastapi import APIRouter, Request, status
from fastapi.responses import JSONResponse
from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

CHECK_TIMEOUT_SECONDS = 2.0

router = APIRouter(prefix="/health", tags=["health"])


async def _database(engine: AsyncEngine) -> None:
    async with engine.connect() as conn:
        await conn.execute(text("select 1"))


async def _cache(redis: Redis) -> None:
    await redis.ping()


async def _run(check: Callable[[], Awaitable[None]]) -> str:
    # Com timeout: um banco inalcançável (sem "connection refused") penduraria o probe.
    try:
        await asyncio.wait_for(check(), timeout=CHECK_TIMEOUT_SECONDS)
    except Exception:
        return "failed"
    return "ok"


@router.get("/live")
async def live() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/ready")
async def ready(request: Request) -> JSONResponse:
    engine: AsyncEngine = request.app.state.db_engine
    redis: Redis = request.app.state.redis
    database, cache = await asyncio.gather(
        _run(lambda: _database(engine)), _run(lambda: _cache(redis))
    )
    checks = {"database": database, "cache": cache}
    healthy = all(result == "ok" for result in checks.values())
    return JSONResponse(
        {"status": "ok" if healthy else "unavailable", "checks": checks},
        status_code=status.HTTP_200_OK if healthy else status.HTTP_503_SERVICE_UNAVAILABLE,
    )
