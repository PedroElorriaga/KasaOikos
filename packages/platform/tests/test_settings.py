import os

import pytest
from pydantic import ValidationError

from hm_platform.settings import Settings


@pytest.fixture(autouse=True)
def clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Isola os testes de variáveis HM_* da máquina."""
    for key in list(os.environ):
        if key.startswith("HM_"):
            monkeypatch.delenv(key)


def load() -> Settings:
    # Sem .env: só o ambiente controlado pelo teste.
    return Settings(_env_file=None)  # type: ignore[call-arg]


def test_loads_nested_groups_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HM_DB__HOST", "192.168.0.10")
    monkeypatch.setenv("HM_DB__APP_PASSWORD", "app-secret")
    monkeypatch.setenv("HM_DB__POOL_SIZE", "20")
    monkeypatch.setenv("HM_REDIS__HOST", "cache")
    monkeypatch.setenv("HM_REDIS__PASSWORD", "redis-secret")
    monkeypatch.setenv("HM_OIDC__ISSUER", "http://192.168.0.10:8080/realms/home")
    monkeypatch.setenv("HM_OTEL__ENABLED", "false")
    monkeypatch.setenv("HM_WORKERS", "3")

    s = load()

    assert s.db.host == "192.168.0.10"
    assert s.db.app_password.get_secret_value() == "app-secret"
    assert s.db.pool_size == 20
    assert s.redis.host == "cache"
    assert s.redis.password is not None
    assert s.redis.password.get_secret_value() == "redis-secret"
    assert s.oidc.issuer == "http://192.168.0.10:8080/realms/home"
    assert s.otel.enabled is False
    assert s.workers == 3


def test_db_settings_are_required() -> None:
    with pytest.raises(ValidationError, match="db"):
        load()


def test_db_app_password_is_required(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HM_DB__HOST", "db")
    with pytest.raises(ValidationError, match="app_password"):
        load()


def test_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HM_DB__APP_PASSWORD", "x")

    s = load()

    assert (s.db.host, s.db.port, s.db.name, s.db.app_user) == ("localhost", 5432, "home", "hm_app")
    assert s.redis.membership_ttl_seconds == 60
    assert s.oidc.audience == "home-api"
    assert s.oidc.algorithms == ("RS256",)
    assert s.oidc.jwks_refetch_min_interval_seconds == 30


def test_jwks_url_derived_from_issuer_or_overridden(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HM_DB__APP_PASSWORD", "x")
    monkeypatch.setenv("HM_OIDC__ISSUER", "http://kc:8080/realms/home/")
    assert load().oidc.resolved_jwks_url() == (
        "http://kc:8080/realms/home/protocol/openid-connect/certs"
    )

    monkeypatch.setenv("HM_OIDC__JWKS_URL", "http://keycloak:8080/certs")
    assert load().oidc.resolved_jwks_url() == "http://keycloak:8080/certs"


def test_database_url_per_role_escapes_password(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HM_DB__APP_PASSWORD", "p@ss/w:rd")
    monkeypatch.setenv("HM_DB__MIGRATOR_PASSWORD", "mig")

    db = load().db

    app_url = db.url("app")
    assert app_url.drivername == "postgresql+asyncpg"
    assert app_url.username == "hm_app"
    assert app_url.password == "p@ss/w:rd"
    assert "p%40ss%2Fw%3Ard" in app_url.render_as_string(hide_password=False)
    assert db.url("migrator").username == "hm_migrator"


def test_migrator_url_requires_password(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HM_DB__APP_PASSWORD", "x")
    with pytest.raises(ValueError, match="MIGRATOR_PASSWORD"):
        load().db.url("migrator")


def test_secrets_are_not_exposed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HM_DB__APP_PASSWORD", "top-secret")
    monkeypatch.setenv("HM_REDIS__PASSWORD", "top-secret")

    s = load()

    assert "top-secret" not in repr(s)
    assert "top-secret" not in s.model_dump_json()
    assert "top-secret" not in str(s.db.url())


@pytest.mark.parametrize(("cpus", "expected"), [(8, 4), (1, 1), (None, 1)])
def test_workers_default_is_half_the_cores(
    monkeypatch: pytest.MonkeyPatch, cpus: int | None, expected: int
) -> None:
    monkeypatch.setenv("HM_DB__APP_PASSWORD", "x")
    monkeypatch.setattr(os, "cpu_count", lambda: cpus)
    assert load().workers == expected


@pytest.mark.parametrize(
    ("var", "value"), [("HM_DB__POOL_SIZE", "0"), ("HM_WORKERS", "0"), ("HM_DB__PORT", "abc")]
)
def test_invalid_values_are_rejected(monkeypatch: pytest.MonkeyPatch, var: str, value: str) -> None:
    monkeypatch.setenv("HM_DB__APP_PASSWORD", "x")
    monkeypatch.setenv(var, value)
    with pytest.raises(ValidationError):
        load()
