// isolation (design D11): 20 VUs tentando agir em lares alheios; qualquer 2xx falha.
//
// A versão sob carga da suíte de isolamento (tarefa 5.9): quem ataca é admin no próprio
// lar, para o papel não mascarar a resposta, e toda rota com escopo de lar precisa
// responder 404 (o lar alheio é indistinguível de um lar inexistente).

import { Counter } from 'k6/metrics';
import { call } from '../lib/api.js';
import { pick, tokenPool } from '../lib/auth.js';
import { commonOptions } from '../lib/config.js';

export { handleSummary } from '../lib/summary.js';

const crossTenantSuccess = new Counter('cross_tenant_success');

export const options = {
  ...commonOptions,
  scenarios: {
    isolation: { executor: 'constant-vus', vus: 20, duration: __ENV.DURATION || '1m' },
  },
  thresholds: {
    cross_tenant_success: ['count==0'],
    checks: ['rate==1'],
  },
};

export function setup() {
  const pool = tokenPool();
  // Um convite pendente por lar: o ataque de revogação mira um convite que existe.
  for (const entry of pool) {
    entry.inviteId = call('POST', '/households/{household_id}/invites', {
      path: { household_id: entry.admin.householdId },
      token: entry.admin.token,
      body: {},
      expect: [201],
    }).json('id');
  }
  return { pool };
}

const ATTACKS = [
  ['GET', '/households/{household_id}'],
  ['PATCH', '/households/{household_id}', { name: 'invadido' }],
  ['GET', '/households/{household_id}/members'],
  ['PATCH', '/households/{household_id}/members/{user_id}', { role: 'admin' }],
  ['DELETE', '/households/{household_id}/members/{user_id}'],
  ['POST', '/households/{household_id}/invites', {}],
  ['GET', '/households/{household_id}/invites'],
  ['DELETE', '/households/{household_id}/invites/{invite_id}'],
];

export default function ({ pool }) {
  const attacker = pick(pool);
  let victim = pick(pool);
  while (victim.seed === attacker.seed) victim = pick(pool);

  const [method, route, body] = pick(ATTACKS);
  const response = call(method, route, {
    path: {
      household_id: victim.admin.householdId,
      user_id: victim.member.userId,
      invite_id: victim.inviteId,
    },
    token: attacker.admin.token,
    body,
    expect: [404],
  });
  if (response.status >= 200 && response.status < 300) {
    crossTenantSuccess.add(1, { name: route, method });
  }
}
