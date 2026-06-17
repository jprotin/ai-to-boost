# Runbook — Phase 0 : socle de l'assistant IA local

Mise en place de la base avant tout déploiement de service. Voir
[ADR 0001](../adr/0001-architecture-assistant-ia-local-orchestre.md).

## Prérequis machine (vérifiés le 2026-06-12)

- GPU RTX 5070 Ti Laptop, 12 Go VRAM, Blackwell — driver 580.126 / CUDA 13.
- Docker 29.5 + compose, `nvidia-container-toolkit` 1.19.1 (runtime `nvidia` présent).
- `lms` (LM Studio CLI), python 3.13, pipx, ffmpeg, `uv` 0.11.

## GPU dans Docker — dépendance à nvidia-persistenced

Le `nvidia-container-toolkit` (mode legacy) monte le socket
`/run/nvidia-persistenced/socket`. Si le daemon `nvidia-persistenced` est arrêté
(fréquent sur laptop après suspension/reprise), `docker run --gpus all` échoue avec :

```
failed to fulfil mount request: open /run/nvidia-persistenced/socket: no such file or directory
```

### Fix immédiat

```bash
sudo systemctl daemon-reload
sudo systemctl start nvidia-persistenced
```

### Vérification

```bash
docker run --rm --gpus all nvidia/cuda:12.8.0-base-ubuntu24.04 nvidia-smi
```

### Persistance (laptop : à durcir)

Le service est `static` et retombe après certaines suspensions. À traiter en
hardening : s'assurer qu'il redémarre au boot / à la reprise (drop-in systemd ou
activation de la persistence mode au démarrage du driver).

## Réseau & secrets

- Réseau Docker partagé : `ai-assistant-net` (défini dans `compose.yaml`).
- Secrets : `.env` (gitignoré), gabarit dans `.env.example`.

## Outils

- `uv` : venv Python (3.11/3.12) pour faster-whisper (évite les limites de python 3.13).
- node/nvm : pour serveurs MCP / outillage JS (n8n tourne en conteneur).
