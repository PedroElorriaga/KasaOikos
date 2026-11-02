## Purpose

Define como o lar ativo (tenant) de uma requisição é determinado e validado, e garante que os dados de um lar nunca sejam lidos ou alterados no contexto de outro, inclusive quando o código da aplicação falha em filtrar.

## ADDED Requirements

### Requirement: Determinação do lar ativo
Endpoints com escopo de lar SHALL determinar o lar ativo pelo identificador presente no caminho (`/households/{id}/...`) ou, nos demais endpoints com escopo de lar, pelo header `X-Household-Id`. O identificador do lar MUST NOT ser lido do corpo da requisição.

#### Scenario: Lar ativo pelo header
- **WHEN** um membro do lar A chama um endpoint com escopo de lar informando `X-Household-Id: A`
- **THEN** a requisição é processada no contexto do lar A

#### Scenario: Header ausente
- **WHEN** um cliente chama um endpoint com escopo de lar que depende do header, sem enviar `X-Household-Id`
- **THEN** a API responde `400` indicando que o lar ativo é obrigatório

#### Scenario: Header malformado
- **WHEN** um cliente envia `X-Household-Id` com um valor que não é um identificador válido
- **THEN** a API responde `400`

#### Scenario: Caminho e header divergentes
- **WHEN** um cliente chama `/households/{A}/...` enviando também `X-Household-Id: B`
- **THEN** a API responde `400` e nada é processado

### Requirement: Verificação de membership
O sistema MUST verificar, a cada requisição com escopo de lar, que o usuário autenticado é membro do lar ativo. Quando não for, MUST responder `404`, sem distinguir "lar inexistente" de "lar ao qual o usuário não pertence".

#### Scenario: Usuário não é membro
- **WHEN** um usuário que é membro apenas do lar A envia uma requisição com lar ativo B
- **THEN** a API responde `404`

#### Scenario: Lar inexistente
- **WHEN** um usuário envia uma requisição com um lar ativo que não existe
- **THEN** a API responde `404` com o mesmo corpo do cenário anterior

### Requirement: Revogação imediata de acesso
A perda de membership ou a mudança de papel MUST ter efeito a partir da requisição seguinte do usuário afetado, mesmo que o sistema mantenha cache de memberships.

#### Scenario: Membro removido
- **WHEN** um usuário é removido do lar A e, em seguida, faz uma requisição com lar ativo A
- **THEN** a API responde `404`

#### Scenario: Admin rebaixado
- **WHEN** um `admin` do lar A é rebaixado a `member` e, em seguida, tenta uma operação exclusiva de admin
- **THEN** a API responde `403`

### Requirement: Isolamento garantido pelo banco de dados
Toda tabela que armazena dados pertencentes a um lar MUST ter isolamento por lar aplicado pelo próprio banco de dados, de forma que uma consulta feita pela aplicação só enxergue e só altere linhas do lar ativo da transação, mesmo que a consulta não filtre por lar.

#### Scenario: Consulta sem filtro de lar
- **WHEN** a aplicação executa, no contexto do lar A, uma consulta sem filtro de lar sobre uma tabela com dados de vários lares
- **THEN** o resultado contém apenas linhas do lar A

#### Scenario: Consulta sem lar ativo
- **WHEN** a aplicação executa uma consulta sobre uma tabela com escopo de lar sem ter definido o lar ativo da transação
- **THEN** o resultado é vazio

#### Scenario: Escrita em outro lar
- **WHEN** a aplicação tenta, no contexto do lar A, inserir ou alterar uma linha pertencente ao lar B
- **THEN** o banco rejeita a operação

#### Scenario: Tabela nova sem isolamento
- **WHEN** uma migração cria uma tabela com coluna de lar sem a política de isolamento habilitada
- **THEN** a suíte de testes automatizados falha
