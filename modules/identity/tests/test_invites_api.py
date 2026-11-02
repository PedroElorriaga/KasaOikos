"""Spec identity/households, requirement "Convites" (tarefa 5.7)."""

import hashlib
import uuid
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from hm_platform.rls import set_tenant_context
from hm_platform.testing.tokens import TokenFactory

from .conftest import World, auth


async def create_invite(
    client: httpx.AsyncClient,
    token_factory: TokenFactory,
    household: uuid.UUID,
    role: str = "member",
) -> dict[str, str]:
    response = await client.post(
        f"/households/{household}/invites",
        headers=auth(token_factory, "alice"),
        json={"role": role},
    )
    assert response.status_code == 201, response.text
    created: dict[str, str] = response.json()
    return created


async def accept(
    client: httpx.AsyncClient, token_factory: TokenFactory, who: str, code: str
) -> httpx.Response:
    return await client.post(
        "/invites/accept", headers=auth(token_factory, who), json={"code": code}
    )


async def stored_invite(
    session: AsyncSession, household: uuid.UUID, invite_id: str
) -> dict[str, object]:
    await set_tenant_context(session, user_id=None, household_id=household)
    row = (
        await session.execute(
            text("select code_hash, status, accepted_by from identity.invites where id = :id"),
            {"id": invite_id},
        )
    ).one()
    await set_tenant_context(session, user_id=None, household_id=None)
    return dict(row._mapping)


async def role_in(session: AsyncSession, household: uuid.UUID, user: uuid.UUID) -> str | None:
    await set_tenant_context(session, user_id=None, household_id=household)
    role: str | None = await session.scalar(
        text("select role from identity.memberships where household_id = :h and user_id = :u"),
        {"h": household, "u": user},
    )
    await set_tenant_context(session, user_id=None, household_id=None)
    return role


# --- Criar convite -----------------------------------------------------------------------


async def test_admin_creates_invite_with_code_and_expiration(
    client: httpx.AsyncClient, token_factory: TokenFactory, world: World, db_session: AsyncSession
) -> None:
    created = await create_invite(client, token_factory, world.household_a)

    assert created["role"] == "member"
    expires_at = datetime.fromisoformat(created["expires_at"])
    assert abs(expires_at - (datetime.now(UTC) + timedelta(days=7))) < timedelta(minutes=1)
    # O banco guarda só o SHA-256 do código.
    stored = await stored_invite(db_session, world.household_a, created["id"])
    assert stored["code_hash"] == hashlib.sha256(created["code"].encode()).hexdigest()
    assert stored["status"] == "pending"


async def test_member_cannot_create_invite(
    client: httpx.AsyncClient, token_factory: TokenFactory, world: World
) -> None:
    response = await client.post(
        f"/households/{world.household_a}/invites", headers=auth(token_factory, "bob"), json={}
    )
    assert response.status_code == 403


async def test_code_is_shown_only_on_creation(
    client: httpx.AsyncClient, token_factory: TokenFactory, world: World
) -> None:
    created = await create_invite(client, token_factory, world.household_a)
    listed = await client.get(
        f"/households/{world.household_a}/invites", headers=auth(token_factory, "alice")
    )
    assert listed.status_code == 200
    assert [i["id"] for i in listed.json()] == [created["id"]]
    assert "code" not in listed.json()[0]
    assert created["code"] not in listed.text


# --- Aceitar convite ---------------------------------------------------------------------


@pytest.mark.parametrize("role", ["member", "admin"])
async def test_accepting_valid_invite_grants_its_role(
    client: httpx.AsyncClient,
    token_factory: TokenFactory,
    world: World,
    db_session: AsyncSession,
    role: str,
) -> None:
    created = await create_invite(client, token_factory, world.household_a, role)

    response = await accept(client, token_factory, "dave", created["code"])

    assert response.status_code == 200
    assert response.json() == {"household_id": str(world.household_a), "role": role}
    assert await role_in(db_session, world.household_a, world.dave) == role
    stored = await stored_invite(db_session, world.household_a, created["id"])
    assert (stored["status"], stored["accepted_by"]) == ("accepted", world.dave)
    # O novo membro já enxerga o lar na requisição seguinte.
    household = await client.get(
        f"/households/{world.household_a}", headers=auth(token_factory, "dave")
    )
    assert household.status_code == 200


async def test_used_invite_returns_410(
    client: httpx.AsyncClient, token_factory: TokenFactory, world: World, db_session: AsyncSession
) -> None:
    created = await create_invite(client, token_factory, world.household_a)
    assert (await accept(client, token_factory, "dave", created["code"])).status_code == 200

    response = await accept(client, token_factory, "carol", created["code"])

    assert response.status_code == 410
    assert await role_in(db_session, world.household_a, world.carol) is None


