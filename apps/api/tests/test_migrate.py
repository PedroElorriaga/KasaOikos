"""`hm migrate` com os módulos reais, num banco vazio: sobe, desce e sobe de novo.

Toda migração nova de qualquer módulo passa a ser exercitada aqui, inclusive o downgrade.
"""

import asyncio
from collections.abc import Iterator

import pytest
from sqlalchemy import text

from hm_api.cli import main
from hm_api.modules import MIGRATIONS
from hm_platform import migrations
from hm_platform.db import create_engine
from hm_platform.settings import DatabaseSettings, get_settings

SCHEMAS = [m.schema for m in MIGRATIONS]


@pytest.fixture
def cli_env(
    empty_database_settings: DatabaseSettings, monkeypatch: pytest.MonkeyPatch
) -> Iterator[DatabaseSettings]:
    db = empty_database_settings
    assert db.migrator_password is not None
    monkeypatch.setenv("HM_DB__HOST", db.host)
    monkeypatch.setenv("HM_DB__PORT", str(db.port))
    monkeypatch.setenv("HM_DB__NAME", db.name)
    monkeypatch.setenv("HM_DB__APP_PASSWORD", db.app_password.get_secret_value())
    monkeypatch.setenv("HM_DB__MIGRATOR_PASSWORD", db.migrator_password.get_secret_value())
    get_settings.cache_clear()
    yield db
    get_settings.cache_clear()


def snapshot(db: DatabaseSettings) -> dict[str, object]:
    """Tabelas por schema e revisões atuais, lidas com uma engine própria."""

    async def read() -> dict[str, object]:
        engine = create_engine(db, "migrator")
        try:
            async with engine.connect() as conn:
                rows = await conn.execute(
                    text(
                        "select schemaname, tablename from pg_tables "
                        "where schemaname = any(:schemas) order by 1, 2"
                    ),
                    {"schemas": SCHEMAS},
                )
                tables: dict[str, list[str]] = {s: [] for s in SCHEMAS}
                for schema, table in rows:
                    tables[schema].append(table)
            return {"tables": tables, "current": await migrations.current(engine, MIGRATIONS)}
        finally:
            await engine.dispose()

    return asyncio.run(read())


def test_migrate_up_down_up_on_empty_database(cli_env: DatabaseSettings) -> None:
    heads = {m.name: m.heads() for m in MIGRATIONS}

    assert main(["migrate"]) == 0
    after_up = snapshot(cli_env)
    assert after_up["current"] == heads
    # Cada módulo tem a própria version_table, no próprio schema.
    tables = after_up["tables"]
    assert isinstance(tables, dict)
    assert all("alembic_version" in tables[s] for s in SCHEMAS)

    assert main(["migrate", "down"]) == 2  # sem --yes, nada acontece
    assert snapshot(cli_env) == after_up

    assert main(["migrate", "down", "--yes"]) == 0
    assert snapshot(cli_env) == {
        "tables": {s: ["alembic_version"] for s in SCHEMAS},
        "current": {m.name: set() for m in MIGRATIONS},
    }

    assert main(["migrate", "up"]) == 0
    assert snapshot(cli_env) == after_up


def test_migrate_current_prints_each_module(
    cli_env: DatabaseSettings, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["migrate"]) == 0
    assert main(["migrate", "current"]) == 0
    printed = capsys.readouterr().out.splitlines()
    assert [line.split()[0] for line in printed] == [m.name for m in MIGRATIONS]
