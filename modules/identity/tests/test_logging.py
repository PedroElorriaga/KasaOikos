"""Spec platform/observability, requirement "Logs estruturados e correlacionados" (6.4)."""

import io
import json
import logging
from collections.abc import Callable, Iterator

import httpx
import pytest
import structlog
from fastapi import FastAPI
from opentelemetry.sdk._logs import LoggerProvider
from opentelemetry.sdk._logs.export import InMemoryLogRecordExporter, SimpleLogRecordProcessor

from hm_platform.logs import REDACTED, configure_logging
from hm_platform.testing.tokens import TokenFactory

from .conftest import World, auth

type LogLines = Callable[[], list[dict[str, object]]]


@pytest.fixture
def log_lines(app: FastAPI) -> Iterator[LogLines]:
    """Redireciona os logs (já configurados pela app) para um buffer e os devolve parseados."""
    buffer = io.StringIO()
    configure_logging("INFO", stream=buffer)

    def lines() -> list[dict[str, object]]:
        return [json.loads(line) for line in buffer.getvalue().splitlines() if line.strip()]

    yield lines
    configure_logging("INFO")


def access(lines: list[dict[str, object]]) -> list[dict[str, object]]:
    return [line for line in lines if line.get("event") == "request"]


# --- Cenário: Correlação entre log e trace -----------------------------------------------


async def test_log_line_carries_trace_user_and_household(
    client: httpx.AsyncClient, token_factory: TokenFactory, world: World, log_lines: LogLines
) -> None:
    response = await client.get(
        f"/households/{world.household_a}", headers=auth(token_factory, "alice")
    )

    [line] = access(log_lines())
    assert line["trace_id"] == response.headers["X-Trace-Id"]
    assert line["user_id"] == str(world.alice)
    assert line["household_id"] == str(world.household_a)
    assert (line["level"], line["route"], line["status"]) == (
        "info",
        "/households/{household_id}",
        200,
    )
    assert "timestamp" in line


async def test_context_of_one_request_does_not_leak_into_the_next(
    client: httpx.AsyncClient, token_factory: TokenFactory, world: World, log_lines: LogLines
) -> None:
    await client.get(f"/households/{world.household_a}", headers=auth(token_factory, "alice"))
    await client.get("/health/live")

    first, second = access(log_lines())
    assert "user_id" in first
    assert "user_id" not in second
    assert "household_id" not in second
    assert first["trace_id"] != second["trace_id"]


# --- Cenário: Dados sensíveis ------------------------------------------------------------


async def test_invite_acceptance_logs_neither_token_nor_code(
    client: httpx.AsyncClient, token_factory: TokenFactory, world: World, log_lines: LogLines
) -> None:
    invite = await client.post(
        f"/households/{world.household_a}/invites", headers=auth(token_factory, "alice"), json={}
    )
    code = invite.json()["code"]
    headers = auth(token_factory, "dave")
    token = headers["Authorization"].removeprefix("Bearer ")

    accepted = await client.post("/invites/accept", headers=headers, json={"code": code})
    # Código na query string de uma rota inexistente: o access log grava só o caminho.
    await client.get(f"/invites/accept?code={code}", headers=headers)

    assert accepted.status_code == 200
    output = json.dumps(log_lines())
    assert code not in output
    assert token not in output
    assert access(log_lines())[-1]["path"] == "/invites/accept"


def test_sensitive_fields_are_redacted_at_any_depth(
    log_lines: LogLines, token_factory: TokenFactory
) -> None:
    jwt = token_factory.valid()
    structlog.get_logger("test").info(
        f"falhou com o token {jwt}",
        authorization=f"Bearer {jwt}",
        code="abc123",
        headers={"Authorization": "Bearer xyz", "Accept": "json"},
        attempts=[{"token": "t0ken"}],
        status_code=401,
    )

    [line] = log_lines()
    assert line["event"] == f"falhou com o token {REDACTED}"
    assert line["authorization"] == REDACTED
    assert line["code"] == REDACTED
    assert line["headers"] == {"Authorization": REDACTED, "Accept": "json"}
    assert line["attempts"] == [{"token": REDACTED}]
    assert line["status_code"] == 401  # "status_code" não é "code"


@pytest.mark.parametrize(
    "url",
    [
        "GET /invites/accept?code=abc123 HTTP/1.1",
        "https://example.com/cb?state=x&access_token=abc123#frag",
        "/x?Token=abc123&page=2",
    ],
)
def test_secrets_in_url_query_strings_are_redacted(log_lines: LogLines, url: str) -> None:
    logging.getLogger("uvicorn.access").info(url)

    [line] = log_lines()
    assert "abc123" not in str(line["event"])
    assert REDACTED in str(line["event"])


def test_non_sensitive_query_parameters_are_kept(log_lines: LogLines) -> None:
    logging.getLogger("uvicorn.access").info("GET /households?page=2&encode=abc123 HTTP/1.1")
    [line] = log_lines()
    assert line["event"] == "GET /households?page=2&encode=abc123 HTTP/1.1"


def test_standard_library_logs_get_the_same_treatment(
    log_lines: LogLines, token_factory: TokenFactory
) -> None:
    jwt = token_factory.valid()
    logging.getLogger("some.library").warning("retrying with Authorization: Bearer %s", jwt)

    [line] = log_lines()
    assert line["logger"] == "some.library"
    assert line["level"] == "warning"
    assert jwt not in json.dumps(line)


def test_otlp_export_gets_rendered_json_without_structlog_internals(log_lines: LogLines) -> None:
    exporter = InMemoryLogRecordExporter()  # type: ignore[no-untyped-call]
    provider = LoggerProvider()
    provider.add_log_record_processor(SimpleLogRecordProcessor(exporter))
    configure_logging("INFO", stream=io.StringIO(), logger_provider=provider)

    structlog.get_logger("test").info("hello", code="abc123", household_id="h1")

    [exported] = exporter.get_finished_logs()
    body = json.loads(str(exported.log_record.body))
    assert (body["event"], body["code"], body["household_id"]) == ("hello", REDACTED, "h1")
    attributes = dict(exported.log_record.attributes or {})
    assert not any(key.startswith("_") for key in attributes), attributes
