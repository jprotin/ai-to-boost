# 0004 — Pipeline BMAD multi-persona / multi-LLM

- **Status** : accepted
- **Date** : 2026-06-24
- **Auteur(s)** : protin
- **Tags** : architecture, orchestration, llm, bmad

## Contexte

Le worker agentique (`services/claude-agent`, Phase 6b) exécute aujourd'hui **un seul
appel `claude -p` one-shot** par tâche : un prompt, un modèle (Claude), une passe dans un
`git worktree`, un commit. Il « consulte » au mieux les skills BMAD, mais n'orchestre **pas**
les personas BMAD (analyst, PM, architecte, dev, QA). Conséquence : les epics/stories sont
produits de façon irrégulière, le board bmad-ui reste souvent vide, et les LLM locaux
(`local-gemma`, `local-qwen` via LiteLLM) ne sont jamais exploités.

ai-to-boost se positionne comme **tour de contrôle** (cf. [vision], CLI `ai2b` du Lot A).
On veut, en 2-3 mouvements, déclencher un développement **complet et cadré** : brief → PRD →
architecture → epics/stories → implémentation, avec la méthode BMAD réellement déroulée,
GitFlow, et une validation humaine aux étapes clés.

Forces en présence :

- **CGU** : Claude doit passer **exclusivement** par `claude -p` (forfait), jamais par le SDK
  ou une clé API. Les LLM locaux passent par LiteLLM (cf. ADR 0002).
- **Coût/latence** : le planning (analyse, PRD, découpage) est moins exigeant que
  l'architecture et le code → candidat au local pour économiser le forfait.
- **Qualité** : un mauvais artefact amont (PRD faible) empoisonne tout l'aval → besoin de
  points de contrôle humains.
- **bmad-ui** lit des fichiers à **format strict** (parser regex ligne-à-ligne, pas du YAML
  libre) : `_bmad-output/implementation-artifacts/sprint-status.yaml` et
  `_bmad-output/planning-artifacts/epics.md`. Tout écart = board vide.
- **Réversibilité** : l'existant (`/jobs`, `ai2b build/code`) fonctionne et ne doit pas
  régresser.

## Options envisagées

### Option 1 : Orchestration dans n8n

- **Description** : un workflow n8n avec un node par persona, HTTP vers LiteLLM/worker,
  nodes `Wait` pour les jalons.
- **Pour** : n8n est déjà l'edge (Telegram, credentials, visuel) ; pas de nouveau service.
- **Contre** : logique d'orchestration en JSON n8n ininspectable/intestable/versionnée
  difficilement ; manipulation de git/worktree depuis n8n bancale ; attentes longues
  (validation humaine sur heures/jours) fragiles ; machine à états illisible.
- **Coût** : faible à écrire, élevé à maintenir et débugger.

### Option 2 : Tout dans le worker Python (moteur autonome)

- **Description** : moteur de pipeline complet dans `claude-agent`, y compris l'I/O
  utilisateur.
- **Pour** : code testable/versionné ; possède déjà git/worktree/garde-fou/RAG ; routage
  LLM trivial.
- **Contre** : le worker réimplémenterait l'I/O Telegram/UI déjà gérée par n8n ; duplication.

### Option 3 : Hybride — moteur dans le worker, n8n en edge fin (retenue)

- **Description** : le **moteur de pipeline** vit dans le worker (Python) ; **n8n** déclenche
  (`POST /pipelines`), relaie les messages de jalon vers Telegram/UI et renvoie la décision
  humaine (`POST /pipelines/<id>/resume`).
- **Pour** : séparation nette des responsabilités (orchestration en code, I/O dans n8n) ;
  réutilise tout l'outillage worker ; jalons = état persisté (survit aux redémarrages) ;
  additif et réversible.
- **Contre** : deux composants à coordonner via un contrat HTTP (simple et idempotent).
- **Coût** : modéré ; concentré dans du code Python testable.

## Décision

Nous retenons l'**option 3 (hybride)**.

Un **moteur de pipeline en Python** est ajouté au worker `claude-agent`, exposé par de
**nouveaux endpoints** `POST /pipelines` (démarrage) et `POST /pipelines/<id>/resume`
(reprise après jalon). L'endpoint `/jobs` one-shot est **conservé tel quel**. Le déclencheur
utilisateur est `ai2b run "<besoin>"` (et `/run` côté n8n/Telegram).

**Séquence (alignée BMAD bmm)**, chaque artefact committé sur une branche feature dédiée :

1. **Analyse** — persona _analyst_ → `docs/brief.md`. _(local)_
2. **Plan/PRD** — persona _PM_ → `docs/prd.md`. _(local)_ ⏸ **Jalon 1**
3. **Solutioning** — persona _architecte_ → `docs/architecture.md`. _(Claude)_ ⏸ **Jalon 2**
4. **Epics/Stories** — _PM/SM_ → `_bmad-output/planning-artifacts/epics.md` +
   `_bmad-output/implementation-artifacts/sprint-status.yaml`. _(local)_ ⏸ **Jalon 3**
