// Pool de tokens obtido uma vez no setup() (design D11): o Keycloak fica fora da medição.

import http from 'k6/http';
import {
  CLIENT_ID,
  KEYCLOAK_URL,
  SEED_HOUSEHOLDS,
  TOKEN_POOL,
  clientSecret,
  seedPassword,
} from './config.js';
import { call } from './api.js';

const LOGIN_BATCH = 20;

// Mesmo padrão de loadtest/common.py: seed-<lar>-<n>; o membro 1 é o admin.
export const seedUsername = (household, member) =>
  `seed-${String(household).padStart(5, '0')}-${member}`;

function loginRequest(username) {
  return {
    method: 'POST',
    url: `${KEYCLOAK_URL}/realms/home/protocol/openid-connect/token`,
    body: {
      grant_type: 'password',
      client_id: CLIENT_ID,
      client_secret: clientSecret(),
      username,
      password: seedPassword(),
    },
    params: { tags: { name: 'keycloak token' } },
  };
}

/** Tokens de vários usuários, em lotes paralelos. */
export function login(usernames) {
  const tokens = [];
  for (let i = 0; i < usernames.length; i += LOGIN_BATCH) {
    const batch = usernames.slice(i, i + LOGIN_BATCH);
    http.batch(batch.map(loginRequest)).forEach((r, j) => {
      if (r.status !== 200) {
        throw new Error(`login de ${batch[j]} falhou (${r.status}): o seed rodou com essa senha?`);
      }
      tokens.push(r.json('access_token'));
    });
  }
  return tokens;
}

/**
 * Admin e um membro de cada lar do pool, com o id do lar e do usuário (via GET /me).
 *
 * Os lares do pool ficam espalhados entre os do seed (1000 lares e pool 100 → 1, 10,
 * 19...). O último lar fica de fora: é reservado ao cenário smoke.
 */
export function tokenPool(size = TOKEN_POOL) {
  const available = SEED_HOUSEHOLDS - 1;
  const count = Math.min(size, available);
  const step = Math.floor(available / count);
  const households = Array.from({ length: count }, (_, i) => 1 + i * step);

  const usernames = households.flatMap((h) => [seedUsername(h, 1), seedUsername(h, 2)]);
  const tokens = login(usernames);
  return households.map((h, i) => {
    const [admin, member] = [tokens[2 * i], tokens[2 * i + 1]];
    return { seed: h, admin: whoAmI(admin, h), member: whoAmI(member, h) };
  });
}

function whoAmI(token, seed) {
  const me = call('GET', '/me', { token }).json();
  if (me.households.length !== 1) {
    throw new Error(`usuário do lar seed ${seed} deveria ter 1 lar, tem ${me.households.length}`);
  }
  return { token, userId: me.id, householdId: me.households[0].id, role: me.households[0].role };
}

export const pick = (items) => items[Math.floor(Math.random() * items.length)];
