import { fireEvent, render, screen, within } from '@testing-library/react'
import { createMemoryRouter, RouterProvider } from 'react-router'
import { describe, expect, it } from 'vitest'

import { rotas } from '../rotas'

function renderizarEm(caminho: string) {
  const roteador = createMemoryRouter(rotas, { initialEntries: [caminho] })
  render(<RouterProvider router={roteador} />)
}

function navegacao() {
  return within(screen.getByRole('navigation', { name: 'Navegação principal' }))
}

describe('Layout', () => {
  it('mostra as 4 seções do canvas, na ordem, com o link de cada uma', () => {
    renderizarEm('/')

    const links = navegacao().getAllByRole('link')
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

  it('marca só a seção atual como página corrente', () => {
    renderizarEm('/custos')

    expect(navegacao().getByRole('link', { name: 'Custos' })).toHaveAttribute(
      'aria-current',
      'page',
    )
    expect(navegacao().getByRole('link', { name: 'Início' })).not.toHaveAttribute('aria-current')
  })

  it('navega para a seção clicada', () => {
    renderizarEm('/')
    expect(screen.getByRole('heading', { level: 1, name: 'Início' })).toBeInTheDocument()

    fireEvent.click(navegacao().getByRole('link', { name: 'Tarefas' }))

    expect(screen.getByRole('heading', { level: 1, name: 'Tarefas' })).toBeInTheDocument()
  })
})
