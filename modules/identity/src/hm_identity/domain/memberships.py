"""Regras de membership (spec identity/households)."""

import uuid

from hm_platform.roles import Role


class LastAdminError(Exception):
    """A operação deixaria o lar sem nenhum admin."""


def ensure_an_admin_remains(
    admins: set[uuid.UUID], target: uuid.UUID, new_role: Role | None
) -> None:
    """``new_role=None`` significa remoção. Levanta :class:`LastAdminError` se sobrar zero admin."""
    remaining = admins | {target} if new_role is Role.ADMIN else admins - {target}
    if not remaining:
        raise LastAdminError
