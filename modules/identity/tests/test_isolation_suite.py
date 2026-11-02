"""Suíte de isolamento entre lares (design D10, tarefa 5.9).

Para cada rota com escopo de lar registrada na app, um usuário do lar A (admin lá, para o
papel não interferir) tenta agir no lar B: a resposta tem de ser 404 e nada em B pode mudar.

As rotas com escopo de lar são descobertas pela árvore de dependencies (quem depende de
``get_path_tenant`` ou ``get_header_tenant``), não por uma lista escrita à mão: uma rota
nova sem caso aqui faz :func:`test_every_household_scoped_route_has_a_case` falhar.
"""

import uuid
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI
from fastapi.dependencies.models import Dependant
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from hm_api.main import create_app
from hm_identity.domain.invites import hash_code
from hm_platform.ids import uuid7
from hm_platform.rls import set_tenant_context
from hm_platform.settings import Settings
from hm_platform.tenancy import HOUSEHOLD_HEADER, get_header_tenant, get_path_tenant
from hm_platform.testing.routes import iter_routes
from hm_platform.testing.tokens import TokenFactory

from .conftest import World, auth

TENANT_DEPENDENCIES = {get_path_tenant, get_header_tenant}


@dataclass(frozen=True)
class Targets:
    """Recursos do lar B que as rotas referenciam além do próprio lar."""

    household: uuid.UUID
    member: uuid.UUID
    invite: uuid.UUID


@dataclass(frozen=True)
class Case:
    path: Callable[[Targets], str]
    body: dict[str, Any] | None = None


# (método, template da rota) → como montar a requisição contra o lar B.
CASES: dict[tuple[str, str], Case] = {
    ("GET", "/households/{household_id}"): Case(lambda t: f"/households/{t.household}"),
    ("PATCH", "/households/{household_id}"): Case(
        lambda t: f"/households/{t.household}", {"name": "invadido"}
    ),
    ("GET", "/households/{household_id}/members"): Case(
        lambda t: f"/households/{t.household}/members"
    ),
    ("PATCH", "/households/{household_id}/members/{user_id}"): Case(
        lambda t: f"/households/{t.household}/members/{t.member}", {"role": "member"}
    ),
    ("DELETE", "/households/{household_id}/members/{user_id}"): Case(
        lambda t: f"/households/{t.household}/members/{t.member}"
    ),
    ("POST", "/households/{household_id}/invites"): Case(
        lambda t: f"/households/{t.household}/invites", {"role": "admin"}
    ),
    ("GET", "/households/{household_id}/invites"): Case(
        lambda t: f"/households/{t.household}/invites"
    ),
    ("DELETE", "/households/{household_id}/invites/{invite_id}"): Case(
        lambda t: f"/households/{t.household}/invites/{t.invite}"
    ),
}


def depends_on_tenant(dependant: Dependant) -> bool:
    return any(
        sub.call in TENANT_DEPENDENCIES or depends_on_tenant(sub) for sub in dependant.dependencies
    )


def household_scoped_routes(app: FastAPI) -> set[tuple[str, str]]:
    return {
        (method, path)
        for path, route, inherited in iter_routes(app.routes)
        if depends_on_tenant(route.dependant) or TENANT_DEPENDENCIES & set(inherited)
        for method in route.methods or ()
    }


def test_every_household_scoped_route_has_a_case(settings: Settings) -> None:
    scoped = household_scoped_routes(create_app(settings))  # só monta as rotas; sem lifespan
    assert scoped, "nenhuma rota com escopo de lar encontrada: a detecção quebrou?"
    missing = scoped - CASES.keys()
    assert not missing, f"rotas com escopo de lar sem caso de isolamento: {sorted(missing)}"
    assert not CASES.keys() - scoped, "há casos para rotas que não existem (ou perderam o escopo)"


@pytest_asyncio.fixture
async def targets(db_session: AsyncSession, world: World) -> Targets:
    await set_tenant_context(db_session, user_id=None, household_id=world.household_b)
    invite = uuid7()
    await db_session.execute(
        text(
            "insert into identity.invites "
            "(id, household_id, code_hash, role, expires_at, created_by) "
            "values (:id, :h, :hash, 'member', now() + interval '7 days', :by)"
        ),
        {"id": invite, "h": world.household_b, "hash": hash_code("b-code"), "by": world.carol},
    )
    await set_tenant_context(db_session, user_id=None, household_id=None)
    return Targets(household=world.household_b, member=world.carol, invite=invite)


async def snapshot(session: AsyncSession, household: uuid.UUID) -> dict[str, object]:
    """Tudo o que existe no lar B, lido no contexto de B."""
    await set_tenant_context(session, user_id=None, household_id=household)
    result: dict[str, object] = {
        "household": (
            await session.execute(text("select id, name from identity.households"))
        ).all(),
        "members": (
            await session.execute(
                text("select user_id, role from identity.memberships where household_id = :h"),
                {"h": household},
            )
        ).all(),
        "invites": (await session.execute(text("select id, status from identity.invites"))).all(),
    }
    await set_tenant_context(session, user_id=None, household_id=None)
    return result


@pytest.mark.parametrize(("method", "route"), sorted(CASES), ids=lambda v: str(v))
async def test_user_of_household_a_gets_404_on_household_b(
    client: httpx.AsyncClient,
    token_factory: TokenFactory,
    db_session: AsyncSession,
    world: World,
    targets: Targets,
    method: str,
    route: str,
) -> None:
    case = CASES[(method, route)]
    before = await snapshot(db_session, world.household_b)

    response = await client.request(
        method,
        case.path(targets),
        # Header coerente com o caminho: o teste é de membership, não de divergência.
        headers=auth(token_factory, "alice", **{HOUSEHOLD_HEADER: str(world.household_b)}),
        json=case.body,
    )

    assert response.status_code == 404, response.text
    assert await snapshot(db_session, world.household_b) == before
