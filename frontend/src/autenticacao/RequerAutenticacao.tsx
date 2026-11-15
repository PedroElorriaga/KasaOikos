import { useEffect, useState } from 'react'
import { Outlet, useLocation } from 'react-router'

import { gerenciador } from './gerenciador'
import { useAutenticacao } from './ProvedorAutenticacao'

/** Rotas protegidas: sem usuário em memória, redireciona ao Keycloak e volta para a mesma página. */
export function RequerAutenticacao() {
  const { estado } = useAutenticacao()
  const { pathname, search } = useLocation()
  const [falhou, setFalhou] = useState(false)

  useEffect(() => {
    if (estado.status !== 'anonimo') return
    gerenciador.signinRedirect({ url_state: pathname + search }).catch(() => {
      setFalhou(true)
    })
  }, [estado.status, pathname, search])

  if (estado.status === 'autenticado') return <Outlet />
  let mensagem = 'Entrando…'
  if (estado.status === 'saindo') mensagem = 'Saindo…'
  if (falhou) mensagem = 'Não foi possível abrir o login. Tente recarregar a página.'
  return (
    <p role="status" className="p-5 font-sans text-texto-secundario">
      {mensagem}
    </p>
  )
}
