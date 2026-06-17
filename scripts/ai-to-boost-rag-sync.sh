#!/usr/bin/env bash
# ai-to-boost-rag-sync.sh — indexe le RAG d'un projet dans sa collection dédiée
# Qdrant `proj-<name>` (Phase 6b.3d). Le RAG commun (`knowledge`) s'indexe, lui, via
# `uv run services/rag/ingest.py` à la racine d'ai-to-boost.
#
# Usage : ai-to-boost-rag-sync.sh [<projet>]   (défaut : répertoire courant)
set -euo pipefail

err() {
  echo "ai-to-boost-rag-sync: $1" >&2
  exit 1
}

PROJECT="${1:-$PWD}"
PROJECT="$(cd "$PROJECT" 2>/dev/null && pwd)" || PROJECT=""
if [ -z "$PROJECT" ]; then
  err "projet introuvable : ${1:-$PWD}"
fi

CFG="$PROJECT/.ai-to-boost/config.json"
if [ ! -f "$CFG" ]; then
  err "projet non initialisé (pas de $CFG) — lancer ai-to-boost-init.sh"
fi
RAGDIR="$PROJECT/.ai-to-boost/rag"
if [ ! -d "$RAGDIR" ]; then
  err "dossier RAG absent : $RAGDIR"
fi

NAME="$(python3 -c "import json; print(json.load(open('$CFG'))['name'])")"
# collection dédiée, nom assaini
SLUG="$(printf '%s' "$NAME" | tr '[:upper:]' '[:lower:]' | tr -c 'a-z0-9_-' '-')"
COLL="proj-$SLUG"

ORCH="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export PATH="$HOME/.local/bin:$PATH"

echo "Indexation RAG projet '$NAME' -> collection '$COLL' (source: $RAGDIR)"
RAG_COLLECTION="$COLL" \
  KNOWLEDGE_DIR="$RAGDIR" \
  QDRANT_URL="${QDRANT_URL:-http://127.0.0.1:6333}" \
  uv run "$ORCH/services/rag/ingest.py"
