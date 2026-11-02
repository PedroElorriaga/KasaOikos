"""Tenancy (design D6): usuário autenticado, lar ativo, papel e cache de membership.

A plataforma não importa módulos (D2). O que ela precisa do identity entra por duas
portas, ligadas pelo ``hm_api`` em ``app.state``:

- ``user_provisioner``: claims do token → :class:`Principal` (provisionamento JIT);
- ``membership_cache``: :class:`MembershipCache`, que consulta um :class:`MembershipResolver`.
"""

import logging
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Annotated, Protocol

from fastapi import Depends, Header, HTTPException, Request, status
from opentelemetry.metrics import Meter, get_meter
from redis.asyncio import Redis
from redis.exceptions import RedisError
from sqlalchemy.ext.asyncio import AsyncSession

from hm_platform.auth import TokenClaims, get_token_claims
from hm_platform.db import DbSession, after_commit
from hm_platform.logs import bind_log_context
from hm_platform.rls import set_tenant_context
from hm_platform.roles import Role as Role  # reexportado: quem usa tenancy costuma precisar

logger = logging.getLogger(__name__)

HOUSEHOLD_HEADER = "X-Household-Id"


@dataclass(frozen=True)
class Principal:
    """Usuário autenticado e provisionado localmente."""

    id: uuid.UUID
    subject: str


@dataclass(frozen=True)
class Tenant:
    """Contexto de uma requisição com escopo de lar."""

    household_id: uuid.UUID
    user: Principal
    role: Role


class UserProvisioner(Protocol):
    def __call__(self, session: AsyncSession, claims: TokenClaims) -> Awaitable[Principal]: ...


class MembershipResolver(Protocol):
    def __call__(
        self, session: AsyncSession, user_id: uuid.UUID, household_id: uuid.UUID
    ) -> Awaitable[Role | None]: ...


class MembershipCache:
    """Papel do usuário no lar, com cache no Redis (``membership:{user}:{household}``).

    Só papéis existentes são guardados: um "não é membro" em cache atrasaria a entrada
    de quem acabou de aceitar um convite. O TTL é só uma rede de segurança; a
    invalidação é explícita, depois do commit (:meth:`invalidate_after_commit`).
    """

    def __init__(
        self,
        redis: Redis,
        resolver: MembershipResolver,
        ttl_seconds: int,
        meter: Meter | None = None,
    ) -> None:
        self._redis = redis
        self._resolver = resolver
        self._ttl = ttl_seconds
        self.hits = 0
        self.misses = 0
        # Hit ratio = hit / (hit + miss): métrica da baseline k6 (design D6).
        self._lookups = (meter or get_meter(__name__)).create_counter(
            "hm.membership_cache.lookups",
            unit="{lookup}",
            description="Consultas ao cache de membership, por resultado (hit, miss, error).",
        )

    @staticmethod
    def key(user_id: uuid.UUID, household_id: uuid.UUID) -> str:
        return f"membership:{user_id}:{household_id}"

    async def get_role(
        self, session: AsyncSession, user_id: uuid.UUID, household_id: uuid.UUID
    ) -> Role | None:
        key = self.key(user_id, household_id)
        try:
            cached = await self._redis.get(key)
        except RedisError:
            # Cache fora do ar não derruba a API: vai direto ao banco.
            logger.warning("membership cache unavailable; reading from database", exc_info=True)
            self._lookups.add(1, {"result": "error"})
            return await self._resolver(session, user_id, household_id)
        if cached is not None:
            self.hits += 1
            self._lookups.add(1, {"result": "hit"})
            return Role(cached.decode() if isinstance(cached, bytes) else cached)

        self.misses += 1
        self._lookups.add(1, {"result": "miss"})
        role = await self._resolver(session, user_id, household_id)
        if role is not None:
            try:
                await self._redis.set(key, role.value, ex=self._ttl)
            except RedisError:
                logger.warning("membership cache unavailable; not caching", exc_info=True)
        return role

    async def invalidate(self, user_id: uuid.UUID, household_id: uuid.UUID) -> None:
        await self._redis.delete(self.key(user_id, household_id))

    def invalidate_after_commit(
        self, session: AsyncSession, user_id: uuid.UUID, household_id: uuid.UUID
    ) -> None:
        """Chame em toda mudança de membership (papel, remoção, saída)."""

        async def callback() -> None:
            await self.invalidate(user_id, household_id)

        after_commit(session, callback)


