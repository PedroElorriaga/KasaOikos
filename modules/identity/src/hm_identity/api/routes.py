"""Rotas HTTP do módulo identity: /me e /households."""

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, status

from hm_identity.api.schemas import (
    HouseholdCreate,
    HouseholdOut,
    HouseholdUpdate,
    InviteAccept,
    InviteAccepted,
    InviteCreate,
    InviteCreated,
    InviteOut,
    MemberOut,
    MemberUpdate,
    MeOut,
    MyHousehold,
)
from hm_identity.domain.invites import VALIDITY as INVITE_VALIDITY
from hm_identity.domain.invites import InviteStatus, effective_status, hash_code, new_code
from hm_identity.domain.memberships import LastAdminError, ensure_an_admin_remains
from hm_identity.infra import households, invites, memberships
from hm_identity.infra.invites import RedeemOutcome
from hm_identity.infra.models import Household, Invite, Membership, User
from hm_platform.db import DbSession
from hm_platform.tenancy import (
    AdminTenant,
    MembershipCacheDep,
    PathTenant,
    PrincipalDep,
    Role,
    Tenant,
)

router = APIRouter(tags=["identity"])


def _household_out(household: Household, role: Role) -> HouseholdOut:
    return HouseholdOut(
        id=household.id, name=household.name, role=role, created_at=household.created_at
    )


async def _load(session: DbSession, tenant: Tenant) -> Household:
    household = await households.get_household(session, tenant.household_id)
    if household is None:  # a membership existia, o lar não: só em corrida com remoção
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="household not found")
    return household


@router.get("/me")
async def get_me(user: PrincipalDep, session: DbSession) -> MeOut:
    """Perfil do usuário e os lares de que é membro. Não exige lar ativo."""
    profile = await households.get_user(session, user.id)
    if profile is None:  # acabou de ser provisionado nesta mesma transação
        raise RuntimeError(f"user {user.id} vanished during the request")
    return MeOut(
        id=profile.id,
        email=profile.email,
        name=profile.name,
        households=[
            MyHousehold(id=h.id, name=h.name, role=Role(role))
            for h, role in await households.list_user_households(session, user.id)
        ],
    )


@router.post("/households", status_code=status.HTTP_201_CREATED)
async def create_household(
    body: HouseholdCreate, user: PrincipalDep, session: DbSession
) -> HouseholdOut:
    household = await households.create_household(session, user.id, body.name)
    return _household_out(household, Role.ADMIN)


@router.get("/households/{household_id}")
async def get_household(tenant: PathTenant, session: DbSession) -> HouseholdOut:
    return _household_out(await _load(session, tenant), tenant.role)


@router.patch("/households/{household_id}")
async def rename_household(
    body: HouseholdUpdate, tenant: AdminTenant, session: DbSession
) -> HouseholdOut:
    household = await households.rename_household(session, await _load(session, tenant), body.name)
    return _household_out(household, tenant.role)


# --- Membros -----------------------------------------------------------------------------


def _member_out(membership: Membership, user: User) -> MemberOut:
    return MemberOut(
        user_id=user.id,
        name=user.name,
        email=user.email,
        role=Role(membership.role),
        joined_at=membership.joined_at,
    )


async def _find_member(
    session: DbSession, tenant: Tenant, user_id: uuid.UUID
) -> tuple[Membership, User]:
    found = await memberships.get_member(session, tenant.household_id, user_id)
    if found is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="member not found")
    return found


_LAST_ADMIN = HTTPException(
    status.HTTP_409_CONFLICT, detail="the household must keep at least one admin"
)


@router.get("/households/{household_id}/members")
async def list_members(tenant: PathTenant, session: DbSession) -> list[MemberOut]:
    return [
        _member_out(m, u) for m, u in await memberships.list_members(session, tenant.household_id)
    ]


