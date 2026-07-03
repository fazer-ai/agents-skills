# 02: Reproduzir (no playground, sem tocar a conversa real)

Antes de mexer em qualquer config, reproduza o comportamento de forma isolada. O **playground** roda o **mesmo** modelo + system prompt + tools (knowledge/HTTP/MCP/integração) que produção, mas **sem** Chatwoot, webhook, debounce ou auto-reply: nada vaza para a conversa do cliente.

## Como rodar

- **Console:** editor do agente → aba **Playground**. Chat panel (Enter envia, Reset reinicia). Cada resposta expande em `trace` (tool calls/resultados) + `sources` (grounding da KB).
- **MCP:** `agent_playground` (`mcp:read`; args `agent_id`, `message`, `thread_id?`) → `{ reply, threadId, trace, sources }`.
- **REST:** `POST /api/v1/agents/:id/playground { message, threadId? }` (TENANT_ADMIN).

O `enabled` do agente é ignorado no playground (você testa antes de ligar). Os toggles por-feature (`stt.enabled`/`vision.enabled`) são respeitados; resposta em áudio é um toggle manual (`forceAudio`).

## Reconstituir o turno

Mande a mesma mensagem (ou a sequência) que disparou o problema. Para multimodal, o playground aceita `attachment` (base64/url). Use o `trace` + `sources` para ver se o agente chamou a tool certa, fez grounding na KB certa, e por que respondeu o que respondeu.

## Limites a ter em mente

- **Não é simulação pura:** as tools de HTTP/integração do agente **executam de verdade** (uma write tool escreve). Se o agente tem tool que muda estado externo, reproduzir pode causar efeito colateral real. Avalie antes.
- Sem mirror/conversa, as vars de contato/prompt vêm vazias (`instanceId`/`conversationId` dummy). Comportamento que depende de dados da conversa real (nome do contato, atributos, histórico daquela conversa) não reproduz idêntico aqui: o playground isola o **agente**, não o **estado da conversa**.
- A thread do playground é **fenced** (`tenant:playground:agentId:uuid`): um `threadId` só é aceito se casar essa forma exata; qualquer outra (ex.: a thread de uma conversa real) é rejeitada. Não dá para "abrir" a conversa do cliente pelo playground.
- Memória multi-turno: o cliente segura o `threadId` retornado entre turnos; Reset começa nova sessão.
