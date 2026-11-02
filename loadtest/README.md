# Testes de carga (k6)

Baseline da Fase 1 (design D11). O k6 roda na **estação**; o alvo é a API no **servidor**. Rodar os dois na mesma máquina serve para desenvolver os cenários, não para medir: o k6, a API e o stack disputam a mesma CPU.

```
loadtest/
  seed.py            usuários no Keycloak + lares e memberships no Postgres
  run.py             roda um cenário com o contexto da execução e grava o resultado
  common.py          leitura do .env compartilhada
  lib/               biblioteca k6: config, chamadas à API, pool de tokens, handleSummary
  scenarios/         smoke, isolation, read-heavy, mixed
  results/           resultados oficiais (versionados)
  .tmp/              resultados de desenvolvimento (ignorados pelo git)
```

## Configuração

Contra o servidor, copie `loadtest/.env.example` para `loadtest/.env` (não versionado) e preencha com os valores do `infra/.env` de lá. Contra o Compose da própria estação, use `--env-file infra/.env`: as chaves são as mesmas.

Variáveis de ambiente têm precedência sobre o arquivo.

## 1. Seed

```bash
uv run python loadtest/seed.py                       # 1.000 lares × 3 membros (padrão)
uv run python loadtest/seed.py --households 10000    # acrescenta os que faltam
```

- Usuários `seed-<lar>-<n>` (o `n = 1` é o admin), com e-mail `@seed.home.test` e a senha `HM_SEED_USER_PASSWORD`.
- **Idempotente**: ids determinísticos, o Keycloak pula quem já existe e o SQL usa `ON CONFLICT DO NOTHING`. Rodar de novo não duplica; com mais lares, só acrescenta.
- O hash da senha é calculado uma vez no seed e importado pronto (PBKDF2). Deixar o Keycloak calcular um Argon2 por usuário custa ~40 ms cada. No primeiro login, o Keycloak refaz o hash no algoritmo dele (~0,3 s, uma vez por usuário).
- O último lar (`seed-01000-*` com o padrão) é reservado ao cenário `smoke`; os demais cenários não o usam.

## 2. Cenários

```bash
uv run python loadtest/run.py smoke
uv run python loadtest/run.py isolation
uv run python loadtest/run.py read-heavy --rate 200 --duration 5m
uv run python loadtest/run.py mixed --rate 100 --duration 5m
```

| Cenário | Executor | O que faz | Thresholds |
|---|---|---|---|
| `smoke` | 1 VU, 30 s | percorre todas as rotas validando o contrato (inclui 401, 404 e 422 em Problem Details) | nenhum check falha, nenhum status inesperado |
| `isolation` | 20 VUs, 1 min | admin do lar A tenta cada rota com escopo de lar no lar B | `cross_tenant_success == 0`, toda resposta é `404` |
| `read-heavy` | `ramping-arrival-rate` | `GET /me`, `/households/{id}`, `/households/{id}/members`; rampa de 1 min até `--rate`, sustenta `--duration`, desce em 30 s | falhas < 1%, p95 de leitura < 200 ms |
| `mixed` | `constant-arrival-rate` | 90% leitura + 10% escrita (criar e revogar convite, renomear o lar) | falhas < 1%, p95 leitura < 200 ms, p95 escrita < 500 ms |

Os thresholds são os iniciais do design, a recalibrar depois da primeira baseline.

Opções do `run.py`: `--rate` (req/s), `--duration`, `--token-pool` (lares cujos admin e membro recebem token no `setup()`; padrão 100), `--no-prometheus` e `--save`.

## 3. Resultados

Cada execução tem um id `<data UTC>-<git sha>-<cenário>` (com `-dirty` se havia mudanças não commitadas). O mesmo id vira:

- o arquivo de resultado: `loadtest/.tmp/<id>.json` ou, com `--save`, `loadtest/results/<id>.json`. Ele guarda a configuração da API (`HM_WORKERS`, `HM_DB_POOL_SIZE` do `.env`), o RTT TCP até a API, os thresholds e todas as métricas do k6;
- a tag `testid` das métricas enviadas ao Prometheus por remote write (histograma nativo). No Grafana, a linha "Carga do k6" do dashboard *API Overview* mostra cada execução e compara o p95 do cliente com o da API.

Use `--save` só nas execuções oficiais (baseline e experimentos), feitas a partir de um commit limpo.

## Leitura dos números

- **Cliente × servidor**: o p95 do k6 inclui rede e a fila antes da API aceitar a requisição; o da API, não. Uma distância que cresce sob carga indica fila.
- **`dropped_iterations`**: o k6 ficou sem VU livre para manter a taxa pedida. A carga real foi menor que a pedida, e a execução não vale como medição daquela taxa.
- **Span `connect` longo no Tempo**: é a espera por uma conexão livre no pool do SQLAlchemy (o span envolve o `Engine.connect`), não a abertura de uma conexão TCP. É o sinal de pool pequeno para a concorrência (experimento `workers × pool_size`).
- **Na estação (Docker Desktop)**: já se viu uma rajada de requisições esperar ~3,6 s antes de chegar à API (`waiting` alto no k6, conexão TCP instantânea e nada de lento do lado da API). A suspeita é o encaminhamento de portas do Docker Desktop recebendo dezenas de conexões novas de uma vez. É mais um motivo para medir só contra o servidor.
