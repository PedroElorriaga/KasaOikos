import type { User } from 'oidc-client-ts'
import { useEffect, useState } from 'react'
import { Link, useLocation, useNavigate } from 'react-router'

import { gerenciador } from '../autenticacao/gerenciador'

// Um processamento por retorno (`?code=...&state=...`): o code só pode ser trocado uma vez,
// e o StrictMode roda o efeito duas vezes em desenvolvimento.
const processamentos = new Map<string, Promise<User>>()

/** Só caminhos internos: evita redirecionamento aberto para outro site (`//site`, `https:`). */
function destinoSeguro(destino: string | undefined): string {
  return destino?.startsWith('/') && !destino.startsWith('//') ? destino : '/'
}

/** Retorno do Keycloak (redirect URI): troca o code pelos tokens e volta à página de origem. */
export function Callback() {
  const { pathname, search } = useLocation()
  const navigate = useNavigate()
  const [falhou, setFalhou] = useState(false)

  useEffect(() => {
    let processamento = processamentos.get(search)
    if (!processamento) {
      processamento = gerenciador.signinRedirectCallback(
        `${window.location.origin}${pathname}${search}`,
      )
      processamentos.set(search, processamento)
    }
    processamento.then(
      (usuario) => {
        void navigate(destinoSeguro(usuario.url_state), { replace: true })
      },
      () => {
        setFalhou(true)
      },
    )
  }, [navigate, pathname, search])

  if (!falhou) {
    return (
      <p role="status" className="p-5 font-sans text-texto-secundario">
        Entrando…
      </p>
    )
  }
  return (
    <div className="flex flex-col gap-3 p-5 font-sans text-texto">
      <p role="alert">Não foi possível concluir o login.</p>
      <Link to="/" className="font-semibold text-primaria">
        Tentar de novo
      </Link>
    </div>
  )
}
