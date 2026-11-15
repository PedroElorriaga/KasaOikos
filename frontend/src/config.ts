function obrigatoria(nome: string, valor: string | undefined): string {
  if (!valor) {
    throw new Error(`Variável ${nome} ausente: defina-a no .env da raiz (veja .env.example).`)
  }
  return valor
}

// Acesso estático a cada variável: é o que o Vite substitui no build.
export const config = {
  oidcAuthority: obrigatoria('VITE_OIDC_AUTHORITY', import.meta.env.VITE_OIDC_AUTHORITY),
  oidcClientId: obrigatoria('VITE_OIDC_CLIENT_ID', import.meta.env.VITE_OIDC_CLIENT_ID),
  apiUrl: obrigatoria('VITE_API_URL', import.meta.env.VITE_API_URL),
}
