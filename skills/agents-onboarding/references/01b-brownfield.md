# 01b: Inventário brownfield (sondar antes de instalar)

A VPS pode chegar vazia (**greenfield**) ou já com Coolify e/ou Chatwoot e/ou Langfuse e/ou a própria agents, em **qualquer combinação** (**brownfield**). Antes de instalar qualquer coisa (etapas 2 a 5), **sonde** o que já existe e decida **por serviço**: reusar, instalar, ou sinalizar incompatibilidade. É isso que torna as etapas de deploy **idempotentes** (só provisionam o que falta) e **não-destrutivas** (nunca apagam o que o usuário já tem).

## 1. Sondagem (read-only, não muta nada)

Rode na VPS via SSH (etapa 0). Tudo aqui é leitura (`docker ps/inspect`, `ss`, `curl`, `df/free`). O probe tem `{{…}}`, `$()`, aspas aninhadas e múltiplas linhas: **não monte isso inline no `ssh <host> '…'`** (no PowerShell as aspas são comidas e a here-string ganha BOM → o bash quebra; ver `gotchas.md`). **Escreva o probe num arquivo `recon.sh`** e rode pelo `scripts/remote.py`, que entrega byte a byte em qualquer SO:

`recon.sh`:
```sh
sec(){ printf '\n### %s\n' "$1"; }
sec OS;        ( . /etc/os-release && echo "$PRETTY_NAME" )
sec RESOURCES; free -h | awk 'NR==2{print "mem "$2"/"$7" avail"}'; df -h / | awk 'NR==2{print "disk "$2"/"$4" free"}'; echo "cpu $(nproc)"
sec DOCKER;    docker --version || echo absent
sec CONTAINERS; docker ps -a --format '{{.Names}}	{{.Image}}	{{.Status}}	[{{.Label "com.docker.compose.project"}}]'
sec PORTS;     ss -tlnp | awk 'NR>1{n=split($4,a,":");print a[n]}' | sort -un | tr '\n' ' '; echo
sec COOLIFY;   curl -s -m5 -o /dev/null -w 'api8000=%{http_code}\n' http://localhost:8000/api/health
sec IMAGES;    docker ps -a --format '{{.Image}}' | sort -u | grep -iE 'coolify|chatwoot|langfuse|agents|pgvector|clickhouse|minio|traefik|caddy|nginx'
```

```sh
python3 scripts/remote.py --ssh root@<VPS_IP> --ssh-opts "-i <chave>" --script-file recon.sh
```

> **Tier B (Portainer):** quando a plataforma é Portainer, a sondagem é **via API do Portainer** (`GET /api/stacks`, `GET /api/endpoints/{id}/docker/containers/json`), não `coolify-db`. A lógica é a mesma (fingerprint por imagem + matriz da seção 3); use `scripts/portainer-brownfield.py` (já detecta quem ocupa 80/443 → se há ingress, o Caddy bundled conflita, reusar ou ir de `templates/docker-compose.prod.yml` BYO-proxy). Ver [`deploy-b-portainer.md`](deploy-b-portainer.md).

## 2. Ler os sinais

**Identifique o serviço pela IMAGEM, não pelo nome do projeto** (é um UUID opaco). Fingerprints:

| Serviço | Imagem (fingerprint) | Saúde = todos healthy | Versão |
|---|---|---|---|
| **Coolify** | `coollabsio/coolify` (+ `coolify-db`/`-redis`/`-realtime`, `-proxy`=`traefik`) | container `coolify` + API `:8000`=200 | tag da imagem (ex. `:4.1.2`) |
| **Chatwoot** | imagem com `chatwoot` (+ `sidekiq`, e `baileys-api` para WhatsApp) | `chatwoot` + `sidekiq` Up | tag (`:latest` → ver via `/version`) |
| **Langfuse** | `langfuse/langfuse` (+ `-worker`, `clickhouse`, **`minio`**) | web+worker+clickhouse+minio Up | tag (ex. `:3`) |
| **fazer.ai agents** | `ghcr.io/fazer-ai/agents` (+ `pgvector`) | container Up + `/api/health` | tag |

