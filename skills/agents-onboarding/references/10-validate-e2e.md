# 10: Validar E2E

## Pré-condições

- Agente importado e habilitado (`enabled:true`), **em test mode** (`mode:test`, como importado; a validação abaixo roda nesse modo via `/teste`; promover pra produção é decisão do usuário, etapa 8), modelo religado a uma vault key real (etapa 8).
- KB com docs **READY** (etapa 8).
- Inbox do Chatwoot bound ao agente, bot `active` (etapa 9).
- Langfuse com ingestion **207** + wired no fazer.ai agents (etapas 5 e 8).

## 1. Playground (modelo real, sem Chatwoot)

Via MCP (preferido): `agent_playground` (mcp:read; aceita texto ou `attachment` base64/url, e `reply_with_audio`). Via REST: `POST /api/v1/agents/:id/playground`. O agente responde com o modelo real. Cheque **grounding**: pergunte algo coberto pela KB e confirme que a resposta usa o conteúdo indexado (não uma resposta genérica).

## 2. Integração Chatwoot → agents via Inbox API (OBRIGATÓRIO, sem aparelho)

**Este é o teste que NÃO pode ficar pendente:** é a prova de aceite obrigatória de bind + webhook + turn. O WhatsApp físico (2b) é opcional. O agente segue em test mode depois disto; **não** promova pra produção (decisão do usuário, etapa 8).

Checklist objetivo (todos marcados = provado):
- [ ] inbox `Channel::Api` criada **e** bound ao agente (`inbox_bind`, etapa 9; bot `active`)
- [ ] conversa criada **e** test mode ativado nela (`/teste`)
- [ ] mensagem real injetada (incoming, `message_type: incoming`)
- [ ] resposta **outgoing** observada na conversa
- [ ] trace no Langfuse

Como fazer, provando a ponta `incoming → webhook → turn → reply` **sem aparelho**, com um inbox `Channel::Api`:
- Crie um inbox `Channel::Api` no Chatwoot e benda ao agente (`inbox_bind`, etapa 9), que auto-provisiona o Agent Bot + webhook.
- Crie uma conversa e **ative o test mode nela**: injete uma mensagem **incoming** com o conteúdo exatamente `/teste`. Em test mode o agente fica em silêncio numa conversa até receber `/teste` (e deixa uma nota privada explicando o porquê); o `/teste` libera as respostas **só nessa conversa**. Sem ele a mensagem chega e espelha, mas o agente **não** responde: é o comportamento correto do test mode, não uma falha.
- Agora injete a **mensagem real** de teste (incoming, `message_type: incoming`) na mesma conversa. **Monte o JSON da mensagem num arquivo UTF-8** e POSTe apontando pro arquivo (`curl --data @msg.json` ou helper): texto com acento montado inline no PowerShell volta corrompido (`Olá`→`Ol?`), ver `gotchas.md`.
- Cadeia esperada: incoming → webhook (`/api/v1/chatwoot/webhook/:routeToken`) → **debounce** → turn → modelo real → resposta **outgoing** na conversa. Confirme a resposta + o `ExecutionLog`/trace no Langfuse.

## 2b. WhatsApp real (opcional, confirma o transporte)

Pareie a inbox real (Baileys via QR) com um número que o usuário controle e mande uma mensagem: mesma cadeia do passo 2, exercitando o transporte WhatsApp de verdade. Pode ficar pendente sem invalidar o core (a integração já foi provada no 2).

## 3. Traces no Langfuse

- Confirme que o turn aparece no Langfuse (env `production-playground` ou `production`, session = threadId do fazer.ai agents). A ingestion já foi validada em 207 na etapa 5.

## Critério de aceite

Responde no **playground** (com **KB grounding** confirmado) E na **integração via Inbox API** (conversa ativada com `/teste`, em test mode); **trace** no Langfuse. O **WhatsApp físico** é confirmação opcional (a integração já foi provada via Inbox API). O **Kanban** segue o passo 9b: happy-path quando há licença, ausente no OSS.
