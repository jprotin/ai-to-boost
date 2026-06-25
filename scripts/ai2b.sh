#!/usr/bin/env bash
# shellcheck disable=SC2016  # filtres jq volontairement en quotes simples (--arg)
# ai2b — tour de contrôle ai-to-boost.
#
# Centralise la gestion de l'orchestrateur et des projets qu'il pilote :
#   - cycle de vie projet : new / init / switch / ls / current / rm
#   - services           : status / up / down / restart / logs
#   - vie du projet actif : build / code / job / ui
#
# Le « projet actif » remplace l'édition manuelle de AGENT_DEFAULT_REPO + restart.
# Registre : ${XDG_CONFIG_HOME:-~/.config}/ai-to-boost/projects.json
#
# Usage : ai2b <commande> [args]   (ai2b help)
set -euo pipefail

# --- Emplacements --------------------------------------------------------------
ORCH="$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")/.." && pwd)"
ENV_FILE="$ORCH/.env"
COMPOSE="$ORCH/compose.yaml"
INIT_SCRIPT="$ORCH/scripts/ai-to-boost-init.sh"
BMAD_START="$ORCH/scripts/bmad-start.sh"

CONFIG_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/ai-to-boost"
REGISTRY="$CONFIG_DIR/projects.json"
PROJECTS_DIR="${AI2B_PROJECTS_DIR:-$HOME/dev}"

# Services systemd user (hôte, forfait) vs services docker compose.
SYSTEMD_SERVICES=(claude-bridge claude-agent)

# --- Sorties -------------------------------------------------------------------
c_reset=$'\033[0m'
c_bold=$'\033[1m'
c_grn=$'\033[32m'
c_red=$'\033[31m'
c_dim=$'\033[2m'
info() { printf '%s\n' "$*"; }
ok() { printf '%s✔%s %s\n' "$c_grn" "$c_reset" "$*"; }
warn() { printf '%s!%s %s\n' "$c_red" "$c_reset" "$*" >&2; }
die() {
  printf '%sai2b: %s%s\n' "$c_red" "$*" "$c_reset" >&2
  exit 1
}

need() { command -v "$1" >/dev/null 2>&1 || die "dépendance manquante : $1"; }

# --- Registre (jq) -------------------------------------------------------------
registry_init() {
  mkdir -p "$CONFIG_DIR"
  [ -f "$REGISTRY" ] || printf '{"active":null,"projects":{}}\n' >"$REGISTRY"
}
reg() { jq "$@" "$REGISTRY"; }
reg_write() {
  local tmp
  tmp="$(mktemp)"
  jq "$@" "$REGISTRY" >"$tmp" && mv "$tmp" "$REGISTRY"
}
proj_path() { reg -r --arg n "$1" '.projects[$n].path // empty'; }
proj_base() { reg -r --arg n "$1" '.projects[$n].base_branch // empty'; }
active_name() { reg -r '.active // empty'; }
proj_exists() { [ -n "$(proj_path "$1")" ]; }

require_active() {
  local n
  n="$(active_name)"
  [ -n "$n" ] || die "aucun projet actif (ai2b switch <nom> ou ai2b new <nom>)"
  printf '%s' "$n"
}

# --- .env / worker -------------------------------------------------------------
env_get() { grep -E "^$1=" "$ENV_FILE" 2>/dev/null | head -1 | cut -d= -f2- || true; }

set_default_repo() { # bascule AGENT_DEFAULT_REPO + restart worker
  local path="$1"
  if grep -qE '^AGENT_DEFAULT_REPO=' "$ENV_FILE"; then
    sed -i -E "s|^AGENT_DEFAULT_REPO=.*|AGENT_DEFAULT_REPO=${path}|" "$ENV_FILE"
  else
    printf 'AGENT_DEFAULT_REPO=%s\n' "$path" >>"$ENV_FILE"
  fi
  if systemctl --user is-active --quiet claude-agent; then
    systemctl --user restart claude-agent && ok "worker reciblé sur $path"
  else
    info "  (worker arrêté — ciblage pris au prochain démarrage)"
  fi
}

