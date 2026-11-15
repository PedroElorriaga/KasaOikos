import { InMemoryWebStorage, UserManager, WebStorageStateStore } from 'oidc-client-ts'

import { config } from '../config'

interface OpcoesGerenciador {
  authority: string
  clientId: string
  /** Origem do front, ex.: http://localhost:5173 (precisa bater com as redirect URIs do realm). */
  origem: string
}

/**
 * Cliente OIDC: Authorization Code + PKCE com o client público do Keycloak (ADR-0002).
 *
 * Tokens (access, refresh e id) ficam SÓ EM MEMÓRIA: recarregar a página os descarta e o app
 * volta ao Keycloak, que devolve o usuário sem pedir senha enquanto a sessão de SSO valer.
 * Só o `state` e o `code_verifier` do PKCE passam pelo sessionStorage (`stateStore` padrão),
 * porque precisam sobreviver ao redirect; são apagados ao processar o callback.
 */
export function criarGerenciador({ authority, clientId, origem }: OpcoesGerenciador) {
  return new UserManager({
    authority,
    client_id: clientId,
    redirect_uri: `${origem}/callback`,
    post_logout_redirect_uri: `${origem}/`,
    response_type: 'code',
    scope: 'openid profile email',
    userStore: new WebStorageStateStore({ store: new InMemoryWebStorage() }),
    // Renova o access token pelo refresh token (em memória), sem iframe.
    automaticSilentRenew: true,
  })
}

export const gerenciador = criarGerenciador({
  authority: config.oidcAuthority,
  clientId: config.oidcClientId,
  origem: window.location.origin,
})
