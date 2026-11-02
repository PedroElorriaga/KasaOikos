"""Modelos ORM do módulo identity, todos no schema ``identity``.

O isolamento por lar (RLS) é criado nas migrações; os modelos só descrevem as tabelas.
"""

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, String, func, text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from hm_platform.db import UUIDv7PrimaryKey, schema_metadata

ROLE_VALUES = "role in ('admin', 'member')"


class Base(DeclarativeBase):
    metadata = schema_metadata("identity")


class User(UUIDv7PrimaryKey, Base):
    """Registro local de um usuário do Keycloak, criado no primeiro acesso.

    Não tem ``household_id``: um usuário existe fora de qualquer lar (o vínculo é a
    membership), por isso a tabela não leva a política de RLS por lar.
    """

    __tablename__ = "users"

    # Claim "sub" do token: identificador estável do usuário no provedor.
    subject: Mapped[str] = mapped_column(String(255), unique=True)
    email: Mapped[str | None] = mapped_column(String(320))
    name: Mapped[str | None] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Household(UUIDv7PrimaryKey, Base):
    """O tenant. Visível no lar ativo ou para quem é membro (política especial do D4)."""

    __tablename__ = "households"

    name: Mapped[str] = mapped_column(String(80))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Membership(Base):
    __tablename__ = "memberships"
    __table_args__ = (
        CheckConstraint(ROLE_VALUES, name="role"),
        # GET /me e a política de leitura filtram por usuário.
        Index("ix_memberships_user_id", "user_id"),
    )

    household_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("identity.households.id", ondelete="CASCADE"), primary_key=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("identity.users.id", ondelete="CASCADE"), primary_key=True
    )
    role: Mapped[str] = mapped_column(String(16))
    joined_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Invite(UUIDv7PrimaryKey, Base):
    """Convite de uso único (design D7). Só o SHA-256 do código é guardado."""

    __tablename__ = "invites"
    __table_args__ = (
        CheckConstraint(ROLE_VALUES, name="role"),
        CheckConstraint("status in ('pending', 'accepted', 'revoked')", name="status"),
        Index("ix_invites_household_id", "household_id"),
    )

    household_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("identity.households.id", ondelete="CASCADE")
    )
    code_hash: Mapped[str] = mapped_column(String(64), unique=True)
    role: Mapped[str] = mapped_column(String(16))
    # "expired" não é guardado: é pending com expires_at no passado (sem job de limpeza).
    status: Mapped[str] = mapped_column(String(16), server_default=text("'pending'"))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("identity.users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    accepted_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("identity.users.id"))
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