dc() { docker compose -f "$COMPOSE" "$@"; }

# Mappe un alias de service vers son unité systemd, sinon chaîne vide.
systemd_unit() {
  case "$1" in
    worker | agent | claude-agent) printf 'claude-agent' ;;
    bridge | claude-bridge) printf 'claude-bridge' ;;
    *) printf '' ;;
  esac
}

# ==============================================================================
# Commandes — cycle de vie projet
# ==============================================================================
cmd_new() {
  need git
  need jq
  local name="${1:-}" path="${2:-}"
  [ -n "$name" ] || die "usage: ai2b new <nom> [chemin]"
  proj_exists "$name" && die "projet déjà enregistré : $name (ai2b switch $name)"
  path="${path:-$PROJECTS_DIR/$name}"
  path="$(readlink -f "$path" 2>/dev/null || printf '%s' "$path")"
  [ "$path" = "$ORCH" ] && die "ai-to-boost ne peut pas se piloter lui-même"
  if [ -e "$path" ] && [ -n "$(ls -A "$path" 2>/dev/null)" ]; then
    die "$path existe et n'est pas vide (utilise: ai2b init $path)"
  fi

  info "${c_bold}Création du projet '$name'${c_reset} → $path"
  mkdir -p "$path"
  git -C "$path" init -q
  printf '# %s\n' "$name" >"$path/README.md"
  git -C "$path" add README.md
  git -C "$path" commit -q -m "chore: init projet $name"
  git -C "$path" branch -M main
  (cd "$path" && git flow init -d -f >/dev/null 2>&1) || die "git flow init a échoué"
  ok "GitFlow initialisé (main + develop)"

  "$INIT_SCRIPT" "$path" # marqueur + RAG + BMAD (base_branch=develop)
  # Versionne le .gitignore posé par l'init (évite le conflit de checkout des branches agent).
  if [ -f "$path/.gitignore" ]; then
    git -C "$path" add .gitignore
    git -C "$path" commit -q -m "chore: .gitignore ai-to-boost" || true
  fi

  registry_init
  reg_write --arg n "$name" --arg p "$path" --arg b "develop" --arg t "$(date -Iseconds)" \
    '.projects[$n]={path:$p,base_branch:$b,created:$t} | .active=$n'
  ok "projet '$name' enregistré et activé"
  set_default_repo "$path"
}

cmd_init() {
  need git
  need jq
  local path="${1:-$PWD}"
  path="$(readlink -f "$path" 2>/dev/null || printf '%s' "$path")"
  [ -d "$path/.git" ] || die "pas un dépôt git : $path (ai2b new <nom> pour en créer un)"
  [ "$path" = "$ORCH" ] && die "ai-to-boost ne peut pas se piloter lui-même"
  local name
  name="$(basename "$path")"

  "$INIT_SCRIPT" "$path"
  local base
  base="$(git -C "$path" symbolic-ref --short HEAD 2>/dev/null || echo main)"
  registry_init
  reg_write --arg n "$name" --arg p "$path" --arg b "$base" --arg t "$(date -Iseconds)" \
    '.projects[$n]={path:$p,base_branch:$b,created:$t} | .active=$n'
  ok "projet existant '$name' enregistré et activé (base=$base)"
  set_default_repo "$path"
}

cmd_switch() {
  need jq
  local name="${1:-}"
  [ -n "$name" ] || die "usage: ai2b switch <nom>"
  proj_exists "$name" || die "projet inconnu : $name (ai2b ls)"
  local path
  path="$(proj_path "$name")"
  [ -d "$path" ] || warn "attention : $path est introuvable sur le disque"
  reg_write --arg n "$name" '.active=$n'
  ok "projet actif → $name"
  set_default_repo "$path"
}

