"""Fixtures dos testes de integração: Postgres real via testcontainers (requer Docker)."""

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from testcontainers.community.postgres import PostgresContainer

from tests.integracao.apoio import cliente_para, novo_postgres


@pytest.fixture(scope="session")
def postgres() -> Iterator[PostgresContainer]:
    """Um Postgres compartilhado pela sessão de testes."""
    with novo_postgres() as container:
        yield container


@pytest.fixture
def cliente(postgres: PostgresContainer) -> Iterator[TestClient]:
    with cliente_para(postgres) as cliente:
        yield cliente


@pytest.fixture
def postgres_descartavel() -> Iterator[PostgresContainer]:
    """Postgres exclusivo do teste, que pode ser derrubado sem afetar os demais."""
    with novo_postgres() as container:
        yield container
