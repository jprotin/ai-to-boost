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
TIMEOUT = int(os.environ.get("AGENT_TIMEOUT", "600"))
MAXTURNS = int(os.environ.get("AGENT_MAXTURNS", "30"))
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


def _run_claude_tools(worktree, repo, prompt, mode, tag):
    """Cœur d'appel `claude -p` AVEC outils (Read/Edit/Write[/Bash]) sous garde-fou + RAG,
    dans un worktree donné. NE gère NI le worktree, NI BMAD, NI le commit, NI RUN_LOCK :
    l'appelant s'en charge (réutilisé par run_job one-shot ET la boucle dev-story du
    pipeline). Retourne {summary, cost_usd, audit}. Lève en cas d'échec claude."""
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
        MODEL,
        "--output-format",
        "json",
        "--permission-mode",
        perm_mode,
        "--max-turns",
        str(MAXTURNS),
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
    proc = subprocess.run(
        cmd, cwd=worktree, env=env, capture_output=True, text=True, timeout=TIMEOUT
    )
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or f"claude exit {proc.returncode}")
    result = json.loads(proc.stdout or "{}")
    audit = []
    if os.path.exists(audit_log):
        with open(audit_log, encoding="utf-8") as f:
            audit = [line.rstrip("\n") for line in f if line.strip()]
    return {
        "summary": result.get("result", ""),
        "cost_usd": result.get("total_cost_usd"),
        "audit": audit,
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

PHASES = [
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
            "Reste cohérent avec le PRD."
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
            "Numérote les epics 1..N et les stories N.M en continu. 2 à 4 epics, "
            "2 à 5 stories par epic. Titres courts et explicites."
        ),
    },
    {
        "key": "implementation",
        "persona": "Développeur BMAD (dev-story)",
        "model": "claude",  # code -> Claude (claude -p, forfait), AVEC outils
        "kind": "implementation",  # boucle par story ; prompt construit dans _story_prompt
        "artifact": None,
        "context": ["docs/architecture.md", "_bmad-output/planning-artifacts/epics.md"],
        "checkpoint": True,  # jalon final unique : revue humaine de la branche complète
        "instruction": "",
    },
]


def _set_pipe(pid, **kw):
    with PIPELINES_LOCK:
        PIPELINES[pid].update(kw)
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


def _llm_local(model, system, user, max_tokens=4000):
    """Chat LiteLLM (modèle local). max_tokens élevé : local-gemma/qwen raisonnent —
    un budget trop bas renvoie un contenu vide."""
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


def _persona_content(worktree, brief, phase, feedback=""):
    """Construit le prompt (rôle + tâche + artefacts amont + feedback) et appelle la LLM
    routée (local via LiteLLM, ou Claude via claude -p). Retourne le contenu markdown."""
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
        "- Ne modifie PAS les fichiers sous _bmad-output/ ni docs/ (gérés par le pipeline).\n"
        "- AUTO-REVUE avant de terminer : relis ton code contre les critères d'acceptation "
        "et corrige les écarts.\n"
        "- Termine par un court résumé (3-5 lignes) de ce qui a été fait.\n"
        f"\n# Besoin initial\n{brief}{ctx}"
    )
    if feedback:
        prompt += f"\n\n## Retour à intégrer (révision)\n{feedback}"
    return prompt


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
    done, failed, total_cost = [], [], 0.0
    for s in todo:
        sid = s["id"]
        try:
            _set_story_status(worktree, sid, "in-progress")
            _rollup_epics(worktree)  # l'epic parent passe in-progress
            _write_commit(worktree, [SPRINT_REL], f"story {sid} in-progress")
            _inject_bmad(worktree)  # skills BMAD visibles pendant le dev
            try:
                res = _run_claude_tools(
                    worktree,
                    repo,
                    _story_prompt(brief, s, worktree, feedback),
                    "build",
                    f"pl-{pid}-{sid}",
                )
            finally:
                _eject_bmad(
                    worktree
                )  # avant tout commit (ne pas committer les symlinks)
            _set_story_status(worktree, sid, "review")
            _rollup_epics(worktree)  # epic done si toutes ses stories le sont
            _write_story_md(worktree, sid, "review", res.get("summary", ""))
            _git(worktree, "add", "-A")
            _git(worktree, "commit", "-m", f"pipeline(story {sid}): implémentation")
            total_cost += res.get("cost_usd") or 0.0
            done.append(sid)
        except Exception as exc:
            # Jette le travail partiel (timeout/erreur) mais garde le commit 'in-progress' :
            # la story sera rejouée à la reprise. Le worktree pipeline est isolé.
            try:
                _git(worktree, "reset", "--hard", "HEAD", check=False)
                _git(worktree, "clean", "-fd", check=False)
            except Exception:
                pass
            failed.append({"id": sid, "error": str(exc)})
        with PIPELINES_LOCK:
            PIPELINES[pid].setdefault("stories", {})[sid] = (
                "review" if sid in done else "error"
            )
    with PIPELINES_LOCK:
        PIPELINES[pid]["impl_cost_usd"] = total_cost
        PIPELINES[pid]["impl_failed"] = failed
    if not todo:
        return "implémentation : aucune story à traiter (déjà terminées)"
    return (
        f"implémentation : {len(done)}/{len(todo)} stories en review, "
        f"{len(failed)} échec(s)"
    )


