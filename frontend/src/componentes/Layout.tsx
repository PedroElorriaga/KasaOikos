import type { ReactNode } from 'react'
import { NavLink, Outlet } from 'react-router'

import { IconeCompras, IconeCustos, IconeInicio, IconeTarefas } from './icones'

interface Secao {
  caminho: string
  rotulo: string
  /** Rótulo da barra inferior do celular, quando o completo não cabe. */
  rotuloCurto?: string
  icone: ReactNode
}

export const SECOES: Secao[] = [
  { caminho: '/', rotulo: 'Início', icone: <IconeInicio /> },
  { caminho: '/tarefas', rotulo: 'Tarefas', icone: <IconeTarefas /> },
  { caminho: '/custos', rotulo: 'Custos', icone: <IconeCustos /> },
  {
    caminho: '/compras',
    rotulo: 'Compras e estoque',
    rotuloCurto: 'Compras',
    icone: <IconeCompras />,
  },
]

function classesDoLink({ isActive }: { isActive: boolean }) {
  const base =
    'flex flex-col items-center justify-center gap-1 text-xs no-underline ' +
    'md:h-11 md:flex-row md:justify-start md:gap-2.5 md:rounded-[10px] md:px-3 md:text-sm'
  return isActive
    ? `${base} font-semibold text-primaria md:bg-ativo`
    : `${base} font-medium text-texto-secundario hover:text-texto`
}

/** Layout base: barra inferior no celular, barra lateral a partir de `md` (768 px). */
export function Layout() {
  return (
    <div className="min-h-dvh bg-fundo font-sans text-texto md:flex">
      <aside className="fixed inset-x-0 bottom-0 z-10 border-t border-borda bg-superficie md:sticky md:top-0 md:flex md:h-dvh md:w-[220px] md:shrink-0 md:flex-col md:gap-6 md:border-t-0 md:border-r md:px-4 md:py-6">
        <span className="hidden px-2 font-titulo text-xl font-bold text-primaria md:block">
          KasaOikos
        </span>
        <nav
          aria-label="Navegação principal"
          className="grid h-[76px] grid-cols-4 md:flex md:h-auto md:flex-col md:gap-1"
        >
          {SECOES.map((secao) => (
            <NavLink
              key={secao.caminho}
              to={secao.caminho}
              end={secao.caminho === '/'}
              // Nome acessível fixo (o rótulo curto do celular está contido nele).
              aria-label={secao.rotulo}
              className={classesDoLink}
            >
              {secao.icone}
              {secao.rotuloCurto ? (
                <>
                  <span className="md:hidden">{secao.rotuloCurto}</span>
                  <span className="hidden md:inline">{secao.rotulo}</span>
                </>
              ) : (
                <span>{secao.rotulo}</span>
              )}
            </NavLink>
          ))}
        </nav>
      </aside>

      {/* pb-[100px]: espaço para a barra inferior fixa (76 px) no celular. */}
      <main className="mx-auto w-full max-w-[1200px] min-w-0 px-5 pt-5 pb-[100px] md:p-8">
        <Outlet />
      </main>
    </div>
  )
}
