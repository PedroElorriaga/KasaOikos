// Smoke test (M0.8): poucos usuários por pouco tempo em /health e /me, com thresholds.
// Pré-requisitos: Postgres, Keycloak (com o client `kasaoikos-carga`) e a API rodando.
//
//   k6 run load/smoke.js        (ou: just smoke)
//
// Configuração: variáveis de ambiente; o que faltar é lido do `.env` da raiz do repositório.
//   API_URL                    padrão http://localhost:8000
//   OIDC_ISSUER                realm do Keycloak (já está no .env)
//   K6_USUARIO                 padrão ana.teste
//   KC_SENHA_USUARIO_TESTE_1   senha do usuário (já está no .env)
// A senha e o token nunca são impressos.

import http from 'k6/http'
import { check, fail, sleep } from 'k6'

// `open` só funciona aqui (init), com caminho relativo a este arquivo.
function lerDotEnv() {
  let conteudo
  try {
    conteudo = open('../.env')
  } catch {
    return {}
  }
  const valores = {}
  for (const linha of conteudo.split(/\r?\n/)) {
    const m = linha.match(/^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*?)\s*$/)
    if (m) valores[m[1]] = m[2].replace(/^(['"])(.*)\1$/, '$2')
  }
  return valores
}

const dotEnv = lerDotEnv()
const config = (nome, padrao) => __ENV[nome] || dotEnv[nome] || padrao

const API_URL = config('API_URL', 'http://localhost:8000').replace(/\/$/, '')
const OIDC_ISSUER = config('OIDC_ISSUER', '').replace(/\/$/, '')
const USUARIO = config('K6_USUARIO', 'ana.teste')
const SENHA = config('KC_SENHA_USUARIO_TESTE_1', '')
const CLIENT_ID = 'kasaoikos-carga'

export const options = {
  vus: 5,
  duration: '30s',
  // Só as requisições à API (tag `escopo: api`); a do token, no setup, fica de fora.
  thresholds: {
    'http_req_duration{escopo:api}': ['p(95)<300'],
    'http_req_failed{escopo:api}': ['rate<0.01'],
    checks: ['rate>0.99'],
  },
}

// Roda uma vez, antes dos VUs.
export function setup() {
  if (!OIDC_ISSUER || !SENHA) {
    fail('defina OIDC_ISSUER e KC_SENHA_USUARIO_TESTE_1 (no ambiente ou no .env)')
  }
  const resposta = http.post(
    `${OIDC_ISSUER}/protocol/openid-connect/token`,
    { grant_type: 'password', client_id: CLIENT_ID, username: USUARIO, password: SENHA },
    { tags: { name: 'token' }, responseCallback: http.expectedStatuses(200) },
  )
  if (resposta.status !== 200) {
    // Só o status: o corpo do erro pode ecoar dados da requisição.
    fail(`token: Keycloak respondeu ${resposta.status} (o client ${CLIENT_ID} existe no realm?)`)
  }
  // O access token vale 5 min (realm); o teste dura 30 s.
  return { token: resposta.json('access_token') }
}

export default function (dados) {
  const saude = http.get(`${API_URL}/health`, { tags: { name: '/health', escopo: 'api' } })
  check(saude, { '/health 200': (r) => r.status === 200 })

  const me = http.get(`${API_URL}/me`, {
    headers: { Authorization: `Bearer ${dados.token}` },
    tags: { name: '/me', escopo: 'api' },
  })
  check(me, {
    '/me 200': (r) => r.status === 200,
    '/me traz o usuário': (r) => r.status === 200 && Boolean(r.json('id')),
  })

  sleep(1)
}
