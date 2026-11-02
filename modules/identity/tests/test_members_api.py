"""Spec identity/households: listagem de membros, alteração de papel, remoção e saída."""

import uuid

import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from hm_identity.domain.memberships import LastAdminError, ensure_an_admin_remains
from hm_platform.rls import set_tenant_context
from hm_platform.roles import Role
from hm_platform.testing.tokens import TokenFactory

from .conftest import World, add_member, auth


async def role_in(session: AsyncSession, household: uuid.UUID, user: uuid.UUID) -> str | None:
    await set_tenant_context(session, user_id=None, household_id=household)
    role: str | None = await session.scalar(
        text("select role from identity.memberships where household_id = :h and user_id = :u"),
        {"h": household, "u": user},
    )
    await set_tenant_context(session, user_id=None, household_id=None)
    return role


# --- Regra de domínio --------------------------------------------------------------------

A, B = uuid.uuid4(), uuid.uuid4()


@pytest.mark.parametrize(
    ("admins", "target", "new_role", "allowed"),
    [
        ({A}, A, Role.MEMBER, False),  # único admin se rebaixa
        ({A}, A, None, False),  # único admin sai
        ({A, B}, A, Role.MEMBER, True),
        ({A, B}, A, None, True),
        ({A}, B, Role.ADMIN, True),  # promover alguém
        ({A}, B, None, True),  # remover um member
    ],
)
def test_an_admin_must_remain(
    admins: set[uuid.UUID], target: uuid.UUID, new_role: Role | None, allowed: bool
) -> None:
    if allowed:
        ensure_an_admin_remains(admins, target, new_role)
    else:
        with pytest.raises(LastAdminError):
            ensure_an_admin_remains(admins, target, new_role)


# --- Requirement: Listagem de membros ----------------------------------------------------


async def test_member_lists_all_members_with_roles(
    client: httpx.AsyncClient, token_factory: TokenFactory, world: World
) -> None:
    response = await client.get(
        f"/households/{world.household_a}/members", headers=auth(token_factory, "bob")
    )
    assert response.status_code == 200
    members = {m["user_id"]: m for m in response.json()}
    assert set(members) == {str(world.alice), str(world.bob)}
    alice = members[str(world.alice)]
    assert (alice["name"], alice["email"], alice["role"]) == ("Alice", "alice@example.com", "admin")
    assert members[str(world.bob)]["role"] == "member"
    assert alice["joined_at"]


async def test_non_member_cannot_list_members(
    client: httpx.AsyncClient, token_factory: TokenFactory, world: World
) -> None:
    response = await client.get(
        f"/households/{world.household_b}/members", headers=auth(token_factory, "alice")
    )
    assert response.status_code == 404


# --- Requirement: Alteração de papel de membro -------------------------------------------


async def test_admin_promotes_member_with_immediate_effect(
    client: httpx.AsyncClient, token_factory: TokenFactory, world: World, db_session: AsyncSession
) -> None:
    rename = f"/households/{world.household_a}"
    # bob tenta antes como member (o papel fica em cache)...
    assert (
        await client.patch(rename, headers=auth(token_factory, "bob"), json={"name": "x"})
    ).status_code == 403

    response = await client.patch(
        f"/households/{world.household_a}/members/{world.bob}",
        headers=auth(token_factory, "alice"),
        json={"role": "admin"},
    )

    assert response.status_code == 200
    assert response.json()["role"] == "admin"
    assert await role_in(db_session, world.household_a, world.bob) == "admin"
    # ...e a promoção vale já na requisição seguinte (cache invalidado após o commit).
    assert (
        await client.patch(rename, headers=auth(token_factory, "bob"), json={"name": "x"})
    ).status_code == 200


async def test_only_admin_cannot_demote_self(
    client: httpx.AsyncClient, token_factory: TokenFactory, world: World, db_session: AsyncSession
) -> None:
    response = await client.patch(
        f"/households/{world.household_a}/members/{world.alice}",
        headers=auth(token_factory, "alice"),
        json={"role": "member"},
    )
    assert response.status_code == 409
    assert await role_in(db_session, world.household_a, world.alice) == "admin"


