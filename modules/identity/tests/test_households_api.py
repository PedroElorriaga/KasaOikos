"""Specs identity/households (criação, consulta, renomeação) e identity/authentication (GET /me)."""

import uuid

import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from hm_platform.rls import set_tenant_context
from hm_platform.testing.tokens import TokenFactory

from .conftest import World, add_member, auth


async def household_name(session: AsyncSession, world: World, household: uuid.UUID) -> str | None:
    """Nome gravado no banco, lido por fora da API (no contexto do próprio lar)."""
    await set_tenant_context(session, user_id=None, household_id=household)
    name: str | None = await session.scalar(
        text("select name from identity.households where id = :id"), {"id": household}
    )
    await set_tenant_context(session, user_id=None, household_id=None)
    return name


# --- Requirement: Criação de lar ---------------------------------------------------------


async def test_create_household_makes_creator_admin(
    client: httpx.AsyncClient, token_factory: TokenFactory, world: World
) -> None:
    headers = auth(token_factory, "dave")
    response = await client.post("/households", headers=headers, json={"name": "Casa da Praia"})

    assert response.status_code == 201
    created = response.json()
    assert (created["name"], created["role"]) == ("Casa da Praia", "admin")

    me = (await client.get("/me", headers=headers)).json()
    assert me["households"] == [{"id": created["id"], "name": "Casa da Praia", "role": "admin"}]
    fetched = await client.get(f"/households/{created['id']}", headers=headers)
    assert fetched.status_code == 200


@pytest.mark.parametrize("name", ["", "   ", "x" * 81])
async def test_invalid_name_returns_422_and_creates_nothing(
    client: httpx.AsyncClient, token_factory: TokenFactory, world: World, name: str
) -> None:
    headers = auth(token_factory, "dave")
    response = await client.post("/households", headers=headers, json={"name": name})

    assert response.status_code == 422
    assert (await client.get("/me", headers=headers)).json()["households"] == []


async def test_name_with_80_characters_is_accepted(
    client: httpx.AsyncClient, token_factory: TokenFactory, world: World
) -> None:
    response = await client.post(
        "/households", headers=auth(token_factory, "dave"), json={"name": "x" * 80}
    )
    assert response.status_code == 201


# --- Requirement: Consulta e renomeação de lar -------------------------------------------


async def test_member_reads_household(
    client: httpx.AsyncClient, token_factory: TokenFactory, world: World
) -> None:
    response = await client.get(
        f"/households/{world.household_a}", headers=auth(token_factory, "bob")
    )
    assert response.status_code == 200
    assert response.json()["id"] == str(world.household_a)
    assert (response.json()["name"], response.json()["role"]) == ("Lar A", "member")


async def test_admin_renames_household(
    client: httpx.AsyncClient, token_factory: TokenFactory, world: World, db_session: AsyncSession
) -> None:
    response = await client.patch(
        f"/households/{world.household_a}",
        headers=auth(token_factory, "alice"),
        json={"name": "Lar A renovado"},
    )
    assert response.status_code == 200
    assert response.json()["name"] == "Lar A renovado"
    assert await household_name(db_session, world, world.household_a) == "Lar A renovado"


async def test_member_cannot_rename(
    client: httpx.AsyncClient, token_factory: TokenFactory, world: World, db_session: AsyncSession
) -> None:
    response = await client.patch(
        f"/households/{world.household_a}", headers=auth(token_factory, "bob"), json={"name": "Meu"}
    )
    assert response.status_code == 403
    assert await household_name(db_session, world, world.household_a) == "Lar A"


@pytest.mark.parametrize("method", ["GET", "PATCH"])
async def test_non_member_gets_404_without_learning_if_household_exists(
    client: httpx.AsyncClient,
    token_factory: TokenFactory,
    world: World,
    db_session: AsyncSession,
    method: str,
) -> None:
    response = await client.request(
        method,
        f"/households/{world.household_b}",
        headers=auth(token_factory, "alice"),
        json={"name": "hack"},
    )
    assert response.status_code == 404
    assert await household_name(db_session, world, world.household_b) == "Lar B"


# --- GET /me (spec identity/authentication) ----------------------------------------------


async def test_me_lists_each_household_with_its_role(
    client: httpx.AsyncClient, token_factory: TokenFactory, world: World, db_session: AsyncSession
) -> None:
    # alice: admin em A (do World) e member em B.
    await add_member(db_session, world.household_b, world.alice, "member")

    response = await client.get("/me", headers=auth(token_factory, "alice"))

    assert response.status_code == 200
    me = response.json()
    assert (me["id"], me["email"], me["name"]) == (str(world.alice), "alice@example.com", "Alice")
    assert {(h["id"], h["role"]) for h in me["households"]} == {
        (str(world.household_a), "admin"),
        (str(world.household_b), "member"),
    }


async def test_me_shows_only_own_households(
    client: httpx.AsyncClient, token_factory: TokenFactory, world: World
) -> None:
    me = (await client.get("/me", headers=auth(token_factory, "bob"))).json()
    assert [h["id"] for h in me["households"]] == [str(world.household_a)]


async def test_me_requires_no_active_household_and_works_for_new_users(
    client: httpx.AsyncClient, token_factory: TokenFactory, world: World
) -> None:
    token = token_factory.valid(sub="kc-new", email="new@example.com", name="Nova")
    response = await client.get("/me", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200
    assert (response.json()["name"], response.json()["households"]) == ("Nova", [])


async def test_me_requires_authentication(client: httpx.AsyncClient) -> None:
    response = await client.get("/me")
    assert response.status_code == 401
