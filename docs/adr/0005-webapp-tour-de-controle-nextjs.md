# 0005 — Web-app tour de contrôle (Next.js + shadcn/ui)

- **Status** : accepted
- **Date** : 2026-06-26
- **Auteur(s)** : protin
- **Tags** : architecture, frontend, web, ux, orchestration

## Contexte

ai-to-boost orchestre des projets via le pipeline BMAD (ADR 0004) et expose aujourd'hui
**trois entrées** : la CLI `ai2b`, Telegram (texte + voix, Lot C C1/C2/C5) et `bmad-ui`
(consultation **lecture seule** du board d'un projet à la fois). Il manque l'entrée
**web** de la vision « tour de contrôle » : une interface unique pour discuter, voir tous
les projets pilotés par BMAD, suivre leurs epics/stories et leur pipeline, et prompter par
projet — en **2-3 mouvements**.

`bmad-ui` (lecteur Svelte/Vite externe, installé globalement, focalisé par symlinks sur un
projet) ne couvre que la consultation d'un board et reste mono-projet ; il ne gère ni chat,
ni multi-projets, ni déclenchement, ni paramétrage.

Forces en présence :

- **CGU** (ADR 0002, [[conformite-cgu-claude]]) : Claude **uniquement** via `claude -p`
  (bridge `:8088`, forfait) — **jamais** le SDK/API depuis l'app. Les LLM locaux passent par
  LiteLLM `:4000`.
- **Local-first** (ADR 0003) : pas d'exposition internet ; l'app reste sur `127.0.0.1`.
- **Usage perso** : **mono-utilisateur**, pas de multi-tenant ni d'OAuth tiers.
- **Backend existant à réutiliser** : worker `:8089` (`/jobs`, `/pipelines`,
  `/pipelines/resume`), dispatcher n8n (`assistant-in`), bridge `:8088`, LiteLLM `:4000`.
- **Secret `AGENT_TOKEN`** : ne doit jamais arriver dans le navigateur.
- **Stack du repo** : majoritairement Python + bash ; introduire Node/React est un ajout
  structurant (build, image, maintenance).

## Options envisagées

### Option 1 : petit chat statique → `assistant-in`

- **Description** : page HTML/JS minimale qui POST le webhook dispatcher et affiche la
  réponse synchrone.
- **Pour** : trivial, réutilise tout le routage.
- **Contre** : ne couvre rien de la vision (pas de projets, board, auth, multi-pages,
  jalons temps réel). Hors périmètre demandé.

### Option 2 : n8n Chat Trigger

- **Description** : UI de chat intégrée à n8n.
- **Pour** : rapide à poser.
- **Contre** : async limité, entrée séparée d'`assistant-in`, non maîtrisable (pas de
  dashboard/projets/auth/board), couplée à n8n.

### Option 3 : web-app Next.js complète (retenue)

- **Description** : application **Next.js** (App Router) + **shadcn/ui**, **dockerisée**,
  avec auth mono-utilisateur, et un **BFF** (API routes côté serveur) qui parle au backend
  existant. Le worker est **étendu d'une API lecture** pour exposer projets et board.
  Remplace `bmad-ui` à terme.
- **Pour** : un seul codebase (pages + BFF + auth + SSE) ; shadcn impose React, Next le
  fournit nativement ; le BFF garde `AGENT_TOKEN` côté serveur (jamais dans le navigateur) ;
  SSE pour les jalons ; testable/versionné ; couvre toute la vision.
- **Contre** : ajoute la stack Node/React au repo ; surface de sécurité (auth) ; gros
  chantier multi-phases.

### Sous-option (dans l'option 3) : Vite+React SPA + backend Node séparé

- **Contre** : deux artefacts à build/déployer, le BFF et l'auth à recâbler à la main, SSE
  et sessions plus lourds. Next.js mono-codebase est plus simple ici.

## Décision

Nous retenons l'**option 3** : web-app **Next.js (App Router) + shadcn/ui**, dockerisée
(service `webui` dans `compose.yaml`, bind `127.0.0.1`), **mono-utilisateur** via **Auth.js**
(provider _credentials_, mot de passe haché en `.env`), avec un **BFF** (API routes Next).

**Le BFF est le seul à parler au backend** (le navigateur ne voit que le BFF) :

