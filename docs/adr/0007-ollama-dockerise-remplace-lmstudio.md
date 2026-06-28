# ADR 0007 — Ollama dockerisé (GPU) remplace LM Studio comme serveur de modèles locaux

- **Statut** : Accepté
- **Date** : 2026-06-28
- **Décideurs** : protin
- **Amende** : [ADR 0001](0001-architecture-assistant-ia-local-orchestre.md) (qui écartait
  Ollama au profit de LM Studio) et [ADR 0002](0002-litellm-modeles-locaux-uniquement.md)
  (LiteLLM = local only, cible LM Studio).

## Contexte

L'ADR 0001 retenait **LM Studio natif** (hors compose, joint via `host.docker.internal`)
comme serveur des modèles locaux, et écartait Ollama explicitement (« LM Studio déjà
installé, pas de doublon »). Deux faits invalident ce choix :

1. **LM Studio ne fonctionne plus** sur la machine et est désinstallé. Il n'y a donc plus
   de fournisseur de modèles locaux opérationnel.
2. **Cap « tour de contrôle / tout-orchestré »** (ADR 0005/0006) : le projet pilote ses
   services via `ai2b` + compose. Une appli GUI native lancée à la main est une friction
   (cf. feedback « UX trop manuelle ») incompatible avec une couche modèles pilotable
   programmatiquement.

## Décision

**Ollama, dockerisé dans la stack compose, avec passthrough GPU**, devient le serveur
unique des modèles locaux. LiteLLM le route via `http://ollama:11434/v1` (OpenAI-compatible).

- Service `ollama` (image `ollama/ollama`, GPU via `deploy.resources`, `OLLAMA_KEEP_ALIVE`,
  volume `ollama-data`, healthcheck `ollama ps`).
- Service one-shot `ollama-init` : `ollama pull` idempotent des modèles, gate
  `service_completed_successfully` pour `litellm`.
- **Alias LiteLLM inchangés** — c'est le point clé : `local-gemma`, `local-qwen`,
  `local-embed` pointent désormais vers des modèles Ollama, donc **aucun changement** dans
  `claude_agent.py`, les workflows n8n et la webui.

| Alias LiteLLM | Cible Ollama       | VRAM (12 Go)                                   |
| ------------- | ------------------ | ---------------------------------------------- |
| `local-gemma` | `gemma3n:e4b`      | ~8,3 Go (défaut planning)                      |
| `local-qwen`  | `qwen3:8b`         | ~6,0 Go (full-GPU, réellement utilisable)      |
| `local-embed` | `nomic-embed-text` | ~0,6 Go, **768 dims** (compat Qdrant existant) |

Le routage Claude (forfait via Claude Code / `claude -p`) reste **inchangé** : Claude n'est
toujours pas routé par LiteLLM (ADR 0002 toujours valable sur ce point).

## Bench de validation (2026-06-28)

- GPU **RTX 5070 Ti Laptop, 12 Go, Blackwell sm_120**, driver 580 / runtime cuda_v13 :
  Ollama 0.18.2 détecte le GPU en **CUDA natif** (`compute=12.0`), pas de fallback CPU.
- `nvidia-container-toolkit` 1.19.1 + runtime `nvidia`/CDI déjà présents → `--gpus all` OK.
- gemma3n:e4b ≈ **84 tok/s** ; gemma + embed tiennent **simultanément** (~8,5 Go) ;
  qwen3:8b seul à 6,0 Go, 100% GPU.
- Routage des 3 alias via LiteLLM `:4000` validé bout-en-bout.

## Conséquences

### Positives

- Couche modèles **100% dans compose**, pilotable par `ai2b up/down` (plus de processus
  natif à démarrer à la main, plus de `host.docker.internal` pour les modèles).
- Open source (MIT), CLI/API-first, `OLLAMA_KEEP_ALIVE` gère le load/unload VRAM.
- Embeddings 768 dims → collections Qdrant RAG existantes réutilisées sans réindexation.

### Négatives / points d'attention

- **Contrainte VRAM 12 Go inchangée** : pas de modèle > ~10 Go full-GPU ; qwen 27B écarté
  au profit de qwen3:8b. gemma reste le modèle de planning par défaut.
- Premier `ai2b up` télécharge ~13 Go de modèles (puis persistés dans le volume).
- Plus de GUI d'exploration de modèles (compromis assumé : usage serveur/headless).

## Alternatives écartées

- **Garder LM Studio** : ne fonctionne plus, et reste natif/GUI (non orchestrable).
- **qwen3 27B** comme `local-qwen` : déborde des 12 Go → offload CPU, trop lent.
- **Ollama natif (hors compose)** comme LM Studio : perd le bénéfice principal
  (pilotage par compose/`ai2b`) ; le GPU passe déjà très bien en conteneur ici.
