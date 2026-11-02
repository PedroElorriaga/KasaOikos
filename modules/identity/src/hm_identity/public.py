"""Interface pública do módulo. Único ponto importável por outros módulos."""

from hm_identity.api.routes import router
from hm_identity.infra.memberships import get_membership_role
from hm_identity.infra.users import provision_user
from hm_platform.tenancy import Principal, PrincipalDep

# Para os outros módulos, o usuário autenticado é o Principal da plataforma.
CurrentUser = Principal
CurrentUserDep = PrincipalDep

__all__ = ["CurrentUser", "CurrentUserDep", "get_membership_role", "provision_user", "router"]
