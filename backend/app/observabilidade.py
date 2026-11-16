"""Observabilidade: logs JSON correlacionados ao trace e OpenTelemetry (FastAPI + SQLAlchemy).

Logs nunca levam dados pessoais (e-mail, telefone, Pix), token nem claims. O formatador só grava
campos conhecidos: o que vier em `extra` fora de `_CAMPOS_EXTRAS` é descartado.
"""

import json
import logging
import sys
import time
import traceback
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any

from fastapi import FastAPI, Request, Response
from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor
from opentelemetry.sdk.resources import SERVICE_NAME, Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

from app.config import Settings

NOME_SERVICO = "kasaoikos-api"

# Campos aceitos em `extra`, além dos fixos. Nenhum deles pode conter dado pessoal.
_CAMPOS_EXTRAS = ("metodo", "caminho", "status", "duracao_ms")

_logger_acesso = logging.getLogger("app.acesso")


class FormatadorJson(logging.Formatter):
    """Uma linha JSON por registro, com `trace_id`/`span_id` do span ativo (ou null)."""

    def format(self, record: logging.LogRecord) -> str:
        contexto = trace.get_current_span().get_span_context()
        dados: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, UTC).isoformat(
                timespec="milliseconds"
            ),
            "nivel": record.levelname,
            "logger": record.name,
            "mensagem": record.getMessage(),
            "trace_id": format(contexto.trace_id, "032x") if contexto.is_valid else None,
            "span_id": format(contexto.span_id, "016x") if contexto.is_valid else None,
        }
        for campo in _CAMPOS_EXTRAS:
            if hasattr(record, campo):
                dados[campo] = getattr(record, campo)
        if record.exc_info and record.exc_info[0] is not None:
            # Tipo e pilha, sem a mensagem: a do driver do banco traz host e usuário.
            dados["excecao"] = record.exc_info[0].__name__
            dados["pilha"] = "".join(traceback.format_tb(record.exc_info[2]))
        # ASCII escapado: a linha fica válida em qualquer encoding do stdout (cp1252 no Windows).
        return json.dumps(dados)


class _HandlerJson(logging.StreamHandler):  # type: ignore[type-arg]
    """Marca o handler instalado por `configurar_logs`, para não duplicar."""


def configurar_logs() -> None:
    """Logs da API e do uvicorn em JSON no stdout. Idempotente.

    Chamada no `create_app`, depois que o uvicorn já montou os próprios handlers.
    """
    raiz = logging.getLogger()
    if not any(isinstance(h, _HandlerJson) for h in raiz.handlers):
        handler = _HandlerJson(sys.stdout)
        handler.setFormatter(FormatadorJson())
        raiz.addHandler(handler)
    # INFO só para o código do app; bibliotecas ficam no padrão (WARNING).
    logging.getLogger("app").setLevel(logging.INFO)

    # Logs do uvicorn (subida, erros) passam pelo handler JSON da raiz.
    uvicorn = logging.getLogger("uvicorn")
    uvicorn.handlers.clear()
    uvicorn.propagate = True
    # O log de acesso do uvicorn traz o IP do cliente e a query string, e roda fora do span.
    # Quem registra o acesso é o middleware de `registrar_log_de_acesso`.
    logging.getLogger("uvicorn.access").disabled = True


def registrar_log_de_acesso(app: FastAPI) -> None:
    """Uma linha por requisição: método, caminho (sem query), status e duração. Sem IP."""

    @app.middleware("http")
    async def log_de_acesso(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        inicio = time.perf_counter()
        status = 500
        try:
            resposta = await call_next(request)
            status = resposta.status_code
            return resposta
        finally:
            _logger_acesso.info(
                "requisição",
                extra={
                    "metodo": request.method,
                    "caminho": request.url.path,
                    "status": status,
                    "duracao_ms": round((time.perf_counter() - inicio) * 1000, 1),
                },
            )


_tracing_configurado = False


def configurar_tracing(settings: Settings) -> None:
    """TracerProvider global e instrumentação do SQLAlchemy. Uma vez por processo.

    Precisa rodar antes de criar o engine: a instrumentação do SQLAlchemy envolve o
    `create_engine` (e só pode ser ligada uma vez por processo). Sem endpoint OTLP, os spans
    são criados mas não exportados (testes e CI).
    """
    global _tracing_configurado
    if _tracing_configurado:
        return
    provider = TracerProvider(resource=Resource.create({SERVICE_NAME: NOME_SERVICO}))
    if settings.otel_exporter_otlp_endpoint:
        endpoint = f"{settings.otel_exporter_otlp_endpoint.rstrip('/')}/v1/traces"
        provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=endpoint)))
    trace.set_tracer_provider(provider)
    SQLAlchemyInstrumentor().instrument()
    _tracing_configurado = True


def instrumentar_app(app: FastAPI) -> None:
    """Um span por requisição. Headers não são capturados (o Authorization fica de fora).

    Sem os spans internos de cada `receive`/`send` do ASGI: só poluem o trace.
    """
    FastAPIInstrumentor.instrument_app(app, exclude_spans=["receive", "send"])
