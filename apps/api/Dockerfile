# syntax=docker/dockerfile:1
# Imagem da API (tarefa 7.2). Construa a partir da raiz do repositório:
#   docker build -f apps/api/Dockerfile -t home-manager-api .
# (no Compose: docker compose build api, a partir de infra/)

FROM ghcr.io/astral-sh/uv:0.13.4 AS uv

# --- build: resolve e instala tudo num virtualenv em /app/.venv -------------------
FROM python:3.13-slim AS build
COPY --from=uv /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/app/.venv
WORKDIR /src

# 1) Só as dependências de terceiros. Esta camada depende apenas do uv.lock e dos
#    pyproject.toml, então mudar código não reinstala FastAPI, SQLAlchemy etc.
#    Módulo novo no workspace = mais uma linha aqui.
COPY pyproject.toml uv.lock ./
COPY apps/api/pyproject.toml apps/api/
COPY packages/platform/pyproject.toml packages/platform/
COPY modules/identity/pyproject.toml modules/identity/
COPY modules/finance/pyproject.toml modules/finance/
COPY modules/tasks/pyproject.toml modules/tasks/
COPY modules/inventory/pyproject.toml modules/inventory/
COPY modules/notifications/pyproject.toml modules/notifications/
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev --package hm-api --no-install-workspace

# 2) O código do workspace, instalado como pacotes normais (não editáveis): a imagem
#    final não precisa de /src.
COPY apps apps
COPY packages packages
COPY modules modules
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev --package hm-api --no-editable

# --- runtime: só o Python e o virtualenv; sem uv, sem código-fonte ----------------
# Mesma imagem base do build: o python do virtualenv aponta para /usr/local/bin.
FROM python:3.13-slim AS runtime
RUN groupadd --system --gid 10001 app \
    && useradd --system --uid 10001 --gid app --no-create-home --shell /usr/sbin/nologin app
COPY --from=build /app/.venv /app/.venv
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1
WORKDIR /app
USER app
EXPOSE 8000
HEALTHCHECK --interval=10s --timeout=3s --start-period=10s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health/live', timeout=2)"]
CMD ["hm", "serve", "--host", "0.0.0.0", "--port", "8000"]
