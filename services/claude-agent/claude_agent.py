#!/usr/bin/env python3
"""Worker agentique : `claude -p` AVEC outils, en isolation git worktree (Phase 6b.1).

Contrairement au claude-bridge (texte seul), ce worker laisse Claude AGIR — mais
sous fortes contraintes (cf. docs/phase6-plan.md, ADR 0002) :

- Forfait Max : ANTHROPIC_API_KEY / ANTHROPIC_AUTH_TOKEN retirés de l'env enfant ;
  le service REFUSE de démarrer si l'une est présente (anti-bascule API payante).
- Isolation : chaque job tourne dans un `git worktree` dédié, sur une branche
  `agent/<job_id>`. JAMAIS de push, JAMAIS de merge, jamais d'écriture sur la
  branche de base. Le repo `ai-to-boost` lui-même est interdit comme cible.
- 6b.1 = outils FICHIERS seulement (Read/Edit/Write, `--permission-mode acceptEdits`).
  Pas de Bash, pas de web : l'agent ne peut rien exécuter. Le Bash scopé viendra
  en 6b.3 (BMAD), derrière un hook PreToolUse.
- Asynchrone : POST /jobs rend un id immédiatement ; le travail tourne en thread,
  sérialisé (1 job à la fois). Résultat via GET /jobs/<id>.

Config (env, cf. .env) :
  AGENT_TOKEN        (requis) token Bearer
  AGENT_HOST         interface (défaut 0.0.0.0)
  AGENT_PORT         port (défaut 8089)
  AGENT_MODEL        modèle claude (défaut opus)
  AGENT_TIMEOUT      timeout secondes par job (défaut 600)
  AGENT_MAXTURNS     max-turns claude (défaut 30)
  AGENT_WORKROOT     racine des worktrees (défaut ~/.local/share/claude-agent/worktrees)
  AGENT_FORBID       repos interdits comme cible (défaut = repo ai-to-boost)
"""

import datetime
import time
import json
import os
import re
import shutil
import subprocess
import threading
import urllib.parse
import urllib.request
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HOST = os.environ.get("AGENT_HOST", "0.0.0.0")
PORT = int(os.environ.get("AGENT_PORT", "8089"))
TOKEN = os.environ.get("AGENT_TOKEN", "")
MODEL = os.environ.get("AGENT_MODEL", "opus")
TIMEOUT = int(os.environ.get("AGENT_TIMEOUT", "1200"))
MAXTURNS = int(os.environ.get("AGENT_MAXTURNS", "30"))
# Pipeline — curseur de modèle des phases dev/doc (par story). Défaut rapide (sonnet) ;
# l'architecte et l'ESCALADE sur échec dur restent sur MODEL (opus). Résolution effective :
# run > projet (.ai-to-boost/config.json:dev_model) > cet env.
DEV_MODEL = os.environ.get("PIPELINE_DEV_MODEL", "sonnet")
# max-turns par story : assez haut pour finir une story réelle (16 était trop bas →
# error_max_turns → travail partiel jeté). Surchargeable par env.
STORY_MAXTURNS = int(os.environ.get("PIPELINE_STORY_MAXTURNS", "40"))
# Gate de vérification : juge LLM (par story + acceptation finale) + tests si présents.
# Désactivable (PIPELINE_VERIFY=false). Juge sur un modèle rapide.
VERIFY = os.environ.get("PIPELINE_VERIFY", "true").lower() != "false"
# Juge PAR STORY : verdict PASS/FAIL simple → Haiku (rapide) suffit et reste objectif.
JUDGE_MODEL = os.environ.get("PIPELINE_JUDGE_MODEL", "haiku")
# Acceptation FINALE (livrable ↔ besoin) : gardée forte pour ne pas perdre en qualité.
ACCEPT_MODEL = os.environ.get("PIPELINE_ACCEPT_MODEL", "sonnet")
# Effort du curseur dev (Sonnet 5 sur-réfléchit au défaut « high ») ; escalade Opus = défaut.
DEV_EFFORT = os.environ.get("PIPELINE_DEV_EFFORT", "medium")
WORKROOT = os.environ.get(
    "AGENT_WORKROOT", os.path.expanduser("~/.local/share/claude-agent/worktrees")
)
CLAUDE = shutil.which("claude") or os.path.expanduser("~/.local/bin/claude")
# Repo cible par défaut quand le job ne le précise pas (ex. appel depuis n8n /code).
DEFAULT_REPO = os.environ.get("AGENT_DEFAULT_REPO", "")
# Callback n8n appelé en fin de job (async) : n8n notifie ensuite l'origine.
CALLBACK_URL = os.environ.get("AGENT_CALLBACK_URL", "")
# Exiger le marqueur .ai-to-boost/ (projet "initialisé") avant d'agir (Phase 6b.3b).
REQUIRE_MARKER = os.environ.get("AGENT_REQUIRE_MARKER", "true").lower() != "false"

# Repos interdits comme cible (le worker ne doit jamais agir sur l'orchestrateur).
_DEFAULT_FORBID = os.path.realpath(
    os.path.join(os.path.dirname(__file__), os.pardir, os.pardir)
)
FORBID = [
    os.path.realpath(os.path.expanduser(p))
    for p in os.environ.get("AGENT_FORBID", _DEFAULT_FORBID).split(os.pathsep)
    if p
]

# Création/suppression de projets depuis la web-app (F4). Mêmes conventions que le CLI
# ai2b : init via scripts/ai-to-boost-init.sh, projets sous AI2B_PROJECTS_DIR (~/dev).
ORCH_ROOT = _DEFAULT_FORBID
INIT_SCRIPT = os.path.join(ORCH_ROOT, "scripts", "ai-to-boost-init.sh")
PROJECTS_DIR = os.path.realpath(
    os.path.expanduser(os.environ.get("AI2B_PROJECTS_DIR", "~/dev"))
)

# Hook garde-fou PreToolUse (denylist Bash + confinement écritures), injecté via --settings.
GUARD_HOOK = os.path.join(os.path.dirname(os.path.abspath(__file__)), "guard_hook.py")
# BMAD commun : installé une fois, injecté (symlink) dans chaque worktree (Phase 6b.3c).
BMAD_SHARED = os.environ.get(
    "AGENT_BMAD_DIR", os.path.expanduser("~/agent-workspace/.bmad-shared")
)
# RAG double-portée : collection commune + collection projet (Phase 6b.3d).
QDRANT_URL = os.environ.get("QDRANT_URL", "http://127.0.0.1:6333")
RAG_COMMON = os.environ.get("RAG_COLLECTION", "knowledge")
EMBED_MODEL = os.environ.get("EMBEDDING_MODEL", "nomic-ai/nomic-embed-text-v1.5")

# Pipeline BMAD multi-persona/multi-LLM (Lot B, ADR 0004).
# LiteLLM = passerelle des modèles LOCAUX (planning) ; Claude reste sur claude -p (forfait).
LITELLM_URL = os.environ.get("LITELLM_URL", "http://127.0.0.1:4000")
LITELLM_KEY = os.environ.get("LITELLM_MASTER_KEY", "")

# Modes : "file" (défaut, outils fichiers) / "build" (Bash en plus, sous garde-fou).
ALLOWED_TOOLS = {
    "file": ["Read", "Edit", "Write"],
    "build": ["Read", "Edit", "Write", "Bash"],
}
DISALLOWED_TOOLS = ["WebFetch", "WebSearch"]
APPEND_SYSTEM_PROMPT = (
    "Tu es un worker de développement automatisé, sans interaction humaine pendant "
    "l'exécution. Réalise la demande en créant/éditant les fichiers nécessaires dans "
    "le répertoire courant. Ne pose aucune question, ne demande aucune confirmation. "
    "Tu disposes d'outils RAG qdrant-find : 'rag-common' (doc transverse) et, si "
    "présent, 'rag-project' (doc/conventions propres au projet courant). Consulte-les "
    "avant d'agir pour respecter le contexte et les conventions du projet."
)

JOBS: dict[str, dict] = {}
JOBS_LOCK = threading.Lock()
RUN_LOCK = threading.Lock()  # sérialise : 1 job à la fois


def _git(repo, *args, check=True):
    proc = subprocess.run(["git", "-C", repo, *args], capture_output=True, text=True)
    if check and proc.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)}: {proc.stderr.strip()}")
    return proc.stdout.strip()


def _set(job_id, **kw):
    with JOBS_LOCK:
        JOBS[job_id].update(kw)


def _inject_bmad(worktree):
    """Rend BMAD (commun) visible dans le worktree via symlinks (sans le committer)."""
    if not os.path.isdir(BMAD_SHARED):
        return False
    try:
        os.symlink(os.path.join(BMAD_SHARED, "_bmad"), os.path.join(worktree, "_bmad"))
        os.makedirs(os.path.join(worktree, ".claude"), exist_ok=True)
        os.symlink(
            os.path.join(BMAD_SHARED, ".claude", "skills"),
            os.path.join(worktree, ".claude", "skills"),
        )
        return True
    except Exception as exc:
        print(f"[bmad] injection échouée: {exc}", flush=True)
        return False


def _eject_bmad(worktree):
    """Retire les symlinks BMAD avant le `git add` (ne pas committer l'injection)."""
    for rel in ("_bmad", ".claude/skills"):
        p = os.path.join(worktree, rel)
        try:
            if os.path.islink(p):
                os.unlink(p)
        except Exception:
            pass
    # supprime .claude si vide
    cdir = os.path.join(worktree, ".claude")
    try:
        if os.path.isdir(cdir) and not os.listdir(cdir):
            os.rmdir(cdir)
    except Exception:
        pass


