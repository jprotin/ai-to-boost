# Architecture d'ensemble

Vue globale d'ai-to-boost : services, ports, flux, état et sécurité. Voir aussi
`docs/adr/` (décisions), `docs/runbooks/` (par service) et le schéma
`docs/assets/architecture-assistant-ia-local.svg`.

> **Principe** : assistant **local-first** mono-utilisateur qui **pilote des projets
> externes** via un pipeline BMAD multi-LLM. Tout est bindé sur `127.0.0.1`.

## Services

### Dockerisés (réseau `ai-assistant-net`, `docker compose`)

| Service           | Port (127.0.0.1) | Rôle                                                                      |
| ----------------- | ---------------- | ------------------------------------------------------------------------- |
| `ollama`          | 11434            | Modèles locaux GPU (gemma4:e4b, qwen3.5:9b, nomic-embed) — ADR 0007       |
| `ollama-init`     | —                | Pull idempotent des modèles au démarrage                                  |
| `litellm`         | 4000             | Gateway OpenAI-compatible vers Ollama (**modèles locaux only**, ADR 0002) |
| `litellm-db`      | —                | Postgres (clés/budgets LiteLLM **+** base n8n)                            |
| `whisper`         | 8000             | STT (speaches / faster-whisper, GPU)                                      |
| `n8n`             | 5678             | Orchestrateur : dispatcher `assistant-in`, callbacks                      |
| `telegram-poller` | 8090 (`/notify`) | Long-poll Telegram (texte+voix), relaie à n8n                             |
| `qdrant`          | 6333 / 6334      | Base vectorielle (RAG)                                                    |
| `rag`             | 8100             | Requête RAG (FastEmbed nomic) pour le chat projet de la webui             |
| `webui`           | 3001             | Web-app tour de contrôle (Next.js) — ADR 0005                             |

### Sur l'hôte (systemd **user**, hors Docker — forfait Claude)

| Service                 | Port | Rôle                                                                                 |
| ----------------------- | ---- | ------------------------------------------------------------------------------------ |
| `claude-bridge`         | 8088 | Chat Claude via `claude -p` (forfait) — ADR 0002                                     |
| `claude-agent` (worker) | 8089 | Moteur de pipeline BMAD : `claude -p` **+ outils**, isolé en git worktree — ADR 0004 |

> Le worker et le bridge tournent **hors conteneur** car ils appellent le binaire
> `claude` connecté au **forfait** (jamais l'API facturée). Gérés par `ai2b` /
> `systemctl --user`.

## Flux principaux

**Chat (webui)** — navigateur → `webui` (BFF, `app/api/**`) → `bridge` (Claude forfait)
ou `litellm`→`ollama` (local) ; le chat projet enrichit le contexte via `rag`.

**Chat (Telegram)** — `telegram-poller` → `whisper` (si voix) → `n8n` dispatcher →
`bridge`/`litellm` ou `worker` (commandes pipeline `/run /approve /collect /board`).

**Pipeline BMAD** — webui / Telegram / CLI `ai2b run` → `worker /run` → phases
séquentielles : **analyst, pm, epics** (planning, local via `litellm`→`ollama`) ·
**architect, dev-story, doc** (Claude via `claude -p`, forfait) · jalons humains ·
`collect` (merge de la branche `pipeline/<id>` dans la base du projet).

**RAG double-portée** — commun (`knowledge`) + projet (`proj-<slug>`). Le worker y accède
via MCP `qdrant-find` (pendant le dev) ; la webui via le service `rag` (chat projet).

## État & persistance

- **Worker** : worktrees `~/.local/share/claude-agent/worktrees`, registre projets
  `~/.config/ai-to-boost/projects.json`, `pipeline.json` par repo (persistance/reprise,
  ADR 0008). `PIPELINES` / `LIVE` en mémoire (réhydratés au démarrage).
- **Webui** : conversations en SQLite (volume `webui-data`).
- **LiteLLM / n8n** : Postgres (`litellm-db`). **Qdrant** : volume `qdrant-data`.

## Sécurité

- **CGU forfait** : le worker/bridge **retirent** `ANTHROPIC_API_KEY`/`ANTHROPIC_AUTH_TOKEN`
  de l'env pour forcer le forfait (ADR 0002). Usage **perso, mono-utilisateur**.
- **Garde-fou worker** : hook `PreToolUse` (`guard_hook.py`) — denylist Bash + confinement
  des écritures au worktree. Actif même en `bypassPermissions`.
- **Accès distant** : allowlist des `chat_id` Telegram ; tokens Bearer (`AGENT_TOKEN`,
  `BRIDGE_TOKEN`, `NOTIFY_TOKEN`). Tout exposé en **`127.0.0.1` uniquement**.

## Voir aussi

- Variables d'environnement : `docs/environment-variables.md`
- Dépannage : `docs/troubleshooting.md`
- Déploiement / parcours : `docs/guide-deploiement.md`
- Audits (doc, portabilité, SaaS) : `docs/audits/`
