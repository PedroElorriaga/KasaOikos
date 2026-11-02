"""Spec platform/observability: rastreamento distribuído (6.2) e métricas de requisição (6.3)."""

import re

import httpx
from fastapi import FastAPI
from opentelemetry.sdk.metrics.export import InMemoryMetricReader, NumberDataPoint
from opentelemetry.sdk.trace import ReadableSpan
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import SpanKind

from hm_platform.ids import uuid7
from hm_platform.telemetry import HTTP_SERVER_METRIC_ATTRIBUTES
from hm_platform.tenancy import MembershipCache

TRACE_ID = "4bf92f3577b34da6a3ce929d0e0e4736"
PARENT_SPAN_ID = "00f067aa0ba902b7"


def trace_id_of(span: ReadableSpan) -> str:
    return format(span.context.trace_id, "032x")


def server_span(spans: tuple[ReadableSpan, ...]) -> ReadableSpan:
    [span] = [s for s in spans if s.kind is SpanKind.SERVER]
    return span


# --- 6.2 Requirement: Rastreamento distribuído -------------------------------------------


async def test_request_without_traceparent_starts_a_new_trace(
    client: httpx.AsyncClient, span_exporter: InMemorySpanExporter
) -> None:
    response = await client.get("/health/ready")

    trace_id = response.headers["X-Trace-Id"]
    assert re.fullmatch(r"[0-9a-f]{32}", trace_id)
    assert trace_id != "0" * 32
    spans = span_exporter.get_finished_spans()
    assert trace_id_of(server_span(spans)) == trace_id
    assert server_span(spans).parent is None


async def test_spans_cover_http_database_and_cache(
    client: httpx.AsyncClient, span_exporter: InMemorySpanExporter
) -> None:
    response = await client.get("/health/ready")

    spans = span_exporter.get_finished_spans()
    same_trace = [s for s in spans if trace_id_of(s) == response.headers["X-Trace-Id"]]
    systems = {
        (s.attributes or {}).get("db.system") or (s.attributes or {}).get("db.system.name")
        for s in same_trace
    }
    assert server_span(spans).name == "GET /health/ready"
    assert {"postgresql", "redis"} <= systems, [s.name for s in same_trace]


async def test_traceparent_continues_the_callers_trace(
    client: httpx.AsyncClient, span_exporter: InMemorySpanExporter
) -> None:
    response = await client.get(
        "/health/live", headers={"traceparent": f"00-{TRACE_ID}-{PARENT_SPAN_ID}-01"}
    )

    assert response.headers["X-Trace-Id"] == TRACE_ID
    span = server_span(span_exporter.get_finished_spans())
    assert trace_id_of(span) == TRACE_ID
    assert span.parent is not None
    assert format(span.parent.span_id, "016x") == PARENT_SPAN_ID


async def test_invalid_traceparent_starts_a_new_trace(client: httpx.AsyncClient) -> None:
    response = await client.get("/health/live", headers={"traceparent": "garbage"})
    assert re.fullmatch(r"[0-9a-f]{32}", response.headers["X-Trace-Id"])
    assert response.headers["X-Trace-Id"] != TRACE_ID


async def test_error_responses_also_carry_the_trace_id(client: httpx.AsyncClient) -> None:
    response = await client.get("/me")  # sem token
    assert response.status_code == 401
    assert re.fullmatch(r"[0-9a-f]{32}", response.headers["X-Trace-Id"])


# --- 6.3 Requirement: Métricas de requisição ---------------------------------------------


def http_server_points(reader: InMemoryMetricReader) -> dict[str, list[dict[str, object]]]:
    data = reader.get_metrics_data()
    assert data is not None
    points: dict[str, list[dict[str, object]]] = {}
    for resource in data.resource_metrics:
        for scope in resource.scope_metrics:
            for metric in scope.metrics:
                if metric.name.startswith("http.server."):
                    points.setdefault(metric.name, []).extend(
                        dict(p.attributes or {}) for p in metric.data.data_points
                    )
    return points


async def test_parametrized_route_is_labelled_with_its_template(
    client: httpx.AsyncClient, metric_reader: InMemoryMetricReader
) -> None:
    household_id = str(uuid7())
    await client.get(f"/households/{household_id}/members")  # 401, mas a rota casou

    points = http_server_points(metric_reader)

    durations = points["http.server.request.duration"]
    assert {
        "http.request.method": "GET",
        "http.route": "/households/{household_id}/members",
        "http.response.status_code": 401,
    } in durations


async def test_metric_labels_never_carry_high_cardinality_values(
    client: httpx.AsyncClient, metric_reader: InMemoryMetricReader
) -> None:
    household_id = str(uuid7())
    await client.get(f"/households/{household_id}/members")
    await client.get(f"/no/such/route/{household_id}")  # 404 sem rota: sem http.route
    await client.get("/health/live", headers={"Host": f"{household_id}.evil.example"})

    points = http_server_points(metric_reader)

    assert points, "nenhuma métrica HTTP do servidor foi registrada"
    for name, attributes in points.items():
        for labels in attributes:
            assert set(labels) <= HTTP_SERVER_METRIC_ATTRIBUTES, (name, labels)
            assert all(household_id not in str(v) for v in labels.values()), (name, labels)


async def test_membership_cache_lookups_are_counted_by_result(
    app: FastAPI, client: httpx.AsyncClient, metric_reader: InMemoryMetricReader
) -> None:
    cache: MembershipCache = app.state.membership_cache
    user, household = uuid7(), uuid7()
    await cache._redis.set(MembershipCache.key(user, household), "member")

    # Num hit, o resolver (e portanto a sessão) nem é usado.
    assert await cache.get_role(None, user, household) == "member"  # type: ignore[arg-type]

    data = metric_reader.get_metrics_data()
    assert data is not None
    counts = {
        str((point.attributes or {})["result"]): point.value
        for resource in data.resource_metrics
        for scope in resource.scope_metrics
        for metric in scope.metrics
        if metric.name == "hm.membership_cache.lookups"
        for point in metric.data.data_points
        if isinstance(point, NumberDataPoint)
    }
    assert counts == {"hit": 1}
