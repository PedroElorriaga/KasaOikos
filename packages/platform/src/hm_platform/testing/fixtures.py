"""Fixtures pytest compartilhadas (design D10).

- Postgres e Valkey reais via testcontainers, um container de cada por sessão.
- ``db_session``: sessão como ``hm_app`` numa transação revertida ao fim de cada teste.
- ``redis_client``: banco Redis limpo a cada teste.
- ``client``: cliente HTTP para a fixture ``app`` (definida no conftest raiz, que conhece
  o ``hm_api``; o ``hm_platform`` não pode importá-lo).
"""

import secrets
from collections.abc import AsyncIterator, Iterator, Sequence
from dataclasses import dataclass

import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI
from opentelemetry.sdk.metrics.export import InMemoryMetricReader
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from pydantic import SecretStr
from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.engine import URL
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, create_async_engine
from testcontainers.community.postgres import PostgresContainer
from testcontainers.community.redis import RedisContainer

from hm_platform import migrations
from hm_platform.cache import create_redis
from hm_platform.db import create_engine
from hm_platform.migrations import ModuleMigrations
from hm_platform.settings import (
    DatabaseSettings,
    OIDCSettings,
    OTelSettings,
    RedisSettings,
    Settings,
)
from hm_platform.telemetry import Telemetry, create_telemetry
from hm_platform.testing import tokens
from hm_platform.testing.tokens import FakeJWKS, SigningKey, TokenFactory

# Mesmas imagens do infra/compose.yaml.
POSTGRES_IMAGE = "pgvector/pgvector:0.8.2-pg17"
VALKEY_IMAGE = "valkey/valkey:8.1-alpine"
# Cópia do banco "home" logo após o init (schemas, grants, nenhuma tabela). Ninguém se
# conecta a ela, então pode servir de TEMPLATE para bancos vazios a qualquer momento.
TEMPLATE_DATABASE = "home_template"


@dataclass(frozen=True)
class PostgresServer:
    host: str
    port: int
    superuser_password: str
    app_password: str
    migrator_password: str

    def database_settings(self, name: str = "home") -> DatabaseSettings:
        return DatabaseSettings(
            host=self.host,
            port=self.port,
            name=name,
            app_password=SecretStr(self.app_password),
            migrator_password=SecretStr(self.migrator_password),
            pool_size=5,
        )

    def superuser_url(self) -> URL:
        return URL.create(
            "postgresql+asyncpg",
            username="postgres",
            password=self.superuser_password,
            host=self.host,
            port=self.port,
            database="postgres",
        )


@pytest.fixture(scope="session")
def postgres_server(pytestconfig: pytest.Config) -> Iterator[PostgresServer]:
    """Sobe o Postgres uma vez por sessão, com os mesmos scripts de init do Compose.

    Assim os testes rodam com os roles reais: ``hm_app`` sujeito a RLS e ``hm_migrator``
    dono dos schemas.
    """
    superuser_password = secrets.token_hex(16)
    app_password, migrator_password = secrets.token_hex(16), secrets.token_hex(16)
    init_dir = pytestconfig.rootpath / "infra" / "postgres" / "init"
    container = (
        PostgresContainer(
            POSTGRES_IMAGE,
            username="postgres",
            password=superuser_password,
            dbname="postgres",
            driver=None,
        )
        .with_env("KEYCLOAK_DB_PASSWORD", secrets.token_hex(16))
        .with_env("HM_MIGRATOR_PASSWORD", migrator_password)
        .with_env("HM_APP_PASSWORD", app_password)
        .with_volume_mapping(str(init_dir), "/docker-entrypoint-initdb.d", "ro")
    )
    # A espera do testcontainers usa psql por TCP, que só responde depois dos
    # scripts de init (o servidor temporário do init escuta apenas no socket Unix).
    with container:
        exit_code, output = container.exec(
            [
                "psql", "-U", "postgres", "-v", "ON_ERROR_STOP=1", "-c",
                f"CREATE DATABASE {TEMPLATE_DATABASE} TEMPLATE home",
            ]
        )  # fmt: skip
        if exit_code != 0:
            raise RuntimeError(f"falha ao criar {TEMPLATE_DATABASE}: {output.decode()}")
        yield PostgresServer(
            host=container.get_container_host_ip(),
            port=int(container.get_exposed_port(5432)),
            superuser_password=superuser_password,
            app_password=app_password,
            migrator_password=migrator_password,
        )


@pytest.fixture(scope="session")
def database_settings(postgres_server: PostgresServer) -> DatabaseSettings:
    """Banco ``home`` compartilhado pela sessão."""
    return postgres_server.database_settings()


