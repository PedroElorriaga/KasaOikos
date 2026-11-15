import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr, ValidationError

from app.config import Settings
from tests.integracao.apoio import ORIGEM_FRONT

OUTRA_ORIGEM = "https://site-malicioso.example"


def _preflight(cliente: TestClient, origem: str) -> dict[str, str]:
    resposta = cliente.options(
        "/me",
        headers={
            "Origin": origem,
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "authorization",
        },
    )
    return {"status": str(resposta.status_code), **resposta.headers}


def test_quando_preflight_vem_da_origem_do_front_entao_libera_so_essa_origem(
    cliente: TestClient,
) -> None:
    resposta = _preflight(cliente, ORIGEM_FRONT)

    assert resposta["status"] == "200"
    assert resposta["access-control-allow-origin"] == ORIGEM_FRONT
    assert "authorization" in resposta["access-control-allow-headers"].lower()
    # Sem cookies: o navegador não deve enviar credenciais em requisições cross-origin.
    assert "access-control-allow-credentials" not in resposta


def test_quando_preflight_vem_de_outra_origem_entao_nao_libera(cliente: TestClient) -> None:
    resposta = _preflight(cliente, OUTRA_ORIGEM)

    assert resposta["status"] == "400"
    assert "access-control-allow-origin" not in resposta


def test_quando_get_vem_de_outra_origem_entao_resposta_nao_tem_header_de_cors(
    cliente: TestClient,
) -> None:
    liberada = cliente.get("/health", headers={"Origin": ORIGEM_FRONT})
    bloqueada = cliente.get("/health", headers={"Origin": OUTRA_ORIGEM})

    assert liberada.headers["access-control-allow-origin"] == ORIGEM_FRONT
    assert "access-control-allow-origin" not in bloqueada.headers


_BANCO = SecretStr("postgresql+psycopg://teste@localhost/teste")
_EMISSOR = "http://localhost/realms/teste"


def _settings(cors_origins: list[str] | None = None) -> Settings:
    if cors_origins is None:
        # Sem passar o campo: vale o padrão da Settings.
        return Settings(
            _env_file=None, database_url=_BANCO, oidc_issuer=_EMISSOR, oidc_audience="teste"
        )
    return Settings(
        _env_file=None,
        database_url=_BANCO,
        oidc_issuer=_EMISSOR,
        oidc_audience="teste",
        cors_origins=cors_origins,
    )


@pytest.mark.parametrize(
    "origem",
    [
        "*",
        "http://*.kasaoikos.dev",
        "http://localhost:5173/",
        "http://localhost:5173/app",
        "localhost:5173",
        "ftp://localhost",
        "http://usuario:senha@localhost:5173",
    ],
)
def test_quando_origem_de_cors_nao_e_exata_entao_configuracao_e_recusada(origem: str) -> None:
    with pytest.raises(ValidationError):
        _settings(cors_origins=[origem])


def test_quando_origens_de_cors_sao_exatas_entao_configuracao_e_aceita() -> None:
    origens = ["http://localhost:5173", "https://staging.kasaoikos.dev"]

    assert _settings(cors_origins=origens).cors_origins == origens


def test_quando_cors_nao_e_configurado_entao_nenhuma_origem_e_liberada() -> None:
    assert _settings().cors_origins == []