def _callback(job_id):
    """Notifie n8n en fin de job (best-effort) ; n8n relaie vers l'origine."""
    if not CALLBACK_URL:
        return
    with JOBS_LOCK:
        payload = dict(JOBS.get(job_id, {}))
    try:
        req = urllib.request.Request(
            CALLBACK_URL,
            data=json.dumps(payload, ensure_ascii=False).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        urllib.request.urlopen(req, timeout=15).read()
    except Exception as exc:
        print(f"[callback] échec pour {job_id}: {exc}", flush=True)


def _validate_repo(repo):
    repo = os.path.realpath(os.path.expanduser(repo))
    if not os.path.isdir(os.path.join(repo, ".git")):
        raise ValueError(f"repo cible introuvable ou non-git: {repo}")
    for forbid in FORBID:
        if (
            repo == forbid
            or repo.startswith(forbid + os.sep)
            or forbid.startswith(repo + os.sep)
        ):
            raise ValueError(f"repo cible interdit (orchestrateur): {repo}")
    if REQUIRE_MARKER and not os.path.isdir(os.path.join(repo, ".ai-to-boost")):
        raise ValueError(
            f"projet non initialisé (marqueur .ai-to-boost/ absent): {repo} "
            "— lancer scripts/ai-to-boost-init.sh"
        )
    return repo


def _base_branch(repo):
    """Base depuis laquelle brancher : config .ai-to-boost, sinon HEAD courant."""
    cfg = os.path.join(repo, ".ai-to-boost", "config.json")
    try:
        with open(cfg, encoding="utf-8") as f:
            base = (json.load(f) or {}).get("base_branch")
        if base:
            return base
    except Exception:
        pass
    return _git(repo, "rev-parse", "--abbrev-ref", "HEAD")


def _rag_mcp(repo):
    """MCP RAG : rag-common (toujours) + rag-project si la collection existe.

    Retourne (config_dict, [outils mcp autorisés]).
    """

    def _server(coll):
        return {
            "command": "uvx",
            "args": ["mcp-server-qdrant"],
            "env": {
                "QDRANT_URL": QDRANT_URL,
                "COLLECTION_NAME": coll,
                "EMBEDDING_MODEL": EMBED_MODEL,
            },
        }

    servers = {"rag-common": _server(RAG_COMMON)}
    tools = ["mcp__rag-common__qdrant-find"]
    try:
        with open(
            os.path.join(repo, ".ai-to-boost", "config.json"), encoding="utf-8"
        ) as f:
            name = (json.load(f) or {}).get("name", "")
        slug = re.sub(r"[^a-z0-9_-]", "-", name.lower())
        coll = f"proj-{slug}"
        with urllib.request.urlopen(f"{QDRANT_URL}/collections/{coll}", timeout=5) as r:
            exists = r.status == 200
        if exists:
            servers["rag-project"] = _server(coll)
            tools.append("mcp__rag-project__qdrant-find")
    except Exception:
        pass
    return {"mcpServers": servers}, tools


def _guard_settings():
    """Settings inline (prime sur le worktree) : hook PreToolUse sur Bash + écritures."""
    return json.dumps(
        {
            "hooks": {
                "PreToolUse": [
                    {
                        "matcher": "Bash|Edit|Write|MultiEdit|NotebookEdit",
                        "hooks": [{"type": "command", "command": GUARD_HOOK}],
                    }
                ]
            }
        }
    )


def _run_claude_tools(
    worktree,
    repo,
    prompt,
    mode,
    tag,
    model=None,
    max_turns=None,
    session_id=None,
    resume=False,
    effort=None,
):
    """Cœur d'appel `claude -p` AVEC outils (Read/Edit/Write[/Bash]) sous garde-fou + RAG,
    dans un worktree donné. `model`/`max_turns` surchargent les défauts (MODEL/MAXTURNS).
    NE gère NI le worktree, NI BMAD, NI le commit, NI RUN_LOCK : l'appelant s'en charge
    (réutilisé par run_job one-shot ET la boucle dev-story du pipeline). Retourne
    {summary, cost_usd, tokens, audit}. Lève en cas d'échec claude."""
    audit_log = os.path.join(WORKROOT, f"{tag}.audit.log")
    env = {
        k: v
        for k, v in os.environ.items()
        if k not in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN")
    }
    env.setdefault("PATH", "/home/jprotin/.local/bin:/usr/bin:/bin")
    env["AGENT_AUDIT_LOG"] = audit_log
    # RAG double-portée : MCP commun + projet (lecture qdrant-find).
    rag_cfg, rag_tools = _rag_mcp(repo)
    mcp_file = os.path.join(WORKROOT, f"{tag}.mcp.json")
    with open(mcp_file, "w", encoding="utf-8") as f:
        json.dump(rag_cfg, f)
    # build : Bash autorisé mais bypassPermissions + garde-fou hook (bloque même
    #         en bypass) ; file : édition auto, pas de Bash.
    perm_mode = "bypassPermissions" if mode == "build" else "acceptEdits"
    cmd = [
        CLAUDE,
        "-p",
        prompt,
        "--model",
        model or MODEL,
        "--output-format",
        "json",
        "--permission-mode",
        perm_mode,
        "--max-turns",
        str(max_turns or MAXTURNS),
        "--allowed-tools",
        *ALLOWED_TOOLS.get(mode, ALLOWED_TOOLS["file"]),
        *rag_tools,
        "--disallowed-tools",
        *DISALLOWED_TOOLS,
        "--settings",
        _guard_settings(),
        "--mcp-config",
        mcp_file,
        "--strict-mcp-config",
        "--append-system-prompt",
        APPEND_SYSTEM_PROMPT,
    ]
    # Session CHAUDE : story 1 crée la session (--session-id), stories suivantes la
    # REPRENNENT (--resume) → contexte/fichiers déjà lus conservés, pas de cold-start.
    # Le guard --settings/--mcp-config est re-passé à chaque appel (sécurité maintenue).
    if resume and session_id:
        cmd += ["--resume", session_id]
    elif session_id:
        cmd += ["--session-id", session_id]
    if effort:  # maîtrise du sur-raisonnement (Sonnet 5) sur les tâches simples
        cmd += ["--effort", effort]
    proc = subprocess.run(
        cmd, cwd=worktree, env=env, capture_output=True, text=True, timeout=TIMEOUT
    )
    try:
        result = json.loads(proc.stdout or "{}")
    except Exception:
        result = {}
    truncated = False
    if proc.returncode != 0:
        # error_max_turns = succès PARTIEL : claude a travaillé mais atteint la limite
        # de tours (rc=1). On NE lève PAS et on CONSERVE le code produit — l'appelant le
        # committe et le juge évalue le diff partiel. Tout autre rc≠0 = vrai échec : on
        # remonte le détail du stdout JSON (subtype/errors), pas seulement stderr (vide).
        truncated = (
            result.get("subtype") == "error_max_turns"
            or result.get("terminal_reason") == "max_turns"
        )
        if not truncated:
            detail = (
                result.get("result")
                or "; ".join(result.get("errors") or [])
                or proc.stderr.strip()
                or f"claude exit {proc.returncode}"
            )
            raise RuntimeError(detail)
    audit = []
    if os.path.exists(audit_log):
        with open(audit_log, encoding="utf-8") as f:
            audit = [line.rstrip("\n") for line in f if line.strip()]
    usage = result.get("usage") or {}
    tokens = {
        # entrée = prompt + cache (création + lecture), tel que consommé.
        "input": (usage.get("input_tokens") or 0)
        + (usage.get("cache_creation_input_tokens") or 0)
        + (usage.get("cache_read_input_tokens") or 0),
        "output": usage.get("output_tokens") or 0,
    }
    return {
        "summary": result.get("result", ""),
        "cost_usd": result.get("total_cost_usd"),
        "tokens": tokens,
        "audit": audit,
        "truncated": truncated,  # True si max_turns atteint (travail partiel conservé)
        "session_id": result.get("session_id"),  # pour reprendre la session (--resume)
    }


def run_job(job_id, prompt, repo, mode="file"):
    branch = f"agent/{job_id}"
    worktree = os.path.join(WORKROOT, job_id)
    with RUN_LOCK:
        _set(job_id, status="running")
        try:
            base = _base_branch(repo)
            _git(repo, "worktree", "add", worktree, "-b", branch, base)
        except Exception as exc:
            _set(job_id, status="error", error=f"préparation worktree: {exc}")
            return
        bmad = _inject_bmad(worktree)
        try:
            res = _run_claude_tools(worktree, repo, prompt, mode, job_id)
            _eject_bmad(worktree)  # retire les symlinks BMAD avant de committer
            _git(worktree, "add", "-A")
            changed = bool(_git(worktree, "status", "--porcelain"))
            if changed:
                _git(worktree, "commit", "-m", f"agent({job_id}): {prompt[:60]}")
            diff_stat = _git(repo, "diff", "--stat", f"{base}..{branch}")
            files = _git(repo, "diff", "--name-status", f"{base}..{branch}")
            _set(
                job_id,
                status="done",
                branch=branch,
                base=base,
                changed=changed,
                bmad=bmad,
                summary=res["summary"],
                diff_stat=diff_stat,
                files=files,
                audit=res["audit"],
                cost_usd=res["cost_usd"],
            )
        except subprocess.TimeoutExpired:
            _set(job_id, status="error", error=f"timeout > {TIMEOUT}s", branch=branch)
        except Exception as exc:
            _set(job_id, status="error", error=str(exc), branch=branch)
        finally:
            # retire le worktree ; la branche agent/<id> est conservée pour revue.
            try:
                _git(repo, "worktree", "remove", worktree, "--force", check=False)
            except Exception:
                pass
    _callback(job_id)


# ============================================================================
# Pipeline BMAD multi-persona / multi-LLM (Lot B — ADR 0004)
# ----------------------------------------------------------------------------
# Moteur de phases : chaque persona produit un artefact, le pipeline s'arrête aux
# jalons (validation humaine) puis reprend. Routage LLM par phase : planning sur LLM
# local (LiteLLM), architecte/dev/QA sur Claude (claude -p). B1 = analyst + PM (texte,
# local) + 1er jalon ; B2/B3 ajouteront archi, epics/stories puis l'implémentation.
# ============================================================================
PIPELINES: dict[str, dict] = {}
PIPELINES_LOCK = threading.Lock()

# Modèle des personas de planning (local via LiteLLM). Défaut local-gemma (charge sur
# la machine actuelle) ; passer à local-qwen quand la VRAM le permet (meilleure qualité).
PLANNING_MODEL = os.environ.get("PIPELINE_PLANNING_MODEL", "local-gemma")

PHASES: list[dict] = [
    {
        "key": "analyst",
        "persona": "Analyste produit BMAD (Mary)",
        "model": PLANNING_MODEL,
        "kind": "text",
        "artifact": "docs/brief.md",
        "context": [],
        "checkpoint": False,
        "instruction": (
            "Rédige un BRIEF PRODUIT concis en français (markdown). Sections : "
            "Contexte & problème, Utilisateurs cibles, Objectifs, Périmètre pressenti, "
            "Contraintes & risques. Factuel, sans remplissage."
        ),
    },
    {
        "key": "pm",
        "persona": "Product Manager BMAD (John)",
        "model": PLANNING_MODEL,
        "kind": "text",
        "artifact": "docs/prd.md",
        "context": ["docs/brief.md"],
        "checkpoint": True,
        "instruction": (
            "Rédige un PRD complet en français (markdown), commençant par "
            "'# PRD — <titre>'. Sections : Contexte et problème, Objectifs (avec "
            "indicateurs), Personas, Périmètre (MVP / hors-MVP), Exigences "
            "fonctionnelles (table priorisée), Exigences non fonctionnelles, "
            "Contraintes techniques, Critères d'acceptation, Risques."
        ),
    },
    {
        "key": "architect",
        "persona": "Architecte BMAD (Winston)",
        "model": "claude",  # raisonnement lourd -> Claude (claude -p, forfait)
        "kind": "text",
        "artifact": "docs/architecture.md",
        "context": ["docs/prd.md"],
        "checkpoint": True,
        "instruction": (
            "Rédige un document d'ARCHITECTURE en français (markdown), commençant par "
            "'# Architecture — <titre>'. Sections : Vue d'ensemble, Choix techniques "
            "(stack + justifications), Composants & responsabilités, Modèle de données "
            "(si pertinent), Découpage en modules, Risques techniques & parades. "
            "Reste cohérent avec le PRD. PRINCIPE DIRECTEUR : conçois la solution la PLUS "
            "SIMPLE et la plus DIRECTE qui répond au besoin, PROPORTIONNÉE à sa taille. "
            "Pas de sur-ingénierie : n'introduis backend, base de données, authentification, "
            "sécurité avancée, étape de build ou batterie de tests QUE si le besoin (ou "
            "l'existant) le justifie réellement. Pour un petit besoin front, une page/un "
            "module suffit."
        ),
    },
    {
        "key": "epics",
        "persona": "Product Manager / Scrum Master BMAD",
        "model": PLANNING_MODEL,
        "kind": "epics",  # produit epics.md ; sprint-status.yaml dérivé (format bmad-ui)
        "artifact": "_bmad-output/planning-artifacts/epics.md",
        "context": ["docs/prd.md", "docs/architecture.md"],
        "checkpoint": True,
        "instruction": (
            "Découpe le produit en EPICS et STORIES, en français (markdown), au format "
            "STRICT suivant (respecté à la lettre, c'est parsé automatiquement) :\n"
            "## Epic 1: <titre de l'epic>\n"
            "<description courte de l'epic>\n"
            "### Story 1.1: <titre de la story>\n"
            "<critères d'acceptation en puces>\n"
            "### Story 1.2: <titre>\n...\n"
            "## Epic 2: <titre>\n...\n"
            "Numérote les epics 1..N et les stories N.M en continu. Titres courts.\n"
            "DÉCOUPAGE MINIMAL et PROPORTIONNÉ au besoin : ne crée que le strict "
            "nécessaire. Pour un petit besoin, 1 epic et 1 à 3 stories SUFFISENT. "
            "Maximum 3 epics. N'invente PAS d'epics/stories pour des besoins NON demandés "
            "(sécurité, admin, tests exhaustifs, perf… seulement si explicitement requis). "
            "Chaque story = un incrément réellement utile et livrable."
        ),
    },
    {
        "key": "implementation",
        "persona": "Développeur BMAD (dev-story)",
        "model": "claude",  # code -> Claude (claude -p, forfait), AVEC outils
        "kind": "implementation",  # boucle par story ; prompt construit dans _story_prompt
        "artifact": None,
        "context": ["docs/architecture.md", "_bmad-output/planning-artifacts/epics.md"],
        "checkpoint": True,  # jalon "code" : revue humaine de l'implémentation
        "instruction": "",
    },
]

# Phase doc OPTIONNELLE (génère README + docs/ depuis le code final). Activée par défaut ;
# PIPELINE_DOC_PHASE=false la désactive pour des itérations plus rapides (un appel Claude
# de moins + un jalon de moins).
if os.environ.get("PIPELINE_DOC_PHASE", "true").lower() != "false":
    PHASES.append(
        {
            "key": "doc",
            "persona": "Rédacteur technique BMAD",
            "model": "claude",  # lit le code produit -> Claude (claude -p, forfait)
            "kind": "documentation",  # README + docs/ depuis le code final + PRD/archi
            "artifact": "README.md",  # artefact affiché (entrée de la doc)
            "context": ["docs/prd.md", "docs/architecture.md"],
            "checkpoint": True,  # jalon final : revue humaine de la documentation
            "instruction": "",
        }
    )

# Artefacts texte relisibles dans la webui (revue avant approbation d'un jalon).
ARTIFACT_TITLES = {
    "analyst": "Brief",
    "pm": "PRD",
    "doc": "Documentation",
    "architect": "Architecture",
    "epics": "Epics",
}
# Chemin par défaut d'un artefact par clé de phase (filet si pipeline.json incomplet).
ARTIFACT_PATHS = {p["key"]: p["artifact"] for p in PHASES if p.get("artifact")}


def _set_pipe(pid, **kw):
    with PIPELINES_LOCK:
        PIPELINES[pid].update(kw)
    _persist_pipe(pid)


def _accum_time(pid, bucket, key, seconds):
    """Cumule un temps (s) dans PIPELINES[pid][bucket][key] (ex. timing_by_phase),
    puis persiste. Cumulatif : une phase rejouée (révision) additionne son temps."""
    with PIPELINES_LOCK:
        d = PIPELINES[pid].setdefault(bucket, {})
        d[key] = round((d.get(key) or 0) + seconds, 1)
    _persist_pipe(pid)


def _persist_pipe(pid):
    """État persisté dans .ai-to-boost/pipeline.json (survit aux redémarrages)."""
    with PIPELINES_LOCK:
        state = dict(PIPELINES.get(pid, {}))
    repo = state.get("repo")
    if not repo:
        return
    try:
        d = os.path.join(repo, ".ai-to-boost")
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, "pipeline.json"), "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
        # Snapshot par run (archive F6) : un fichier par pipeline_id, jamais écrasé par
        # un run suivant → historique consultable même après relance d'un nouveau pipeline.
        hdir = os.path.join(d, "pipelines")
        os.makedirs(hdir, exist_ok=True)
        with open(os.path.join(hdir, f"{pid}.json"), "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
    except Exception as exc:
        print(f"[pipe] persist {pid}: {exc}", flush=True)


def _pipe_callback(pid):
    if not CALLBACK_URL:
        return
    with PIPELINES_LOCK:
        payload = dict(PIPELINES.get(pid, {}))
    payload["kind"] = "pipeline"
    try:
        req = urllib.request.Request(
            CALLBACK_URL,
            data=json.dumps(payload, ensure_ascii=False).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        urllib.request.urlopen(req, timeout=15).read()
    except Exception as exc:
        print(f"[pipe-callback] échec {pid}: {exc}", flush=True)


def _llm_local(model, system, user, max_tokens=16000):
    """Chat LiteLLM (modèle local). max_tokens élevé : local-gemma/qwen raisonnent —
    un budget trop bas renvoie un contenu vide. qwen3.5:9b a une réflexion longue ET
    variable (parfois > 4000 tokens) → défaut 16000 pour couvrir réflexion + réponse."""
    body = json.dumps(
        {
            "model": model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "max_tokens": max_tokens,
            "temperature": 0.3,
        }
    ).encode()
    req = urllib.request.Request(
        f"{LITELLM_URL}/v1/chat/completions",
        data=body,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {LITELLM_KEY}",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        data = json.loads(r.read())
    msg = (data.get("choices") or [{}])[0].get("message", {}) or {}
    content = (msg.get("content") or "").strip()
    if not content:
        raise RuntimeError(f"réponse vide de {model} (raisonnement sans contenu ?)")
    return content


def _llm_claude_text(prompt):
    """Persona Claude en mode TEXTE (sans outils) via claude -p forfait."""
    env = {
        k: v
        for k, v in os.environ.items()
        if k not in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN")
    }
    cmd = [CLAUDE, "-p", prompt, "--model", MODEL, "--output-format", "json"]
    proc = subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=TIMEOUT)
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or f"claude exit {proc.returncode}")
    return (json.loads(proc.stdout or "{}").get("result") or "").strip()


def _project_context(worktree, max_files=200, char_budget=8000):
    """Résumé compact de l'état ACTUEL du projet (arborescence git + extraits des fichiers
    clés) pour ancrer le planning sur l'EXISTANT au lieu de re-spécifier à neuf. Chaîne
    vide si le projet est quasi neuf (rien à préserver)."""
    try:
        files = [f for f in _git(worktree, "ls-files").splitlines() if f]
    except Exception:
        files = []
    files = [f for f in files if not f.startswith("_bmad-output/")]  # artefacts générés
    code = [f for f in files if not f.startswith("docs/")]
    # Projet neuf (vide ou juste un README) → pas de contexte à préserver.
    if not code or (len(code) == 1 and os.path.basename(code[0]) == "README.md"):
        return ""
    tree = "\n".join(f"- {f}" for f in files[:max_files])
    if len(files) > max_files:
        tree += f"\n- … (+{len(files) - max_files} fichiers)"
    priority = [
        f
        for f in files
        if os.path.basename(f)
        in (
            "index.html",
            "README.md",
            "package.json",
            "pyproject.toml",
            "main.py",
            "app.py",
        )
    ]
    excerpts, used = "", 0
    for rel in priority + [f for f in code if f not in priority]:
        if used >= char_budget:
            break
        try:
            with open(os.path.join(worktree, rel), encoding="utf-8") as f:
                chunk = f.read()[:3000]
        except Exception:
            continue
        excerpts += f"\n\n### {rel}\n```\n{chunk}\n```"
        used += len(chunk)
    return (
        "## État ACTUEL du projet (déjà développé — à PRÉSERVER et étendre)\n"
        f"Arborescence :\n{tree}\n{excerpts}"
    )


def _persona_content(worktree, brief, phase, feedback=""):
    """Construit le prompt (rôle + tâche + état du projet + artefacts amont + feedback) et
    appelle la LLM routée (local via LiteLLM, ou Claude via claude -p)."""
    ctx = ""
    for rel in phase["context"]:
        p = os.path.join(worktree, rel)
        if os.path.isfile(p):
            with open(p, encoding="utf-8") as f:
                ctx += f"\n\n## Artefact amont — {rel}\n{f.read()}"
    system = (
        f"Tu es {phase['persona']}, dans un pipeline automatisé sans interaction humaine. "
        f"{phase['instruction']} Réponds UNIQUEMENT par le contenu markdown du document, "
        "sans préambule ni commentaire."
    )
    user = f"# Besoin initial\n{brief}{ctx}"
    # Contexte de l'existant injecté CIBLÉ (analyste : cadre ; architecte : conçoit). PM et
    # epics héritent de l'existant via les artefacts amont (brief/architecture incrémentaux)
    # → on évite de re-dumper le code à chaque phase (coût tokens/latence).
    proj = (
        _project_context(worktree) if phase["key"] in ("analyst", "architect") else ""
    )
    if proj:
        user += (
            f"\n\n{proj}\n\n"
            "## Consigne INCRÉMENTALE (IMPORTANT)\n"
            "Le projet ci-dessus existe DÉJÀ. Conçois/spécifie en t'appuyant sur cet "
            "existant et en PRÉSERVANT ses fonctionnalités : tu AJOUTES / ÉTENDS. Ne "
            "supprime ni ne remplace une fonctionnalité existante QUE si le besoin le "
            "demande EXPLICITEMENT."
        )
    if feedback:
        user += f"\n\n## Retour à intégrer (révision)\n{feedback}"
    model = phase["model"]
    if model.startswith("local-"):
        return _llm_local(model, system, user)
    return _llm_claude_text(f"{system}\n\n{user}")


def _write_commit(worktree, rels, key):
    """Écrit déjà fait par l'appelant : add + commit des chemins donnés. Tolère un commit
    vide (révision idempotente qui régénère un contenu identique) sans passer en erreur."""
    for rel in rels:
        _git(worktree, "add", rel)
    # 'git diff --cached --quiet' sort 0 si rien n'est stagé (révision idempotente),
    # 1 s'il y a des changements. Indépendant de la locale (vs parser le message git).
    staged = subprocess.run(["git", "-C", worktree, "diff", "--cached", "--quiet"])
    if staged.returncode == 0:
        return
    _git(worktree, "commit", "-m", f"pipeline({key}): {', '.join(rels)}")


def _run_phase(worktree, brief, phase, feedback=""):
    """Persona texte mono-artefact : génère, écrit, commit."""
    content = _persona_content(worktree, brief, phase, feedback)
    dest = os.path.join(worktree, phase["artifact"])
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    with open(dest, "w", encoding="utf-8") as f:
        f.write(content if content.endswith("\n") else content + "\n")
    _write_commit(worktree, [phase["artifact"]], phase["key"])
    return phase["artifact"]


def _slugify(text):
    """Slug IDENTIQUE à slugifyStoryLabel de bmad-ui (parser.ts) : minuscules, puis
    caractères hors [a-z0-9 -] SUPPRIMÉS — surtout PAS de translittération NFKD (bmad-ui
    enlève les accents au lieu de les remplacer : 'créer' -> 'crer', pas 'creer'). Toute
    divergence ici fige le statut des stories sur 'backlog' en B3. Voir mémoire/ADR 0004."""
    text = re.sub(r"[^a-z0-9\s-]", "", text.lower())
    text = re.sub(r"\s+", "-", text.strip())
    text = re.sub(r"-+", "-", text)
    return text or "story"


def _parse_epics(md):
    """Parse '## Epic N: Titre' + '### Story N.M: Titre' → [{n, title, stories:[{n,m,title}]}]."""
    epics = []
    cur = None
    for line in md.splitlines():
        m = re.match(r"^##\s+Epic\s+(\d+)\s*:\s*(.+)$", line.strip(), re.I)
        if m:
            cur = {"n": int(m.group(1)), "title": m.group(2).strip(), "stories": []}
            epics.append(cur)
            continue
        s = re.match(r"^###\s+Story\s+(\d+)\.(\d+)\s*:\s*(.+)$", line.strip(), re.I)
        if s and cur is not None:
            cur["stories"].append(
                {
                    "n": int(s.group(1)),
                    "m": int(s.group(2)),
                    "title": s.group(3).strip(),
                }
            )
    return epics


def _project_name(worktree):
    """Nom du projet depuis le marqueur .ai-to-boost du repo principal (gitignoré, donc
    absent du worktree → on remonte via git-common-dir). Cosmétique (header sprint-status)."""
    try:
        common = _git(worktree, "rev-parse", "--git-common-dir")
        if not os.path.isabs(common):
            common = os.path.join(worktree, common)
        repo = os.path.dirname(os.path.abspath(common))
        with open(
            os.path.join(repo, ".ai-to-boost", "config.json"), encoding="utf-8"
        ) as f:
            return (json.load(f) or {}).get("name") or os.path.basename(repo)
    except Exception:
        return "projet"


def _gen_sprint_status(epics, project_name):
    """Génère un sprint-status.yaml au format STRICT lu par bmad-ui (parser regex)."""
    safe_name = " ".join(
        str(project_name).split()
    )  # aplatit \n/espaces (fichier strict)
    lines = [
        f"project: {safe_name}",
        f"project_key: {_slugify(safe_name).upper()}",
        "tracking_system: file-system",
        'story_location: "_bmad-output/implementation-artifacts/stories"',
        "",
        "development_status:",
    ]
    for e in epics:
        lines.append(f"  epic-{e['n']}: backlog")
        for s in e["stories"]:
            # numéro d'epic = epic PARENT (e['n']), pas s['n'] : un LLM qui numérote mal
            # une story (Story 2.1 sous Epic 1) ne doit pas créer un epic-2 fantôme côté UI.
            sid = f"{e['n']}-{s['m']}-{_slugify(s['title'])}"
            lines.append(f"  {sid}: backlog")
    return "\n".join(lines) + "\n"


def _run_epics_phase(worktree, brief, phase, feedback=""):
    """Persona epics : LLM produit epics.md (format canonique), sprint-status.yaml est
    DÉRIVÉ programmatiquement (garantit le format strict + cohérence des slugs)."""
    content = _persona_content(worktree, brief, phase, feedback)
    epics = _parse_epics(content)
    if not epics:
        raise RuntimeError(
            "epics.md généré sans '## Epic N:' parsable (board bmad-ui vide) — "
            "relancer (ai2b revise) ou promouvoir la phase sur Claude"
        )
    epics_rel = phase["artifact"]
    sprint_rel = "_bmad-output/implementation-artifacts/sprint-status.yaml"
    name = _project_name(worktree)
    for rel, data in (
        (epics_rel, content if content.endswith("\n") else content + "\n"),
        (sprint_rel, _gen_sprint_status(epics, name)),
    ):
        dest = os.path.join(worktree, rel)
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        with open(dest, "w", encoding="utf-8") as f:
            f.write(data)
    _write_commit(worktree, [epics_rel, sprint_rel], phase["key"])
    n_stories = sum(len(e["stories"]) for e in epics)
    return f"{epics_rel} (+sprint-status: {len(epics)} epics, {n_stories} stories)"


SPRINT_REL = "_bmad-output/implementation-artifacts/sprint-status.yaml"
IMPL_DIR = "_bmad-output/implementation-artifacts"
# Statuts story bmad-ui, par rang croissant (override markdown forward-only côté UI).
STORY_STATUSES = ("backlog", "ready-for-dev", "in-progress", "review", "done")
# Ligne story du sprint-status.yaml : '  N-M-slug: statut' (les 'epic-N:' ne matchent pas).
_STORY_LINE_RE = re.compile(r"^(\s+)(\d+-\d+-[a-z0-9-]+):\s*(\S+)\s*$")
# Ligne epic : '  epic-N: statut' (statut epic bmad-ui ∈ backlog|in-progress|done).
_EPIC_LINE_RE = re.compile(r"^(\s+)epic-(\d+):\s*\S+\s*$")


def _read_sprint_status(worktree):
    """Lit sprint-status.yaml -> liste ordonnée [{id, status}] (stories uniquement)."""
    path = os.path.join(worktree, SPRINT_REL)
    stories = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            m = _STORY_LINE_RE.match(line.rstrip("\n"))
            if m:
                stories.append({"id": m.group(2), "status": m.group(3)})
    return stories


def _set_story_status(worktree, story_id, status):
    """Réécrit la ligne 'N-M-slug: <status>' (préserve indentation + reste du fichier)."""
    path = os.path.join(worktree, SPRINT_REL)
    with open(path, encoding="utf-8") as f:
        lines = f.readlines()
    for i, line in enumerate(lines):
        m = _STORY_LINE_RE.match(line.rstrip("\n"))
        if m and m.group(2) == story_id:
            lines[i] = f"{m.group(1)}{story_id}: {status}\n"
            break
    with open(path, "w", encoding="utf-8") as f:
        f.writelines(lines)


def _rollup_epics(worktree):
    """Recalcule chaque ligne 'epic-N:' depuis l'état de ses stories : 'done' si toutes
    done, 'backlog' si toutes backlog, sinon 'in-progress' (bmad-ui n'accepte que ces 3).
    Réécrit le fichier en place. Retourne {N: statut}."""
    by_epic = {}
    for s in _read_sprint_status(worktree):
        by_epic.setdefault(s["id"].split("-")[0], []).append(s["status"])
    rollup = {}
    for n, sts in by_epic.items():
        if all(x == "done" for x in sts):
            rollup[n] = "done"
        elif all(x == "backlog" for x in sts):
            rollup[n] = "backlog"
        else:
            rollup[n] = "in-progress"
    path = os.path.join(worktree, SPRINT_REL)
    with open(path, encoding="utf-8") as f:
        lines = f.readlines()
    for i, line in enumerate(lines):
        m = _EPIC_LINE_RE.match(line.rstrip("\n"))
        if m and m.group(2) in rollup:
            lines[i] = f"{m.group(1)}epic-{m.group(2)}: {rollup[m.group(2)]}\n"
    with open(path, "w", encoding="utf-8") as f:
        f.writelines(lines)
    return rollup


def _write_story_md(worktree, story_id, status, body):
    """Fichier story lu par bmad-ui (override forward-only) : nom = id EXACT (N-M-slug.md),
    ligne 'Status: <status>'. Retourne le chemin relatif."""
    rel = f"{IMPL_DIR}/{story_id}.md"
    dest = os.path.join(worktree, rel)
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    body = (body or "").strip()
    with open(dest, "w", encoding="utf-8") as f:
        f.write(f"# Story {story_id}\n\nStatus: {status}\n\n{body}\n")
    return rel


def _story_prompt(brief, story, worktree, feedback=""):
    """Prompt dev-story : persona + 1 story ciblée + archi/epics en contexte + auto-revue."""
    n, m = story["id"].split("-")[:2]
    ctx = ""
    for rel in ("docs/architecture.md", "_bmad-output/planning-artifacts/epics.md"):
        p = os.path.join(worktree, rel)
        if os.path.isfile(p):
            with open(p, encoding="utf-8") as fh:
                ctx += f"\n\n## {rel}\n{fh.read()}"
    prompt = (
        "Tu es le Développeur BMAD (dev-story) d'un pipeline automatisé, sans interaction "
        "humaine. Implémente UNIQUEMENT la story ci-dessous, en respectant l'architecture "
        "et ses critères d'acceptation. Crée/édite les fichiers de code nécessaires dans le "
        "répertoire courant.\n\n"
        f"### Story à implémenter : {n}.{m} (id {story['id']})\n"
        f"Retrouve son titre et ses critères d'acceptation sous '## Epic {n}' / "
        f"'### Story {n}.{m}:' dans epics.md ci-dessous.\n\n"
        "Contraintes STRICTES :\n"
        "- N'implémente AUCUNE autre story que celle-ci.\n"
        "- PRÉSERVE l'EXISTANT : le projet contient déjà du code et des fonctionnalités "
        "(lis les fichiers présents AVANT d'écrire). Tu ajoutes/étends sans casser ni "
        "supprimer ce qui existe, sauf si la story demande explicitement de le retirer. "
        "N'ÉCRASE pas un fichier existant pour le réduire à ta seule story.\n"
        "- Ne modifie PAS les fichiers sous _bmad-output/ ni docs/ (gérés par le pipeline).\n"
        "- AUTO-REVUE avant de terminer : relis ton code contre les critères d'acceptation "
        "et corrige les écarts.\n"
        "- Termine par un court résumé (3-5 lignes) de ce qui a été fait.\n"
        f"\n# Besoin initial\n{brief}{ctx}"
    )
    if feedback:
        prompt += f"\n\n## Retour à intégrer (révision)\n{feedback}"
    return prompt


def _resolve_dev_model(repo, run_model=None):
    """Modèle des phases dev/doc : run > projet (.ai-to-boost/config.json:dev_model) > env
    (DEV_MODEL, défaut sonnet)."""
    if run_model:
        return run_model
    try:
        with open(
            os.path.join(repo, ".ai-to-boost", "config.json"), encoding="utf-8"
        ) as f:
            m = (json.load(f) or {}).get("dev_model")
        if m:
            return m
    except Exception:
        pass
    return DEV_MODEL


def _pipe_dev_model(pid, repo):
    with PIPELINES_LOCK:
        run_model = (PIPELINES.get(pid) or {}).get("dev_model")
    return _resolve_dev_model(repo, run_model)


def _run_tools_escalate(worktree, repo, prompt, mode, tag, dev_model, max_turns=None):
    """Appel claude -p outils sur `dev_model` (rapide) ; sur ÉCHEC DUR (exception/timeout),
    rejoue UNE fois sur le modèle fort MODEL (escalade auto). Lève si l'escalade échoue
    aussi, ou si dev_model == MODEL."""
    try:
        return _run_claude_tools(
            worktree, repo, prompt, mode, tag, model=dev_model, max_turns=max_turns
        )
    except Exception as exc:
        if dev_model == MODEL:
            raise
        print(
            f"[pipe] {tag}: échec sur {dev_model} → escalade {MODEL} ({exc})",
            flush=True,
        )
        return _run_claude_tools(
            worktree, repo, prompt, mode, tag, model=MODEL, max_turns=max_turns
        )


def _verdict(text):
    """Parse 'VERDICT: PASS|FAIL — raison'. Tolérant : PASS si verdict illisible (ne
    bloque pas faussement sur une réponse hors-format)."""
    mfail = re.search(r"VERDICT\s*[:\-]?\s*FAIL\b[ \-—:]*(.*)", text, re.I)
    if mfail:
        return False, (mfail.group(1).strip() or "non conforme")[:300]
    return True, ""


def _run_judge(worktree, prompt, model):
    """claude -p LECTURE SEULE (Read/Grep/Glob) pour un verdict QA. Retourne le texte."""
    env = {
        k: v
        for k, v in os.environ.items()
        if k not in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN")
    }
    env.setdefault("PATH", "/home/jprotin/.local/bin:/usr/bin:/bin")
    cmd = [
        CLAUDE,
        "-p",
        prompt,
        "--model",
        model,
        "--output-format",
        "json",
        "--permission-mode",
        "acceptEdits",
        "--max-turns",
        "8",
        "--allowed-tools",
        "Read",
        "Grep",
        "Glob",
        "--disallowed-tools",
        "Edit",
        "Write",
        "Bash",
        "WebFetch",
        "WebSearch",
    ]
    proc = subprocess.run(
        cmd, cwd=worktree, env=env, capture_output=True, text=True, timeout=TIMEOUT
    )
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or f"judge exit {proc.returncode}")
    return json.loads(proc.stdout or "{}").get("result", "")


