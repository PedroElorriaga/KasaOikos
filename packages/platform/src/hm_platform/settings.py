"""Configuração da aplicação, lida de variáveis de ambiente (prefixo ``HM_``).

Grupos aninhados usam ``__`` como separador, por exemplo ``HM_DB__POOL_SIZE=20``
ou ``HM_OIDC__ISSUER=http://192.168.0.10:8080/realms/home``.
"""

import os
from functools import lru_cache
from typing import Literal

from pydantic import BaseModel, Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import URL

type DatabaseRole = Literal["app", "migrator"]


class DatabaseSettings(BaseModel):
    host: str = "localhost"
    port: int = 5432
    name: str = "home"
    # Usuário da API: sujeito a RLS (design D4).
    app_user: str = "hm_app"
    app_password: SecretStr
    # Usuário das migrações e do seed; a API não precisa dele.
    migrator_user: str = "hm_migrator"
    migrator_password: SecretStr | None = None
    # Pool por worker (design D9): conexões totais = workers × (pool_size + max_overflow).
    pool_size: int = Field(default=10, ge=1)
    max_overflow: int = Field(default=0, ge=0)
    pool_timeout_seconds: float = Field(default=5.0, gt=0)

    def url(self, role: DatabaseRole = "app") -> URL:
        if role == "app":
            user, password = self.app_user, self.app_password
        else:
            if self.migrator_password is None:
                raise ValueError("HM_DB__MIGRATOR_PASSWORD é obrigatório para o role migrator")
            user, password = self.migrator_user, self.migrator_password
        # URL.create escapa a senha; não é preciso URL-encoding manual.
        return URL.create(
            "postgresql+asyncpg",
            username=user,
            password=password.get_secret_value(),
            host=self.host,
            port=self.port,
            database=self.name,
        )


class RedisSettings(BaseModel):
    host: str = "localhost"
    port: int = 6379
    password: SecretStr | None = None
    db: int = Field(default=0, ge=0)
    # Conexão e comandos; estourou, a API segue sem cache (vai ao banco).
    timeout_seconds: float = Field(default=0.5, gt=0)
    # Rede de segurança do cache de membership; a invalidação é explícita (design D6).
    membership_ttl_seconds: int = Field(default=60, ge=1)


class OIDCSettings(BaseModel):
    # Precisa ser idêntico ao "iss" dos tokens (KEYCLOAK_PUBLIC_URL + /realms/home).
    issuer: str = "http://localhost:8080/realms/home"
    audience: str = "home-api"
    # Vazio = derivado do issuer. Dentro do Compose, aponte para a rede interna
    # (http://keycloak:8080/...), já que o issuer usa o endereço externo.
    jwks_url: str | None = None
    # Intervalo mínimo entre refetches do JWKS em kid desconhecido (design D5).
    jwks_refetch_min_interval_seconds: float = Field(default=30.0, ge=0)
    algorithms: tuple[str, ...] = ("RS256",)
    # Tolerância a diferença de relógio entre o Keycloak e a API ao checar exp/iat.
    leeway_seconds: float = Field(default=5.0, ge=0)

    def resolved_jwks_url(self) -> str:
        if self.jwks_url:
            return self.jwks_url
        return f"{self.issuer.rstrip('/')}/protocol/openid-connect/certs"


class OTelSettings(BaseModel):
    # Desligado: traces e métricas continuam sendo gerados (X-Trace-Id funciona), só
    # não são exportados.
    enabled: bool = True
    service_name: str = "home-api"
    environment: str = "dev"
    # OTLP via HTTP/protobuf (porta 4318 do Collector); os caminhos /v1/* são acrescentados.
    exporter_endpoint: str = "http://localhost:4318"
    metric_export_interval_seconds: float = Field(default=15.0, gt=0)


def _default_workers() -> int:
    # Padrão do design D9: núcleos ÷ 2, no mínimo 1.
    return max(1, (os.cpu_count() or 2) // 2)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="HM_",
        env_nested_delimiter="__",
        env_file=".env",
        extra="ignore",
    )

    db: DatabaseSettings
    redis: RedisSettings = Field(default_factory=RedisSettings)
    oidc: OIDCSettings = Field(default_factory=OIDCSettings)
    otel: OTelSettings = Field(default_factory=OTelSettings)
    workers: int = Field(default_factory=_default_workers, ge=1)
    log_level: str = "INFO"


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]  # campos obrigatórios vêm do ambiente
