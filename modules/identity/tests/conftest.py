"""Fixtures do módulo identity: um "mundo" com dois lares e quatro usuários."""

import uuid
from dataclasses import dataclass

import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from hm_platform.ids import uuid7
from hm_platform.rls import set_tenant_context
from hm_platform.testing.tokens import TokenFactory


def auth(token_factory: TokenFactory, name: str, **headers: str) -> dict[str, str]:
    """Headers de um usuário do World (mesmo sub/e-mail/nome: o provisionamento não escreve)."""
    token = token_factory.valid(sub=f"kc-{name}", email=f"{name}@example.com", name=name.title())
    return {"Authorization": f"Bearer {token}", **headers}


@dataclass(frozen=True)
class World:
    """Lar A: alice (admin) e bob (member). Lar B: carol (admin). dave: sem lar."""

    household_a: uuid.UUID
    household_b: uuid.UUID
    alice: uuid.UUID
    bob: uuid.UUID
    carol: uuid.UUID
    dave: uuid.UUID


async def insert_user(session: AsyncSession, name: str) -> uuid.UUID:
    user_id = uuid7()
    await session.execute(
        text(
            "insert into identity.users (id, subject, email, name) "
            "values (:id, :sub, :email, :name)"
        ),
        {"id": user_id, "sub": f"kc-{name}", "email": f"{name}@example.com", "name": name.title()},
    )
    return user_id


async def insert_household(
    session: AsyncSession, name: str, members: list[tuple[uuid.UUID, str]]
) -> uuid.UUID:
    """Cria o lar como a aplicação faz: o id novo vira o lar ativo antes do INSERT."""
    household_id = uuid7()
    await set_tenant_context(session, user_id=None, household_id=household_id)
    await session.execute(
        text("insert into identity.households (id, name) values (:id, :name)"),
        {"id": household_id, "name": name},
    )
    for user_id, role in members:
        await session.execute(
            text(
                "insert into identity.memberships (household_id, user_id, role) values (:h, :u, :r)"
            ),
            {"h": household_id, "u": user_id, "r": role},
        )
    await set_tenant_context(session, user_id=None, household_id=None)
    return household_id


async def add_member(
    session: AsyncSession, household_id: uuid.UUID, user_id: uuid.UUID, role: str
) -> None:
    """Insere uma membership como a aplicação faria (lar ativo = o lar da membership)."""
    await set_tenant_context(session, user_id=None, household_id=household_id)
    await session.execute(
        text("insert into identity.memberships (household_id, user_id, role) values (:h, :u, :r)"),
        {"h": household_id, "u": user_id, "r": role},
    )
    await set_tenant_context(session, user_id=None, household_id=None)


@pytest_asyncio.fixture
async def world(db_session: AsyncSession) -> World:
    alice, bob, carol, dave = [
        await insert_user(db_session, n) for n in ("alice", "bob", "carol", "dave")
    ]
    household_a = await insert_household(db_session, "Lar A", [(alice, "admin"), (bob, "member")])
    household_b = await insert_household(db_session, "Lar B", [(carol, "admin")])
    return World(household_a, household_b, alice, bob, carol, dave)
