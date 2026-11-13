import logging

import pytest
from fastapi.testclient import TestClient
from testcontainers.community.postgres import PostgresContainer

from tests.integracao.apoio import cliente_para


def test_quando_banco_no_ar_entao_health_responde_200(cliente: TestClient) -> None:
    resposta = cliente.get("/health")

    assert resposta.status_code == 200
    assert resposta.json() == {"status": "ok"}


def test_quando_banco_fora_entao_health_responde_503_sem_expor_detalhes(
    postgres_descartavel: PostgresContainer, caplog: pytest.LogCaptureFixture
) -> None:
    pg = postgres_descartavel
    # Coletados antes de derrubar: depois do stop o container perde o mapeamento de porta.
    host = pg.get_container_host_ip()
    porta = str(pg.get_exposed_port(pg.port))

    with cliente_para(pg) as cliente:
        # Primeiro com o banco no ar, para o pool já ter conexão aberta.
        assert cliente.get("/health").status_code == 200

        # Derruba o banco (docker stop); a fixture remove o container no fim.
        pg.get_wrapped_container().stop()

        with caplog.at_level(logging.WARNING):
            resposta = cliente.get("/health")

    assert resposta.status_code == 503
    assert resposta.json() == {"status": "indisponivel"}
    for detalhe in [host, porta, pg.username, pg.password, "psycopg", "OperationalError"]:
        assert detalhe not in resposta.text

    # O log registra a falha, mas sem host, porta, usuário ou senha do banco.
    assert "banco indisponível" in caplog.text
    for detalhe in [host, porta, pg.username, pg.password]:
        assert detalhe not in caplog.text
