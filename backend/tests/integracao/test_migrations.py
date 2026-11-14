"""Migrations do Alembic aplicadas em um banco novo (Postgres exclusivo do teste)."""

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, create_engine, inspect, text
from sqlalchemy.exc import IntegrityError
from testcontainers.community.postgres import PostgresContainer

_ALEMBIC_INI = Path(__file__).resolve().parents[2] / "alembic.ini"

# coluna -> aceita nulo
_COLUNAS_ESPERADAS = {
    "id": False,
    "keycloak_sub": False,
    "nome": False,
    "email": False,
    "telefone": True,
    "chave_pix": True,
    "criado_em": False,
    "atualizado_em": False,
}


@pytest.fixture
def banco_novo(postgres_descartavel: PostgresContainer) -> Iterator[tuple[Config, Engine]]:
    url = postgres_descartavel.get_connection_url()
    config = Config(str(_ALEMBIC_INI))
    config.attributes["database_url"] = url
    config.attributes["configurar_logs"] = False
    engine = create_engine(url)
    yield config, engine
    engine.dispose()


def _schema_usuarios(engine: Engine) -> dict[str, Any]:
    inspetor = inspect(engine)
    return {
        "colunas": [
            (c["name"], str(c["type"]), c["nullable"], c.get("default"))
            for c in inspetor.get_columns("usuarios")
        ],
        "pk": inspetor.get_pk_constraint("usuarios"),
        "uniques": inspetor.get_unique_constraints("usuarios"),
        "indices": inspetor.get_indexes("usuarios"),
    }


def _versoes_aplicadas(engine: Engine) -> list[str]:
    with engine.connect() as conexao:
        return list(conexao.execute(text("SELECT version_num FROM alembic_version")).scalars())


def test_upgrade_downgrade_upgrade_roda_limpo_em_banco_novo(
    banco_novo: tuple[Config, Engine],
) -> None:
    config, engine = banco_novo

    command.upgrade(config, "head")

    assert _versoes_aplicadas(engine) == ["0001"]
    schema = _schema_usuarios(engine)
    assert {nome: nulo for nome, _, nulo, _ in schema["colunas"]} == _COLUNAS_ESPERADAS
    assert schema["pk"]["constrained_columns"] == ["id"]
    assert [(u["name"], u["column_names"]) for u in schema["uniques"]] == [
        ("uq_usuarios_keycloak_sub", ["keycloak_sub"])
    ]

    command.downgrade(config, "base")

    assert not inspect(engine).has_table("usuarios")
    assert _versoes_aplicadas(engine) == []

    command.upgrade(config, "head")

    assert _versoes_aplicadas(engine) == ["0001"]
    assert _schema_usuarios(engine) == schema


def test_keycloak_sub_e_unico_e_banco_preenche_id_e_datas(
    banco_novo: tuple[Config, Engine],
) -> None:
    config, engine = banco_novo
    command.upgrade(config, "head")
    inserir = text(
        "INSERT INTO usuarios (keycloak_sub, nome, email) VALUES (:sub, :nome, :email) "
        "RETURNING id, criado_em, atualizado_em"
    )

    with engine.begin() as conexao:
        linha = conexao.execute(
            inserir, {"sub": "sub-teste-1", "nome": "Ana Teste", "email": "ana@example.com"}
        ).one()
    assert linha.id is not None
    assert linha.criado_em is not None
    assert linha.atualizado_em is not None

    with pytest.raises(IntegrityError, match="uq_usuarios_keycloak_sub"), engine.begin() as conexao:
        conexao.execute(
            inserir, {"sub": "sub-teste-1", "nome": "Outra Ana", "email": "outra@example.com"}
        )
