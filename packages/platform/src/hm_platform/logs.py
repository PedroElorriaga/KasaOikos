"""Logs estruturados (spec platform/observability; design D8).

Tudo que é logado, pelo ``structlog`` ou pelo ``logging`` padrão (uvicorn, SQLAlchemy...),
passa pelos mesmos processadores e sai em JSON no stdout e, com a telemetria ligada,
via OTLP para o Loki. Cada linha traz o trace id do span ativo e, quando a requisição
já os resolveu, ``user_id`` e ``household_id`` (vinculados pela tenancy).
"""

import copy
import logging
import re
import sys
import time
from collections.abc import MutableMapping
from typing import IO, Any

import structlog
from opentelemetry import trace
from opentelemetry.instrumentation.logging.handler import LoggingHandler
from opentelemetry.sdk._logs import LoggerProvider
from opentelemetry.trace import format_span_id, format_trace_id
from structlog.typing import EventDict, Processor, WrappedLogger

from hm_platform.telemetry import ASGIApp, Message, Receive, Scope, Send

REDACTED = "[REDACTED]"
# Comparação sem diferenciar maiúsculas; chave exata ("status_code" não é "code").
SENSITIVE_KEYS = frozenset(
    {
        "authorization",
        "cookie",
        "set-cookie",
        "token",
        "access_token",
        "refresh_token",
        "id_token",
        "code",  # código de convite
        "password",
        "secret",
        "client_secret",
    }
)
# Um segredo no meio de um texto também é mascarado: mensagem de exceção, ou uma URL
# com query string (o access log do uvicorn e o log do httpx registram a URL inteira).
_SENSITIVE_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"eyJ[\w-]+\.[\w-]+\.[\w-]*"), REDACTED),  # JWT
    (re.compile(r"(?i)\bbearer\s+[^\s,;\"']+"), REDACTED),
    (
        re.compile(r"(?i)([?&](?:" + "|".join(sorted(SENSITIVE_KEYS)) + r")=)[^&\s\"'#]+"),
        rf"\g<1>{REDACTED}",
    ),
)

access_logger = structlog.get_logger("hm.access")


def _redact(value: Any, key: str | None = None) -> Any:
    if key is not None and key.lower() in SENSITIVE_KEYS:
        return REDACTED
    if isinstance(value, dict):
        return {k: _redact(v, str(k)) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return type(value)(_redact(v) for v in value)
    if isinstance(value, str):
        for pattern, replacement in _SENSITIVE_PATTERNS:
            value = pattern.sub(replacement, value)
    return value


def redact_sensitive(logger: WrappedLogger, method: str, event_dict: EventDict) -> EventDict:
    redacted: EventDict = _redact(dict(event_dict))
    return redacted


def add_trace_context(logger: WrappedLogger, method: str, event_dict: EventDict) -> EventDict:
    context = trace.get_current_span().get_span_context()
    if context.is_valid:
        event_dict.setdefault("trace_id", format_trace_id(context.trace_id))
        event_dict.setdefault("span_id", format_span_id(context.span_id))
    return event_dict


_SHARED: list[Processor] = [
    structlog.contextvars.merge_contextvars,
    structlog.stdlib.add_log_level,
    structlog.stdlib.add_logger_name,
    structlog.processors.TimeStamper(fmt="iso", utc=True),
    add_trace_context,
    structlog.processors.format_exc_info,
    # Por último: nada que um processador anterior acrescente escapa da redação.
    redact_sensitive,
]

# Handlers instalados por configure_logging: só eles são trocados numa reconfiguração
# (os do pytest e de outras bibliotecas ficam).
_installed: list[logging.Handler] = []


def configure_logging(
    level: str = "INFO",
    *,
    stream: IO[str] | None = None,
    logger_provider: LoggerProvider | None = None,
) -> None:
    structlog.configure(
        processors=[*_SHARED, structlog.stdlib.ProcessorFormatter.wrap_for_formatter],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=False,
    )
    formatter = structlog.stdlib.ProcessorFormatter(
        foreign_pre_chain=_SHARED,
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            structlog.processors.JSONRenderer(),
        ],
    )
    stdout = logging.StreamHandler(stream or sys.stdout)
    stdout.setFormatter(formatter)
    handlers: list[logging.Handler] = [stdout]
    if logger_provider is not None:
        otlp = LoggingHandler(logger_provider=logger_provider)
        otlp.addFilter(_RenderedCopy(formatter))
        handlers.append(otlp)

    root = logging.getLogger()
    for handler in _installed:
        root.removeHandler(handler)
    _installed.clear()
    for handler in handlers:
        root.addHandler(handler)
        _installed.append(handler)
    root.setLevel(level.upper())


class _RenderedCopy(logging.Filter):
    """Entrega ao handler do OTel uma cópia do registro já renderizada em JSON.

    O structlog anexa ao registro campos internos (``_logger``, um objeto) que o handler
    do OTel tentaria converter em atributos, com um warning por linha. A cópia leva o
    JSON como mensagem e não leva esses campos; o registro original segue intacto para
    os outros handlers. (Filtro que devolve um registro: Python 3.12+.)
    """

    def __init__(self, formatter: logging.Formatter) -> None:
        super().__init__()
        self._formatter = formatter

    def filter(self, record: logging.LogRecord) -> logging.LogRecord:
        rendered = copy.copy(record)
        rendered.msg = self._formatter.format(record)
        rendered.args = None
        rendered.exc_info = rendered.exc_text = None  # já estão no JSON
        for key in ("_logger", "_name", "_from_structlog"):
            rendered.__dict__.pop(key, None)
        return rendered


def bind_log_context(**values: object) -> None:
    """Campos que passam a constar em todas as linhas de log da requisição corrente."""
    structlog.contextvars.bind_contextvars(**values)


class AccessLogMiddleware:
    """Uma linha de log por requisição, com rota template, status e duração.

    Registra o caminho sem a query string: um ``?code=...`` não chega ao log. Fica por
    dentro do middleware do OTel, então a linha sai com o trace id da requisição.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        # Cada requisição começa com o contexto de log limpo.
        structlog.contextvars.clear_contextvars()
        started = time.perf_counter()
        response: MutableMapping[str, Any] = {"status": 500}

        async def send_and_capture(message: Message) -> None:
            if message["type"] == "http.response.start":
                response["status"] = message["status"]
            await send(message)

        try:
            await self.app(scope, receive, send_and_capture)
        finally:
            route = scope.get("route")
            access_logger.info(
                "request",
                method=scope["method"],
                route=getattr(route, "path", None),
                path=scope["path"],
                status=response["status"],
                duration_ms=round((time.perf_counter() - started) * 1000, 2),
            )
