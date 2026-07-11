# Guardrails: fronteiras que NÃO se cruzam

Valem em qualquer execução desta skill. Cruzar qualquer uma é **parar e perguntar**.

## Escopo de operação

- **Opere SÓ na infraestrutura que o usuário forneceu e autorizou para este onboarding:** a VPS indicada (`<VPS_IP>`), o domínio indicado (`<seu-dominio>`), e a licença + registry credential do Chatwoot Pro indicadas (`<LICENSE_ID>` / `<REGISTRY_CRED_ID>`). Tudo isso é dado de entrada; as refs usam placeholders.
- **Nunca toque em outras VPS, domínios, instâncias ou licenças da conta do usuário.** A mesma conta (provedor de VPS, DNS, hub `app-fazer-ai`) pode hospedar **produção de terceiros**. Uma write tool errada derruba o serviço de outro cliente, e o token do hub costuma ter `mcp:admin`. Antes de qualquer write no hub (ou ação destrutiva na VPS), **confirme que o alvo é o recurso certo**; na dúvida, pare e pergunte.
- **Ações destrutivas** (recreate/stop/restart/firewall/reset de VPS, reinstalar Coolify, wipe de volume) **só com OK explícito** e só no recurso confirmado como descartável. Em brownfield (VPS já populada), **nunca** destrua dados do usuário: detecte e reaproveite.

## Produção e mutações

- **Nunca** modificar produção a menos que o usuário peça aquela mudança específica. Autorização a um objetivo não é autorização para tocar produção nem para escolher o método.
- **Nunca** editar o DB de produção direto para mudar estado de aplicação: usar a UI/API da própria app. (Durante o provisionamento inicial, antes da app estar no ar, mexer no DB/console via `psql`/Rails runner é aceitável e transitório; uma vez em produção, use a UI/API.)
- **Writes do hub** (via proxy `bunx @fazer-ai/agents hub …`) e **write tools de MCP** são **dry-run por padrão**. Aplicar (`--apply` / `dry_run:false`) só com OK explícito do usuário para aquela ação.

## Como pedir aprovação e falar com o usuário (frases boas × ruins)

Quando você pede um "pode ir" ou faz uma pergunta, o usuário é uma pessoa que quer o agente de atendimento no ar, **não** um engenheiro do produto. Descreva **o que** vai mudar e **por que**, em português comum. **Corte o jargão interno:** nomes de tool (`deployment_connect`, `agent_import`), termos de arquitetura ("dry-run", "idempotente", "tenant", "marcador", "write no hub", "credencial per-user do Harbor", "robot"), nomes de env var e caminhos de arquivo. Isso é vocabulário seu pra executar, não pra repetir ao usuário. Regra prática: se a frase só faz sentido pra quem leu esta skill, reescreva.

Cada ponto de aprovação, com uma frase **ruim** (jargão) e uma **boa** (clara):

- **Ativar a licença Pro / Kanban (hub):**
  - Ruim: "Posso aplicar o write no hub pra atachar a licença e rodar o refresh da assinatura? É idempotente."
  - Boa: "Vou ativar o seu plano Pro nesta instalação, o que libera o Kanban no Chatwoot. Posso seguir?"
- **Baixar a imagem Pro (credencial do registro privado):**
  - Ruim: "Vou provisionar a registry credential per-user do Harbor pelo proxy do hub e fazer o docker login."
  - Boa: "Vou liberar o acesso à versão Pro pra baixar os programas no servidor. Isso usa a sua assinatura; nenhuma senha passa por mim."
  - (Só peça se de fato houver uma escolha; se a edição já foi decidida no início, é um passo automático, não uma pergunta.)
- **Ligar o Chatwoot ao agente (conectar deployment + contas + inbox):**
  - Ruim: "Rodo o `deployment_connect` e depois o `inbox_bind` (dry_run:false) pra provisionar o Agent Bot e o webhook?"
  - Boa: "Vou conectar o seu Chatwoot ao agente e ligar o robô na caixa de entrada, pra ele começar a responder as conversas. Posso aplicar?"
- **Importar o agente:**
  - Ruim: "Vou chamar o `agent_import` no tenant `<slug>` com o export vendorado."
  - Boa: "Vou criar o agente de atendimento (a Maria, uma recepcionista de exemplo) na sua conta. Ele nasce desligado e em modo de teste, então não fala com cliente nenhum até você liberar. Posso criar?"
- **Ligar o Langfuse (traços/monitoramento):**
  - Ruim: "Rodo o `langfuse_connect` inline com as keys que semeei e ligo o tracing no tenant-settings."
  - Boa: "Vou ligar o painel que registra as conversas do agente (pra você acompanhar e depurar depois). Posso seguir?"
- **Criar credenciais que faltam (para o usuário preencher):**
  - Ruim: "O import gerou entradas pending; te mando o deeplink de fill do vault."
  - Boa: "Faltam algumas chaves (por exemplo a da OpenAI) pro agente funcionar. Vou te mandar um link direto pra você colar cada uma com segurança; elas não passam por mim."
