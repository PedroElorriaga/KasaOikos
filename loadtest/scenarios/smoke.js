// smoke (design D11): 1 VU percorrendo todas as rotas e validando o contrato.
// Também é o tráfego da verificação visual do dashboard (tarefa 6.5).
//
// Usa os dois primeiros usuários do último lar do seed, que os outros cenários deixam
// de fora: o admin cria um lar "Smoke" por execução e o outro entra e sai dele.

import { check, group, sleep } from 'k6';
import { call, isProblem } from '../lib/api.js';
import { login, seedUsername } from '../lib/auth.js';
import { SEED_HOUSEHOLDS, commonOptions } from '../lib/config.js';

export { handleSummary } from '../lib/summary.js';

export const options = {
  ...commonOptions,
  scenarios: {
    smoke: { executor: 'constant-vus', vus: 1, duration: __ENV.DURATION || '30s' },
  },
  // Contrato: nenhum status inesperado e nenhum check falhando.
  thresholds: { checks: ['rate==1'], http_req_failed: ['rate==0'] },
};

export function setup() {
  const [admin, guest] = login([seedUsername(SEED_HOUSEHOLDS, 1), seedUsername(SEED_HOUSEHOLDS, 2)]);
  const guestId = call('GET', '/me', { token: guest }).json('id');
  const created = call('POST', '/households', {
    token: admin,
    body: { name: 'Smoke' },
    expect: [201],
  });
  check(created, { 'quem cria o lar é admin': (r) => r.json('role') === 'admin' });
  return { admin, guest, guestId, household: created.json('id') };
}

export default function ({ admin, guest, guestId, household }) {
  const path = { household_id: household };
  const member = { household_id: household, user_id: guestId };

  group('saúde e autenticação', () => {
    call('GET', '/health/live');
    call('GET', '/health/ready');
    const anonymous = call('GET', '/me', { expect: [401] });
    check(anonymous, {
      '401 em Problem Details com WWW-Authenticate': (r) =>
        isProblem(r) && r.headers['Www-Authenticate'] === 'Bearer',
    });
  });

  group('lar', () => {
    const me = call('GET', '/me', { token: admin });
    check(me, { '/me lista o lar do smoke': (r) => r.json('households').some((h) => h.id === household) });
    const got = call('GET', '/households/{household_id}', { path, token: admin });
    check(got, { 'GET do lar traz o papel de quem pergunta': (r) => r.json('role') === 'admin' });
    call('PATCH', '/households/{household_id}', { path, token: admin, body: { name: `Smoke ${__ITER}` } });
    const invalid = call('PATCH', '/households/{household_id}', {
      path,
      token: admin,
      body: { name: '' },
      expect: [422],
    });
    check(invalid, { '422 lista o campo inválido': (r) => isProblem(r) && r.json('errors').length === 1 });
  });

  group('convite e membros', () => {
    const invite = call('POST', '/households/{household_id}/invites', {
      path,
      token: admin,
      body: {},
      expect: [201],
    });
    const listed = call('GET', '/households/{household_id}/invites', { path, token: admin });
    check(listed, {
      'listagem de convites não expõe o código': (r) =>
        r.json().some((i) => i.id === invite.json('id')) && !r.body.includes(invite.json('code')),
    });
    call('POST', '/invites/accept', { token: guest, body: { code: invite.json('code') } });

    const members = call('GET', '/households/{household_id}/members', { path, token: guest });
    check(members, {
      'convidado entra como member': (r) =>
        r.json().some((m) => m.user_id === guestId && m.role === 'member'),
    });
    call('PATCH', '/households/{household_id}/members/{user_id}', {
      path: member,
      token: admin,
      body: { role: 'admin' },
    });
    call('PATCH', '/households/{household_id}/members/{user_id}', {
      path: member,
      token: admin,
      body: { role: 'member' },
    });
    call('DELETE', '/households/{household_id}/members/{user_id}', {
      path: member,
      token: admin,
      expect: [204],
    });
    // Revogação imediata (cache de membership invalidado) e 404, não 403.
    const gone = call('GET', '/households/{household_id}', { path, token: guest, expect: [404] });
    check(gone, { 'ex-membro recebe 404 em Problem Details': isProblem });

    const revoked = call('POST', '/households/{household_id}/invites', {
      path,
      token: admin,
      body: {},
      expect: [201],
    });
    call('DELETE', '/households/{household_id}/invites/{invite_id}', {
      path: { household_id: household, invite_id: revoked.json('id') },
      token: admin,
      expect: [204],
    });
  });

  sleep(1);
}
