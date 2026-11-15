import { useQuery } from '@tanstack/react-query'

import { api } from '../api/cliente'
import { TituloPagina } from '../componentes/TituloPagina'

export function Inicio() {
  const me = useQuery({
    queryKey: ['me'],
    queryFn: async () => {
      const { data, response } = await api.GET('/me')
      if (!response.ok || !data) throw new Error(`GET /me respondeu ${String(response.status)}`)
      return data
    },
  })

  if (me.isPending) {
    return (
      <p role="status" className="text-texto-secundario">
        Carregando…
      </p>
    )
  }
  if (me.isError) {
    return <p role="alert">Não foi possível carregar seus dados. Tente recarregar a página.</p>
  }
  return <TituloPagina>{`Olá, ${me.data.nome}`}</TituloPagina>
}
