# ADR-0004: Staging em uma VM na Azure

Data: 2026-11-21 · Status: **aceita** · Substitui: [ADR-0003](0003-hospedagem-staging.md)

## Contexto

A [ADR-0003](0003-hospedagem-staging.md) escolheu uma VPS na Hetzner com Docker Compose para o staging,
principalmente pelo custo (~€6 a €7/mês). Os requisitos continuam os mesmos: cerca de 1,5 a 2 GB de RAM para
API, Keycloak e Postgres, Keycloak sempre ligado e aprendizado de operação como objetivo.

O que mudou: agora existe acesso de administrador a uma **assinatura Azure da empresa**, com autorização para
usá-la neste projeto. Com isso, o custo deixa de pesar contra a Azure, e ela ainda conta como experiência de
mercado no portfólio.

## Opções consideradas na Azure

| Opção | Como ficaria | Prós | Contras |
|---|---|---|---|
| **VM Linux + Docker Compose** | Uma VM com o mesmo compose do ambiente local + Caddy | Quase nada muda em relação à ADR-0003; staging igual ao local; aprendizado real de ops | Você cuida de SSH, atualizações e backups |
| **Container Apps + Azure Database for PostgreSQL** | Um container app por serviço, com Postgres gerenciado | Sem servidor para cuidar | O Keycloak precisa de uma réplica sempre ligada; deploy, proxy e rede ficam diferentes do ambiente local; reescreve a M0.9 |

## Decisão

**Uma VM Linux na Azure rodando Docker Compose + Caddy**, criada na assinatura da empresa. O front continua em
uma CDN estática gratuita (Cloudflare Pages ou Azure Static Web Apps, que tem plano gratuito com domínio
próprio e HTTPS; a escolha fica para a M0.9).

Todo o resto da ADR-0003 continua valendo: compose de produção, deploy pelo CI via SSH, `pg_dump` diário com
restauração testada, health check externo e a regra de que a IA não acessa o servidor.

### Detalhes da VM

- **Tamanho:** 2 vCPU e 4 GB de RAM, por exemplo `Standard_B2als_v2` (~US$ 27/mês só de computação em East US,
  sob demanda, segundo os agregadores citados abaixo; disco e IP público são cobrados à parte). Uma VM de 1 a
  2 GB não comporta o Keycloak junto com a API e o Postgres. A série B funciona com créditos de CPU, o que basta
  para o staging, mas vale observar o consumo na subida do Keycloak.
- **Região:** escolhida na M0.9, comparando preço e latência. Brazil South costuma ser mais cara; confirme na
  calculadora da Azure.
- **Rede:** NSG liberando apenas as portas 22, 80 e 443, e `ufw` na VM com as mesmas regras (defesa em
  profundidade). A porta 5432 e o console admin do Keycloak nunca ficam expostos.
- **Backup:** `pg_dump` diário enviado para um container **privado** do Azure Blob Storage, com credencial de
  escopo mínimo (só escrita naquele container) guardada no `.env` do servidor.

### Regras por ser uma assinatura da empresa

- Tudo fica em um **resource group dedicado** (ex.: `rg-kasaoikos-staging`), com tags de projeto, para ser fácil
  de auditar e apagar.
- **Alerta de orçamento** no Cost Management para esse resource group.
- **O CI não recebe credenciais da Azure.** O deploy continua por SSH na VM, então nenhum service principal com
  acesso à assinatura vai parar no GitHub.
- ID da assinatura, ID do tenant e outros identificadores da empresa não entram no repositório (que é público).
- O staging só guarda **dados de teste**; nenhum dado pessoal real entra no ambiente da empresa.

## Consequências

- (+) Custo coberto pela assinatura da empresa; experiência com Azure no portfólio.
- (+) A M0.9 muda pouco: o compose, o deploy e o runbook seguem a ADR-0003, trocando só o provedor.
- (−) O staging depende do acesso à conta da empresa. Se o acesso acabar, voltar para a Hetzner (plano B) custa
  pouco, porque tudo roda em containers e o deploy é por SSH.
- (−) Políticas da empresa (Azure Policy) podem bloquear ou exigir configurações, como IP público ou tags.
  Se isso acontecer, ajustar o runbook ou voltar ao plano B.
- (−) Sem créditos, uma VM equivalente na Azure custaria várias vezes o preço da Hetzner. Ou seja, a decisão só
  se sustenta enquanto a empresa pagar.

## Fontes (preços de nov/2026, de agregadores; confira na calculadora oficial)

- B2als_v2: https://www.economize.cloud/resources/azure/pricing/virtual-machine/b2alsv2/ · https://calculator.holori.com/azure/vm/standard-b2als-v2/eastus
- Static Web Apps: https://learn.microsoft.com/azure/static-web-apps/quotas · https://azure.microsoft.com/pricing/details/app-service/static/
- Calculadora oficial: https://azure.microsoft.com/pricing/calculator/
