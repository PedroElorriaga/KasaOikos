"""Tokens de teste: chave RSA própria e JWKS servido por HTTP local (ADR-0002, seção Testes).

O Keycloak é serviço externo; aqui ele é substituído por uma chave de teste. O PyJWKClient
da API busca o JWKS por HTTP de verdade, sem mock.
"""

import base64
import hashlib
import hmac
import json
import threading
import time
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

import jwt
from cryptography.hazmat.primitives.asymmetric import rsa
from jwt.algorithms import RSAAlgorithm

EMISSOR = "http://keycloak-teste.local/realms/kasaoikos"
AUDIENCIA = "kasaoikos-api"
KID = "chave-teste-1"


def gerar_chave() -> rsa.RSAPrivateKey:
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


def jwks_de(chave: rsa.RSAPrivateKey) -> dict[str, Any]:
    jwk = RSAAlgorithm.to_jwk(chave.public_key(), as_dict=True)
    jwk.update({"kid": KID, "use": "sig", "alg": "RS256"})
    return {"keys": [jwk]}


@contextmanager
def servidor_jwks(jwks: dict[str, Any]) -> Iterator[str]:
    """Serve o JWKS em 127.0.0.1 (porta livre) e devolve a URL."""
    corpo = json.dumps(jwks).encode()

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(corpo)))
            self.end_headers()
            self.wfile.write(corpo)

        def log_message(self, format: str, *args: Any) -> None:
            pass  # silencia o log de acesso no stderr dos testes

    servidor = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=servidor.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{servidor.server_port}/certs"
    finally:
        servidor.shutdown()
        servidor.server_close()


def claims_validos(**alteracoes: Any) -> dict[str, Any]:
    """Claims como os de um access token do Keycloak; `alteracoes` sobrescreve ou remove (None)."""
    agora = int(time.time())
    sub = str(uuid.uuid4())
    claims: dict[str, Any] = {
        "iss": EMISSOR,
        "aud": AUDIENCIA,
        "sub": sub,
        "iat": agora,
        "exp": agora + 300,
        "typ": "Bearer",
        "name": "Ana Teste",
        "preferred_username": "ana.teste",
        "email": f"ana.{sub[:8]}@example.com",
    }
    claims.update(alteracoes)
    return {k: v for k, v in claims.items() if v is not None}


def assinar(claims: dict[str, Any], chave: rsa.RSAPrivateKey, *, kid: str = KID) -> str:
    return jwt.encode(claims, chave, algorithm="RS256", headers={"kid": kid})


def forjar_hs256(claims: dict[str, Any], segredo: bytes) -> str:
    """HS256 montado à mão: o PyJWT recusa usar uma chave pública como segredo HMAC."""

    def b64(dados: bytes) -> str:
        return base64.urlsafe_b64encode(dados).rstrip(b"=").decode()

    cabecalho = b64(json.dumps({"alg": "HS256", "typ": "JWT", "kid": KID}).encode())
    corpo = b64(json.dumps(claims).encode())
    assinatura = hmac.new(segredo, f"{cabecalho}.{corpo}".encode(), hashlib.sha256).digest()
    return f"{cabecalho}.{corpo}.{b64(assinatura)}"