async def test_admin_can_step_down_when_another_admin_exists(
    client: httpx.AsyncClient, token_factory: TokenFactory, world: World, db_session: AsyncSession
) -> None:
    await add_member(db_session, world.household_a, world.dave, "admin")
    response = await client.patch(
        f"/households/{world.household_a}/members/{world.alice}",
        headers=auth(token_factory, "alice"),
        json={"role": "member"},
    )
    assert response.status_code == 200
    assert await role_in(db_session, world.household_a, world.alice) == "member"


async def test_member_cannot_change_roles(
    client: httpx.AsyncClient, token_factory: TokenFactory, world: World, db_session: AsyncSession
) -> None:
    response = await client.patch(
        f"/households/{world.household_a}/members/{world.alice}",
        headers=auth(token_factory, "bob"),
        json={"role": "member"},
    )
    assert response.status_code == 403
    assert await role_in(db_session, world.household_a, world.alice) == "admin"


async def test_role_is_per_household(
    client: httpx.AsyncClient, token_factory: TokenFactory, world: World, db_session: AsyncSession
) -> None:
    await add_member(db_session, world.household_b, world.bob, "member")

    response = await client.patch(
        f"/households/{world.household_a}/members/{world.bob}",
        headers=auth(token_factory, "alice"),
        json={"role": "admin"},
    )

    assert response.status_code == 200
    me = (await client.get("/me", headers=auth(token_factory, "bob"))).json()
    assert {h["id"]: h["role"] for h in me["households"]} == {
        str(world.household_a): "admin",
        str(world.household_b): "member",
    }


async def test_invalid_role_returns_422(
    client: httpx.AsyncClient, token_factory: TokenFactory, world: World
) -> None:
    response = await client.patch(
        f"/households/{world.household_a}/members/{world.bob}",
        headers=auth(token_factory, "alice"),
        json={"role": "owner"},
    )
    assert response.status_code == 422


@pytest.mark.parametrize("method", ["PATCH", "DELETE"])
async def test_target_that_is_not_a_member_returns_404(
    client: httpx.AsyncClient, token_factory: TokenFactory, world: World, method: str
) -> None:
    response = await client.request(
        method,
        f"/households/{world.household_a}/members/{world.dave}",
        headers=auth(token_factory, "alice"),
        json={"role": "admin"},
    )
    assert response.status_code == 404


# --- Requirement: Remoção e saída de membro ----------------------------------------------


async def test_admin_removes_member_and_access_is_revoked(
    client: httpx.AsyncClient, token_factory: TokenFactory, world: World, db_session: AsyncSession
) -> None:
    household = f"/households/{world.household_a}"
    assert (await client.get(household, headers=auth(token_factory, "bob"))).status_code == 200

    response = await client.delete(
        f"{household}/members/{world.bob}", headers=auth(token_factory, "alice")
    )

    assert response.status_code == 204
    assert await role_in(db_session, world.household_a, world.bob) is None
    # Cenário "Membro removido" (tenant-isolation): 404 já na requisição seguinte.
    assert (await client.get(household, headers=auth(token_factory, "bob"))).status_code == 404


async def test_member_leaves_household(
    client: httpx.AsyncClient, token_factory: TokenFactory, world: World, db_session: AsyncSession
) -> None:
    response = await client.delete(
        f"/households/{world.household_a}/members/{world.bob}", headers=auth(token_factory, "bob")
    )
    assert response.status_code == 204
    assert await role_in(db_session, world.household_a, world.bob) is None


async def test_last_admin_cannot_leave(
    client: httpx.AsyncClient, token_factory: TokenFactory, world: World, db_session: AsyncSession
) -> None:
    response = await client.delete(
        f"/households/{world.household_a}/members/{world.alice}",
        headers=auth(token_factory, "alice"),
    )
    assert response.status_code == 409
    assert await role_in(db_session, world.household_a, world.alice) == "admin"


async def test_member_cannot_remove_someone_else(
    client: httpx.AsyncClient, token_factory: TokenFactory, world: World, db_session: AsyncSession
) -> None:
    response = await client.delete(
        f"/households/{world.household_a}/members/{world.alice}", headers=auth(token_factory, "bob")
    )
    assert response.status_code == 403
    assert await role_in(db_session, world.household_a, world.alice) == "admin"
