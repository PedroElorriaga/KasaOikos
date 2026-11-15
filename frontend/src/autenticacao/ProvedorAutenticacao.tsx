import { useQueryClient } from '@tanstack/react-query'
import type { User } from 'oidc-client-ts'
import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react'
import type { ReactNode } from 'react'

import { gerenciador } from './gerenciador'

export type EstadoAutenticacao =
  | { status: 'carregando' }
  | { status: 'anonimo' }
  | { status: 'autenticado'; usuario: User }
  // Logout em andamento: impede que a saída do usuário dispare um novo login.
  | { status: 'saindo' }

interface ContextoAutenticacao {
  estado: EstadoAutenticacao
  sair: () => Promise<void>
}

const Contexto = createContext<ContextoAutenticacao | null>(null)

export function ProvedorAutenticacao({ children }: { children: ReactNode }) {
  const queryClient = useQueryClient()
  const [estado, setEstado] = useState<EstadoAutenticacao>({ status: 'carregando' })

  useEffect(() => {
    let ativo = true
    void gerenciador.getUser().then((usuario) => {
      if (!ativo) return
      setEstado(
        usuario && !usuario.expired ? { status: 'autenticado', usuario } : { status: 'anonimo' },
      )
    })

    const eventos = gerenciador.events
    const removerOuvintes = [
      eventos.addUserLoaded((usuario) => {
        setEstado({ status: 'autenticado', usuario })
      }),
      eventos.addUserUnloaded(() => {
        setEstado((atual) => (atual.status === 'saindo' ? atual : { status: 'anonimo' }))
      }),
      // A renovação falhou e o token venceu: descarta o usuário (volta ao login).
      eventos.addAccessTokenExpired(() => {
        void gerenciador.removeUser()
      }),
    ]
    return () => {
      ativo = false
      removerOuvintes.forEach((remover) => {
        remover()
      })
    }
  }, [])

  const sair = useCallback(async () => {
    setEstado({ status: 'saindo' })
    queryClient.clear()
    await gerenciador.signoutRedirect()
  }, [queryClient])

  const valor = useMemo(() => ({ estado, sair }), [estado, sair])
  return <Contexto value={valor}>{children}</Contexto>
}

export function useAutenticacao(): ContextoAutenticacao {
  const contexto = useContext(Contexto)
  if (!contexto) throw new Error('useAutenticacao precisa estar dentro de <ProvedorAutenticacao>')
  return contexto
}
