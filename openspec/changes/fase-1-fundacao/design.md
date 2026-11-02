## Context

Projeto novo (greenfield), sem código existente. Motivação e escopo estão em `proposal.md`; o comportamento esperado está nas specs `identity/*` e `platform/*`.

Restrições que moldam o desenho:
- Duas máquinas: o **servidor** (42 GB RAM, GPU 8 GB) roda o sistema via Docker Compose; a **estação Windows** roda desenvolvimento e o k6.
- O monolito precisa nascer pronto para ser fatiado: cada decisão abaixo indica o impacto na extração futura.
- Apenas ferramentas gratuitas/self-hosted.

## Goals / Non-Goals

**Goals:**
- Fronteiras entre módulos impostas por ferramenta (CI), não por disciplina.
- Isolamento de tenant com defesa em profundidade: aplicação **e** banco.
- Cada módulo com dados, migrações e pacote próprios, para que a extração seja uma "mudança de transporte", não uma reescrita.
- Baseline de desempenho reprodutível, versionada junto com o código.

**Non-Goals:**
- Alta disponibilidade, backups e TLS interno: ambiente de laboratório.
- Otimização prematura (cache de leitura de domínio, read replicas): só se o k6 apontar necessidade.

## Decisions

### D1. Monorepo com `uv` workspace, um pacote por módulo

```
home-manager/
├── apps/
│   └── api/                 # composition root: cria o FastAPI e monta os routers
├── packages/
│   └── platform/            # hm_platform: settings, db, auth, tenancy, telemetry, errors
├── modules/
│   ├── identity/            # hm_identity  (completo nesta fase)
│   ├── finance/             # hm_finance   (esqueleto)
│   ├── tasks/               # hm_tasks     (esqueleto)
│   ├── inventory/           # hm_inventory (esqueleto)
│   └── notifications/       # hm_notifications (esqueleto)
├── loadtest/                # scripts k6, seeding, resultados
├── infra/                   # compose, keycloak realm, grafana, otel collector
└── openspec/
```

Estrutura interna de cada módulo:

```
hm_<module>/
├── public.py      # ÚNICA interface importável por outros módulos (funções/DTOs)
├── api/           # routers FastAPI
├── domain/        # entidades, regras, exceções de domínio
├── infra/         # repositórios SQLAlchemy, modelos ORM
└── migrations/    # Alembic próprio do módulo
```

- **Por quê:** um pacote por módulo torna explícitas as dependências (`pyproject.toml` de cada um) e transforma a extração futura em "pegar o pacote e colocar atrás de HTTP/eventos".
- **Alternativa considerada:** um único pacote com subpastas. Mais simples, mas as dependências ficam implícitas e o `import-linter` vira a única barreira.
- **Impacto na extração:** `public.py` é o embrião do contrato do serviço. Na Fase 4, as chamadas a `public.py` são trocadas por um cliente HTTP com a mesma assinatura.

### D2. Fronteiras com `import-linter`

Contratos no CI:
1. **Independence:** `hm_finance`, `hm_tasks`, `hm_inventory`, `hm_notifications` e `hm_identity` não importam uns aos outros, exceto `<module>.public`.
2. **Layers:** `apps.api` → `hm_<module>` → `hm_platform`. O `hm_platform` nunca importa módulos.
3. **Forbidden:** dentro de um módulo, `domain` não importa `infra` nem `fastapi`.

- **Alternativa considerada:** Tach. É mais novo e ainda não é o padrão de mercado; o `import-linter` é suficiente.

### D3. Postgres: schema por módulo, sem FK entre schemas

- Schemas `identity`, `finance`, `tasks`, `inventory`, `notifications`.
- Referências a usuário ou lar em outros módulos são `uuid` **sem foreign key** para `identity`.
- Cada módulo tem seu próprio ambiente Alembic, com `version_table` no próprio schema. Um comando `hm migrate` roda todos em ordem.
- IDs: **UUIDv7** gerados na aplicação, ordenáveis no tempo, o que preserva a localidade do índice B-tree.
- **Por quê:** FK entre schemas é o acoplamento que mais dificulta a extração; abrir mão dela desde já força o pensamento "o outro módulo pode estar em outro banco".
- **Trade-off:** perde-se integridade referencial entre módulos. Inconsistências (ex.: lar removido) serão tratadas por eventos na Fase 2.

### D4. Row Level Security com papéis separados

```
 role "hm_migrator"  ── dono das tabelas, roda migrações (nunca usado pela API)
 role "hm_app"       ── usado pela API: NOSUPERUSER, NOBYPASSRLS

 por transação (início de cada request):
   SELECT set_config('app.user_id',      :user_id,      true);   -- true = LOCAL
   SELECT set_config('app.household_id', :household_id, true);

 política padrão em toda tabela com household_id:
   ALTER TABLE ... ENABLE ROW LEVEL SECURITY;
   ALTER TABLE ... FORCE  ROW LEVEL SECURITY;
   CREATE POLICY tenant_isolation ON ...
     USING      (household_id = current_setting('app.household_id', true)::uuid)
     WITH CHECK (household_id = current_setting('app.household_id', true)::uuid);
```

