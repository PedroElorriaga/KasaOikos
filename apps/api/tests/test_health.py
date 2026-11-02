"""Spec platform/observability, requirement "Health checks" (tarefa 6.1)."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx

from hm_api.main import create_app
from hm_platform.settings import RedisSettings, Settings


async def test_live_and_ready_when_everything_is_up(client: httpx.AsyncClient) -> None:
    live = await client.get("/health/live")
    ready = await client.get("/health/ready")

    assert (live.status_code, live.json()) == (200, {"status": "ok"})
    assert ready.status_code == 200
    assert ready.json() == {"status": "ok", "checks": {"database": "ok", "cache": "ok"}}


async def test_health_needs_no_authentication_or_household(client: httpx.AsyncClient) -> None:
    # Sem Authorization e sem X-Household-Id.
    assert (await client.get("/health/ready")).status_code == 200


@asynccontextmanager
async def client_for(settings: Settings) -> AsyncIterator[httpx.AsyncClient]:
    app = create_app(settings)
    transport = httpx.ASGITransport(app=app)
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(transport=transport, base_url="http://test") as http,
    ):
        yield http


async def test_database_down_ready_503_and_live_still_200(settings: Settings) -> None:
    # Porta 1: ninguém escuta.
    async with client_for(
        settings.model_copy(update={"db": settings.db.model_copy(update={"port": 1})})
    ) as http:
        ready = await http.get("/health/ready")
        live = await http.get("/health/live")

    assert ready.status_code == 503
    assert ready.json() == {
        "status": "unavailable",
        "checks": {"database": "failed", "cache": "ok"},
    }
    assert live.status_code == 200


async def test_cache_down_is_reported(settings: Settings) -> None:
    async with client_for(
        settings.model_copy(update={"redis": RedisSettings(host="127.0.0.1", port=1)})
    ) as http:
        ready = await http.get("/health/ready")

    assert ready.status_code == 503
    assert ready.json()["checks"] == {"database": "ok", "cache": "failed"}
