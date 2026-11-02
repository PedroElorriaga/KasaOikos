"""OpenTelemetry (design D8): traces, métricas e logs via OTLP para o Collector.

Os providers são explícitos (passados a cada instrumentação), não os globais do OTel:
o global só pode ser definido uma vez por processo, e os testes criam várias apps. Em
produção, onde há uma app por processo, o entrypoint também os define como globais
(:meth:`Telemetry.set_global`).
"""

import os
import uuid
from collections.abc import Awaitable, Callable, MutableMapping
from dataclasses import dataclass, field
from typing import Any

import httpx
from fastapi import FastAPI
from opentelemetry import _logs, metrics, trace
from opentelemetry.exporter.otlp.proto.http._log_exporter import OTLPLogExporter
from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
from opentelemetry.instrumentation.redis import RedisInstrumentor
from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor
from opentelemetry.sdk._logs import LoggerProvider
from opentelemetry.sdk._logs.export import BatchLogRecordProcessor
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import MetricReader, PeriodicExportingMetricReader
from opentelemetry.sdk.metrics.view import View
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, SimpleSpanProcessor, SpanExporter
from opentelemetry.trace import format_trace_id
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncEngine

from hm_platform.settings import OTelSettings

# Convenções semânticas HTTP estáveis (http.server.request.duration em segundos, com
# http.route). Sem isso, a instrumentação usa as antigas, que rotulam por http.host e
# http.server_name: valores do header Host, controlados pelo cliente. É lido uma vez,
# na primeira instrumentação, por isso fica no import deste módulo.
os.environ.setdefault("OTEL_SEMCONV_STABILITY_OPT_IN", "http")

TRACE_ID_HEADER = "X-Trace-Id"
# Rótulos permitidos nas métricas HTTP do servidor (spec: método, rota template e status).
# Lista de permissão, não de bloqueio: um atributo novo numa versão futura da
# instrumentação não vira rótulo de alta cardinalidade sem alguém decidir.
HTTP_SERVER_METRIC_ATTRIBUTES = frozenset(
    {"http.request.method", "http.route", "http.response.status_code"}
)

type Scope = MutableMapping[str, Any]
type Message = MutableMapping[str, Any]
type Receive = Callable[[], Awaitable[Message]]
type Send = Callable[[Message], Awaitable[None]]
type ASGIApp = Callable[[Scope, Receive, Send], Awaitable[None]]


@dataclass
class Telemetry:
    tracer_provider: TracerProvider
    meter_provider: MeterProvider
    logger_provider: LoggerProvider | None = None
    _engines: list[AsyncEngine] = field(default_factory=list)

    def instrument_app(self, app: FastAPI) -> None:
        """Spans e métricas HTTP. Chame depois de registrar os middlewares da app."""
        app.add_middleware(TraceIdHeaderMiddleware)
        FastAPIInstrumentor.instrument_app(
            app,
            tracer_provider=self.tracer_provider,
            meter_provider=self.meter_provider,
            # Sem spans filhos para cada mensagem ASGI (receive/send): só ruído.
            exclude_spans=["receive", "send"],
        )

    def instrument_engine(self, engine: AsyncEngine) -> None:
        SQLAlchemyInstrumentor().instrument(
            engine=engine.sync_engine,
            tracer_provider=self.tracer_provider,
            meter_provider=self.meter_provider,
        )
        self._engines.append(engine)

    def instrument_redis(self, redis: Redis) -> None:
        RedisInstrumentor.instrument_client(redis, tracer_provider=self.tracer_provider)

    def instrument_http(self, http: httpx.AsyncClient) -> None:
        HTTPXClientInstrumentor.instrument_client(
            http, tracer_provider=self.tracer_provider, meter_provider=self.meter_provider
        )

    def set_global(self) -> None:
        """Para bibliotecas que usam a API global do OTel. Uma vez por processo."""
        trace.set_tracer_provider(self.tracer_provider)
        metrics.set_meter_provider(self.meter_provider)
        if self.logger_provider is not None:
            _logs.set_logger_provider(self.logger_provider)

    def shutdown(self) -> None:
        # O instrumentor do SQLAlchemy é um singleton por processo: desfazer permite
        # instrumentar o engine da próxima app (nos testes, várias por processo).
        if self._engines:
            SQLAlchemyInstrumentor().uninstrument()
            self._engines.clear()
        self.tracer_provider.shutdown()
        self.meter_provider.shutdown()
        if self.logger_provider is not None:
            self.logger_provider.shutdown()


def create_telemetry(
    settings: OTelSettings,
    *,
    span_exporter: SpanExporter | None = None,
    metric_reader: MetricReader | None = None,
) -> Telemetry:
    """``span_exporter``/``metric_reader`` substituem o OTLP (testes usam os de memória)."""
    resource = Resource.create(
        {
            "service.name": settings.service_name,
            "deployment.environment.name": settings.environment,
            # Um por processo: com N workers, as séries de cada worker não se misturam.
            "service.instance.id": str(uuid.uuid4()),
        }
    )
    endpoint = settings.exporter_endpoint.rstrip("/")

    tracer_provider = TracerProvider(resource=resource)
    if span_exporter is not None:
        tracer_provider.add_span_processor(SimpleSpanProcessor(span_exporter))
    elif settings.enabled:
        tracer_provider.add_span_processor(
            BatchSpanProcessor(OTLPSpanExporter(endpoint=f"{endpoint}/v1/traces"))
        )

    readers: list[MetricReader] = []
    if metric_reader is not None:
        readers.append(metric_reader)
    elif settings.enabled:
        readers.append(
            PeriodicExportingMetricReader(
                OTLPMetricExporter(endpoint=f"{endpoint}/v1/metrics"),
                export_interval_millis=settings.metric_export_interval_seconds * 1000,
            )
        )
    meter_provider = MeterProvider(
        resource=resource,
        metric_readers=readers,
        views=[
            View(instrument_name="http.server.*", attribute_keys=set(HTTP_SERVER_METRIC_ATTRIBUTES))
        ],
    )

    logger_provider = None
    if settings.enabled:
        logger_provider = LoggerProvider(resource=resource)
        logger_provider.add_log_record_processor(
            BatchLogRecordProcessor(OTLPLogExporter(endpoint=f"{endpoint}/v1/logs"))
        )

    return Telemetry(tracer_provider, meter_provider, logger_provider)


def current_trace_id() -> str | None:
    context = trace.get_current_span().get_span_context()
    return format_trace_id(context.trace_id) if context.is_valid else None


class TraceIdHeaderMiddleware:
    """Acrescenta ``X-Trace-Id`` a toda resposta (spec: "Rastreamento distribuído").

    Fica por dentro do middleware do OTel, então o span da requisição já está ativo
    quando a resposta começa a ser enviada.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_with_trace_id(message: Message) -> None:
            if message["type"] == "http.response.start" and (trace_id := current_trace_id()):
                headers = list(message.get("headers", []))
                headers.append((TRACE_ID_HEADER.lower().encode(), trace_id.encode()))
                message["headers"] = headers
            await send(message)

        await self.app(scope, receive, send_with_trace_id)
