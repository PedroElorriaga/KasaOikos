import createClient from 'openapi-fetch'

import { gerenciador } from '../autenticacao/gerenciador'
import { config } from '../config'
import type { paths } from './esquema.gerado'

/** Cliente da API tipado pelo contrato OpenAPI, com o access token no header Authorization. */
export function criarClienteApi(baseUrl: string, obterToken: () => Promise<string | null>) {
  // `fetch` resolvido a cada chamada (e não na criação), para os testes poderem substituí-lo.
  const cliente = createClient<paths>({ baseUrl, fetch: (requisicao) => fetch(requisicao) })
  cliente.use({
    async onRequest({ request }) {
      const token = await obterToken()
      if (token) request.headers.set('Authorization', `Bearer ${token}`)
      return request
    },
  })
  return cliente
}

export const api = criarClienteApi(
  config.apiUrl,
  async () => (await gerenciador.getUser())?.access_token ?? null,
)
