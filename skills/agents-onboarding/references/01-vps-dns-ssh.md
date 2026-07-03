# 01: VPS + DNS + SSH

## VPS: qual VPS é escolha do usuário (pergunte, não escolha)

O **`<VPS_IP>` vem do usuário**, nunca de um chute. Se ele não disse qual e o MCP lista mais de uma VM na conta (`VPS_getVirtualMachinesV1`), **apresente as opções (id, IP, hostname, plano) e pergunte qual usar**: ter o MCP conectado não autoriza escolher por ele. Confirmada a VPS, **nunca toque em outra** da conta (ver `guardrails.md`). O orquestrador (Coolify, Portainer, outro painel, ou nenhum) já está instalado (brownfield) ou será instalado no deploy do tier (escolhido em 1c).

## SSH: sondar o acesso antes de gerar chave

O acesso à VPS é o 1º ponto onde a run costuma emperrar (a run real bateu em `Permission denied`). O jeito de não emperrar: **sonde antes de pedir qualquer coisa**, e quando precisar de uma chave nova, **guie o cadastro em passos curtos e espere**. **Nunca peça "o caminho da chave SSH" de cara** e **nunca use senha de root** (só chave). Ordem:

**1. Sonde o acesso** (sem perguntar nada): tente logar com as chaves que o operador já tem (default em `~/.ssh` + agent):
```sh
ssh -o ConnectTimeout=12 -o BatchMode=yes -o StrictHostKeyChecking=accept-new root@<VPS_IP> 'echo OK; hostname'
```
- Saiu `OK` → **há acesso**; siga, **não pergunte nada de chave**. Anote qual chave funcionou pra reusar no resto do fluxo.
- `Permission denied (publickey…)` ou exit ≠ 0 → **sem acesso ainda**. Antes de gerar uma chave nova, tente a dedicada de uma run anterior: se `~/.ssh/fazer-ai-agents` existe, sonde de novo com ela (`-i ~/.ssh/fazer-ai-agents`). Logou → já está cadastrada, **reuse** (não gere outra nem peça re-paste). Senão, passo 2. (`BatchMode=yes` evita travar pedindo senha; `dangerouslyDisableSandbox: true` é obrigatório por ser rede.)

**2. Sem acesso: gere a chave dedicada e mostre a pública pro operador cadastrar.** Use `scripts/sshkey.py` (não monte o `ssh-keygen` à mão): ele chama o `ssh-keygen` com **argv direto**, então a passphrase vazia passa em qualquer SO. No PowerShell (Windows) o `ssh-keygen -N ""` cru **perde** o argumento vazio, cai no prompt interativo e **trava**.
```sh
python3 scripts/sshkey.py generate --name fazer-ai-agents --comment fazer-ai-onboarding
```
Saída JSON com `public_key` (idempotente: se a chave já existe, só reimprime). **Use o nome FIXO `fazer-ai-agents`, literal, nunca um sufixo inventado nem um placeholder** (`fazer-ai-<algo>`): com nome estável o generate reusa a MESMA chave em toda run, e o operador cola a pública **uma vez só**. Nome novo a cada vez faz a chave que ele colou "sumir" (o agente passa a usar outra) e força re-paste, o atrito recorrente aqui. Mostre a linha `ssh-ed25519 …` e **guie o cadastro no painel em passos curtos** (você **não** faz isto pela API, ver *Nota MCP*), em linguagem clara: "gerei uma chave de acesso; cole a linha abaixo no painel da sua VPS pra eu conseguir entrar":
- **Hostinger:** painel da VPS → card **"Chave SSH"** → **"Gerenciar"** → **"+ Chave SSH"** → cole a chave pública → **"Salvar"**.
- **Outro provedor:** o equivalente no painel dele ("SSH Keys" / "Add SSH key" da VPS).

