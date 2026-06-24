# Runbook — `ai2b` (tour de contrôle)

CLI central pour piloter ai-to-boost et les projets qu'il orchestre. Remplace les
manipulations manuelles (`.env` + `systemctl restart`, `git init`, `bmad-start`…).

- Script : `scripts/ai2b.sh` (lien `~/.local/bin/ai2b`).
- Registre : `${XDG_CONFIG_HOME:-~/.config}/ai-to-boost/projects.json` — liste des projets
  - **projet actif**.
- Projets créés par défaut sous `~/dev` (surchargeable : `AI2B_PROJECTS_DIR`).

## Installation

```bash
ln -sfn /datadisk/ai-projects/ai-to-boost/scripts/ai2b.sh ~/.local/bin/ai2b
ai2b help
```

## Cycle de vie d'un projet

```bash
ai2b new mon-projet              # crée ~/dev/mon-projet : git init + GitFlow + init BMAD,
                                 # commit initial + .gitignore versionné, enregistre + active
ai2b init ~/code/repo-existant   # enregistre un repo git existant comme projet piloté
ai2b switch mon-projet           # change le projet actif (recible le worker)
ai2b ls                          # liste (▶ = actif, ● présent / ✕ absent, [base_branch])
ai2b current                     # projet actif
ai2b rm mon-projet               # retire du registre (registre seul)
ai2b rm mon-projet --purge       # …et supprime le répertoire (confirmation demandée)
```

`new` détecte la branche `develop` comme `base_branch` (GitFlow). Le worker branchera
toujours ses tâches depuis cette base (`agent/<id>`), jamais de push/merge automatique.

## Services

```bash
ai2b status                      # docker compose + bridge:8088 + worker:8089 + projet actif
ai2b up | down                   # démarre / arrête toute la stack (docker + systemd user)
ai2b restart [service]           # tout, ou un service : worker | bridge | <service compose>
ai2b logs <service>              # suit les logs (journalctl pour worker/bridge, sinon compose)
```

## Vie du projet actif

```bash
ai2b build "<spec>"              # tâche agentique, Bash autorisé (garde-fou PreToolUse actif)
ai2b code  "<spec>"             # tâche agentique, édition de fichiers
ai2b job <id>                    # état d'une tâche (statut, branche, diff_stat, coût)
ai2b ui                          # bmad-ui focalisé sur le projet actif (port 5273)
```

Les tâches sont envoyées au worker (`POST :8089/jobs`, `Authorization: Bearer AGENT_TOKEN`)
avec le `repo` du projet actif. Récupération du résultat : `git checkout agent/<id>`.

## Pipeline BMAD (Lot B, ADR 0004)

Au lieu d'une tâche one-shot, déroule la **méthode BMAD** par personas avec jalons de
validation. État B1 : phases _analyst_ + _PM_ (texte, LLM local) + 1er jalon après le PRD.

```bash
ai2b run "<besoin>"      # démarre le pipeline (analyst→brief, PM→PRD) puis s'arrête au jalon
ai2b pipeline [id]       # état (défaut : dernier pipeline du projet actif)
ai2b approve             # valide le jalon et continue
ai2b revise "<retour>"   # rejoue la phase en attente avec un retour humain
ai2b stop                # arrête le pipeline
```

- Endpoints worker : `POST /pipelines`, `GET /pipelines/<id>`, `POST /pipelines/<id>/resume`.
- Branche dédiée `pipeline/<id>` (worktree), artefacts committés par phase ; aucun push/merge.
- État persisté dans `.ai-to-boost/pipeline.json`.
- Routage LLM : planning sur `PIPELINE_PLANNING_MODEL` (défaut `local-gemma`) via LiteLLM ;
  architecte/dev/QA sur Claude (`claude -p`) — ajoutés en B2/B3.
- Récupération : `git checkout pipeline/<id>` puis `ai2b ui` pour le board bmad-ui.

## Notes

- `switch`/`new` réécrivent `AGENT_DEFAULT_REPO` dans `.env` et redémarrent `claude-agent`
  (transition : sera remplacé par un ciblage dynamique via n8n quand le Lot C sera livré —
  le `repo` est déjà accepté dans le payload du worker).
- Supprimer le projet **actif** laisse `AGENT_DEFAULT_REPO` pointer sur un chemin disparu
  jusqu'au prochain `switch`/`new` (sans gravité, le worker refuse un repo invalide).