def _story_section(epics_md, n, m):
    """Extrait le bloc '### Story n.m: …' (titre + critères) d'epics.md."""
    out, cap = [], False
    pat = re.compile(rf"^###\s+Story\s+{n}\.{m}\s*:", re.I)
    for ln in epics_md.splitlines():
        if pat.match(ln.strip()):
            cap = True
            out.append(ln)
            continue
        if cap and re.match(r"^#{2,3}\s+", ln.strip()):
            break
        if cap:
            out.append(ln)
    return "\n".join(out).strip()


def _judge_story(worktree, criteria, diff, summary, model):
    """Verdict QA d'une story : (ok, raison). Tolérant si verdict illisible."""
    prompt = (
        "Tu es relecteur QA INDÉPENDANT et EXIGEANT. Détermine si la story est RÉELLEMENT "
        "et CORRECTEMENT implémentée dans le code du répertoire courant (utilise Read/Grep "
        "pour inspecter les fichiers). Refuse si : critères non couverts, code incomplet "
        "(marqueurs « à faire », fonction vide, placeholder), ou existant cassé.\n\n"
        f"## Story (critères d'acceptation)\n{criteria}\n\n"
        f"## Diff produit par le dev\n{diff[:6000]}\n\n"
        f"## Résumé du dev\n{summary[:1500]}\n\n"
        "Termine IMPÉRATIVEMENT par UNE seule ligne :\n"
        "VERDICT: PASS\nou\nVERDICT: FAIL — <raison courte et actionnable>"
    )
    try:
        return _verdict(_run_judge(worktree, prompt, model))
    except Exception as exc:
        print(f"[judge] story illisible/échec ({exc}) → toléré PASS", flush=True)
        return True, ""


