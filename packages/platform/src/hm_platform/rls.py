"""Row Level Security por lar (design D4): SQL para migrações e contexto por transação.

Nas migrações::

    for statement in tenant_isolation("finance.entries"):
        op.execute(statement)
"""

import uuid

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession

# Uma conexão que já teve SET LOCAL numa transação anterior devolve '' (e não NULL)
# para o parâmetro; ''::uuid daria erro, por isso o nullif.
CURRENT_HOUSEHOLD = "nullif(current_setting('app.household_id', true), '')::uuid"
CURRENT_USER = "nullif(current_setting('app.user_id', true), '')::uuid"


def enable_rls(table: str) -> list[str]:
    """Habilita e força RLS: com FORCE, nem o dono da tabela escapa das políticas."""
    return [
        f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY",
        f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY",
    ]


def tenant_isolation(table: str) -> list[str]:
    """Política padrão de toda tabela com ``household_id``: só o lar ativo, para ler e escrever."""
    return [
        *enable_rls(table),
        f"CREATE POLICY tenant_isolation ON {table} "
        f"USING (household_id = {CURRENT_HOUSEHOLD}) "
        f"WITH CHECK (household_id = {CURRENT_HOUSEHOLD})",
    ]


async def set_tenant_context(
    session: AsyncSession,
    *,
    user_id: uuid.UUID | None,
    household_id: uuid.UUID | None,
) -> None:
    """Define usuário e lar ativos da transação corrente (``set_config(..., true)`` = LOCAL).

    ``None`` limpa o valor. Vale só até o fim da transação, o que é compatível com
    PgBouncer em modo transaction.
    """
    await session.execute(
        text(
            "select set_config('app.user_id', :u, true), set_config('app.household_id', :h, true)"
        ),
        {"u": str(user_id) if user_id else "", "h": str(household_id) if household_id else ""},
    )


_TENANT_TABLES_SQL = text(
    """
    select c.table_schema || '.' || c.table_name as name,
           t.relrowsecurity and t.relforcerowsecurity as protected
    from information_schema.columns c
    join pg_namespace n on n.nspname = c.table_schema
    join pg_class t on t.relnamespace = n.oid and t.relname = c.table_name
    where c.column_name = 'household_id'
      and t.relkind in ('r', 'p')
      and c.table_schema not in ('pg_catalog', 'information_schema')
    order by 1
    """
)


async def tenant_tables(conn: AsyncConnection) -> dict[str, bool]:
    """Tabelas com ``household_id`` → se têm RLS habilitado **e** forçado.

    Rode como dono das tabelas (``hm_migrator``): o ``information_schema`` só lista
    colunas de tabelas às quais o usuário corrente tem acesso.
    """
    rows = await conn.execute(_TENANT_TABLES_SQL)
    return {str(name): bool(protected) for name, protected in rows}
