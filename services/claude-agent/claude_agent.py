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


def run_job(job_id, prompt, repo, mode="file"):
    branch = f"agent/{job_id}"
    worktree = os.path.join(WORKROOT, job_id)
    audit_log = os.path.join(WORKROOT, f"{job_id}.audit.log")
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
            env = {
                k: v
                for k, v in os.environ.items()
                if k not in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN")
            }
            env.setdefault("PATH", "/home/jprotin/.local/bin:/usr/bin:/bin")
            env["AGENT_AUDIT_LOG"] = audit_log
            # RAG double-portée : MCP commun + projet (lecture qdrant-find).
            rag_cfg, rag_tools = _rag_mcp(repo)
            mcp_file = os.path.join(WORKROOT, f"{job_id}.mcp.json")
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
                cmd,
                cwd=worktree,
                env=env,
                capture_output=True,
                text=True,
                timeout=TIMEOUT,
            )
            if proc.returncode != 0:
                raise RuntimeError(
                    proc.stderr.strip() or f"claude exit {proc.returncode}"
                )
            result = json.loads(proc.stdout or "{}")
            summary = result.get("result", "")

            _eject_bmad(worktree)  # retire les symlinks BMAD avant de committer
            _git(worktree, "add", "-A")
            changed = bool(_git(worktree, "status", "--porcelain"))
            if changed:
                _git(
                    worktree,
                    "commit",
                    "-m",
                    f"agent({job_id}): {prompt[:60]}",
                )
            diff_stat = _git(repo, "diff", "--stat", f"{base}..{branch}")
            files = _git(repo, "diff", "--name-status", f"{base}..{branch}")
            audit = []
            if os.path.exists(audit_log):
                with open(audit_log, encoding="utf-8") as f:
                    audit = [line.rstrip("\n") for line in f if line.strip()]
            _set(
                job_id,
                status="done",
                branch=branch,
                base=base,
                changed=changed,
                bmad=bmad,
                summary=summary,
                diff_stat=diff_stat,
                files=files,
                audit=audit,
                cost_usd=result.get("total_cost_usd"),
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


def _run_phase(worktree, brief, phase, feedback=""):
    """Persona texte : prompt = rôle + tâche + artefacts amont (+ feedback), écrit + commit."""
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
    content = (
        _llm_local(model, system, user)
        if model.startswith("local-")
        else _llm_claude_text(f"{system}\n\n{user}")
    )
    dest = os.path.join(worktree, phase["artifact"])
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    with open(dest, "w", encoding="utf-8") as f:
        f.write(content if content.endswith("\n") else content + "\n")
    _git(worktree, "add", phase["artifact"])
    _git(worktree, "commit", "-m", f"pipeline({phase['key']}): {phase['artifact']}")
    return phase["artifact"]


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
                if phase["kind"] == "text":
                    art = _run_phase(worktree, brief, phase)
                else:  # B3 : phase "tools" (dev-story) — non implémentée en B1
                    raise RuntimeError(f"phase '{phase['kind']}' non supportée (B1)")
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
            art = _run_phase(st["worktree"], st["prompt"], phase, feedback=feedback)
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
    if repo and worktree:
        try:
            _git(repo, "worktree", "remove", worktree, "--force", check=False)
        except Exception:
            pass
    _set_pipe(pid, status=status)
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
