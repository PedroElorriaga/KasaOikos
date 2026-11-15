"""Autenticação: valida o access token do Keycloak e identifica o usuário (ADR-0002).

A API é só resource server: confere assinatura (JWKS), `iss`, `aud`, `exp` e o algoritmo.
Nunca registrar o token nem os claims (e-mail) em log.
"""

import logging
from dataclasses import dataclass
from typing import Annotated, Any

import jwt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.config import Settings
from app.db import sessao
from app.usuarios import servico as usuarios_servico
from app.usuarios.esquemas import UsuarioAtual

logger = logging.getLogger(__name__)

# Único algoritmo aceito. Lista fixa: nunca vem do header do token (evita `none` e HS256).
_ALGORITMOS = ["RS256"]
_CLAIMS_OBRIGATORIOS = ["exp", "iat", "sub", "iss", "aud"]
# Segundos para desistir de buscar o JWKS no Keycloak.
_JWKS_TIMEOUT = 5

# auto_error=False: sem token, quem responde é usuario_atual (401 padronizado).
_bearer = HTTPBearer(auto_error=False)


class TokenInvalido(Exception):
    """O token não prova a identidade do usuário. Vira 401."""


class EmissorIndisponivel(Exception):
    """Não foi possível obter as chaves públicas do emissor. Vira 503."""


@dataclass(frozen=True)
class Identidade:
    sub: str
    nome: str
    email: str


class ValidadorToken:
    def __init__(self, settings: Settings) -> None:
        self._issuer = settings.oidc_issuer
        self._audience = settings.oidc_audience
        # Cache do conjunto de chaves (padrão: 5 min). Um `kid` desconhecido força no máximo
        # uma nova busca a cada `cooldown_duration` (padrão: 30 s).
        self._jwks = jwt.PyJWKClient(settings.jwks_url, cache_keys=True, timeout=_JWKS_TIMEOUT)

    def validar(self, token: str) -> Identidade:
        try:
            chave = self._jwks.get_signing_key_from_jwt(token)
            claims: dict[str, Any] = jwt.decode(
                token,
                chave.key,
                algorithms=_ALGORITMOS,
                issuer=self._issuer,
                audience=self._audience,
                options={"require": _CLAIMS_OBRIGATORIOS},
            )
        except jwt.PyJWKClientConnectionError as erro:
            raise EmissorIndisponivel from erro
        except jwt.PyJWTError as erro:
            # Só o nome da classe: a mensagem pode trazer partes do token.
            raise TokenInvalido(type(erro).__name__) from erro
        return _identidade(claims)


def _identidade(claims: dict[str, Any]) -> Identidade:
    sub = claims.get("sub")
    email = claims.get("email")
    nome = claims.get("name") or claims.get("preferred_username")
    if not isinstance(sub, str) or not sub:
        raise TokenInvalido("sub ausente")
    if not isinstance(email, str) or not email:
        raise TokenInvalido("email ausente")
    if not isinstance(nome, str) or not nome:
        raise TokenInvalido("nome ausente")
    return Identidade(sub=sub, nome=nome, email=email)


def _nao_autenticado() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="não autenticado",
        headers={"WWW-Authenticate": "Bearer"},
    )


def usuario_atual(
    request: Request,
    credenciais: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
    s: Annotated[Session, Depends(sessao)],
) -> UsuarioAtual:
    """Dependência FastAPI: valida o Bearer token e cria o usuário no primeiro acesso."""
    if credenciais is None:
        raise _nao_autenticado()

    validador: ValidadorToken = request.app.state.validador_token
    try:
        identidade = validador.validar(credenciais.credentials)
    except TokenInvalido as erro:
        logger.info("autenticação recusada (%s)", erro)
        raise _nao_autenticado() from None
    except EmissorIndisponivel as erro:
        logger.warning("autenticação: JWKS indisponível (%s)", type(erro.__cause__).__name__)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="autenticação indisponível",
        ) from None

    return usuarios_servico.obter_ou_criar(
        s, keycloak_sub=identidade.sub, nome=identidade.nome, email=identidade.email
    )
