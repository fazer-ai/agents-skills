# Guardrails: modo desenvolvedor

- **Pro privado:** nunca publicar o repo (`fazer-ai/agents-pro`), a imagem, ou trechos exclusivos do Full em local público.
- **Segredos fora do repo:** nunca commitar `.env`, chaves ou tokens; confira `.env.example` ao adicionar env var. Nunca logar tokens/credenciais.
- **Qualidade:** `bun check` verde antes de concluir. Nunca `prisma migrate reset` cru; use `bun db:reset`.
- **Estilo:** PT-BR com acentuação; sem em-dash; `fazer.ai` minúsculo; comentários só com tag.
