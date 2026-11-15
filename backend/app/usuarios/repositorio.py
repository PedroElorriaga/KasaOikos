from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.usuarios.modelos import Usuario


def buscar_por_sub(sessao: Session, keycloak_sub: str) -> Usuario | None:
    return sessao.scalars(select(Usuario).where(Usuario.keycloak_sub == keycloak_sub)).one_or_none()


def inserir_se_ausente(sessao: Session, *, keycloak_sub: str, nome: str, email: str) -> None:
    """Insere o usuário; se outro acesso já inseriu o mesmo `sub`, não faz nada.

    O índice único `uq_usuarios_keycloak_sub` resolve a corrida entre acessos simultâneos.
    """
    sessao.execute(
        insert(Usuario)
        .values(keycloak_sub=keycloak_sub, nome=nome, email=email)
        .on_conflict_do_nothing(index_elements=[Usuario.keycloak_sub])
    )
