"""Spec identity/authentication: validação de token e rotação de chaves (tarefa 4.2)."""

import asyncio
import time
from collections.abc import AsyncIterator
from typing import Annotated

import httpx
import jwt
import pytest
import pytest_asyncio
from fastapi import Depends, FastAPI

from hm_platform.auth import (
    AuthenticationError,
    IdentityProviderUnavailableError,
    JWKSCache,
    TokenClaims,
    TokenValidator,
    get_token_claims,
)
from hm_platform.settings import OIDCSettings
from hm_platform.testing.tokens import (
    AUDIENCE,
    ISSUER,
    JWKS_URL,
    FakeJWKS,
    SigningKey,
    TokenFactory,
)

REFETCH_INTERVAL = 30.0


class FakeClock:
    def __init__(self) -> None:
        self.now = 1_000.0

    def __call__(self) -> float:
        return self.now


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest_asyncio.fixture
async def validator(fake_jwks: FakeJWKS, clock: FakeClock) -> AsyncIterator[TokenValidator]:
    settings = OIDCSettings(issuer=ISSUER, audience=AUDIENCE, jwks_url=JWKS_URL)
    async with httpx.AsyncClient(transport=fake_jwks.transport()) as http:
        jwks = JWKSCache(JWKS_URL, http, min_refetch_interval=REFETCH_INTERVAL, clock=clock)
        yield TokenValidator(settings, jwks)


@pytest_asyncio.fixture
async def api(validator: TokenValidator) -> AsyncIterator[httpx.AsyncClient]:
    app = FastAPI()
    app.state.token_validator = validator

    @app.get("/protected")
    async def protected(
        claims: Annotated[TokenClaims, Depends(get_token_claims)],
    ) -> dict[str, str]:
        return {"sub": claims.subject}

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as http:
        yield http


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


# --- Requirement: Validação de token de acesso -------------------------------------------


async def test_valid_token_is_processed_as_its_subject(
    api: httpx.AsyncClient, token_factory: TokenFactory
) -> None:
    response = await api.get("/protected", headers=bearer(token_factory.valid(sub="user-123")))
    assert response.status_code == 200
    assert response.json() == {"sub": "user-123"}


async def test_missing_token_returns_401_with_bearer_challenge(api: httpx.AsyncClient) -> None:
    response = await api.get("/protected")
    assert response.status_code == 401
    assert response.headers["WWW-Authenticate"] == "Bearer"


@pytest.mark.parametrize("header", ["Basic dXNlcjpwYXNz", "Bearer", "Bearer not-a-jwt"])
async def test_malformed_authorization_returns_401(api: httpx.AsyncClient, header: str) -> None:
    response = await api.get("/protected", headers={"Authorization": header})
    assert response.status_code == 401
    assert response.headers["WWW-Authenticate"].startswith("Bearer")


@pytest.mark.parametrize(
    "variant",
    [
        "expired",  # Cenário: Token expirado
        "wrong_issuer",  # Cenário: Emissor ou audiência incorretos
        "wrong_audience",
        "bad_signature",  # Cenário: Assinatura inválida (kid publicado, chave errada)
        "unknown_kid",  # Cenário: Assinatura inválida (chave nunca publicada)
    ],
)
async def test_invalid_tokens_return_401(
    api: httpx.AsyncClient, token_factory: TokenFactory, variant: str
) -> None:
    response = await api.get("/protected", headers=bearer(getattr(token_factory, variant)()))
    assert response.status_code == 401
    assert response.headers["WWW-Authenticate"] == 'Bearer error="invalid_token"'


async def test_token_without_subject_is_rejected(
    validator: TokenValidator, signing_key: SigningKey
) -> None:
    now = int(time.time())
    claims = {"iss": ISSUER, "aud": AUDIENCE, "iat": now, "exp": now + 60}
    token = jwt.encode(claims, signing_key.private_key, "RS256", headers={"kid": signing_key.kid})
    with pytest.raises(AuthenticationError):
        await validator.validate(token)