- Sem lar ativo, `current_setting(..., true)` retorna NULL → nenhuma linha é visível (cenário "consulta sem lar ativo").
- **Ajuste na implementação:** numa conexão que já teve `SET LOCAL` em transação anterior (o caso normal com pool), `current_setting(..., true)` retorna `''`, não NULL, e `''::uuid` dá erro. As políticas usam `nullif(current_setting('app.household_id', true), '')::uuid`.
- **Casos especiais do `identity`**, que precisam enxergar além de um lar:
  - `memberships`: política `user_id = app.user_id OR household_id = app.household_id`, que atende tanto o `GET /me` (todos os lares do usuário) quanto a listagem de membros do lar ativo.
  - `households`: visível se `id = app.household_id` ou se existe membership do `app.user_id`.
  - **Aceite de convite** (o usuário ainda não é membro): função `identity.redeem_invite(code_hash, user_id)` com `SECURITY DEFINER`, escopo mínimo e auditada por teste.
- `set_config(..., true)` vale só para a transação, o que é compatível com PgBouncer em modo transaction no futuro.
- **Guarda automática:** um teste percorre `information_schema` e falha se alguma tabela com coluna `household_id` não tiver RLS habilitado **e** forçado.
- **Alternativa considerada:** apenas filtro na aplicação (`WHERE household_id = ...` no repositório base). Fica como primeira camada; o RLS é a rede de segurança.
- **Impacto na extração:** cada serviço extraído leva consigo seu schema e suas políticas, sem alteração.

### D5. Autenticação: Keycloak só para "quem é você"

- Realm `home` versionado em `infra/keycloak/realm-home.json` e importado no boot (`--import-realm`).
- Clients:

  | Client | Tipo | Uso |
  |---|---|---|
  | `home-api` | resource (sem login) | audiência dos tokens |
  | `home-mobile` | público, Authorization Code + PKCE | app Expo (fase 1b) |
  | `home-loadtest` | confidencial, *direct access grants* | **somente dev/loadtest**: k6 obtém tokens por senha |

- A API valida JWT RS256 com PyJWT + cache de JWKS. Em caso de `kid` desconhecido, refaz o fetch com limitação de frequência (no máximo 1 vez a cada 30 s) para que tokens forjados não virem um DoS no Keycloak.
- Usuário local (`identity.users`) é criado ou atualizado *just-in-time* pelo `sub`. A atualização só grava quando nome ou e-mail mudam, para evitar uma escrita por request.
- **Alternativa considerada:** Keycloak Organizations para representar os lares. Descartada porque o papel é **por lar**, um usuário participa de vários lares, e criar milhares de organizations para o k6 via Admin API é lento. Autorização fica no domínio, onde é testável.

### D6. Resolução do tenant e cache de membership

```
 Request
   │
   ├─ auth dependency ─────▶ valida JWT ─▶ CurrentUser(id, sub)
   │
   ├─ tenant dependency ───▶ household_id ← path param | X-Household-Id (divergência → 400)
   │                          │
   │                          ▼
   │                   Redis GET membership:{user}:{household}
   │                     hit ─▶ role
   │                     miss ─▶ consulta identity.public.get_membership() → SETEX 60s
   │                     ausente ─▶ 404
   │
   └─ db session ──────────▶ BEGIN; set_config(user_id, household_id); ... COMMIT
```

- Toda mudança de membership (papel alterado, remoção, saída) faz `DEL` da chave **na mesma unidade de trabalho**, após o commit, o que garante a "revogação imediata" da spec. O TTL de 60 s é só uma rede de segurança.
- Papel exigido é declarado na rota: `Depends(require_role("admin"))` → `403`.
- **Fronteira (decidido na implementação):** a tenancy fica no `hm_platform`, que não pode importar módulos (D2). O que ela precisa do identity passa por portas (`typing.Protocol`) definidas no platform, `UserProvisioner` e `MembershipResolver`, implementadas pelo `hm_identity` e ligadas pelo `hm_api` ao criar a app. Na extração (Fase 4), a implementação vira um cliente HTTP sem mudar a tenancy.
- **k6:** o hit ratio desse cache é uma métrica importante da baseline (dá para comparar com o cache desligado).

### D7. Convites

- Código = `secrets.token_urlsafe(32)`; o banco guarda apenas o **SHA-256** do código.
- Estados: `pending → accepted | revoked | expired` (expiração calculada por `expires_at`, sem job).
- Aceite atômico: `UPDATE ... SET status='accepted' WHERE code_hash=? AND status='pending' AND expires_at > now() RETURNING ...` dentro de `redeem_invite`, o que evita aceite duplo em concorrência.

### D8. Observabilidade

```
 API (OTel SDK) ──OTLP──▶ OTel Collector ─┬─▶ Prometheus (métricas, exemplars)
                                          ├─▶ Tempo (traces)
                                          └─▶ Loki (logs, OTLP nativo)
 k6 ──remote write──────────────────────────▶ Prometheus
                                                  │
                                              Grafana (datasources e dashboards provisionados)
```

