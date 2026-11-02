## Purpose

Gerencia os lares (tenants) do sistema: criação, membros, papéis por lar (`admin` | `member`) e convites para entrada de novos membros.

## ADDED Requirements

### Requirement: Criação de lar
O sistema SHALL permitir que qualquer usuário autenticado crie um lar informando um nome de 1 a 80 caracteres. O criador MUST se tornar `admin` do novo lar.

#### Scenario: Criação bem-sucedida
- **WHEN** um usuário autenticado envia `POST /households` com o nome "Casa da Praia"
- **THEN** a API responde `201` com o lar criado, e o usuário passa a ser `admin` dele

#### Scenario: Nome inválido
- **WHEN** um usuário envia `POST /households` com nome vazio ou com mais de 80 caracteres
- **THEN** a API responde `422` e nenhum lar é criado

### Requirement: Consulta e renomeação de lar
O sistema SHALL permitir que qualquer membro consulte os dados do lar e que apenas `admin` o renomeie.

#### Scenario: Membro consulta o lar
- **WHEN** um membro do lar A chama `GET /households/{A}`
- **THEN** a API responde `200` com os dados do lar A

#### Scenario: Admin renomeia o lar
- **WHEN** um `admin` do lar A envia `PATCH /households/{A}` com um nome válido
- **THEN** o lar A passa a ter o novo nome

#### Scenario: Membro comum tenta renomear
- **WHEN** um `member` do lar A envia `PATCH /households/{A}`
- **THEN** a API responde `403` e o nome não muda

#### Scenario: Isolamento entre lares
- **WHEN** um usuário que não é membro do lar B chama `GET /households/{B}` ou `PATCH /households/{B}`
- **THEN** a API responde `404`, sem revelar se o lar B existe

### Requirement: Listagem de membros
O sistema SHALL permitir que qualquer membro de um lar liste seus membros, com nome, e-mail, papel e data de entrada.

#### Scenario: Listagem pelo membro
- **WHEN** um membro do lar A chama `GET /households/{A}/members`
- **THEN** a resposta contém todos os membros do lar A e seus papéis

#### Scenario: Isolamento entre lares
- **WHEN** um usuário que não é membro do lar B chama `GET /households/{B}/members`
- **THEN** a API responde `404`

### Requirement: Alteração de papel de membro
O sistema SHALL permitir que um `admin` altere o papel de qualquer membro do lar entre `admin` e `member`. Um lar MUST sempre ter pelo menos um `admin`.

#### Scenario: Promover membro
- **WHEN** um `admin` do lar A altera o papel de um `member` para `admin`
- **THEN** esse usuário passa a ter papel `admin` no lar A

#### Scenario: Rebaixar o último admin
- **WHEN** o único `admin` do lar A tenta alterar o próprio papel para `member`
- **THEN** a API responde `409` e o papel não muda

#### Scenario: Membro comum tenta alterar papel
- **WHEN** um `member` do lar A tenta alterar o papel de outro membro
- **THEN** a API responde `403`

#### Scenario: Papel é por lar
- **WHEN** um usuário é promovido a `admin` no lar A
- **THEN** seu papel em qualquer outro lar permanece inalterado

### Requirement: Remoção e saída de membro
O sistema SHALL permitir que um `admin` remova qualquer membro do lar e que qualquer membro saia do lar por conta própria. A operação MUST ser rejeitada se deixar o lar sem nenhum `admin`.

#### Scenario: Admin remove membro
- **WHEN** um `admin` do lar A remove um `member`
- **THEN** o usuário removido deixa de ser membro do lar A

#### Scenario: Membro sai do lar
- **WHEN** um `member` do lar A remove a própria membership
- **THEN** ele deixa de ser membro do lar A

#### Scenario: Último admin tenta sair
- **WHEN** o único `admin` do lar A tenta sair do lar
- **THEN** a API responde `409` e a membership é mantida

#### Scenario: Membro comum tenta remover outro
- **WHEN** um `member` do lar A tenta remover outro membro
- **THEN** a API responde `403`

### Requirement: Convites
O sistema SHALL permitir que um `admin` gere um convite para o lar, indicando o papel que o convidado receberá. O convite MUST ser representado por um código secreto de uso único, válido por 7 dias, que o admin compartilha por fora do sistema. O código MUST ser exibido apenas na criação.

#### Scenario: Criar convite
- **WHEN** um `admin` do lar A envia `POST /households/{A}/invites` com papel `member`
- **THEN** a API responde `201` com o código do convite e sua data de expiração

#### Scenario: Membro comum tenta convidar
- **WHEN** um `member` do lar A tenta criar um convite
- **THEN** a API responde `403`

#### Scenario: Aceitar convite válido
- **WHEN** um usuário autenticado que não é membro do lar A envia `POST /invites/accept` com um código válido do lar A
- **THEN** ele passa a ser membro do lar A com o papel definido no convite, e o código deixa de ser válido

#### Scenario: Convite expirado ou já usado
- **WHEN** um usuário tenta aceitar um convite expirado, já utilizado ou revogado
- **THEN** a API responde `410` e nenhuma membership é criada

#### Scenario: Código inexistente
- **WHEN** um usuário tenta aceitar um código que não corresponde a nenhum convite
- **THEN** a API responde `404`

#### Scenario: Já é membro
- **WHEN** um membro do lar A tenta aceitar um convite do próprio lar A
- **THEN** a API responde `409`, seu papel não muda e o convite continua válido

#### Scenario: Revogar convite
- **WHEN** um `admin` do lar A revoga um convite pendente
- **THEN** o convite não pode mais ser aceito

#### Scenario: Isolamento entre lares
- **WHEN** um `admin` do lar A tenta listar ou revogar convites do lar B
- **THEN** a API responde `404`
