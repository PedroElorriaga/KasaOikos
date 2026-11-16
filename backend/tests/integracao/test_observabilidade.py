"""Observabilidade (M0.8): traces de rota + banco e logs JSON com trace_id, sem dados pessoais."""

import io
import json
import logging
from collections.abc import Iterator
from typing import Any

import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient
from opentelemetry import trace
from opentelemetry.sdk.trace import ReadableSpan, TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import SpanKind

from app.observabilidade import FormatadorJson, _HandlerJson
from tests.integracao.tokens import assinar, claims_validos

_exportador = InMemorySpanExporter()
_exportador_ligado = False


@pytest.fixture
def spans(cliente: TestClient) -> Iterator[InMemorySpanExporter]:
    """Spans exportados durante o teste. O provider global é criado pelo `create_app`."""
    global _exportador_ligado
    provider = trace.get_tracer_provider()
    assert isinstance(provider, TracerProvider)
    if not _exportador_ligado:
        provider.add_span_processor(SimpleSpanProcessor(_exportador))
        _exportador_ligado = True
    _exportador.clear()
    yield _exportador
    _exportador.clear()


@pytest.fixture
def logs(cliente: TestClient) -> Iterator[io.StringIO]:
    """Linhas de log formatadas em JSON durante o teste, como sairiam no stdout."""
    buffer = io.StringIO()
    handler = logging.StreamHandler(buffer)
    handler.setFormatter(FormatadorJson())
    raiz = logging.getLogger()
    raiz.addHandler(handler)
    yield buffer
    raiz.removeHandler(handler)


def _linhas(buffer: io.StringIO) -> list[dict[str, Any]]:
    return [json.loads(linha) for linha in buffer.getvalue().splitlines()]


def _span_servidor(spans: InMemorySpanExporter) -> ReadableSpan:
    servidor = [s for s in spans.get_finished_spans() if s.kind == SpanKind.SERVER]
    assert len(servidor) == 1
    return servidor[0]


def _hex(trace_id: int) -> str:
    return format(trace_id, "032x")


def test_me_gera_trace_com_span_do_banco(
    cliente: TestClient, spans: InMemorySpanExporter, chave_teste: rsa.RSAPrivateKey
) -> None:
    token = assinar(claims_validos(), chave_teste)

    resposta = cliente.get("/me", headers={"Authorization": f"Bearer {token}"})

    assert resposta.status_code == 200
    servidor = _span_servidor(spans)
    assert servidor.attributes is not None
    assert servidor.attributes.get("http.route") == "/me"
    trace_id = servidor.context.trace_id
    banco = [
        s
        for s in spans.get_finished_spans()
        if s.kind == SpanKind.CLIENT
        and s.attributes is not None
        and "postgresql" in (s.attributes.get("db.system"), s.attributes.get("db.system.name"))
    ]
    assert banco, "nenhum span do banco"
    assert all(s.context.trace_id == trace_id for s in banco)


def test_span_nao_leva_token_nem_email(
    cliente: TestClient, spans: InMemorySpanExporter, chave_teste: rsa.RSAPrivateKey
) -> None:
    claims = claims_validos()
    token = assinar(claims, chave_teste)

    cliente.get("/me", headers={"Authorization": f"Bearer {token}"})

    for span in spans.get_finished_spans():
        texto = json.dumps({k: str(v) for k, v in (span.attributes or {}).items()})
        assert token not in texto
        assert claims["email"] not in texto


def test_log_de_acesso_em_json_com_trace_id(
    cliente: TestClient,
    spans: InMemorySpanExporter,
    logs: io.StringIO,
    chave_teste: rsa.RSAPrivateKey,
) -> None:
    token = assinar(claims_validos(), chave_teste)

    cliente.get("/me?x=1", headers={"Authorization": f"Bearer {token}"})

    acessos = [linha for linha in _linhas(logs) if linha["logger"] == "app.acesso"]
    assert len(acessos) == 1
    acesso = acessos[0]
    assert acesso["metodo"] == "GET"
    assert acesso["caminho"] == "/me"  # sem a query string
    assert acesso["status"] == 200
    assert isinstance(acesso["duracao_ms"], float)
    assert acesso["trace_id"] == _hex(_span_servidor(spans).context.trace_id)


def test_log_de_token_recusado_tem_trace_id_e_nao_tem_dados_pessoais(
    cliente: TestClient,
    spans: InMemorySpanExporter,
    logs: io.StringIO,
    chave_teste: rsa.RSAPrivateKey,
) -> None:
    claims = claims_validos(exp=1)
    token = assinar(claims, chave_teste)

    resposta = cliente.get("/me", headers={"Authorization": f"Bearer {token}"})

    assert resposta.status_code == 401
    linhas = _linhas(logs)
    recusa = [linha for linha in linhas if linha["logger"] == "app.autenticacao"]
    assert len(recusa) == 1
    assert recusa[0]["trace_id"] == _hex(_span_servidor(spans).context.trace_id)
    texto = logs.getvalue()
    for dado in (token, claims["email"], claims["sub"], claims["name"]):
        assert dado not in texto


def test_extra_desconhecido_nao_vai_para_o_log(logs: io.StringIO) -> None:
    logging.getLogger("app.teste").info("evento", extra={"email": "ana@example.com"})

    (linha,) = _linhas(logs)
    assert linha["mensagem"] == "evento"
    assert "email" not in linha
    assert linha["trace_id"] is None  # fora de requisição


def test_excecao_registra_tipo_e_pilha_sem_mensagem(logs: io.StringIO) -> None:
    # Em linha separada: a pilha mostra só a linha do `raise`, não a mensagem montada em runtime.
    mensagem = "senha=segredo@host"
    try:
        raise ValueError(mensagem)
    except ValueError:
        logging.getLogger("app.teste").exception("falhou")

    (linha,) = _linhas(logs)
    assert linha["excecao"] == "ValueError"
    assert "test_excecao_registra_tipo_e_pilha_sem_mensagem" in linha["pilha"]
    assert "segredo" not in json.dumps(linha)


def test_create_app_instala_um_unico_handler_json(cliente: TestClient) -> None:
    handlers = [h for h in logging.getLogger().handlers if isinstance(h, _HandlerJson)]
    assert len(handlers) == 1
    assert isinstance(handlers[0].formatter, FormatadorJson)