cmd_ls() {
  need jq
  registry_init
  local active
  active="$(active_name)"
  local any=0
  while IFS=$'\t' read -r n p b; do
    any=1
    local mark="  " state="$c_grn●$c_reset"
    [ "$n" = "$active" ] && mark="${c_grn}▶${c_reset} "
    [ -d "$p" ] || state="$c_red✕$c_reset"
    printf '%s%s%-18s%s %s %s[%s]%s %s%s%s\n' \
      "$mark" "$c_bold" "$n" "$c_reset" "$state" "$c_dim" "$b" "$c_reset" "$c_dim" "$p" "$c_reset"
  done < <(reg -r '.projects | to_entries[] | [.key, .value.path, .value.base_branch] | @tsv')
  [ "$any" = 1 ] || info "aucun projet (ai2b new <nom>)"
}

cmd_current() {
  need jq
  registry_init
  local n
  n="$(active_name)"
  [ -n "$n" ] || {
    info "aucun projet actif"
    return 0
  }
  printf '%s  %s%s%s\n' "$n" "$c_dim" "$(proj_path "$n")" "$c_reset"
}

cmd_rm() {
  need jq
  registry_init
  local name="" purge=0
  for a in "$@"; do
    case "$a" in
      --purge) purge=1 ;;
      *) name="$a" ;;
    esac
  done
  [ -n "$name" ] || die "usage: ai2b rm <nom> [--purge]"
  proj_exists "$name" || die "projet inconnu : $name"
  local path
  path="$(proj_path "$name")"

  if [ "$purge" = 1 ]; then
    printf '%sSupprimer le RÉPERTOIRE %s ? [y/N] %s' "$c_red" "$path" "$c_reset"
    read -r ans
    [ "$ans" = "y" ] || [ "$ans" = "Y" ] || die "annulé"
    if [ -z "$path" ] || [ "$path" = "/" ] || [ "$path" = "$HOME" ]; then
      die "chemin refusé : $path"
    fi
    rm -rf -- "$path" && ok "répertoire supprimé : $path"
  fi
  reg_write --arg n "$name" 'del(.projects[$n]) | (if .active==$n then .active=null else . end)'
  ok "projet '$name' retiré du registre"
  if [ -z "$(active_name)" ]; then info "  (plus de projet actif)"; fi
}

# ==============================================================================
# Commandes — services
# ==============================================================================
cmd_status() {
  need curl
  info "${c_bold}Services docker${c_reset}"
  dc ps --format "  {{.Service}}\t{{.Status}}" 2>/dev/null || warn "docker compose indisponible"
  info ""
  info "${c_bold}Services hôte (systemd user)${c_reset}"
  local u
  for u in "${SYSTEMD_SERVICES[@]}"; do
    printf '  %-16s %s\n' "$u" "$(systemctl --user is-active "$u" 2>/dev/null || echo inactive)"
  done
  printf '  %-16s %s\n' "bridge :8088" "$(curl -s --max-time 3 localhost:8088/health || echo '(KO)')"
  printf '  %-16s %s\n' "worker :8089" "$(curl -s --max-time 3 localhost:8089/health || echo '(KO)')"
  info ""
  info "${c_bold}Projet actif${c_reset}"
  printf '  '
  cmd_current
}

cmd_up() {
  info "Démarrage docker…"
  dc up -d
  systemctl --user start "${SYSTEMD_SERVICES[@]}" && ok "services hôte démarrés"
}

cmd_down() {
  systemctl --user stop "${SYSTEMD_SERVICES[@]}" 2>/dev/null || true
  dc down && ok "stack arrêtée"
}

cmd_restart() {
  local svc="${1:-}"
  if [ -z "$svc" ]; then
    dc restart
    systemctl --user restart "${SYSTEMD_SERVICES[@]}" && ok "tout redémarré"
    return
  fi
  local unit
  unit="$(systemd_unit "$svc")"
  if [ -n "$unit" ]; then
    systemctl --user restart "$unit" && ok "$unit redémarré"
  else
    dc restart "$svc" && ok "$svc redémarré"
  fi
}

