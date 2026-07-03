# 09: Plugar o Chatwoot no fazer.ai agents

> **Ao pedir o OK do usuário** para aplicar (cada `dry_run:false` abaixo), descreva o efeito, não a tool: "vou conectar o seu Chatwoot ao agente e ligar o robô na caixa de entrada, pra ele começar a responder as conversas". **Não** cite `deployment_connect`/`inbox_bind`/`webhook`/"Agent Bot". Frases boas × ruins em `guardrails.md`.

Sequência MCP-first. As tools de deployment são `mcp:admin` (SUPER_ADMIN); `inbox_bind` é `mcp:write`. O admin token do Chatwoot **não é credencial de vault** (é guardado encriptado na linha do deployment), então **não** use o fluxo de pending/deeplink dele. Há dois caminhos pra entregá-lo, conforme quem tem o token (o **mesmo** vale para `chatwootSource: existing`, Chatwoot BYO): se a instância é on-box/alcançável por SSH, o agente pega o token via Rails runner (Caso A); se é off-box (Chatwoot Cloud / outro host), o usuário fornece o token (Caso B).

## 1. Conectar o deployment

### Caso A: o agente provisionou o Chatwoot (tem o token)

O agente extraiu o admin token via Rails runner (etapa 3), então registra direto por MCP, em uma chamada:

```jsonc
deployment_connect { "base_url":"https://chatwoot.<seu-dominio>", "admin_token":"<token cru>" }  // dry_run:false pra aplicar
```

O token é usado in-band e **redatado no audit** (o audit guarda só metadados). Valida via `/profile`, **persiste o deployment** (URL + token criptografado na linha do deployment) e retorna as contas alcançáveis. Ainda **não** conecta as contas: isso é o passo 2.

### Caso B: traga seu próprio Chatwoot (só o usuário tem o token)

O agente **não** tem o token. Em vez de inventar credencial pending (o token nem é de vault), o agente **linka o usuário pra tela `/channels`**: em "Connect instance" (SUPER_ADMIN), o usuário cola Base URL + Admin access token (validado via `/profile`, guardado encriptado). O usuário pode seguir ali pelo "Manage accounts" e pelo bind de inbox, ou devolver pro agente continuar via MCP.

## 2. Conectar a conta + sincronizar inboxes (`deployment_set_accounts`)

```jsonc
deployment_set_accounts { "account_ids": [1] }   // dry_run:false pra aplicar
```

Conecta as contas selecionadas (cria a instância + sincroniza os inboxes pra agents) e soft-desconecta as de-selecionadas. **É este passo que conecta as contas** (o `deployment_connect` só registrou o deployment e listou as contas).

## 3. Bindar o inbox ao agente (`inbox_bind`)

```jsonc
inbox_bind { "inbox_id":"<id do inbox no fazer.ai agents>", "agent_id":"<id do agente>" }   // dry_run:false pra aplicar
```

O bind **provisiona/conecta o bot do agente no Chatwoot** (Agent Bot + webhook `/v1/chatwoot/webhook/:routeToken`); o `routeTokenHash`/`inboundSecretRef` ficam encriptados no fazer.ai agents e **nunca** saem no export. Não precisa setar `webhook_url` à mão. Verifique: bot-status do inbox = `active`.

## Só MCP (nada de REST à mão)

O fazer.ai agents expõe endpoints REST equivalentes por baixo (o que a tela `/channels` chama), mas **não os chame à mão**: as tools MCP `deployment_connect`/`inbox_bind` são o único caminho (regra MCP-only, ver `SKILL.md` e `06-setup-and-mcp.md`).
