from pathlib import Path
from urllib.parse import urlsplit

from pydantic import SecretStr, field_validator
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

    # Origens do front liberadas no CORS, exatas (ex.: ["http://localhost:5173"]).
    # Vazio: nenhuma origem liberada (fecha por padrão).
    cors_origins: list[str] = []

    @field_validator("cors_origins")
    @classmethod
    def _origens_exatas(cls, origens: list[str]) -> list[str]:
        for origem in origens:
            partes = urlsplit(origem)
            exata = (
                partes.scheme in ("http", "https")
                and bool(partes.hostname)
                and "*" not in origem
                and not partes.username
                and not partes.password
                and origem == f"{partes.scheme}://{partes.netloc}"
            )
            if not exata:
                raise ValueError(
                    f"origem de CORS inválida: {origem!r}; use esquema://host[:porta], "
                    "sem curinga, caminho ou barra no fim"
                )
        return origens

    @property
    def jwks_url(self) -> str:
        if self.oidc_jwks_url:
            return self.oidc_jwks_url
        return f"{self.oidc_issuer.rstrip('/')}/protocol/openid-connect/certs"