cmd_logs() {
  local svc="${1:-}"
  [ -n "$svc" ] || die "usage: ai2b logs <service>"
  local unit
  unit="$(systemd_unit "$svc")"
  if [ -n "$unit" ]; then
    journalctl --user -u "$unit" -n 80 -f
  else
    dc logs --tail 80 -f "$svc"
  fi
}

# ==============================================================================
# Commandes — vie du projet actif
# ==============================================================================
_post_job() { # <mode> <spec...>
  need curl
  need jq
  local mode="$1"
  shift
  local spec="$*"
  [ -n "$spec" ] || die "usage: ai2b ${mode/file/code} \"<spec>\""
  local name path port token
  name="$(require_active)"
  path="$(proj_path "$name")"
  port="$(env_get AGENT_PORT)"
  port="${port:-8089}"
  token="$(env_get AGENT_TOKEN)"
  [ -n "$token" ] || die "AGENT_TOKEN absent de $ENV_FILE"

  local body
  body="$(jq -nc --arg p "$spec" --arg r "$path" --arg m "$mode" \
    '{prompt:$p, repo:$r, mode:$m}')"
  local resp
  resp="$(curl -s --max-time 10 -X POST "http://localhost:$port/jobs" \
    -H "Authorization: Bearer $token" -H "Content-Type: application/json" -d "$body")" ||
    die "worker injoignable (:$port)"
  local job
  job="$(printf '%s' "$resp" | jq -r '.job_id // empty')"
  [ -n "$job" ] || die "worker a refusé : $resp"
  ok "tâche ${c_bold}$job${c_reset} acceptée sur '$name' (mode=$mode)"
  info "  suivi : ai2b job $job   |   résultat : branche agent/$job"
}

cmd_build() { _post_job build "$@"; } # Bash autorisé (garde-fou actif)
cmd_code() { _post_job file "$@"; }   # édition de fichiers

cmd_job() {
  need curl
  need jq
  local id="${1:-}"
  [ -n "$id" ] || die "usage: ai2b job <id>"
  local port token
  port="$(env_get AGENT_PORT)"
  port="${port:-8089}"
  token="$(env_get AGENT_TOKEN)"
  [ -n "$token" ] || die "AGENT_TOKEN absent de $ENV_FILE"
  curl -s --max-time 5 -H "Authorization: Bearer $token" "http://localhost:$port/jobs/$id" | jq . ||
    die "worker injoignable"
}

cmd_ui() {
  local force_project=0
  [ "${1:-}" = "--project" ] && force_project=1
  local name path target wt
  name="$(require_active)"
  path="$(proj_path "$name")"
  [ -d "$path" ] || die "répertoire introuvable : $path"
  target="$path"
  # Par défaut, si un pipeline a un worktree vivant (board live pendant le run, ou
  # résultat conservé à 'done'), on l'affiche plutôt que la racine projet (sur develop,
  # vide). '--project' force la racine.
  if [ "$force_project" = 0 ]; then
    wt="$(_pipe_field '.worktree')" || wt=""
    # Même critère que bmad-start (_bmad-output/ OU docs/) : le worktree a docs/ dès le
    # PRD, et _bmad-output/ à partir des epics.
    if [ -n "$wt" ] && { [ -d "$wt/_bmad-output" ] || [ -d "$wt/docs" ]; }; then
      target="$wt"
      info "  ${c_dim}board du pipeline $(_pipe_field '.pipeline_id') (worktree) — 'ai2b ui --project' pour le repo${c_reset}"
    fi
  fi
  (cd "$target" && exec "$BMAD_START")
}

# ==============================================================================
# Commandes — pipeline BMAD (Lot B, ADR 0004)
# ==============================================================================
_agent_endpoint() { # imprime "port token" pour le worker
  local port token
  port="$(env_get AGENT_PORT)"
  port="${port:-8089}"
  token="$(env_get AGENT_TOKEN)"
  [ -n "$token" ] || die "AGENT_TOKEN absent de $ENV_FILE"
  printf '%s %s\n' "$port" "$token"
}

