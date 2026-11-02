"""Persistência de lares. As consultas filtram por lar (1ª camada); o RLS é a rede de segurança."""

import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from hm_identity.infra.models import Household, Membership, User
from hm_platform.ids import uuid7
from hm_platform.rls import set_tenant_context
from hm_platform.tenancy import Role


async def create_household(session: AsyncSession, user_id: uuid.UUID, name: str) -> Household:
    """Cria o lar com o criador como admin.

    O id novo vira o lar ativo da transação antes do INSERT: é o que a política de
    escrita de households e memberships exige (design D4).
    """
    household = Household(id=uuid7(), name=name)
    await set_tenant_context(session, user_id=user_id, household_id=household.id)
    session.add(household)
    await session.flush()  # o lar precisa existir antes da membership (FK)
    session.add(Membership(household_id=household.id, user_id=user_id, role=Role.ADMIN.value))
    await session.flush()
    await session.refresh(household)  # created_at vem do banco
    return household


async def get_household(session: AsyncSession, household_id: uuid.UUID) -> Household | None:
    household: Household | None = await session.scalar(
        select(Household).where(Household.id == household_id)
    )
    return household


async def rename_household(session: AsyncSession, household: Household, name: str) -> Household:
    household.name = name
    household.updated_at = func.now()
    await session.flush()
    await session.refresh(household)
    return household


async def get_user(session: AsyncSession, user_id: uuid.UUID) -> User | None:
    return await session.get(User, user_id)


async def list_user_households(
    session: AsyncSession, user_id: uuid.UUID
) -> list[tuple[Household, str]]:
    """Lares do usuário com o papel em cada um, na ordem em que entrou."""
    rows = await session.execute(
        select(Household, Membership.role)
        .join(Membership, Membership.household_id == Household.id)
        .where(Membership.user_id == user_id)
        .order_by(Membership.joined_at, Household.id)
    )
    return [(household, role) for household, role in rows]
