"""Persistência de convites e chamada da função de aceite."""

import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from hm_identity.infra.models import Invite
from hm_platform.ids import uuid7
from hm_platform.roles import Role


class RedeemOutcome(StrEnum):
    ACCEPTED = "accepted"
    GONE = "gone"  # expirado, já usado ou revogado
    NOT_FOUND = "not_found"
    ALREADY_MEMBER = "already_member"


async def create_invite(
    session: AsyncSession,
    household_id: uuid.UUID,
    created_by: uuid.UUID,
    role: Role,
    code_hash: str,
    expires_at: datetime,
) -> Invite:
    invite = Invite(
        id=uuid7(),
        household_id=household_id,
        code_hash=code_hash,
        role=role.value,
        status="pending",
        expires_at=expires_at,
        created_by=created_by,
    )
    session.add(invite)
    await session.flush()
    await session.refresh(invite)
    return invite


async def list_invites(session: AsyncSession, household_id: uuid.UUID) -> list[Invite]:
    rows = await session.scalars(
        select(Invite)
        .where(Invite.household_id == household_id)
        .order_by(Invite.created_at.desc(), Invite.id.desc())
    )
    return list(rows.all())


async def get_invite_for_update(
    session: AsyncSession, household_id: uuid.UUID, invite_id: uuid.UUID
) -> Invite | None:
    # FOR UPDATE: uma revogação e um aceite simultâneos não se atropelam.
    invite: Invite | None = await session.scalar(
        select(Invite)
        .where(Invite.household_id == household_id, Invite.id == invite_id)
        .with_for_update()
    )
    return invite


async def revoke(session: AsyncSession, invite: Invite) -> None:
    invite.status = "revoked"
    await session.flush()


async def redeem(
    session: AsyncSession, code_hash: str, user_id: uuid.UUID
) -> tuple[RedeemOutcome, uuid.UUID | None, Role | None]:
    """Chama ``identity.redeem_invite`` (SECURITY DEFINER; ver a migração 621cb5c57396)."""
    row = (
        await session.execute(
            text("select outcome, household_id, role from identity.redeem_invite(:hash, :user)"),
            {"hash": code_hash, "user": user_id},
        )
    ).one()
    role = Role(row.role) if row.role else None
    return RedeemOutcome(row.outcome), row.household_id, role
