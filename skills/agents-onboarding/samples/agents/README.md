# Sample agents

Exemplos de agentes no schema de export **`fazer-ai.agent` v1** (o mesmo formato que `POST /v1/agents/import`
/ a write tool `agent_import` do MCP consomem). Servem para testar o import, o onboarding e a documentação.

| Arquivo | Persona |
| --- | --- |
| `maria-clinica-moreira.json` | "Maria", recepção de uma clínica fictícia (Clínica Moreira): agendamento, FAQ, voz, KB. |

## Credenciais são por NOME, não por valor

O export **não carrega segredos**: cada credencial é referenciada por **nome** (`credentialRef`). Ao importar
num tenant novo, os refs não resolvem automaticamente: crie entradas no vault com os mesmos nomes (ou
re-aponte via `PATCH /v1/agents/:id`). Os nomes neste sample são genéricos de propósito:

- `OpenAI`: modelo (`gpt-5.4-mini`) + STT.
- `ElevenLabs`: TTS.
- `Google Gemini`: visão.
- `Google OAuth2`: integrações Google Calendar + Drive.
- `Asaas`: integração de cobrança.

IDs específicos de ambiente foram neutralizados (ex.: o Google Calendar usa `primary`). Não há chaves,
tokens ou IDs reais no arquivo: pode versionar e publicar à vontade.
