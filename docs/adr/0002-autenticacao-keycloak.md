# ADR-0002: Autenticação com Keycloak (OIDC)

Data: 2026-11-11 · Status: **aceita**

## Contexto

- O guia pede para não implementar login nem hash de senha do zero.
- O app guarda dados pessoais (e-mail, telefone e chave Pix).
- Na fase 3, um módulo vai virar serviço (em Go), e os dois lados precisam confiar na mesma identidade.
- Um provedor de identidade padrão de mercado também conta como item de portfólio.

## Decisão

Usar **Keycloak self-hosted** como provedor OIDC. O app e os serviços futuros atuam apenas como **resource servers**.

### Divisão de responsabilidades

| Fica no Keycloak (autenticação) | Fica no app (autorização e dados) |
|---|---|
| Cadastro, login, logout, troca e recuperação de senha | Tabela `usuarios`, ligada ao Keycloak pelo `sub` do token |
| Hash de senha, política de senha, proteção contra força bruta | Casas, membros e papéis `admin`/`membro` **por casa** |
| Emissão e assinatura dos tokens (JWT) | Telefone e chave Pix (não vão para o Keycloak) |
| Login social (futuro, opcional) | Verificação de "é membro desta casa?" em toda rota |

Os papéis por casa **não** vão para roles do Keycloak. Como um usuário pode ser admin de uma casa e membro de outra, esse modelo pertence ao domínio do app. O Keycloak responde "quem é você", e o app responde "o que você pode fazer aqui".

### Fluxo

1. O front (SPA) usa **Authorization Code + PKCE** com um client público (`kasaoikos-web`). O access token fica **só em memória**, nunca em `localStorage`.
2. O front envia `Authorization: Bearer <token>` para a API.
3. O FastAPI valida o JWT localmente: assinatura via JWKS (com cache), `iss`, `aud`, `exp` e algoritmo permitido (`RS256`).
4. No primeiro acesso, o app cria a linha em `usuarios` a partir de `sub` + `email` (provisionamento automático).
5. Access token curto (5 min) e refresh feito pelo próprio fluxo OIDC.

### Ambientes

- **Local:** Keycloak no `docker compose`. O realm é exportado em `infra/keycloak/realm-kasaoikos.json` e versionado, com usuários de teste fictícios. A senha do admin do Keycloak vem do `.env`.
- **Staging/produção:** Keycloak com banco Postgres **próprio** (separado do banco do app), HTTPS obrigatório, `hostname` configurado e console admin fora da internet pública, se a hospedagem permitir.
- **Configuração do realm:** cadastro aberto, proteção contra força bruta ligada, política de senha mínima, redirect URIs exatas (sem curinga) e CORS restrito à origem do front.

### Testes

- **Integração (maioria):** as rotas recebem tokens assinados por uma chave de teste, e o app aponta o JWKS para essa chave. O Keycloak é um serviço externo, então essa simulação é a permitida pelo CLAUDE.md. Os testes cobrem: token expirado, `aud` errado, assinatura inválida, sem token, e usuário A acessando a casa B.
- **Fumaça (poucos):** um teste no CI sobe o Keycloak real via testcontainers e faz login de verdade para garantir que realm e configuração funcionam.

### Dependências candidatas (confirmar na fase 0 antes de instalar)

- Back: `PyJWT` com `PyJWKClient`, para validar tokens.
- Front: `oidc-client-ts` (genérico, sem prender o front ao Keycloak) ou `keycloak-js`.

## Alternativas consideradas

- **Biblioteca dentro do monolito (argon2 + sessão):** mais simples, mas fluxos como recuperação de senha e força bruta ficariam sob nossa responsabilidade, e cada serviço futuro precisaria confiar no monolito.
- **Provedor gerenciado (Auth0, Clerk):** mais rápido, mas o aprendizado é menor e cria dependência de fornecedor e plano pago.
- **Zitadel:** é mais leve que o Keycloak, mas tem menos material e menos reconhecimento em vagas.
- **BFF (back-end guarda os tokens e o navegador só recebe cookie `httpOnly`):** é mais seguro contra XSS e é o padrão recomendado para SPAs, mas dá mais trabalho. Fica registrado como evolução possível. Por isso a decisão acima já evita `localStorage`.

## Consequências

- (+) Login, senha e força bruta ficam com uma ferramenta consolidada, e os serviços futuros validam o mesmo token sem chamar o monolito.
- (+) Bom material de portfólio: OIDC, PKCE, JWKS, realm como código.
- (−) A fase 0 cresce cerca de 2 dias por causa da curva de aprendizado de OIDC e da configuração do realm.
- (−) Mais um container pesado (cerca de 512 MB a 1 GB de RAM). Isso **pesa na escolha da hospedagem do staging**, e o plano gratuito pode não servir.
- (−) Sem SMTP no MVP não há verificação de e-mail nem "esqueci a senha". Configurar um SMTP de teste fica como tarefa da fase 1.
- (−) Revisão humana obrigatória na validação do token e na checagem de membro da casa.
