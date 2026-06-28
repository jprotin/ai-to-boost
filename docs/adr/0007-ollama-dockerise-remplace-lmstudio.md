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

- Service `ollama` (image **pinnée `ollama/ollama:0.30.11`** — 0.30+ requis pour `gemma4`,
  GPU via `deploy.resources`, `OLLAMA_KEEP_ALIVE`, `OLLAMA_CONTEXT_LENGTH=32768` pour les
  agents de code type KiloCode, volume `ollama-data`, healthcheck `ollama ps`).
- Service one-shot `ollama-init` : `ollama pull` idempotent des modèles, gate
  `service_completed_successfully` pour `litellm`.
- **Alias LiteLLM inchangés** — c'est le point clé : `local-gemma`, `local-qwen`,
  `local-embed` pointent désormais vers des modèles Ollama, donc **aucun changement** dans
  `claude_agent.py`, les workflows n8n et la webui.

| Alias LiteLLM | Cible Ollama       | VRAM @ ctx 32k (12 Go)                         |
| ------------- | ------------------ | ---------------------------------------------- |
| `local-gemma` | `gemma4:e4b`       | ~3,3 Go (défaut planning, non bavard)          |
| `local-qwen`  | `qwen3.5:9b`       | ~6,7 Go (full-GPU ; reasoner, voir ci-dessous) |
| `local-embed` | `nomic-embed-text` | ~0,6 Go, **768 dims** (compat Qdrant existant) |

> **qwen3.5:9b est un modèle à raisonnement bavard et de longueur variable.** Via /v1, la
> réflexion est comptée dans `max_tokens` puis retirée du `content` final ; un budget trop
> bas (le défaut historique `4000` du worker) renvoie un `content` vide de façon
> intermittente. Mitigation : `_llm_local` passe à **`max_tokens=16000`**. `gemma4:e4b`
> n'a pas ce comportement.

Le routage Claude (forfait via Claude Code / `claude -p`) reste **inchangé** : Claude n'est
toujours pas routé par LiteLLM (ADR 0002 toujours valable sur ce point).

## Bench de validation (2026-06-28)

- GPU **RTX 5070 Ti Laptop, 12 Go, Blackwell sm_120**, driver 580 / runtime cuda_v13 :
  Ollama détecte le GPU en **CUDA natif** (`compute=12.0`), pas de fallback CPU.
- `nvidia-container-toolkit` 1.19.1 + runtime `nvidia`/CDI déjà présents → `--gpus all` OK.
- gemma3n:e4b ≈ **84 tok/s** (bench initial).
- Modèles finaux à contexte 32k : `gemma4:e4b` ~3,3 Go ; `qwen3.5:9b` ~6,7 Go (7,7 Go VRAM
  totale, 100% GPU) ; routage des 3 alias via LiteLLM `:4000` validé (qwen testé 3× pour
  la variabilité du raisonnement, contenu non vide à `max_tokens=16000`).

## Conséquences

### Positives

- Couche modèles **100% dans compose**, pilotable par `ai2b up/down` (plus de processus
  natif à démarrer à la main, plus de `host.docker.internal` pour les modèles).
- Open source (MIT), CLI/API-first, `OLLAMA_KEEP_ALIVE` gère le load/unload VRAM.
- Embeddings 768 dims → collections Qdrant RAG existantes réutilisées sans réindexation.

### Négatives / points d'attention

- **Contrainte VRAM 12 Go inchangée** : pas de modèle > ~10 Go full-GPU ; qwen 27B écarté
  au profit de `qwen3.5:9b`. `gemma4:e4b` reste le modèle de planning par défaut.
- **qwen3.5:9b raisonne** → latence accrue même sur requêtes triviales (~2000 tokens de
  réflexion cachés) et budget `max_tokens` à voir large (16000). Non bloquant pour le
  planning ; pour du chat instantané, préférer `gemma4:e4b`.
- Premier `ai2b up` télécharge ~10 Go de modèles (puis persistés dans le volume).
- Plus de GUI d'exploration de modèles (compromis assumé : usage serveur/headless).

## Alternatives écartées

- **Garder LM Studio** : ne fonctionne plus, et reste natif/GUI (non orchestrable).
- **qwen3 27B** comme `local-qwen` : déborde des 12 Go → offload CPU, trop lent.
- **Ollama natif (hors compose)** comme LM Studio : perd le bénéfice principal
  (pilotage par compose/`ai2b`) ; le GPU passe déjà très bien en conteneur ici.
