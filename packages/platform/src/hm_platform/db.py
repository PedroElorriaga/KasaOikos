"""Engine e sessões async do SQLAlchemy (asyncpg) e blocos para os modelos dos módulos.

Cada módulo declara a própria base, presa ao seu schema (design D3)::

    class Base(DeclarativeBase):
        metadata = schema_metadata("identity")

Subclasses diretas de ``DeclarativeBase`` têm registry e metadata próprios, então o
Alembic de cada módulo só enxerga as tabelas dele.
"""

import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy import MetaData
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import Mapped, mapped_column

from hm_platform.ids import uuid7
from hm_platform.settings import DatabaseRole, DatabaseSettings

# Nomes de constraints determinísticos: o autogenerate do Alembic consegue
# compará-los e as migrações de downgrade sabem o que remover.
NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


def schema_metadata(schema: str) -> MetaData:
    return MetaData(schema=schema, naming_convention=NAMING_CONVENTION)


class UUIDv7PrimaryKey:
    """Mixin: chave primária ``id`` UUIDv7 gerada na aplicação."""

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid7)


def create_engine(
    settings: DatabaseSettings,
    role: DatabaseRole = "app",
    *,
    application_name: str = "home-api",
) -> AsyncEngine:
    return create_async_engine(
        settings.url(role),
        pool_size=settings.pool_size,
        max_overflow=settings.max_overflow,
        pool_timeout=settings.pool_timeout_seconds,
        # Aparece em pg_stat_activity: ajuda a separar API, migrações e seed.
        connect_args={"server_settings": {"application_name": application_name}},
    )


def create_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    # expire_on_commit=False: objetos continuam legíveis após o commit (ex.: na resposta).
    return async_sessionmaker(engine, expire_on_commit=False)


type AfterCommit = Callable[[], Awaitable[None]]


def after_commit(session: AsyncSession, callback: AfterCommit) -> None:
    """Agenda ``callback`` para depois do commit da requisição (ex.: invalidar cache).

    Se a transação for desfeita, o callback é descartado: o cache não é limpo à toa, e
    nunca antes de o dado novo estar visível para as outras conexões.
    """
    session.info.setdefault("after_commit", []).append(callback)


async def run_after_commit(session: AsyncSession) -> None:
    callbacks: list[AfterCommit] = session.info.pop("after_commit", [])
    for callback in callbacks:
        await callback()


def discard_after_commit(session: AsyncSession) -> None:
    session.info.pop("after_commit", None)


async def get_db_session(request: Request) -> AsyncIterator[AsyncSession]:
    """Dependency FastAPI: uma sessão e uma transação por requisição.

    Use pelo alias :data:`DbSession`, que tem ``scope="function"``: o commit acontece
    logo que o endpoint retorna, antes de a resposta sair. Assim o cliente nunca recebe
    um 2xx de uma escrita que depois falhou no commit. Qualquer exceção (inclusive
    ``HTTPException``) desfaz a transação.
    """
    sessions: async_sessionmaker[AsyncSession] = request.app.state.db_sessions
    async with sessions() as session:
        try:
            async with session.begin():
                yield session
        except BaseException:
            discard_after_commit(session)
            raise
        await run_after_commit(session)


DbSession = Annotated[AsyncSession, Depends(get_db_session, scope="function")]
