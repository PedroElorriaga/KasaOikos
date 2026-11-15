import { act, fireEvent, screen, waitFor } from '@testing-library/react'
import type { User } from 'oidc-client-ts'
import { describe, expect, it, vi } from 'vitest'

import { entrarComo, mockarMe, renderizarApp, TOKEN_FALSO, usuarioFalso } from '../testes/apoio'
import { criarGerenciador, gerenciador } from './gerenciador'

function valoresGuardados(armazenamento: Storage): string[] {
  return Array.from({ length: armazenamento.length }, (_, i) => {
    const chave = armazenamento.key(i) ?? ''
    return `${chave}=${armazenamento.getItem(chave) ?? ''}`
  })
}

/** Simula o retorno do Keycloak: grava o usuário e avisa o app, como o callback real faz. */
function mockarCallback(usuario: User) {
  return vi.spyOn(gerenciador, 'signinRedirectCallback').mockImplementation(async () => {
    await gerenciador.storeUser(usuario)
    await gerenciador.events.load(usuario)
    return usuario
  })
}

describe('token só em memória', () => {
  it('guarda o usuário sem gravar nada em localStorage nem token em sessionStorage', async () => {
    const g = criarGerenciador({
      authority: 'http://keycloak.teste/realms/teste',
      clientId: 'cliente-teste',
      origem: 'http://localhost:5173',
    })

    await g.storeUser(usuarioFalso())

    expect((await g.getUser())?.access_token).toBe(TOKEN_FALSO)
    expect(localStorage).toHaveLength(0)
    expect(valoresGuardados(sessionStorage).join('\n')).not.toContain(TOKEN_FALSO)
  })
})

describe('login', () => {
  it('sem usuário, redireciona ao Keycloak para voltar à mesma página', async () => {
    const signin = vi.spyOn(gerenciador, 'signinRedirect').mockResolvedValue()

    renderizarApp('/tarefas?filtro=hoje')

    await waitFor(() => {
      expect(signin).toHaveBeenCalledWith({ url_state: '/tarefas?filtro=hoje' })
    })
    expect(screen.queryByRole('navigation')).not.toBeInTheDocument()
  })

  it('no retorno do Keycloak, troca o code pelos tokens e volta à página de origem', async () => {
    mockarMe()
    const callback = mockarCallback(usuarioFalso('/custos'))

    const { roteador } = renderizarApp('/callback?code=abc&state=xyz')

    expect(await screen.findByRole('heading', { level: 1, name: 'Custos' })).toBeInTheDocument()
    expect(callback).toHaveBeenCalledOnce()
    expect(callback.mock.calls[0]?.[0]).toMatch(/\/callback\?code=abc&state=xyz$/)
    expect(roteador.state.location.pathname).toBe('/custos')
  })

  it('no retorno, ignora destino externo e vai para o início', async () => {
    mockarMe()
    mockarCallback(usuarioFalso('//site-malicioso.example'))

    const { roteador } = renderizarApp('/callback?code=def&state=uvw')

    expect(await screen.findByRole('heading', { level: 1, name: 'Olá, Ana Teste' })).toBeVisible()
    expect(roteador.state.location.pathname).toBe('/')
  })

  it('se o retorno do Keycloak falhar, avisa e oferece tentar de novo', async () => {
    vi.spyOn(gerenciador, 'signinRedirectCallback').mockRejectedValue(new Error('state inválido'))

    renderizarApp('/callback?code=ghi&state=rst')

    expect(await screen.findByRole('alert')).toHaveTextContent('Não foi possível concluir o login.')
    expect(screen.getByRole('link', { name: 'Tentar de novo' })).toHaveAttribute('href', '/')
  })
})

describe('logout', () => {
  it('"Sair" encerra a sessão no Keycloak sem disparar um novo login', async () => {
    await entrarComo()
    mockarMe()
    // Como o real: o oidc-client-ts descarta o usuário antes de redirecionar.
    const signout = vi.spyOn(gerenciador, 'signoutRedirect').mockImplementation(async () => {
      await gerenciador.removeUser()
    })
    const signin = vi.spyOn(gerenciador, 'signinRedirect').mockResolvedValue()

    renderizarApp('/tarefas')
    // Dois botões no DOM: lateral (desktop) e topo (celular); o CSS mostra um de cada vez.
    const botoes = await screen.findAllByRole('button', { name: 'Sair' })
    expect(botoes).toHaveLength(2)
    const [primeiro] = botoes
    if (!primeiro) throw new Error('botão "Sair" ausente')
    fireEvent.click(primeiro)

    await waitFor(() => {
      expect(signout).toHaveBeenCalledOnce()
    })
    // Espera o logout descartar o usuário e o React processar o efeito disso.
    await act(async () => {
      await signout.mock.results[0]?.value
    })
    expect(screen.getByRole('status')).toHaveTextContent('Saindo…')
    expect(signin).not.toHaveBeenCalled()
  })
})
