from typing import Annotated

from fastapi import APIRouter, Depends

from app.autenticacao import usuario_atual
from app.usuarios.esquemas import UsuarioAtual

router = APIRouter(tags=["usuarios"])


@router.get("/me")
def me(usuario: Annotated[UsuarioAtual, Depends(usuario_atual)]) -> UsuarioAtual:
    """Dados do usuário autenticado."""
    return usuario