- **Ação que apaga ou reinicia algo no servidor (recreate/stop/restart/firewall/apagar volume):**
  - Ruim: "Posso rodar o recreate da VM / wipe do volume?"
  - Boa: "Pra seguir eu preciso reiniciar o serviço X no servidor, o que deixa ele fora do ar por alguns instantes. Confirma que posso?" (E se a ação apaga dados, diga isso explicitamente e espere um "sim" claro.)
- **Ir para produção (agente atende clientes reais):**
  - Ruim: "Faço o `agent_update` com `mode:production`?"
  - Boa: "O teste passou. Quando você quiser, eu coloco o agente pra atender clientes de verdade, é a sua decisão. Me avisa quando for a hora."

Duas regras que valem em todo ponto: (1) uma ação que grava algo roda primeiro em **prévia** (sem efeito) e só vale de verdade com o "pode ir", então deixe claro que nada foi feito ainda; (2) o usuário **cria as contas de admin** (Coolify/Chatwoot/fazer.ai agents) no navegador dele: você entrega o link e a instrução e **espera**, sem criar por conta própria (ver "Gates de criação de conta").

## Segredos

- **Nenhum segredo em repo, log, commit ou arquivo plano.** Cada segredo vive no destino final: env do serviço no Coolify / DB do Chatwoot / **vault do fazer.ai agents** / store de MCP do harness (o token do fazer.ai agents fica no harness do agente).
- **Nunca `cat`/imprima arquivos de credencial locais** do CLI/agente: `~/.fazer-ai/oauth.json` (refresh token do hub), `*.token`, `*.keys.json`, `/root/.docker/config.json`. Para checar presença, teste só a existência (`Test-Path` / `[ -f … ]`) ou um `grep -q` **sem** imprimir o conteúdo; despejar o arquivo no output coloca o segredo no transcript (que persiste em disco). Mesma regra dos logs: redija (`sed -E 's/(token=|password=|secret=)[^ ]+/\1[REDACTED]/'`) antes de mostrar.
- Segredos de infra usados pelo agente são **buscados transitoriamente** no momento do uso (token do Chatwoot via Rails runner, senha do Coolify-db via env do container), nunca persistidos em disco.
- Credenciais do **usuário** (OpenAI/ElevenLabs/Asaas) entram como **pending + deeplink**: o usuário preenche no console; nunca passam pelo agente.
- **Passar um segredo como ARGUMENTO de uma tool sancionada NÃO é vazar; é o caminho correto e obrigatório.** As tools de infra que recebem segredo in-band, `deployment_connect`/`langfuse_connect` (token/keys inline) e os helpers com `--secret-file`/header `api-access-token`, são o único jeito de conectar: o audit **redige o segredo server-side** (guarda só metadados) e a tool nunca o devolve. **NUNCA recuse uma tool sancionada por medo de "segredo no argumento"**, nem invente um fluxo pending/deeplink pro admin token do Chatwoot (ele não é de vault: fica encriptado na linha do deployment). O que a regra acima proíbe é **transitar o segredo pro output/log/repo** (`cat`/print/commit sem redigir), não passá-lo a uma tool. Para levar o `api_access_token` do arquivo `0600` (`chatwoot-admin.json`) pro uso **sem imprimi-lo**: os helpers de shell leem `--secret-file <arquivo>` (o token nunca entra no argv); a tool MCP `deployment_connect` recebe como argumento o token que você já extraiu (caminho sancionado, audit redige). Em nenhum dos casos rode `cat chatwoot-admin.json` no terminal, que joga o token no transcript. Em resumo: o segredo pode transitar **de arquivo `0600` → argumento da tool**; o que não pode é **transitar pro output/log/repo**.

## Gates de criação de conta

- O **usuário** cria o 1º admin no browser do orquestrador (Coolify/Portainer), do Chatwoot e do fazer.ai agents (`/setup`). O agente **entrega o link + a instrução e espera** o usuário criar; **nunca** cria essas contas por conta própria (não há atalho: nada de CLI/console/auto-seed criando esses admins). Na agents, a URL `/setup` **não pede token** (o onboarding sobe com `SETUP_TOKEN_REQUIRED=false`). Depois da conta criada, o agente segue (obtém o token do Chatwoot via Rails runner transitório, deploy, config). Rede de segurança do login da agents (não do gate de conta): `bun set-admin` no container cria um SUPER_ADMIN sem depender do token efêmero, mas não substitui o `/setup`, que também cria o tenant (ver `references/06-setup-and-mcp.md`).
- **Exceção: o Langfuse** é provisionado **headless** (`LANGFUSE_INIT_*`, etapa 5): o agente semeia usuário (OWNER) + org + projeto + keys num deploy só, com signup fechado desde o boot. O usuário **não cria conta** lá, só faz **login** na conta semeada (`/auth/sign-in`) e troca a senha. É o padrão oficial do Langfuse e evita a janela de signup aberto (o Langfuse não tem o gate primeiro-admin-depois-fecha do Coolify/agents). Como o seed é headless (o usuário não vê nada acontecer), faça um **handoff explícito com pausa**: anuncie que o painel está no ar, entregue a URL `/auth/sign-in` + e-mail derivado + senha temporária, e **espere um "consegui entrar"** antes de continuar.

## Estilo

- PT-BR com acentuação correta. Nada de em-dash (use vírgula/ponto/dois-pontos). `fazer.ai` sempre minúsculo (slugs `fazer-ai` ok).