- **Chat général** : sélecteur de modèle → **Claude via le bridge `:8088`** (`claude -p`,
  forfait — **jamais l'API**, CGU) **ou** **local-gemma/qwen via LiteLLM `:4000`**.
- **Pipeline / jobs** : worker `:8089` (`/pipelines`, `/jobs`, `/pipelines/resume`), en
  injectant `AGENT_TOKEN` **côté serveur**.
- **Projets + epics/stories + état pipeline** : nouvelle **API lecture du worker**
  (`GET /projects`, `GET /projects/<nom>/board`, etc.) — source de vérité unique, sans monter
  les repos/worktrees dans le conteneur web.
- **Jalons temps réel** : le worker route les callbacks `return_target = web:<session>` vers
  un `/notify` du BFF ; le navigateur s'abonne en **SSE**.

**Pages** : Dashboard · Chat général · Projets (liste) · Projet (détail : epics/stories avec
statut+infos, chat dédié au projet, état pipeline, décisions de jalon) · Paramètres.

**`bmad-ui` est remplacé** : la page Projet de la web-app le supplante. `bmad-ui` est conservé
en parallèle jusqu'à parité fonctionnelle, puis retiré (commande `bmad-start` / `ai2b ui`
re-pointées ou dépréciées).

**Sécurité** : `127.0.0.1` only ; toute page/route protégée par session ; `AGENT_TOKEN` et
clés jamais exposés au client ; pas de secret dans le bundle.

**Découpage en phases** (chacune = une branche `feature/*` + livraison) :

- **C3.0** — ADR (ce document) + scaffold Next.js/shadcn + Dockerfile + service compose +
  auth (login/logout) + shells des 5 pages.
- **C3.1** — Chat général (Claude via bridge / local via LiteLLM, sélecteur de modèle).
- **C3.2** — Worker : API lecture (`/projects`, board) + page Projets.
- **C3.3** — Page Projet : epics/stories (statut + infos) + état pipeline.
- **C3.4** — Chat dédié projet → déclenche `/run` / jobs scopés au projet.
- **C3.5** — Jalons temps réel (SSE) + décisions approve/revise/stop depuis le web.
- **C3.6** — Page Paramètres ; dépréciation de `bmad-ui`.

## Conséquences

### Positives

- Entrée web unifiée conforme à la vision ; multi-projets, board, chat, pilotage en un lieu.
- Réutilise tout le backend ; `AGENT_TOKEN` confiné au serveur.
- Claude reste sur `claude -p` (CGU) ; LLM locaux via LiteLLM.
- Le worker devient la source de vérité (API lecture) → bmad-ui et web-app cohérents.
- Codebase unique testable/versionné.

### Négatives / Coûts

- Ajout d'une stack **Node/React** à un repo surtout Python/bash (build, image, lint front).
- Surface de sécurité : auth, sessions, durcissement même en local.
- Chantier conséquent (7 phases) ; le worker doit grossir (API lecture).

### Neutres / À surveiller

- **CGU** : vérifier en continu qu'aucun chemin n'appelle l'API Claude (seul `claude -p`).
- **Exposition** : rester strictement `127.0.0.1` (un reverse-proxy/LAN serait un nouvel ADR).
- **Migration bmad-ui** : ne le retirer qu'après parité (board projet).
- **Multi-session** : mono-utilisateur, mais plusieurs onglets ⇒ corrélation `web:<session>`
  pour router les notifs SSE au bon onglet.

## Alternatives non explorées (et pourquoi)

- **SDK/API Claude pour le chat** : exclu par les CGU (forfait via `claude -p` uniquement).
- **Auth multi-utilisateurs / SSO** : hors usage perso ; complexité injustifiée.
- **Exposer la web-app sur le LAN/mobile** : nécessiterait TLS + durcissement ⇒ ADR dédié.
- **Garder bmad-ui comme board** : doublon mono-projet, non intégré au chat/pilotage.

## Références

- [ADR 0001](0001-architecture-assistant-ia-local-orchestre.md) — architecture d'ensemble
- [ADR 0002](0002-litellm-modeles-locaux-uniquement.md) — LiteLLM local-only, Claude via `claude -p`
- [ADR 0003](0003-telegram-polling-sans-exposition.md) — local-first, sans exposition
- [ADR 0004](0004-pipeline-bmad-multi-persona-multi-llm.md) — pipeline BMAD
- `docs/runbooks/ai2b.md`, `docs/runbooks/phase6a-dispatcher.md` — backend réutilisé
- `docs/runbooks/bmad-ui.md` — lecteur remplacé
