"""Cliente Redis/Valkey (async), usado pelo cache de membership (design D6)."""

from redis.asyncio import Redis
from redis.asyncio.retry import Retry
from redis.backoff import ExponentialBackoff

from hm_platform.settings import RedisSettings


def create_redis(settings: RedisSettings) -> Redis:
    return Redis(
        host=settings.host,
        port=settings.port,
        db=settings.db,
        password=settings.password.get_secret_value() if settings.password else None,
        decode_responses=True,
        # É um cache: se cair, melhor falhar rápido e ir ao banco. O padrão do redis-py
        # (3 retries, backoff de até 10 s) seguraria cada requisição por ~10 s.
        socket_connect_timeout=settings.timeout_seconds,
        socket_timeout=settings.timeout_seconds,
        retry=Retry(ExponentialBackoff(cap=0.05, base=0.01), retries=1),
    )
