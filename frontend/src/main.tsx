import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { RouterProvider } from 'react-router'

import { ProvedorAutenticacao } from './autenticacao/ProvedorAutenticacao'
import './index.css'
import { roteador } from './rotas'

const raiz = document.getElementById('root')
if (!raiz) throw new Error('Elemento #root não encontrado no index.html')

const queryClient = new QueryClient()

createRoot(raiz).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <ProvedorAutenticacao>
        <RouterProvider router={roteador} />
      </ProvedorAutenticacao>
    </QueryClientProvider>
  </StrictMode>,
)
