#!/usr/bin/env bash
# bmad-start — lance l'instance unique de bmad-ui, focalisée sur le projet courant.
#
# bmad-ui calcule projectRoot = parent de son dossier `_bmad-ui` (aucun override env),
# et lit plusieurs chemins relatifs à projectRoot. On installe bmad-ui une fois dans
# GLOBAL/_bmad-ui (projectRoot = GLOBAL) et on repointe par symlink, vers le projet
# courant, TOUS les chemins lus :
#   contenu  : GLOBAL/_bmad-output, GLOBAL/docs, GLOBAL/README.md
#   état UI  : GLOBAL/_bmad-ui/agents, GLOBAL/_bmad-ui/artifacts (isolés par projet)
# Une seule instance / un port → un projet à la fois (bascule instantanée).
#
# Usage : se placer dans un projet (avec _bmad-output/ et/ou docs/) puis : bmad-start
set -euo pipefail

GLOBAL="${BMAD_UI_GLOBAL:-$HOME/.bmad-ui-global}"
APP="$GLOBAL/_bmad-ui"
PORT="${BMAD_UI_PORT:-5173}"

die() {
  printf 'bmad-start: %s\n' "$1" >&2
  exit 1
}

[ -d "$APP" ] || die "bmad-ui non installé ($APP) — lance scripts/bmad-ui-setup.sh"

PROJECT="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
if [ ! -d "$PROJECT/_bmad-output" ] && [ ! -d "$PROJECT/docs" ]; then
  die "ni _bmad-output/ ni docs/ dans $PROJECT (rien à afficher)"
fi

# symlink si la cible existe : link <cible_projet> <chemin_global>
link_if() {
  if [ -e "$1" ]; then ln -sfn "$1" "$2"; fi
}

# --- contenu (lu sous projectRoot = GLOBAL) ---
link_if "$PROJECT/_bmad-output" "$GLOBAL/_bmad-output"
link_if "$PROJECT/docs" "$GLOBAL/docs"
link_if "$PROJECT/README.md" "$GLOBAL/README.md"

# --- état UI isolé par projet, initialisé depuis le gabarit ---
STATE="$PROJECT/.bmad-ui-state"
if [ ! -d "$STATE" ]; then
  mkdir -p "$STATE"
  cp -a "$GLOBAL/.state-template/." "$STATE/" 2>/dev/null || true
fi
mkdir -p "$STATE/agents" "$STATE/artifacts"
ln -sfn "$STATE/agents" "$APP/agents"
ln -sfn "$STATE/artifacts" "$APP/artifacts"

# --- une seule instance : stoppe l'éventuelle précédente ---
if command -v lsof >/dev/null 2>&1; then
  lsof -ti "tcp:$PORT" 2>/dev/null | xargs -r kill 2>/dev/null || true
  sleep 1
fi

printf 'bmad-start: projet "%s" -> http://localhost:%s\n' "$(basename "$PROJECT")" "$PORT"
export NVM_DIR="$HOME/.nvm"
if [ -s "$NVM_DIR/nvm.sh" ]; then
  # shellcheck disable=SC1091
  . "$NVM_DIR/nvm.sh"
fi
cd "$APP"
exec corepack pnpm dev
