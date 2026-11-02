# Home Manager

Sistema multi-tenant de administração de lares. É um projeto de aprendizado: começa como monolito modular e evolui para microserviços, com o k6 medindo cada fase. O planejamento fica em [`openspec/`](openspec/).

## Topologia

São duas máquinas:

| Máquina | Papel | O que roda |
|---|---|---|
| **Servidor** (Windows + WSL2, 42 GB) | Ambiente completo e alvo do k6 | `infra/compose.yaml`: Postgres, Valkey, Keycloak, OTel Collector, Prometheus, Tempo, Loki, Grafana (e a API, a partir da tarefa 7.2) |
| **Estação** (Windows) | Desenvolvimento e carga | `uv`, testes (testcontainers no Docker local), k6, seed |

A stack ociosa ocupa cerca de 2,5 GB de RAM, dos quais ~1,7 GB são do Keycloak.

## Subir o ambiente no servidor

### 1. Pré-requisitos (uma vez)

- **WSL2** com uma distro Linux (ex.: Ubuntu) e **Docker** disponível dentro dela. Serve o Docker Engine instalado na distro ou o Docker Desktop com integração WSL. Confira com `docker compose version` dentro do WSL.
- **Rede do WSL em modo espelhado**, para que as portas publicadas pelo Docker fiquem acessíveis pela rede local (no modo NAT padrão, só o próprio Windows do servidor as enxerga). No Windows do servidor, crie ou edite `%UserProfile%\.wslconfig`:

  ```ini
  [wsl2]
  networkingMode=mirrored
  ```

  Depois rode `wsl --shutdown` e abra o WSL de novo. Se usar Docker Desktop no servidor, este passo não é necessário: ele publica as portas direto no Windows.

- **Firewall do Windows** do servidor liberando as portas para a rede local. Em um PowerShell como administrador:

  ```powershell
  # Firewall do Windows (Docker Desktop ou WSL)
  New-NetFirewallRule -DisplayName "Home Manager" -Direction Inbound -Protocol TCP `
    -LocalPort 3000,4317,4318,5432,6379,8000,8080,9090 -Profile Private -Action Allow

  # Só no modo espelhado do WSL: o tráfego passa também pelo firewall do Hyper-V
  Set-NetFirewallHyperVVMSetting -Name '{40E0AC32-46A5-438A-A0B2-2B479E8F2E90}' -DefaultInboundAction Allow
  ```

  A rede da casa precisa estar com o perfil **Privada** no Windows. Para medições com k6, prefira cabo a Wi-Fi entre as máquinas.

- **IP fixo para o servidor** (reserva DHCP no roteador). O IP entra no emissor (`iss`) dos tokens: se ele mudar, os tokens emitidos antes deixam de ser aceitos.

### 2. Clonar e configurar

Clone **dentro do sistema de arquivos do WSL** (ex.: `~/`), e não em `/mnt/c/...`: bind mounts a partir do disco do Windows são lentos e perdem permissões.

```bash
git clone https://github.com/PedroElorriaga/KasaOikos.git ~/home-manager
cd ~/home-manager/infra
cp .env.example .env
```

Edite o `.env`:

- Troque **todas** as senhas `change-me`. Para gerar uma: `openssl rand -hex 24` (hexadecimal evita caracteres que precisariam de escape em URLs de conexão).
- Defina `KEYCLOAK_PUBLIC_URL=http://<IP-do-servidor>:8080`. Esse é o endereço que a estação e o k6 usam, e ele vira o `iss` dos tokens.

### 3. Subir

```bash
docker compose up -d --wait
docker compose ps
```

O `--wait` só retorna quando os serviços com healthcheck (Postgres, Valkey, Keycloak, Prometheus, Grafana e a API) estão `healthy`. Leva cerca de 40 s depois que as imagens estão baixadas; na primeira vez, a imagem da API também é construída (`apps/api/Dockerfile`). Collector, Tempo e Loki usam imagens sem shell, que não comportam healthcheck; a saúde deles aparece em `http://<IP>:9090/targets` (todos `up`).

No primeiro boot, com os volumes vazios:

