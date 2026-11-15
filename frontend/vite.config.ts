import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vitest/config'

export default defineConfig({
  plugins: [react(), tailwindcss()],
  // Lê o `.env` da raiz do repositório. Só variáveis VITE_* chegam ao navegador.
  envDir: '..',
  server: {
    // Porta fixa: as redirect URIs do realm (Keycloak) são exatas para localhost:5173.
    port: 5173,
    strictPort: true,
  },
  test: {
    environment: 'jsdom',
    setupFiles: ['./src/testes/setup.ts'],
    // Valores fictícios: os testes não dependem do `.env` de quem roda.
    env: {
      VITE_OIDC_AUTHORITY: 'http://keycloak.teste/realms/teste',
      VITE_OIDC_CLIENT_ID: 'cliente-teste',
      VITE_API_URL: 'http://api.teste',
    },
  },
})