async def test_expired_invite_returns_410(
    client: httpx.AsyncClient, token_factory: TokenFactory, world: World, db_session: AsyncSession
) -> None:
    created = await create_invite(client, token_factory, world.household_a)
    await set_tenant_context(db_session, user_id=None, household_id=world.household_a)
    await db_session.execute(
        text("update identity.invites set expires_at = now() - interval '1 second' where id = :id"),
        {"id": created["id"]},
    )

    response = await accept(client, token_factory, "dave", created["code"])

    assert response.status_code == 410
    assert await role_in(db_session, world.household_a, world.dave) is None
    listed = await client.get(
        f"/households/{world.household_a}/invites", headers=auth(token_factory, "alice")
    )
    assert listed.json()[0]["status"] == "expired"


async def test_revoked_invite_cannot_be_accepted(
    client: httpx.AsyncClient, token_factory: TokenFactory, world: World, db_session: AsyncSession
) -> None:
    created = await create_invite(client, token_factory, world.household_a)

    revoked = await client.delete(
        f"/households/{world.household_a}/invites/{created['id']}",
        headers=auth(token_factory, "alice"),
    )

    assert revoked.status_code == 204
    assert (await accept(client, token_factory, "dave", created["code"])).status_code == 410
    assert await role_in(db_session, world.household_a, world.dave) is None


async def test_unknown_code_returns_404(
    client: httpx.AsyncClient, token_factory: TokenFactory, world: World
) -> None:
    assert (await accept(client, token_factory, "dave", "no-such-code")).status_code == 404


async def test_member_accepting_own_household_invite_gets_409_and_invite_stays_valid(
    client: httpx.AsyncClient, token_factory: TokenFactory, world: World, db_session: AsyncSession
) -> None:
    created = await create_invite(client, token_factory, world.household_a, "admin")

    response = await accept(client, token_factory, "bob", created["code"])

    assert response.status_code == 409
    assert await role_in(db_session, world.household_a, world.bob) == "member"  # papel não mudou
    assert (await accept(client, token_factory, "dave", created["code"])).status_code == 200


# --- Revogar -----------------------------------------------------------------------------


async def test_revoking_twice_or_after_acceptance_returns_409(
    client: httpx.AsyncClient, token_factory: TokenFactory, world: World
) -> None:
    created = await create_invite(client, token_factory, world.household_a)
    await accept(client, token_factory, "dave", created["code"])

    response = await client.delete(
        f"/households/{world.household_a}/invites/{created['id']}",
        headers=auth(token_factory, "alice"),
    )
    assert response.status_code == 409


async def test_member_cannot_list_or_revoke(
    client: httpx.AsyncClient, token_factory: TokenFactory, world: World
) -> None:
    created = await create_invite(client, token_factory, world.household_a)
    base = f"/households/{world.household_a}/invites"
    bob = auth(token_factory, "bob")
    assert (await client.get(base, headers=bob)).status_code == 403
    assert (await client.delete(f"{base}/{created['id']}", headers=bob)).status_code == 403


# --- Isolamento entre lares --------------------------------------------------------------


async def test_admin_cannot_list_or_revoke_other_household_invites(
    client: httpx.AsyncClient, token_factory: TokenFactory, world: World, db_session: AsyncSession
) -> None:
    carol = auth(token_factory, "carol")
    created = (
        await client.post(f"/households/{world.household_b}/invites", headers=carol, json={})
    ).json()
    alice = auth(token_factory, "alice")

    assert (
        await client.get(f"/households/{world.household_b}/invites", headers=alice)
    ).status_code == 404
    revoke_b = f"/households/{world.household_b}/invites/{created['id']}"
    assert (await client.delete(revoke_b, headers=alice)).status_code == 404
    # Nem pelo caminho do próprio lar com o id do convite de B.
    revoke_via_a = f"/households/{world.household_a}/invites/{created['id']}"
    assert (await client.delete(revoke_via_a, headers=alice)).status_code == 404
    assert (await stored_invite(db_session, world.household_b, created["id"]))[
        "status"
    ] == "pending"


# --- Auditoria da função SECURITY DEFINER ------------------------------------------------


async def test_redeem_function_is_locked_down(db_session: AsyncSession) -> None:
    row = (
        await db_session.execute(
            text(
                "select p.prosecdef, p.proconfig, pg_get_userbyid(p.proowner) as owner, "
                "has_function_privilege('hm_app', p.oid, 'execute') as app, "
                "has_function_privilege('public', p.oid, 'execute') as public "
                "from pg_proc p join pg_namespace n on n.oid = p.pronamespace "
                "where n.nspname = 'identity' and p.proname = 'redeem_invite'"
            )
        )
    ).one()
    assert row.prosecdef is True
    assert row.proconfig == ["search_path=pg_catalog, pg_temp"]
    assert (row.owner, row.app, row.public) == ("hm_migrator", True, False)


async def test_redeem_function_refuses_another_users_id(
    db_session: AsyncSession, world: World
) -> None:
    await set_tenant_context(db_session, user_id=world.dave, household_id=None)
    with pytest.raises(DBAPIError, match="does not match the authenticated user"):
        async with db_session.begin_nested():
            await db_session.execute(
                text("select * from identity.redeem_invite('x', :other)"), {"other": world.carol}
            )
