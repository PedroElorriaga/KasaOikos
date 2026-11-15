import type { ReactNode } from 'react'

// Ícones de traço do canvas, decorativos: o nome acessível vem do rótulo ao lado.
function Icone({ children }: { children: ReactNode }) {
  return (
    <svg
      aria-hidden="true"
      className="size-[22px] shrink-0 md:size-5"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      {children}
    </svg>
  )
}

export function IconeInicio() {
  return (
    <Icone>
      <path d="M3 10.5 12 3l9 7.5V20a1 1 0 0 1-1 1h-5v-6H9v6H4a1 1 0 0 1-1-1z" />
    </Icone>
  )
}

export function IconeTarefas() {
  return (
    <Icone>
      <rect x="3" y="3" width="18" height="18" rx="3" />
      <path d="m8 12 3 3 5-6" />
    </Icone>
  )
}

export function IconeCustos() {
  return (
    <Icone>
      <rect x="3" y="6" width="18" height="14" rx="2" />
      <path d="M3 10h18M16 15h2" />
    </Icone>
  )
}

export function IconeCompras() {
  return (
    <Icone>
      <circle cx="9" cy="20" r="1.5" />
      <circle cx="18" cy="20" r="1.5" />
      <path d="M3 4h2l2.4 11h11.2L21 8H6.2" />
    </Icone>
  )
}
