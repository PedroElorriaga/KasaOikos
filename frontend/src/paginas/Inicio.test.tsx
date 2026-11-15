import { screen } from '@testing-library/react'
import { beforeEach, describe, expect, it } from 'vitest'

import { entrarComo, ME_FALSO, mockarMe, renderizarApp, TOKEN_FALSO } from '../testes/apoio'

describe('Início', () => {
  beforeEach(async () => {
    await entrarComo()
  })

  it('mostra "Olá, {nome}" a partir de GET /me, enviando o access token', async () => {
    const fetch = mockarMe({ ...ME_FALSO, nome: 'Ana Teste' })

    renderizarApp('/')

    expect(await screen.findByRole('heading', { level: 1, name: 'Olá, Ana Teste' })).toBeVisible()
    expect(fetch).toHaveBeenCalledOnce()
    const requisicao = fetch.mock.calls[0]?.[0]
    expect(requisicao?.method).toBe('GET')
    expect(requisicao?.url).toBe('http://api.teste/me')
    expect(requisicao?.headers.get('Authorization')).toBe(`Bearer ${TOKEN_FALSO}`)
  })

  it('avisa quando a API falha, sem mostrar a saudação', async () => {
    mockarMe({ detail: 'erro' }, 500)

    renderizarApp('/')

    expect(await screen.findByRole('alert')).toHaveTextContent(
      'Não foi possível carregar seus dados',
    )
    expect(screen.queryByRole('heading', { name: /Olá/ })).not.toBeInTheDocument()
  })
})
