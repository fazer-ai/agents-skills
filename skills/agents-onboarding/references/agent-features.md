# Pós-import: resolver avisos + ligar features do agente

Depois do import (`08`), o agente entra **disabled + test**. Antes de validar (`10`), **resolva todos os
avisos de configuração** (não bloqueiam o boot, mas degradam a qualidade) e ligue as features opcionais que
o agente usa. Trate a seção 1 como **gate**, não como "nice to have".

## 1. Avisos pós-import (gate, obrigatório)

O editor do agente lista "Avisos de configuração". Resolva **cada um** (ou desligue a feature
conscientemente):

- **KB sem indexar.** Os docs do import entram UNINDEXED e só indexam com o embedding por-tenant ligado
  + o OpenAI preenchido (sem isso ficam UNINDEXED, não FAILED). Sequência (detalhe em
  [`08-agent-import.md`](08-agent-import.md) §4-5): setar embedding por-tenant → `knowledge_reindex` da
  base (devolve `blocked` + `fillAt` se falta preencher a credencial; `include_failed:true` recupera
  FAILED reais), até **todos READY**.
  Depois **verifique grounding**: pergunte no playground algo que só a KB sabe e confirme que a resposta usa
  o conteúdo indexado. KB não-READY = sem grounding = critério de aceite (`10`) não batido.
- **STT/TTS/visão ligados sem chave.** Conecte a credencial (deeplink) **ou** desligue a feature. Não deixe
  o aviso aberto.

## 2. Voz (STT/TTS): opcional, por-agente

MCP `agent_settings_set` (dry-run por padrão; `credentialRef` aceita o **nome** da entrada do vault):

```jsonc
agent_settings_set {
  "agent_id": "<id>",
  "stt": { "enabled": true, "provider": "openai", "model": "whisper-1", "language": "pt", "credentialRef": "<nome no vault>" },
  "tts": { "mode": "mirror", "provider": "openai", "model": "tts-1", "voice": "alloy", "credentialRef": "<nome no vault>" }
}   // dry_run:false pra aplicar
```

- Campos (fonte `src/modules/stt/settings.ts`, `src/modules/tts/settings.ts`): STT
  `enabled/provider/model/language/credentialRef/baseURL`; TTS
  `mode (never|mirror|preference)/provider/model/voice/credentialRef/normalize`. ElevenLabs exige `voice`.
- **`agent_settings_set` é tool separada do `agent_update`** (este é nome/enabled/mode/modelConfig). Os
  blocos de comportamento (stt/tts/split/handoff/etc.) vão pelo `agent_settings_set`.
- REST equivalente: `PATCH /api/v1/agents/:id { settings: { stt, tts } }` (aqui o `credentialRef` tem que
  ser `vault:<id>`; REST não resolve por nome).
- A chave (OpenAI/ElevenLabs) é credencial do vault, preenchida por deeplink como qualquer outra (`08` §2).

### Links de afiliado da fazer.ai (ElevenLabs + Asaas)

Quando o usuário **não tem conta** no ElevenLabs (voz) ou no Asaas (cobrança PIX), ofereça o **link de
afiliado da fazer.ai** pra ele criar a conta. O mesmo link aparece na UI (no formulário de credencial, como
"Não tem conta ainda? Crie pela fazer.ai"), então é o caminho consistente:

- **ElevenLabs:** `https://try.elevenlabs.io/fazer-ai-agents-cli`
- **Asaas:** `https://www.asaas.com/r/5ec90fd5-677d-40c7-b577-cc1f6de62fec`

Ofereça só quando fizer sentido (o usuário vai usar voz/cobrança e não tem conta): é conveniência, não
empurre. A chave em si continua entrando pelo deeplink do vault; o segredo **nunca** passa pelo agente.

## 3. Google (Calendar/Drive): opcional, **fora do MCP por design**

As tools de Google usam uma credencial kind `google_oauth`. **Não há MCP write tool pra conectar o Google**
(o segredo e o consent nunca cruzam o MCP). É um fluxo de **console** (o usuário faz):

1. Pré: no Google Cloud, um OAuth 2.0 Client ID (Web) com a redirect URI
   **`${PUBLIC_URL}/api/v1/oauth/google/callback`** registrada.
2. No console `/resources/vault`: criar credencial kind `google_oauth` com Client ID + Client Secret.
3. Na `GoogleOAuthSection`: escolher os scopes (Calendar/Drive/...) → "Sign in with Google" → popup de
   consent → o callback grava os tokens (criptografados) na entrada do vault.
4. Status: "Connected as <email>". A partir daí, as tools de Calendar/Drive resolvem por `vault:<id>` (token
   renovado automaticamente).

Endpoints (fonte `src/api/v1/oauth-google.controller.ts`): `POST /api/v1/vault/:id/oauth/google/authorize {scopes}`,
`GET /api/v1/oauth/google/callback`, `GET .../status`, `POST .../disconnect`. Não confundir com o login
social do `docs/google-oauth.md` (é outra coisa).

> Princípio: tudo o mais é MCP-first, mas **o connect do Google é console-only por design**. Entregue o
> link/instrução ao usuário; o agente não vê o segredo.
