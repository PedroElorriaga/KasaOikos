# Spec: Fase 0 · Fundação

Status: **rascunho para revisão** · Estimativa: 5 a 7 dias · Base: README, ADR-0001, ADR-0002, ADR-0003

## Objetivo

Deixar o projeto pronto para receber funcionalidades. Ao final da fase:

- o repositório tem CI verde, e lint, tipos e testes rodam com um comando;
- o ambiente local sobe com um comando: Postgres, Keycloak e, opcionalmente, Grafana;
- o login funciona de ponta a ponta: o front autentica no Keycloak, chama a API e a API reconhece o usuário;
- o staging está no ar na VPS, com deploy feito só pelo CI;
- os riscos de k6 e Grafana foram testados em um spike curto.

## Fora do escopo

Casas, tarefas, custos, estoque e qualquer tela além de login, layout base e "Olá, {nome}". Essas funcionalidades ficam para a fase 1.

## Decisões a confirmar antes de começar

| # | Pergunta | Sugestão |
|---|---|---|
| D1 | Onde o código roda no Windows? | ✅ **Decidido: Windows nativo, em `E:\Projetos-code\KasaOikos`**, com Docker Desktop. Consequências: scripts do projeto não podem depender de bash (usar `just`, Python ou comandos que rodam em PowerShell), `.gitattributes` com LF é obrigatório, e o CI (Linux) é a referência quando algo diferir. |
| D2 | Repositório público ou privado no GitHub? | ✅ **Decidido: público.** Gitleaks no pre-commit e push protection do GitHub ligados **antes do primeiro push**; o histórico nunca pode ter segredo, nem por um commit. |
| D3 | Licença | ✅ **Decidido: MIT.** Arquivo `LICENSE` entra na M0.1. |
| D4 | Comando único para checar tudo | ✅ **Decidido: `just check`**, via [just](https://github.com/casey/just), que roda igual em PowerShell e no CI. Instalar o `just` é pré-requisito no README. |
| D5 | Domínio do staging | Um domínio barato ou subdomínio seu (ex.: `staging.kasaoikos.dev`). O HTTPS automático do Caddy precisa de um domínio apontando para a VPS. |

## Mudanças

Cada mudança vira **uma branch e um PR**, e deve caber em 10 a 15 minutos de revisão. A ordem importa: cada uma depende das anteriores.

---

### M0.1 · Base do repositório e regras do Claude Code

**Tarefas**
- `git init`, branch `main`, primeiro commit com os documentos atuais.
- `.gitignore` (Python, Node, `.env`, `.venv`, `node_modules`, `dist`), `.gitattributes` com `* text=auto eol=lf` (evita quebra de scripts e hooks entre Windows e Linux) e `.editorconfig`.
- `.env.example` com chaves e valores falsos.
- `LICENSE` (MIT) e `justfile` inicial com a receita `check` (por enquanto só imprime o que ainda falta).
- `.claude/settings.json` com regras de permissão do projeto: bloquear leitura de `.env` e `**/secrets/**`; bloquear `git push --force`, `rm -rf`, `curl | sh` e comandos `ssh` para o servidor.
- Hook de pre-commit com gitleaks instalado **antes do primeiro commit** (o repositório é público).
- Repositório público no GitHub com proteção da `main` (PR obrigatório e CI verde), secret scanning e push protection ligados. Isso é configurado por você no GitHub, antes do primeiro push.

**Aceite**
- `git status` limpo depois de criar um `.env` local, ou seja, ele é ignorado.
- O Claude Code no shell recusa ler `.env`.

---

### M0.2 · Esqueleto do back-end

**Tarefas**
- Projeto `backend/` com `uv`, Python 3.13 e FastAPI. Pastas dos módulos (`casa`, `tarefas`, `custos`, `estoque`) criadas vazias, com `__init__.py`.
- Configuração via variáveis de ambiente (Pydantic Settings), sem nenhum segredo com valor padrão real.
- `GET /health`: responde 200 e verifica a conexão com o banco.
- `ruff` (lint + format), `mypy` estrito, `pytest` + `testcontainers` (Postgres real).
- Comando único `just check` (ou o escolhido em D4): roda lint, tipos e testes do back.

**Aceite**
- Teste de integração: "quando o banco está no ar, então `/health` responde 200".
- Teste de integração: "quando o banco está fora, então `/health` responde 503 sem expor detalhes do erro".
- `just check` passa do zero, em uma máquina limpa, seguindo o README.

**Dependências a confirmar:** fastapi, uvicorn, pydantic-settings, sqlalchemy, psycopg, alembic, pytest, testcontainers, ruff, mypy.

---

### M0.3 · Ambiente local com Docker Compose

**Tarefas**
- `compose.yaml` com:
  - `postgres`, com um script de init que cria os bancos `app` e `keycloak` e usuários separados (menor privilégio);
  - `keycloak` em modo dev, importando `infra/keycloak/realm-kasaoikos.json`;
  - `lgtm` (`grafana/otel-lgtm`) em um **profile** opcional (`docker compose --profile obs up`).
- Realm versionado: client público `kasaoikos-web` (PKCE obrigatório, redirect URIs exatas de `localhost`), cadastro aberto, proteção contra força bruta, política de senha e dois usuários de teste fictícios.
- Todas as senhas vêm do `.env`.
- Seção "Como rodar" no README.

**Aceite**
- `docker compose up -d` deixa Postgres e Keycloak saudáveis (healthchecks).
- É possível fazer login no Keycloak local com um usuário de teste.
- Nenhuma senha real versionada (gitleaks passa).

---

### M0.4 · Migrations e tabela de usuários

**Tarefas**
- Alembic configurado. Primeira migration cria `usuarios`: `id`, `keycloak_sub` (único), `nome`, `email`, `telefone` (nulo), `chave_pix` (nulo), `criado_em`, `atualizado_em`.
- A migration tem `downgrade` funcionando.

**Aceite**
- Teste: `upgrade` → `downgrade` → `upgrade` roda limpo em um banco novo.
- ⚠️ **Revisão manual obrigatória** da migration antes do merge.

---

### M0.5 · Autenticação no back-end

**Tarefas**
- Dependência FastAPI `usuario_atual`: valida o JWT (assinatura via JWKS com cache, `iss`, `aud`, `exp`, algoritmo `RS256`) e cria o usuário no primeiro acesso.
- `GET /me`: devolve `id`, `nome` e `email` do usuário autenticado.
- Logs nunca incluem o token, o e-mail ou o telefone.

**Aceite (testes de integração com tokens assinados por uma chave de teste)**
- Sem token → 401.
- Token expirado → 401.
- `aud` errado → 401.
- Assinatura de outra chave → 401.
- Algoritmo `none` ou `HS256` → 401.
- Token válido no primeiro acesso → 200 e cria **um** usuário.
- **Dois primeiros acessos simultâneos** do mesmo usuário → os dois respondem 200 e existe **uma** linha (proteção por índice único + upsert).
- ⚠️ **Revisão manual obrigatória** (auth).

**Dependência a confirmar:** PyJWT (com `PyJWKClient`).

---

### M0.6 · Esqueleto do front-end com login

**Tarefas**
- `frontend/`: Vite + React + TypeScript (`strict: true`), Tailwind, ESLint, Prettier e Vitest, com `pnpm`.
- Layout base responsivo, seguindo o canvas: barra inferior no celular e lateral no desktop, com as 4 seções ainda vazias.
- Login OIDC com Authorization Code + PKCE. Token só em memória, logout funcionando.
- Tipos gerados a partir do OpenAPI do back (`openapi-typescript`), via script `pnpm gen:api`. Os arquivos gerados não são editados à mão.
- Página inicial mostra "Olá, {nome}" a partir de `GET /me`.
- CORS da API liberado só para a origem do front.

**Aceite**
- Fluxo manual: abrir o app → redireciona ao Keycloak → login → volta e mostra "Olá, {nome}".
- Recarregar a página não deixa nenhum token em `localStorage` (verificar no DevTools).
- Layout confere em 390 px e em 1280 px de largura.
- `pnpm check` (lint + tipos + testes) passa.

**Dependências a confirmar:** oidc-client-ts ou keycloak-js, @tanstack/react-query, react-router, tailwindcss, openapi-typescript.

---

### M0.7 · CI, pre-commit e segurança

**Tarefas**
- Pre-commit hooks: ruff, prettier/eslint e gitleaks.
- GitHub Actions em todo push e PR, com três jobs:
  - `backend`: lint, tipos e testes;
  - `frontend`: lint, tipos, testes e build;
  - `seguranca`: gitleaks, `pip-audit`, `pnpm audit --audit-level=high` e CodeQL.
- Dependabot para pip, npm, GitHub Actions e Docker.
- Secret scanning e push protection do GitHub ativados por você nas configurações do repositório.

**Aceite**
- Um PR com um segredo falso de teste é barrado (pelo hook local e pelo CI).
- A `main` só aceita merge com os 3 jobs verdes.

---

### M0.8 · Observabilidade base + spike de k6

**Tarefas**
- Logs estruturados em JSON, com `trace_id` e sem dados pessoais.
- OpenTelemetry na API (FastAPI + SQLAlchemy), enviando para o `lgtm` local.
- Script k6 `load/smoke.js` batendo em `/health` e `/me` com token de teste, com thresholds (ex.: `p95 < 300ms`, erros < 1%).
- Nota curta em `docs/spikes/k6-grafana.md` explicando o que aprendeu, o que funcionou e o que fica para a fase 2.

**Aceite**
- Com `--profile obs`, uma requisição a `/me` aparece no Grafana como trace com o span do banco.
- `k6 run load/smoke.js` termina com thresholds verdes no ambiente local.

---

### M0.9 · Staging na VPS Hetzner

**Feito por você (prepare-se):**
1. Criar a conta e a VPS na Hetzner. Pagamento e senha são com você.
2. Apontar o domínio (D5) para o IP da VPS.
3. Seguir o runbook `docs/runbooks/vps.md` (o Claude escreve; você executa): usuário sem root, SSH só por chave, firewall nas portas 22, 80 e 443, `unattended-upgrades` e Docker.
4. Cadastrar os segredos de deploy no GitHub (chave SSH de deploy, `.env` de staging).

**Feito com o Claude:**
- `compose.prod.yaml`: API, Keycloak (modo produção, `hostname` configurado), Postgres e Caddy (HTTPS automático; console admin do Keycloak não exposto).
- Workflow `deploy-staging`: depois do CI verde na `main`, faz build das imagens, publica no GHCR e roda via SSH `docker compose pull && docker compose up -d` + migrations.
- Front publicado em CDN estática (Cloudflare Pages ou similar).
- Backup: `pg_dump` diário para storage externo + `docs/runbooks/restore.md`.
- Health check externo com alerta (ex.: UptimeRobot ou o próprio Grafana Cloud).

**Aceite**
- Merge na `main` → staging atualizado sem nenhum comando manual.
- Login de ponta a ponta funcionando na URL de staging com HTTPS.
- **Restauração de backup testada** em um banco descartável e registrada no runbook.
- Porta 5432 e console admin do Keycloak inacessíveis de fora (testado).

## Definição de pronto da fase 0

- [ ] M0.1 a M0.9 mergeadas, cada uma com CI verde.
- [ ] `README` → "Como rodar" funciona do zero em uma máquina limpa.
- [ ] CLAUDE.md atualizado com o comando único real (substituir `<comando a definir na fase 0>`).
- [ ] Itens do checklist do guia marcados: README, .gitignore/.env.example, linter + hook, CI com auditoria, secret scanning, Dependabot/SAST, deploy automático, backup com restauração testada.

## Como usar esta spec com o Claude Code no shell

1. Uma sessão do Claude Code por mudança, sempre a partir da `main` atualizada:
   > "Implemente a mudança M0.2 de `docs/specs/fase-0.md`. Crie a branch `m0.2-esqueleto-backend`, mostre o plano e espere meu OK antes de editar."
2. Revise o plano, depois o diff, e rode `just check` você mesmo.
3. Aplique o "teste de duas frases" do guia antes do merge.
4. Se for usar OpenSpec, cada M0.x vira uma proposta de mudança no OpenSpec, com este texto como ponto de partida.
