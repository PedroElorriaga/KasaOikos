"""MembershipCache isolado, com um resolver falso no lugar do módulo identity."""

import time
import uuid

from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from hm_platform.cache import create_redis
from hm_platform.settings import RedisSettings
from hm_platform.tenancy import MembershipCache, Role

USER, HOUSEHOLD = uuid.uuid4(), uuid.uuid4()


class FakeResolver:
    def __init__(self, role: Role | None) -> None:
        self.role = role
        self.calls = 0

    async def __call__(
        self, session: AsyncSession, user_id: uuid.UUID, household_id: uuid.UUID
    ) -> Role | None:
        self.calls += 1
        return self.role


SESSION: AsyncSession = None  # type: ignore[assignment]  # o resolver falso não usa a sessão


async def test_caches_roles_with_ttl(redis_client: Redis) -> None:
    resolver = FakeResolver(Role.ADMIN)
    cache = MembershipCache(redis_client, resolver, ttl_seconds=60)

    assert await cache.get_role(SESSION, USER, HOUSEHOLD) == Role.ADMIN
    assert await cache.get_role(SESSION, USER, HOUSEHOLD) == Role.ADMIN

    assert resolver.calls == 1
    assert 0 < await redis_client.ttl(MembershipCache.key(USER, HOUSEHOLD)) <= 60


async def test_non_membership_is_not_cached(redis_client: Redis) -> None:
    resolver = FakeResolver(None)
    cache = MembershipCache(redis_client, resolver, ttl_seconds=60)

    assert await cache.get_role(SESSION, USER, HOUSEHOLD) is None
    resolver.role = Role.MEMBER  # aceitou um convite: tem acesso já na próxima requisição
    assert await cache.get_role(SESSION, USER, HOUSEHOLD) == Role.MEMBER


async def test_invalidate_forces_a_fresh_read(redis_client: Redis) -> None:
    resolver = FakeResolver(Role.ADMIN)
    cache = MembershipCache(redis_client, resolver, ttl_seconds=60)
    await cache.get_role(SESSION, USER, HOUSEHOLD)

    resolver.role = Role.MEMBER
    await cache.invalidate(USER, HOUSEHOLD)

    assert await cache.get_role(SESSION, USER, HOUSEHOLD) == Role.MEMBER


async def test_unavailable_redis_falls_back_to_the_resolver_quickly() -> None:
    # Porta 1: ninguém escuta. Usa a mesma fábrica da aplicação (timeouts e retries reais).
    redis = create_redis(RedisSettings(host="127.0.0.1", port=1))
    started = time.monotonic()
    resolver = FakeResolver(Role.MEMBER)
    try:
        cache = MembershipCache(redis, resolver, ttl_seconds=60)
        assert await cache.get_role(SESSION, USER, HOUSEHOLD) == Role.MEMBER
        assert resolver.calls == 1
        assert time.monotonic() - started < 3
    finally:
        await redis.aclose()
