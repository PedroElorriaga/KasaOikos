# Modelo de domínio

Rascunho para revisão. Os nomes das entidades ficam em português no código.

## 1. Casa e membros

- **Usuario**: `keycloak_sub` (único, vem do token), nome, e-mail, telefone (opcional), chave Pix (opcional).
  É criado no primeiro acesso autenticado. Senha e login ficam no Keycloak (ADR-0002); papéis por casa ficam aqui.
- **Casa**: nome, criada por um usuário.
- **Membro**: liga Usuario ↔ Casa com papel `admin` | `membro`. Constraint única `(casa_id, usuario_id)`.
- **Convite**: token aleatório, expira em 7 dias, uso único.

Regras:
- Toda casa tem pelo menos um admin. Por isso, não é possível remover nem rebaixar o último admin.
- **Autorização em todo endpoint:** o usuário precisa ser membro da casa do recurso
  (ex.: usuário da casa A não lê despesas da casa B). Há teste de integração para cada rota.
- Telefone e Pix só aparecem para membros da mesma casa e nunca vão para logs.
- Race condition: dois aceites simultâneos do mesmo convite. A solução é `UPDATE convites SET usado_em=now() WHERE id=? AND usado_em IS NULL` e conferir as linhas afetadas.

## 2. Tarefas

- **Tarefa**: título, ícone, recorrência (`unica` | `diaria` | `semanal` | `mensal`), dias, modo de atribuição (`fixo` | `rodizio`), membros participantes.
- **OcorrenciaTarefa**: tarefa, data prevista, responsável, `concluida_em`, `concluida_por`.

Regras:
- Ocorrências são geradas para a janela de 14 dias à frente. No MVP, a geração é feita sob demanda ao abrir a tela; job agendado fica para depois.
- No rodízio, o próximo responsável é o membro participante que fez a tarefa há mais tempo.
- Qualquer membro pode concluir (ex.: "eu lavei por você"). O histórico registra quem fez.
- Race: concluir duas vezes. A solução é um update condicional `WHERE concluida_em IS NULL`.

## 3. Custos

- **Despesa**: descrição, categoria, valor em **centavos (inteiro)**, data, `pago_por`, modo de divisão (`igual` | `valor` | `percentual`).
- **ParticipacaoDespesa**: despesa, membro, valor devido em centavos. A soma das participações é igual ao valor da despesa (constraint verificada no serviço e por teste).
- **Acerto**: de → para, valor, data e `chave_idempotencia` (única).

Regras:
- **Saldo** de cada membro = total pago − total devido + acertos recebidos − acertos feitos. O saldo é calculado a partir dos lançamentos e nunca armazenado como campo editável.
- **Arredondamento:** na divisão igual, o centavo que sobra fica com quem pagou. Exemplo: R$ 10,00 dividido entre 3 resulta em 334 + 333 + 333, e quem pagou fica com 334. Essa regra precisa ter teste.
- "Quem deve a quem" usa simplificação de dívidas: algoritmo guloso entre o maior credor e o maior devedor.
- **Nunca confiar no cliente:** o servidor recalcula as participações a partir do modo de divisão e ignora os valores enviados pelo front.
- Editar ou excluir uma despesa é permitido ao autor ou a um admin, e todo o histórico é registrado.
- Idempotência: `POST /acertos` aceita o header `Idempotency-Key`. O duplo clique em "Registrar acerto" não pode duplicar o registro.

## 4. Estoque e lista de compras

- **ItemEstoque**: nome, categoria, unidade, quantidade atual, quantidade mínima.
- **ItemLista**: nome, quantidade, `item_estoque_id` (opcional), adicionado_por, `comprado_em`, `comprado_por`, `despesa_id` (opcional).

Regras:
- Quando a quantidade fica ≤ mínimo, o item entra automaticamente na lista. Só pode haver um item aberto por item de estoque, garantido por índice único parcial `WHERE comprado_em IS NULL`.
- O botão "Está acabando" de um item adiciona à lista sem precisar contar a quantidade exata.
- Marcar como comprado repõe o estoque e, opcionalmente, cria uma despesa com os itens marcados juntos ("Compra do mercado R$ 230").
- Race: dois membros marcando o mesmo item como comprado. A solução é um update condicional.

## 5. Fronteiras de módulo (preparação para serviços)

```
casa  ←  tarefas
  ↑   ←  custos  ←  estoque (compra vira despesa)
```

- Cada módulo expõe um **serviço** (funções públicas). Nenhum módulo acessa tabelas de outro diretamente.
- Comunicação que já nasce como evento interno (in-process no MVP), pronta para virar mensageria:
  `CompraConcluida`, `DespesaCriada`, `TarefaAtrasada`, `MembroEntrou`.
- **Candidatos à primeira extração em Go (fase 3):**
  1. **Notificações**: consome eventos e envia avisos. Não tem regra de dinheiro, é isolado e é um ótimo primeiro serviço.
  2. **Estoque/lista de compras**: domínio simples, com bastante leitura e escrita. Bom para teste de carga.

## 6. Onde o gateway de pagamento se encaixa

Fora do MVP, mas o desenho já reserva o lugar:

- Novo módulo `pagamentos` com uma **porta** (`ProvedorPagamento`: `criar_cobranca`, `consultar`) e um adaptador por gateway (ex.: Pix via PSP).
- Fluxo: o acerto é criado como `pendente` → o gateway gera a cobrança Pix → um **webhook** confirma → o acerto passa a `pago`.
- Requisitos do guia já previstos: assinatura do webhook validada com o corpo bruto, tabela `eventos_processados` com o ID do evento como chave única, idempotency key nas chamadas ao gateway, e consulta do estado atual na API do gateway em vez de confiar na ordem de chegada dos eventos.
- No MVP, `Acerto` já tem `status` e `chave_idempotencia`. Assim, o gateway entra sem migração destrutiva.

## 7. Pontos de revisão manual obrigatória

Autenticação, autorização por casa, cálculo de rateio e saldo, migrations, e o futuro módulo de pagamentos.
