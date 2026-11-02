from collections.abc import AsyncIterator
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from hm_platform import migrations
from hm_platform.db import create_engine
from hm_platform.migrations import ModuleMigrations
from hm_platform.settings import DatabaseSettings

ENV_PY = """
from hm_platform.db import schema_metadata
from hm_platform.migrations import run_env

run_env(schema_metadata("finance"))
"""

REVISION_1 = """
import sqlalchemy as sa
from alembic import op

revision = "r1"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("probe", sa.Column("id", sa.Integer, primary_key=True), schema="finance")


def downgrade():
    op.drop_table("probe", schema="finance")
"""

REVISION_2 = """
import sqlalchemy as sa
from alembic import op

revision = "r2"
down_revision = "r1"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("probe", sa.Column("name", sa.Text), schema="finance")


def downgrade():
    op.drop_column("probe", "name", schema="finance")
"""


@pytest_asyncio.fixture
async def engine(empty_database_settings: DatabaseSettings) -> AsyncIterator[AsyncEngine]:
    engine = create_engine(empty_database_settings, "migrator")
    yield engine
    await engine.dispose()


def fake_module(tmp_path: Path) -> ModuleMigrations:
    versions = tmp_path / "versions"
    versions.mkdir()
    (tmp_path / "env.py").write_text(ENV_PY)
    (versions / "r1.py").write_text(REVISION_1)
    (versions / "r2.py").write_text(REVISION_2)
    return ModuleMigrations(name="fake", schema="finance", script_location=str(tmp_path))


async def finance_state(engine: AsyncEngine) -> dict[str, object]:
    async with engine.connect() as conn:
        tables = (
            await conn.scalars(
                text(
                    "select tablename || ':' || tableowner from pg_tables "
                    "where schemaname = 'finance' order by 1"
                )
            )
        ).all()
        columns = (
            await conn.scalars(
                text(
                    "select column_name from information_schema.columns "
                    "where table_schema = 'finance' and table_name = 'probe' order by 1"
                )
            )
        ).all()
    return {"tables": tables, "columns": columns}


async def test_upgrade_applies_all_revisions_with_version_table_in_module_schema(
    engine: AsyncEngine, tmp_path: Path
) -> None:
    module = fake_module(tmp_path)

    await migrations.upgrade(engine, [module])

    assert await finance_state(engine) == {
        "tables": ["alembic_version:hm_migrator", "probe:hm_migrator"],
        "columns": ["id", "name"],
    }
    assert (
        await migrations.current(engine, [module]) == {"fake": {"r2"}} == {"fake": module.heads()}
    )


async def test_upgrade_is_idempotent(engine: AsyncEngine, tmp_path: Path) -> None:
    module = fake_module(tmp_path)

    await migrations.upgrade(engine, [module])
    await migrations.upgrade(engine, [module])

    assert await migrations.current(engine, [module]) == {"fake": {"r2"}}


async def test_autogenerate_revision_uses_module_template(
    engine: AsyncEngine, tmp_path: Path, pytestconfig: pytest.Config
) -> None:
    module = fake_module(tmp_path)
    template = pytestconfig.rootpath / "modules/finance/src/hm_finance/migrations/script.py.mako"
    (tmp_path / "script.py.mako").write_text(template.read_text(encoding="utf-8"), encoding="utf-8")
    await migrations.upgrade(engine, [module])
    async with engine.begin() as conn:
        await conn.execute(text("create table identity.other_module_table (id int)"))

    await migrations.revision(engine, module, "nothing changed", autogenerate=True)

    [new] = [p for p in (tmp_path / "versions").glob("*.py") if p.stem not in {"r1", "r2"}]
    source = new.read_text(encoding="utf-8")
    assert "down_revision: str | Sequence[str] | None = 'r2'" in source
    # O metadata do módulo falso está vazio: o autogenerate propõe remover "probe",
    # o que mostra que ele comparou o schema do módulo e só ele.
    assert "op.drop_table('probe', schema='finance')" in source
    assert "other_module_table" not in source
    assert "alembic_version" not in source


async def test_downgrade_reverts_everything(engine: AsyncEngine, tmp_path: Path) -> None:
    module = fake_module(tmp_path)
    await migrations.upgrade(engine, [module])

    await migrations.downgrade(engine, [module])

    assert await finance_state(engine) == {"tables": ["alembic_version:hm_migrator"], "columns": []}
    assert await migrations.current(engine, [module]) == {"fake": set()}
