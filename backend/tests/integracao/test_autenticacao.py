"""Autenticação (M0.5): GET /me com tokens assinados por uma chave de teste."""

import logging
import socket
import threading
import time
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor

import httpx2 as httpx
import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient
from sqlalchemy import Engine, create_engine, text
from testcontainers.community.postgres import PostgresContainer

from tests.integracao.apoio import cliente_para
from tests.integracao.tokens import (
    assinar,
    claims_validos,
    forjar_hs256,
    gerar_chave,
)


@pytest.fixture(scope="module")
def banco(postgres: PostgresContainer) -> Iterator[Engine]:
    engine = create_engine(postgres.get_connection_url())
    yield engine
    engine.dispose()


def _me(cliente: TestClient, token: str | None = None) -> httpx.Response:
    headers = {"Authorization": f"Bearer {token}"} if token is not None else {}
    return cliente.get("/me", headers=headers)


def _linhas_do_sub(banco: Engine, sub: str) -> int:
    with banco.connect() as conexao:
        return int(
            conexao.execute(
                text("SELECT count(*) FROM usuarios WHERE keycloak_sub = :sub"), {"sub": sub}
            ).scalar_one()
        )


def _assert_401(resposta: httpx.Response) -> None:
    assert resposta.status_code == 401
    assert resposta.headers["WWW-Authenticate"] == "Bearer"
    assert resposta.json() == {"detail": "não autenticado"}


# --- Tokens recusados ---


def test_sem_token_responde_401(cliente: TestClient) -> None:
    _assert_401(_me(cliente))


def test_esquema_diferente_de_bearer_responde_401(cliente: TestClient) -> None:
    _assert_401(cliente.get("/me", headers={"Authorization": "Basic dXNlcjpzZW5oYQ=="}))


def test_token_malformado_responde_401(cliente: TestClient) -> None:
    _assert_401(_me(cliente, "isto-nao-e-um-jwt"))


def test_token_expirado_responde_401(cliente: TestClient, chave_teste: rsa.RSAPrivateKey) -> None:
    agora = int(time.time())
    token = assinar(claims_validos(iat=agora - 600, exp=agora - 60), chave_teste)

    _assert_401(_me(cliente, token))


def test_aud_errado_responde_401(cliente: TestClient, chave_teste: rsa.RSAPrivateKey) -> None:
    token = assinar(claims_validos(aud="outra-api"), chave_teste)

    _assert_401(_me(cliente, token))


def test_iss_errado_responde_401(cliente: TestClient, chave_teste: rsa.RSAPrivateKey) -> None:
    token = assinar(claims_validos(iss="http://outro-emissor/realms/kasaoikos"), chave_teste)

    _assert_401(_me(cliente, token))


def test_assinatura_de_outra_chave_responde_401(cliente: TestClient) -> None:
    # Mesmo `kid` da chave de teste, mas assinado por uma chave que não está no JWKS.
    token = assinar(claims_validos(), gerar_chave())

    _assert_401(_me(cliente, token))


def test_kid_desconhecido_responde_401(cliente: TestClient, chave_teste: rsa.RSAPrivateKey) -> None:
    token = assinar(claims_validos(), chave_teste, kid="kid-que-nao-existe")

    _assert_401(_me(cliente, token))


def test_algoritmo_none_responde_401(cliente: TestClient) -> None:
    # O PyJWT aceita chave vazia com `none`; o token sai sem assinatura.
    token = jwt.encode(claims_validos(), "", algorithm="none", headers={"kid": "chave-teste-1"})

    _assert_401(_me(cliente, token))


def test_hs256_com_chave_publica_como_segredo_responde_401(
    cliente: TestClient, chave_teste: rsa.RSAPrivateKey
) -> None:
    # Ataque de confusão de algoritmo: a chave pública (conhecida) usada como segredo HMAC.
    publica_pem = chave_teste.public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
    )
    token = forjar_hs256(claims_validos(), publica_pem)

    _assert_401(_me(cliente, token))


