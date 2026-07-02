# Dépannage

Problèmes fréquents et correctifs, centralisés. Le détail par service reste dans
`docs/runbooks/*` (section « Dépannage » de chacun).

## Modèles / LLM

- **`content` vide sur `local-qwen`** — `qwen3.5:9b` est un _reasoner_ bavard : la réflexion
  consomme `max_tokens` puis est retirée du contenu → réponse vide si budget trop bas.
  Prévoir `max_tokens ≥ 8000–16000` côté appelant (le worker utilise 16000).
- **`reply` vide en chat local (gemma)** — même cause ; prévoir `max_tokens ≥ 2048`.
- **Ollama « NVML version mismatch »** — driver NVIDIA mis à jour sans reboot (TUXEDO) →
  **redémarrer la machine**.
- **Un modèle local ne charge pas** — VRAM insuffisante (12 Go). `qwen3.5:9b` tient seul ;
  `gemma4:e4b` + embed tiennent ensemble. `OLLAMA_KEEP_ALIVE` gère le load/unload.

## Pipeline / worker

- **Une story reste `in-progress`, la suivante démarre** — la story a **échoué le juge QA**
  (ou atteint `max_turns`) : elle reste `in-progress` (honnête), le pipeline continue.
  Rejouer via `/revise` ou relancer. Si TOUTES les stories restent `in-progress` **sans
  code produit**, vérifier `PIPELINE_STORY_MAXTURNS` (trop bas → travail tronqué jeté).
- **Board vide sur un projet** — `pipeline.json` perdu (gitignoré). Le worker retombe sur la
  dernière branche `pipeline/*` ; sinon relancer un run.
- **Un changement de code du worker n'est pas pris** — le worker est un service **systemd
  user** : `systemctl --user restart claude-agent` (ou `ai2b restart worker`). Idem bridge.
- **`/run` Telegram échoue (« repo cible introuvable »)** — `AGENT_DEFAULT_REPO` vide/faux :
  `ai2b switch <projet>` (règle la variable + redémarre le worker).
- **Pipeline « running » figé après restart** — la réhydratation reprend les runs `running`
  (phases idempotentes/cumulatives) ; laisser terminer.

## Docker / webui

- **Build webui « réussi » mais rien ne change** — un build raté laisse tourner l'**ancien**
  conteneur (HTTP répond quand même). Vérifier l'image neuve, forcer `--force-recreate`.
- **Changement de `webui.env` non pris** — `env_file` n'est pas rechargé par un simple
  `restart` : `docker compose up -d --force-recreate webui`.
- **Micro « Voir en direct » / dictée indisponible** — `getUserMedia` exige un **contexte
  sécurisé** : OK sur `http://127.0.0.1:3001` (localhost), bloqué via une IP LAN en http.

## RAG / Qdrant

- **Recherche RAG vide / hors-sujet** — modèle d'embedding **différent** entre ingestion et
  requête, ou doc pas ingéré. `EMBEDDING_MODEL` doit être identique partout ; vecteur nommé
  `fast-nomic-embed-text-v1.5`. Ré-ingérer via `scripts/ai-to-boost-rag-sync.sh`.
- **Un doc supprimé pollue encore le RAG** — `ingest.py` **n'efface pas** les docs retirés.
  Supprimer les points : `POST /collections/<coll>/points/delete` (filtre `source`).

## n8n

- **Import de workflow non pris** — via l'UI, l'import **fusionne** dans le workflow ouvert.
  Utiliser la CLI : `docker cp` + `n8n import:workflow` (upsert par id) +
  `update:workflow --active=true` + `docker restart n8n`. Vérifier via `export:workflow`.

## Claude forfait (CGU)

- **Claude facture l'API au lieu du forfait** — `ANTHROPIC_API_KEY`/`ANTHROPIC_AUTH_TOKEN`
  exportée dans le shell. Vérif : `env | grep -i ANTHROPIC` → doit être **vide**. Le
  worker/bridge les retirent déjà de l'env enfant.
- **Worker/bridge crashent au démarrage** — binaire `claude` introuvable dans le `PATH` du
  service. Vérifier `~/.local/bin/claude` et le `PATH` du unit systemd.

## Git / outillage (dev)

- **`git log` incohérent** — le cache de `rtk` peut être périmé : vérifier via
  `rtk proxy git rev-parse` / `reflog`.
- **1er commit Python avorté** — `pre-commit` (ruff-format) reformate le fichier et annule le
  commit ; re-`git add` + re-commit (le 2e passage aboutit).

## Voir aussi

- Architecture : `docs/architecture.md` · Variables : `docs/environment-variables.md`
- Dépannage par service : `docs/runbooks/*`