_resolve_pid() { # <id?>  → id explicite, sinon dernier pipeline du projet actif
  local id="${1:-}" name
  if [ -z "$id" ]; then
    name="$(require_active)"
    id="$(reg -r --arg n "$name" '.projects[$n].last_pipeline // empty')"
    [ -n "$id" ] || die "aucun pipeline récent (préciser un id : ai2b pipeline <id>)"
  fi
  printf '%s' "$id"
}

# État pipeline persisté côté projet (<projet>/.ai-to-boost/pipeline.json) : survit au
# redémarrage du worker, contrairement à l'état en mémoire interrogé via /pipelines.
_pipe_json() { # imprime le chemin du pipeline.json du projet actif (ou code 1)
  local name path
  name="$(active_name)"
  [ -n "$name" ] || return 1
  path="$(proj_path "$name")"
  [ -n "$path" ] && [ -f "$path/.ai-to-boost/pipeline.json" ] || return 1
  printf '%s' "$path/.ai-to-boost/pipeline.json"
}
_pipe_field() { # <jq-filter> → valeur depuis pipeline.json du projet actif (vide sinon)
  local pj
  pj="$(_pipe_json)" || return 1
  jq -r "$1 // empty" "$pj" 2>/dev/null
}

cmd_run() {
  need curl
  need jq
  local spec="$*"
  [ -n "$spec" ] || die "usage: ai2b run \"<besoin>\""
  local name path port token
  name="$(require_active)"
  path="$(proj_path "$name")"
  read -r port token < <(_agent_endpoint)
  local body resp pid
  body="$(jq -nc --arg p "$spec" --arg r "$path" '{prompt:$p, repo:$r}')"
  resp="$(curl -s --max-time 15 -X POST "http://localhost:$port/pipelines" \
    -H "Authorization: Bearer $token" -H "Content-Type: application/json" -d "$body")" ||
    die "worker injoignable (:$port)"
  pid="$(printf '%s' "$resp" | jq -r '.pipeline_id // empty')"
  [ -n "$pid" ] || die "worker a refusé : $resp"
  reg_write --arg n "$name" --arg id "$pid" '.projects[$n].last_pipeline=$id'
  ok "pipeline ${c_bold}$pid${c_reset} démarré sur '$name'"
  info "  suivi : ai2b pipeline   |   board : ai2b ui   |   au jalon : ai2b approve | ai2b revise \"<retour>\" | ai2b stop"
  info "  à la fin : ai2b result (synthèse) | ai2b ui (board) | ai2b pipeline clean"
}

cmd_pipeline() {
  if [ "${1:-}" = "clean" ]; then
    shift
    cmd_pipeline_clean "$@"
    return
  fi
  need curl
  need jq
  local id port token resp
  id="$(_resolve_pid "${1:-}")"
  read -r port token < <(_agent_endpoint)
  resp="$(curl -s --max-time 5 -H "Authorization: Bearer $token" \
    "http://localhost:$port/pipelines/$id" 2>/dev/null || true)"
  # Repli : worker injoignable, réponse non-JSON, ou pipeline absent de la mémoire
  # (ex. après restart → {"error":"pipeline inconnu"}) → lire l'état persisté côté projet.
  if [ -z "$resp" ] || ! printf '%s' "$resp" | jq -e 'has("status") and .status != null' >/dev/null 2>&1; then
    local pj
    if pj="$(_pipe_json)" && [ "$(jq -r '.pipeline_id' "$pj")" = "$id" ]; then
      info "  ${c_dim}(état persisté — worker sans ce pipeline en mémoire)${c_reset}"
      resp="$(cat "$pj")"
    fi
  fi
  [ -n "$resp" ] || die "pipeline introuvable (worker injoignable et pas de pipeline.json)"
  printf '%s' "$resp" |
    jq '{pipeline_id, status, phase, awaiting, last_artifact, branch, base, error}'
}

