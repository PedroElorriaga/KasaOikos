import uuid
from datetime import datetime

from sqlalchemy import DateTime, Text, func, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class Usuario(Base):
    """Tabela `usuarios` (migration 0001). Ligada ao Keycloak pelo `sub` do token."""

    __tablename__ = "usuarios"

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, server_default=text("gen_random_uuid()")
    )
    keycloak_sub: Mapped[str] = mapped_column(Text, unique=True)
    nome: Mapped[str] = mapped_column(Text)
    email: Mapped[str] = mapped_column(Text)
    telefone: Mapped[str | None] = mapped_column(Text)
    chave_pix: Mapped[str | None] = mapped_column(Text)
    criado_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    atualizado_em: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
