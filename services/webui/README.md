# webui — Web-app tour de contrôle

Front-end Next.js (App Router) + shadcn/ui de l'assistant ai-to-boost. Point de contrôle
unique : chat multi-LLM, gestion des projets, pilotage des pipelines BMAD, historique.
Voir **ADR 0005** (`docs/adr/0005-webapp-tour-de-controle-nextjs.md`) et le runbook
`docs/runbooks/webui.md`.

> ⚠️ Cette version de Next.js peut différer de ce que tu connais — lire `AGENTS.md`
> (et les guides `node_modules/next/dist/docs/`) avant de coder.

## Rôle

- **Chat** : Claude (forfait, via le bridge) ou modèles locaux (via LiteLLM/Ollama).
- **Projets** : CRUD, board epics/stories, lancement de pipeline, jalons (approuver /
  réviser / stopper), collect, artefacts, archives, dashboard tokens + durées, live.
- **BFF (Backend-for-Frontend)** : toute la logique serveur (routes `app/api/**`) parle
  au worker (pipelines/projets), au bridge (`claude -p`) et à LiteLLM. Le token
  `AGENT_TOKEN` et les secrets **ne sont jamais exposés au navigateur** (ADR 0005).

## Architecture (résumé)

```
Navigateur ──> app/(dash)/*          (pages, Server Components)
           ──> app/api/**            (BFF, runtime nodejs)
                 ├─ worker  :8089    projets, /run, /resume, /collect, /board, /live
                 ├─ bridge  :8088    chat Claude (claude -p, forfait)
                 ├─ litellm :4000    chat local (gemma/qwen via Ollama)
                 └─ rag     :8100    contexte RAG du chat projet
Auth : NextAuth (Credentials, mono-utilisateur). Conversations : SQLite (webui-data).
```

Cibles backend et secrets : `lib/backend.ts` (server-only). Auth : `auth.ts`
(`WEBUI_USER` / `WEBUI_PASSWORD_HASH` bcrypt, dans `webui.env`).

## Développement

```bash
# via la stack (recommandé) — build + run dockerisé
docker compose up -d --build webui        # expose http://127.0.0.1:3001

# local (hors Docker)
npm install
npm run dev                                # http://localhost:3000
```

Variables : `WORKER_URL`, `BRIDGE_URL`, `LITELLM_URL`, `RAG_URL`, `WHISPER_URL`,
`AGENT_TOKEN`, `BRIDGE_TOKEN`, `LITELLM_KEY`, `WEBUI_USER`, `WEBUI_PASSWORD_HASH`,
`WEBUI_DB_PATH` (cf. `compose.yaml` service `webui` + `webui.env`).
