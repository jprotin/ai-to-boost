# Référence des variables d'environnement

Valeurs par défaut = celles du **code** (`os.environ.get(...)`). Le `.env` racine (copié
depuis `.env.example`, **gitignoré**) surcharge. Les secrets de la webui vivent à part dans
`services/webui/webui.env`.

## LiteLLM / modèles locaux

| Variable                             | Défaut                                                           | Rôle                                            |
| ------------------------------------ | ---------------------------------------------------------------- | ----------------------------------------------- |
| `LITELLM_MASTER_KEY`                 | `sk-local-change-me`                                             | Clé maître LiteLLM (= `LITELLM_KEY` côté webui) |
| `OLLAMA_BASE_URL`                    | `http://ollama:11434/v1`                                         | Endpoint Ollama vu des conteneurs               |
| `POSTGRES_PASSWORD` / `DATABASE_URL` | `change-me`                                                      | Postgres LiteLLM (`litellm-db`)                 |
| `LITELLM_URL`                        | `http://127.0.0.1:4000` (worker) / `http://litellm:4000` (webui) | Gateway LiteLLM                                 |

## Bridge Claude (`claude -p`, forfait)

| Variable                | Défaut | Rôle                              |
| ----------------------- | ------ | --------------------------------- |
| `BRIDGE_TOKEN`          | `""`   | Token Bearer (bridge ↔ n8n/webui) |
| `CLAUDE_BRIDGE_PORT`    | `8088` | Port du bridge                    |
| `CLAUDE_BRIDGE_MODEL`   | `opus` | Modèle par défaut du chat Claude  |
| `CLAUDE_BRIDGE_TIMEOUT` | `300`  | Timeout (s) par appel             |

## Worker agentique (pipeline BMAD)

| Variable                    | Défaut                                  | Rôle                                                |
| --------------------------- | --------------------------------------- | --------------------------------------------------- |
| `AGENT_TOKEN`               | `""`                                    | Token Bearer du worker                              |
| `AGENT_HOST` / `AGENT_PORT` | `0.0.0.0` / `8089`                      | Bind du worker                                      |
| `AGENT_MODEL`               | `opus`                                  | Modèle Claude (architecte + escalade dev/doc)       |
| `AGENT_TIMEOUT`             | `1200`                                  | Timeout (s) par appel `claude -p`                   |
| `AGENT_MAXTURNS`            | `30`                                    | Max-turns par défaut (jobs one-shot)                |
| `AGENT_DEFAULT_REPO`        | `""`                                    | Repo cible si non précisé (réglé par `ai2b switch`) |
| `AGENT_CALLBACK_URL`        | `""`                                    | Callback n8n de fin de job                          |
| `AGENT_REQUIRE_MARKER`      | `true`                                  | Exige le marqueur `.ai-to-boost/` sur la cible      |
| `AGENT_FORBID`              | (repo ai-to-boost)                      | Repo(s) interdit(s) comme cible (séparés par `:`)   |
| `AGENT_WORKROOT`            | `~/.local/share/claude-agent/worktrees` | Racine des worktrees                                |
| `AGENT_BMAD_DIR`            | —                                       | BMAD commun injecté (symlink) dans chaque worktree  |

## Pipeline BMAD — curseurs perf/qualité

| Variable                  | Défaut        | Rôle                                                |
| ------------------------- | ------------- | --------------------------------------------------- |
| `PIPELINE_PLANNING_MODEL` | `local-gemma` | Modèle des phases de planning (local)               |
| `PIPELINE_DEV_MODEL`      | `sonnet`      | Curseur dev/doc (rapide) ; escalade → `AGENT_MODEL` |
| `PIPELINE_DEV_EFFORT`     | `medium`      | Effort du dev (limite le sur-raisonnement Sonnet 5) |
| `PIPELINE_STORY_MAXTURNS` | `40`          | Max-turns par story (trop bas → travail tronqué)    |
| `PIPELINE_VERIFY`         | `true`        | Gate de vérification (juge par story + acceptation) |
| `PIPELINE_JUDGE_MODEL`    | `haiku`       | Juge par story (verdict PASS/FAIL, rapide)          |
| `PIPELINE_ACCEPT_MODEL`   | `sonnet`      | Juge d'acceptation finale (qualité)                 |
| `PIPELINE_DOC_PHASE`      | `true`        | Phase doc finale (`false` = itération plus rapide)  |

## Telegram / poller

| Variable                        | Défaut                                                  | Rôle                               |
| ------------------------------- | ------------------------------------------------------- | ---------------------------------- |
| `TELEGRAM_BOT_TOKEN`            | `""`                                                    | Token du bot                       |
| `TELEGRAM_ALLOWED_CHAT_IDS`     | `""`                                                    | Allowlist des `chat_id` (sécurité) |
| `NOTIFY_PORT` / `NOTIFY_TOKEN`  | `8090` / `""`                                           | Endpoint `/notify` (n8n → poller)  |
| `WHISPER_URL` / `WHISPER_MODEL` | `http://whisper:8000` / `Systran/faster-whisper-medium` | STT                                |
| `POLL_TIMEOUT`                  | `30`                                                    | Long-poll Telegram (s)             |

## Qdrant / RAG

| Variable          | Défaut                                                        | Rôle                                                                        |
| ----------------- | ------------------------------------------------------------- | --------------------------------------------------------------------------- |
| `QDRANT_URL`      | `http://127.0.0.1:6333` (worker) / `http://qdrant:6333` (rag) | Base vectorielle                                                            |
| `RAG_COLLECTION`  | `knowledge`                                                   | Collection commune                                                          |
| `EMBEDDING_MODEL` | `nomic-ai/nomic-embed-text-v1.5`                              | Embeddings (FastEmbed) — **doit** être identique entre ingestion et requête |
| `RAG_PORT`        | `8100`                                                        | Port du service `rag`                                                       |

## n8n

| Variable             | Rôle                                                                     |
| -------------------- | ------------------------------------------------------------------------ |
| `N8N_ENCRYPTION_KEY` | Chiffre les credentials n8n — **ne pas perdre/changer** après le 1er run |
| `N8N_DB_PASSWORD`    | Mot de passe du rôle Postgres `n8n` (réutilise `litellm-db`)             |

## Webui (`services/webui/webui.env`)

| Variable                                                                | Rôle                                               |
| ----------------------------------------------------------------------- | -------------------------------------------------- |
| `WEBUI_USER` / `WEBUI_PASSWORD_HASH`                                    | Auth (identifiant + hash **bcrypt**)               |
| `WORKER_URL` / `BRIDGE_URL` / `LITELLM_URL` / `RAG_URL` / `WHISPER_URL` | Cibles backend (BFF)                               |
| `AGENT_TOKEN` / `BRIDGE_TOKEN` / `LITELLM_KEY`                          | Tokens (server-only, jamais exposés au navigateur) |
| `WEBUI_DB_PATH`                                                         | Chemin SQLite des conversations                    |

> ⚠️ **Ne jamais exporter `ANTHROPIC_API_KEY`/`ANTHROPIC_AUTH_TOKEN`** dans le shell : le
> forfait Claude serait remplacé par l'API facturée (cf. ADR 0002).
