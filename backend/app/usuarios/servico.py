from sqlalchemy.orm import Session

from app.usuarios import repositorio
from app.usuarios.esquemas import UsuarioAtual


def obter_ou_criar(sessao: Session, *, keycloak_sub: str, nome: str, email: str) -> UsuarioAtual:
    """Devolve o usuário do `sub`, criando-o no primeiro acesso (ADR-0002).

    Usuário existente não é atualizado: nome e e-mail ficam como no primeiro acesso.
    """
    usuario = repositorio.buscar_por_sub(sessao, keycloak_sub)
    if usuario is None:
        repositorio.inserir_se_ausente(sessao, keycloak_sub=keycloak_sub, nome=nome, email=email)
        sessao.commit()
        # Relê: se outro acesso simultâneo venceu a corrida, a linha é a dele.
        usuario = repositorio.buscar_por_sub(sessao, keycloak_sub)
    if usuario is None:
        raise RuntimeError("usuário não encontrado após inserção")
    return UsuarioAtual.model_validate(usuario)
