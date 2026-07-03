# 02: Aditividade + invariantes

## Aditividade
Ao mexer no código, mantenha as mudanças **aditivas**: schema sempre com `tenant_id`; env vars, endpoints e UI adicionam, nunca removem o que já existe. As convenções de código e de contribuição do projeto estão nas instruções do projeto na raiz.

## Invariantes (leia a doc certa ANTES de mexer no subsistema)
Os pontos fixos do projeto (multi-tenancy/RLS, "um core três transportes", roteamento BrowserRouter, CSP, encryption, i18n, UX/skeletons) estão nas instruções do projeto na raiz e detalhados por subsistema em `docs/` (cada doc cobre um subsistema: tenancy, graph, chatwoot, mcp, logs, etc.). Aponte e leia a doc do subsistema **antes** de editá-lo.
