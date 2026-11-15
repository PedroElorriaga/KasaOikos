"""Exporta o contrato OpenAPI da API para um arquivo JSON, sem subir servidor nem banco.

Uso (a partir de `backend/`): uv run python -m scripts.exportar_openapi <arquivo.json>
Chamado pelo `pnpm gen:api` do front, que gera os tipos TS a partir dele.
"""

import json
import sys
from pathlib import Path

from pydantic import SecretStr

from app.config import Settings
from app.main import create_app


def main(destino: Path) -> None:
    # Valores fictícios: montar o app não conecta ao banco nem busca o JWKS.
    # `_env_file=None`: o contrato não pode depender do `.env` de quem gera.
    settings = Settings(
        _env_file=None,
        database_url=SecretStr("postgresql+psycopg://openapi@localhost/openapi"),
        oidc_issuer="http://localhost/realms/openapi",
        oidc_audience="openapi",
    )
    esquema = create_app(settings).openapi()
    destino.write_text(
        json.dumps(esquema, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n"
    )


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit("uso: python -m scripts.exportar_openapi <arquivo.json>")
    main(Path(sys.argv[1]))
