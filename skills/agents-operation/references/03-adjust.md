# 03: Ajustar (corrigir na camada certa)

Achada a causa, ajuste na camada que a explica. Via **console** (editor do agente) ou **MCP** (write tools, **dry-run primeiro**, aplica só com OK). Toda mutação segue o `00-production-safety.md`.

## Em qual camada está o problema

| Sintoma | Camada | Onde | Tool MCP |
| --- | --- | --- | --- |
| Tom/conteúdo/decisão da resposta | **Prompt/instruções** | editor → General | `prompt_set` |
| Modelo errado/caro/lento, temperatura | **Modelo** | editor → General (seção Model, `modelConfig`) | `agent_update` |
| Usou/não usou a tool certa | **Grants de ferramentas** | editor → Tools | `agent_tools_set` |
| Resposta sem fundamento na base | **Grounding/KB** | editor → Knowledge | `agent_tools_set` (grant RAG), `knowledge_*` |
| Cadência/áudio/janela/agrupamento | **Behavior** | editor → Behavior | `agent_settings_set` |

## Grants de ferramentas: replace-the-set

O editor (`Tools` + `Knowledge`) edita **um** working set de grants e faz **PUT do set inteiro** (substitui, não acumula). O `agent_tools_set` segue o mesmo modelo.

- **NATIVE:** sem grant NATIVE (ou allowlist vazia) = **todas** as tools nativas. Restringir = mandar o subconjunto explícito.
- **RAG:** habilitar = mandar os nomes da tool RAG + os ids das KBs. Vazio = sem RAG (fail-closed).
- MCP: discover por servidor → allowlist. INTEGRATION: checkboxes por toolpack.

## Behavior: o que cada bloco controla (1 linha)

`agent.settings.*`, ajustável no editor → Behavior e via `agent_settings_set` (patch parcial, merge nas sub-chaves, re-lido pelos readers tipados com clamp):

- **debounce**: agrupa a rajada de mensagens e responde **uma vez** (on por padrão; `windowSeconds`, `maxMessagesPerBurst`, `maxWindowSeconds`).
- **stt**: transcreve áudios recebidos (on por padrão, efetivo só com credencial; `provider`/`model`/`language`/`credentialRef`).
- **tts**: responde em áudio: `mode` `never`|`mirror`|`preference` (default `never`).
- **split**: quebra a resposta em balões com "digitando" (off por padrão; só texto).
- **serviceWindow**: janela de 24h do WhatsApp para envios **proativos**: dentro = livre, fora = template HSM ou nota (on por padrão). Não afeta a resposta reativa.
- **grounding**: limiar de distância (`maxDistance`) da busca na KB (distinto do grant RAG da aba Knowledge).

## Credenciais

Nunca passe o segredo cru. Na agents o segredo vive no **vault** e é referenciado por nome (`credentialRef` = `vault:<id>`); MCP traduz nome↔ref na borda, nunca o valor. Credencial faltando não é erro: a tool retorna `needsCredential` + URL do console para o usuário preencher fora de banda.
