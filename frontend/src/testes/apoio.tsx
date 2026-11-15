import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render } from '@testing-library/react'
import { User } from 'oidc-client-ts'
import { createMemoryRouter, RouterProvider } from 'react-router'
import { vi } from 'vitest'

import { gerenciador } from '../autenticacao/gerenciador'
import { ProvedorAutenticacao } from '../autenticacao/ProvedorAutenticacao'
import { rotas } from '../rotas'

export const TOKEN_FALSO = 'token-falso'

/** Usuário OIDC fictício, como o Keycloak devolveria depois do login. */
export function usuarioFalso(urlState?: string): User {
  const agora = Math.floor(Date.now() / 1000)
  return new User({
    access_token: TOKEN_FALSO,
    token_type: 'Bearer',
    session_state: null,
    expires_at: agora + 3600,
    url_state: urlState,
    profile: {
      iss: 'http://keycloak.teste/realms/teste',
      sub: 'sub-teste',
      aud: 'cliente-teste',
      exp: agora + 3600,
      iat: agora,
    },
  })
}

/** Deixa um usuário logado (em memória) antes de renderizar o app. */
export async function entrarComo(usuario: User = usuarioFalso()): Promise<void> {
  await gerenciador.storeUser(usuario)
}

export function respostaJson(corpo: unknown, status = 200): Response {
  return new Response(JSON.stringify(corpo), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

/** Substitui o `fetch` (a API) por uma resposta fixa de `GET /me`; devolve o mock. */
export function mockarMe(corpo: unknown = ME_FALSO, status = 200) {
  const mock = vi.fn<(requisicao: Request) => Promise<Response>>(() =>
    Promise.resolve(respostaJson(corpo, status)),
  )
  vi.stubGlobal('fetch', mock)
  return mock
}

export const ME_FALSO = {
  id: '6f1c7a52-8f0e-4a8e-9a37-0d2f5a0c1b11',
  nome: 'Ana Teste',
  email: 'ana.teste@example.com',
}

/** Renderiza o app inteiro (providers + rotas reais) a partir de um caminho. */
export function renderizarApp(caminho: string) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const roteador = createMemoryRouter(rotas, { initialEntries: [caminho] })
  render(
    <QueryClientProvider client={queryClient}>
      <ProvedorAutenticacao>
        <RouterProvider router={roteador} />
      </ProvedorAutenticacao>
    </QueryClientProvider>,
  )
  return { roteador }
}
