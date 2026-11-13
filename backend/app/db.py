from sqlalchemy import Engine, create_engine

from app.config import Settings

# Segundos para desistir de abrir conexão. Mantém o /health rápido quando o banco cai.
_CONNECT_TIMEOUT = 2


def criar_engine(settings: Settings) -> Engine:
    return create_engine(
        settings.database_url.get_secret_value(),
        # Testa a conexão antes de usar: descarta conexões mortas do pool.
        pool_pre_ping=True,
        connect_args={"connect_timeout": _CONNECT_TIMEOUT},
    )