As portas das apps **não** ficam expostas no host (atrás do Traefik); só Coolify (`:8000`) e o proxy (`:80`/`:443`) escutam. `curl localhost:80` sem o Host certo dá 404/503 (esperado). Pra health de uma app, use o FQDN dela.

## 3. Matriz de decisão (por serviço)

- **Ausente** (nenhum container com o fingerprint) → **instala** do zero (etapa do serviço).
- **Presente + saudável + compatível** → **reaproveita**: capture endpoint/UUID/FQDN pro state, NÃO recrie (a etapa do serviço vira no-op + captura).
- **Presente + não-saudável** (container existe mas não Up/healthy) → **pare e sinalize**: investigar/consertar antes de prosseguir; nunca instalar por cima.
- **Presente + incompatível** → **pare e sinalize ao usuário** (atualizar / migrar / instalar em paralelo, decisão dele). Ver compatibilidade abaixo.

Greenfield = tudo ausente = instala tudo. O resultado é um inventário por serviço (`ausente | reusar | sinalizar`) que dirige as etapas 2 a 5.

## 4. Compatibilidade (o que torna "presente" em "incompatível")

- **Chatwoot OSS vs Pro:** a imagem revela. `harbor.fazer.ai/chatwoot/fazer-ai/chatwoot-pro` = **Pro** (Kanban + features fazer-ai). `ghcr.io/fazer-ai/chatwoot` (nosso fork OSS), ou o `chatwoot/chatwoot` oficial do Docker Hub num brownfield de terceiro, = **OSS**: o core do agente funciona (Agent Bot é padrão), mas **sem** Kanban/features Pro. Se o usuário quer essas features, sinalize a migração pra Pro.
- **Langfuse v3 vs v2:** o fazer.ai agents fala com a v3 (arquitetura `clickhouse` + **`minio` obrigatório**, ver `references/05-langfuse.md`). Tag `:2`, ou ausência de `clickhouse`/`minio`, → incompatível/parcial: sinalize.
- **Coolify:** validado em `4.x`. Versões muito antigas têm API diferente; confirme `:8000/api/health`=200 e cheque a versão pela tag.
- **Postgres reusado (fora do Coolify, Tier B/C):** o fazer.ai agents exige **pgvector** (extensão `vector`) e um **superuser** pro bootstrap das 2 roles (ver `references/04-agents-image.md`). Um Postgres compartilhado sem pgvector ou sem acesso superuser → sinalize.

## 5. Reaproveitar (capturar pro state, sem recriar)

Pra um serviço que vai reusar, capture o que as etapas seguintes precisam:
- **No Coolify, do container ao FQDN:** cruze o label `com.docker.compose.project` (= `uuid` do serviço) com o `coolify-db` pra pegar o endpoint público (sub-componentes como `sidekiq`/`minio`/`clickhouse` têm `fqdn` vazio):

  ```sh
  docker exec -i coolify-db psql -U coolify -d coolify -c \
    "SELECT s.uuid, s.name, sa.fqdn FROM services s
     JOIN service_applications sa ON sa.service_id=s.id
     WHERE sa.fqdn IS NOT NULL AND sa.fqdn<>'' ORDER BY s.id;"
  ```

  Ou via API: `GET /api/v1/services` (etapa 2). Preserve a porta do FQDN quando houver (ex. Langfuse `:3000`).
- **Endpoints/creds:** FQDN público + credenciais já existentes (admin token do Chatwoot via Rails runner; chaves do Langfuse) buscadas **transitoriamente** (ver `guardrails.md`), nunca persistidas.
- **Nunca** recrie um serviço saudável só pra "padronizar": isso destrói dados do usuário. Em brownfield, reusar > reinstalar.
