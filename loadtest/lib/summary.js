// handleSummary compartilhado (design D11): grava o resultado em JSON com o contexto da
// execução (data, git sha, configuração da API, latência de rede) e imprime um resumo.
//
// O contexto vem do runner (loadtest/run.py) pelas variáveis RUN_*. O JSON guarda todas
// as métricas do k6: é o histórico que permite comparar as fases.

const env = (name, fallback = null) => __ENV[name] || fallback;

function metadata() {
  return {
    run_id: env('RUN_ID'),
    scenario: env('RUN_SCENARIO'),
    started_at: env('RUN_STARTED_AT'),
    git_sha: env('RUN_GIT_SHA'),
    api_url: env('API_URL'),
    api_config: {
      workers: Number(env('RUN_WORKERS')) || null,
      db_pool_size: Number(env('RUN_DB_POOL_SIZE')) || null,
    },
    network: { tcp_connect_rtt_ms: Number(env('RUN_RTT_MS')) || null },
    load: {
      seed_households: Number(env('SEED_HOUSEHOLDS')) || null,
      token_pool: Number(env('TOKEN_POOL')) || null,
      rate: Number(env('RATE')) || null,
      duration: env('DURATION'),
    },
  };
}

function thresholds(metrics) {
  const result = {};
  for (const [name, metric] of Object.entries(metrics)) {
    for (const [expr, { ok }] of Object.entries(metric.thresholds || {})) {
      result[`${name}: ${expr}`] = ok;
    }
  }
  return result;
}

const ms = (value) => (value === undefined ? '-' : `${value.toFixed(1)} ms`);

function text(data, meta, passed) {
  const m = data.metrics;
  const lines = [
    '',
    `== ${meta.run_id || meta.scenario || 'k6'} (${(data.state.testRunDurationMs / 1000).toFixed(0)} s)`,
  ];
  if (m.http_reqs) {
    lines.push(
      `requisições: ${m.http_reqs.values.count} (${m.http_reqs.values.rate.toFixed(1)}/s)` +
        ` · falhas: ${(100 * m.http_req_failed.values.rate).toFixed(2)}%`,
    );
  }
  // Por tipo (kind:read/write) quando o cenário tem thresholds assim; a métrica geral
  // inclui os logins no Keycloak do setup() e distorce a leitura.
  const byKind = Object.keys(m).filter((name) => name.startsWith('http_req_duration{kind:'));
  for (const name of byKind.length ? byKind : ['http_req_duration']) {
    const metric = m[name];
    if (metric) {
      const v = metric.values;
      lines.push(
        `${name.padEnd(42)} p50 ${ms(v['p(50)'])}  p95 ${ms(v['p(95)'])}  p99 ${ms(v['p(99)'])}`,
      );
    }
  }
  if (m.dropped_iterations) {
    // O k6 não teve VUs livres para manter a taxa pedida: a carga real foi menor.
    lines.push(`iterações descartadas pelo k6: ${m.dropped_iterations.values.count}`);
  }
  if (m.checks) {
    lines.push(`checks: ${m.checks.values.passes} ok, ${m.checks.values.fails} falharam`);
  }
  for (const [name, ok] of Object.entries(passed)) {
    lines.push(`${ok ? '✓' : '✗'} ${name}`);
  }
  return lines.join('\n') + '\n';
}

export function handleSummary(data) {
  const meta = metadata();
  const passed = thresholds(data.metrics);
  const outputs = { stdout: text(data, meta, passed) };
  const file = env('RUN_RESULT_FILE');
  if (file) {
    outputs[file] = JSON.stringify(
      { meta, thresholds: passed, state: data.state, metrics: data.metrics },
      null,
      2,
    );
  }
  return outputs;
}
