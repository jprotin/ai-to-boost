#!/usr/bin/env bash
# bmad-ui-setup.sh — installe bmad-ui UNE seule fois dans un dossier centralisé
# (~/.bmad-ui-global) et déploie la commande globale `bmad-start`.
#
# bmad-ui dérive son projectRoot du parent de son dossier `_bmad-ui` (aucun override
# par variable d'env) : on l'installe donc dans GLOBAL/_bmad-ui, et `bmad-start`
# repointe par symlink GLOBAL/_bmad-output vers le projet courant.
#
# Usage : scripts/bmad-ui-setup.sh
set -euo pipefail

GLOBAL="${BMAD_UI_GLOBAL:-$HOME/.bmad-ui-global}"
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

export NVM_DIR="$HOME/.nvm"
if [ -s "$NVM_DIR/nvm.sh" ]; then
  # shellcheck disable=SC1091
  . "$NVM_DIR/nvm.sh"
fi

echo "[1/4] Installation de bmad-ui dans $GLOBAL (npx bmad-method-ui install)…"
mkdir -p "$GLOBAL"
(cd "$GLOBAL" && npx -y bmad-method-ui install)

echo "[2/4] Dépendances (corepack pnpm install)…"
corepack enable pnpm 2>/dev/null || true
# évite le téléchargement des navigateurs Playwright (devDep, inutile pour servir l'UI)
export PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=1
(cd "$GLOBAL/_bmad-ui" && corepack pnpm install)

echo "[3/4] Capture du gabarit d'état UI (.state-template)…"
mkdir -p "$GLOBAL/.state-template/agents" "$GLOBAL/.state-template/artifacts"
if [ -d "$GLOBAL/_bmad-ui/artifacts" ]; then
  cp -a "$GLOBAL/_bmad-ui/artifacts/." "$GLOBAL/.state-template/artifacts/" 2>/dev/null || true
fi
if [ -d "$GLOBAL/_bmad-ui/agents" ]; then
  cp -a "$GLOBAL/_bmad-ui/agents/." "$GLOBAL/.state-template/agents/" 2>/dev/null || true
fi

echo "[4/4] Déploiement de la commande bmad-start…"
mkdir -p "$HOME/.local/bin"
chmod +x "$REPO/scripts/bmad-start.sh"
ln -sfn "$REPO/scripts/bmad-start.sh" "$HOME/.local/bin/bmad-start"

echo "OK — depuis un projet contenant _bmad-output/, tape : bmad-start"
