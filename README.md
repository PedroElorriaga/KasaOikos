# KasaOikos

App para organizar a casa: tarefas, divisão de custos, estoque e lista de compras.
Serve para quem mora sozinho ou divide a casa com outras pessoas.

> Status: **planejamento**. Ainda não há código. Antes de implementar, revise este README,
> o [modelo de domínio](docs/dominio.md) e os [ADRs](docs/adr/).

## 1. Problema, usuário e métrica de sucesso

- **Problema:** quem divide a casa perde tempo e se desgasta combinando quem faz o quê,
  quem pagou o quê e o que está faltando. Isso costuma ficar espalhado entre grupo de WhatsApp,
  planilha e memória.
- **Usuário:** quem mora sozinho (para organizar a própria casa) e grupos que dividem uma casa
  (república, casal, amigos, família).
- **Objetivo principal:** projeto de portfólio para ganhar experiência real com:
  monolito modular → extração de serviços, testes de integração, CI/CD, observabilidade
  (Grafana) e teste de carga (k6).
- **Critérios de sucesso:**
  1. MVP no ar em staging com deploy automático e CI verde.
  2. Uso real por pelo menos uma casa, a sua, durante 2 semanas.
  3. Dashboard no Grafana com latência, erros e throughput por rota.
  4. Relatório de teste de carga k6 com a meta de desempenho documentada (ex.: p95 < 300 ms com N usuários).
  5. Pelo menos um módulo extraído do monolito para um serviço próprio, com ADR explicando o porquê.
  6. Se houver tração: avaliar o lançamento (fora do escopo por enquanto).

## 2. Escopo da primeira entrega (MVP)

**Entra:**

| Módulo | O mínimo que gera valor |
|---|---|
| Contas e casa | Cadastro/login, criar casa, convidar membros por link, papéis `admin` e `membro` |
| Tarefas | Criar tarefa, definir responsável, recorrência (diária/semanal/mensal), rodízio entre membros, marcar como feita, histórico |
| Custos | Lançar despesa (quem pagou, valor, quem participa), divisão igual ou por valor/percentual, saldo "quem deve a quem", registrar acerto (com a chave Pix do credor visível) |
| Estoque e compras | Itens com quantidade e nível mínimo; item abaixo do mínimo vai para a lista de compras; marcar como comprado, com opção de virar despesa |

**Fica de fora do MVP:**

- Gateway de pagamento (acerto é só registrado manualmente; o ponto de encaixe está desenhado em [dominio.md](docs/dominio.md#6-onde-o-gateway-de-pagamento-se-encaixa)).
- Notificações por push/e-mail (só avisos dentro do app).
- Upload de arquivos (fotos de nota fiscal, avatar).
- App nativo (o front é web responsivo; PWA pode vir depois).
- Várias casas por usuário. O modelo de dados permite, mas a interface do MVP assume uma casa.
- Microsserviços, Kubernetes e filas. Ficam para as fases 3 e 4.

## 3. Roadmap em marcos

Estimativa em faixa, para uma pessoa trabalhando no projeto paralelamente a outras atividades.

| Fase | Entrega | Faixa |
|---|---|---|
| 0. Fundação | Repo, CI, linters, pre-commit, Docker Compose (Postgres + Keycloak), realm versionado, esqueleto do back e do front com login funcionando, contrato OpenAPI gerando tipos no front, deploy em staging | 5 a 7 dias |
| 1. MVP monolito | Auth + casa → Estoque/compras → Tarefas → Custos, nesta ordem (do mais simples ao mais delicado) | 3 a 5 semanas |
| 2. Observabilidade e carga | OpenTelemetry, Grafana (métricas, logs, traces), cenários k6, primeira rodada de otimização | 1 a 2 semanas |
| 3. Primeiro serviço | Extrair um módulo para um serviço em Go, com comunicação por eventos | 2 a 3 semanas |

**Leitura honesta do prazo:** a meta de 4 semanas cobre bem as fases 0 e 1. Incluir as fases 2 e 3
no mesmo período não é realista sem cortar escopo. Sugestão: chegar ao MVP em 4 a 6 semanas, mas
deixar logs estruturados e métricas básicas prontos já na fase 0, porque o custo nesse momento é baixo.

## 4. Riscos e incertezas

| Risco | Impacto | Mitigação |
|---|---|---|
| Keycloak/OIDC é novo e pesado para hospedar | Fase 0 atrasa; staging pago | Realm exportado como código; escolher hospedagem já considerando a RAM do Keycloak |
| Nunca usou k6 nem Grafana | Fase 2 atrasa | Spike de 1 dia com a imagem `grafana/otel-lgtm` e um script k6 simples, ainda na fase 0 |
| TypeScript/Go são novos | Velocidade cai e o código fica difícil de revisar | TS só no front e Go só na fase 3; o domínio fica em Python, que você domina |
| Cálculo de rateio (centavos, arredondamento) | Saldos errados geram desconfiança no app | Valores em centavos (inteiro), regra explícita para o centavo restante, testes de propriedade |
| Race conditions (acerto duplicado, item comprado duas vezes, convite usado duas vezes) | Dados inconsistentes | Constraints e updates atômicos no banco (ver dominio.md) |
| Dados pessoais (e-mail, telefone, Pix) | Vazamento e LGPD | Visíveis só para membros da casa, nunca em logs, exclusão de conta prevista |
| Escopo cresce (é projeto de portfólio, dá vontade de pôr tudo) | Nada fica pronto | A lista "fica de fora" acima vale até o MVP estar no ar |
| Microsserviços cedo demais | Complexidade sem ganho | Fronteiras de módulo bem definidas desde já; só extrair com motivo escrito em ADR |

## 5. Documentos

- [docs/dominio.md](docs/dominio.md): entidades, regras de negócio e pontos sensíveis
- [docs/adr/0001-stack-e-arquitetura.md](docs/adr/0001-stack-e-arquitetura.md): stack e arquitetura
- [docs/adr/0002-autenticacao-keycloak.md](docs/adr/0002-autenticacao-keycloak.md): autenticação com Keycloak
- [docs/adr/0003-hospedagem-staging.md](docs/adr/0003-hospedagem-staging.md): hospedagem do staging
- [docs/specs/fase-0.md](docs/specs/fase-0.md): spec da fase 0 (fundação), dividida em mudanças pequenas
- [CLAUDE.md](CLAUDE.md): convenções para desenvolvimento com IA

## 6. Como rodar / testar

_A preencher na fase 0._