def _pytest_available():
    try:
        return (
            subprocess.run(
                ["python3", "-c", "import pytest"], capture_output=True, timeout=15
            ).returncode
            == 0
        )
    except Exception:
        return False


def _run_tests(worktree):
    """Exécute les tests du projet SI ses dépendances sont réellement présentes (évite les
    faux échecs : npm sans node_modules, pytest non installé). 'pass' | 'fail:<x>' | None."""
    pkg = os.path.join(worktree, "package.json")
    if os.path.isfile(pkg) and os.path.isdir(os.path.join(worktree, "node_modules")):
        try:
            with open(pkg, encoding="utf-8") as f:
                has_test = '"test"' in f.read()
        except Exception:
            has_test = False
        if has_test:
            r = subprocess.run(
                ["npm", "test", "--silent"],
                cwd=worktree,
                capture_output=True,
                text=True,
                timeout=300,
            )
            return (
                "pass"
                if r.returncode == 0
                else "fail:" + (r.stdout + r.stderr).strip()[-600:]
            )
    has_py = os.path.isfile(os.path.join(worktree, "pytest.ini")) or os.path.isfile(
        os.path.join(worktree, "pyproject.toml")
    )
    if has_py and _pytest_available():
        r = subprocess.run(
            ["python3", "-m", "pytest", "-q"],
            cwd=worktree,
            capture_output=True,
            text=True,
            timeout=300,
        )
        return (
            "pass"
            if r.returncode == 0
            else "fail:" + (r.stdout + r.stderr).strip()[-600:]
        )
    return None


def _judge_acceptance(worktree, brief, model):
    """Acceptation GLOBALE : le livrable répond-il au besoin initial ? (ok, raison)."""
    prompt = (
        "Tu es relecteur d'ACCEPTATION. Le projet du répertoire courant est censé répondre "
        "au BESOIN ci-dessous. Inspecte le code RÉELLEMENT présent (Read/Grep/Glob) et juge "
        "si un UTILISATEUR obtiendrait le résultat attendu (livrable réellement fonctionnel "
        "et démontrable, pas seulement des bouts de code épars).\n\n"
        f"## Besoin initial\n{brief}\n\n"
        "Termine IMPÉRATIVEMENT par UNE seule ligne :\n"
        "VERDICT: PASS\nou\nVERDICT: FAIL — <ce qui manque pour que ça marche>"
    )
    try:
        return _verdict(_run_judge(worktree, prompt, model))
    except Exception as exc:
        print(f"[judge] acceptation illisible/échec ({exc}) → toléré PASS", flush=True)
        return True, ""


