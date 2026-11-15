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

    # Emissor dos tokens (realm do Keycloak), comparado com o claim `iss`.
    oidc_issuer: str
    # Valor que precisa estar no claim `aud` (mapper de audience do realm).
    oidc_audience: str
    # Chaves públicas do emissor. Vazio: usa o endpoint padrão do Keycloak a partir do issuer.
    oidc_jwks_url: str | None = None

    @property
    def jwks_url(self) -> str:
        if self.oidc_jwks_url:
            return self.oidc_jwks_url
        return f"{self.oidc_issuer.rstrip('/')}/protocol/openid-connect/certs"
