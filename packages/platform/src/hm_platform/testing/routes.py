"""Descoberta das rotas de uma app FastAPI, para testes que precisam cobrir todas."""

from collections.abc import Iterator, Sequence

from fastapi.routing import APIRoute
from starlette.routing import BaseRoute


def iter_routes(
    routes: Sequence[BaseRoute], prefix: str = "", inherited: tuple[object, ...] = ()
) -> Iterator[tuple[str, APIRoute, tuple[object, ...]]]:
    """Todas as APIRoute da app, inclusive dentro de routers incluídos.

    Devolve o caminho completo, a rota e as dependencies herdadas dos ``include_router``.
    O FastAPI atual guarda ``include_router`` como um router aninhado (``original_router``
    + ``include_context``, com prefixo e dependencies do include); versões antigas
    copiavam as rotas para ``app.routes``. Os dois formatos são aceitos.
    """
    for route in routes:
        if isinstance(route, APIRoute):
            yield prefix + route.path, route, inherited
        elif (inner := getattr(route, "original_router", None)) is not None:
            context = getattr(route, "include_context", None)
            deps = tuple(d.dependency for d in getattr(context, "dependencies", []))
            yield from iter_routes(
                inner.routes, prefix + getattr(context, "prefix", ""), inherited + deps
            )
