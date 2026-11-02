"""Provisionamento just-in-time do usuário local a partir das claims do token (design D5)."""

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from hm_identity.infra.models import User
from hm_platform.auth import TokenClaims
from hm_platform.ids import uuid7
from hm_platform.tenancy import Principal


async def provision_user(session: AsyncSession, claims: TokenClaims) -> Principal:
    """Cria ou atualiza o usuário local. Só escreve quando algo mudou.

    O caminho comum (usuário já existe, dados iguais) é um único SELECT: sem isso,
    toda requisição autenticada viraria uma escrita no banco.
    """
    user = await session.scalar(select(User).where(User.subject == claims.subject))

    if user is None:
        # ON CONFLICT: duas requisições simultâneas do mesmo usuário novo não falham.
        await session.execute(
            insert(User)
            .values(id=uuid7(), subject=claims.subject, email=claims.email, name=claims.name)
            .on_conflict_do_nothing(index_elements=[User.subject])
        )
        user = await session.scalar(select(User).where(User.subject == claims.subject))
        if user is None:
            raise RuntimeError(f"user {claims.subject!r} vanished right after provisioning")
    elif (user.email, user.name) != (claims.email, claims.name):
        user.email = claims.email
        user.name = claims.name
        user.updated_at = func.now()
        await session.flush()

    return Principal(id=user.id, subject=user.subject)
