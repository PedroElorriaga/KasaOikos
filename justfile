# Tarefas do projeto. Rodam igual no PowerShell (Windows) e no sh (CI/Linux).
set windows-shell := ["powershell.exe", "-NoLogo", "-NoProfile", "-Command"]

# Lista as receitas disponíveis
default:
    @just --list

# Roda lint, tipos e testes de todo o projeto
check: check-backend check-frontend

# Back-end: lint, formatação, tipos e testes (os testes precisam do Docker rodando)
check-backend:
    uv run --directory backend --locked ruff check .
    uv run --directory backend --locked ruff format --check .
    uv run --directory backend --locked mypy
    uv run --directory backend --locked pytest

# Front-end: lint, formatação, tipos e testes
check-frontend:
    pnpm --dir frontend install --frozen-lockfile
    pnpm --dir frontend check

# Sobe o front em modo de desenvolvimento (http://localhost:5173)
front:
    pnpm --dir frontend dev

# Aplica as migrations pendentes no banco do `.env` (revise a migration antes de rodar)
migrate:
    uv run --directory backend --locked alembic upgrade head

# Formata o código e aplica as correções automáticas do lint
fmt:
    uv run --directory backend --locked ruff format .
    uv run --directory backend --locked ruff check --fix .
    pnpm --dir frontend format
