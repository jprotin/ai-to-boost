# ADR 0001 — Architecture d'un assistant IA local orchestré

- **Statut** : Accepté
- **Date** : 2026-06-12
- **Décideurs** : protin
- **Schéma de référence** : [`docs/assets/architecture-assistant-ia-local.svg`](../assets/architecture-assistant-ia-local.svg)

## Contexte

Mettre en place un assistant IA **local-first**, orchestré, exécuté sur la station de travail
(TUXEDO, kernel 6.17). L'assistant doit pouvoir être déclenché à distance (voix/texte via Telegram)
ou en local (CLI/micro), transcrire la voix, router vers des modèles (Claude API, modèles locaux,
Bedrock), exécuter des tâches (dev/IaC/docs, RAG), et restituer des livrables, un retour
Telegram et une veille classée.

### Contraintes matérielles (mesurées)

| Ressource     | Valeur                                                                      | Implication                                                            |
| ------------- | --------------------------------------------------------------------------- | ---------------------------------------------------------------------- |
| GPU           | RTX 5070 Ti **Laptop**, **12 Go VRAM**, Blackwell (sm_120)                  | **Facteur limitant** : STT + LLM local + embeddings partagent 12 Go    |
| Driver / CUDA | 580.126 / runtime CUDA 13                                                   | Compatible Blackwell ; `nvcc` absent (OK si images prébuildées cu128+) |
| CPU / RAM     | 24 threads / 62 Go (≈34 libre)                                              | Large : orchestration + embeddings CPU OK                              |
| Disque        | `/datadisk` ≈912 Go libre                                                   | Large : modèles, Qdrant, données                                       |
| Déjà présent  | docker 29.5, compose, python 3.13, pipx, ffmpeg, `lms` (LM Studio CLI), git | Socle correct                                                          |
| Manquant      | node/npm, uv, qdrant, n8n, litellm, (ollama non retenu)                     | À installer (services en conteneurs)                                   |

## Décision

Pile **en 6 couches** : Entrées → STT → Orchestration → Gateway modèles → Exécution → Sorties.

### Choix structurants

1. **Conteneurisation Docker Compose** pour n8n, LiteLLM, Qdrant (reproductible, isolé).
   **LM Studio reste natif** (déjà installé, gère son runtime GPU Blackwell) ;
   **faster-whisper** en service GPU dédié.
2. **LiteLLM = gateway unique** (API OpenAI-compatible) routant vers : API Claude, LM Studio local, Bedrock.
   Centralise clés, budgets, logs.
3. **Stratégie VRAM (12 Go)** : pas de co-résidence des gros modèles. Whisper `small/medium` (~1–2 Go),
   LM Studio en **load/unload à la demande** (`lms`), embeddings RAG sur **CPU** par défaut,
   n8n **séquence** pour éviter la contention.
4. **Sécurité accès distant** : bot Telegram avec **allowlist de chat IDs**, secrets en `.env`,
   webhook n8n derrière tunnel (pas d'exposition directe). Cohérent avec gitleaks/detect-secrets.
5. **RAG Qdrant exposé en MCP** → branché sur Claude Code. **BMAD-METHOD** articulé avec le
   `claude-framework` (v0.1.0).
6. **Hébergement de la doc/ADR dans ce repo** (`ai-to-boost`). Le projet `ai-to-boost` EST cet assistant.

### Composants par couche

| Couche        | Composant                                         | Rôle                                                |
| ------------- | ------------------------------------------------- | --------------------------------------------------- |
| Entrées       | Telegram / CLI-micro local                        | Déclenchement voix+texte (distant / sur place)      |
| STT           | faster-whisper (GPU)                              | Speech-to-text, exposé en API                       |
| Orchestration | n8n                                               | Routage, scheduling, tâches parallèles              |
| Gateway       | LiteLLM                                           | Gateway modèles unifiée (Claude / local / Bedrock)  |
| Exécution     | Claude Code + BMAD / LM Studio local / RAG Qdrant | Dev-IaC-docs / modèles locaux / base doc (MCP)      |
| Sorties       | Livrables / Retour Telegram / Veille + stats      | Code-sites-docs / réponse distante / veille classée |

## Plan de mise en place (phasé, ordonné par dépendances)

- **Phase 0 — Socle** : repo + bootstrap framework, réseau Docker, `.env`/secrets,
  `nvidia-container-toolkit` (à confirmer), node + uv. → base saine.
- **Phase 1 — Couche modèles (cœur GPU)** : LM Studio server + LiteLLM gateway.
  Valider routage Claude / local / Bedrock via un endpoint unique.
- **Phase 2 — STT** : faster-whisper en API GPU (point dur Blackwell). Valider transcription FR.
- **Phase 3 — Orchestrateur n8n** : déploiement + connexion LiteLLM & whisper + 1er workflow bout-en-bout.
- **Phase 4 — Entrées/Sorties** : bot Telegram (entrée vocale + retour) & CLI/micro local. Sécurité distant.
- **Phase 5 — RAG** : Qdrant + ingestion doc + serveur MCP + branchement Claude Code.
- **Phase 6 — Exécution & livrables** : Claude Code + BMAD, industrialisation livrables, veille classée.

Chaque phase = livrable + critère de validation avant la suivante.

## Conséquences

### Positives

- Pile modulaire, chaque couche testable indépendamment.
- Gateway unique → un seul point de config clés/budgets/logs.
- Local-first → confidentialité, coût maîtrisé, pas de dépendance réseau pour le cœur.

### Risques / points à valider

- **Blackwell sm_120** : support CTranslate2/faster-whisper (build cu128) + runtime GPU LM Studio (Phase 1/2).
- **`nvidia-container-toolkit`** installé ? (gate `--gpus` Docker) — Phase 0.
- **VRAM 12 Go** : contrainte maîtresse → dimensionnement des modèles.
- **Python 3.13** : libs ML parfois en retard → venv 3.11/3.12 via `uv` pour whisper.
- **Sécurité Telegram distant** : tunnel + allowlist + secrets.

## Alternatives écartées

- **Ollama** au lieu de LM Studio : LM Studio déjà installé (`lms`) et gère bien le load/unload GPU → pas de doublon.
- **Orchestration par scripts maison** au lieu de n8n : n8n apporte scheduling, UI, connecteurs (Telegram) prêts.
- **Tout natif (sans Docker)** : moins reproductible, conflits de versions Python ; Docker isole proprement.
