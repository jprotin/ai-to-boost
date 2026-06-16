#!/usr/bin/env bash
# ai-to-boost-init.sh — rend un projet pilotable par l'assistant ai-to-boost (Phase 6b.3b).
#
# Pose le marqueur .ai-to-boost/ (config + RAG par projet) que le worker agentique
# exige avant d'agir. Le projet cible est ainsi "enregistré" (opt-in explicite).
#
# Usage : ai-to-boost-init.sh [<chemin-projet>]   (défaut : répertoire courant)
set -euo pipefail

err() {
  echo "ai-to-boost-init: $1" >&2
  exit 1
}

PROJECT="${1:-$PWD}"
PROJECT="$(cd "$PROJECT" 2>/dev/null && pwd)" || PROJECT=""

if [ -z "$PROJECT" ] || [ ! -d "$PROJECT" ]; then
  err "projet introuvable : ${1:-$PWD}"
fi
if [ ! -d "$PROJECT/.git" ]; then
  err "pas un dépôt git : $PROJECT (lancer 'git init' d'abord)"
fi

# Refuse l'orchestrateur lui-même comme cible.
ORCH="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
if [ "$(realpath "$PROJECT")" = "$(realpath "$ORCH")" ]; then
  err "ai-to-boost ne peut pas se cibler lui-même"
fi

NAME="$(basename "$PROJECT")"
# Base branch : branche courante du projet (sinon main).
BASE="$(git -C "$PROJECT" symbolic-ref --short HEAD 2>/dev/null || echo main)"

MARK="$PROJECT/.ai-to-boost"
mkdir -p "$MARK/rag"

if [ -f "$MARK/config.json" ]; then
  echo "déjà initialisé : $MARK/config.json (mise à jour de base_branch=$BASE)"
fi

cat >"$MARK/config.json" <<JSON
{
  "name": "$NAME",
  "base_branch": "$BASE",
  "agent_enabled": true
}
JSON

cat >"$MARK/rag/README.md" <<'MD'
# RAG par projet

Doc spécifique à ce projet, indexée en plus du RAG commun d'ai-to-boost.
Déposer ici les `.md`/`.txt` propres au projet (cf. Phase 6b.3d).
MD

# Config privée : ne pas versionner le marqueur dans le projet cible.
GI="$PROJECT/.gitignore"
if ! { [ -f "$GI" ] && grep -qxF ".ai-to-boost/" "$GI"; }; then
  printf '\n# config privée ai-to-boost (orchestrateur)\n.ai-to-boost/\n' >>"$GI"
fi

echo "OK — projet '$NAME' initialisé (base_branch=$BASE)"
echo "  marqueur : $MARK/config.json"
echo "  RAG projet : $MARK/rag/"