def _run_implementation_phase(worktree, repo, brief, phase, pid, feedback=""):
    """Boucle dev-story dans le worktree pipeline (cumulatif) : chaque story non terminée
    est implémentée via claude -p AVEC outils, statut maj dans sprint-status.yaml + fichier
    story.md, 1 commit par story. Échec d'une story -> on la laisse en in-progress (rejouée
    à la reprise) et on CONTINUE. En révision, on reprend toutes les stories non 'done'."""
    stories = _read_sprint_status(worktree)
    if feedback:
        todo = [s for s in stories if s["status"] != "done"]
    else:
        todo = [s for s in stories if s["status"] not in ("review", "done")]
    if not todo:
        return "implémentation : aucune story à traiter (déjà terminées)"
    done, failed, total_cost = [], [], 0.0
    usage_by_story = {}
    timing_by_story = {}  # durée (s) par story
    dev_model = _pipe_dev_model(pid, repo)  # rapide (sonnet), escalade qualité -> opus
    try:
        with open(
            os.path.join(worktree, "_bmad-output/planning-artifacts/epics.md"),
            encoding="utf-8",
        ) as f:
            epics_md = f.read()
    except Exception:
        epics_md = ""

    # Session CHAUDE partagée par les stories de cette phase : story 1 la crée
    # (--session-id), les suivantes la reprennent (--resume) → contexte/fichiers déjà
    # lus conservés, pas de cold-start ni de ré-exploration. Repli sur une session
    # neuve si une reprise échoue.
    phase_session = str(uuid.uuid4())
    session_started = False

    for s in todo:
        sid = s["id"]
        _ts = time.monotonic()  # chrono de la story
        n, mnum = (sid.split("-") + ["", ""])[:2]
        criteria = _story_section(epics_md, n, mnum) or sid
        try:
            _set_story_status(worktree, sid, "in-progress")
            _rollup_epics(worktree)  # l'epic parent passe in-progress
            _write_commit(worktree, [SPRINT_REL], f"story {sid} in-progress")
            base_rev = _git(worktree, "rev-parse", "HEAD")

            # Tentatives : dev_model puis escalade QUALITÉ (Opus) si le juge refuse.
            models = [dev_model] + ([MODEL] if (VERIFY and dev_model != MODEL) else [])
            ok, reason, res = False, "non implémentée", None
            for am in models:
                _inject_bmad(worktree)  # skills BMAD visibles pendant le dev
                try:
                    res = _run_claude_tools(
                        worktree,
                        repo,
                        _story_prompt(brief, s, worktree, feedback),
                        "build",
                        f"pl-{pid}-{sid}",
                        model=am,
                        max_turns=STORY_MAXTURNS,
                        session_id=phase_session,
                        resume=session_started,
                        # dev sur curseur rapide → effort maîtrisé ; escalade Opus = défaut.
                        effort=DEV_EFFORT if am != MODEL else None,
                    )
                    session_started = True  # session chaude établie → reprise ensuite
                    phase_session = res.get("session_id") or phase_session
                except Exception as exc:  # échec dur -> tentative suivante (Opus)
                    reason = f"erreur d'exécution sur {am}: {exc}"
                    if (
                        session_started
                    ):  # reprise perdue → session neuve au prochain essai
                        phase_session, session_started = str(uuid.uuid4()), False
                    _eject_bmad(worktree)
                    _git(worktree, "reset", "--hard", base_rev, check=False)
                    _git(worktree, "clean", "-fd", check=False)
                    continue
                _eject_bmad(worktree)  # avant commit (ne pas committer les symlinks)
                _git(worktree, "add", "-A")
                _git(
                    worktree,
                    "commit",
                    "-m",
                    f"pipeline(story {sid}): implémentation ({am})",
                    check=False,
                )
                if not VERIFY:
                    ok = True
                    break
                diff = _git(worktree, "diff", base_rev, "HEAD", check=False)
                ok, reason = _judge_story(
                    worktree, criteria, diff, res.get("summary", ""), JUDGE_MODEL
                )
                if ok:
                    break
                if res.get("truncated"):
                    reason = f"tronqué (max_turns={STORY_MAXTURNS}), QA : {reason}"
                print(f"[verify] story {sid}: QA FAIL ({am}) — {reason}", flush=True)

            if ok:
                _set_story_status(worktree, sid, "review")
                _rollup_epics(worktree)  # epic done si toutes ses stories le sont
                _write_story_md(worktree, sid, "review", res.get("summary", ""))
                _git(worktree, "add", "-A")
                _git(
                    worktree,
                    "commit",
                    "-m",
                    f"pipeline(story {sid}): review",
                    check=False,
                )
                total_cost += res.get("cost_usd") or 0.0
                if res.get("tokens"):
                    usage_by_story[sid] = res["tokens"]
                done.append(sid)
            else:
                # Échec HONNÊTE : la story reste 'in-progress' (PAS 'review'/'done'),
                # consignée avec la raison QA. Le code partiel est conservé (rejouable).
                _set_story_status(worktree, sid, "in-progress")
                _rollup_epics(worktree)
                _git(worktree, "add", "-A")
                _git(
                    worktree,
                    "commit",
                    "-m",
                    f"pipeline(story {sid}): QA non conforme",
                    check=False,
                )
                failed.append({"id": sid, "error": "QA: " + reason})
        except Exception as exc:
            try:
                _git(worktree, "reset", "--hard", "HEAD", check=False)
                _git(worktree, "clean", "-fd", check=False)
            except Exception:
                pass
            failed.append({"id": sid, "error": str(exc)})
        timing_by_story[sid] = round(time.monotonic() - _ts, 1)
        with PIPELINES_LOCK:
            PIPELINES[pid].setdefault("stories", {})[sid] = (
                "review" if sid in done else "error"
            )

    # Acceptation GLOBALE du livrable (tests + juge), au 1er passage (pas à chaque revise).
    acceptance = None
    if VERIFY and not feedback:
        tests = _run_tests(worktree)
        acc_ok, acc_reason = _judge_acceptance(worktree, brief, ACCEPT_MODEL)
        if tests and tests.startswith("fail"):
            acc_ok = False
            acc_reason = (acc_reason + " | " if acc_reason else "") + "tests en échec"
        acceptance = {"ok": acc_ok, "reason": acc_reason, "tests": tests or "aucun"}

    with PIPELINES_LOCK:
        PIPELINES[pid]["impl_cost_usd"] = total_cost
        PIPELINES[pid]["impl_failed"] = failed
        PIPELINES[pid].setdefault("usage_by_story", {}).update(usage_by_story)
        PIPELINES[pid].setdefault("timing_by_story", {}).update(timing_by_story)
        if acceptance is not None:
            PIPELINES[pid]["acceptance"] = acceptance

    msg = f"implémentation : {len(done)}/{len(todo)} stories OK, {len(failed)} échec(s)"
    if acceptance is not None:
        msg += (
            " ; acceptation : OK"
            if acceptance["ok"]
            else f" ; acceptation : KO — {acceptance['reason']}"
        )
    return msg


def _doc_prompt(brief, worktree, feedback=""):
    """Prompt de la phase doc : documenter le CODE RÉEL (pas la spec)."""

    def _rd(rel):
        try:
            with open(os.path.join(worktree, rel), encoding="utf-8") as f:
                return f.read()
        except Exception:
            return ""

    prompt = (
        "Tu es Rédacteur technique. Le code du projet vient d'être implémenté dans le "
        "répertoire courant. Produis une DOCUMENTATION claire et à jour, en français.\n\n"
        "À FAIRE (créer ou mettre à jour) :\n"
        "- README.md (racine) : présentation, fonctionnalités, prérequis, installation, "
        "démarrage / usage, structure du projet.\n"
        "- docs/usage.md : guide utilisateur (parcours principaux, exemples concrets).\n"
        "- docs/technical.md : architecture RÉELLE du code (composants, flux, points "
        "techniques), cohérente avec ce que tu lis dans le code.\n\n"
        "RÈGLES STRICTES :\n"
        "- Explore le code (Read) pour documenter ce qui EXISTE réellement, pas la spec.\n"
        "- Ne modifie PAS le code applicatif (uniquement README.md et docs/usage|technical).\n"
        "- Ne touche PAS à _bmad-output/ ni aux docs de planning "
        "(docs/brief.md, docs/prd.md, docs/architecture.md = ENTRÉES en lecture seule).\n"
        "- Concis et factuel, sans remplissage. Termine par un court résumé.\n\n"
        f"# Besoin initial\n{brief}\n"
    )
    prd, arch = _rd("docs/prd.md"), _rd("docs/architecture.md")
    if prd:
        prompt += f"\n# PRD (référence)\n{prd[:4000]}\n"
    if arch:
        prompt += f"\n# Architecture (référence)\n{arch[:4000]}\n"
    if feedback:
        prompt += f"\n## Retour à intégrer (révision)\n{feedback}\n"
    return prompt


def _run_doc_phase(worktree, repo, brief, phase, pid, feedback=""):
    """Phase doc : claude -p AVEC outils lit le code produit + PRD/architecture et
    crée/met à jour README.md + docs/usage.md + docs/technical.md (sans toucher au code
    ni aux docs de planning), puis commit (no-op toléré)."""
    _inject_bmad(worktree)
    try:
        res = _run_tools_escalate(
            worktree,
            repo,
            _doc_prompt(brief, worktree, feedback),
            "file",
            f"pl-{pid}-doc",
            _pipe_dev_model(pid, repo),
        )
    finally:
        _eject_bmad(worktree)  # avant le commit (ne pas committer les symlinks)
    _git(worktree, "add", "-A")
    _git(worktree, "commit", "-m", "pipeline(doc): documentation", check=False)
    with PIPELINES_LOCK:
        PIPELINES[pid]["doc_tokens"] = res.get("tokens")
    return phase["artifact"]  # "README.md"


def _dispatch_phase(worktree, brief, phase, feedback="", repo=None, pid=None):
    """Aiguille selon le type : 'text', 'epics', 'implementation' ou 'documentation'."""
    if phase["kind"] == "text":
        return _run_phase(worktree, brief, phase, feedback)
    if phase["kind"] == "epics":
        return _run_epics_phase(worktree, brief, phase, feedback)
    if phase["kind"] == "implementation":
        return _run_implementation_phase(worktree, repo, brief, phase, pid, feedback)
    if phase["kind"] == "documentation":
        return _run_doc_phase(worktree, repo, brief, phase, pid, feedback)
    raise RuntimeError(f"phase '{phase['kind']}' non supportée")


def _run_pipeline(pid):
    """Exécute les phases depuis phase_index jusqu'au prochain jalon ou la fin."""
    with RUN_LOCK:
        with PIPELINES_LOCK:
            st = dict(PIPELINES[pid])
        worktree, brief = st["worktree"], st["prompt"]
        try:
            idx = st["phase_index"]
            while idx < len(PHASES):
                phase = PHASES[idx]
                _set_pipe(pid, status="running", phase=phase["key"], phase_index=idx)
                _t0 = time.monotonic()
                art = _dispatch_phase(worktree, brief, phase, repo=st["repo"], pid=pid)
                _accum_time(
                    pid, "timing_by_phase", phase["key"], time.monotonic() - _t0
                )
                with PIPELINES_LOCK:
                    PIPELINES[pid].setdefault("artifacts", {})[phase["key"]] = art
                if phase["checkpoint"]:
                    _set_pipe(
                        pid,
                        status="awaiting_approval",
                        checkpoint_index=idx,
                        phase_index=idx + 1,
                        awaiting=phase["key"],
                        last_artifact=art,
                    )
                    _pipe_callback(pid)
                    return
                idx += 1
            _finish_pipeline(pid, "done")
        except Exception as exc:
            _set_pipe(pid, status="error", error=str(exc))
            _pipe_callback(pid)


def _revise_pipeline(pid, feedback):
    """Rejoue la phase en attente avec le retour humain, puis re-jalonne."""
    with RUN_LOCK:
        with PIPELINES_LOCK:
            st = dict(PIPELINES[pid])
        try:
            idx = st["checkpoint_index"]
            phase = PHASES[idx]
            _set_pipe(pid, status="running", phase=phase["key"])
            _t0 = time.monotonic()
            art = _dispatch_phase(
                st["worktree"],
                st["prompt"],
                phase,
                feedback=feedback,
                repo=st["repo"],
                pid=pid,
            )
            _accum_time(pid, "timing_by_phase", phase["key"], time.monotonic() - _t0)
            _set_pipe(
                pid,
                status="awaiting_approval",
                awaiting=phase["key"],
                last_artifact=art,
            )
            _pipe_callback(pid)
        except Exception as exc:
            _set_pipe(pid, status="error", error=str(exc))
            _pipe_callback(pid)


def _finish_pipeline(pid, status):
    with PIPELINES_LOCK:
        st = dict(PIPELINES[pid])
    repo, worktree = st.get("repo"), st.get("worktree")
    # Jalon final approuvé : les stories en 'review' (code produit + auto-revue) passent
    # 'done' sur la branche pipeline avant de retirer le worktree (l'humain a validé).
    if status == "done" and worktree and os.path.isdir(worktree):
        try:
            sprint = os.path.join(worktree, SPRINT_REL)
            if os.path.isfile(sprint):
                for s in _read_sprint_status(worktree):
                    if s["status"] == "review":
                        _set_story_status(worktree, s["id"], "done")
                _rollup_epics(worktree)  # epics done quand toutes leurs stories le sont
                _write_commit(worktree, [SPRINT_REL], "stories done")
        except Exception as exc:
            print(f"[pipe] bump review->done {pid}: {exc}", flush=True)
    # Le worktree pl-<pid> est CONSERVÉ à 'done'/'error' : c'est le point de
    # consultation du résultat (board bmad-ui via `ai2b ui`, code via `ai2b result`).
    # Il n'est retiré qu'à 'stopped' (abandon) ou explicitement via `ai2b pipeline clean`.
    if status == "stopped" and repo and worktree:
        try:
            _git(repo, "worktree", "remove", worktree, "--force", check=False)
        except Exception:
            pass
    # diff_stat à done : message de fin utile côté canal (Telegram/web).
    extra = {}
    if status == "done" and repo and st.get("branch") and st.get("base"):
        try:
            extra["diff_stat"] = _git(
                repo, "diff", "--stat", f"{st['base']}..{st['branch']}"
            )
        except Exception:
            pass
    _set_pipe(
        pid,
        status=status,
        finished=datetime.datetime.now().isoformat(timespec="seconds"),
        **extra,
    )
    _pipe_callback(pid)