- `infra/postgres/init/` cria o banco `home`, os roles `hm_migrator` (dono, migrações e seed) e `hm_app` (API, sujeito a RLS), os schemas por módulo e o banco do Keycloak.
- O Keycloak importa o realm `home` de `infra/keycloak/realm-home.json`.

A cada `up`, o serviço `migrate` aplica as migrações (`hm migrate up`) e termina; a `api` só sobe depois dele.

Os dois passos acima **só rodam com o volume vazio**. Para aplicar mudanças nesses arquivos (ou trocar senhas do `.env` já aplicadas), recrie tudo:

```bash
docker compose down -v   # apaga os dados de todos os serviços
docker compose up -d --wait
```

### 4. Conferir

```bash
# Emissor do realm: precisa mostrar o IP configurado em KEYCLOAK_PUBLIC_URL
curl -s http://localhost:8080/realms/home/.well-known/openid-configuration | grep -o '"issuer":"[^"]*"'

# Roles do banco: hm_app sem BYPASSRLS
docker compose exec postgres psql -U postgres -d home -c \
  "select rolname, rolbypassrls from pg_roles where rolname like 'hm_%'"
```

A API responde em `http://<IP>:8000` (`/docs` lista as rotas; `/health/ready` checa banco e cache). Depois de mudar o código, reconstrua e suba de novo:

```bash
git pull
docker compose up -d --build --wait api
```

Para o experimento `workers × pool_size` (design D9), mude `HM_WORKERS` e `HM_DB_POOL_SIZE` no `.env` e rode `docker compose up -d --wait api`. O total de conexões da API é `HM_WORKERS × HM_DB_POOL_SIZE` e precisa caber em `POSTGRES_MAX_CONNECTIONS`, junto com o Keycloak.

Abra o Grafana em `http://<IP>:3000` (usuário e senha `GRAFANA_ADMIN_*` do `.env`). Em *Connections → Data sources*, Prometheus, Tempo e Loki devem passar no *Test*.

## Apontar a estação para o servidor

Na estação, guarde o endereço do servidor numa variável de ambiente do usuário (PowerShell, uma vez; abra um terminal novo depois):

```powershell
[Environment]::SetEnvironmentVariable("HM_SERVER", "192.168.0.10", "User")   # use o IP do servidor
```

Teste o acesso às portas a partir da estação:

```powershell
foreach ($p in 3000, 4318, 5432, 8000, 8080, 9090) {
  $ok = (Test-NetConnection $env:HM_SERVER -Port $p -WarningAction SilentlyContinue).TcpTestSucceeded
  "{0,5}  {1}" -f $p, $(if ($ok) { "ok" } else { "FALHOU" })
}
```

Endereços usados a partir da estação:

| Serviço | Endereço | Quem usa |
|---|---|---|
| Keycloak | `http://$HM_SERVER:8080` (realm `home`) | k6 (tokens), seed (Admin API), navegador |
| Grafana | `http://$HM_SERVER:3000` | navegador |
| Prometheus | `http://$HM_SERVER:9090` (`/api/v1/write` para o k6) | k6 (remote write) |
| OTel Collector | `$HM_SERVER:4317` (gRPC), `http://$HM_SERVER:4318` (HTTP) | API rodando na estação, se for o caso |
| Postgres | `$HM_SERVER:5432`, banco `home` | seed (`hm_migrator`), inspeção com `psql` |
| Valkey | `$HM_SERVER:6379` | API rodando na estação, se for o caso |
| API | `http://$HM_SERVER:8000` | k6, clientes |

As senhas ficam só no `infra/.env` do servidor. Copie para a estação apenas as que forem necessárias (ex.: `HM_LOADTEST_CLIENT_SECRET` para o k6), sempre fora do repositório.

> Os testes automatizados **não** usam o servidor: sobem Postgres e Redis próprios via testcontainers no Docker da estação.

## Testes de carga

Seed, cenários do k6 e resultados: [`loadtest/README.md`](loadtest/README.md).

## Desenvolvimento

```bash
uv sync                      # instala o workspace
uv run pytest                # testes
uv run ruff format . && uv run ruff check . && uv run mypy && uv run lint-imports
```
