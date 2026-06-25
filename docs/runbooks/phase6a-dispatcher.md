# Runbook Phase 6a — Dispatcher n8n (routeur unique)

Routeur unique pour toutes les entrées (Telegram, prompt/API, futur murmure). Une
seule logique de routage par **commande explicite**, secrets confinés dans des
**credentials n8n chiffrés**.

## Composants

- Workflow `services/n8n/workflows/10-assistant-dispatcher.json` (id `dispatcher000001`).
- Webhook **production** : `POST http://n8n:5678/webhook/assistant-in`.
- Credentials n8n (chiffrés, hors repo) :
  - `LiteLLM master key` (`litellmmasterkey1`) — `Authorization: Bearer <LITELLM_MASTER_KEY>`.
  - `Bridge token` (`bridgetoken00001`) — `Authorization: Bearer <BRIDGE_TOKEN>`.

## Contrat d'entrée / sortie

Entrée (JSON) — tolérante :

```json
{ "source": "telegram|api|…", "return_target": "<id>", "text": "…" }
```

- `text` accepté tel quel ; `chat_id` est mappé en `return_target` et `source=telegram`
  (compat poller Telegram Phase 4).

Sortie (JSON) : `{ "reply": "…" }`.

## Routage (commandes)

| Préfixe                | Route           | Backend                                          |
| ---------------------- | --------------- | ------------------------------------------------ |
| _(défaut)_ / `/chat`   | chat local      | LiteLLM `local-gemma` (max_tokens 2048)          |
| `/claude …`            | Claude forfait  | bridge `claude -p` (`host.docker.internal:8088`) |
| `/code …` / `/build …` | tâche agentique | **placeholder** (worker branché en Phase 6b)     |

## Déploiement / activation

Le fichier repo est `"active": false` (convention : le repo = définition, l'instance = état).
Après import, **activer** dans l'instance qui tourne :

```bash
docker cp services/n8n/workflows/10-assistant-dispatcher.json n8n:/tmp/10.json
docker exec n8n n8n import:workflow --input=/tmp/10.json
docker exec n8n n8n update:workflow --id=dispatcher000001 --active=true
docker restart n8n   # requis : enregistre le webhook de production
```

Recréer les credentials si le volume `n8n-data` est neuf :

```bash
# httpHeaderAuth, valeur "Bearer <clé>" — voir .env (LITELLM_MASTER_KEY, BRIDGE_TOKEN)
docker exec n8n n8n import:credentials --input=/tmp/cred-*.json
```

Le poller Telegram pointe sur le dispatcher (`compose.yaml` →
`telegram-poller.N8N_WEBHOOK_URL=http://n8n:5678/webhook/assistant-in`).

## Validation

```bash
# chat (défaut) → LiteLLM
curl -s -X POST http://localhost:5678/webhook/assistant-in -H 'Content-Type: application/json' \
  -d '{"text":"Dis bonjour en une phrase."}'
# /claude → bridge (forfait)
curl -s -X POST http://localhost:5678/webhook/assistant-in -H 'Content-Type: application/json' \
  -d '{"text":"/claude Réponds en 3 mots"}'
# /code → ack placeholder (Phase 6b)
curl -s -X POST http://localhost:5678/webhook/assistant-in -H 'Content-Type: application/json' \
  -d '{"text":"/code crée un script hello"}'
```

Validé le 2026-06-16 : les 3 routes + le format `{chat_id,text}` renvoient un `reply`.
Test Telegram bout-en-bout : envoyer un message au bot (texte et `/claude …`).

## Dépannage

- `404 webhook not registered` : workflow non actif → `update:workflow --active=true` **puis
  `docker restart n8n`**.
- `reply` vide en chat : `max_tokens` trop bas (gemma = modèle à raisonnement, prévoir ≥ 2048).
- 401/403 sur une route : credential manquant/incorrect dans l'instance n8n.

## Pipeline BMAD via Telegram (Lot C — C1+C2)

Le dispatcher pilote aussi le **pipeline BMAD** (en plus des jobs one-shot). Commandes
(texte ou voix transcrite) :

```
/run <besoin>      → POST :8089/pipelines  (lance le pipeline sur le projet actif)
/approve           → POST :8089/pipelines/resume {decision:"approve"}
/revise <retour>   → … {decision:"revise:<retour>"}
/stop              → … {decision:"stop"}
```

- **À la voix (C5)** : le `telegram-poller` mappe une commande dictée vers sa forme
  `/slash` avant d'envoyer au dispatcher (`_voice_to_command`) — « lance une page… » →
  `/run une page…`, « stop » → `/stop`, « approuve » → `/approve`, « révise … » →
  `/revise …` (aussi « slash/barre <cmd> »). Appliqué **aux messages vocaux uniquement** ;
  un texte tapé n'est jamais réinterprété. Aucun changement n8n.
- Le **projet cible** est `AGENT_DEFAULT_REPO` (réglé par `ai2b switch <projet>`).
- La **corrélation** canal↔pipeline est faite **par le worker** (`/pipelines/resume`
  résout le pipeline en attente du `return_target`) → pas de `pipeline_id` à manipuler
  côté Telegram. Un seul pipeline en attente par canal à la fois.
- **Notifications de jalon (C1)** : le worker POSTe `_pipe_callback` (`kind:"pipeline"`)
  vers `/webhook/job-callback`. Le workflow `11-job-callback` formate :
  `awaiting_approval` → « ⏸ Jalon … → /approve · /revise · /stop » ; `done` → « ✅ … » +
  `diff_stat` ; `error`/`stopped` → message dédié ; `running`/`accepted` ignorés (anti-spam).

**Import** : ré-importer `10-assistant-dispatcher.json` et `11-job-callback.json` dans n8n,
vérifier les credentials (`Agent token`, `Poller notify token`), activer + `docker restart
n8n`. Même backend que `ai2b run/approve/...` (cf. ai2b.md).

## Évolutions (phases suivantes)

- **6b** : route `/code` → worker agentique (`POST /jobs`, async) + webhook `/job-callback`.
- **6c** : entrée murmure (`/voice-in`, forme OpenAI) + notifications de résultat.
- **Lot C (suite)** : entrée web (chat), TTS (réponses vocales).