@pytest_asyncio.fixture
async def empty_database_settings(
    postgres_server: PostgresServer,
) -> AsyncIterator[DatabaseSettings]:
    """Banco novo e vazio, exclusivo do teste (para migrações ou dados que precisam de commit)."""
    name = f"test_{secrets.token_hex(6)}"
    admin = create_async_engine(postgres_server.superuser_url(), isolation_level="AUTOCOMMIT")
    try:
        async with admin.connect() as conn:
            await conn.execute(
                text(f"CREATE DATABASE {name} TEMPLATE {TEMPLATE_DATABASE} OWNER hm_migrator")
            )
            # Privilégios de banco não são copiados do template (os de schema, sim).
            await conn.execute(text(f"REVOKE ALL ON DATABASE {name} FROM PUBLIC"))
            await conn.execute(text(f"GRANT CONNECT, TEMPORARY ON DATABASE {name} TO hm_app"))
        yield postgres_server.database_settings(name)
        async with admin.connect() as conn:
            await conn.execute(text(f"DROP DATABASE {name} WITH (FORCE)"))
    finally:
        await admin.dispose()


@pytest_asyncio.fixture(scope="session")
async def app_engine(database_settings: DatabaseSettings) -> AsyncIterator[AsyncEngine]:
    """Engine como ``hm_app``, o mesmo role da API."""
    engine = create_engine(database_settings, "app", application_name="pytest")
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture(scope="session")
async def migrator_engine(database_settings: DatabaseSettings) -> AsyncIterator[AsyncEngine]:
    """Engine como ``hm_migrator``, para DDL e preparação de dados nos testes."""
    engine = create_engine(database_settings, "migrator", application_name="pytest-migrator")
    yield engine
    await engine.dispose()


@pytest.fixture(scope="session")
def module_migrations() -> Sequence[ModuleMigrations]:
    """Módulos cujas migrações sobem no banco da sessão. O conftest raiz sobrescreve."""
    return ()


@pytest_asyncio.fixture(scope="session")
async def migrated_database(
    migrator_engine: AsyncEngine, module_migrations: Sequence[ModuleMigrations]
) -> None:
    """Banco ``home`` com as migrações de todos os módulos aplicadas (uma vez por sessão)."""
    await migrations.upgrade(migrator_engine, module_migrations)


@pytest_asyncio.fixture
async def db_session(
    app_engine: AsyncEngine, migrated_database: None
) -> AsyncIterator[AsyncSession]:
    """Sessão como ``hm_app`` dentro de uma transação desfeita ao fim do teste.

    Com ``join_transaction_mode="create_savepoint"``, cada ``commit()`` do código testado
    vira um SAVEPOINT da transação externa: nada chega a ser gravado de verdade.
    """
    async with app_engine.connect() as conn:
        transaction = await conn.begin()
        session = AsyncSession(
            bind=conn, join_transaction_mode="create_savepoint", expire_on_commit=False
        )
        try:
            yield session
        finally:
            await session.close()
            await transaction.rollback()


@pytest.fixture(scope="session")
def redis_settings() -> Iterator[RedisSettings]:
    password = secrets.token_hex(16)
    with RedisContainer(VALKEY_IMAGE, password=password) as container:
        yield RedisSettings(
            host=container.get_container_host_ip(),
            port=int(container.get_exposed_port(6379)),
            password=SecretStr(password),
        )


@pytest_asyncio.fixture
async def redis_client(redis_settings: RedisSettings) -> AsyncIterator[Redis]:
    client = create_redis(redis_settings)
    await client.flushdb()
    try:
        yield client
    finally:
        await client.flushdb()
        await client.aclose()


@pytest.fixture(scope="session")
def settings(database_settings: DatabaseSettings, redis_settings: RedisSettings) -> Settings:
    """Configuração completa apontando para os containers, sem ler o ambiente da máquina."""
    return Settings(
        _env_file=None,  # type: ignore[call-arg]
        db=database_settings,
        redis=redis_settings,
        oidc=OIDCSettings(issuer=tokens.ISSUER, audience=tokens.AUDIENCE, jwks_url=tokens.JWKS_URL),
        otel=OTelSettings(enabled=False),
        workers=1,
    )


@pytest_asyncio.fixture
async def client(app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    """Cliente HTTP em processo (sem rede), com o lifespan da app em execução."""
    transport = httpx.ASGITransport(app=app)
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(transport=transport, base_url="http://test") as http,
    ):
        yield http


@pytest.fixture(scope="session")
def signing_key() -> SigningKey:
    """Chave RSA do "provedor de identidade" nos testes (gerá-la custa ~50 ms)."""
    return SigningKey.generate("test-key-1")


@pytest.fixture
def fake_jwks(signing_key: SigningKey) -> FakeJWKS:
    """JWKS falso, novo a cada teste (contador de fetches zerado)."""
    return FakeJWKS(keys=[signing_key])


@pytest.fixture
def token_factory(signing_key: SigningKey) -> TokenFactory:
    return TokenFactory(key=signing_key)


@pytest.fixture
def span_exporter() -> InMemorySpanExporter:
    return InMemorySpanExporter()


@pytest.fixture
def metric_reader() -> InMemoryMetricReader:
    return InMemoryMetricReader()


@pytest.fixture
def telemetry(
    settings: Settings, span_exporter: InMemorySpanExporter, metric_reader: InMemoryMetricReader
) -> Telemetry:
    """Telemetria da app de teste: spans e métricas ficam em memória para inspeção."""
    return create_telemetry(settings.otel, span_exporter=span_exporter, metric_reader=metric_reader)
