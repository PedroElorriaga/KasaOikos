// Configuração lida do ambiente. Quem preenche é o runner (loadtest/run.py), a partir do
// --env-file; rodar `k6 run` direto também funciona, com as mesmas variáveis.

function required(name) {
  const value = __ENV[name];
  if (!value) {
    throw new Error(`defina ${name} (o loadtest/run.py preenche a partir do --env-file)`);
  }
  return value;
}

export const API_URL = __ENV.API_URL || 'http://localhost:8000';
export const KEYCLOAK_URL = __ENV.KEYCLOAK_URL || 'http://localhost:8080';
export const CLIENT_ID = 'home-loadtest';

export const clientSecret = () => required('HM_LOADTEST_CLIENT_SECRET');
export const seedPassword = () => required('HM_SEED_USER_PASSWORD');

// Quantos lares o seed criou e de quantos deles o setup() obtém tokens.
export const SEED_HOUSEHOLDS = Number(__ENV.SEED_HOUSEHOLDS || 1000);
export const TOKEN_POOL = Number(__ENV.TOKEN_POOL || 100);

// Carga dos cenários de arrival rate: requisições (iterações) por segundo e duração.
export const RATE = Number(__ENV.RATE || 50);
export const DURATION = __ENV.DURATION || '2m';

// Opções comuns a todos os cenários.
export const commonOptions = {
  // Tokens de até 200 usuários, com o rehash do Keycloak no primeiro login de cada um.
  setupTimeout: '3m',
  summaryTrendStats: ['avg', 'p(50)', 'p(95)', 'p(99)', 'max'],
  // Sem "url" nas tags (cada id de lar viraria uma série no Prometheus, a mesma
  // explosão de cardinalidade das métricas da API); as requisições se agrupam por
  // "name", a rota template.
  systemTags: ['status', 'method', 'name', 'group', 'check', 'scenario', 'expected_response'],
};