def start_pipeline(prompt, repo, return_target=None, dev_model=None):
    pid = uuid.uuid4().hex[:12]
    branch = f"pipeline/{pid}"
    worktree = os.path.join(WORKROOT, f"pl-{pid}")
    base = _base_branch(repo)
    _git(repo, "worktree", "add", worktree, "-b", branch, base)
    with PIPELINES_LOCK:
        PIPELINES[pid] = {
            "pipeline_id": pid,
            "status": "accepted",
            "repo": repo,
            "branch": branch,
            "base": base,
            "worktree": worktree,
            "prompt": prompt,
            "return_target": return_target,
            "phase_index": 0,
            "artifacts": {},
            "created": datetime.datetime.now().isoformat(timespec="seconds"),
            # Override de modèle dev/doc pour CE run (None -> projet/env). Cf. _resolve_dev_model.
            "dev_model": dev_model or None,
        }
    _persist_pipe(pid)
    threading.Thread(target=_run_pipeline, args=(pid,), daemon=True).start()
    return pid


def resume_pipeline(pid, decision):
    """decision : 'approve' | 'revise:<feedback>' | 'stop'."""
    with PIPELINES_LOCK:
        st = dict(PIPELINES.get(pid, {}))
    if not st:
        return {"error": "pipeline inconnu"}
    if st.get("status") != "awaiting_approval":
        return {"error": f"pipeline non en attente (status={st.get('status')})"}
    if decision == "approve":
        _set_pipe(pid, status="running")
        threading.Thread(target=_run_pipeline, args=(pid,), daemon=True).start()
    elif decision.startswith("revise:"):
        fb = decision[len("revise:") :].strip()
        threading.Thread(target=_revise_pipeline, args=(pid, fb), daemon=True).start()
    elif decision == "stop":
        _finish_pipeline(pid, "stopped")
    else:
        return {"error": f"décision invalide: {decision}"}
    return {"pipeline_id": pid, "status": "resuming", "decision": decision}


def _resolve_pipeline_for_target(return_target):
    """pid du pipeline en attente de validation pour ce canal (return_target), le plus
    récent. Permet de décider depuis Telegram/web sans connaître le pid (corrélation
    canal↔pipeline côté worker → n8n reste un relais fin)."""
    if not return_target:
        return None
    match = None
    with PIPELINES_LOCK:
        for (
            pid,
            st,
        ) in PIPELINES.items():  # dict ordonné par insertion → garde le dernier
            if str(st.get("return_target")) == str(return_target) and (
                st.get("status") == "awaiting_approval"
            ):
                match = pid
    return match


def resume_pipeline_by_target(decision, return_target):
    """Reprise sans pid : résout le pipeline en attente du canal puis délègue."""
    pid = _resolve_pipeline_for_target(return_target)
    if not pid:
        return {"error": "aucun pipeline en attente pour ce canal"}
    return resume_pipeline(pid, decision)


def _pipeline_state_for_target(return_target):
    """État du pipeline le plus récent d'un canal (TOUT statut) — pour /collect et /board
    Telegram, où seul le return_target (chat_id) est connu."""
    if not return_target:
        return None
    match = None
    with PIPELINES_LOCK:
        for st in PIPELINES.values():  # ordonné par insertion → garde le dernier
            if str(st.get("return_target")) == str(return_target):
                match = st
    return match


def _project_name_for_repo(repo):
    """Nom de projet enregistré pour un chemin de repo (reverse registre)."""
    for name, p in (_read_registry().get("projects") or {}).items():
        if (p or {}).get("path") == repo:
            return name
    return None


def collect_pipeline_by_target(return_target):
    """/collect Telegram : résout le projet du canal puis intègre sa branche pipeline.
    Renvoie {reply} (message prêt à afficher côté n8n)."""
    st = _pipeline_state_for_target(return_target)
    if not st:
        return {"reply": "⚠️ aucun pipeline connu pour ce canal"}
    name = _project_name_for_repo(st.get("repo") or "")
    if not name:
        return {"reply": "⚠️ projet introuvable pour ce canal"}
    res = collect_pipeline(name)
    if res.get("error"):
        return {"reply": f"⚠️ {res['error']}"}
    ds = (res.get("diff_stat") or "").strip()
    return {
        "reply": f"📥 Résultat intégré dans « {name} » ({res.get('base')})."
        + (f"\n{ds}" if ds else "")
    }


def board_text_for_target(return_target):
    """/board Telegram : résumé texte compact du board du projet du canal. {reply}."""
    st = _pipeline_state_for_target(return_target)
    if not st:
        return {"reply": "⚠️ aucun pipeline connu pour ce canal"}
    name = _project_name_for_repo(st.get("repo") or "")
    board = _project_board(name) if name else None
    if not board:
        return {"reply": "⚠️ board indisponible pour ce canal"}
    pipe = board.get("pipeline") or {}
    head = f"📊 « {name} » — statut {pipe.get('status') or '—'}"
    if pipe.get("phase"):
        head += f" / {pipe['phase']}"
    lines = [head]
    epics = board.get("epics") or []
    for e in epics:
        stories = e.get("stories") or []
        done = sum(1 for s in stories if s.get("status") == "done")
        lines.append(
            f"• Epic {e.get('n')} « {e.get('title')} » [{e.get('status')}]"
            f" — {done}/{len(stories)} stories done"
        )
    acc = pipe.get("acceptance")
    if acc:
        lines.append(
            "✅ acceptation OK" if acc.get("ok") else "⚠️ acceptation à vérifier"
        )
    if not epics:
        lines.append("(pas encore de board)")
    return {"reply": "\n".join(lines)}


def _registry_path():
    cfg = os.environ.get("XDG_CONFIG_HOME") or os.path.join(
        os.path.expanduser("~"), ".config"
    )
    return os.path.join(cfg, "ai-to-boost", "projects.json")


def _list_projects():
    """Projets du registre ai2b, enrichis du statut du dernier pipeline de chacun
    (lecture seule pour la web-app, ADR 0005 — source de vérité unique côté worker)."""
    try:
        with open(_registry_path(), encoding="utf-8") as f:
            data = json.load(f) or {}
    except Exception:
        return []
    active = data.get("active")
    out = []
    for name, p in (data.get("projects") or {}).items():
        path = p.get("path") or ""
        entry = {
            "name": name,
            "path": path,
            "base_branch": p.get("base_branch"),
            "last_pipeline": p.get("last_pipeline"),
            "active": name == active,
            "exists": bool(path) and os.path.isdir(path),
        }
        try:
            pj = os.path.join(path, ".ai-to-boost", "pipeline.json")
            with open(pj, encoding="utf-8") as f:
                st = json.load(f) or {}
            entry["pipeline_status"] = st.get("status")
            entry["pipeline_phase"] = st.get("phase")
        except Exception:
            pass
        out.append(entry)
    return out


_PROJECT_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 _-]{0,63}$")


def _valid_project_name(name):
    """Nom de projet sûr : lettres/chiffres/espace/-/_ , 1-64 car., pas de séparateur."""
    return bool(name) and bool(_PROJECT_NAME_RE.match(name)) and os.sep not in name


def _read_registry():
    try:
        with open(_registry_path(), encoding="utf-8") as f:
            return json.load(f) or {}
    except Exception:
        return {}


def _update_registry(mutator):
    """Lit, applique mutator(dict)->dict, réécrit le registre de façon atomique."""
    reg = mutator(_read_registry())
    path = _registry_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(reg, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)
    return reg


def _is_forbidden_path(target):
    for forbid in FORBID:
        if (
            target == forbid
            or target.startswith(forbid + os.sep)
            or forbid.startswith(target + os.sep)
        ):
            return True
    return False


def create_project(name, path=None):
    """Crée un projet pilotable (git + main/develop + marqueur .ai-to-boost via
    ai-to-boost-init.sh) et l'enregistre. Ne touche PAS l'actif/AGENT_DEFAULT_REPO
    (pas d'auto-restart du worker). Retourne {created, name, path} ou {error}."""
    name = (name or "").strip()
    if not _valid_project_name(name):
        return {"error": "nom invalide (lettres/chiffres/espace/-/_ , max 64)"}
    if name in (_read_registry().get("projects") or {}):
        return {"error": f"projet déjà enregistré : {name}"}

    target = os.path.realpath(
        os.path.expanduser(path or os.path.join(PROJECTS_DIR, name))
    )
    if _is_forbidden_path(target):
        return {"error": "chemin interdit (orchestrateur)"}
    if os.path.isdir(target) and os.listdir(target):
        return {"error": f"{target} existe et n'est pas vide (utiliser 'enregistrer')"}

    ident = ["-c", "user.email=ai2b@local", "-c", "user.name=ai-to-boost"]
    try:
        os.makedirs(target, exist_ok=True)
        _git(target, "init", "-q")
        with open(os.path.join(target, "README.md"), "w", encoding="utf-8") as f:
            f.write(f"# {name}\n")
        _git(target, "add", "README.md")
        _git(target, *ident, "commit", "-q", "-m", f"chore: init projet {name}")
        _git(target, "branch", "-M", "main")
        _git(target, "checkout", "-q", "-b", "develop")
        init = subprocess.run([INIT_SCRIPT, target], capture_output=True, text=True)
        if init.returncode != 0:
            return {
                "error": "init projet échoué: "
                + (init.stderr.strip() or init.stdout.strip() or "?")
            }
        if os.path.isfile(os.path.join(target, ".gitignore")):
            _git(target, "add", ".gitignore")
            _git(
                target,
                *ident,
                "commit",
                "-q",
                "-m",
                "chore: .gitignore ai-to-boost",
                check=False,
            )
    except Exception as exc:
        return {"error": f"création échouée: {exc}"}

    created = datetime.datetime.now().isoformat(timespec="seconds")

    def _mut(d):
        d.setdefault("projects", {})[name] = {
            "path": target,
            "base_branch": "develop",
            "created": created,
        }
        return d

    _update_registry(_mut)
    return {"created": True, "name": name, "path": target}


def delete_project(name):
    """Désinscrit un projet du registre (NON destructif : le répertoire reste).
    Retourne {deleted, name} ou {error}."""
    name = (name or "").strip()
    if name not in (_read_registry().get("projects") or {}):
        return {"error": "projet inconnu"}

    def _mut(d):
        (d.get("projects") or {}).pop(name, None)
        if d.get("active") == name:
            d["active"] = None
        return d

    _update_registry(_mut)
    return {"deleted": True, "name": name, "purged": False}


_EPIC_STATUS_RE = re.compile(r"^\s+epic-(\d+):\s*(\S+)")


def _read_project_text(repo, branch, worktree, rel):
    """Lit un fichier du projet dans l'ordre : worktree pl-<pid> → branche pipeline
    (git show) → working tree. Chaîne vide si introuvable."""
    if worktree:
        wp = os.path.join(worktree, rel)
        if os.path.isfile(wp):
            with open(wp, encoding="utf-8") as f:
                return f.read()
    if branch:
        try:
            return _git(repo, "show", f"{branch}:{rel}")
        except Exception:
            pass
    p = os.path.join(repo, rel)
    if os.path.isfile(p):
        with open(p, encoding="utf-8") as f:
            return f.read()
    return ""


def _latest_pipeline_branch(repo):
    """Dernière branche `pipeline/*` (par date de commit). None si aucune.
    Filet de sécurité quand .ai-to-boost/pipeline.json est perdu (gitignoré)."""
    try:
        out = _git(
            repo,
            "for-each-ref",
            "--sort=-committerdate",
            "--format=%(refname:short)",
            "refs/heads/pipeline/",
        )
        for line in out.splitlines():
            if line.strip():
                return line.strip()
    except Exception:
        pass
    return None


def _pipeline_wall_seconds(created, finished):
    """Durée mur (s) du pipeline : created→finished, ou created→maintenant si en cours.
    Inclut les attentes de validation humaine. None si created illisible."""
    if not created:
        return None
    try:
        t0 = datetime.datetime.fromisoformat(created)
        t1 = (
            datetime.datetime.fromisoformat(finished)
            if finished
            else datetime.datetime.now()
        )
        return round((t1 - t0).total_seconds(), 1)
    except Exception:
        return None