5. **Implémentation** — boucle par story : persona _dev-story_ (`claude -p` **avec outils**
   Edit/Bash + garde-fou, en worktree, scopé à une story) puis _QA/review_. Mise à jour du
   statut de la story dans `sprint-status.yaml`. _(Claude)_

**Deux types de persona** :

- **Texte** : le moteur construit le prompt = \*(rôle persona + instructions de la tâche BMAD
  - artefacts amont + RAG)\*, appelle la LLM (LiteLLM local **ou** `claude -p` texte) et
    **écrit lui-même** l'artefact au chemin attendu. Pas d'outils.
- **Outils** : `claude -p` avec Edit/Bash sous garde-fou, mécanisme actuel, scopé à une story.

**Routage LLM** (table de config surchargeable, `pipeline.yaml`) : planning
(analyst/PM/epics) sur `local-gemma`/`local-qwen` **d'emblée** ; architecte + dev + QA sur
Claude (`claude -p`, forfait). Les jalons humains rattrapent une qualité locale insuffisante ;
chaque persona peut être promu sur Claude par configuration.

**Jalons** : à chaque ⏸, le moteur persiste l'état dans `.ai-to-boost/pipeline.json`, passe
en `awaiting_approval` et notifie via n8n. La décision humaine (`approve` |
`revise:<feedback>` | `stop`), reçue via Telegram ou `ai2b`, relance la phase suivante (ou
rejoue la phase courante avec le feedback). Le pipeline progresse **phase par phase**, pas en
process unique long.

**Format des artefacts** : générés via les **skills BMAD canoniques**
(`bmad-create-epics-and-stories`, `bmad-sprint-planning`) pour respecter le parser bmad-ui —
`sprint-status.yaml` : bloc `development_status:` avec lignes `N-M-slug: <statut>` (slug
minuscule ; statuts stories ∈ `backlog|ready-for-dev|in-progress|review|done` ; epics
`epic-N: backlog|in-progress|done`) ; `epics.md` : `## Epic N: Titre` + `### Story N.M:
Titre`, slug du titre cohérent avec l'id du YAML.

## Conséquences

### Positives

- Vraie méthode BMAD déroulée → epics/stories fiables, board bmad-ui peuplé.
- Forfait Claude économisé sur le planning (local), réservé à l'architecture et au code.
- Contrôle humain aux jalons → qualité maîtrisée sans micro-management.
- Additif et réversible : `ai2b build/code` (one-shot) reste disponible.
- Orchestration en code Python testable et versionné.

### Négatives / Coûts

- Plus de code et d'état à maintenir dans le worker (machine à états, persistance).
- Contrat HTTP worker↔n8n à tenir idempotent (reprise rejouable).
- Latence accrue (plusieurs passes LLM + attentes humaines) vs le one-shot.

### Neutres / À surveiller

- **Qualité réelle des LLM locaux** sur PRD/epics : à mesurer ; basculer sur Claude si faible.
- **Piège `local-gemma`** (modèle à raisonnement) : `max_tokens` ≥ 300-500 sinon réponse
  vide.
- **Stratégie de branche/commits** par story à affiner (un commit par phase/story).
- Couverture des jalons côté UI web (Lot C) — pour l'instant Telegram + `ai2b`.

## Alternatives non explorées (et pourquoi)

- **SDK Claude / API directe** : exclu par les CGU (forfait uniquement via `claude -p`),
  cf. ADR 0002.
- **Framework d'agents tiers (LangGraph, CrewAI…)** : surdimensionné, ajoute une dépendance
  lourde et un couplage, pour une séquence linéaire à jalons que du Python simple couvre.
- **Personas Claude en parallèle** : non pertinent ici (séquence avec dépendances amont/aval
  fortes) ; complexité de concurrence non justifiée.

## Références

- [ADR 0001](0001-architecture-assistant-ia-local-orchestre.md) — architecture d'ensemble
- [ADR 0002](0002-litellm-modeles-locaux-uniquement.md) — LiteLLM local-only, Claude via `claude -p`
- [ADR 0003](0003-telegram-polling-sans-exposition.md) — entrée Telegram par polling
- `docs/runbooks/ai2b.md` — CLI tour de contrôle (Lot A)
- `docs/runbooks/phase6b-worker.md` — worker agentique one-shot (existant)
- BMAD v6 : `~/agent-workspace/.bmad-shared/_bmad/bmm/` (workflows analysis/plan/solutioning/implementation)
- Format bmad-ui : parser `scripts/server/sprint/summarize.ts`, templates
  `bmad-create-epics-and-stories`, `bmad-sprint-planning` ; projet de référence `~/dev/demo-todo`
