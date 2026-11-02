from collections.abc import AsyncIterator

import httpx
import pytest_asyncio
from fastapi import FastAPI
from sqlalchemy import String, select, text
from sqlalchemy.ext.asyncio import AsyncEngine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from hm_platform.db import (
    DbSession,
    UUIDv7PrimaryKey,
    create_engine,
    create_session_factory,
    schema_metadata,
)
from hm_platform.settings import DatabaseSettings


class ProbeBase(DeclarativeBase):
    metadata = schema_metadata("identity")


class Probe(UUIDv7PrimaryKey, ProbeBase):
    __tablename__ = "db_probe"

    name: Mapped[str] = mapped_column(String(40))


@pytest_asyncio.fixture
async def probe_table(migrator_engine: AsyncEngine) -> AsyncIterator[None]:
    # DDL como dono (hm_migrator); os default privileges dão DML ao hm_app.
    async with migrator_engine.begin() as conn:
        await conn.run_sync(ProbeBase.metadata.create_all)
    yield
    async with migrator_engine.begin() as conn:
        await conn.run_sync(ProbeBase.metadata.drop_all)


async def test_connects_as_app_role(app_engine: AsyncEngine) -> None:
    async with app_engine.connect() as conn:
        row = (
            await conn.execute(
                text(
                    "select current_user, current_database(), "
                    "current_setting('application_name'), r.rolbypassrls "
                    "from pg_roles r where r.rolname = current_user"
                )
            )
        ).one()
    assert tuple(row) == ("hm_app", "home", "pytest", False)


async def test_connects_as_migrator_role(migrator_engine: AsyncEngine) -> None:
    async with migrator_engine.connect() as conn:
        assert await conn.scalar(text("select current_user")) == "hm_migrator"


def test_base_is_bound_to_module_schema() -> None:
    table = ProbeBase.metadata.tables["identity.db_probe"]
    assert table is Probe.__table__
    assert table.schema == "identity"
    assert table.primary_key.name == "pk_db_probe"


async def test_orm_round_trip_as_app_role(app_engine: AsyncEngine, probe_table: None) -> None:
    sessions = create_session_factory(app_engine)

    async with sessions.begin() as session:
        probe = Probe(name="primeiro")
        session.add(probe)
    assert probe.id.version == 7  # gerado na aplicação, antes do INSERT

    async with sessions() as session:
        loaded = await session.scalar(select(Probe).where(Probe.id == probe.id))
    assert loaded is not None
    assert loaded.name == "primeiro"


async def test_request_session_commits_before_response_and_rolls_back_on_error(
    empty_database_settings: DatabaseSettings,
) -> None:
    migrator = create_engine(empty_database_settings, "migrator")
    engine = create_engine(empty_database_settings, "app")
    try:
        async with migrator.begin() as conn:
            await conn.execute(text("create table identity.request_probe (value text)"))

        app = FastAPI()
        app.state.db_sessions = create_session_factory(engine)

        @app.post("/ok")
        async def ok(session: DbSession) -> None:
            await session.execute(text("insert into identity.request_probe values ('ok')"))

        @app.post("/fail")
        async def fail(session: DbSession) -> None:
            await session.execute(text("insert into identity.request_probe values ('fail')"))
            raise RuntimeError("boom")

        transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as http:
            assert (await http.post("/ok")).status_code == 200
            # Lido por outra conexão logo após a resposta: o commit já aconteceu.
            async with migrator.connect() as conn:
                rows = await conn.scalars(text("select value from identity.request_probe"))
                assert rows.all() == ["ok"]

            assert (await http.post("/fail")).status_code == 500
            async with migrator.connect() as conn:
                rows = await conn.scalars(text("select value from identity.request_probe"))
                assert rows.all() == ["ok"]
    finally:
        await engine.dispose()
        await migrator.dispose()
