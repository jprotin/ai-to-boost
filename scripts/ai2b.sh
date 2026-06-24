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
  local name path
  name="$(require_active)"
  path="$(proj_path "$name")"
  [ -d "$path" ] || die "répertoire introuvable : $path"
  (cd "$path" && exec "$BMAD_START")
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
  info "  suivi : ai2b pipeline   |   au jalon : ai2b approve | ai2b revise \"<retour>\" | ai2b stop"
}

cmd_pipeline() {
  need curl
  need jq
  local id port token
  id="$(_resolve_pid "${1:-}")"
  read -r port token < <(_agent_endpoint)
  curl -s --max-time 5 -H "Authorization: Bearer $token" \
    "http://localhost:$port/pipelines/$id" |
    jq '{pipeline_id, status, phase, awaiting, last_artifact, branch, base, error}' ||
    die "worker injoignable"
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
