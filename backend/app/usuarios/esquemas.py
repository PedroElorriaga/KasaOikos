import uuid

from pydantic import BaseModel, ConfigDict


class UsuarioAtual(BaseModel):
    """Usuário autenticado, como exposto pela API."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    nome: str
    email: str
