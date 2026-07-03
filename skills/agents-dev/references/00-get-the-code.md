# 00: Obter o código (Free ou Pro)

Bifurca por edição. Pergunte ao desenvolvedor qual ele tem acesso, ou deduza: sem credencial da comunidade = Free.

## Free (repo público)

Clone direto, sem credencial:
```sh
git clone https://github.com/fazer-ai/agents.git
```
(O repo Free é `fazer-ai/agents`; a marca client-facing do produto ainda pode mudar.)

## Pro (repo privado via git proxy do hub)

O código Pro/Full (`fazer-ai/agents-pro`) é privado. O acesso é por **credencial per-user do hub** (a mesma que serve a marketplace de skills), não por convite direto no GitHub.

1. Garanta o login no hub (`app.fazer.ai`) e a credencial git/NPM **per-user** (via o MCP `app-fazer-ai`; dry-run, depois apply com OK). Uma credencial por usuário, válida em todas as suas máquinas.
2. Clone autenticado pelo git proxy do hub:
```sh
git clone https://<user>:<token>@app.fazer.ai/git/<repo-do-codigo>.git
```
3. **Nunca** logar o token nem commitá-lo.

> **Dependência do hub (em aberto):** hoje o git proxy do hub serve a marketplace de **skills**, não o código-fonte do fazer.ai agents. O endpoint que serve `fazer-ai/agents-pro` ainda será exposto no hub; até lá, o caminho Pro não é exercitável e o path acima (`/git/<repo-do-codigo>`) é o contrato assumido, a confirmar quando o hub publicar.

## Não-redistribuição (Pro)

Código e imagem Pro são privados e concedidos individualmente. Nunca publique repo, imagem ou trechos exclusivos do Full em local público (gist, fork público, registry público, post, screenshot).