_resume() { # <decision>
  need curl
  need jq
  local decision="$1" id port token body resp
  id="$(_resolve_pid "")"
  read -r port token < <(_agent_endpoint)
  body="$(jq -nc --arg d "$decision" '{decision:$d}')"
  resp="$(curl -s --max-time 10 -X POST "http://localhost:$port/pipelines/$id/resume" \
    -H "Authorization: Bearer $token" -H "Content-Type: application/json" -d "$body")" ||
    die "worker injoignable"
  if printf '%s' "$resp" | jq -e 'has("error") and .error != null' >/dev/null 2>&1; then
    die "$(printf '%s' "$resp" | jq -r '.error')"
  fi
  ok "${decision%%:*} → pipeline $id"
}

cmd_approve() { _resume "approve"; }
cmd_revise() {
  local fb="$*"
  [ -n "$fb" ] || die "usage: ai2b revise \"<retour>\""
  _resume "revise:$fb"
}
cmd_stop() { _resume "stop"; }

cmd_result() { # [pid] — synthèse du résultat d'un pipeline (sans rien merger)
  need jq
  need git
  local name path pj
  name="$(require_active)"
  path="$(proj_path "$name")"
  pj="$(_pipe_json)" || die "aucun pipeline pour '$name' (lancer ai2b run \"<besoin>\")"
  local id status branch base wt
  id="$(jq -r '.pipeline_id // "?"' "$pj")"
  status="$(jq -r '.status // "?"' "$pj")"
  branch="$(jq -r '.branch // empty' "$pj")"
  base="$(jq -r '.base // empty' "$pj")"
  wt="$(jq -r '.worktree // empty' "$pj")"

  info "${c_bold}Pipeline $id${c_reset} — statut : $status"
  info "  branche : ${branch:-?}    base : ${base:-?}"
  if [ -n "$wt" ] && [ -d "$wt" ]; then
    info "  worktree : $wt ${c_dim}(présent)${c_reset}"
  elif [ -n "$wt" ]; then
    info "  worktree : ${c_dim}retiré (ai2b run pour régénérer, ou voir la branche)${c_reset}"
  fi

  # Décompte des stories : worktree si présent, sinon la branche.
  local sprint yaml=""
  sprint="_bmad-output/implementation-artifacts/sprint-status.yaml"
  if [ -n "$wt" ] && [ -f "$wt/$sprint" ]; then
    yaml="$(cat "$wt/$sprint")"
  elif [ -n "$branch" ]; then
    yaml="$(git -C "$path" show "$branch:$sprint" 2>/dev/null || true)"
  fi
  if [ -n "$yaml" ]; then
    local d r p b
    d="$(printf '%s\n' "$yaml" | grep -cE '^[[:space:]]+[0-9]+-[0-9]+-.*: done$' || true)"
    r="$(printf '%s\n' "$yaml" | grep -cE '^[[:space:]]+[0-9]+-[0-9]+-.*: review$' || true)"
    p="$(printf '%s\n' "$yaml" | grep -cE '^[[:space:]]+[0-9]+-[0-9]+-.*: in-progress$' || true)"
    b="$(printf '%s\n' "$yaml" | grep -cE '^[[:space:]]+[0-9]+-[0-9]+-.*: backlog$' || true)"
    info "  stories  : done=$d review=$r in-progress=$p backlog=$b"
  fi
  local fails
  fails="$(jq -r '(.impl_failed // []) | length' "$pj" 2>/dev/null || echo 0)"
  [ "${fails:-0}" != "0" ] &&
    warn "  échecs implémentation : $fails  (détail : jq .impl_failed \"$pj\")"

  if [ -n "$branch" ] && [ -n "$base" ]; then
    info ""
    info "${c_bold}Modifications ($base..$branch)${c_reset}"
    git -C "$path" diff --stat "$base..$branch" 2>/dev/null | tail -15 | sed 's/^/  /' || true
  fi

  cat <<EOF

${c_bold}Consulter / intégrer${c_reset} ${c_dim}(rien n'est mergé automatiquement)${c_reset}
  board    : ai2b ui
  revue    : git -C "$path" checkout $branch
  merge    : git -C "$path" checkout $base && git -C "$path" merge --no-ff $branch
  nettoyer : ai2b pipeline clean         (worktree ; --branch pour aussi la branche)
EOF
}

cmd_pipeline_clean() { # [--branch] — retire le worktree conservé (et opt. la branche)
  need jq
  need git
  local drop_branch=0 a
  for a in "$@"; do
    case "$a" in
      --branch | --all) drop_branch=1 ;;
    esac
  done
  local name path pj id branch wt
  name="$(require_active)"
  path="$(proj_path "$name")"
  pj="$(_pipe_json)" || die "aucun pipeline.json pour '$name'"
  id="$(jq -r '.pipeline_id // "?"' "$pj")"
  branch="$(jq -r '.branch // empty' "$pj")"
  wt="$(jq -r '.worktree // empty' "$pj")"

  local what="worktree"
  [ "$drop_branch" = 1 ] && what="worktree + branche $branch (code PERDU si non mergé)"
  printf '%sNettoyer le pipeline %s — %s ? [y/N] %s' "$c_red" "$id" "$what" "$c_reset"
  read -r ans
  [ "$ans" = "y" ] || [ "$ans" = "Y" ] || die "annulé"

  if [ -n "$wt" ]; then
    if git -C "$path" worktree remove "$wt" --force 2>/dev/null; then
      ok "worktree retiré : $wt"
    else
      info "  (worktree déjà absent)"
    fi
  fi
  if [ "$drop_branch" = 1 ] && [ -n "$branch" ]; then
    if git -C "$path" branch -D "$branch" 2>/dev/null; then
      ok "branche supprimée : $branch"
    else
      info "  (branche absente)"
    fi
  fi
}

