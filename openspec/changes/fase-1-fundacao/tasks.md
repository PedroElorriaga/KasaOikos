## 1. Repositório e ferramentas

- [x] 1.1 Inicializar git, `.gitignore`, `.editorconfig` e `uv` workspace na raiz (D1), com membros `apps/*`, `packages/*` e `modules/*`; verificar com `uv sync` sem erros
- [x] 1.2 Criar os pacotes `hm_platform`, `hm_identity`, `hm_finance`, `hm_tasks`, `hm_inventory` e `hm_notifications`, cada um com `public.py`, `api/`, `domain/`, `infra/` e `migrations/`, e o app `apps/api`; verificar que `uv run python -c "import hm_identity, hm_finance"` funciona
- [x] 1.3 Configurar `ruff` (lint + format), `mypy --strict` e `pre-commit`; verificar com `uv run ruff check . && uv run mypy .` passando no esqueleto
- [x] 1.4 Configurar os contratos do `import-linter` (independence, layers, forbidden; D2) e criar um teste-sentinela temporário que viola uma fronteira; verificar que `lint-imports` falha com ele e passa sem ele
- [x] 1.5 Criar o workflow do GitHub Actions (lint, mypy, import-linter, pytest com serviço Docker); verificar com execução verde em um PR de teste

## 2. Infraestrutura local (Docker Compose)

- [x] 2.1 Criar `infra/compose.yaml` com Postgres 17 (+ pgvector), Redis/Valkey e Keycloak 26, com healthchecks e volumes nomeados; verificar com `docker compose up -d` e todos os serviços `healthy`
- [x] 2.2 Criar o script de init do Postgres: database `home`, roles `hm_migrator` (owner) e `hm_app` (NOBYPASSRLS), schemas por módulo e grants (D4); verificar via `psql` que `hm_app` não é owner e tem `rolbypassrls = false`
- [x] 2.3 Criar e exportar o realm `home` (`infra/keycloak/realm-home.json`) com os clients `home-api`, `home-mobile` (PKCE) e `home-loadtest` (direct grants, token de 1 h) e o mapper de audiência; verificar obtendo um token com `curl` e inspecionando `iss`/`aud`
- [x] 2.4 Adicionar ao Compose o OTel Collector, Prometheus (com remote-write receiver e exemplars), Tempo, Loki e Grafana com datasources provisionados (D8); verificar que o Grafana abre com os 3 datasources em estado OK
- [x] 2.5 Documentar no `README.md` como subir o ambiente no servidor e como apontar a estação Windows para ele (variáveis de host/IP); verificar seguindo o README do zero em um clone limpo

## 3. Plataforma: configuração, banco e testes

- [x] 3.1 Implementar `hm_platform.settings` com `pydantic-settings` (DB, Redis, OIDC, OTel, workers) e testes de carga de configuração por variável de ambiente; verificar com `pytest packages/platform`
- [x] 3.2 Implementar engine/sessão async do SQLAlchemy com asyncpg, gerador UUIDv7 e base declarativa por schema; verificar com teste de conexão em testcontainers
- [x] 3.3 Implementar o runner `hm migrate`, que executa o Alembic de cada módulo em ordem com `version_table` no próprio schema (D3); verificar com teste que aplica e reverte todas as migrações num banco vazio
- [x] 3.4 Criar a infraestrutura de testes compartilhada: fixture de Postgres (testcontainers, uma vez por sessão), transação revertida por teste, fixture de Redis e app de teste; verificar com um teste trivial de cada fixture

## 4. Autenticação (spec `identity/authentication`)

- [x] 4.1 Criar fixture de testes com par RSA gerado em memória, JWKS falso e fábrica de tokens (válido, expirado, iss/aud errados, `kid` desconhecido); verificar que a fábrica gera tokens decodificáveis com a chave pública
- [x] 4.2 Implementar a validação de JWT com cache de JWKS e refetch limitado em `kid` desconhecido (D5), escrevendo junto os testes dos cenários "Token válido/ausente/expirado/emissor ou audiência/assinatura inválida" e "Chave nova após rotação"; verificar com `pytest -k authentication`
- [x] 4.3 Criar a tabela `identity.users` (migração) e o provisionamento just-in-time que grava apenas quando há mudança, com testes "Primeiro acesso" e "Dados alterados no provedor"; verificar com pytest

## 5. Lares e tenancy (specs `identity/households` e `platform/tenant-isolation`)

