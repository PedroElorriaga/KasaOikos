## Why

O Home Manager é um projeto de aprendizado sobre a evolução de um monolito modular para microserviços. Antes de qualquer regra de negócio, é preciso uma fundação que torne essa evolução possível e mensurável: fronteiras rígidas entre módulos, isolamento multi-tenant garantido pelo banco, autenticação real e uma baseline de desempenho medida com k6, para servir de comparação com as próximas fases.

**Fase do roadmap:** Fase 1 — Fundação do monolito modular.

## What Changes

- Monorepo Python gerenciado com `uv`, contendo uma aplicação FastAPI organizada como monolito modular com os módulos `identity`, `finance`, `tasks`, `inventory` e `notifications` (os quatro últimos apenas como esqueleto).
- Fronteiras entre módulos verificadas no CI com `import-linter`: um módulo só se comunica com outro pela interface pública dele.
- Autenticação via Keycloak (OIDC): a API valida JWTs emitidos pelo realm `home`.
- Módulo `identity` completo: lares (households), membros, papéis por lar (`admin` | `member`), convites e seleção do lar ativo.
- Isolamento multi-tenant: lar ativo informado no header `X-Household-Id`, validado contra a membership, e aplicado no PostgreSQL via Row Level Security.
- PostgreSQL com um schema por módulo e migrações com Alembic.
- Health checks, métricas, traces e logs estruturados com OpenTelemetry, exportados para a stack Grafana (Prometheus, Loki, Tempo).
- Ambiente completo em Docker Compose para o servidor local (42 GB), com Postgres, Redis, Keycloak e a stack de observabilidade.
- Primeiro conjunto de scripts k6 (baseline), executados a partir de uma máquina separada, com seeding de lares e usuários sintéticos.

## Non-goals

- Regras de negócio de Finanças, Tarefas, Estoque e Notificações (changes próprias na Fase 1b).
- App mobile (Expo): entra quando houver funcionalidades de domínio para consumir.
- Eventos de domínio, outbox e broker de mensagens (Fase 2).
- Qualquer funcionalidade de IA ou LangGraph (Fase 3).
- Extração de microserviços, Kubernetes/k3s e API Gateway (Fases 4–5).
- Cadastro de usuários, recuperação de senha e MFA: ficam a cargo do Keycloak, sem telas próprias.

## Roadmap (contexto)

| Fase | Foco |
|---|---|
| **1 — Fundação** (esta change) | Monolito modular, identity, multi-tenant, observabilidade, baseline k6 |
| 1b — Domínio | Finanças, Tarefas, Estoque, Notificações (uma change por módulo) + app Expo |
| 2 — Eventos | Eventos de domínio, outbox, RabbitMQ, consumidores assíncronos |
| 3 — IA | `agent-service` com LangGraph: lançamento por linguagem natural |
| 4 — Extração | Notificações e agente como serviços separados (strangler fig), k3s |
| 5 — Malha | Mais serviços, API Gateway, tracing distribuído, MCP por serviço |

## Capabilities

### New Capabilities
- `identity/authentication`: validação de tokens OIDC emitidos pelo Keycloak e resolução do usuário autenticado.
- `identity/households`: lares, membros, papéis por lar, convites e listagem dos lares do usuário.
- `platform/tenant-isolation`: seleção do lar ativo via header, verificação de membership e isolamento de dados por lar no banco (RLS).
- `platform/observability`: health checks (liveness/readiness), métricas, traces e logs estruturados correlacionados.

### Modified Capabilities
<!-- Nenhuma: primeira change do projeto. -->

## Impact

- **Código novo:** `apps/api` (FastAPI), pacotes de módulo em `modules/*`, pacote `platform` (configuração, banco, auth, tenancy, telemetria), `loadtest/` (k6), `infra/` (Compose, Keycloak realm, Grafana).
- **APIs:** `/health/*`, `/me`, `/households/*`, `/households/{id}/members/*`, `/invites/*`.
- **Dependências:** FastAPI, SQLAlchemy 2 (asyncpg), Alembic, Pydantic v2, PyJWT/JWKS, redis, opentelemetry-*, import-linter, pytest, testcontainers.
- **Infra:** PostgreSQL 16+, Redis/Valkey, Keycloak 26+, Grafana, Prometheus, Loki, Tempo, OpenTelemetry Collector.
