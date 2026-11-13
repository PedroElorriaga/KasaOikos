# ADR-0001: Stack e arquitetura inicial

Data: 2026-11-10 · Status: **proposta** (aguardando revisão)

## Contexto

- Projeto solo, com foco em portfólio e aprendizado: monolito → serviços, observabilidade e carga.
- O autor programa em Python há 5 anos e quer praticar TypeScript e/ou Go.
- Front e back separados, com interface responsiva para celular e PC.
- Há dados pessoais (e-mail, telefone, chave Pix) e dinheiro (rateio de despesas).
- Prazo apertado: precisamos de velocidade onde há domínio e de aprendizado onde o risco é menor.

## Decisão

**Cada linguagem entra onde o risco de errar é menor:**

| Camada | Escolha | Por quê |
|---|---|---|
| Back-end (monolito) | **Python 3.13 + FastAPI**, Pydantic v2, SQLAlchemy 2 + Alembic | É onde estão as regras de negócio e o dinheiro, então fica com a linguagem que você domina. O FastAPI gera OpenAPI automaticamente |
| Banco | **PostgreSQL** | Constraints, transações e `SELECT ... FOR UPDATE` resolvem race conditions no próprio banco |
| Front-end | **React + TypeScript + Vite**, TanStack Query, Tailwind CSS | Pratica TS em uma camada onde um erro não corrompe dados. Tailwind deixa o layout responsivo rápido |
| Contrato | OpenAPI gerado pelo FastAPI → tipos TS gerados com `openapi-typescript` | Contrato leve: se o back mudar, o front quebra na compilação, não em produção |
| Serviço extraído (fase 3) | **Go** | Aprendizado de Go em um serviço pequeno e isolado (candidatos em dominio.md) |
| Arquitetura | **Monolito modular**: um pacote por módulo (`casa`, `tarefas`, `custos`, `estoque`), cada um com camadas `api` / `servico` / `repositorio` | Fronteiras claras desde o início facilitam a extração depois |
| Ferramentas Python | `uv`, `ruff` (lint + format), `mypy` ou `pyright`, `pytest` + `testcontainers` (Postgres real nos testes) | Segue o guia: testes de integração com banco real em vez de mocks |
| Ferramentas TS | `pnpm`, ESLint, Prettier, Vitest, Playwright (só fluxos críticos) | |
| Local | Docker Compose (Postgres + `grafana/otel-lgtm`) | Ambiente de observabilidade disponível desde o primeiro dia |
| Observabilidade | OpenTelemetry (traces, métricas, logs) → Grafana | Padrão aberto, sem depender de fornecedor |
| Carga | k6 | Pedido explícito; os scripts ficam versionados em `load/` |
| CI | GitHub Actions: lint, tipos, testes, `pip-audit`, `pnpm audit`, CodeQL, gitleaks | Itens de segurança do checklist |
| Autenticação | **Keycloak** (OIDC), ver ADR-0002 | Login padrão de mercado, compartilhado com os serviços futuros |
| Hospedagem staging | **VPS Hetzner + Docker Compose**, ver ADR-0003 | Mais barato e igual ao ambiente local; Railway como plano B |

## Autenticação

Decidida no [ADR-0002](0002-autenticacao-keycloak.md): Keycloak self-hosted (OIDC). O app só valida tokens e
cuida da autorização por casa.

## Alternativas consideradas

- **Back-end em Go desde o início:** aprendizado máximo, mas regras de dinheiro em uma linguagem
  nova e com prazo de 4 semanas aumentam o risco. Fica para o serviço extraído.
- **Back-end em TypeScript (NestJS/Fastify):** uma linguagem só no projeto inteiro. Porém joga fora
  sua vantagem em Python e você praticaria duas coisas novas ao mesmo tempo.
- **Django + DRF:** produtivo, mas o FastAPI gera OpenAPI e tipos de forma mais direta, e o
  modelo mais explícito facilita separar os módulos.
- **Supabase (BaaS):** acelera o desenvolvimento, mas esconde justamente o que você quer aprender
  (back-end, serviços, observabilidade). O guia também cita os riscos de RLS mal configurado.
- **Microsserviços desde o início:** o guia desaconselha. Primeiro as fronteiras, depois a extração.

## Consequências

- (+) Velocidade no domínio, TypeScript na prática diária e Go em escopo controlado.
- (+) O contrato OpenAPI evita divergência entre front e back.
- (−) Duas (depois três) toolchains para manter no CI.
- (−) A fronteira entre módulos precisa de disciplina: um módulo não importa o repositório de outro,
  só o serviço (regra no CLAUDE.md).
