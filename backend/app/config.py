from pathlib import Path

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

# `.env` na raiz do repositório (fora do git). Opcional: variáveis de ambiente têm prioridade.
_ENV_FILE = Path(__file__).resolve().parents[2] / ".env"


class Settings(BaseSettings):
    """Configuração da API, lida de variáveis de ambiente.

    Nenhum segredo tem valor padrão: se faltar, a API não sobe.
    """

    model_config = SettingsConfigDict(env_file=_ENV_FILE, extra="ignore")

    # SecretStr: a URL contém senha e não pode aparecer em repr nem em log.
    database_url: SecretStr
