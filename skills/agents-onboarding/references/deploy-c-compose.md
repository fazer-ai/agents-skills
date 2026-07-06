# Deploy Tier C: Compose genérico (VM crua ou painel sem trilha dedicada)

O caminho catch-all: tudo que não é Coolify (Tier A) nem Portainer (Tier B). Cobre dois casos com a mesma
base de artefatos:

- **VM crua**, só Docker + `docker compose`: você sobe cada stack à mão e cuida do TLS.
- **Painel sem trilha dedicada** (Easypanel, Dokploy, CapRover, etc.): **não há doc específico na skill, por
  escolha.** Pegue os passos genéricos abaixo e adapte ao painel com o que você já sabe dele (como ele cria
  um projeto Compose, injeta env, e anexa domínio + emite TLS). O alvo é sempre o
  [contrato (1c)](01c-pick-tier.md); o painel é só o meio.

## Tem um painel? Adapte, não procure trilha

O padrão de qualquer painel PaaS (Easypanel/Dokploy/CapRover/…) é o mesmo:

- O **proxy do painel** (Traefik/nginx embutido) detém 80/443 e emite Let's Encrypt ao **anexar um domínio**
  a um serviço. Logo, use o `templates/docker-compose.prod.yml` (BYO-proxy, **sem** o Caddy bundled) e deixe o painel
  rotear + certificar. Um Caddy nosso brigaria pelas portas.
- O env vem do **`.env` que você controla** (não há magic vars do Coolify): gere com o
  `scripts/gen-onboarding-env.ts` e cole as vars no serviço pelo painel.
- Cada stack (fazer.ai agents, Chatwoot, Langfuse) vira um projeto Compose; anexe `agents.`/`chatwoot.`/`langfuse.` a
  cada um. Detalhes de UI/API variam por produto e versão: resolva com seu conhecimento do painel da run.

Daqui em diante os passos são os mesmos da VM crua; só muda o "como" você aplica o compose + env.

## TLS na VM crua: duas opções

- **Caddy bundled** (recomendado se a VM tem 80/443 **livres**): use o `templates/docker-compose.portainer.yml` pra
  agents. Ele já traz um Caddy que emite Let's Encrypt automático a partir de `CADDY_DOMAIN`/`ACME_EMAIL`
  (gerados no `.env`).
- **BYO-proxy** (se já há nginx/Caddy/Traefik na 443, ou é um painel): use o `templates/docker-compose.prod.yml` (sem
  Caddy) e aponte o proxy pra porta publicada do app. O inventário ([1b](01b-brownfield.md)) diz quem ocupa
  80/443.

## Passos

1. **DNS primeiro** (A-records resolvendo antes do ACME; ver [1c](01c-pick-tier.md)).
2. **Env:** `bun scripts/gen-onboarding-env.ts --public-url https://agents.<domínio> --acme-email
   voce@<domínio>` gera o `.env` (duas roles, secrets, URLs, `CADDY_DOMAIN`). Chatwoot/Langfuse têm env
   próprio (ver [`03-chatwoot-pro.md`](03-chatwoot-pro.md) e [`05-langfuse.md`](05-langfuse.md)).
3. **Suba cada stack** (a partir da raiz desta skill, com o `.env` ao lado; num painel, o equivalente é
   criar cada projeto Compose):
   ```sh
   docker compose -f templates/docker-compose.portainer.yml up -d       # agents + postgres + Caddy (ou .prod.yml + proxy)
   docker compose -f templates/chatwoot/docker-compose.yml up -d  # Pro vs OSS pelo env (03-chatwoot-pro.md)
   docker compose -f templates/langfuse/docker-compose.yml up -d  # com MinIO (obrigatório)
   ```
4. **Boot do fazer.ai agents:** o CMD da imagem faz `bootstrap → migrate → serve`; **não** sobrescreva `command:`.
5. **O `/setup` da agents não pede token** (o compose do onboarding sobe com `SETUP_TOKEN_REQUIRED=false`):
   entregue `https://agents.<domínio>/setup` ao usuário, sem garimpar token de log. Rede de segurança:
   `docker compose exec agents bun set-admin <email> <senha>` cria um SUPER_ADMIN direto (ver
   [`06-setup-and-mcp.md`](06-setup-and-mcp.md)). O **admin token do Chatwoot** sai do Rails runner, igual aos
   outros tiers.
6. **Verifique** (200 + cert Let's Encrypt) e **siga pra etapa 6**.

## Brownfield

Se a VM/painel já roda algum serviço, sonde com a etapa [1b](01b-brownfield.md) (a sondagem via
`docker ps`/`ss` cobre o caso sem painel; num painel, use a API/UI dele pra inventariar) e **reuse** o que
estiver saudável.

## O que entrega ao contrato

Os 5 outputs do [1c](01c-pick-tier.md). **Lacuna conhecida:** quando você usa o Caddy bundled só pra agents, o
fronting TLS de `chatwoot.`/`langfuse.` precisa de um site Caddy/proxy adicional apontando pra porta
publicada de cada um (a seção "Chatwoot + Langfuse" de [`deploy-b-portainer.md`](deploy-b-portainer.md)
descreve esse mesmo padrão).
