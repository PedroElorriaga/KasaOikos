"""Guarda de RLS (design D4; cenário "Tabela nova sem isolamento").

Toda tabela de qualquer módulo com coluna ``household_id`` precisa de Row Level
Security habilitado e forçado. Este teste roda sobre o banco com todas as migrações.
"""

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from hm_platform.db import create_engine
from hm_platform.rls import enable_rls, tenant_isolation, tenant_tables
from hm_platform.settings import DatabaseSettings


async def test_every_table_with_household_id_has_forced_rls(
    migrator_engine: AsyncEngine, migrated_database: None
) -> None:
    async with migrator_engine.connect() as conn:
        tables = await tenant_tables(conn)

    unprotected = sorted(name for name, protected in tables.items() if not protected)
    assert unprotected == [], (
        f"tabelas com household_id sem RLS habilitado e forçado: {unprotected}"
    )
    # O guarda não pode passar "no vazio": as tabelas conhecidas precisam aparecer.
    assert {"identity.invites", "identity.memberships"} <= tables.keys()


async def test_guard_detects_table_without_rls(empty_database_settings: DatabaseSettings) -> None:
    """Verificação da tarefa 5.2: uma tabela nova sem RLS é detectada."""
    engine = create_engine(empty_database_settings, "migrator")
    try:
        async with engine.begin() as conn:
            for table in ("finance.no_rls", "finance.enabled_only", "finance.protected"):
                await conn.execute(text(f"create table {table} (id int, household_id uuid)"))
            await conn.execute(text(enable_rls("finance.enabled_only")[0]))  # ENABLE sem FORCE
            for statement in tenant_isolation("finance.protected"):
                await conn.execute(text(statement))

        async with engine.connect() as conn:
            assert await tenant_tables(conn) == {
                "finance.enabled_only": False,
                "finance.no_rls": False,
                "finance.protected": True,
            }
    finally:
        await engine.dispose()
