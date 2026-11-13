# Tarefas do projeto. Rodam igual no PowerShell (Windows) e no sh (CI/Linux).
set windows-shell := ["powershell.exe", "-NoLogo", "-NoProfile", "-Command"]

# Lista as receitas disponíveis
default:
    @just --list

# Roda lint, tipos e testes de todo o projeto
check:
    @echo "just check: ainda nao ha nada para checar."
    @echo "  pendente: backend  (M0.2) - ruff, mypy, pytest"
    @echo "  pendente: frontend (M0.6) - eslint, tsc, vitest"
