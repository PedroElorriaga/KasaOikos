"""Fixtures dos testes de integração: Postgres real via testcontainers (requer Docker)."""

from collections.abc import Iterator

import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient
from testcontainers.community.postgres import PostgresContainer

from tests.integracao.apoio import aplicar_migrations, cliente_para, novo_postgres
from tests.integracao.tokens import gerar_chave, jwks_de, servidor_jwks


@pytest.fixture(scope="session")
def postgres() -> Iterator[PostgresContainer]:
    """Um Postgres compartilhado pela sessão de testes, com as migrations aplicadas."""
    with novo_postgres() as container:
        aplicar_migrations(container)
        yield container


@pytest.fixture(scope="session")
def chave_teste() -> rsa.RSAPrivateKey:
    """Chave que assina os tokens válidos; a pública é a servida no JWKS."""
    return gerar_chave()


@pytest.fixture(scope="session")
def jwks_url(chave_teste: rsa.RSAPrivateKey) -> Iterator[str]:
    with servidor_jwks(jwks_de(chave_teste)) as url:
        yield url


@pytest.fixture
def cliente(postgres: PostgresContainer, jwks_url: str) -> Iterator[TestClient]:
    with cliente_para(postgres, jwks_url=jwks_url) as cliente:
        yield cliente


@pytest.fixture
def postgres_descartavel() -> Iterator[PostgresContainer]:
    """Postgres exclusivo do teste, que pode ser derrubado sem afetar os demais."""
    with novo_postgres() as container:
        yield container
