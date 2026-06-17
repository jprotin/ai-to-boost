# Runbook — bmad-ui (dashboard BMAD multi-projets, instance unique)

Visualiser les artefacts BMAD d'un projet (docs/PRD/architecture, epics, stories,
sprint, analytics) via [bmad-ui](https://github.com/lorenzogm/bmad-ui), **installé une
seule fois** et **focalisé sur le projet courant** par `bmad-start`.

## Principe

bmad-ui calcule `projectRoot = parent de son dossier _bmad-ui` (aucun override par env).
On l'installe donc dans `~/.bmad-ui-global/_bmad-ui` (→ `projectRoot = ~/.bmad-ui-global`)
et `bmad-start` **repointe par symlink**, vers le projet courant, tous les chemins lus :

| Chemin global (sous projectRoot) | → symlink vers                       | Contenu                                            |
| -------------------------------- | ------------------------------------ | -------------------------------------------------- |
| `_bmad-output/`                  | `<projet>/_bmad-output/`             | epics, stories, sprint-status, test-artifacts      |
| `docs/`                          | `<projet>/docs/`                     | docs markdown (PRD, architecture…)                 |
| `README.md`                      | `<projet>/README.md`                 | overview                                           |
| `_bmad-ui/agents/`               | `<projet>/.bmad-ui-state/agents/`    | sessions/analytics (état UI, **isolé par projet**) |
| `_bmad-ui/artifacts/`            | `<projet>/.bmad-ui-state/artifacts/` | links/notes (état UI, isolé)                       |

Une seule instance / port 5273 → **un projet à la fois** (bascule instantanée ;
`bmad-start` tue l'instance précédente). Pas de multi-projets simultanés.

## Installation (une fois)

```bash
scripts/bmad-ui-setup.sh
```

Installe bmad-ui dans `~/.bmad-ui-global` (`npx bmad-method-ui install`, sans réseau
ensuite), les deps (`corepack pnpm install`, sans navigateurs Playwright), capture le
gabarit d'état `.state-template/`, et déploie `bmad-start` dans `~/.local/bin`.
Prérequis : node ≥ 24 + corepack (via nvm), `~/.local/bin` dans le PATH.

## Usage

```bash
cd ~/dev/mon-projet        # un projet avec docs/ et/ou _bmad-output/
bmad-start                 # → http://localhost:5273, focalisé sur ce projet
```

Override possibles : `BMAD_UI_GLOBAL` (dossier central), `BMAD_UI_PORT`.
L'état UI par projet est dans `<projet>/.bmad-ui-state/` (gitignoré par l'init).

## Limites / notes

- **Local-first**, lecture seule sur les artefacts (édite seulement `sprint-status.yaml`
  - notes/links UI). Serveur dev permissif sur le FS → **ne pas exposer hors localhost**.
- bmad-ui est **alpha / mono-mainteneur**, testé contre BMAD 6.3.0 (nous : 6.8.0). La
  vue **Docs** lit `<projet>/docs/*.md` + `README.md` ; epics/stories lisent
  `_bmad-output/` — si BMAD 6.8 range certains artefacts ailleurs, ils peuvent ne pas
  s'afficher (à ajuster selon la sortie réelle du worker).
- `_bmad-output/` doit être **versionné** dans le projet (les jobs BMAD du worker l'y
  committent) ; `.bmad-ui-state/` reste privé (gitignoré).
