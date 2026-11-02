"""Tarefa 7.1: erros no formato Problem Details (RFC 9457) e o OpenAPI da app composta."""

import httpx
from fastapi import FastAPI
from openapi_spec_validator import validate
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import StatusCode

from hm_platform.errors import PROBLEM_JSON
from hm_platform.telemetry import TRACE_ID_HEADER
from hm_platform.testing.routes import iter_routes
from hm_platform.testing.tokens import TokenFactory


def assert_problem(response: httpx.Response, status: int, title: str) -> dict[str, object]:
    assert response.status_code == status
    assert response.headers["content-type"] == PROBLEM_JSON
    body: dict[str, object] = response.json()
    assert (body["type"], body["title"], body["status"]) == ("about:blank", title, status)
    assert body["instance"] == response.request.url.path
    # O cliente cita o trace_id ao reportar o erro; é o mesmo do header.
    assert body["trace_id"] == response.headers[TRACE_ID_HEADER]
    return body


async def test_http_exception_keeps_detail_and_headers(client: httpx.AsyncClient) -> None:
    response = await client.get("/me")

    body = assert_problem(response, 401, "Unauthorized")
    assert body["detail"] == "missing bearer token"
    assert response.headers["www-authenticate"] == "Bearer"


async def test_unknown_route_is_a_problem_without_redundant_detail(
    client: httpx.AsyncClient,
) -> None:
    response = await client.get("/nope", params={"code": "segredo"})

    body = assert_problem(response, 404, "Not Found")
    assert "detail" not in body
    assert body["instance"] == "/nope"  # sem a query string
    assert "segredo" not in response.text


async def test_validation_error_lists_fields_without_echoing_input(
    client: httpx.AsyncClient, token_factory: TokenFactory
) -> None:
    headers = {"Authorization": f"Bearer {token_factory.valid(sub='kc-errors')}"}
    sent = "segredo-" + "x" * 100  # acima do limite de 80 caracteres

    response = await client.post("/households", headers=headers, json={"name": sent})

    body = assert_problem(response, 422, "Unprocessable Content")
    assert body["errors"] == [
        {
            "loc": ["body", "name"],
            "msg": "String should have at most 80 characters",
            "type": "string_too_long",
        }
    ]
    assert "segredo" not in response.text


async def test_unexpected_exception_is_a_500_without_internals(
    app: FastAPI, client: httpx.AsyncClient, span_exporter: InMemorySpanExporter
) -> None:
    @app.get("/_test/boom")
    async def boom() -> None:
        raise RuntimeError("connection string postgres://hm_app:senha@db")

    response = await client.get("/_test/boom")

    body = assert_problem(response, 500, "Internal Server Error")
    assert "detail" not in body
    assert "senha" not in response.text
    # A exceção fica registrada no span da requisição, que é marcado como erro.
    (server,) = [s for s in span_exporter.get_finished_spans() if s.name == "GET /_test/boom"]
    assert server.status.status_code is StatusCode.ERROR
    assert [e.attributes["exception.type"] for e in server.events if e.attributes] == [
        "RuntimeError"
    ]


async def test_openapi_is_valid_and_documents_every_route(
    app: FastAPI, client: httpx.AsyncClient
) -> None:
    schema = (await client.get("/openapi.json")).json()
    validate(schema)

    documented = {(path, method.upper()) for path, ops in schema["paths"].items() for method in ops}
    routes = {
        (path, method)
        for path, route, _ in iter_routes(app.routes)
        if route.include_in_schema
        for method in route.methods or ()
    }
    assert ("/households", "POST") in routes  # a descoberta enxerga os routers dos módulos
    assert routes == documented

    # Rotas dos módulos documentam o erro como Problem, e o 422 padrão do FastAPI some.
    default = schema["paths"]["/households"]["post"]["responses"]["default"]
    assert default["content"] == {
        PROBLEM_JSON: {"schema": {"$ref": "#/components/schemas/Problem"}}
    }
    assert "HTTPValidationError" not in schema["components"]["schemas"]

    assert (await client.get("/docs")).status_code == 200