@pytest.mark.parametrize("alg", ["none", "HS256"])
async def test_algorithm_confusion_is_rejected(
    validator: TokenValidator, token_factory: TokenFactory, signing_key: SigningKey, alg: str
) -> None:
    claims = jwt.decode(token_factory.valid(), options={"verify_signature": False})
    # HS256 "assinado" com a chave pública: o ataque clássico contra validadores ingênuos.
    secret = signing_key.public_jwk()["n"] if alg == "HS256" else ""
    forged = jwt.encode(claims, secret, algorithm=alg, headers={"kid": signing_key.kid})
    with pytest.raises(AuthenticationError, match="algorithm"):
        await validator.validate(forged)


# --- Requirement: Rotação de chaves de assinatura ----------------------------------------


async def test_new_key_after_rotation_is_accepted_without_restart(
    validator: TokenValidator, token_factory: TokenFactory, fake_jwks: FakeJWKS, clock: FakeClock
) -> None:
    await validator.validate(token_factory.valid())  # aquece o cache com a chave atual
    assert fake_jwks.fetches == 1

    clock.now += REFETCH_INTERVAL  # a rotação acontece depois de um tempo
    new_key = SigningKey.generate("test-key-2")
    fake_jwks.keys.append(new_key)
    claims = await validator.validate(token_factory.valid(key=new_key, sub="after-rotation"))

    assert claims.subject == "after-rotation"
    assert fake_jwks.fetches == 2


async def test_known_keys_are_served_from_cache(
    validator: TokenValidator, token_factory: TokenFactory, fake_jwks: FakeJWKS
) -> None:
    for _ in range(20):
        await validator.validate(token_factory.valid())
    assert fake_jwks.fetches == 1


async def test_unknown_kid_refetch_is_rate_limited(
    validator: TokenValidator, token_factory: TokenFactory, fake_jwks: FakeJWKS, clock: FakeClock
) -> None:
    await validator.validate(token_factory.valid())
    clock.now += REFETCH_INTERVAL

    # Rajada de tokens forjados com kid desconhecido: um único refetch na janela.
    for _ in range(10):
        with pytest.raises(AuthenticationError, match="unknown signing key"):
            await validator.validate(token_factory.unknown_kid())
    assert fake_jwks.fetches == 2

    clock.now += REFETCH_INTERVAL - 1
    with pytest.raises(AuthenticationError):
        await validator.validate(token_factory.unknown_kid())
    assert fake_jwks.fetches == 2

    clock.now += 1  # a janela fechou: pode buscar de novo
    with pytest.raises(AuthenticationError):
        await validator.validate(token_factory.unknown_kid())
    assert fake_jwks.fetches == 3


async def test_concurrent_requests_with_new_kid_fetch_once(
    validator: TokenValidator, token_factory: TokenFactory, fake_jwks: FakeJWKS
) -> None:
    new_key = SigningKey.generate("test-key-2")
    fake_jwks.keys.append(new_key)
    token = token_factory.valid(key=new_key)

    results = await asyncio.gather(*(validator.validate(token) for _ in range(10)))

    assert len(results) == 10
    assert fake_jwks.fetches == 1


async def test_encryption_keys_in_jwks_are_ignored(
    validator: TokenValidator, token_factory: TokenFactory
) -> None:
    with pytest.raises(AuthenticationError, match="unknown signing key"):
        await validator.validate(token_factory.valid(kid="enc-key"))


async def test_unreachable_provider_returns_503(token_factory: TokenFactory) -> None:
    def down(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    settings = OIDCSettings(issuer=ISSUER, audience=AUDIENCE, jwks_url=JWKS_URL)
    async with httpx.AsyncClient(transport=httpx.MockTransport(down)) as http:
        validator = TokenValidator(settings, JWKSCache(JWKS_URL, http, min_refetch_interval=30))
        with pytest.raises(IdentityProviderUnavailableError):
            await validator.validate(token_factory.valid())

        app = FastAPI()
        app.state.token_validator = validator

        @app.get("/protected")
        async def protected(claims: Annotated[TokenClaims, Depends(get_token_claims)]) -> None:
            return None

        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            # Ainda dentro da janela: não chama o provedor de novo, mas continua 503
            # (um token válido não pode virar 401 só porque o Keycloak caiu).
            response = await client.get("/protected", headers=bearer(token_factory.valid()))
        assert response.status_code == 503
