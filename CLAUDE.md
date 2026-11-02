# Home Manager

Projeto de aprendizado: sistema multi-tenant de administração de lares que começa como monolito modular e evolui para microserviços, com k6 medindo cada fase.

- Planejamento vive no OpenSpec: contexto e regras em `openspec/config.yaml`; change ativa em `openspec/changes/fase-1-fundacao/` (proposal, design, specs, tasks). Leia esses arquivos antes de implementar.
- Para implementar: `/opsx:apply fase-1-fundacao`. Marque `- [x]` em `tasks.md` só depois da verificação descrita na própria tarefa.
- Converse em pt-BR. Código em inglês, documentação em pt-BR.

## Ambiente

- **Estação de desenvolvimento:** Windows, projeto dentro do OneDrive. Ferramentas: `uv` (o Python 3.13 é baixado por ele; o 3.12 do sistema não é usado), Docker Desktop, k6, Git, Node.
- **Servidor:** outra máquina Windows + WSL, com 42 GB de RAM e GPU de 8 GB. Roda o Compose completo (Keycloak, stack Grafana) e é o alvo do k6, que roda a partir da estação.
- Testes usam testcontainers (Postgres e Redis reais) no Docker da estação.
- `.gitattributes` força LF; não converta arquivos para CRLF.

## Comandos

```
uv sync                      # instala o workspace
uv run pytest                # testes
uv run ruff format . && uv run ruff check . && uv run mypy && uv run lint-imports
cd infra && docker compose up -d --build --wait api   # reconstrói e sobe a API
uv run python loadtest/seed.py --env-file infra/.env  # seed (1.000 lares × 3)
uv run python loadtest/run.py smoke --env-file infra/.env
```

## Estado (atualize ao avançar)

- Grupo 1 concluído (1.1–1.4). A tarefa **1.5 (CI)** tem o workflow escrito, mas espera um repositório no GitHub para ser verificada.
- Grupo 2: 2.1–2.4 concluídas (`infra/compose.yaml` e configs em `infra/`). A **2.5 (README)** está escrita e foi verificada na estação com uma cópia limpa; falta segui-la no servidor a partir de um clone real (depende de commit/push).
- Grupo 3 concluído: `hm_platform.settings`/`db`/`ids`/`migrations`/`cache`, CLI `hm migrate` (`hm_api.cli`) e fixtures em `hm_platform.testing.fixtures` (registradas pelo `conftest.py` raiz).
- Grupo 4 concluído: `hm_platform.auth` (JWT + cache de JWKS), `hm_platform.testing.tokens` (RSA/JWKS falsos), `identity.users` + provisionamento JIT (`hm_identity.infra.users`), `DbSession` (commit antes da resposta).
- Grupo 5 concluído: tabelas `households`/`memberships`/`invites` com RLS, `identity.redeem_invite` (SECURITY DEFINER), `hm_platform.tenancy` (portas `UserProvisioner`/`MembershipResolver` ligadas em `hm_api.main`; decisão registrada no D6), rotas em `hm_identity.api.routes` e suíte de isolamento que descobre as rotas com escopo de lar sozinha.
- Grupo 6: 6.1–6.4 concluídas (`hm_platform.health`/`telemetry`/`logs`). A **6.5 (dashboard)** está em `infra/grafana/provisioning/dashboards/api-overview.json`, com as queries validadas contra dados reais; falta a verificação visual com o cenário `smoke` do k6 (depende de 7.2 e 8.3).
- Repositório: https://github.com/PedroElorriaga/KasaOikos (commit inicial `9811469` na `main`). Commitar só quando o usuário pedir; autor configurado só neste repositório.
- Grupo 7 concluído: erros em Problem Details (`hm_platform.errors`; routers registrados em `hm_api.modules.ROUTERS`), `hm serve` + `create_production_app`, `apps/api/Dockerfile` e serviços `migrate`/`api` no Compose. A fumaça de ponta a ponta (7.3) foi verificada contra o Compose da estação.
- Grupo 8: 8.1 (seed, `loadtest/seed.py`), 8.2 (`loadtest/lib/` + `loadtest/run.py`) e 8.4 (`read-heavy`/`mixed` + remote write com histograma nativo + linha "Carga do k6" no dashboard) concluídas. A **8.3** (`smoke` e `isolation`) passa contra o Compose da estação, mas a tarefa pede o servidor; **8.5** e **8.6** também dependem do servidor.
- Próximo passo: preparar o servidor (2.5), então 8.3, 6.5, 8.5 e 8.6 a partir da estação.