cmd_collect() { # [--clean] — intègre pipeline/<id> → base du projet (merge --no-ff)
  need git
  need jq
  local do_clean=0 a
  for a in "$@"; do
    case "$a" in
      --clean) do_clean=1 ;;
    esac
  done
  local name path pj id branch base wt
  name="$(require_active)"
  path="$(proj_path "$name")"
  pj="$(_pipe_json)" || die "aucun pipeline pour '$name' (lancer ai2b run \"<besoin>\")"
  id="$(jq -r '.pipeline_id // "?"' "$pj")"
  branch="$(jq -r '.branch // empty' "$pj")"
  base="$(jq -r '.base // empty' "$pj")"
  wt="$(jq -r '.worktree // empty' "$pj")"
  if [ -z "$branch" ] || [ -z "$base" ]; then
    die "pipeline.json incomplet (branch/base)"
  fi
  git -C "$path" rev-parse --verify "$branch" >/dev/null 2>&1 ||
    die "branche $branch introuvable (déjà nettoyée ?)"
  # Garde-fou : aucune modif SUIVIE en attente (le merge bascule de branche). Les fichiers
  # non suivis (ex. .ai-to-boost/ gitignoré) ne bloquent pas checkout/merge → ignorés.
  [ -z "$(git -C "$path" status --porcelain --untracked-files=no)" ] ||
    die "copie de travail de '$name' a des modifs non commitées — committe/stash avant collect"

  printf '%sIntégrer %s → %s du projet %s (merge --no-ff) ? [y/N] %s' \
    "$c_red" "$branch" "$base" "$name" "$c_reset"
  read -r ans
  [ "$ans" = "y" ] || [ "$ans" = "Y" ] || die "annulé"

  git -C "$path" checkout "$base" 2>/dev/null || die "checkout $base impossible"
  if git -C "$path" merge --no-ff --no-edit \
    -m "Merge $branch into $base — pipeline BMAD $id" "$branch"; then
    ok "intégré : $branch → $base"
  else
    git -C "$path" merge --abort 2>/dev/null || true
    die "conflits de merge — résoudre à la main : git -C \"$path\" merge --no-ff $branch"
  fi

  if [ "$do_clean" = 1 ]; then
    if [ -n "$wt" ]; then
      git -C "$path" worktree remove "$wt" --force 2>/dev/null && ok "worktree retiré"
    fi
    # -d : ne supprime que si bien mergée (elle l'est) ; sinon on la garde.
    if git -C "$path" branch -d "$branch" 2>/dev/null; then
      ok "branche supprimée : $branch"
    fi
  fi
  info "  ${c_dim}push : git -C \"$path\" push origin $base (si remote configuré)${c_reset}"
}

