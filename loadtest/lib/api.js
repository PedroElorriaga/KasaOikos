// Chamadas à API com nome por rota template, status esperado e check automático.

import http from 'k6/http';
import { check } from 'k6';
import { API_URL } from './config.js';

const expectedCallbacks = {};

function expectedStatuses(statuses) {
  const key = statuses.join(',');
  if (!(key in expectedCallbacks)) {
    expectedCallbacks[key] = http.expectedStatuses(...statuses);
  }
  return expectedCallbacks[key];
}

/**
 * Faz uma requisição e confere o status.
 *
 * @param {string} method
 * @param {string} route  rota template, ex. "/households/{household_id}": vira a tag "name"
 * @param {object} opts
 * @param {Object<string, string>} [opts.path]  valores dos parâmetros da rota
 * @param {string} [opts.token]
 * @param {object} [opts.body]  enviado como JSON
 * @param {number[]} [opts.expect]  status esperados; os demais contam em http_req_failed
 * @param {string} [opts.kind]  "read" ou "write": tag para os thresholds por tipo
 */
export function call(method, route, opts = {}) {
  const { path = {}, token, body, expect = [200], kind = method === 'GET' ? 'read' : 'write' } = opts;
  const url = API_URL + route.replace(/\{(\w+)\}/g, (_, name) => path[name]);
  const headers = {};
  if (token) headers.Authorization = `Bearer ${token}`;
  if (body !== undefined) headers['Content-Type'] = 'application/json';

  const response = http.request(method, url, body === undefined ? null : JSON.stringify(body), {
    headers,
    tags: { name: route, kind },
    responseCallback: expectedStatuses(expect),
  });
  check(response, {
    [`${method} ${route} → ${expect.join('|')}`]: (r) => expect.includes(r.status),
  });
  return response;
}

export const isProblem = (r) =>
  r.headers['Content-Type'] === 'application/problem+json' && r.json('status') === r.status;