## Pegadinhas

- O `infra/.env` local (ignorado pelo git) tem senhas aleatórias. Os scripts de `infra/postgres/init/` e o import do realm só rodam com o volume vazio: `docker compose down -v` para reaplicar.
- No Git Bash, `docker compose exec ... /caminho/absoluto` é reescrito para um caminho do Windows. Use `MSYS_NO_PATHCONV=1`.
- O virtualenv fica **fora do OneDrive** (o OneDrive travava arquivos do `.venv`): `UV_PROJECT_ENVIRONMENT` aponta para `%USERPROFILE%\.venvs\home-manager` e `UV_LINK_MODE=copy` evita hard links com o cache. Nas sessões do Claude Code isso vem de `.claude/settings.local.json`; num terminal próprio, defina as duas variáveis antes de usar `uv`.
- Testes que precisam de banco vazio ou de commit real usam a fixture `empty_database_settings` (banco novo copiado de `home_template`); os demais usam `db_session` (transação revertida).
- Migrações com RLS: o autogenerate não gera políticas; escreva-as à mão com os helpers de `hm_platform.rls`. No downgrade, remova antes as políticas que consultam outras tabelas (o `test_migrate` pega isso).
- Rota nova com escopo de lar exige um caso em `modules/identity/tests/test_isolation_suite.py` (o teste de cobertura falha sem ele).
- SQLAlchemy fica em `<2.1`: a instrumentação do OTel não suporta a 2.1 e se desliga em silêncio (sem spans de banco).
- No Windows, parar o processo que rodou `uvicorn` não encerra o Python filho, que segura a porta 8000; confira com `Get-NetTCPConnection -LocalPort 8000`. A API do Compose também usa a 8000: pare-a (`docker compose stop api`) antes de rodar o uvicorn local.
- Teste de mutação: rode com `PYTHONDONTWRITEBYTECODE=1`. O `.pyc` é validado por mtime (em segundos) e tamanho; uma mutação de mesmo tamanho restaurada no mesmo segundo reaproveita o bytecode mutante.
- Módulo novo no workspace: acrescente o `COPY` do `pyproject.toml` dele em `apps/api/Dockerfile` e o router em `hm_api.modules.ROUTERS`.
- Comandos da CLI escrevem logs no stderr; o stdout é a saída do comando.
- O hook do `pre-commit` guarda o caminho do Python do venv: depois de mover o venv, rode `uv run pre-commit install` de novo. Os hooks do ruff usam `--force-exclude`; sem ele, os arquivos passados explicitamente furam o `extend-exclude` das migrações.
- O Grafana não percebe sozinho a edição do JSON de dashboard (bind mount do Docker Desktop): recarregue com `POST /api/admin/provisioning/dashboards/reload` (usuário admin) ou reinicie o container.
- No Tempo, o span `connect` do SQLAlchemy é a retirada de uma conexão do pool (inclui a espera por uma livre), não a abertura de conexão TCP.
- O último lar do seed é reservado ao cenário `smoke`; o pool de tokens dos outros cenários o deixa de fora. Resultados de desenvolvimento vão para `loadtest/.tmp/`; `--save` grava em `loadtest/results/` (versionado), só para execuções oficiais.
