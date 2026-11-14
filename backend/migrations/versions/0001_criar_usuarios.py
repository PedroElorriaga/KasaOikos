"""Cria a tabela usuarios.

Revision ID: 0001
Revises:
Create Date: 2026-11-14
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0001"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "usuarios",
        # gen_random_uuid() é nativo desde o Postgres 13 (não precisa de extensão).
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        # `sub` do token do Keycloak: identidade do usuário (ADR-0002).
        sa.Column("keycloak_sub", sa.Text(), nullable=False),
        sa.Column("nome", sa.Text(), nullable=False),
        # Sem unique: quem garante e-mail único é o Keycloak, e ele pode mudar lá.
        sa.Column("email", sa.Text(), nullable=False),
        sa.Column("telefone", sa.Text(), nullable=True),
        sa.Column("chave_pix", sa.Text(), nullable=True),
        sa.Column(
            "criado_em",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "atualizado_em",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_usuarios"),
        # Base do upsert no primeiro acesso (M0.5): dois acessos simultâneos geram uma só linha.
        sa.UniqueConstraint("keycloak_sub", name="uq_usuarios_keycloak_sub"),
    )


def downgrade() -> None:
    op.drop_table("usuarios")
