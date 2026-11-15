/// <reference types="vite/client" />

// Variáveis lidas do `.env` da raiz (ver `.env.example`). Nenhuma é segredo.
interface ImportMetaEnv {
  readonly VITE_OIDC_AUTHORITY?: string
  readonly VITE_OIDC_CLIENT_ID?: string
  readonly VITE_API_URL?: string
}
