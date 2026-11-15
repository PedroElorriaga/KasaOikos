import '@testing-library/jest-dom/vitest'
import { cleanup } from '@testing-library/react'
import { afterEach, beforeEach, vi } from 'vitest'

import { gerenciador } from '../autenticacao/gerenciador'

beforeEach(() => {
  // Nenhum teste fala com a rede: quem precisa da API substitui o fetch (ver apoio.tsx).
  vi.stubGlobal(
    'fetch',
    vi.fn(() => Promise.reject(new Error('fetch não mockado neste teste'))),
  )
})

// Sem `globals: true` no Vitest, a Testing Library não limpa o DOM sozinha.
afterEach(async () => {
  cleanup()
  await gerenciador.removeUser()
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
  localStorage.clear()
  sessionStorage.clear()
})
