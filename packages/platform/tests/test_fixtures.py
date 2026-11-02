"""Testes triviais das fixtures compartilhadas (hm_platform.testing.fixtures)."""

from collections.abc import AsyncIterator, Sequence

import httpx
import pytest
import pytest_asyncio
from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from hm_platform import migrations
from hm_platform.migrations import ModuleMigrations


@pytest_asyncio.fixture(scope="module")
async def probe_table(migrator_engine: AsyncEngine) -> AsyncIterator[None]:
    # Criada e removida com commit real, como dono; o hm_app recebe DML pelos default privileges.
    async with migrator_engine.begin() as conn:
        await conn.execute(text("create table identity.fixture_probe (value text)"))
    yield
    async with migrator_engine.begin() as conn:
        await conn.execute(text("drop table identity.fixture_probe"))


async def test_db_session_runs_as_app_role(db_session: AsyncSession) -> None:
    assert await db_session.scalar(text("select current_user")) == "hm_app"


@pytest.mark.parametrize("attempt", [1, 2])
async def test_db_session_rolls_back_even_after_commit(
    db_session: AsyncSession, probe_table: None, attempt: int
) -> None:
    await db_session.execute(
        text("insert into identity.fixture_probe values (:v)"), {"v": str(attempt)}
    )
    await db_session.commit()  # vira SAVEPOINT; a transação externa é desfeita no fim

    # Se o commit tivesse vazado, a segunda execução veria 2 linhas.
    assert await db_session.scalar(text("select count(*) from identity.fixture_probe")) == 1


async def test_migrated_database_is_at_head(
    migrator_engine: AsyncEngine,
    migrated_database: None,
    module_migrations: Sequence[ModuleMigrations],
) -> None:
    assert [m.name for m in module_migrations] == [
        "identity",
        "finance",
        "tasks",
        "inventory",
        "notifications",
    ]
    assert await migrations.current(migrator_engine, module_migrations) == {
        m.name: m.heads() for m in module_migrations
    }


@pytest.mark.parametrize("attempt", [1, 2])
async def test_redis_client_starts_empty(redis_client: Redis, attempt: int) -> None:
    assert await redis_client.dbsize() == 0
    await redis_client.set("probe", f"value-{attempt}")
    assert await redis_client.get("probe") == f"value-{attempt}"  # decode_responses=True


async def test_client_talks_to_the_test_app(client: httpx.AsyncClient) -> None:
    response = await client.get("/openapi.json")
    assert response.status_code == 200
    assert response.json()["info"]["title"] == "Home Manager API"
