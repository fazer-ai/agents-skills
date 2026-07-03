# 04: Gerar a própria imagem + deploy

Para rodar a sua versão modificada num servidor, gere a própria imagem e plugue num deploy.

## Build da imagem
```sh
docker build -t <seu-registry>/<seu-nome>:<tag> .
docker push <seu-registry>/<seu-nome>:<tag>
```
O `Dockerfile` do repo já define o boot `bootstrap → migrate deploy → serve` como CMD. **Não** sobrescreva `command:` no compose (sobrescrever crash-loopa).

## Plugar no deploy
Casa com o **Tier C** da `agents-onboarding` (compose genérico): aponte a imagem para a sua, setando a env `AGENTS_IMAGE` (ou edite o compose). As duas roles de DB (superuser para migrate/bootstrap; não-superuser para runtime) e os demais invariantes de deploy estão em `docs/deploy.md`.