@pytest.mark.parametrize("claim", ["exp", "iat", "sub", "email"])
def test_claim_obrigatorio_ausente_responde_401(
    cliente: TestClient, chave_teste: rsa.RSAPrivateKey, claim: str
) -> None:
    token = assinar(claims_validos(**{claim: None}), chave_teste)

    _assert_401(_me(cliente, token))


def test_tokens_recusados_nao_criam_usuario(
    cliente: TestClient, chave_teste: rsa.RSAPrivateKey, banco: Engine
) -> None:
    claims = claims_validos(aud="outra-api")

    _assert_401(_me(cliente, assinar(claims, chave_teste)))

    assert _linhas_do_sub(banco, claims["sub"]) == 0


# --- Token válido ---


def test_token_valido_no_primeiro_acesso_responde_200_e_cria_um_usuario(
    cliente: TestClient, chave_teste: rsa.RSAPrivateKey, banco: Engine
) -> None:
    claims = claims_validos()
    token = assinar(claims, chave_teste)

    resposta = _me(cliente, token)

    assert resposta.status_code == 200
    corpo = resposta.json()
    assert set(corpo) == {"id", "nome", "email"}
    assert corpo["nome"] == "Ana Teste"
    assert corpo["email"] == claims["email"]
    assert _linhas_do_sub(banco, claims["sub"]) == 1

    # Segundo acesso: mesmo usuário, nenhuma linha nova.
    segunda = _me(cliente, token)
    assert segunda.status_code == 200
    assert segunda.json()["id"] == corpo["id"]
    assert _linhas_do_sub(banco, claims["sub"]) == 1


def test_sem_claim_name_usa_preferred_username(
    cliente: TestClient, chave_teste: rsa.RSAPrivateKey
) -> None:
    token = assinar(claims_validos(name=None), chave_teste)

    resposta = _me(cliente, token)

    assert resposta.status_code == 200
    assert resposta.json()["nome"] == "ana.teste"


def test_dois_primeiros_acessos_simultaneos_criam_uma_linha(
    cliente: TestClient, chave_teste: rsa.RSAPrivateKey, banco: Engine
) -> None:
    claims = claims_validos()
    token = assinar(claims, chave_teste)
    largada = threading.Barrier(2)

    def acessar() -> httpx.Response:
        largada.wait()
        return _me(cliente, token)

    with ThreadPoolExecutor(max_workers=2) as executor:
        respostas = list(executor.map(lambda _: acessar(), range(2)))

    assert [r.status_code for r in respostas] == [200, 200]
    assert respostas[0].json() == respostas[1].json()
    assert _linhas_do_sub(banco, claims["sub"]) == 1


# --- Logs e indisponibilidade ---


def test_logs_nao_incluem_token_nem_email(
    cliente: TestClient, chave_teste: rsa.RSAPrivateKey, caplog: pytest.LogCaptureFixture
) -> None:
    valido = claims_validos()
    agora = int(time.time())
    expirado = claims_validos(iat=agora - 600, exp=agora - 60)
    tokens = [assinar(valido, chave_teste), assinar(expirado, chave_teste)]

    with caplog.at_level(logging.DEBUG):
        assert _me(cliente, tokens[0]).status_code == 200
        assert _me(cliente, tokens[1]).status_code == 401

    assert "autenticação recusada (ExpiredSignatureError)" in caplog.text
    for sensivel in [*tokens, valido["email"], expirado["email"]]:
        assert sensivel not in caplog.text
    # Nem pedaços do token (cabeçalho e corpo em base64).
    for token in tokens:
        for parte in token.split("."):
            assert parte not in caplog.text


def _porta_fechada() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        porta: int = s.getsockname()[1]
    return porta


def test_jwks_indisponivel_responde_503(
    postgres: PostgresContainer, chave_teste: rsa.RSAPrivateKey
) -> None:
    jwks_fora = f"http://127.0.0.1:{_porta_fechada()}/certs"
    token = assinar(claims_validos(), chave_teste)

    with cliente_para(postgres, jwks_url=jwks_fora) as cliente:
        resposta = _me(cliente, token)

    assert resposta.status_code == 503
    assert resposta.json() == {"detail": "autenticação indisponível"}
