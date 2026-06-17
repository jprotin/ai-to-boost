# Runbook — Phase 1 : couche modèles locaux (LiteLLM gateway)

Gateway OpenAI-compatible routant vers les **modèles locaux** (LM Studio).
Voir [ADR 0001](../adr/0001-architecture-assistant-ia-local-orchestre.md) (socle)
et [ADR 0002](../adr/0002-litellm-modeles-locaux-uniquement.md) (LiteLLM = local only).

## Périmètre

- **LM Studio local** (serveur natif sur `:1234`) :
  - `local-gemma` — `google/gemma-4-e4b`
  - `local-qwen` — `qwen/qwen3.6-27b` (load à la demande, contrainte 12 Go VRAM)
  - `local-embed` — `text-embedding-nomic-embed-text-v1.5` (embeddings, Phase 5 RAG)
- **Claude n'est PAS routé par LiteLLM** (cf. ADR 0002) :
  - à la main (BMAD) → Claude Code (forfait Max)
  - automatisé (n8n) → `claude -p` headless / Agent SDK (forfait)

Config : [`services/litellm/config.yaml`](../../services/litellm/config.yaml).

## Prérequis

- `.env` complété (copie de `.env.example`) :
  - `LITELLM_MASTER_KEY` — clé d'accès à la gateway (à changer)
  - `LMSTUDIO_BASE_URL` — `http://host.docker.internal:1234/v1`
  - `POSTGRES_PASSWORD` — mot de passe de la base LiteLLM (à changer)
  - `DATABASE_URL` — `postgresql://litellm:<POSTGRES_PASSWORD>@litellm-db:5432/litellm`
    (reprendre le **même** mot de passe que `POSTGRES_PASSWORD`)
- Serveur LM Studio démarré **en bind réseau** (sinon les conteneurs ne peuvent
  pas l'atteindre via `host.docker.internal` — LM Studio écoute sur `127.0.0.1`
  par défaut) avec un modèle chargé :

```bash
lms server start --bind 0.0.0.0 --port 1234   # accepte les connexions réseau local
lms load google/gemma-4-e4b                   # ou un modèle déjà présent (lms ls)
lms ps                                         # vérifier l'état
ss -ltn | grep 1234                            # doit montrer 0.0.0.0:1234, pas 127.0.0.1
```

> Sécurité : `--bind 0.0.0.0` expose le serveur au réseau local. Acceptable en
> poste de travail isolé ; à durcir (firewall) si le réseau n'est pas de confiance.

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

# Route LM Studio local
curl -s http://127.0.0.1:4000/v1/chat/completions \
  -H "Authorization: Bearer $LITELLM_MASTER_KEY" \
  -H "Content-Type: application/json" \
  -d '{"model":"local-gemma","messages":[{"role":"user","content":"dis bonjour en un mot"}]}'
```

La route locale doit renvoyer une complétion, et `/v1/models` ne doit lister que
des modèles `local-*` → Phase 1 validée.

## Dépannage

- **502/connexion refusée sur `local-*`** : serveur LM Studio arrêté, modèle non
  chargé (`lms ps`), ou `host.docker.internal` injoignable (vérifier `extra_hosts`
  et le bind `0.0.0.0`).
- **401 gateway** : mauvais `LITELLM_MASTER_KEY` dans l'en-tête `Authorization`.
- **VRAM** : un seul gros modèle local à la fois (contrainte 12 Go) — load/unload via `lms`.
