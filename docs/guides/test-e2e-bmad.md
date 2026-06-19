# Guide de test E2E — voix (murmure) → BMAD + Claude Code → bmad-ui

Use case complet, **validé le 2026-06-17** : demander à la voix la création d'une petite
app, la faire produire par l'agent Claude (forfait) en s'appuyant sur **BMAD**, puis suivre
les artefacts (PRD, architecture, epics, stories) dans **bmad-ui**.

> **À savoir** : murmure n'est pas (encore) câblé directement à n8n — c'est un **clavier
> vocal** qui tape dans la fenêtre active. Le chemin actuel = **dicter dans Telegram**.
> Dicter un slash-command à la voix étant pénible, on **tape `/build`** puis on **dicte
> la spec**.

## Pré-vol

```bash
docker compose ps                 # n8n, litellm, whisper, qdrant, telegram-poller : Up
curl -s localhost:8088/health     # bridge claude -p
curl -s localhost:8089/health     # worker agentique
command -v bmad-start             # commande UI déployée
```

Worker sur le forfait (`claude login` fait, pas d'`ANTHROPIC_API_KEY`). bmad-ui installé
(`scripts/bmad-ui-setup.sh`, une fois).

## Étape 0 — Projet cible (opt-in)

```bash
mkdir -p ~/dev/demo-todo && cd ~/dev/demo-todo
git init -q && git add -A && git commit -q -m "init"
/datadisk/ai-projects/ai-to-boost/scripts/ai-to-boost-init.sh .
```

→ marqueur `.ai-to-boost/` requis par le worker (base_branch détectée). L'init **expose
aussi BMAD en interactif** (symlinks `_bmad/` + `.claude/skills/bmad-*` vers le partagé) :
dans une session Claude Code sur ce projet, `/bmad-help`, `/bmad-prd`, etc. deviennent
disponibles. `/bmad-help` lit l'état du projet et recommande la prochaine étape.

**Cibler ce projet** : le poller Telegram n'envoie pas de chemin → le worker utilise
`AGENT_DEFAULT_REPO`. Pour viser `~/dev/demo-todo` :

```bash
# dans /datadisk/ai-projects/ai-to-boost/.env
AGENT_DEFAULT_REPO=/home/<user>/dev/demo-todo
# puis
systemctl --user restart claude-agent
```

(ou tester sur le projet déjà pointé par `AGENT_DEFAULT_REPO`).

## Étape 1 — murmure en dictée brute

- Raccourci d'enregistrement **brut** (ex. `Ctrl+Space`) — **pas** les modes LLM
  « mumu général/traduction » (ils reformuleraient la commande).

## Étape 2 — Dicter la demande dans Telegram

1. Telegram → focus champ message → **tape `/build`**.
2. Déclenche murmure et **dicte la spec**, ex. :
   > « En t'appuyant sur les skills BMAD, initialise une petite application TODO list.
   > Produis docs/prd.md, docs/architecture.md, \_bmad-output/planning-artifacts/epics.md,
   > \_bmad-output/implementation-artifacts/sprint-status.yaml avec 2-3 stories, et un
   > squelette minimal package.json + src/index.js. »
3. **Envoie**.

> Préciser les **chemins** (`docs/`, `_bmad-output/…`) garantit que bmad-ui affichera le
> contenu. L'agent consulte alors les skills BMAD (`bmad-create-prd`,
> `bmad-create-epics-and-stories`…) et génère le `sprint-status.yaml` au **format BMAD**
> (donc le board se peuple).

## Étape 3 — Observer (Telegram)

- Immédiat : **« 🛠️ Tâche <id> acceptée »**.
- ~1-3 min plus tard : **résultat** (branche `agent/<id>` + diff + résumé).

## Étape 4 — Récupérer le travail

```bash
cd ~/dev/demo-todo
git checkout agent/<id>          # le working tree contient docs/ + _bmad-output/
ls docs _bmad-output/*/
```

## Étape 5 — Visualiser dans bmad-ui

```bash
cd ~/dev/demo-todo
bmad-start                       # → http://localhost:5273 (focalisé sur ce projet)
```

- **Docs** : `prd`, `architecture`, `README`.
- **Board / Stories** : peuplé depuis `sprint-status.yaml` (validé : 5 stories,
  statuts backlog/ready-for-dev/done).
- Port dédié **5273** (jamais 5173) ; un projet à la fois (bascule via `bmad-start`).

## Ce qui est prouvé (run du 2026-06-17, sur demo-todo)

`/build` → worker (BMAD injecté) → 6 fichiers (PRD, architecture, epics, sprint-status,
package.json, src/index.js), CLI smoke-testée (node). bmad-ui : Docs OK + Board 5 stories.
**Aucun push** (branche `agent/<id>`), garde-fou Bash actif, forfait.

## Dépannage

- Worker refuse (`projet non initialisé`) → lancer `ai-to-boost-init.sh` sur la cible.
- Job sur le mauvais repo → ajuster `AGENT_DEFAULT_REPO` (+ restart `claude-agent`).
- bmad-ui Docs vide → l'agent n'a pas écrit dans `docs/` (préciser le chemin dans la spec).
- Board vide → `sprint-status.yaml` absent/hors schéma (demander explicitement de l'écrire).
- Port 5273 occupé → `BMAD_UI_PORT=5274 bmad-start`.

## Variante voix « directe » (non implémentée)

Une **entrée murmure→n8n** dédiée (Phase 6c) permettrait de parler la demande sans passer
par Telegram (wake word « build »). Non câblée à ce jour — cf. mémoire projet.
