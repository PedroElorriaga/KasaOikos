"""Configuração compartilhada pelo seed e pelo runner do k6.

As chaves são as mesmas do ``infra/.env``: na estação de desenvolvimento, aponte
``--env-file`` para ele; contra o servidor, use um ``loadtest/.env`` só com as chaves
necessárias (modelo em ``loadtest/.env.example``). Variáveis de ambiente têm precedência
sobre o arquivo.
"""

import os
from collections.abc import Mapping
from pathlib import Path

LOADTEST_DIR = Path(__file__).resolve().parent
DEFAULT_ENV_FILE = LOADTEST_DIR / ".env"

# Usuários sintéticos: seed-<lar>-<n>; o primeiro de cada lar é o admin.
SEED_EMAIL_DOMAIN = "seed.home.test"


def seed_username(household: int, member: int) -> str:
    return f"seed-{household:05d}-{member}"


def load_env(path: Path | None) -> dict[str, str]:
    env: dict[str, str] = {}
    if path is not None:
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                env[key.strip()] = value.strip()
    env.update(os.environ)
    return env


def require(env: Mapping[str, str], key: str) -> str:
    value = env.get(key)
    if not value:
        raise SystemExit(f"defina {key} no --env-file ou no ambiente")
    return value


def server(env: Mapping[str, str]) -> str:
    """Endereço do servidor (HM_SERVER); localhost quando o Compose roda na estação."""
    return env.get("HM_SERVER") or "localhost"


def keycloak_url(env: Mapping[str, str]) -> str:
    return f"http://{server(env)}:{env.get('KEYCLOAK_PORT', '8080')}"
