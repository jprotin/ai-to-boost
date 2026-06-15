# Runbook — Phase 2 : STT GPU (faster-whisper / speaches)

Service de transcription voix→texte, OpenAI-compatible, sur GPU.
Voir [ADR 0001](../adr/0001-architecture-assistant-ia-local-orchestre.md).

## Périmètre

- Image **speaches** (`ghcr.io/speaches-ai/speaches:latest-cuda`), service `whisper`.
- Endpoint OpenAI-compatible : `POST http://127.0.0.1:8000/v1/audio/transcriptions`.
- Modèle par défaut : `Systran/faster-whisper-medium` (FR), `float16`, device `cuda`.
- Appelé directement par n8n (Phase 3) — **pas** routé via LiteLLM.

## Compatibilité GPU Blackwell (sm_120)

Point dur de l'ADR : faster-whisper repose sur CTranslate2. Validé sur ce poste —
le GPU **sm_120** est bien utilisé (pic ~97 % GPU, modèle en VRAM) malgré la base
CUDA 12.6 de l'image (le driver 580 JIT-compile depuis le PTX au 1er appel).

- **VRAM** : medium ≈ 2,2 Go → co-résidence possible avec `gemma` (~7,5 Go) sur les 12 Go.
- **Latence** : ~2 s pour 10 s d'audio à chaud ; ~20 s au 1er appel après (re)démarrage
  (chargement modèle + JIT CUDA sm_120). Le modèle est déchargé après 300 s d'inactivité
  (`ttl`), d'où un cold-start occasionnel.

## Prérequis

- GPU dans Docker opérationnel : `nvidia-persistenced` actif (cf.
  [runbook Phase 0](phase0-socle.md)).
- Volume `whisper-cache` (cache modèles HuggingFace, persistant).

## Démarrage

```bash
docker compose up -d whisper
docker compose logs -f whisper   # "Application startup complete" + port 8000
```

## Téléchargement du modèle (une fois)

speaches ne pré-télécharge pas le modèle ; il faut l'installer une fois (persisté
dans le volume `whisper-cache`) :

```bash
curl -s -X POST "http://127.0.0.1:8000/v1/models/Systran/faster-whisper-medium"
curl -s http://127.0.0.1:8000/v1/models | grep faster-whisper-medium   # vérif présence
```

## Validation (critère de passage Phase 3)

```bash
# Extraire l'audio d'une vidéo/clip en wav 16 kHz mono
ffmpeg -y -i clip.mp4 -ar 16000 -ac 1 -vn /tmp/fr.wav

curl -s http://127.0.0.1:8000/v1/audio/transcriptions \
  -F file=@/tmp/fr.wav \
  -F model=Systran/faster-whisper-medium \
  -F language=fr
```

Doit renvoyer `{"text":"..."}` avec une transcription FR cohérente → Phase 2 validée.

## Dépannage

- **`Model '...' is not installed locally`** : lancer le `POST /v1/models/<id>` ci-dessus.
- **Perms / échec d'écriture du cache** : le volume est monté sur `/home/ubuntu/.cache`
  (user `ubuntu` uid 1000) ; ne pas remonter sur un sous-dossier root-owned.
- **Pas d'accélération GPU** : vérifier `nvidia-persistenced` et la section
  `deploy.resources.reservations.devices` du service ; `nvidia-smi` doit montrer le
  process speaches pendant un appel.
- **Cold-start ~20 s** : normal après (re)démarrage (JIT sm_120) ; à chaud ~2 s.

## Notes

- UI gradio désactivée (`ENABLE_UI=false`) + télémétrie coupée (`DO_NOT_TRACK`,
  `HF_HUB_DISABLE_TELEMETRY`) — cohérent local-first.
- Modèles plus précis possibles (ex. `deepdml/faster-whisper-large-v3-turbo-ct2`)
  au prix de plus de VRAM ; à arbitrer selon la co-résidence souhaitée.
