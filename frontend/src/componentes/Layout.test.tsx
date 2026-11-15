import { fireEvent, screen, within } from '@testing-library/react'
import { beforeEach, describe, expect, it } from 'vitest'

import { entrarComo, mockarMe, renderizarApp } from '../testes/apoio'

async function navegacao() {
  return within(await screen.findByRole('navigation', { name: 'Navegação principal' }))
}

describe('Layout', () => {
  beforeEach(async () => {
    await entrarComo()
    mockarMe()
  })

  it('mostra as 4 seções do canvas, na ordem, com o link de cada uma', async () => {
    renderizarApp('/')

    const links = (await navegacao()).getAllByRole('link')
    expect(links.map((link) => link.getAttribute('aria-label'))).toEqual([
      'Início',
      'Tarefas',
      'Custos',
      'Compras e estoque',
    ])
    expect(links.map((link) => link.getAttribute('href'))).toEqual([
      '/',
      '/tarefas',
      '/custos',
      '/compras',
    ])
  })

  it('marca só a seção atual como página corrente', async () => {
    renderizarApp('/custos')

    const nav = await navegacao()
    expect(nav.getByRole('link', { name: 'Custos' })).toHaveAttribute('aria-current', 'page')
    expect(nav.getByRole('link', { name: 'Início' })).not.toHaveAttribute('aria-current')
  })

  it('navega para a seção clicada', async () => {
    renderizarApp('/custos')
    expect(await screen.findByRole('heading', { level: 1, name: 'Custos' })).toBeInTheDocument()

    fireEvent.click((await navegacao()).getByRole('link', { name: 'Tarefas' }))

    expect(screen.getByRole('heading', { level: 1, name: 'Tarefas' })).toBeInTheDocument()
  })
})
