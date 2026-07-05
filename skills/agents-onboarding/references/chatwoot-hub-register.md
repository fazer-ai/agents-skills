# Licenciar a instância Chatwoot no hub (Kanban/Pro)

Habilita as features **Pro** (Kanban etc.) numa instância Chatwoot **Pro já deployada**. Duas coisas são
necessárias e **distintas**:

- A **imagem Pro** (`harbor.fazer.ai/chatwoot/fazer-ai/chatwoot-pro`) traz o **código** (driver de Kanban,
  Baileys). Sem ela, não há Pro. A edição é escolhida no deploy (ver [`03-chatwoot-pro.md`](03-chatwoot-pro.md)).
- A **assinatura no hub** dá a habilitação em runtime: **imagem Pro sem assinatura ativa = features
  travadas.** Por isso existe o passo do Refresh (não é restart de container).

## Quando: happy-path se há licença

A edição é decidida **no deploy** pelo marcador do CLI `~/.fazer-ai/onboarding.json`
(`chatwootTier` + `chatwootLicenseId`), com fallback pro `hub licenses` se o marcador faltar:
- **`chatwootTier: "pro"`** (ou, sem marcador, há licença CHATWOOT no hub) → deploy da **imagem Pro** e **estes passos são happy-path**: registrar + atachar (use `chatwootLicenseId`) + Refresh pra ligar o Kanban. Não pule.
- **`chatwootTier: "community"`** (ou, sem marcador, sem licença) → deploy da imagem **OSS** (sem Kanban) e segue; nada a fazer aqui.
- **`chatwootSource: "existing"`** (Chatwoot BYO, sem `chatwootTier` no marcador) → detecte Pro/OSS pela **imagem** (etapa 1b); não assuma Pro. Um Pro existente **sem** Kanban pode ser licenciado por estes passos, mas **não é forçado** (só se o usuário quiser); OSS não tem Kanban.

> **Sem licença e o usuário quer Kanban?** Sugira virar membro Pro da comunidade do Lucas Moreira
> ([lucasmoreira.ai](https://lucasmoreira.ai)): ganha licença grátis do Kanban (1 conta no plano mensal,
> 2 ilimitadas no anual). Depois é só rodar o CLI de novo e escolher "já me tornei membro" pra a nova
> licença aparecer; ou seguir em OSS.

> Pré-requisitos: `FRONTEND_URL` setado no container do Chatwoot (vira o host que identifica a instância e
> gateia o Refresh). As ops do hub saem pelo **proxy do CLI** (`bunx @fazer-ai/agents hub …`), que usa
> o OAuth do `~/.fazer-ai/oauth.json` do bootstrap (sem hub MCP na sessão); se ele expirou (erro de auth),
> o operador re-roda o CLI. Writes do hub são **dry-run por padrão** (aplique com `--apply`); mexa só na sua
> própria licença/instância (ver `guardrails.md`).

## Passos

> **Ao pedir o OK do usuário** para aplicar (passos 2 a 4), fale em linguagem de usuário: "vou ativar o seu plano Pro nesta instalação, o que libera o Kanban no Chatwoot". **Não** cite `attach-license`, "Refresh da assinatura", "idempotente" nem os comandos: são o seu mecanismo. Frases boas × ruins em `guardrails.md`.

1. **Identidade da instância.** Pegue o host/identifier que o hub casa, direto do Chatwoot (read-only, sem hub):
   ```sh
   python3 scripts/chatwoot-admin.py installation-id --ssh root@<VPS_IP> --container <chatwoot-rails-container>
   ```
   Devolve `frontend_url` (o host) + `installation_identifier`. O `identifier` que o hub usa é o **host** (ex.: `chatwoot.<seu-dominio>`).
2. **Instância no hub.** Confira se já existe e crie se faltar (dry-run primeiro; `--apply` pra valer):
   ```sh
   bunx @fazer-ai/agents hub instances
   bunx @fazer-ai/agents hub create-instance --identifier chatwoot.<seu-dominio> --apply
   ```
3. **Atacha a licença** (uma feature por instância; os tipos têm que bater). O `--instance` é o id que aparece em `hub instances`:
   ```sh
   bunx @fazer-ai/agents hub attach-license --license <licença CHATWOOT> --instance <id> --apply
   ```
4. **Refresh + verify na instância** (o botão "Refresh" do super admin) via `scripts/chatwoot-admin.py`, que roda o job e reporta os configs da assinatura (NÃO despeja valores crus que poderiam ser segredo):
   ```sh
   python3 scripts/chatwoot-admin.py refresh-subscription --ssh root@<VPS_IP> --container <chatwoot-rails-container>
   ```
   **`jitter_applied: true` é obrigatório** (o script já passa). Sem ele, o job só se reagenda (janela determinística de até 30 min) e o sync nem roda.

   **Leia a saída de volta e só dê o 9b por concluído se vier verde — não basta o comando ter rodado.** Verde = `refreshed: true` **E** `config_keys` lista os `FAZER_AI_SUBSCRIPTION_*` **E** `diagnostics` traz `SYNC_ERROR_MESSAGE` **nil** + `VERIFIED_AT` **recente** (o timestamp do Refresh que você acabou de disparar). Interpretação das falhas:
   - `VERIFIED_AT` vazio/antigo **ou** sem os `FAZER_AI_SUBSCRIPTION_*` em `config_keys` → a assinatura **não** sincronizou e o **Kanban NÃO vai aparecer**. Re-rode o Refresh (o "hub não respondeu" é transitório, ver Erros comuns); se persistir, cheque `FRONTEND_URL` e o attach (passos 2–3) antes de seguir.
   - `SYNC_ERROR_MESSAGE` preenchido → o hub **recusou** (licença não atachada à instância certa / instância errada). Trate a causa; não ignore e não declare 9b feito.

   Confirmação visual do mesmo estado: no super admin (`/super_admin/settings`), "fazer.ai Subscription" fica ativa e o Kanban aparece.

## Erros comuns

- **`hub …` diz que "o hub não respondeu ao refresh da sessão" / instabilidade:** é **transitório** (a
  sessão segue válida; o refresh token nem foi consumido): **rode o MESMO comando de novo** em instantes.
  Só **"sessão expirada/ausente"** (erro de auth real) pede re-rodar o CLI de onboarding pra logar no
  browser. Em nenhum dos casos contorne o `hub` indo por REST/MCP por fora: ou re-tenta, ou re-loga.
- **Kanban não aparece com imagem Pro:** faltou o **passo 4 (o Refresh)**, ou ele rodou mas **não veio verde**
  (confira `VERIFIED_AT` recente + `SYNC_ERROR_MESSAGE` nil + os `FAZER_AI_SUBSCRIPTION_*` em `config_keys`). A
  imagem traz o código; a assinatura libera em runtime. Rode/re-rode o Refresh e confirme o diagnóstico.
- **`FRONTEND_URL` vazio:** o controller do Refresh recusa, e o `installation_host` enviado ao hub fica
  vazio. Sete antes.
- **403 / inativo no `/api/ping`:** a licença não está atachada à instância certa no hub. Confira
  `bunx @fazer-ai/agents hub get-license --license <id>` / `hub get-instance --instance <id>` (casamento por identifier/host).
- **Assinatura "out of sync" > 3 dias:** o job auto-desativa (`auto_deactivate_if_stale`). Rode o Refresh
  pra re-sincronizar.

OSS não tem nada disso (sem Kanban). Migrar OSS → Pro = re-deploy com a imagem Pro + estes passos.