def _build_board(name, repo, branch, worktree, story_usage, pipe, story_timing=None):
    """Construit le board (epics/stories + statuts + détail + tokens + durées) depuis
    une branche/worktree donnés. `pipe` = métadonnées pipeline (dont timing_by_phase,
    created, finished). Réutilisé par le board COURANT et l'ARCHIVE."""
    story_usage = story_usage or {}
    story_timing = story_timing or {}
    if not pipe.get("artifacts"):
        pipe["artifacts"] = [
            {"key": k, "title": ARTIFACT_TITLES.get(k, k)}
            for k, rel in ARTIFACT_PATHS.items()
            if _read_project_text(repo, branch, worktree, rel).strip()
        ]

    sprint = _read_project_text(repo, branch, worktree, SPRINT_REL)
    epics_md = _read_project_text(
        repo, branch, worktree, "_bmad-output/planning-artifacts/epics.md"
    )
    story_status, epic_status = {}, {}
    for line in sprint.splitlines():
        sm = _STORY_LINE_RE.match(line.rstrip("\n"))
        if sm:
            story_status[sm.group(2)] = sm.group(3)
        em = _EPIC_STATUS_RE.match(line.rstrip("\n"))
        if em:
            epic_status[em.group(1)] = em.group(2)

    def _add(acc, tok):
        if tok:
            acc["input"] += tok.get("input") or 0
            acc["output"] += tok.get("output") or 0

    epics_out = []
    pipe_tokens = {"input": 0, "output": 0}
    for e in _parse_epics(epics_md):
        stories = []
        epic_tokens = {"input": 0, "output": 0}
        epic_dur = 0.0
        for s in e["stories"]:
            sid = f"{e['n']}-{s['m']}-{_slugify(s['title'])}"
            status = story_status.get(sid)
            if status is None:  # tolère un slug divergent : match par préfixe N-M-
                prefix = f"{e['n']}-{s['m']}-"
                for k, v in story_status.items():
                    if k.startswith(prefix):
                        sid, status = k, v
                        break
            detail = _read_project_text(repo, branch, worktree, f"{IMPL_DIR}/{sid}.md")
            tok = story_usage.get(sid)
            dur = story_timing.get(sid)
            _add(epic_tokens, tok)
            epic_dur += dur or 0
            stories.append(
                {
                    "id": sid,
                    "title": s["title"],
                    "status": status or "backlog",
                    "detail": detail,
                    "tokens": tok,
                    "duration_s": dur,
                }
            )
        _add(pipe_tokens, epic_tokens)
        epics_out.append(
            {
                "n": e["n"],
                "title": e["title"],
                "status": epic_status.get(str(e["n"]), "backlog"),
                "stories": stories,
                "tokens": epic_tokens
                if (epic_tokens["input"] or epic_tokens["output"])
                else None,
                "duration_s": round(epic_dur, 1) if epic_dur else None,
            }
        )
    phases = [
        {"key": p["key"], "persona": p["persona"], "model": p["model"]} for p in PHASES
    ]
    pipe["tokens"] = (
        pipe_tokens if (pipe_tokens["input"] or pipe_tokens["output"]) else None
    )
    # Durées : par phase (temps IA actif), total actif, total mur (inclut attentes).
    tbp = pipe.get("timing_by_phase") or {}
    pipe["phase_timings"] = [
        {"key": p["key"], "seconds": tbp[p["key"]]} for p in PHASES if p["key"] in tbp
    ]
    pipe["active_s"] = round(sum(tbp.values()), 1) if tbp else None
    pipe["duration_s"] = _pipeline_wall_seconds(
        pipe.get("created"), pipe.get("finished")
    )
    return {"name": name, "pipeline": pipe, "epics": epics_out, "phases": phases}


def _project_board(name):
    """Board d'un projet (epics/stories + statuts + détail) pour la web-app (ADR 0005).
    Source : sprint-status.yaml + epics.md du worktree/branche/working tree. None si projet
    inconnu/absent."""
    try:
        with open(_registry_path(), encoding="utf-8") as f:
            p = ((json.load(f) or {}).get("projects") or {}).get(name) or {}
    except Exception:
        p = {}
    repo = p.get("path") or ""
    if not repo or not os.path.isdir(repo):
        return None

    pipe, branch, worktree = {}, None, None
    story_usage, pj = {}, {}
    try:
        with open(
            os.path.join(repo, ".ai-to-boost", "pipeline.json"), encoding="utf-8"
        ) as f:
            pj = json.load(f) or {}
        branch, worktree = pj.get("branch"), pj.get("worktree")
        story_usage = pj.get("usage_by_story") or {}
        pipe = {
            "id": pj.get("pipeline_id"),
            "status": pj.get("status"),
            "phase": pj.get("phase"),
            "branch": branch,
            "prompt": pj.get("prompt"),  # besoin original (description du projet)
            "awaiting": pj.get("awaiting"),
            "acceptance": pj.get("acceptance"),  # gate de vérification (juge + tests)
            "artifacts": [
                {"key": k, "title": ARTIFACT_TITLES.get(k, k)}
                for k in ARTIFACT_PATHS  # ordre des phases
                if k in (pj.get("artifacts") or {})
            ],
            # Durées (Phase 1 timings) : le board dérive duration_s/active_s/phase_timings.
            "timing_by_phase": pj.get("timing_by_phase") or {},
            "created": pj.get("created"),
            "finished": pj.get("finished"),
        }
    except Exception:
        pass

    # Filet : pipeline.json perdu (gitignoré) → retrouver la dernière branche pipeline/*
    # pour éviter un board vide qui retomberait sur le working tree de develop.
    if not branch:
        branch = _latest_pipeline_branch(repo)
        if branch and not pipe.get("branch"):
            pipe["branch"] = branch

    return _build_board(
        name, repo, branch, worktree, story_usage, pipe, pj.get("timing_by_story")
    )


def _project_repo(name):
    """Chemin du repo d'un projet du registre (None si inconnu/absent)."""
    try:
        with open(_registry_path(), encoding="utf-8") as f:
            p = ((json.load(f) or {}).get("projects") or {}).get(name) or {}
    except Exception:
        p = {}
    repo = p.get("path") or ""
    return repo if repo and os.path.isdir(repo) else None


def _pipeline_history(name):
    """Liste des runs archivés d'un projet (snapshots .ai-to-boost/pipelines/*.json),
    du plus récent au plus ancien. Tokens = somme de usage_by_story du snapshot."""
    repo = _project_repo(name)
    if repo is None:
        return None
    hdir = os.path.join(repo, ".ai-to-boost", "pipelines")
    runs = []
    try:
        files = [f for f in os.listdir(hdir) if f.endswith(".json")]
    except Exception:
        files = []
    for fn in files:
        try:
            with open(os.path.join(hdir, fn), encoding="utf-8") as f:
                st = json.load(f) or {}
        except Exception:
            continue
        tin = tout = 0
        for tok in (st.get("usage_by_story") or {}).values():
            tin += (tok or {}).get("input") or 0
            tout += (tok or {}).get("output") or 0
        runs.append(
            {
                "id": st.get("pipeline_id"),
                "prompt": st.get("prompt"),
                "status": st.get("status"),
                "created": st.get("created"),
                "finished": st.get("finished"),
                "branch": st.get("branch"),
                "tokens": {"input": tin, "output": tout} if (tin or tout) else None,
                "duration_s": _pipeline_wall_seconds(
                    st.get("created"), st.get("finished")
                ),
            }
        )
    runs.sort(key=lambda r: r.get("created") or "", reverse=True)
    return runs


def _pipeline_snapshot(name, pid):
    """Board read-only d'un run archivé (lu depuis SA branche, worktree ignoré car
    souvent retiré). None si projet/snapshot inconnu."""
    repo = _project_repo(name)
    if repo is None:
        return None
    try:
        with open(
            os.path.join(repo, ".ai-to-boost", "pipelines", f"{pid}.json"),
            encoding="utf-8",
        ) as f:
            st = json.load(f) or {}
    except Exception:
        return None
    pipe = {
        "id": st.get("pipeline_id"),
        "status": st.get("status"),
        "phase": st.get("phase"),
        "branch": st.get("branch"),
        "prompt": st.get("prompt"),
        "created": st.get("created"),
        "finished": st.get("finished"),
        "awaiting": st.get("awaiting"),
        "acceptance": st.get("acceptance"),
        "artifacts": [
            {"key": k, "title": ARTIFACT_TITLES.get(k, k)}
            for k in ARTIFACT_PATHS
            if k in (st.get("artifacts") or {})
        ],
        "timing_by_phase": st.get("timing_by_phase") or {},
    }
    # Archive : lecture depuis la branche (immuable), pas du worktree (réutilisé/retiré).
    return _build_board(
        name,
        repo,
        st.get("branch"),
        None,
        st.get("usage_by_story"),
        pipe,
        st.get("timing_by_story"),
    )


def project_artifact(name, key, pid=None):
    """Contenu Markdown d'un artefact (brief/prd/architecture/epics) pour relecture
    webui. Clé restreinte (pas de lecture de chemin arbitraire). Retourne {key, title,
    content} ou {error}."""
    if key not in ARTIFACT_PATHS:
        return {"error": "artefact inconnu"}
    try:
        with open(_registry_path(), encoding="utf-8") as f:
            p = ((json.load(f) or {}).get("projects") or {}).get(name) or {}
    except Exception:
        p = {}
    repo = p.get("path") or ""
    if not repo or not os.path.isdir(repo):
        return {"error": "projet inconnu"}

    branch = worktree = None
    rel = ARTIFACT_PATHS[key]
    # pid donné -> run archivé (lecture depuis sa branche) ; sinon pipeline courant.
    src = (
        os.path.join(repo, ".ai-to-boost", "pipelines", f"{pid}.json")
        if pid
        else os.path.join(repo, ".ai-to-boost", "pipeline.json")
    )
    try:
        with open(src, encoding="utf-8") as f:
            pj = json.load(f) or {}
        branch = pj.get("branch")
        worktree = None if pid else pj.get("worktree")  # archive = branche seule
        # On garde le chemin CANONIQUE ARTIFACT_PATHS[key] : la valeur stockée dans
        # artifacts{} peut être décorative (ex. epics : "epics.md (+sprint-status…)").
    except Exception:
        if pid:
            return {"error": "run inconnu"}
    if not branch:
        branch = _latest_pipeline_branch(repo)

    return {
        "key": key,
        "title": ARTIFACT_TITLES.get(key, key),
        "content": _read_project_text(repo, branch, worktree, rel),
    }


