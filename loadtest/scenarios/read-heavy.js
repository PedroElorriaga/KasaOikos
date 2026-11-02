// read-heavy (design D11): leituras com taxa de chegada em rampa (modelo aberto).
//
// Cada iteração é uma requisição, então RATE é req/s. Rampa até RATE em 1 min,
// sustenta por DURATION e desce em 30 s. Modelo aberto: as requisições chegam no ritmo
// pedido mesmo se a API ficar lenta (sem "coordinated omission"); se faltar VU livre,
// o k6 descarta a iteração e conta em dropped_iterations.

import { call } from '../lib/api.js';
import { pick, tokenPool } from '../lib/auth.js';
import { DURATION, RATE, commonOptions } from '../lib/config.js';

export { handleSummary } from '../lib/summary.js';

export const options = {
  ...commonOptions,
  scenarios: {
    read_heavy: {
      executor: 'ramping-arrival-rate',
      startRate: 0,
      timeUnit: '1s',
      preAllocatedVUs: 50,
      maxVUs: 1000,
      stages: [
        { target: RATE, duration: '1m' },
        { target: RATE, duration: DURATION },
        { target: 0, duration: '30s' },
      ],
    },
  },
  // Thresholds iniciais do design, a recalibrar depois da primeira baseline.
  thresholds: {
    http_req_failed: ['rate<0.01'],
    'http_req_duration{kind:read}': ['p(95)<200'],
  },
};

export function setup() {
  return { pool: tokenPool() };
}

export function read(pool) {
  const entry = pick(pool);
  const user = Math.random() < 0.5 ? entry.admin : entry.member;
  const path = { household_id: user.householdId };
  switch (Math.floor(Math.random() * 3)) {
    case 0:
      return call('GET', '/me', { token: user.token });
    case 1:
      return call('GET', '/households/{household_id}', { path, token: user.token });
    default:
      return call('GET', '/households/{household_id}/members', { path, token: user.token });
  }
}

export default function ({ pool }) {
  read(pool);
}
