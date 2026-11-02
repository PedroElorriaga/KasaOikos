"""Contratos HTTP do módulo identity."""

import uuid
from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, StringConstraints

from hm_identity.domain.invites import InviteStatus
from hm_platform.roles import Role

HouseholdName = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=80)
]


class HouseholdCreate(BaseModel):
    name: HouseholdName


class HouseholdUpdate(BaseModel):
    name: HouseholdName


class HouseholdOut(BaseModel):
    id: uuid.UUID
    name: str
    role: Role  # papel de quem pergunta
    created_at: datetime


class MyHousehold(BaseModel):
    id: uuid.UUID
    name: str
    role: Role


class MemberOut(BaseModel):
    user_id: uuid.UUID
    name: str | None
    email: str | None
    role: Role
    joined_at: datetime


class MemberUpdate(BaseModel):
    role: Role


class InviteCreate(BaseModel):
    role: Role = Role.MEMBER


class InviteCreated(BaseModel):
    id: uuid.UUID
    code: str  # única vez em que o código aparece
    role: Role
    expires_at: datetime


class InviteOut(BaseModel):
    id: uuid.UUID
    role: Role
    status: InviteStatus
    expires_at: datetime
    created_at: datetime


class InviteAccept(BaseModel):
    code: Annotated[str, StringConstraints(min_length=1, max_length=128)]


class InviteAccepted(BaseModel):
    household_id: uuid.UUID
    role: Role


class MeOut(BaseModel):
    id: uuid.UUID
    email: str | None
    name: str | None
    households: list[MyHousehold]
