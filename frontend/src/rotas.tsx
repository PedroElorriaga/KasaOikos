import { createBrowserRouter, type RouteObject } from 'react-router'

import { RequerAutenticacao } from './autenticacao/RequerAutenticacao'
import { Layout } from './componentes/Layout'
import { Callback } from './paginas/Callback'
import { Compras } from './paginas/Compras'
import { Custos } from './paginas/Custos'
import { Inicio } from './paginas/Inicio'
import { Tarefas } from './paginas/Tarefas'

export const rotas: RouteObject[] = [
  // Redirect URI do Keycloak: fica fora da área protegida.
  { path: 'callback', element: <Callback /> },
  {
    element: <RequerAutenticacao />,
    children: [
      {
        element: <Layout />,
        children: [
          { index: true, element: <Inicio /> },
          { path: 'tarefas', element: <Tarefas /> },
          { path: 'custos', element: <Custos /> },
          { path: 'compras', element: <Compras /> },
        ],
      },
    ],
  },
]

export const roteador = createBrowserRouter(rotas)
