"""Conftest raiz: registra as fixtures compartilhadas e liga-as aos módulos do monolito."""

from collections.abc import AsyncIterator, Sequence

import pytest
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncSession

from hm_api.main import create_app
from hm_api.modules import MIGRATIONS
from hm_platform.db import discard_after_commit, get_db_session, run_after_commit
from hm_platform.migrations import ModuleMigrations
from hm_platform.settings import Settings
from hm_platform.telemetry import Telemetry
from hm_platform.testing.tokens import FakeJWKS

pytest_plugins = ["hm_platform.testing.fixtures"]


@pytest.fixture(scope="session")
def module_migrations() -> Sequence[ModuleMigrations]:
    return MIGRATIONS


@pytest.fixture
def app(
    settings: Settings, fake_jwks: FakeJWKS, db_session: AsyncSession, telemetry: Telemetry
) -> FastAPI:
    """App real, com JWKS falso, telemetria em memória e a sessão de banco revertida."""
    app = create_app(settings, http_transport=fake_jwks.transport(), telemetry=telemetry)

    async def test_session() -> AsyncIterator[AsyncSession]:
        # Como a sessão real: cada requisição numa transação (aqui, um SAVEPOINT) que é
        # desfeita em qualquer erro, e os callbacks pós-commit só rodam no sucesso.
        try:
            async with db_session.begin_nested():
                yield db_session
        except BaseException:
            discard_after_commit(db_session)
            raise
        await run_after_commit(db_session)

    app.dependency_overrides[get_db_session] = test_session
    return app
