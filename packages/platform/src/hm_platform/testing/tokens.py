"""Tokens de teste (design D10): pares RSA em memória, JWKS falso e fábrica de JWTs.

Substituem o Keycloak nos testes: os tokens têm o mesmo formato (RS256, ``kid`` no
header, ``iss``/``aud``/``sub``/``email``/``name``) e o JWKS é servido por um
``httpx.MockTransport``, que também conta os fetches.
"""

import json
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

import httpx
import jwt
from cryptography.hazmat.primitives.asymmetric import rsa
from jwt.algorithms import RSAAlgorithm

ISSUER = "http://keycloak.test/realms/home"
AUDIENCE = "home-api"
JWKS_URL = f"{ISSUER}/protocol/openid-connect/certs"


@dataclass(frozen=True)
class SigningKey:
    kid: str
    private_key: rsa.RSAPrivateKey

    @classmethod
    def generate(cls, kid: str | None = None) -> "SigningKey":
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        return cls(kid=kid or f"kid-{uuid.uuid4().hex[:8]}", private_key=key)

    def public_jwk(self) -> dict[str, Any]:
        jwk: dict[str, Any] = json.loads(RSAAlgorithm.to_jwk(self.private_key.public_key()))
        return {**jwk, "kid": self.kid, "alg": "RS256", "use": "sig"}


@dataclass
class FakeJWKS:
    """JWKS publicado pelo "provedor". Alterar ``keys`` simula uma rotação de chaves."""

    keys: list[SigningKey]
    fetches: int = field(default=0, init=False)

    def document(self) -> dict[str, Any]:
        # Como o Keycloak, publica também uma chave de cifragem, que deve ser ignorada.
        enc = {
            "kid": "enc-key",
            "kty": "RSA",
            "use": "enc",
            "alg": "RSA-OAEP",
            "n": "AQAB",
            "e": "AQAB",
        }
        return {"keys": [k.public_jwk() for k in self.keys] + [enc]}

    def transport(self) -> httpx.MockTransport:
        def handler(request: httpx.Request) -> httpx.Response:
            if str(request.url) != JWKS_URL:
                return httpx.Response(404)
            self.fetches += 1
            return httpx.Response(200, json=self.document())

        return httpx.MockTransport(handler)


@dataclass
class TokenFactory:
    key: SigningKey
    issuer: str = ISSUER
    audience: str = AUDIENCE

    def issue(
        self,
        *,
        sub: str | None = None,
        email: str | None = "ana@example.com",
        name: str | None = "Ana Souza",
        expires_in: int = 300,
        issuer: str | None = None,
        audience: str | None = None,
        key: SigningKey | None = None,
        kid: str | None = None,
        **extra: Any,
    ) -> str:
        """Token de acesso no formato do Keycloak. Os argumentos permitem estragá-lo."""
        now = int(time.time())
        signer = key or self.key
        claims: dict[str, Any] = {
            "iss": issuer or self.issuer,
            "aud": [audience or self.audience, "account"],
            "sub": sub or str(uuid.uuid4()),
            "iat": now,
            "exp": now + expires_in,
            "azp": "home-loadtest",
            "typ": "Bearer",
            **extra,
        }
        if email is not None:
            claims["email"] = email
        if name is not None:
            claims["name"] = name
        return jwt.encode(
            claims, signer.private_key, algorithm="RS256", headers={"kid": kid or signer.kid}
        )

    def valid(self, **kwargs: Any) -> str:
        return self.issue(**kwargs)

    def expired(self, **kwargs: Any) -> str:
        return self.issue(expires_in=-60, **kwargs)

    def wrong_issuer(self, **kwargs: Any) -> str:
        return self.issue(issuer="http://keycloak.test/realms/other", **kwargs)

    def wrong_audience(self, **kwargs: Any) -> str:
        return self.issue(audience="other-api", **kwargs)

    def unknown_kid(self, **kwargs: Any) -> str:
        """Assinado por uma chave que o provedor nunca publicou."""
        return self.issue(key=SigningKey.generate("never-published"), **kwargs)

    def bad_signature(self, **kwargs: Any) -> str:
        """``kid`` de uma chave publicada, mas assinado com outra chave privada."""
        return self.issue(key=SigningKey.generate(self.key.kid), **kwargs)
