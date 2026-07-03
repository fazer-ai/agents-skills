# 00: Obter o código (Free ou Pro)

Bifurca por edição. Pergunte ao desenvolvedor qual ele tem acesso, ou deduza: sem credencial da comunidade = Free.

## Free (repo público)

Clone direto, sem credencial:
```sh
git clone https://github.com/fazer-ai/agents.git fazer-ai-agents
```
(O repo Free é `fazer-ai/agents`.)

## Pro (repo privado via git proxy do hub)

O código Pro/Full (`fazer-ai/agents-pro`) é privado. O acesso é por **credencial per-user do hub** (a mesma que serve a marketplace de skills), usada como HTTP Basic no git proxy — não por convite direto no GitHub.

1. Logue no hub (`app.fazer.ai`) e obtenha a credencial git/NPM **per-user** (a mesma da marketplace de skills). No console do hub, o card de código-fonte Pro revela a credencial e o comando de clone prontos; uma credencial por usuário, válida em todas as suas máquinas.
2. Clone autenticado pelo git proxy do hub (fetch-only — você não dá push aqui; contribuições vão pro repo Free):
```sh
git clone https://<user>:<token>@app.fazer.ai/git/agents-pro.git fazer-ai-agents-pro
```
3. **Nunca** logar o token nem commitá-lo.

## Não-redistribuição (Pro)

Código e imagem Pro são privados e concedidos individualmente. Nunca publique repo, imagem ou trechos exclusivos do Full em local público (gist, fork público, registry público, post, screenshot).