def _dispatch_phase(worktree, brief, phase, feedback="", repo=None, pid=None):
    """Aiguille selon le type de phase : 'text', 'epics' ou 'implementation' (boucle dev)."""
    if phase["kind"] == "text":
        return _run_phase(worktree, brief, phase, feedback)
    if phase["kind"] == "epics":
        return _run_epics_phase(worktree, brief, phase, feedback)
    if phase["kind"] == "implementation":
        return _run_implementation_phase(worktree, repo, brief, phase, pid, feedback)
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
                art = _dispatch_phase(worktree, brief, phase, repo=st["repo"], pid=pid)
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
            art = _dispatch_phase(
                st["worktree"],
                st["prompt"],
                phase,
                feedback=feedback,
                repo=st["repo"],
                pid=pid,
            )
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
    _set_pipe(pid, status=status, **extra)
    _pipe_callback(pid)


def start_pipeline(prompt, repo, return_target=None):
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
    try:
        with open(
            os.path.join(repo, ".ai-to-boost", "pipeline.json"), encoding="utf-8"
        ) as f:
            pj = json.load(f) or {}
        branch, worktree = pj.get("branch"), pj.get("worktree")
        pipe = {
            "id": pj.get("pipeline_id"),
            "status": pj.get("status"),
            "phase": pj.get("phase"),
            "branch": branch,
        }
    except Exception:
        pass

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

    epics_out = []
    for e in _parse_epics(epics_md):
        stories = []
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
            stories.append(
                {
                    "id": sid,
                    "title": s["title"],
                    "status": status or "backlog",
                    "detail": detail,
                }
            )
        epics_out.append(
            {
                "n": e["n"],
                "title": e["title"],
                "status": epic_status.get(str(e["n"]), "backlog"),
                "stories": stories,
            }
        )
    return {"name": name, "pipeline": pipe, "epics": epics_out}


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
        elif self.path == "/pipelines":
            self._post_pipeline()
        elif self.path == "/pipelines/resume":
            self._post_resume_by_target()
        elif self.path.startswith("/pipelines/") and self.path.endswith("/resume"):
            self._post_resume()
        else:
            self._send(404, {"error": "not found"})

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
        pid = start_pipeline(prompt, repo, data.get("return_target"))
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


def main():
    if not TOKEN:
        raise SystemExit("AGENT_TOKEN requis (cf. .env)")
    if os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN"):
        raise SystemExit(
            "ANTHROPIC_API_KEY/AUTH_TOKEN présente : refus de démarrer (forfait only)"
        )
    os.makedirs(WORKROOT, exist_ok=True)
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    print(
        f"claude-agent sur {HOST}:{PORT} (modèle {MODEL}, repos interdits: {FORBID})",
        flush=True,
    )
    server.serve_forever()


if __name__ == "__main__":
    main()
