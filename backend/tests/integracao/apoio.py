"""Helpers dos testes de integração."""

from fastapi.testclient import TestClient
from pydantic import SecretStr
from testcontainers.community.postgres import PostgresContainer

from app.config import Settings
from app.main import create_app

IMAGEM_POSTGRES = "postgres:17-alpine"


def novo_postgres() -> PostgresContainer:
    return PostgresContainer(IMAGEM_POSTGRES, driver="psycopg")


def cliente_para(postgres: PostgresContainer) -> TestClient:
    settings = Settings(database_url=SecretStr(postgres.get_connection_url()))
    return TestClient(create_app(settings))
