## Purpose

Torna o comportamento do sistema observável (saúde, métricas, traces e logs correlacionados), para operar o ambiente e comparar o desempenho entre fases da arquitetura nos testes de carga.

## ADDED Requirements

### Requirement: Health checks
O sistema SHALL expor `GET /health/live` e `GET /health/ready` sem exigir autenticação nem lar ativo. O endpoint de liveness MUST responder `200` sempre que o processo estiver atendendo requisições. O de readiness MUST responder `200` somente quando o banco de dados e o cache estiverem acessíveis e, caso contrário, `503` indicando qual dependência falhou.

#### Scenario: Sistema saudável
- **WHEN** banco e cache estão acessíveis e um cliente chama `GET /health/ready`
- **THEN** a API responde `200`

#### Scenario: Banco indisponível
- **WHEN** o banco está inacessível e um cliente chama `GET /health/ready`
- **THEN** a API responde `503` informando que a dependência `database` falhou
- **AND** `GET /health/live` continua respondendo `200`

### Requirement: Métricas de requisição
O sistema SHALL produzir métricas de contagem e de latência (histograma) das requisições HTTP, rotuladas por método, rota no formato de template (ex.: `/households/{household_id}`) e código de status. Os rótulos das métricas MUST NOT conter identificadores de alta cardinalidade, como id de usuário, id de lar ou valores do caminho.

#### Scenario: Rota com parâmetro
- **WHEN** a API atende `GET /households/<id-concreto>/members`
- **THEN** a métrica é registrada com a rota `/households/{household_id}/members`, e não com o id concreto

#### Scenario: Métricas disponíveis na stack de observabilidade
- **WHEN** a API recebe tráfego
- **THEN** as métricas de taxa, erros e latência (p50, p95, p99) por rota podem ser consultadas no Grafana

### Requirement: Rastreamento distribuído
O sistema SHALL gerar um trace para cada requisição, com spans para o processamento HTTP, para as consultas ao banco e para as chamadas ao cache. Quando a requisição trouxer o header `traceparent` (W3C Trace Context), o trace MUST dar continuidade ao trace de origem. Toda resposta SHALL incluir o identificador do trace no header `X-Trace-Id`.

#### Scenario: Requisição sem contexto de trace
- **WHEN** um cliente chama a API sem `traceparent`
- **THEN** um novo trace é criado e seu identificador é retornado em `X-Trace-Id`

#### Scenario: Continuidade de trace
- **WHEN** um cliente chama a API com um `traceparent` válido
- **THEN** o trace gerado usa o mesmo trace id do header recebido

### Requirement: Logs estruturados e correlacionados
O sistema SHALL emitir logs em formato estruturado (JSON), contendo nível, mensagem, trace id e, quando houver, o id do usuário autenticado e o id do lar ativo. Os logs MUST NOT conter tokens de acesso, códigos de convite nem o header `Authorization`.

#### Scenario: Correlação entre log e trace
- **WHEN** uma requisição autenticada com lar ativo gera uma linha de log
- **THEN** a linha contém o mesmo trace id retornado em `X-Trace-Id`, o id do usuário e o id do lar

#### Scenario: Dados sensíveis
- **WHEN** uma requisição de aceite de convite é registrada em log
- **THEN** nem o token de acesso nem o código do convite aparecem no log