@router.patch("/households/{household_id}/members/{user_id}")
async def change_member_role(
    user_id: uuid.UUID,
    body: MemberUpdate,
    tenant: AdminTenant,
    session: DbSession,
    cache: MembershipCacheDep,
) -> MemberOut:
    admins = await memberships.lock_admins(session, tenant.household_id)
    membership, user = await _find_member(session, tenant, user_id)
    try:
        ensure_an_admin_remains(admins, user_id, body.role)
    except LastAdminError:
        raise _LAST_ADMIN from None
    await memberships.set_role(session, membership, body.role)
    cache.invalidate_after_commit(session, user_id, tenant.household_id)
    return _member_out(membership, user)


@router.delete(
    "/households/{household_id}/members/{user_id}", status_code=status.HTTP_204_NO_CONTENT
)
async def remove_member(
    user_id: uuid.UUID, tenant: PathTenant, session: DbSession, cache: MembershipCacheDep
) -> None:
    """Admin remove qualquer membro; qualquer membro pode sair (remover a si mesmo)."""
    if user_id != tenant.user.id and tenant.role is not Role.ADMIN:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, detail="only admins can remove other members"
        )
    admins = await memberships.lock_admins(session, tenant.household_id)
    membership, _ = await _find_member(session, tenant, user_id)
    try:
        ensure_an_admin_remains(admins, user_id, None)
    except LastAdminError:
        raise _LAST_ADMIN from None
    await memberships.remove(session, membership)
    cache.invalidate_after_commit(session, user_id, tenant.household_id)


# --- Convites ----------------------------------------------------------------------------


def _invite_out(invite: Invite, now: datetime) -> InviteOut:
    return InviteOut(
        id=invite.id,
        role=Role(invite.role),
        status=effective_status(invite.status, invite.expires_at, now),
        expires_at=invite.expires_at,
        created_at=invite.created_at,
    )


@router.post("/households/{household_id}/invites", status_code=status.HTTP_201_CREATED)
async def create_invite(
    body: InviteCreate, tenant: AdminTenant, session: DbSession
) -> InviteCreated:
    code = new_code()
    invite = await invites.create_invite(
        session,
        tenant.household_id,
        tenant.user.id,
        body.role,
        hash_code(code),
        datetime.now(UTC) + INVITE_VALIDITY,
    )
    return InviteCreated(id=invite.id, code=code, role=body.role, expires_at=invite.expires_at)


@router.get("/households/{household_id}/invites")
async def list_invites(tenant: AdminTenant, session: DbSession) -> list[InviteOut]:
    now = datetime.now(UTC)
    return [_invite_out(i, now) for i in await invites.list_invites(session, tenant.household_id)]


@router.delete(
    "/households/{household_id}/invites/{invite_id}", status_code=status.HTTP_204_NO_CONTENT
)
async def revoke_invite(invite_id: uuid.UUID, tenant: AdminTenant, session: DbSession) -> None:
    invite = await invites.get_invite_for_update(session, tenant.household_id, invite_id)
    if invite is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="invite not found")
    current = effective_status(invite.status, invite.expires_at, datetime.now(UTC))
    if current is not InviteStatus.PENDING:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=f"invite is {current}")
    await invites.revoke(session, invite)


_REDEEM_ERRORS = {
    RedeemOutcome.NOT_FOUND: (status.HTTP_404_NOT_FOUND, "invite not found"),
    RedeemOutcome.GONE: (status.HTTP_410_GONE, "invite expired, already used or revoked"),
    RedeemOutcome.ALREADY_MEMBER: (status.HTTP_409_CONFLICT, "already a member of this household"),
}


@router.post("/invites/accept")
async def accept_invite(
    body: InviteAccept, user: PrincipalDep, session: DbSession
) -> InviteAccepted:
    """Sem escopo de lar: quem aceita ainda não é membro (o lar vem do convite)."""
    outcome, household_id, role = await invites.redeem(session, hash_code(body.code), user.id)
    if outcome is not RedeemOutcome.ACCEPTED or household_id is None or role is None:
        code, detail = _REDEEM_ERRORS.get(outcome, (500, "unexpected redeem result"))
        raise HTTPException(code, detail=detail)
    return InviteAccepted(household_id=household_id, role=role)