def collect_pipeline(name, do_clean=False):
    """Intègre la branche pipeline d'un projet dans sa base (merge --no-ff).
    Réplique `ai2b collect` côté worker (ADR 0005). Retourne {merged, branch, base,
    diff_stat, cleaned} ou {error}."""
    try:
        with open(_registry_path(), encoding="utf-8") as f:
            p = ((json.load(f) or {}).get("projects") or {}).get(name) or {}
    except Exception:
        p = {}
    repo = p.get("path") or ""
    if not repo or not os.path.isdir(repo):
        return {"error": "projet inconnu"}

    branch = base = worktree = None
    try:
        with open(
            os.path.join(repo, ".ai-to-boost", "pipeline.json"), encoding="utf-8"
        ) as f:
            pj = json.load(f) or {}
        branch, base, worktree = pj.get("branch"), pj.get("base"), pj.get("worktree")
    except Exception:
        pass
    if not branch:
        branch = _latest_pipeline_branch(repo)
    if not base:
        try:
            base = _base_branch(repo)
        except Exception:
            base = None
    if not branch or not base:
        return {"error": "branche pipeline ou base introuvable"}

    try:
        _git(repo, "rev-parse", "--verify", branch)
    except Exception:
        return {"error": f"branche {branch} introuvable (déjà nettoyée ?)"}

    # Garde-fou : aucune modif SUIVIE en attente (le merge bascule de branche). Les
    # fichiers non suivis (ex. .ai-to-boost/ gitignoré) ne bloquent pas → ignorés.
    if _git(repo, "status", "--porcelain", "--untracked-files=no"):
        return {
            "error": f"copie de travail de '{name}' a des modifs non commitées — "
            "committe/stash avant l'intégration"
        }

    try:
        _git(repo, "checkout", base)
    except Exception as exc:
        return {"error": f"checkout {base} impossible: {exc}"}

    merge = subprocess.run(
        [
            "git",
            "-C",
            repo,
            "merge",
            "--no-ff",
            "--no-edit",
            "-m",
            f"Merge {branch} into {base} — pipeline BMAD (webui collect)",
            branch,
        ],
        capture_output=True,
        text=True,
    )
    if merge.returncode != 0:
        _git(repo, "merge", "--abort", check=False)
        return {
            "error": f"conflits de merge — résoudre à la main : "
            f"git -C {repo} merge --no-ff {branch}"
        }

    cleaned = False
    if do_clean:
        if worktree:
            _git(repo, "worktree", "remove", worktree, "--force", check=False)
        _git(repo, "branch", "-d", branch, check=False)  # -d : seulement si bien mergée
        cleaned = True

    try:
        diff_stat = _git(repo, "diff", "--stat", "HEAD^1", "HEAD")
    except Exception:
        diff_stat = ""
    return {
        "merged": True,
        "branch": branch,
        "base": base,
        "cleaned": cleaned,
        "diff_stat": diff_stat,
    }


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def _send(self, code, payload):
        body = json.dumps(payload, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _auth_ok(self):
        return TOKEN and self.headers.get("Authorization") == f"Bearer {TOKEN}"

    def do_GET(self):
        if self.path == "/health":
            self._send(200, {"status": "ok", "model": MODEL})
            return
        if self.path == "/projects":
            if not self._auth_ok():
                self._send(401, {"error": "unauthorized"})
                return
            self._send(200, {"projects": _list_projects()})
            return
        if self.path.startswith("/projects/") and self.path.endswith("/board"):
            if not self._auth_ok():
                self._send(401, {"error": "unauthorized"})
                return
            name = urllib.parse.unquote(
                self.path[len("/projects/") : -len("/board")].strip("/")
            )
            board = _project_board(name)
            self._send(200, board) if board else self._send(
                404, {"error": "projet inconnu"}
            )
            return
        if self.path.startswith("/projects/") and "/history" in self.path:
            if not self._auth_ok():
                self._send(401, {"error": "unauthorized"})
                return
            rest = self.path[len("/projects/") :]
            name, _, tail = rest.partition("/history")
            name = urllib.parse.unquote(name.strip("/"))
            tail = tail.strip("/")  # "" | "<pid>" | "<pid>/artifact/<key>"
            if not tail:
                runs = _pipeline_history(name)
                if runs is None:
                    self._send(404, {"error": "projet inconnu"})
                else:
                    self._send(200, {"runs": runs})
                return
            if "/artifact/" in tail:
                pid, _, key = tail.partition("/artifact/")
                res = project_artifact(
                    name,
                    urllib.parse.unquote(key.strip("/")),
                    pid=urllib.parse.unquote(pid.strip("/")),
                )
                code = 200
                if res.get("error") in ("projet inconnu", "run inconnu"):
                    code = 404
                elif res.get("error"):
                    code = 400
                self._send(code, res)
                return
            board = _pipeline_snapshot(name, urllib.parse.unquote(tail))
            self._send(200, board) if board else self._send(
                404, {"error": "run inconnu"}
            )
            return
        if self.path.startswith("/projects/") and "/artifact/" in self.path:
            if not self._auth_ok():
                self._send(401, {"error": "unauthorized"})
                return
            rest = self.path[len("/projects/") :]
            name, _, key = rest.partition("/artifact/")
            res = project_artifact(
                urllib.parse.unquote(name.strip("/")),
                urllib.parse.unquote(key.strip("/")),
            )
            code = 200
            if res.get("error") == "projet inconnu":
                code = 404
            elif res.get("error"):
                code = 400
            self._send(code, res)
            return
        if self.path.startswith("/jobs/"):
            if not self._auth_ok():
                self._send(401, {"error": "unauthorized"})
                return
            job_id = self.path.split("/jobs/", 1)[1]
            with JOBS_LOCK:
                job = JOBS.get(job_id)
            if not job:
                self._send(404, {"error": "job inconnu"})
                return
            self._send(200, job)
            return
        if self.path.startswith("/pipelines/"):
            if not self._auth_ok():
                self._send(401, {"error": "unauthorized"})
                return
            pid = self.path.split("/pipelines/", 1)[1].strip("/")
            with PIPELINES_LOCK:
                st = PIPELINES.get(pid)
            self._send(200, st) if st else self._send(
                404, {"error": "pipeline inconnu"}
            )
            return
        self._send(404, {"error": "not found"})

    def _read_json(self):
        length = int(self.headers.get("Content-Length", "0"))
        return json.loads(self.rfile.read(length) or b"{}")

    def do_POST(self):
        if not self._auth_ok():
            self._send(401, {"error": "unauthorized"})
            return
        if self.path == "/jobs":
            self._post_job()
        elif self.path == "/projects":
            self._post_project_create()
        elif self.path == "/pipelines":
            self._post_pipeline()
        elif self.path == "/pipelines/resume":
            self._post_resume_by_target()
        elif self.path == "/pipelines/collect":
            self._post_collect_by_target()
        elif self.path == "/pipelines/board":
            self._post_board_by_target()
        elif self.path.startswith("/pipelines/") and self.path.endswith("/resume"):
            self._post_resume()
        elif self.path.startswith("/projects/") and self.path.endswith("/resume"):
            self._post_project_resume()
        elif self.path.startswith("/projects/") and self.path.endswith("/run"):
            self._post_project_run()
        elif self.path.startswith("/projects/") and self.path.endswith("/collect"):
            self._post_project_collect()
        else:
            self._send(404, {"error": "not found"})

    def do_DELETE(self):
        if not self._auth_ok():
            self._send(401, {"error": "unauthorized"})
            return
        if self.path.startswith("/projects/"):
            name = urllib.parse.unquote(self.path[len("/projects/") :].strip("/"))
            res = delete_project(name)
            self._send(400 if res.get("error") else 200, res)
            return
        self._send(404, {"error": "not found"})

    def _post_project_create(self):
        """Crée + enregistre un projet pilotable (réplique ai2b new, sans restart)."""
        try:
            data = self._read_json()
        except Exception as exc:
            self._send(400, {"error": f"bad json: {exc}"})
            return
        res = create_project(data.get("name") or "", data.get("path") or None)
        self._send(400 if res.get("error") else 201, res)

    def _post_project_collect(self):
        """Intègre la branche pipeline d'un projet → sa base (merge --no-ff)."""
        name = urllib.parse.unquote(
            self.path[len("/projects/") : -len("/collect")].strip("/")
        )
        try:
            data = self._read_json()
        except Exception as exc:
            self._send(400, {"error": f"bad json: {exc}"})
            return
        res = collect_pipeline(name, bool(data.get("clean")))
        self._send(400 if res.get("error") else 200, res)

    def _post_project_resume(self):
        """Décision de jalon sur le pipeline courant d'un projet (résout le pid)."""
        name = urllib.parse.unquote(
            self.path[len("/projects/") : -len("/resume")].strip("/")
        )
        try:
            data = self._read_json()
        except Exception as exc:
            self._send(400, {"error": f"bad json: {exc}"})
            return
        decision = (data.get("decision") or "").strip()
        pid = None
        try:
            with open(_registry_path(), encoding="utf-8") as f:
                p = ((json.load(f) or {}).get("projects") or {}).get(name) or {}
            with open(
                os.path.join(p["path"], ".ai-to-boost", "pipeline.json"),
                encoding="utf-8",
            ) as f:
                pid = (json.load(f) or {}).get("pipeline_id")
        except Exception:
            pid = None
        if not pid:
            self._send(404, {"error": "aucun pipeline pour ce projet"})
            return
        res = resume_pipeline(pid, decision)
        self._send(400 if res.get("error") else 202, res)

    def _post_project_run(self):
        """Lance un pipeline sur un projet nommé (résout le repo via le registre)."""
        name = urllib.parse.unquote(
            self.path[len("/projects/") : -len("/run")].strip("/")
        )
        try:
            data = self._read_json()
        except Exception as exc:
            self._send(400, {"error": f"bad json: {exc}"})
            return
        prompt = (data.get("prompt") or "").strip()
        if not prompt:
            self._send(400, {"error": "missing 'prompt'"})
            return
        try:
            with open(_registry_path(), encoding="utf-8") as f:
                p = ((json.load(f) or {}).get("projects") or {}).get(name) or {}
        except Exception:
            p = {}
        if not p.get("path"):
            self._send(404, {"error": "projet inconnu"})
            return
        try:
            repo = _validate_repo(p["path"])
        except ValueError as exc:
            self._send(400, {"error": str(exc)})
            return
        # Garde anti-pipeline-concurrent : un seul pipeline actif par projet.
        try:
            with open(
                os.path.join(repo, ".ai-to-boost", "pipeline.json"), encoding="utf-8"
            ) as f:
                cur = (json.load(f) or {}).get("status")
        except Exception:
            cur = None
        if cur in ("accepted", "running", "awaiting_approval"):
            self._send(409, {"error": "un pipeline est déjà en cours sur ce projet"})
            return
        pid = start_pipeline(
            prompt, repo, data.get("return_target"), dev_model=data.get("dev_model")
        )
        self._send(202, {"pipeline_id": pid, "status": "accepted"})

    def _post_job(self):
        try:
            data = self._read_json()
        except Exception as exc:
            self._send(400, {"error": f"bad json: {exc}"})
            return
        prompt = (data.get("prompt") or "").strip()
        if not prompt:
            self._send(400, {"error": "missing 'prompt'"})
            return
        try:
            repo = _validate_repo(data.get("repo") or DEFAULT_REPO)
        except ValueError as exc:
            self._send(400, {"error": str(exc)})
            return
        mode = data.get("mode") if data.get("mode") in ("file", "build") else "file"
        job_id = uuid.uuid4().hex[:12]
        with JOBS_LOCK:
            JOBS[job_id] = {
                "job_id": job_id,
                "status": "accepted",
                "repo": repo,
                "mode": mode,
                "return_target": data.get("return_target"),
            }
        threading.Thread(
            target=run_job, args=(job_id, prompt, repo, mode), daemon=True
        ).start()
        self._send(202, {"job_id": job_id, "status": "accepted"})

    def _post_pipeline(self):
        try:
            data = self._read_json()
        except Exception as exc:
            self._send(400, {"error": f"bad json: {exc}"})
            return
        prompt = (data.get("prompt") or "").strip()
        if not prompt:
            self._send(400, {"error": "missing 'prompt'"})
            return
        try:
            repo = _validate_repo(data.get("repo") or DEFAULT_REPO)
        except ValueError as exc:
            self._send(400, {"error": str(exc)})
            return
        pid = start_pipeline(
            prompt, repo, data.get("return_target"), dev_model=data.get("dev_model")
        )
        self._send(202, {"pipeline_id": pid, "status": "accepted"})

    def _post_resume(self):
        pid = self.path.split("/pipelines/", 1)[1].rsplit("/resume", 1)[0].strip("/")
        try:
            data = self._read_json()
        except Exception as exc:
            self._send(400, {"error": f"bad json: {exc}"})
            return
        decision = (data.get("decision") or "").strip()
        res = resume_pipeline(pid, decision)
        self._send(400 if res.get("error") else 202, res)

    def _post_resume_by_target(self):
        """Reprise sans pid (depuis un canal) : résout via return_target."""
        try:
            data = self._read_json()
        except Exception as exc:
            self._send(400, {"error": f"bad json: {exc}"})
            return
        decision = (data.get("decision") or "").strip()
        res = resume_pipeline_by_target(decision, data.get("return_target"))
        self._send(400 if res.get("error") else 202, res)

    def _post_collect_by_target(self):
        """/collect depuis un canal : résout le projet via return_target puis intègre."""
        try:
            data = self._read_json()
        except Exception as exc:
            self._send(400, {"error": f"bad json: {exc}"})
            return
        self._send(200, collect_pipeline_by_target(data.get("return_target")))

    def _post_board_by_target(self):
        """/board depuis un canal : résumé texte du board du projet via return_target."""
        try:
            data = self._read_json()
        except Exception as exc:
            self._send(400, {"error": f"bad json: {exc}"})
            return
        self._send(200, board_text_for_target(data.get("return_target")))


def _rehydrate_pipelines():
    """Au démarrage : recharge en mémoire les pipelines persistés (pipeline.json de
    chaque projet du registre) — `PIPELINES` est volatil, un redémarrage du worker les
    perd sinon. Retourne la liste des pid à REPRENDRE : ceux laissés en cours
    (running/accepted) avec worktree présent (interrompus par l'arrêt du worker ; les
    phases sont idempotentes/cumulatives). Les `awaiting_approval` restent en attente ;
    un worktree disparu → marqué `error` plutôt que faussement « running »."""
    to_resume = []
    for name, p in (_read_registry().get("projects") or {}).items():
        repo = (p or {}).get("path") or ""
        try:
            with open(
                os.path.join(repo, ".ai-to-boost", "pipeline.json"), encoding="utf-8"
            ) as f:
                st = json.load(f) or {}
        except Exception:
            continue
        pid = st.get("pipeline_id")
        if not pid:
            continue
        with PIPELINES_LOCK:
            if pid in PIPELINES:
                continue
            PIPELINES[pid] = st
        _persist_pipe(pid)  # snapshot le run courant (alimente l'archive F6)
        if st.get("status") in ("running", "accepted"):
            if os.path.isdir(st.get("worktree") or ""):
                to_resume.append(pid)
            else:
                _set_pipe(
                    pid,
                    status="error",
                    error="worktree absent au redémarrage (pipeline interrompu)",
                )
    return to_resume


def main():
    if not TOKEN:
        raise SystemExit("AGENT_TOKEN requis (cf. .env)")
    if os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN"):
        raise SystemExit(
            "ANTHROPIC_API_KEY/AUTH_TOKEN présente : refus de démarrer (forfait only)"
        )
    os.makedirs(WORKROOT, exist_ok=True)
    for pid in _rehydrate_pipelines():
        print(f"[rehydrate] reprise du pipeline interrompu {pid}", flush=True)
        threading.Thread(target=_run_pipeline, args=(pid,), daemon=True).start()
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    print(
        f"claude-agent sur {HOST}:{PORT} (modèle {MODEL}, repos interdits: {FORBID})",
        flush=True,
    )
    server.serve_forever()


if __name__ == "__main__":
    main()
