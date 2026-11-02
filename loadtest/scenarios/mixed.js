// mixed (design D11): 90% leitura + 10% escrita, taxa de chegada constante.
//
// As leituras são as do read-heavy. As escritas, sempre como admin do lar: criar e
// revogar um convite (duas requisições) ou renomear o lar para o nome original do
// seed (os dados não derivam entre execuções).

import { call } from '../lib/api.js';
import { pick, tokenPool } from '../lib/auth.js';
import { DURATION, RATE, commonOptions } from '../lib/config.js';
import { read } from './read-heavy.js';

export { handleSummary } from '../lib/summary.js';

export const options = {
  ...commonOptions,
  scenarios: {
    mixed: {
      executor: 'constant-arrival-rate',
      rate: RATE,
      timeUnit: '1s',
      duration: DURATION,
      preAllocatedVUs: 50,
      maxVUs: 1000,
    },
  },
  thresholds: {
    http_req_failed: ['rate<0.01'],
    'http_req_duration{kind:read}': ['p(95)<200'],
    // Sem meta no design para escrita; ponto de partida, a recalibrar como os demais.
    'http_req_duration{kind:write}': ['p(95)<500'],
  },
};

export function setup() {
  return { pool: tokenPool() };
}

function write(pool) {
  const entry = pick(pool);
  const path = { household_id: entry.admin.householdId };
  const token = entry.admin.token;
  if (Math.random() < 0.5) {
    const invite = call('POST', '/households/{household_id}/invites', {
      path,
      token,
      body: {},
      expect: [201],
    });
    call('DELETE', '/households/{household_id}/invites/{invite_id}', {
      path: { ...path, invite_id: invite.json('id') },
      token,
      expect: [204],
    });
  } else {
    const name = `Seed ${String(entry.seed).padStart(5, '0')}`;
    call('PATCH', '/households/{household_id}', { path, token, body: { name } });
  }
}

export default function ({ pool }) {
  if (Math.random() < 0.9) {
    read(pool);
  } else {
    write(pool);
  }
}
