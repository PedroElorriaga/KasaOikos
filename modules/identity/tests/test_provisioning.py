"""Spec identity/authentication, requirement "Provisionamento do usuário no primeiro acesso"."""

from typing import Any

import httpx
from fastapi import FastAPI
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from hm_identity.infra.users import provision_user
from hm_identity.public import CurrentUserDep
from hm_platform.auth import TokenClaims
from hm_platform.testing.tokens import TokenFactory


def claims(
    sub: str = "kc-user-1", email: str | None = "ana@example.com", name: str | None = "Ana"
) -> TokenClaims:
    return TokenClaims(subject=sub, email=email, name=name, raw={})


async def stored(session: AsyncSession, sub: str) -> dict[str, Any] | None:
    # ctid muda a cada UPDATE (o Postgres grava uma nova versão da linha): é a prova de escrita.
    row = await session.execute(
        text("select id, email, name, ctid::text as ctid from identity.users where subject = :s"),
        {"s": sub},
    )
    found = row.mappings().one_or_none()
    return dict(found) if found else None


async def test_first_access_creates_local_user(db_session: AsyncSession) -> None:
    assert await stored(db_session, "kc-user-1") is None

    user = await provision_user(db_session, claims())

    row = await stored(db_session, "kc-user-1")
    assert row is not None
    assert (row["id"], row["email"], row["name"]) == (user.id, "ana@example.com", "Ana")
    assert user.subject == "kc-user-1"
    assert user.id.version == 7


async def test_unchanged_data_does_not_write(db_session: AsyncSession) -> None:
    first = await provision_user(db_session, claims())
    before = await stored(db_session, "kc-user-1")

    again = await provision_user(db_session, claims())

    assert again == first
    assert await stored(db_session, "kc-user-1") == before  # mesmo ctid: nenhuma escrita


async def test_changed_name_in_provider_updates_local_record(db_session: AsyncSession) -> None:
    first = await provision_user(db_session, claims(name="Ana"))
    before = await stored(db_session, "kc-user-1")
    assert before is not None

    again = await provision_user(db_session, claims(name="Ana Souza"))

    after = await stored(db_session, "kc-user-1")
    assert after is not None
    assert again.id == first.id
    assert after["name"] == "Ana Souza"
    assert after["ctid"] != before["ctid"]


async def test_changed_email_in_provider_updates_local_record(db_session: AsyncSession) -> None:
    await provision_user(db_session, claims(email="ana@example.com"))
    await provision_user(db_session, claims(email="ana@novo.example.com"))

    row = await stored(db_session, "kc-user-1")
    assert row is not None
    assert row["email"] == "ana@novo.example.com"


async def test_users_are_distinguished_by_subject(db_session: AsyncSession) -> None:
    a = await provision_user(db_session, claims(sub="kc-a", email="a@example.com"))
    b = await provision_user(db_session, claims(sub="kc-b", email="b@example.com"))
    assert a.id != b.id


# --- Pela API: a requisição é processada normalmente -------------------------------------


def add_whoami_route(app: FastAPI) -> None:
    @app.get("/_test/whoami")
    async def whoami(user: CurrentUserDep) -> dict[str, str]:
        return {"id": str(user.id), "subject": user.subject}


async def test_first_request_provisions_and_is_processed(
    app: FastAPI, client: httpx.AsyncClient, token_factory: TokenFactory, db_session: AsyncSession
) -> None:
    add_whoami_route(app)
    token = token_factory.valid(sub="kc-http-1", name="Bruno")

    response = await client.get("/_test/whoami", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 200
    row = await stored(db_session, "kc-http-1")
    assert row is not None
    assert response.json() == {"id": str(row["id"]), "subject": "kc-http-1"}
    assert row["name"] == "Bruno"


async def test_new_token_with_new_name_updates_record(
    app: FastAPI, client: httpx.AsyncClient, token_factory: TokenFactory, db_session: AsyncSession
) -> None:
    add_whoami_route(app)
    for name in ("Bruno", "Bruno Lima"):
        token = token_factory.valid(sub="kc-http-2", name=name)
        response = await client.get("/_test/whoami", headers={"Authorization": f"Bearer {token}"})
        assert response.status_code == 200

    row = await stored(db_session, "kc-http-2")
    assert row is not None
    assert row["name"] == "Bruno Lima"


async def test_unauthenticated_request_does_not_provision(
    app: FastAPI, client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    add_whoami_route(app)
    response = await client.get("/_test/whoami")
    assert response.status_code == 401
    assert await db_session.scalar(text("select count(*) from identity.users")) == 0
