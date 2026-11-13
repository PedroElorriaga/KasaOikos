# ADR-0003: Hospedagem do staging

Data: 2026-11-11 · Status: **aceita**

## Contexto

O staging precisa rodar:

| Componente | RAM estimada |
|---|---|
| API FastAPI | ~300 a 512 MB |
| Keycloak (ADR-0002) | ~512 MB a 1 GB |
| PostgreSQL (um servidor, dois bancos: `app` e `keycloak`) | ~256 a 512 MB |
| Front (arquivos estáticos do Vite) | nenhuma, pode ir para CDN gratuita |
| Observabilidade (fase 2) | `grafana/otel-lgtm` é pesado; alternativa é o plano gratuito do Grafana Cloud |

Total: **cerca de 1,5 a 2 GB de RAM** sem a observabilidade.

Restrições: projeto pessoal (custo baixo), aprendizado em primeiro lugar e Keycloak sempre ligado (não pode "dormir", senão o login fica lento).

## Comparação (preços pesquisados em nov/2026; confira na página oficial antes de assinar)

| Opção | Como ficaria | Custo/mês estimado | Prós | Contras |
|---|---|---|---|---|
| **VPS Hetzner (CX23 ou CAX11) + Docker Compose** | Uma VM com o mesmo compose do ambiente local + Caddy (HTTPS automático) | **~€6 a €7** (+20% se ligar o backup da Hetzner) | Mais barato; staging igual ao ambiente local; aprendizado real de ops (portfólio) | Você cuida de firewall, SSH, atualizações e backups; disponibilidade dos planos pequenos instável em 2026 (alternativa CPX22 ~€20) |
| **Railway** | Um serviço por componente + Postgres | **~US$ 15 a 20** (US$ 5 de assinatura + ~US$ 10/GB RAM/mês pelo uso) | Zero ops; deploy por git push; cobra pelo uso real | Custo cresce com a RAM do Keycloak; menos controle |
| **Fly.io** | Machines para API e Keycloak; Postgres próprio em volume ou gerenciado | **~US$ 15** (Postgres próprio) ou **~US$ 50** (Managed Postgres a partir de US$ 38) | Boa DX; Machines combinam com a fase de serviços | Postgres gerenciado caro; Postgres próprio exige cuidar de backup |
| **Render** | API Starter, Keycloak Standard (2 GB), Postgres Basic | **~US$ 38** (7 + 25 + 6) | Simples; Postgres gerenciado | Mais caro para o Keycloak; plano gratuito dorme após 15 min e o Postgres grátis expira em 30 dias, então não serve |

## Decisão

**VPS na Hetzner com Docker Compose**, com o front em uma CDN de arquivos estáticos gratuita (Cloudflare Pages ou similar).

Motivos:
1. É de 2 a 6 vezes mais barata que as alternativas, para um projeto que pode ficar meses no ar.
2. O compose de staging é praticamente o mesmo do ambiente local, o que diminui o "na minha máquina funciona".
3. Configurar e proteger um servidor (firewall, HTTPS, backup testado, deploy pelo CI) é exatamente o tipo de experiência que o projeto quer mostrar.

**Plano B:** se o objetivo for zero ops, usar **Railway**. A mudança é barata, porque tudo já roda em containers.

## O que o deploy na VPS exige (vira tarefas da fase 0)

- Acesso SSH só por chave, login de root desativado, firewall liberando apenas as portas 22, 80 e 443.
- Atualizações de segurança automáticas (`unattended-upgrades`).
- Caddy como proxy reverso com HTTPS automático; o console admin do Keycloak fica fora do proxy público.
- Segredos em `.env` no servidor (nunca no repositório) e diferentes dos segredos locais.
- CI faz build das imagens, publica no GHCR e faz o deploy via SSH (`docker compose pull && up -d`).
- `pg_dump` diário enviado para um storage externo, com **teste de restauração** documentado.
- Monitoramento mínimo: health check externo e alerta se a API cair.

## Consequências

- (+) Custo baixo e previsível; ambiente fiel ao local; bom material de portfólio.
- (−) A segurança e a disponibilidade do servidor ficam por sua conta. A revisão manual vale também para a configuração do servidor.
- (−) Sem alta disponibilidade, o que é aceitável para staging. Produção, se houver, ganha um ADR próprio.
- (−) Na fase 2, a stack Grafana completa pode não caber em 4 GB. Nesse caso, usar o plano gratuito do Grafana Cloud ou uma VM maior.

## Fontes

- Hetzner: https://cloudtally.eu/hetzner-cloud-prices · https://www.bitdoze.com/hetzner-cloud-cost-optimized-plans/
- Render: https://render-web.onrender.com/pricing · https://www.srvrlss.io/provider/render/
- Railway: https://www.budgetforge.dev/tools/railway-pricing-2026
- Fly.io: https://fly.io/pricing/ · https://fly.io/docs/mpg/
