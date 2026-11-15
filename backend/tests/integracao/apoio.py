"""Helpers dos testes de integração."""

from pathlib import Path

from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from pydantic import SecretStr
from testcontainers.community.postgres import PostgresContainer

from app.config import Settings
from app.main import create_app
from tests.integracao.tokens import AUDIENCIA, EMISSOR

IMAGEM_POSTGRES = "postgres:17-alpine"
# Origem do front liberada no CORS dos clientes de teste.
ORIGEM_FRONT = "http://localhost:5173"
ALEMBIC_INI = Path(__file__).resolve().parents[2] / "alembic.ini"


def novo_postgres() -> PostgresContainer:
    return PostgresContainer(IMAGEM_POSTGRES, driver="psycopg")


def config_alembic(url: str) -> Config:
    config = Config(str(ALEMBIC_INI))
    config.attributes["database_url"] = url
    config.attributes["configurar_logs"] = False
    return config


def aplicar_migrations(postgres: PostgresContainer) -> None:
    command.upgrade(config_alembic(postgres.get_connection_url()), "head")


def cliente_para(postgres: PostgresContainer, *, jwks_url: str) -> TestClient:
    settings = Settings(
        database_url=SecretStr(postgres.get_connection_url()),
        oidc_issuer=EMISSOR,
        oidc_audience=AUDIENCIA,
        oidc_jwks_url=jwks_url,
        cors_origins=[ORIGEM_FRONT],
    )
    return TestClient(create_app(settings))
