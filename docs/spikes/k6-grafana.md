# Spike: k6 + Grafana (M0.8)

Objetivo: reduzir o risco "nunca usou k6 nem Grafana" (README, riscos) antes da fase 2, com o mínimo
que já serve ao projeto: traces e logs da API no `grafana/otel-lgtm` local e um smoke test k6.

## O que foi feito

- **Traces:** OpenTelemetry na API (FastAPI + SQLAlchemy), exportando por OTLP HTTP
  (`OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4318`) para o `lgtm` do `--profile obs`.
  Cada requisição vira um trace: span `GET /me` (servidor) com os spans `connect` e `SELECT` do banco.
- **Logs:** JSON no stdout com `trace_id`, que é o mesmo id procurado no Tempo. Uma linha `app.acesso`
  por requisição, sem IP, query string, e-mail nem token.
- **k6:** `load/smoke.js` (ou `just smoke`): 5 VUs por 30 s em `/health` e `/me`.
  - Thresholds: p95 < 300 ms, erros < 1%, checks > 99%.
  - O token vem do client `kasaoikos-carga` (password grant, só local, ver ADR-0002).

## Resultado (local, Windows + Docker Desktop, 15/11/2026)

| Métrica (só requisições à API) | Valor |
|---|---|
| Requisições | 280 (140 iterações) |
| p95 | 17,9 ms |
| Mediana | 8,4 ms |
| Máximo | 2,08 s |
| Erros | 0% |
| Checks | 420/420 |

## O que aprendi

- **Instrumentar é pouco código, os detalhes é que custam.**
  - O instrumentador do SQLAlchemy é global, faz patch de `sqlalchemy.create_engine` e liga uma
    única vez por processo. Um `from sqlalchemy import create_engine` feito antes disso escapa da
    instrumentação. Por isso o `app/db.py` chama a função pelo módulo.
  - A versão 0.66 da instrumentação não aceita SQLAlchemy 2.1: ela se recusa a instrumentar, com só um
    aviso no log. O projeto ficou em `<2.1` até a 0.67.
- **O span do banco leva o SQL com placeholders**, sem os valores. O SQL é bom para achar
  consulta lenta e não expõe dados pessoais.
- **Spans `receive`/`send` do ASGI** dobram o tamanho do trace sem informação útil e foram desligados.
- **Log de acesso do uvicorn:** roda fora do span (sem `trace_id`) e traz o IP do cliente. Um
  middleware próprio dentro do span resolve as duas coisas.
- **k6:**
  - `setup()` roda uma vez e o retorno chega a todos os VUs, o lugar certo para pegar o token.
  - As requisições do `setup()` entram nas métricas globais. Filtrar os thresholds por tag
    (`http_req_duration{escopo:api}`) tira a do Keycloak da conta.
  - `open()` só funciona no contexto de init, com caminho relativo ao script.
  - `__ENV` inclui as variáveis do sistema.
- **O máximo de 2,08 s** é a primeira conexão ao banco e bate com o `connect_timeout=2` do engine.
  A suspeita é que, no Windows, `localhost` resolve primeiro para `::1`, o Postgres só escuta em
  `127.0.0.1` e a primeira tentativa espera o timeout antes de cair no IPv4. O pool esconde isso
  depois da primeira conexão. Não corrigido aqui; ver fase 2.

## O que funcionou bem

- A imagem `grafana/otel-lgtm` traz Grafana + Tempo + Loki + Prometheus com os data sources prontos.
  Basta apontar o OTLP para ela.
- O Grafana expõe a API do Tempo pelo proxy de data source
  (`/api/datasources/proxy/uid/tempo/api/search?q=<TraceQL>`), o que dá para conferir traces por script.
  TraceQL usado: `{resource.service.name="kasaoikos-api" && span.http.route="/me"}`.
- Thresholds do k6 com `p(95)` e `rate` são diretos e o exit code serve para o CI.

## O que fica para a fase 2

- **Métricas** (RED por rota: taxa, erros, duração) via OTel → Prometheus, e o dashboard do README.
- **Logs no Loki via OTLP** (hoje só no stdout), para ir do trace ao log no Grafana.
- **Cenários de carga reais** (rampa, carga sustentada, pico) com as rotas de casa, tarefas e custos, e
  a meta de desempenho documentada (ex.: p95 < 300 ms com N usuários).
- **Vários usuários de carga** (hoje só `ana.teste`), para não medir só o caminho com cache quente.
- **Investigar a primeira conexão de 2 s** (`127.0.0.1` no `DATABASE_URL` local ou Postgres também
  em `::1`).
- **Observabilidade em staging:** o `lgtm` pesa para a VPS (ADR-0003). Avaliar o plano gratuito do
  Grafana Cloud.
- **Remover `kasaoikos-carga` do realm de staging** (M0.9) e definir como a carga em staging obtém token.
