# Gotchas: modo desenvolvedor

- **`prisma migrate reset` cru apaga os grants do role runtime** → todo query falha com Postgres `42501` (`permission denied for schema public`) no próximo boot. Use `bun db:reset` (ou re-rode `bun db:bootstrap` após qualquer reset, inclusive um `migrate dev` que reseta por drift).
- **`psql` cru com a `DATABASE_URL` não enxerga linhas tenant-scoped:** a `DATABASE_URL` é o role runtime não-superuser com RLS; sem contexto de tenant, tabelas como `agents` voltam zero linhas (silencioso, parece "não existe"). Para diagnosticar, conecte como superuser (`MIGRATION_DATABASE_URL`, read-only) ou rode `SET app.tenant_id = '<id>'` na sessão antes do `SELECT`.
- **Porta do Postgres:** se 5432 já estiver em uso, escolha a próxima livre e setar `POSTGRES_PORT` no `.env`.
- **Editar script inline no `index.html`** exige `bun run build` antes de servir em produção: o hash no header de CSP precisa bater com o HTML servido, senão o browser bloqueia o script.
