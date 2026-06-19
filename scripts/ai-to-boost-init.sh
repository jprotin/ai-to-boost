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

# BMAD commun : même source que le worker agentique (AGENT_BMAD_DIR).
BMAD_SHARED="${AGENT_BMAD_DIR:-$HOME/agent-workspace/.bmad-shared}"

# expose_bmad — rend BMAD utilisable EN INTERACTIF dans le projet (persistant), en
# miroir de ce que le worker fait temporairement dans son worktree (_inject_bmad) :
#   - _bmad/                -> partagé (config + agents/workflows, dont _config/bmad-help.csv)
#   - .claude/skills/bmad-* -> partagé (skills découvrables : /bmad-help, /bmad-prd, …)
# Les artefacts restent locaux (_bmad-output/ du projet). Symlinks => jamais committés.
expose_bmad() {
  local skills_src="$BMAD_SHARED/.claude/skills"
  if [ ! -d "$BMAD_SHARED/_bmad" ] || [ ! -d "$skills_src" ]; then
    echo "  BMAD : partagé introuvable ($BMAD_SHARED) — skills interactifs non exposés"
    return 0
  fi

  # _bmad partagé (config/agents/workflows) ; les sorties restent dans $PROJECT/_bmad-output
  ln -sfn "$BMAD_SHARED/_bmad" "$PROJECT/_bmad"

  # Skills découvrables par Claude Code en session interactive (per-skill : n'écrase
  # pas d'éventuels skills propres au projet).
  mkdir -p "$PROJECT/.claude/skills"
  local n=0 d
  for d in "$skills_src"/bmad-*/; do
    [ -d "$d" ] || continue
    ln -sfn "${d%/}" "$PROJECT/.claude/skills/$(basename "$d")"
    n=$((n + 1))
  done

  echo "  BMAD : $n skills exposés (/bmad-help dispo en interactif) -> $BMAD_SHARED"
}

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

# Expose BMAD en interactif (symlinks vers le partagé).
expose_bmad

# Config privée : ne pas versionner le marqueur, l'état UI bmad-ui, ni les symlinks BMAD
# (BMAD est partagé/mis à jour centralement, jamais committé dans le projet cible).
# Idempotent par pattern : un projet déjà initialisé reçoit les patterns manquants
# (ex. ceux ajoutés après une mise à jour de ce script).
GI="$PROJECT/.gitignore"
gi_has() { [ -f "$GI" ] && grep -qxF "$1" "$GI"; }
if ! gi_has ".ai-to-boost/"; then
  printf '\n# config privée ai-to-boost (orchestrateur)\n' >>"$GI"
fi
for pat in ".ai-to-boost/" ".bmad-ui-state/" "/_bmad" "/.claude/skills/bmad-*"; do
  gi_has "$pat" || printf '%s\n' "$pat" >>"$GI"
done

echo "OK — projet '$NAME' initialisé (base_branch=$BASE)"
echo "  marqueur : $MARK/config.json"
echo "  RAG projet : $MARK/rag/"
