"""Spec platform/tenant-isolation: determinação do lar ativo (5.3), verificação de
membership e revogação imediata (5.4), com a app real e rotas de teste.
"""

import uuid
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from hm_platform.db import DbSession, run_after_commit
from hm_platform.ids import uuid7
from hm_platform.rls import set_tenant_context
from hm_platform.tenancy import AdminTenant, HeaderTenant, MembershipCache, PathTenant, Role
from hm_platform.testing.tokens import TokenFactory

from .conftest import World, auth


class Payload(BaseModel):
    household_id: uuid.UUID | None = None


@pytest.fixture
def calls() -> list[str]:
    return []


@pytest.fixture
def routes(app: FastAPI, calls: list[str]) -> FastAPI:
    async def context(tenant: Any, session: AsyncSession, route: str) -> dict[str, str]:
        calls.append(route)
        db_household = await session.scalar(
            text("select current_setting('app.household_id', true)")
        )
        return {"household": str(tenant.household_id), "role": tenant.role, "db": str(db_household)}

    @app.get("/_test/households/{household_id}/context")
    async def by_path(tenant: PathTenant, session: DbSession) -> dict[str, str]:
        return await context(tenant, session, "path")

    @app.post("/_test/active-household")
    async def by_header(tenant: HeaderTenant, session: DbSession, body: Payload) -> dict[str, str]:
        return await context(tenant, session, "header")

    @app.get("/_test/households/{household_id}/admin-only")
    async def admin_only(tenant: AdminTenant) -> dict[str, str]:
        calls.append("admin")
        return {"ok": "yes"}

    return app


def cache_of(app: FastAPI) -> MembershipCache:
    cache: MembershipCache = app.state.membership_cache
    return cache


# --- 5.3 Requirement: Determinação do lar ativo ------------------------------------------


async def test_active_household_from_header(
    routes: FastAPI, client: httpx.AsyncClient, token_factory: TokenFactory, world: World
) -> None:
    headers = auth(token_factory, "alice", **{"X-Household-Id": str(world.household_a)})
    response = await client.post("/_test/active-household", headers=headers, json={})

    assert response.status_code == 200
    a = str(world.household_a)
    # O lar ativo também foi fixado na transação do banco (set_config), para o RLS.
    assert response.json() == {"household": a, "role": "admin", "db": a}


async def test_missing_header_returns_400(
    routes: FastAPI,
    client: httpx.AsyncClient,
    token_factory: TokenFactory,
    world: World,
    calls: list[str],
) -> None:
    response = await client.post(
        "/_test/active-household", headers=auth(token_factory, "alice"), json={}
    )
    assert response.status_code == 400
    assert "X-Household-Id" in response.json()["detail"]
    assert calls == []


@pytest.mark.parametrize("value", ["not-a-uuid", "123", ""])
async def test_malformed_header_returns_400(
    routes: FastAPI,
    client: httpx.AsyncClient,
    token_factory: TokenFactory,
    world: World,
    value: str,
) -> None:
    headers = auth(token_factory, "alice", **{"X-Household-Id": value})
    response = await client.post("/_test/active-household", headers=headers, json={})
    assert response.status_code == 400


async def test_path_and_divergent_header_returns_400_and_nothing_runs(
    routes: FastAPI,
    client: httpx.AsyncClient,
    token_factory: TokenFactory,
    world: World,
    calls: list[str],
) -> None:
    headers = auth(token_factory, "carol", **{"X-Household-Id": str(world.household_a)})
    response = await client.get(f"/_test/households/{world.household_b}/context", headers=headers)
    assert response.status_code == 400
    assert calls == []


async def test_path_with_matching_header_is_accepted(
    routes: FastAPI, client: httpx.AsyncClient, token_factory: TokenFactory, world: World
) -> None:
    headers = auth(token_factory, "bob", **{"X-Household-Id": str(world.household_a)})
    response = await client.get(f"/_test/households/{world.household_a}/context", headers=headers)
    assert response.status_code == 200
    assert response.json()["role"] == "member"


async def test_household_id_in_body_is_ignored(
    routes: FastAPI, client: httpx.AsyncClient, token_factory: TokenFactory, world: World
) -> None:
    headers = auth(token_factory, "alice", **{"X-Household-Id": str(world.household_a)})
    body = {"household_id": str(world.household_b)}
    response = await client.post("/_test/active-household", headers=headers, json=body)
    assert response.status_code == 200
    assert response.json()["db"] == str(world.household_a)


# --- 5.4 Requirement: Verificação de membership ------------------------------------------


async def test_non_member_gets_404(
    routes: FastAPI,
    client: httpx.AsyncClient,
    token_factory: TokenFactory,
    world: World,
    calls: list[str],
) -> None:
    response = await client.get(
        f"/_test/households/{world.household_b}/context", headers=auth(token_factory, "alice")
    )
    assert response.status_code == 404
    assert calls == []


