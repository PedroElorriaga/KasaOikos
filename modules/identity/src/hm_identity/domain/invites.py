"""Regras de convites (design D7)."""

import hashlib
import secrets
from datetime import datetime, timedelta
from enum import StrEnum

VALIDITY = timedelta(days=7)


class InviteStatus(StrEnum):
    PENDING = "pending"
    ACCEPTED = "accepted"
    REVOKED = "revoked"
    EXPIRED = "expired"  # calculado: pending com expires_at no passado (sem job)


def new_code() -> str:
    """Código secreto de uso único, mostrado só na criação."""
    return secrets.token_urlsafe(32)


def hash_code(code: str) -> str:
    # O banco guarda só o hash: um vazamento da tabela não entrega convites válidos.
    return hashlib.sha256(code.encode()).hexdigest()


def effective_status(stored: str, expires_at: datetime, now: datetime) -> InviteStatus:
    if stored == InviteStatus.PENDING and expires_at <= now:
        return InviteStatus.EXPIRED
    return InviteStatus(stored)
