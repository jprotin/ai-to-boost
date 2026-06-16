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

# Modes : "file" (défaut, outils fichiers) / "build" (Bash en plus, sous garde-fou).
ALLOWED_TOOLS = {
    "file": ["Read", "Edit", "Write"],
    "build": ["Read", "Edit", "Write", "Bash"],
}
DISALLOWED_TOOLS = ["WebFetch", "WebSearch"]
APPEND_SYSTEM_PROMPT = (
    "Tu es un worker de développement automatisé, sans interaction humaine pendant "
    "l'exécution. Réalise la demande en créant/éditant les fichiers nécessaires dans "
    "le répertoire courant. Ne pose aucune question, ne demande aucune confirmation."
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
        try:
            env = {
                k: v
                for k, v in os.environ.items()
                if k not in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN")
            }
            env.setdefault("PATH", "/home/jprotin/.local/bin:/usr/bin:/bin")
            env["AGENT_AUDIT_LOG"] = audit_log
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
                "--disallowed-tools",
                *DISALLOWED_TOOLS,
                "--settings",
                _guard_settings(),
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
        self._send(404, {"error": "not found"})

    def do_POST(self):
        if self.path != "/jobs":
            self._send(404, {"error": "not found"})
            return
        if not self._auth_ok():
            self._send(401, {"error": "unauthorized"})
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            data = json.loads(self.rfile.read(length) or b"{}")
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
