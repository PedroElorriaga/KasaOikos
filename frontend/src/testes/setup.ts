import '@testing-library/jest-dom/vitest'
import { cleanup } from '@testing-library/react'
import { afterEach } from 'vitest'

// Sem `globals: true` no Vitest, a Testing Library não limpa o DOM sozinha.
afterEach(() => {
  cleanup()
})
