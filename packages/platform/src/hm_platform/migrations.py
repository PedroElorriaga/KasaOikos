"""Migrações por módulo (design D3): um ambiente Alembic por módulo, com a
``version_table`` no schema do próprio módulo.

O ``env.py`` de cada módulo só chama :func:`run_env`. Quem abre a conexão é o runner
(:func:`upgrade`, :func:`downgrade`), sempre como ``hm_migrator``.
"""

from collections.abc import Callable, Sequence
from dataclasses import dataclass

from alembic import command
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import Connection, MetaData
from sqlalchemy.ext.asyncio import AsyncEngine

VERSION_TABLE = "alembic_version"


@dataclass(frozen=True)
class ModuleMigrations:
    name: str
    schema: str
    # Formato "pacote:diretório", ex.: "hm_identity:migrations".
    script_location: str

    def config(self, connection: Connection | None = None) -> Config:
        cfg = Config()
        cfg.set_main_option("script_location", self.script_location)
        cfg.attributes["connection"] = connection
        return cfg

    def heads(self) -> set[str]:
        return set(ScriptDirectory.from_config(self.config()).get_heads())


def run_env(target_metadata: MetaData) -> None:
    """Corpo do ``env.py`` de um módulo. Só funciona chamado pelo runner."""
    from alembic import context  # proxy válido só dentro do env.py

    schema = target_metadata.schema
    if schema is None:
        raise RuntimeError("o metadata do módulo precisa de schema (use schema_metadata)")
    connection = context.config.attributes.get("connection")
    if connection is None:
        raise RuntimeError("rode as migrações com `hm migrate`; modo offline não é suportado")

    def include_name(name: str | None, type_: str, parent_names: object) -> bool:
        # O autogenerate só compara o schema do módulo, nunca os dos outros.
        return name == schema if type_ == "schema" else True

    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        version_table=VERSION_TABLE,
        version_table_schema=schema,
        include_schemas=True,
        include_name=include_name,
    )
    with context.begin_transaction():
        context.run_migrations()


async def _run(
    engine: AsyncEngine, module: ModuleMigrations, action: Callable[[Config], object]
) -> None:
    async with engine.connect() as conn:
        await conn.run_sync(lambda sync_conn: action(module.config(sync_conn)))
        await conn.commit()


async def upgrade(
    engine: AsyncEngine, modules: Sequence[ModuleMigrations], revision: str = "heads"
) -> None:
    for module in modules:
        await _run(engine, module, lambda cfg: command.upgrade(cfg, revision))


async def downgrade(
    engine: AsyncEngine, modules: Sequence[ModuleMigrations], revision: str = "base"
) -> None:
    # Ordem inversa da subida.
    for module in reversed(modules):
        await _run(engine, module, lambda cfg: command.downgrade(cfg, revision))


async def current(engine: AsyncEngine, modules: Sequence[ModuleMigrations]) -> dict[str, set[str]]:
    result: dict[str, set[str]] = {}
    async with engine.connect() as conn:
        for module in modules:

            def read(sync_conn: Connection, schema: str = module.schema) -> set[str]:
                ctx = MigrationContext.configure(
                    sync_conn,
                    opts={"version_table": VERSION_TABLE, "version_table_schema": schema},
                )
                return set(ctx.get_current_heads())

            result[module.name] = await conn.run_sync(read)
    return result


async def revision(
    engine: AsyncEngine, module: ModuleMigrations, message: str, *, autogenerate: bool
) -> None:
    # O autogenerate compara os modelos com o banco, por isso também precisa de conexão.
    await _run(
        engine,
        module,
        lambda cfg: command.revision(cfg, message=message, autogenerate=autogenerate),
    )
