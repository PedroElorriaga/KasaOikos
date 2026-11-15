import { createBrowserRouter, type RouteObject } from 'react-router'

import { Layout } from './componentes/Layout'
import { Compras } from './paginas/Compras'
import { Custos } from './paginas/Custos'
import { Inicio } from './paginas/Inicio'
import { Tarefas } from './paginas/Tarefas'

export const rotas: RouteObject[] = [
  {
    element: <Layout />,
    children: [
      { index: true, element: <Inicio /> },
      { path: 'tarefas', element: <Tarefas /> },
      { path: 'custos', element: <Custos /> },
      { path: 'compras', element: <Compras /> },
    ],
  },
]

export const roteador = createBrowserRouter(rotas)