- [x] 5.1 Criar as migrações de `households`, `memberships` e `invites`, com RLS habilitado e forçado e as políticas especiais de D4; verificar com teste SQL direto como `hm_app` (sem lar ativo → 0 linhas)
- [x] 5.2 Implementar o teste de guarda que percorre `information_schema` e falha se alguma tabela com `household_id` estiver sem RLS habilitado e forçado; verificar criando uma tabela de teste sem RLS e vendo o teste falhar
- [x] 5.3 Implementar a dependency de tenant (path vs. header, divergência, malformado; `set_config` por transação) com os testes da requirement "Determinação do lar ativo"; verificar com pytest
- [x] 5.4 Implementar o cache de membership no Redis com invalidação pós-commit e `require_role` (D6), com os testes de "Verificação de membership" e "Revogação imediata de acesso"; verificar com pytest
- [x] 5.5 Implementar `POST /households`, `GET/PATCH /households/{id}` e `GET /me`, com testes de criação, nome inválido, renomeação por admin/member, listagem de lares e isolamento; verificar com pytest
- [x] 5.6 Implementar `GET /households/{id}/members`, a alteração de papel e a remoção/saída com a regra do último admin (`409`), com testes de todos os cenários das requirements correspondentes; verificar com pytest
- [x] 5.7 Implementar os convites (criação com hash SHA-256, listagem, revogação) e a função `identity.redeem_invite` com `SECURITY DEFINER` e `search_path` fixo (D7), com testes de aceite válido, expirado/usado/revogado (`410`), inexistente (`404`) e já membro (`409`); verificar com pytest
- [x] 5.8 Escrever um teste de concorrência em que dois usuários aceitam o mesmo convite simultaneamente; verificar que exatamente um recebe sucesso
- [x] 5.9 Escrever a suíte parametrizada de isolamento: para cada rota com escopo de lar, um usuário do lar A acessando o lar B recebe `404`; verificar que a suíte cobre todas as rotas registradas (o teste falha se surgir rota nova sem caso)

## 6. Observabilidade (spec `platform/observability`)

- [x] 6.1 Implementar `/health/live` e `/health/ready` (checagem de DB e Redis), com testes de sistema saudável e banco indisponível; verificar com pytest
- [x] 6.2 Configurar o OTel SDK (traces + métricas via OTLP) com auto-instrumentação de FastAPI, SQLAlchemy e Redis, e o middleware `X-Trace-Id`, com testes de "novo trace" e "continuidade de `traceparent`" usando um exporter em memória; verificar com pytest
- [x] 6.3 Garantir que as métricas HTTP usam a rota template e não têm rótulos de alta cardinalidade, com teste que inspeciona os rótulos de uma métrica de rota parametrizada; verificar com pytest
- [x] 6.4 Configurar `structlog` em JSON com trace id, user id e household id, e o processador de redação de dados sensíveis, com testes de correlação e de redação de token e código de convite; verificar com pytest
- [x] 6.5 Provisionar o dashboard "API Overview" no Grafana (RED por rota, p50/p95/p99, pool do DB, hit ratio do cache de membership) com link de exemplar para o Tempo; verificar visualmente com tráfego gerado pelo cenário `smoke`

## 7. Composição e empacotamento da API

- [x] 7.1 Montar o app em `apps/api` registrando os routers dos módulos, os handlers de erro padronizados (formato Problem Details, RFC 9457) e o OpenAPI; verificar com o `/docs` listando todas as rotas e o schema válido
- [x] 7.2 Criar o Dockerfile multi-stage (uv, usuário não-root) e o serviço `api` no Compose, com `workers` e `pool_size` configuráveis por env; verificar com `/health/ready` respondendo `200` no container
- [x] 7.3 Executar um teste de fumaça manual de ponta a ponta: login no Keycloak → `GET /me` → criar lar → convidar → aceitar com outro usuário; verificar o trace completo no Tempo e os logs correlacionados no Loki

## 8. Baseline com k6 (D11)

- [x] 8.1 Implementar o seed em Python (usuários via Admin API em lote, lares e memberships via SQL) parametrizado por quantidade; verificar com seed de 1.000 lares × 3 membros e contagens conferidas no banco
- [x] 8.2 Criar a biblioteca k6 compartilhada (config de host, pool de tokens no `setup()`, `handleSummary` que grava JSON com data, git sha e config); verificar rodando um script vazio que gera o arquivo de resultado
- [x] 8.3 Implementar os cenários `smoke` e `isolation` (qualquer `2xx` cruzado falha); verificar com os dois passando contra o servidor
- [x] 8.4 Implementar os cenários `read-heavy` e `mixed` com thresholds iniciais e envio de métricas por remote write para o Prometheus; verificar com as métricas do k6 aparecendo no Grafana ao lado das métricas da API
- [ ] 8.5 Executar a baseline oficial a partir da estação Windows (registrando o ping até o servidor) e salvar os resultados em `loadtest/results/`; verificar com os arquivos versionados no git
- [ ] 8.6 Executar o experimento `workers × pool_size` (D9), no mínimo 3 combinações, e registrar as conclusões em `loadtest/results/README.md`; verificar com uma tabela comparativa de RPS, p95 e erros por combinação
