"""Consulta de membership: implementação da porta ``MembershipResolver`` da plataforma."""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from hm_identity.infra.models import Membership, User
from hm_platform.tenancy import Role


async def get_membership_role(
    session: AsyncSession, user_id: uuid.UUID, household_id: uuid.UUID
) -> Role | None:
    role = await session.scalar(
        select(Membership.role).where(
            Membership.user_id == user_id, Membership.household_id == household_id
        )
    )
    return Role(role) if role is not None else None


async def list_members(
    session: AsyncSession, household_id: uuid.UUID
) -> list[tuple[Membership, User]]:
    rows = await session.execute(
        select(Membership, User)
        .join(User, User.id == Membership.user_id)
        .where(Membership.household_id == household_id)
        .order_by(Membership.joined_at, User.id)
    )
    return [(membership, user) for membership, user in rows]


async def get_member(
    session: AsyncSession, household_id: uuid.UUID, user_id: uuid.UUID
) -> tuple[Membership, User] | None:
    row = (
        await session.execute(
            select(Membership, User)
            .join(User, User.id == Membership.user_id)
            .where(Membership.household_id == household_id, Membership.user_id == user_id)
        )
    ).one_or_none()
    return (row[0], row[1]) if row else None


async def lock_admins(session: AsyncSession, household_id: uuid.UUID) -> set[uuid.UUID]:
    """Admins atuais do lar, com as linhas travadas até o fim da transação.

    Duas operações simultâneas (ex.: dois admins rebaixando um ao outro) ficam em
    fila aqui; a segunda relê os admins depois da primeira e vê o estado novo.
    """
    rows = await session.scalars(
        select(Membership.user_id)
        .where(Membership.household_id == household_id, Membership.role == Role.ADMIN.value)
        .with_for_update()
    )
    return set(rows.all())


async def set_role(session: AsyncSession, membership: Membership, role: Role) -> None:
    membership.role = role.value
    await session.flush()


async def remove(session: AsyncSession, membership: Membership) -> None:
    await session.delete(membership)
    await session.flush()
