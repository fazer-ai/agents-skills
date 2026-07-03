# 00: Segurança de produção (lê primeiro)

O alvo **é** produção. A postura é o inverso do onboarding (onde nada toca produção).

## O que é livre

**Investigação read-only**, sem pedir: ler conversas no Chatwoot, ler o `ExecutionLog` (`GET /v1/logs`, página `/logs`), ler traces no Langfuse, ler a config do agente (editor ou `agent_get`/`agent_settings_get`/`agent_tools_get`), rodar o **playground** (modelo real, mas isolado da conversa), queries de leitura no DB.

## O que exige OK explícito

**Toda mutação**, item a item. Inclui: editar prompt/modelo/grants/behavior/KB do agente, qualquer write tool de MCP com `dry_run:false`, postar/transferir/resolver numa conversa real (tools `conversation_*`: `reply`/`handoff`/`return`/`status`/`reengage`), mexer em credencial/vault, reindexar KB.

- Autorização a um **objetivo** ("conserta esse comportamento") não autoriza o **método** nem aplicar sozinho. Proponha o ajuste exato (qual campo, valor antigo → novo), mostre o diff, espere o aval.
- Aprovação de uma mudança não se estende à próxima.
- **Infra: reiniciar/redeployar/rebuildar serviços** (fazer.ai agents, Chatwoot, Langfuse, orquestrador), rodar **migrations**, ou mudar env/config viva. É mutação de produção, não diagnóstico: pode derrubar estado em voo (um restart do Coolify zera a fila de deploy) e um `migrate` pode ser destrutivo/irreversível. Proponha e espere o OK; nunca como atalho no meio de uma investigação.

## Nunca

- **Editar o DB de produção direto para mudar estado da app.** Use a UI/API/console da própria app: editor do agente, write tools de MCP. Write direto no DB fura o passo de publish/validação (o reader tipado normaliza e faz clamp; o audit registra; o runtime relê) e pode deixar o sistema OK agora e quebrado no próximo restart.
- **Expor segredo** em log, output ou commit. Ao exibir, mascare. O fazer.ai agents retorna segredos só por referência (nome do vault), nunca o valor; respeite isso.

## Dry-run é o padrão das write tools de MCP

Toda write tool previewa um diff campo-a-campo e **não aplica nada** sem `dry_run:false` explícito. Rode o dry-run primeiro, mostre o diff ao usuário, só então aplique com o OK dele. O apply grava um `AuditLog` (`actorType: "mcp"`).
