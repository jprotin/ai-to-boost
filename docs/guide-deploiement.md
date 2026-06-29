# Guide de déploiement & d'utilisation — ai-to-boost

Ce guide va de l'installation à pied d'œuvre jusqu'au parcours complet d'un projet depuis
la **web-app tour de contrôle** : créer un projet → lancer un pipeline BMAD → relire les
artefacts → approuver → récupérer le résultat → consulter l'archive.

> ai-to-boost est un **assistant IA local-first orchestré** qui _pilote des projets externes_
> (il n'est jamais lui-même la cible). Voir [ADR 0001](adr/0001-architecture-assistant-ia-local-orchestre.md).

---

## 1. Prérequis

| Composant                     | Détail                                                                                                           |
| ----------------------------- | ---------------------------------------------------------------------------------------------------------------- |
| **OS**                        | Linux (testé sur TUXEDO / Ubuntu-like)                                                                           |
| **Docker**                    | Docker Engine + Compose v2                                                                                       |
| **GPU NVIDIA**                | + `nvidia-container-toolkit` (runtime `nvidia` / CDI) pour Ollama & Whisper                                      |
| **Ollama**                    | servi **dans** la stack (image dockerisée, GPU) — cf. [ADR 0007](adr/0007-ollama-dockerise-remplace-lmstudio.md) |
| **Claude Code**               | binaire `claude` (`~/.local/bin/claude`), connecté au **forfait** (jamais `ANTHROPIC_API_KEY` exportée)          |
| **Python 3.12+**, `git`, `jq` | pour le worker, `ai2b` et l'init des projets                                                                     |

Vérifier le GPU dans Docker :

```bash
docker run --rm --gpus all ollama/ollama nvidia-smi   # doit lister le GPU
```

> ⚠️ **CGU Claude** : l'usage Claude passe **uniquement** par `claude -p` (forfait). Ne jamais
> exporter `ANTHROPIC_API_KEY` dans le shell — Claude Code basculerait sur l'API facturée.
> Cf. [ADR 0002](adr/0002-litellm-modeles-locaux-uniquement.md).

## 2. Configuration

1. Copier `.env.example` → `.env` et renseigner les secrets :
   - `LITELLM_MASTER_KEY` (clé gateway, format `sk-…`), `POSTGRES_PASSWORD`, `DATABASE_URL`,
   - `OLLAMA_BASE_URL=http://ollama:11434/v1`,
   - `AGENT_TOKEN`, `BRIDGE_TOKEN` (worker / bridge), `TELEGRAM_*` (optionnel).
2. Secrets webui dans `services/webui/webui.env` (modèle `webui.env.example`) :
   `AUTH_SECRET`, `WEBUI_USER`, `WEBUI_PASSWORD_HASH` (bcrypt). Défaut posé : `admin` /
   `ai2b-admin` — **à changer**.

## 3. Démarrer la stack

```bash
ai2b up        # docker compose up -d + services hôte (bridge, worker systemd)
ai2b status    # état des 8 services docker + bridge/worker + projet actif
```

Au premier démarrage, le service `ollama-init` télécharge les modèles (≈10 Go :
`gemma4:e4b`, `qwen3.5:9b`, `nomic-embed-text`), puis `litellm` démarre.

Services exposés (local uniquement) :

| Service       | URL                     | Rôle                                   |
| ------------- | ----------------------- | -------------------------------------- |
| **webui**     | <http://127.0.0.1:3001> | tour de contrôle (navigateur)          |
| litellm       | `:4000`                 | gateway modèles locaux (OpenAI-compat) |
| ollama        | `:11434`                | serveur de modèles (GPU)               |
| whisper       | `:8000`                 | STT (voix → texte)                     |
| n8n           | `:5678`                 | orchestrateur de flux                  |
| qdrant        | `:6333`                 | base vectorielle (RAG)                 |
| worker (hôte) | `:8089`                 | moteur agentique / pipeline BMAD       |
| bridge (hôte) | `:8088`                 | `claude -p` (forfait)                  |

## 4. Parcours complet dans la web-app

Se connecter sur <http://127.0.0.1:3001> (identifiants `webui.env`).

1. **Dashboard** — vue d'ensemble : nb de projets, pipelines actifs / jalons en attente,
   stories terminées, **tokens cumulés**, et la liste des projets avec leur statut.
2. **Projets → « Nouveau projet »** — saisir un nom (chemin par défaut `~/dev/<nom>`). Le worker
   crée un dépôt git (`main` + `develop`), pose le marqueur `.ai-to-boost/` et l'enregistre.
   (Suppression = retrait du registre, **non destructif** : les fichiers restent.)
3. **Ouvrir le projet → « Lancer un pipeline »** — décrire le besoin. Le pipeline déroule
   _analyst → PM → architecte → epics → implémentation_ sur une branche dédiée `pipeline/<id>`,
   avec des **jalons de validation**. Le board se met à jour en direct (polling).
4. **Jalon → onglet « Artefacts »** — à chaque `awaiting_approval`, la webui ouvre l'artefact de
   la phase (Brief, PRD, Architecture, Epics) en Markdown. **Relire**, puis dans le bandeau de
   jalon : **Approuver** / **Réviser** (avec un retour) / **Arrêter**.
5. **Board** — epics & stories avec statut et **tokens** (↑ entrée / ↓ sortie) par story, somme
   par epic, total pipeline. Clic sur une story → détail du dev.
6. **« Récupérer le résultat »** (statut _done_) — fusionne `pipeline/<id>` dans la base
   (`develop`) du projet (merge `--no-ff`, local). Rien n'est poussé automatiquement.
7. **Onglet « Archive »** — historique des runs (date créé / terminé, besoin, statut, tokens).
   Clic sur un run → board read-only + PRD/architecture/epics/stories **de ce run**.

## 5. Équivalents CLI (`ai2b`)

Tout est aussi pilotable en terminal (utile pour scripter / déboguer) :

```bash
ai2b new <nom> [chemin]     # créer + activer un projet
ai2b run "<besoin>"         # lancer le pipeline sur le projet actif
ai2b pipeline               # état du pipeline
ai2b approve | revise "<r>" | stop
ai2b result                 # synthèse (branche, stories, diff, intégration)
ai2b collect [--clean]      # merge pipeline/<id> → base
ai2b status | up | down | restart [service] | logs <service>
```

## 6. Pousser le travail

`develop` du projet **piloté** reçoit le résultat après _collect_. Le push vers un remote
git reste **manuel** (aucune opération distante automatique) :

```bash
git -C ~/dev/<nom> push origin develop
```

## 7. Aller plus loin

- Exploitation du worker (dépannage pipeline) : [runbook worker](runbooks/worker-claude-agent.md).
- Web-app (config, build, fonctionnalités) : [runbook webui](runbooks/webui.md).
- Couche modèles (Ollama/LiteLLM) : [runbook phase 1](runbooks/phase1-litellm.md).
- Décisions d'architecture : [docs/adr/](adr/).
