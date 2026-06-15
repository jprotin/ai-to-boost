# Runbook — Phase 3 : orchestrateur n8n

Orchestrateur de workflows, connecté à `whisper` et `litellm`.
Voir [ADR 0001](../adr/0001-architecture-assistant-ia-local-orchestre.md) et
[ADR 0002](../adr/0002-litellm-modeles-locaux-uniquement.md) (routage Claude).

## Périmètre

- Service `n8n` (`docker.n8n.io/n8nio/n8n`), UI sur `http://127.0.0.1:5678`.
- Persistance : **réutilise l'instance Postgres `litellm-db`** (base + rôle dédiés `n8n`).
- Joint les autres services par nom dans `ai-assistant-net` : `whisper:8000`, `litellm:4000`.
- **Claude via `claude -p` : différé** (sous-chantier dédié — bridge HTTP sur l'hôte ;
  voir Notes). En Phase 3, l'étape LLM utilise le **local** (`local-gemma` via LiteLLM).

## Prérequis

- `.env` : `N8N_ENCRYPTION_KEY` (chiffre les credentials — **ne pas perdre/changer**)
  et `N8N_DB_PASSWORD` (rôle Postgres `n8n`).
- Base `n8n` présente dans `litellm-db`.

### Création de la base n8n

- **Déploiement neuf** : le script `services/litellm/initdb/10-create-n8n-db.sh`
  crée la base + le rôle au premier démarrage de `litellm-db` (data dir vide).
- **Instance déjà initialisée** (cas courant) : créer manuellement —

```bash
PGPW=$(grep '^POSTGRES_PASSWORD=' .env | cut -d= -f2)
N8NPW=$(grep '^N8N_DB_PASSWORD=' .env | cut -d= -f2)
docker exec -e PGPASSWORD="$PGPW" litellm-db psql -U litellm -d postgres \
  -c "CREATE ROLE n8n LOGIN PASSWORD '$N8NPW';" \
  -c "CREATE DATABASE n8n OWNER n8n;" \
  -c "GRANT ALL PRIVILEGES ON DATABASE n8n TO n8n;"
```

## Démarrage

```bash
docker compose up -d n8n
docker compose logs -f n8n   # migrations + "Editor is now accessible"
```

Premier accès `http://127.0.0.1:5678` → création du **compte propriétaire** (user
management n8n). Données et credentials chiffrés via `N8N_ENCRYPTION_KEY`.

## 1er workflow (démo bout-en-bout)

Workflow versionné : `services/n8n/workflows/01-demo-whisper-litellm.json`.

- Import : UI n8n → _Workflows_ → _Import from File_ → choisir le JSON.
- Avant exécution : remplacer `CHANGEME_LITELLM_MASTER_KEY` dans le nœud
  _LiteLLM local-gemma_ par la `LITELLM_MASTER_KEY` du `.env` (ou créer un
  credential _Header Auth_ et le référencer).
- _Execute Workflow_ : le nœud _Whisper connectivité_ liste les modèles STT, le
  nœud _LiteLLM local-gemma_ renvoie une complétion → chaîne n8n ↔ whisper ↔ LiteLLM OK.

## Validation (critère de passage Phase 4)

```bash
# UI / API up
curl -s -o /dev/null -w "n8n: HTTP %{http_code}\n" http://127.0.0.1:5678/healthz

# Réseau interne : n8n joint whisper et litellm
docker exec n8n sh -c 'wget -qO- http://whisper:8000/v1/models >/dev/null && echo "whisper OK"'
docker exec n8n sh -c 'wget -qO- http://litellm:4000/health/liveliness >/dev/null && echo "litellm OK"'
```

## Dépannage

- **n8n ne démarre pas / erreur DB** : vérifier la base `n8n` et `N8N_DB_PASSWORD`
  (cf. création manuelle ci-dessus), et que `litellm-db` est _healthy_.
- **Credentials illisibles après redéploiement** : `N8N_ENCRYPTION_KEY` a changé —
  remettre la clé d'origine.
- **401 sur le nœud LiteLLM** : clé `Authorization` non remplacée (placeholder).

## Notes — bridge `claude -p` (différé)

Pour appeler Claude (forfait Max) depuis n8n sans clé API : monter un **petit
wrapper HTTP sur l'hôte** exécutant `claude -p`, appelé par n8n via
`host.docker.internal` (`extra_hosts` déjà en place). Garde l'auth Claude native
sur l'hôte, conforme à l'[ADR 0002](../adr/0002-litellm-modeles-locaux-uniquement.md).
À traiter en étape dédiée avant la Phase 4 (entrées Telegram).