# ==============================================================================
cmd_help() {
  cat <<EOF
${c_bold}ai2b${c_reset} — tour de contrôle ai-to-boost

${c_bold}Projets${c_reset}
  ai2b new <nom> [chemin]   crée un repo (git + GitFlow + init BMAD) et l'active
  ai2b init [chemin]        enregistre un repo existant (défaut: .) et l'active
  ai2b switch <nom>         change le projet actif
  ai2b ls                   liste les projets (▶ = actif)
  ai2b current              affiche le projet actif
  ai2b rm <nom> [--purge]   retire du registre (--purge supprime le dossier)

${c_bold}Services${c_reset}
  ai2b status               état des services + projet actif
  ai2b up | down            démarre / arrête toute la stack
  ai2b restart [service]    redémarre tout, ou un service (worker|bridge|<compose>)
  ai2b logs <service>       suit les logs d'un service

${c_bold}Projet actif — tâche one-shot${c_reset}
  ai2b build "<spec>"       lance une tâche agentique (Bash autorisé)
  ai2b code  "<spec>"       lance une tâche agentique (édition de fichiers)
  ai2b job <id>             état d'une tâche
  ai2b ui                   ouvre bmad-ui focalisé sur le projet actif

${c_bold}Projet actif — pipeline BMAD${c_reset}
  ai2b run "<besoin>"       démarre le pipeline BMAD (analyst→PM→… avec jalons)
  ai2b pipeline [id]        état du pipeline (défaut : le dernier)
  ai2b approve              valide le jalon courant et continue
  ai2b revise "<retour>"    rejoue la phase en attente avec un retour
  ai2b stop                 arrête le pipeline
  ai2b result               synthèse du résultat (branche, stories, diff, intégration)
  ai2b ui                   board bmad-ui du pipeline (worktree) ; --project = repo
  ai2b collect [--clean]    merge pipeline/<id> → base du projet (--clean : purge ensuite)
  ai2b pipeline clean       retire le worktree conservé (--branch : aussi la branche)

Registre : $REGISTRY
Projets par défaut : $PROJECTS_DIR
EOF
}

# --- Dispatch ------------------------------------------------------------------
main() {
  local cmd="${1:-help}"
  shift || true
  case "$cmd" in
    new) cmd_new "$@" ;;
    init) cmd_init "$@" ;;
    switch | sw) cmd_switch "$@" ;;
    ls | list) cmd_ls "$@" ;;
    current | cur) cmd_current "$@" ;;
    rm | remove) cmd_rm "$@" ;;
    status | st) cmd_status "$@" ;;
    up) cmd_up "$@" ;;
    down) cmd_down "$@" ;;
    restart) cmd_restart "$@" ;;
    logs) cmd_logs "$@" ;;
    build) cmd_build "$@" ;;
    code) cmd_code "$@" ;;
    job) cmd_job "$@" ;;
    ui) cmd_ui "$@" ;;
    run) cmd_run "$@" ;;
    pipeline | pl) cmd_pipeline "$@" ;;
    result | res) cmd_result "$@" ;;
    collect) cmd_collect "$@" ;;
    approve | ok) cmd_approve "$@" ;;
    revise) cmd_revise "$@" ;;
    stop) cmd_stop "$@" ;;
    help | -h | --help) cmd_help ;;
    *)
      warn "commande inconnue : $cmd"
      cmd_help
      exit 1
      ;;
  esac
}
main "$@"