- Auto-instrumentação: FastAPI, SQLAlchemy, Redis, httpx.
- Logs: `structlog` em JSON → handler OTel, com processador que remove `authorization`, `code` e `token`.
- `X-Trace-Id` adicionado por middleware.
- **Alternativa considerada:** imagem `grafana/otel-lgtm` (tudo em um container). Mais simples, mas esconde a configuração que se quer aprender, e os componentes separados serão necessários no k3s.

### D9. Runtime da API

- `uvicorn` com `--workers N` configurável (padrão = núcleos ÷ 2). Driver `asyncpg`; pool por worker (`pool_size` configurável).
- **Experimento k6 previsto:** variar `workers` × `pool_size` e observar o limite de conexões do Postgres e o efeito do GIL. O resultado alimenta a decisão de usar PgBouncer.

### D10. Testes

- `pytest` + `pytest-asyncio` + `httpx.AsyncClient`.
- **Postgres real via testcontainers**, porque RLS não existe em SQLite; o banco sobe uma vez por sessão e cada teste roda em transação revertida.
- Tokens de teste assinados com um par RSA gerado no teste e servidos por um JWKS falso (sem Keycloak nos testes unitários e de integração).
- Testes de isolamento parametrizados: para cada endpoint com escopo de lar, existe um caso "usuário do lar A acessa recurso do lar B → 404".

### D11. k6: baseline

```
 Estação Windows                                 Servidor 42 GB
 ┌──────────────────────────┐                    ┌──────────────────────┐
 │ seed (python):           │──Admin API────────▶│ Keycloak             │
 │  N usuários, M lares     │──SQL (hm_migrator)▶│ Postgres             │
 │                          │                    │                      │
 │ k6 setup(): pool de      │──token (1x/VU)────▶│ Keycloak             │
 │  tokens reutilizados     │                    │                      │
 │ k6 cenários              │──HTTP─────────────▶│ API                  │
 └──────────────────────────┘                    └──────────────────────┘
```

- **Seed:** usuários criados no Keycloak via Admin API em lote (*partial import*), lares e memberships inseridos direto no Postgres. Tamanho inicial: 1.000 lares × 3 membros, configurável.
- **Tokens:** obtidos uma única vez no `setup()` e reaproveitados; o client `home-loadtest` tem *access token lifespan* longo (1 h). Isso evita que o Keycloak vire o gargalo e contamine a medição.
- **Cenários:**

  | Cenário | Executor | Conteúdo |
  |---|---|---|
  | `smoke` | 1 VU, 30 s | todas as rotas, valida contrato |
  | `read-heavy` | `ramping-arrival-rate` | `GET /me`, `GET /households/{id}`, `GET /households/{id}/members` |
  | `mixed` | `constant-arrival-rate` | 90% leitura + 10% escrita (criar/revogar convite, renomear) |
  | `isolation` | 20 VUs | tentativas cruzadas entre lares; **qualquer `2xx` falha o teste** |

- **Thresholds iniciais:** `http_req_failed < 1%`, `p(95) < 200ms` em leitura (serão recalibrados após a primeira medição).
- **Resultados:** `handleSummary()` grava JSON em `loadtest/results/<data>-<git-sha>-<cenario>.json`, junto com a configuração (workers, pool). É o histórico versionado que permite comparar as fases.
- Executor `arrival-rate` (modelo aberto) em vez de VUs fixos: mede o sistema sob uma taxa de chegada real, sem o *coordinated omission* do modelo fechado.

## Risks / Trade-offs

- **[RLS esquecido em tabela nova]** → teste de guarda sobre `information_schema` (D4) roda no CI.
- **[`SECURITY DEFINER` vira brecha]** → uma única função, `search_path` fixo, testes específicos de aceite cruzado.
- **[Keycloak gargalo nos testes]** → tokens pré-obtidos; cenário separado de login fica para depois, se houver interesse.
- **[Direct access grants (senha) é inseguro]** → habilitado só no client `home-loadtest`, documentado como dev-only; o mobile usa PKCE.
- **[Pacote por módulo aumenta a cerimônia]** → template de módulo e `uv` workspace mantêm o custo baixo; os benefícios aparecem na Fase 4.
- **[Sem FK entre schemas]** → inconsistências possíveis até a Fase 2 (eventos); aceitável em laboratório.
- **[Rede doméstica afeta medições]** → registrar latência base (ping) no resultado; preferir cabo ao Wi-Fi entre as máquinas.
- **[Memória do stack]** → estimativa de ~6–8 GB (Keycloak ~1 GB, stack Grafana ~2–3 GB), confortável em 42 GB.

## Migration Plan

Greenfield, sem migração de dados. Ordem de subida: `docker compose up` (infra) → `hm migrate` → API → seed → k6. Rollback: `docker compose down -v`.

## Open Questions

- Python 3.12 ou 3.13: depende da compatibilidade das libs de OTel no momento da implementação; não afeta specs nem tasks.
- Volume final do seed (1k vs. 10k lares): será calibrado depois da primeira execução.
