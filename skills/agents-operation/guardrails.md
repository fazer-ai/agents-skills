# Guardrails: fronteiras que NÃO se cruzam

Valem em qualquer execução desta skill. Cruzar qualquer uma é **parar e perguntar**. Detalhe em [`references/00-production-safety.md`](references/00-production-safety.md).

## Produção-first

- O alvo **é** produção. **Investigação read-only é livre** (ler conversas, logs, traces, config do agente, queries de leitura, playground). **Mutação não.**
- **Toda mudança precisa de OK explícito do usuário para aquela mudança específica.** Autorização a um objetivo (corrigir um comportamento) não é autorização para escolher o método nem para aplicar sozinho. Proponha o ajuste exato (campo, valor antigo → novo, diff) e espere o aval. Aprovação de uma mudança não se estende à próxima.
- **Nunca editar o DB de produção direto** para mudar estado da app. Use a UI/API/console da própria app (editor do agente, write tools de MCP). Write direto no DB fura o publish/validação e pode quebrar no próximo restart.
- Confirme que o **alvo é o recurso certo** (a conversa/agente/tenant certo) antes de qualquer mutação ou de postar numa conversa viva.

## Dry-run

- Toda **write tool de MCP é dry-run por padrão**: previewa um diff e não aplica nada sem `dry_run:false` explícito. Rode o dry-run, mostre o diff, aplique só com OK. O apply grava `AuditLog`.
- As tools `conversation_*` (`reply`/`handoff`/`return`/`status`/`reengage`) têm **efeito externo real** numa conversa do cliente e não são reversíveis: o dry-run mostra o texto exato; aplicar só com OK.

## Segredos

- **Nenhum segredo em log, output, commit ou arquivo plano.** Ao exibir, mascare.
- O fazer.ai agents referencia segredos por **nome de vault** (`vault:<id>`), nunca o valor; respeite: não tente extrair nem imprimir o plaintext. Credencial faltando → o usuário preenche no console fora de banda.

## Estilo

- PT-BR com acentuação correta (escreva "não"/"ação", nunca "nao"/"acao").
- Nada de em-dash (—) nem en-dash (–): use vírgula, ponto, dois-pontos, parênteses ou reescreva.
- `fazer.ai` sempre minúsculo (slugs `fazer-ai` ok).
