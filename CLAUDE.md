# Projeto: KasaOikos

App de gestão da casa (tarefas, custos, estoque/lista de compras). Projeto solo de portfólio.
Visão e escopo: README.md · Domínio: docs/dominio.md · Decisões: docs/adr/ · Specs: docs/specs/
Implemente uma mudança (ex.: M0.2) por vez, exatamente como descrita na spec; o que não estiver na spec, pergunte.

## Stack
- Back: Python 3.13, FastAPI, Pydantic v2, SQLAlchemy 2, Alembic, PostgreSQL. Gerenciador: uv
- Front: React + TypeScript + Vite, TanStack Query, Tailwind. Gerenciador: pnpm
- Contrato: OpenAPI do FastAPI → tipos TS gerados (não editar os tipos gerados à mão)
- Observabilidade: OpenTelemetry → Grafana (local via docker compose)
- Auth: Keycloak (OIDC, Authorization Code + PKCE). A API só valida o JWT (assinatura via JWKS, `iss`, `aud`, `exp`).
  Papéis por casa ficam no banco do app, não no Keycloak. Token só em memória no front, nunca em localStorage. Ver ADR-0002.
- Staging: VPS Hetzner com Docker Compose + Caddy; front em CDN estática. Deploy só pelo CI. A IA não acessa o servidor. Ver ADR-0003.

## Ambiente
- Desenvolvimento em Windows nativo (PowerShell) com Docker Desktop; CI e staging em Linux.
- Tarefas do projeto via `just`; nada de script que só roda em bash. Fins de linha LF (`.gitattributes`).
- Repositório **público**: qualquer segredo commitado é considerado vazado (revogar e gerar outro).

## Estrutura
```
backend/app/<modulo>/{api.py, servico.py, repositorio.py, modelos.py, esquemas.py}
backend/tests/integracao/   # testes batendo nas rotas com Postgres real (testcontainers)
frontend/src/{paginas,componentes,api}/
load/                       # scripts k6
docs/adr/                   # um ADR por decisão de arquitetura
```
Módulos: `casa`, `tarefas`, `custos`, `estoque`.

## Convenções
- Lint/format: ruff (Python), ESLint + Prettier (TS). Não desativar regra sem avisar.
- Tipos: mypy/pyright estrito no back, `strict: true` no TS.
- Dinheiro sempre em **centavos (int)**. Nunca usar float para valores.
- Um módulo só chama o `servico` de outro módulo; nunca importa `repositorio`/`modelos` de outro módulo.
- Toda rota verifica se o usuário é membro da casa do recurso.
- Testes: todo código novo com teste de integração na rota. Mock só para serviço externo.
  Rodar `just check` antes de concluir.

## Regras para a IA
- Mostrar o plano antes de editar; mudanças pequenas (revisáveis em 10 a 15 min); uma branch por mudança.
- Não refatorar fora do escopo da tarefa.
- Não adicionar dependências sem perguntar (e confirmar que o pacote existe e é mantido).
- Nunca colocar segredos no código; usar variáveis de ambiente (`.env` fora do git, `.env.example` com valores falsos).
- Não registrar e-mail, telefone, chave Pix, senha ou token em logs.
- Não executar comandos destrutivos, não rodar migrations sem eu revisar, não tocar em produção.
- Proibido apagar, pular ou afrouxar teste para fazê-lo passar.
- Perguntar quando a spec estiver ambígua. Atualizar README/ADR quando houver decisão de arquitetura.
- Revisão humana obrigatória em: auth, autorização, rateio/saldo, migrations, pagamentos.
