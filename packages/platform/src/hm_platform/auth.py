"""Autenticação (design D5): validação de JWTs do Keycloak com cache de JWKS.

A plataforma só responde "quem é você" (claims validadas). Transformar as claims em
usuário local (provisionamento) é papel do módulo identity.
"""

import asyncio
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Annotated, Any

import httpx
import jwt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from hm_platform.settings import OIDCSettings


@dataclass(frozen=True)
class TokenClaims:
    subject: str
    email: str | None
    name: str | None
    raw: Mapping[str, Any]


class AuthenticationError(Exception):
    """Token ausente, malformado ou inválido: resulta em 401."""


class IdentityProviderUnavailableError(Exception):
    """Não foi possível obter as chaves do provedor: resulta em 503."""


class JWKSCache:
    """Chaves públicas do provedor, indexadas por ``kid``.

    Um ``kid`` desconhecido provoca novo fetch do JWKS (rotação de chaves), mas no
    máximo uma vez a cada ``min_refetch_interval`` segundos: tokens forjados com
    ``kid`` aleatório não viram uma enxurrada de requisições ao Keycloak.
    """

    def __init__(
        self,
        url: str,
        http: httpx.AsyncClient,
        *,
        min_refetch_interval: float,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._url = url
        self._http = http
        self._min_refetch_interval = min_refetch_interval
        self._clock = clock
        self._keys: dict[str, jwt.PyJWK] = {}
        self._last_fetch: float | None = None
        # Último fetch falhou: sem a chave, a culpa é do provedor, não do token.
        self._provider_down = False
        self._lock = asyncio.Lock()

    async def get(self, kid: str) -> jwt.PyJWK:
        if key := self._keys.get(kid):
            return key
        async with self._lock:
            # Outra requisição pode ter buscado as chaves enquanto esta esperava.
            if (key := self._keys.get(kid)) is None and self._may_refetch():
                await self._refresh()
                key = self._keys.get(kid)
        if key is None:
            if self._provider_down:
                raise IdentityProviderUnavailableError("JWKS unavailable")
            raise AuthenticationError("unknown signing key")
        return key

    def _may_refetch(self) -> bool:
        return (
            self._last_fetch is None
            or self._clock() - self._last_fetch >= self._min_refetch_interval
        )

    async def _refresh(self) -> None:
        # Marca antes do fetch: falhas também respeitam o intervalo mínimo.
        self._last_fetch = self._clock()
        try:
            response = await self._http.get(self._url, timeout=5.0)
            response.raise_for_status()
            document = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            self._provider_down = True
            raise IdentityProviderUnavailableError(f"JWKS fetch failed: {exc}") from exc
        self._provider_down = False
        keys: dict[str, jwt.PyJWK] = {}
        for jwk in document.get("keys", []):
            # O Keycloak publica também chaves de cifragem (use=enc): só valem as de assinatura.
            if jwk.get("use", "sig") != "sig" or "kid" not in jwk:
                continue
            try:
                keys[jwk["kid"]] = jwt.PyJWK(jwk)
            except jwt.PyJWKError:
                continue
        self._keys = keys


class TokenValidator:
    def __init__(self, settings: OIDCSettings, jwks: JWKSCache) -> None:
        self._settings = settings
        self._jwks = jwks

    async def validate(self, token: str) -> TokenClaims:
        try:
            header = jwt.get_unverified_header(token)
        except jwt.DecodeError as exc:
            raise AuthenticationError("malformed token") from exc
        # Só aceita os algoritmos configurados (RS256): bloqueia "none" e HS256
        # assinado com a chave pública (algorithm confusion).
        if header.get("alg") not in self._settings.algorithms:
            raise AuthenticationError("unsupported signing algorithm")
        kid = header.get("kid")
        if not isinstance(kid, str):
            raise AuthenticationError("token without key id")

        key = await self._jwks.get(kid)
        try:
            claims: dict[str, Any] = jwt.decode(
                token,
                key=key.key,
                algorithms=list(self._settings.algorithms),
                audience=self._settings.audience,
                issuer=self._settings.issuer,
                leeway=self._settings.leeway_seconds,
                options={"require": ["exp", "iat", "iss", "aud", "sub"]},
            )
        except jwt.ExpiredSignatureError as exc:
            raise AuthenticationError("token expired") from exc
        except jwt.InvalidTokenError as exc:
            raise AuthenticationError("invalid token") from exc

        return TokenClaims(
            subject=claims["sub"],
            email=claims.get("email"),
            name=claims.get("name"),
            raw=claims,
        )


def create_token_validator(settings: OIDCSettings, http: httpx.AsyncClient) -> TokenValidator:
    jwks = JWKSCache(
        settings.resolved_jwks_url(),
        http,
        min_refetch_interval=settings.jwks_refetch_min_interval_seconds,
    )
    return TokenValidator(settings, jwks)


# auto_error=False: a ausência do header vira o nosso 401 (com WWW-Authenticate),
# não o 403 padrão do FastAPI. Também registra o esquema Bearer no OpenAPI.
_bearer = HTTPBearer(auto_error=False)


def _unauthorized(detail: str, error: str | None = None) -> HTTPException:
    challenge = "Bearer" if error is None else f'Bearer error="{error}"'
    return HTTPException(
        status.HTTP_401_UNAUTHORIZED, detail=detail, headers={"WWW-Authenticate": challenge}
    )


async def get_token_claims(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> TokenClaims:
    """Dependency FastAPI: exige um Bearer token válido e devolve suas claims."""
    if credentials is None:
        raise _unauthorized("missing bearer token")
    validator: TokenValidator = request.app.state.token_validator
    try:
        return await validator.validate(credentials.credentials)
    except AuthenticationError as exc:
        raise _unauthorized(str(exc), error="invalid_token") from exc
    except IdentityProviderUnavailableError as exc:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, detail="identity provider unavailable"
        ) from exc
