"""Respostas de erro no formato Problem Details (RFC 9457).

Todo erro da API sai como ``application/problem+json``: os ``HTTPException`` das rotas e
dependencies, as falhas de validação (422) e as exceções inesperadas (500). Os campos
são os da RFC (``type``, ``title``, ``status``, ``detail``, ``instance``) mais duas
extensões: ``trace_id``, para o cliente citar ao reportar um erro, e ``errors``, a
lista de campos inválidos de um 422.
"""

from collections.abc import Mapping, Sequence
from http import HTTPStatus
from typing import Any

import structlog
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from opentelemetry import trace
from opentelemetry.trace import Status, StatusCode
from pydantic import BaseModel
from starlette.exceptions import HTTPException as StarletteHTTPException

from hm_platform.telemetry import ASGIApp, Message, Receive, Scope, Send, current_trace_id

PROBLEM_JSON = "application/problem+json"

logger = structlog.get_logger("hm.errors")


class InvalidParam(BaseModel):
    loc: list[str | int]
    msg: str
    type: str


class Problem(BaseModel):
    type: str = "about:blank"
    title: str
    status: int
    detail: str | None = None
    instance: str | None = None
    trace_id: str | None = None
    errors: list[InvalidParam] | None = None


# Para o ``include_router(..., responses=...)``: documenta no OpenAPI que qualquer
# status não declarado pela rota responde um Problem. Com "default", o FastAPI também
# deixa de anunciar o seu 422 próprio (HTTPValidationError), que não é o que sai.
PROBLEM_RESPONSES: dict[int | str, dict[str, Any]] = {
    "default": {"model": Problem, "description": "Erro (Problem Details, RFC 9457)"}
}


def problem_response(
    request: Request,
    status: int,
    detail: str | None = None,
    *,
    headers: Mapping[str, str] | None = None,
    errors: Sequence[InvalidParam] | None = None,
) -> JSONResponse:
    problem = Problem(
        title=HTTPStatus(status).phrase,
        status=status,
        detail=detail,
        # Só o caminho: a query string pode trazer segredos (?code=...).
        instance=request.url.path,
        trace_id=current_trace_id(),
        errors=list(errors) if errors is not None else None,
    )
    return JSONResponse(
        problem.model_dump(exclude_none=True),
        status_code=status,
        headers=headers,
        media_type=PROBLEM_JSON,
    )


async def _http_exception(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    # Um detail que só repete a frase do status (404 de rota inexistente) não acrescenta nada.
    detail = exc.detail if exc.detail != HTTPStatus(exc.status_code).phrase else None
    return problem_response(request, exc.status_code, detail, headers=exc.headers)


async def _validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
    # Sem o campo "input" do pydantic: ecoaria o valor enviado, que pode ser um segredo.
    errors = [InvalidParam(loc=list(e["loc"]), msg=e["msg"], type=e["type"]) for e in exc.errors()]
    return problem_response(request, 422, "request validation failed", errors=errors)


class UnhandledErrorMiddleware:
    """Converte uma exceção inesperada num 500 Problem, sem detalhes internos.

    Precisa ficar por dentro dos middlewares de telemetria: o span da requisição ainda
    está ativo, então a exceção fica registrada nele, o log de erro sai com o trace id e
    a resposta leva ``X-Trace-Id``. O handler de ``Exception`` do Starlette não serve:
    roda no ``ServerErrorMiddleware``, por fora de todos os middlewares da app.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        started = False

        async def track_start(message: Message) -> None:
            nonlocal started
            started = started or message["type"] == "http.response.start"
            await send(message)

        try:
            await self.app(scope, receive, track_start)
        except Exception as exc:
            span = trace.get_current_span()
            span.record_exception(exc)
            span.set_status(Status(StatusCode.ERROR, type(exc).__name__))
            logger.exception("unhandled error")
            if started:  # a resposta já começou: não dá para trocá-la por um 500
                raise
            response = problem_response(Request(scope), 500)
            await response(scope, receive, send)


def install_error_handlers(app: FastAPI) -> None:
    """Chame antes de ``Telemetry.instrument_app`` (ver UnhandledErrorMiddleware)."""
    # Substituem os handlers padrão do FastAPI, que respondem {"detail": ...}.
    app.exception_handlers[StarletteHTTPException] = _http_exception
    app.exception_handlers[RequestValidationError] = _validation_error
    app.add_middleware(UnhandledErrorMiddleware)

    # Com ``model``, o FastAPI documenta a resposta como application/json; aqui ela
    # passa a ser application/problem+json, o tipo que a API de fato envia.
    build_openapi = app.openapi

    def openapi() -> dict[str, Any]:
        schema = app.openapi_schema
        if schema is None:
            schema = build_openapi()  # gera e guarda em app.openapi_schema
            for operations in schema["paths"].values():
                for operation in operations.values():
                    default = operation.get("responses", {}).get("default", {})
                    if "application/json" in default.get("content", {}):
                        default["content"] = {PROBLEM_JSON: default["content"]["application/json"]}
        return schema

    app.openapi = openapi  # type: ignore[method-assign]