**3. Espere o cadastro e confirme sozinho.** Em vez de pedir "me avise quando cadastrar", deixe o helper **aguardar** o acesso (faz poll do SSH e detecta sozinho quando a chave entra). **Rode em background, não em foreground** (o poll trava o seu turno enquanto o operador cola a chave); retome quando sair:
```sh
python3 scripts/sshkey.py wait-access --ssh root@<VPS_IP> --ssh-opts "-i ~/.ssh/fazer-ai-agents"   # em background, non-blocking
```
`ok:true` → há acesso, siga. `ok:false` (timeout) → aí sim volte ao operador (ver troubleshooting abaixo). Daí use o **comando de trabalho** no resto do fluxo, com a chave que funcionou (a dedicada `~/.ssh/fazer-ai-agents`, ou a existente que a sondagem achou no passo 1):
```sh
ssh -o IdentitiesOnly=yes -o IdentityAgent=none -o ConnectTimeout=12 -o BatchMode=yes \
    -o StrictHostKeyChecking=accept-new -i ~/.ssh/fazer-ai-agents root@<VPS_IP>
```
Bash com rede → `dangerouslyDisableSandbox: true`. Um comando de **uma linha sem** `"`/`$()`/`{{…}}`/`(` pode ir inline; qualquer **script não-trivial** (multi-linha, com aspas/`$()`/`{{…}}`/heredoc) vai por arquivo `.sh` + `scripts/remote.py`, nunca inline no `ssh <host> '…'` nem por here-string no PowerShell (aspas comidas + BOM; ver `gotchas.md`). **Windows:** passe o caminho da chave no `--ssh-opts` (helpers preservam as barras `\`); todo helper que fala SSH aceita `--ssh-opts "-i <caminho>"`.

### Se persistir "Permission denied (publickey,password)"

O sintoma da run real. Não é um beco sem saída; quase sempre é uma destas causas, na ordem pra checar:

1. **A chave ainda não foi salva no painel** (ou salvou em outra VPS). É a causa nº 1: o poll do passo 3 continua `ok:false` porque a chave não entrou. Peça ao operador, **em linguagem simples**, pra confirmar que colou a chave **nesta** VPS e clicou Salvar: "não consegui entrar ainda; você chegou a colar aquela chave no painel desta VPS e salvar?".
2. **Chave errada apontada.** Confirme que o `-i` aponta pra chave cuja **pública** foi cadastrada (`~/.ssh/fazer-ai-agents` se você gerou no passo 2). Se a sondagem do passo 1 achou uma chave existente, use **essa**, não a dedicada.
3. **Provedor só injeta a chave em provisionamento.** Em alguns provedores, cadastrar a chave no painel só a aplica ao **criar/recriar** a VM, não numa VM já rodando (é o caso da API Hostinger, ver *Nota MCP*). Se o painel não aplica a quente, o operador precisa adicioná-la por um acesso que já funcione (um console web do provedor, ou uma chave que já entra) e colá-la nas chaves autorizadas do root (o arquivo padrão de chaves SSH, em `~/.ssh/`). **Nunca** recrie a VM pra forçar a chave: isso apaga os dados.
4. **Login de root desabilitado.** Se `PermitRootLogin` está `no` no `sshd`, nem a chave certa entra como root. Aí o operador loga com o usuário dele (com sudo) e o fluxo segue com esse usuário + `sudo` (o `remote.py` tem `--sudo`).

Só depois de descartar 1 e 2 (as comuns) leve 3/4 ao operador. Enquanto isso, **não** caia pra senha de root nem invente contornos.

### Nota MCP: cadastre a chave pelo painel, não pela API
A API de chaves não serve aqui: `attach`/`create` registram a chave mas não a injetam numa VM em execução (só aplicam em provisionamento/`recreate`, que apaga dados). Por isso a skill cadastra a chave **pelo painel da VPS** e confirma o acesso **por sondagem** (passo 3).

## DNS (MCP Hostinger, domínio `<seu-dominio>`)

O **domínio raiz (`<seu-dominio>`) é escolha do usuário**: liste os domínios da conta (`domains_getDomainListV1`) e **pergunte qual usar como raiz**: nunca assuma um porque "estava na conta". Definido o raiz, crie os A-records apontando pra `<VPS_IP>` (os três da app são o contrato; ver 1c):
- `agentes.<seu-dominio>`: fazer.ai agents
- `chatwoot.<seu-dominio>`: Chatwoot (Pro ou OSS)
- `langfuse.<seu-dominio>`: Langfuse (recomendado)
- **painel do orquestrador** (se houver e você quiser um domínio limpo): `coolify.` (Tier A) / `portainer.` (Tier B); outro painel usa o próprio; no compose genérico (Tier C) pode não haver painel.

Tools do `hostinger-dns`: `DNS_getDNSRecordsV1` (inspecionar), `DNS_updateDNSRecordsV1` (setar). **Monitore a propagação** antes de prosseguir: o ACME (Traefik do Coolify, Caddy do Portainer, ou o proxy do tier) só emite o certificado quando o A-record resolve. Sem isso, os serviços sobem mas ficam 503/sem TLS.

## Outro provider (VPS/DNS fora da Hostinger)

Se o usuário usa outro provider de VPS e/ou DNS, **não há MCP da Hostinger**. Pergunte qual provider ele usa e conduza com base no seu conhecimento dele. Só o **provisionamento de VPS/DNS** muda de ferramenta; do SSH em diante (deploy do tier, agents, branding, bind) o fluxo é idêntico.

- **DNS:** crie os **mesmos A-records** (`agentes.`/`chatwoot.`/`langfuse.` + o painel do tier → IP da VPS) pelo painel/CLI/API do provider do usuário. Monitore a propagação igual (o ACME só emite o cert quando o A-record resolve).
- **VPS:** o usuário cria a VPS no provider dele e fornece **IP + chave SSH**. Confirme que a porta 22 está aberta e que dá pra logar como root (ou com sudo). O resto da `01` (comando SSH, base64-pipe) vale igual.
- **Sem VPS ainda?** Sugira adquirir (recomendado: Hostinger, [link de parceiro fazer.ai](https://www.hostg.xyz/SHJfs), cupom `FAZERAI` = 10% de desconto na primeira compra). Detalhe na `00-prereqs-and-access.md`.
