"""Papéis por lar. Sem dependências: pode ser usado pela camada de domínio dos módulos."""

from enum import StrEnum


class Role(StrEnum):
    ADMIN = "admin"
    MEMBER = "member"
