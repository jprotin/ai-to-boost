# ADR 0008 — Persistance, reprise et archive des pipelines BMAD

- **Statut** : Accepté
- **Date** : 2026-06-29
- **Décideurs** : protin
- **Lié à** : [ADR 0004](0004-pipeline-bmad-multi-persona-multi-llm.md) (moteur de pipeline),
  [ADR 0005](0005-webapp-tour-de-controle-nextjs.md) (web-app tour de contrôle).

## Contexte

Le moteur de pipeline (worker `claude-agent`) tient l'état des pipelines dans un dict
**en mémoire** (`PIPELINES`), persisté au fil de l'eau dans `<repo>/.ai-to-boost/pipeline.json`.
Deux limites sont apparues à l'usage :

1. **Perte au redémarrage.** Le worker exécute chaque phase dans un thread. Un redémarrage
   du service (déploiement, reboot) **tue le thread** et vide `PIPELINES` ; `pipeline.json`
   reste figé à `status=running`. Le pipeline devient **orphelin** : plus aucun thread ni
   process `claude`, mais il s'affiche « running » indéfiniment (incident constaté le 29/06).
2. **Pas d'historique.** `pipeline.json` ne suit qu'**un** pipeline (le dernier). Relancer un
   pipeline sur un projet **écrase** le fichier ; les PRD/architecture/epics/stories des runs
   précédents ne sont plus consultables (seules les branches git `pipeline/<id>` subsistent).

## Décision

### Reprise au démarrage (réhydratation)

Au boot, `_rehydrate_pipelines()` recharge en mémoire le `pipeline.json` de chaque projet du
registre, puis **reprend** les pipelines laissés en cours (`running`/`accepted`) en relançant
`_run_pipeline` depuis leur `phase_index`. C'est sûr car les phases sont
**idempotentes / cumulatives** (la boucle d'implémentation saute les stories `review`/`done`,
rejoue `in-progress`/`backlog` sur le worktree conservé). Garde-fous :

- les pipelines en `awaiting_approval` restent **en attente** (décision humaine) ;
- un worktree disparu → le run est marqué `error` (plutôt que faussement « running »).

### Archive (snapshot par run)

`_persist_pipe()` écrit, en plus de `pipeline.json` (pointeur courant), un **snapshot par
run** dans `<repo>/.ai-to-boost/pipelines/<pipeline_id>.json`, **jamais écrasé** par un run
suivant. L'historique (`GET …/history`) liste ces snapshots ; le board d'un run passé
(`GET …/history/<pid>`) et ses artefacts sont **reconstruits depuis la branche git du run**
(`git show pipeline/<id>:<chemin>`), immuable, même worktree retiré. Horodatage `created` /
`finished` ajouté à l'état.

Le tout reste **local et gitignoré** (`.ai-to-boost/`), cohérent avec le modèle existant
(local-first, source de vérité côté worker — ADR 0005).

## Conséquences

### Positives

- Les pipelines **survivent** aux redémarrages du worker (reprise automatique).
- **Historique consultable** depuis la webui (onglet Archive) : besoins, PRD, architecture,
  epics/stories et tokens de chaque run passé, sans dépendre du worktree.
- Logique de board **factorisée** (`_build_board`) entre courant et archive.

### Négatives / points d'attention

- L'archive démarre **« à partir de maintenant »** : les runs déjà écrasés dans `pipeline.json`
  avant cette décision n'ont pas de snapshot (seule leur branche git subsiste). La
  réhydratation snapshote toutefois le run **courant** de chaque projet au premier boot.
- Un projet ne suit toujours qu'**un** pipeline « courant » à la fois (le pointeur
  `pipeline.json`). Mener plusieurs pipelines en parallèle sur un même projet reste un
  chantier ultérieur.
- Les snapshots s'accumulent (un petit JSON par run) ; purge éventuelle à prévoir si volume.

### Règle d'exploitation

Avant de redémarrer le worker, vérifier qu'aucun pipeline n'est en cours d'exécution
(`ai2b status` / `GET /projects` → `pipeline_status=running`). La reprise automatique limite
l'impact, mais une interruption en pleine phase relance la phase courante.

## Alternatives écartées

- **Base de données** (SQLite/Postgres) pour l'état pipeline : surdimensionné pour du
  local-first mono-utilisateur ; le couple `pipeline.json` + snapshots + branches git suffit.
- **Reprise manuelle uniquement** : laisse des pipelines orphelins « running » ; mauvaise UX.
- **Archive basée seulement sur les branches `pipeline/*`** : perd les métadonnées non
  versionnées (besoin initial, tokens, horodatage) → snapshot retenu.
