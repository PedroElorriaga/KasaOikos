from collections.abc import Iterator

import sqlalchemy
from fastapi import Request
from sqlalchemy import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import Settings

# Segundos para desistir de abrir conexão. Mantém o /health rápido quando o banco cai.
_CONNECT_TIMEOUT = 2


class Base(DeclarativeBase):
    """Base dos modelos do ORM. O schema é criado pelas migrations, não por esta metadata."""


def criar_engine(settings: Settings) -> Engine:
    # Pelo módulo, não por `from sqlalchemy import create_engine`: a instrumentação do OTel
    # (app.observabilidade) troca `sqlalchemy.create_engine` em tempo de execução.
    return sqlalchemy.create_engine(
        settings.database_url.get_secret_value(),
        # Testa a conexão antes de usar: descarta conexões mortas do pool.
        pool_pre_ping=True,
        connect_args={"connect_timeout": _CONNECT_TIMEOUT},
    )


def criar_fabrica_sessoes(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, expire_on_commit=False)


def sessao(request: Request) -> Iterator[Session]:
    """Dependência FastAPI: uma sessão por requisição, fechada ao final."""
    fabrica: sessionmaker[Session] = request.app.state.fabrica_sessoes
    with fabrica() as s:
        yield s