async def test_nonexistent_household_gets_same_404_body(
    routes: FastAPI, client: httpx.AsyncClient, token_factory: TokenFactory, world: World
) -> None:
    headers = auth(token_factory, "alice")
    not_member = await client.get(f"/_test/households/{world.household_b}/context", headers=headers)
    missing = await client.get(f"/_test/households/{uuid7()}/context", headers=headers)

    def body(response: httpx.Response) -> dict[str, object]:
        # instance (o caminho pedido) e trace_id mudam a cada requisição, não com o lar.
        return {k: v for k, v in response.json().items() if k not in {"instance", "trace_id"}}

    assert (missing.status_code, body(missing)) == (not_member.status_code, body(not_member))
    assert body(missing) == {
        "type": "about:blank",
        "title": "Not Found",
        "status": 404,
        "detail": "household not found",
    }


async def test_member_role_is_enforced(
    routes: FastAPI, client: httpx.AsyncClient, token_factory: TokenFactory, world: World
) -> None:
    url = f"/_test/households/{world.household_a}/admin-only"
    assert (await client.get(url, headers=auth(token_factory, "alice"))).status_code == 200
    assert (await client.get(url, headers=auth(token_factory, "bob"))).status_code == 403


async def test_membership_is_served_from_cache_after_first_request(
    routes: FastAPI, client: httpx.AsyncClient, token_factory: TokenFactory, world: World
) -> None:
    url = f"/_test/households/{world.household_a}/context"
    cache = cache_of(routes)

    for _ in range(3):
        assert (await client.get(url, headers=auth(token_factory, "bob"))).status_code == 200

    assert (cache.misses, cache.hits) == (1, 2)


# --- 5.4 Requirement: Revogação imediata de acesso ---------------------------------------


async def remove_membership(session: AsyncSession, household: uuid.UUID, user: uuid.UUID) -> None:
    await set_tenant_context(session, user_id=None, household_id=household)
    await session.execute(
        text("delete from identity.memberships where household_id = :h and user_id = :u"),
        {"h": household, "u": user},
    )


async def change_role(
    session: AsyncSession, household: uuid.UUID, user: uuid.UUID, role: Role
) -> None:
    await set_tenant_context(session, user_id=None, household_id=household)
    await session.execute(
        text("update identity.memberships set role = :r where household_id = :h and user_id = :u"),
        {"r": role.value, "h": household, "u": user},
    )


async def test_removed_member_gets_404_on_next_request(
    routes: FastAPI,
    client: httpx.AsyncClient,
    token_factory: TokenFactory,
    world: World,
    db_session: AsyncSession,
) -> None:
    url = f"/_test/households/{world.household_a}/context"
    assert (
        await client.get(url, headers=auth(token_factory, "bob"))
    ).status_code == 200  # em cache

    # O que o módulo faz ao remover alguém (tarefa 5.6): muda o banco e agenda a invalidação.
    await remove_membership(db_session, world.household_a, world.bob)
    cache_of(routes).invalidate_after_commit(db_session, world.bob, world.household_a)
    await run_after_commit(db_session)

    assert (await client.get(url, headers=auth(token_factory, "bob"))).status_code == 404


async def test_demoted_admin_gets_403_on_next_request(
    routes: FastAPI,
    client: httpx.AsyncClient,
    token_factory: TokenFactory,
    world: World,
    db_session: AsyncSession,
) -> None:
    url = f"/_test/households/{world.household_a}/admin-only"
    assert (await client.get(url, headers=auth(token_factory, "alice"))).status_code == 200

    await change_role(db_session, world.household_a, world.alice, Role.MEMBER)
    cache_of(routes).invalidate_after_commit(db_session, world.alice, world.household_a)
    await run_after_commit(db_session)

    assert (await client.get(url, headers=auth(token_factory, "alice"))).status_code == 403


async def test_without_invalidation_the_cache_would_keep_stale_access(
    routes: FastAPI,
    client: httpx.AsyncClient,
    token_factory: TokenFactory,
    world: World,
    db_session: AsyncSession,
) -> None:
    """Mostra por que a invalidação explícita é obrigatória (o TTL é só rede de segurança)."""
    url = f"/_test/households/{world.household_a}/context"
    assert (await client.get(url, headers=auth(token_factory, "bob"))).status_code == 200

    await remove_membership(db_session, world.household_a, world.bob)

    assert (await client.get(url, headers=auth(token_factory, "bob"))).status_code == 200


async def test_invalidation_is_discarded_when_the_request_fails(
    routes: FastAPI, client: httpx.AsyncClient, token_factory: TokenFactory, world: World
) -> None:
    cache = cache_of(routes)

    @routes.post("/_test/households/{household_id}/fail-after-change")
    async def fail(tenant: PathTenant, session: DbSession) -> None:
        cache.invalidate_after_commit(session, tenant.user.id, tenant.household_id)
        raise RuntimeError("boom")

    url = f"/_test/households/{world.household_a}"
    assert (
        await client.get(f"{url}/context", headers=auth(token_factory, "bob"))
    ).status_code == 200
    key = MembershipCache.key(world.bob, world.household_a)
    assert await cache._redis.get(key) == "member"

    failed = await client.post(f"{url}/fail-after-change", headers=auth(token_factory, "bob"))
    assert failed.status_code == 500

    assert await cache._redis.get(key) == "member"
