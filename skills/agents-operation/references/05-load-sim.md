# 05: Simular clientes concorrentes (carga + teste das ferramentas)

Extensão da "conversa de teste controlada" (04) para **N clientes ao mesmo tempo**: prova que o agente aguenta várias conversas simultâneas **e** que as **ferramentas disparam** de verdade sob concorrência. Use quando quiser validar comportamento sob carga (rajada de atendimentos), ou reproduzir um problema que só aparece com concorrência (corrida no debounce, watermark, limite de tool calls).

Script: [`scripts/simulate-load.py`](../scripts/simulate-load.py) (stdlib-only; roda via Bash com `dangerouslyDisableSandbox:true`).

## Pré-requisitos

- Um inbox **`Channel::Api`** no Chatwoot **ligado ao agente** (auto-provisiona Agent Bot + webhook). **Use um inbox de teste**, nunca o de um cliente real.
- O **token admin do Chatwoot** + `account_id` + `inbox_id`. O token sai do `agents-onboarding/scripts/chatwoot-admin.py provision` (arquivo 0600); o `inbox_id` é o do inbox de teste.

## Rodar

```bash
python3 scripts/simulate-load.py \
  --base-url https://chatwoot.SEU-DOMINIO \
  --token-file /caminho/chatwoot-admin-token \
  --account-id 1 --inbox-id 42 \
  --count 15
```

Cada persona cria um contato + conversa e injeta mensagens **incoming**; a cadeia real (webhook → debounce → turn → modelo → resposta **outgoing**) roda para cada uma. O script fecha com `RESULT_JSON:{...}` (quantas OK, quantas tiveram resposta, mensagens enviadas) e sai `!= 0` se alguma persona falhou.

## Contornar o modo `/teste` (padrão)

Um agente em `mode: "test"` fica **em silêncio** numa conversa até chegar um `/teste` (que ativa só **aquela** conversa). Por isso o script, por padrão, manda `/teste` como **1ª mensagem de cada conversa**: contorna o modo teste **sem** tirar o agente de teste (cada conversa se auto-ativa, o tráfego real segue intocado). É o jeito seguro de simular num agente de teste.

- Agente já em **produção**: passe `--no-activate-test` (ele já responde; o `/teste` viraria só ruído).

## Garantir que o agente TESTA AS FERRAMENTAS

Simular carga sem provocar as tools testa metade do sistema. Os scripts de mensagem padrão já provocam as ferramentas comuns (agendar, link de pagamento, disponibilidade/FAQ). **Para um agente específico, monte o roteiro a partir da lista real de ferramentas dele** (aba Tools do editor) e passe com `--script`:

```jsonc
// tool-script.json — um array de conversas; cada conversa é um array de mensagens.
[
  ["Quero agendar amanhã 15h", "Confirma esse horário"],          // provoca a tool de agenda
  ["Me manda o link de pagamento por PIX da consulta"],            // provoca a tool Asaas
  ["Vocês abrem no feriado? Qual o endereço?"]                     // provoca a busca na KB/FAQ
]
```

```bash
python3 scripts/simulate-load.py ... --script tool-script.json --count 15
```

Regra: **cada mensagem deve deixar óbvio qual ferramenta o agente precisa chamar**. Uma para agenda, uma para cobrança, uma para a KB, etc. Sem isso, a simulação vira só bate-papo e não prova as tools.

## Verificar o resultado

- **Uso das ferramentas:** abra o `/logs` (ExecutionLog, uma linha `turnId` por turno, com o estágio de tool) e/ou o **Langfuse** (traces por conversa) e confirme que **cada ferramenta esperada foi realmente chamada** e não deu erro sob concorrência.
- **Respostas:** o `RESULT_JSON` reporta quantas conversas tiveram resposta do agente; as conversas aparecem no Chatwoot (conta/inbox indicados) para inspeção visual.
- **Regressões de carga:** cheque debounce (respondeu **uma vez** por rajada, não N), limite de tool calls (soft/hard), e nenhum turno preso/erro.

## Segurança

Isso **escreve** (mensagens incoming) num inbox de teste: efeito externo, mas controlado. Não aponte para o inbox de um cliente real. Segue o `00-production-safety.md` (a "conversa de teste controlada", só que em escala).