# --- Dependencies FastAPI ---------------------------------------------------------------


def get_membership_cache(request: Request) -> MembershipCache:
    cache: MembershipCache = request.app.state.membership_cache
    return cache


MembershipCacheDep = Annotated[MembershipCache, Depends(get_membership_cache)]


async def get_principal(
    request: Request,
    claims: Annotated[TokenClaims, Depends(get_token_claims)],
    session: DbSession,
) -> Principal:
    """Usuário autenticado; define ``app.user_id`` e limpa o lar ativo da transação."""
    provisioner: UserProvisioner = request.app.state.user_provisioner
    principal = await provisioner(session, claims)
    await set_tenant_context(session, user_id=principal.id, household_id=None)
    bind_log_context(user_id=str(principal.id))
    return principal


PrincipalDep = Annotated[Principal, Depends(get_principal)]

_NOT_FOUND = HTTPException(status.HTTP_404_NOT_FOUND, detail="household not found")


def _parse_household_header(value: str) -> uuid.UUID:
    try:
        return uuid.UUID(value)
    except ValueError:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, detail=f"{HOUSEHOLD_HEADER} must be a UUID"
        ) from None


async def _enter_household(
    session: AsyncSession, cache: MembershipCache, principal: Principal, household_id: uuid.UUID
) -> Tenant:
    # A política de memberships deixa o usuário ler as próprias memberships (app.user_id
    # já definido), então o papel é resolvido antes de fixar o lar ativo.
    role = await cache.get_role(session, principal.id, household_id)
    if role is None:
        # Mesma resposta para "não existe" e "não é membro": não revela lares alheios.
        raise _NOT_FOUND
    await set_tenant_context(session, user_id=principal.id, household_id=household_id)
    bind_log_context(household_id=str(household_id))
    return Tenant(household_id=household_id, user=principal, role=role)


async def get_path_tenant(
    household_id: uuid.UUID,
    principal: PrincipalDep,
    session: DbSession,
    cache: MembershipCacheDep,
    header: Annotated[str | None, Header(alias=HOUSEHOLD_HEADER)] = None,
) -> Tenant:
    """Lar ativo pelo caminho (``/households/{household_id}/...``)."""
    if header is not None and _parse_household_header(header) != household_id:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            detail=f"{HOUSEHOLD_HEADER} does not match the household in the path",
        )
    return await _enter_household(session, cache, principal, household_id)


async def get_header_tenant(
    principal: PrincipalDep,
    session: DbSession,
    cache: MembershipCacheDep,
    header: Annotated[str | None, Header(alias=HOUSEHOLD_HEADER)] = None,
) -> Tenant:
    """Lar ativo pelo header ``X-Household-Id`` (endpoints sem o lar no caminho)."""
    if header is None:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, detail=f"{HOUSEHOLD_HEADER} header is required"
        )
    return await _enter_household(session, cache, principal, _parse_household_header(header))


PathTenant = Annotated[Tenant, Depends(get_path_tenant)]
HeaderTenant = Annotated[Tenant, Depends(get_header_tenant)]

_RANK = {Role.MEMBER: 0, Role.ADMIN: 1}


def require_role(
    role: Role, tenant_dependency: Callable[..., Awaitable[Tenant]] = get_path_tenant
) -> Callable[..., Awaitable[Tenant]]:
    """Exige pelo menos ``role`` no lar ativo (admin também atende a "member")."""

    async def dependency(tenant: Annotated[Tenant, Depends(tenant_dependency)]) -> Tenant:
        if _RANK[tenant.role] < _RANK[role]:
            raise HTTPException(status.HTTP_403_FORBIDDEN, detail=f"requires role {role}")
        return tenant

    return dependency


AdminTenant = Annotated[Tenant, Depends(require_role(Role.ADMIN))]
