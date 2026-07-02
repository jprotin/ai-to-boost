# ai-to-boost

**Assistant IA local-first orchestré** — une _tour de contrôle_ qui pilote des projets de
développement de bout en bout : de l'expression d'un besoin jusqu'au code, via un pipeline
multi-persona BMAD (analyst → PM → architecte → epics → implémentation) avec validation humaine
aux jalons.

ai-to-boost **pilote des projets externes** (il n'est jamais lui-même la cible). Tout tourne
en local : modèles via **Ollama** (GPU), Claude via le **forfait** (`claude -p`, jamais l'API),
RAG **Qdrant**, voix **Whisper**, orchestration **n8n**, et une **web-app Next.js** comme poste
de pilotage.

## Architecture (vue rapide)

| Couche         | Service                                 | Rôle                                        |
| -------------- | --------------------------------------- | ------------------------------------------- |
| Modèles locaux | `ollama` (GPU) + `litellm`              | inférence + gateway OpenAI-compat           |
| Claude         | `claude-bridge` / `claude-agent` (hôte) | texte (forfait) / agentique + pipeline BMAD |
| Entrées        | `whisper`, `n8n`, `telegram-poller`     | voix, flux, messagerie                      |
| RAG            | `qdrant`                                | base vectorielle (commune + par projet)     |
| Pilotage       | `webui` (Next.js) + CLI `ai2b`          | tour de contrôle web & terminal             |

## Démarrage rapide

```bash
cp .env.example .env          # renseigner les secrets (cf. guide)
ai2b up                       # démarre la stack (docker + services hôte)
ai2b status                   # vérifier
# Web-app : http://127.0.0.1:3001
```

Parcours complet (créer un projet → lancer un pipeline → relire → approuver → récupérer →
archive) et prérequis détaillés : **[guide de déploiement & d'utilisation](docs/guide-deploiement.md)**.

## Documentation

- **[Architecture d'ensemble](docs/architecture.md)** — services, ports, flux, état, sécurité
- **[Guide de déploiement & d'utilisation](docs/guide-deploiement.md)** — de l'install au parcours complet
- **[Variables d'environnement](docs/environment-variables.md)** — référence par service
- **[Dépannage](docs/troubleshooting.md)** — problèmes fréquents centralisés
- **[Décisions d'architecture (ADR)](docs/adr/)** — 0001 socle → 0008 persistance/archive pipelines
- **[Audits](docs/audits/)** — documentation, portabilité locale, cloud/SaaS
- **Runbooks** ([worker](docs/runbooks/worker-claude-agent.md), [webui](docs/runbooks/webui.md),
  [modèles/LiteLLM](docs/runbooks/phase1-litellm.md), [ai2b](docs/runbooks/ai2b.md), …)
- **[CHANGELOG](CHANGELOG.md)**

## Principes

- **Local-first** : données et modèles restent sur la machine.
- **Conforme CGU** : Claude uniquement via `claude -p` (forfait) ; jamais d'`ANTHROPIC_API_KEY`
  exportée. Cf. [ADR 0002](docs/adr/0002-litellm-modeles-locaux-uniquement.md).
- **GitFlow** : `main` (prod) ← `release/*`/`hotfix/*` ; `develop` ← `feature/*`.
