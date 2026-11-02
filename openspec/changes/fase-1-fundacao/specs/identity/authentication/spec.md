## Purpose

Garante que apenas usuários autenticados pelo provedor de identidade (Keycloak, realm `home`) acessem a API, e mantém um registro local de cada usuário para que os módulos de domínio possam referenciá-lo.

## ADDED Requirements

### Requirement: Validação de token de acesso
O sistema MUST exigir um token de acesso Bearer válido em todos os endpoints, exceto os de health check. O token MUST ser assinado por uma chave publicada pelo provedor de identidade, ter emissor igual ao realm `home`, conter a audiência da API e não estar expirado.

#### Scenario: Token válido
- **WHEN** um cliente chama um endpoint protegido com um token válido emitido pelo realm `home`
- **THEN** a requisição é processada como o usuário identificado pela claim `sub`

#### Scenario: Token ausente
- **WHEN** um cliente chama um endpoint protegido sem o header `Authorization`
- **THEN** a API responde `401` com o header `WWW-Authenticate: Bearer`

#### Scenario: Token expirado
- **WHEN** um cliente envia um token cuja claim `exp` está no passado
- **THEN** a API responde `401`

#### Scenario: Emissor ou audiência incorretos
- **WHEN** um cliente envia um token assinado corretamente, mas emitido por outro realm ou sem a audiência da API
- **THEN** a API responde `401`

#### Scenario: Assinatura inválida
- **WHEN** um cliente envia um token cuja assinatura não corresponde a nenhuma chave publicada pelo provedor
- **THEN** a API responde `401`

### Requirement: Rotação de chaves de assinatura
O sistema SHALL aceitar tokens assinados por uma chave recém-publicada pelo provedor de identidade sem precisar ser reiniciado.

#### Scenario: Chave nova após rotação
- **WHEN** o provedor de identidade passa a assinar tokens com uma chave cujo identificador (`kid`) ainda não é conhecido pela API
- **THEN** a API obtém novamente as chaves publicadas e aceita o token, se ele for válido

### Requirement: Provisionamento do usuário no primeiro acesso
O sistema SHALL criar um registro local do usuário na primeira requisição autenticada, usando `sub`, e-mail e nome do token. Nas requisições seguintes, SHALL atualizar e-mail e nome se tiverem mudado no provedor.

#### Scenario: Primeiro acesso
- **WHEN** um usuário autenticado sem registro local faz sua primeira requisição
- **THEN** o sistema cria o registro local e processa a requisição normalmente

#### Scenario: Dados alterados no provedor
- **WHEN** um usuário que alterou o nome no provedor faz uma requisição com o token novo
- **THEN** o registro local passa a refletir o novo nome

### Requirement: Consulta do usuário autenticado
O sistema SHALL expor `GET /me`, que retorna o perfil do usuário autenticado e a lista dos lares dos quais ele é membro, com o papel em cada um. Esse endpoint não exige lar ativo.

#### Scenario: Usuário com dois lares
- **WHEN** um usuário que é `admin` no lar A e `member` no lar B chama `GET /me`
- **THEN** a resposta contém seu perfil e exatamente os lares A (papel `admin`) e B (papel `member`)

#### Scenario: Isolamento entre lares
- **WHEN** um usuário que é membro apenas do lar A chama `GET /me`
- **THEN** a resposta não contém nenhum outro lar além de A
