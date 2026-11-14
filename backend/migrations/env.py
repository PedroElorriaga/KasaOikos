"""Ambiente do Alembic: aplica as migrations no banco da API."""

from logging.config import fileConfig

from alembic import context
from sqlalchemy import create_engine, pool

from app.config import Settings

config = context.config

# Os testes desligam isto para não trocar a configuração de log do pytest.
if config.config_file_name is not None and config.attributes.get("configurar_logs", True):
    fileConfig(config.config_file_name, disable_existing_loggers=False)

# Sem metadata do ORM: as migrations são escritas à mão (não usamos autogenerate).
target_metadata = None


def _url_do_banco() -> str:
    # Os testes passam a URL do container; fora deles, vale a mesma configuração da API.
    url = config.attributes.get("database_url")
    if url is None:
        return Settings().database_url.get_secret_value()
    return str(url)


def rodar_migrations() -> None:
    engine = create_engine(_url_do_banco(), poolclass=pool.NullPool)
    try:
        with engine.connect() as conexao:
            context.configure(connection=conexao, target_metadata=target_metadata)
            with context.begin_transaction():
                context.run_migrations()
    finally:
        engine.dispose()


if context.is_offline_mode():
    raise RuntimeError("Modo offline (--sql) não é suportado: rode as migrations contra o banco.")

rodar_migrations()
