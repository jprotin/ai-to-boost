# Runbook — Phase 1 : couche modèles locaux (LiteLLM gateway)

Gateway OpenAI-compatible routant vers les **modèles locaux** (Ollama).
Voir [ADR 0001](../adr/0001-architecture-assistant-ia-local-orchestre.md) (socle),
[ADR 0002](../adr/0002-litellm-modeles-locaux-uniquement.md) (LiteLLM = local only)
et [ADR 0007](../adr/0007-ollama-dockerise-remplace-lmstudio.md) (Ollama remplace LM Studio).

## Périmètre

- **Ollama** (service compose `ollama`, GPU, sur `:11434`) :
  - `local-gemma` — `gemma3n:e4b` (défaut planning, ~8,3 Go)
  - `local-qwen` — `qwen3:8b` (~6 Go, full-GPU ; qwen 27B écarté car > 12 Go)
  - `local-embed` — `nomic-embed-text` (768 dims, Phase 5 RAG)
- **Claude n'est PAS routé par LiteLLM** (cf. ADR 0002) :
  - à la main (BMAD) → Claude Code (forfait Max)
  - automatisé (n8n) → `claude -p` headless / Agent SDK (forfait)

Config : [`services/litellm/config.yaml`](../../services/litellm/config.yaml).

## Prérequis

- `.env` complété (copie de `.env.example`) :
  - `LITELLM_MASTER_KEY` — clé d'accès à la gateway (à changer)
  - `OLLAMA_BASE_URL` — `http://ollama:11434/v1` (service compose, réseau interne)
  - `POSTGRES_PASSWORD` — mot de passe de la base LiteLLM (à changer)
  - `DATABASE_URL` — `postgresql://litellm:<POSTGRES_PASSWORD>@litellm-db:5432/litellm`
    (reprendre le **même** mot de passe que `POSTGRES_PASSWORD`)
- GPU NVIDIA accessible à Docker (`nvidia-container-toolkit` + runtime `nvidia`).
  Le service `ollama` réclame le GPU via `deploy.resources` ; vérifier la détection :

```bash
docker compose up -d ollama
docker logs ollama 2>&1 | grep -i "inference compute"   # doit montrer library=CUDA (pas CPU)
```

- Modèles : le service one-shot `ollama-init` les `pull` automatiquement au premier
  `up` (gemma3n:e4b, qwen3:8b, nomic-embed-text), puis sort. `litellm` attend sa
  complétion (`service_completed_successfully`). Pull manuel si besoin :

```bash
docker exec ollama ollama pull gemma3n:e4b
docker exec ollama ollama list      # modèles présents
docker exec ollama ollama ps        # modèles chauds en VRAM + % GPU
```

## Base de données (clés virtuelles, budgets, logs)

LiteLLM stocke clés virtuelles, budgets et logs dans Postgres (service `litellm-db`,
volume `litellm-db`). Sans DB, l'UI affiche « not connected to the database » et la
gestion de clés est désactivée — le routage fonctionne quand même.

Au premier démarrage, LiteLLM applique automatiquement ses migrations Prisma et crée
les tables. Inspection :

```bash
docker exec litellm-db psql -U litellm -d litellm -c "\dt"
```

## Démarrage

```bash
docker compose up -d                 # démarre litellm-db (healthy) puis litellm
docker compose logs -f litellm       # vérifier migrations + port 4000
```

## Interface admin

- URL : `http://127.0.0.1:4000/ui`
- Login : utilisateur `admin`, mot de passe = `LITELLM_MASTER_KEY`
- Permet de créer des **clés virtuelles** dédiées (ex. une par service : n8n…),
  avec budget/limites, plutôt que de partager la master key.

## Validation (critère de passage Phase 2)

Endpoint : `http://127.0.0.1:4000`. Remplacer `$LITELLM_MASTER_KEY`.

```bash
# Liste des modèles exposés (uniquement local-*)
curl -s http://127.0.0.1:4000/v1/models \
  -H "Authorization: Bearer $LITELLM_MASTER_KEY"

# Route Ollama local
curl -s http://127.0.0.1:4000/v1/chat/completions \
  -H "Authorization: Bearer $LITELLM_MASTER_KEY" \
  -H "Content-Type: application/json" \
  -d '{"model":"local-gemma","messages":[{"role":"user","content":"dis bonjour en un mot"}]}'
```

La route locale doit renvoyer une complétion, et `/v1/models` ne doit lister que
des modèles `local-*` → Phase 1 validée.

## Dépannage

- **502/connexion refusée sur `local-*`** : service `ollama` arrêté/non healthy
  (`docker compose ps ollama`), ou modèle absent (`docker exec ollama ollama list`).
- **Modèle sur CPU (lent)** : GPU non vu par Ollama — vérifier `nvidia-container-toolkit`
  et `docker logs ollama | grep "inference compute"` (doit être `library=CUDA`).
- **401 gateway** : mauvais `LITELLM_MASTER_KEY` dans l'en-tête `Authorization`.
- **VRAM (12 Go)** : gemma + embed tiennent ensemble ; qwen3:8b seul. `OLLAMA_KEEP_ALIVE`
  (compose) décharge les modèles inactifs ; `docker exec ollama ollama ps` pour l'état.
