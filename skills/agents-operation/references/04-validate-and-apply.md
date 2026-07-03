# 04: Validar e aplicar

Ordem: re-validar no playground → (quando fizer sentido) conversa de teste controlada → aplicar em produção com aprovação.

## 1. Re-validar no playground

Com o ajuste **proposto** (ou já aplicado num agente de teste/clone), repita no playground o mesmo turno do `02-reproduce.md` e confirme que o comportamento corrigiu. Use `trace` + `sources` para checar a tool/grounding certos. Itere aqui (barato, isolado) antes de tocar tráfego real.

## 2. Conversa de teste controlada (Inbox API)

Quando o problema depende da ponta real (webhook → debounce → turn → reply) e não só do agente, prove headless com um inbox `Channel::Api`, sem aparelho:

- Crie/use um inbox `Channel::Api` no Chatwoot bound ao agente (auto-provisiona Agent Bot + webhook).
- Injete uma mensagem **incoming** pela API do Chatwoot (criar conversa + `POST .../messages` com `message_type: incoming`).
- Cadeia esperada: incoming → `/api/v1/chatwoot/webhook/:routeToken` → debounce → turn → modelo real → resposta **outgoing**. Confirme a resposta + o novo `ExecutionLog`/trace.

Isso exercita o caminho de produção sem expor um cliente real. Faça nesse inbox de teste, não numa conversa de cliente.

## 3. Aplicar

- Só com **aprovação explícita** do usuário para aquela mudança específica.
- Console (editor do agente) ou MCP com `dry_run:false` (mostre o diff do dry-run **antes**).
- O write é registrado: editor → via API normal; MCP → grava `AuditLog` (`actorType: "mcp"`, com before/after projetado e limitado, nunca segredo). Para auditar depois: página de audit ou `audit_list` (MCP read).

## 4. Confirmar em produção

Após aplicar, acompanhe os próximos turnos reais no `/logs` + Langfuse e confirme que o estágio que divergia agora passa. Se uma conversa real ficou com erro pendente, há um badge de erro + botão de **re-engage** na conversa (re-responde o tail não respondido), use só com OK, é envio real ao cliente.

## Tocar a conversa real diretamente (último recurso, efeito externo)

As tools `conversation_*` de escrita (`reply`/`handoff`/`return`/`status`/`reengage`, MCP `mcp:write`) ou a tela de Conversations postam/mudam estado numa conversa **viva** do cliente. O dry-run do `conversation_reply` mostra o **texto exato** que seria enviado; aplicar **não é reversível**. Só com OK explícito, e confirme que o alvo é a conversa certa.
