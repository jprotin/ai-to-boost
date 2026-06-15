#!/usr/bin/env python3
"""Bridge HTTP minimal vers `claude -p` (Claude Code, forfait Max).

Permet à n8n (conteneur) d'appeler Claude via le forfait — PAS l'API au token —
en exécutant `claude -p` sur l'hôte. Cf. ADR 0002 et docs/runbooks/claude-bridge.md.

- Texte seul : les outils mutants/web sont interdits (--disallowed-tools) ; en
  mode -p sans --dangerously-skip-permissions, les autres outils sont de toute
  façon refusés (pas de TTY).
- Protégé par un token Bearer (BRIDGE_TOKEN). Bind sur CLAUDE_BRIDGE_HOST.
- Force le forfait : ANTHROPIC_API_KEY / ANTHROPIC_AUTH_TOKEN retirés de l'env enfant.

Config par variables d'environnement (cf. .env) :
  BRIDGE_TOKEN            (requis) token Bearer partagé avec n8n
  CLAUDE_BRIDGE_PORT      port d'écoute (défaut 8088)
  CLAUDE_BRIDGE_HOST      interface d'écoute (défaut 0.0.0.0)
  CLAUDE_BRIDGE_MODEL     modèle par défaut (défaut opus)
  CLAUDE_BRIDGE_TIMEOUT   timeout secondes par appel (défaut 300)
  CLAUDE_BRIDGE_WORKDIR   cwd des exécutions claude (défaut ~/.local/share/claude-bridge/work)
"""

import json
import os
import shutil
import subprocess
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HOST = os.environ.get("CLAUDE_BRIDGE_HOST", "0.0.0.0")
PORT = int(os.environ.get("CLAUDE_BRIDGE_PORT", "8088"))
TOKEN = os.environ.get("BRIDGE_TOKEN", "")
DEFAULT_MODEL = os.environ.get("CLAUDE_BRIDGE_MODEL", "opus")
TIMEOUT = int(os.environ.get("CLAUDE_BRIDGE_TIMEOUT", "300"))
WORKDIR = os.environ.get(
    "CLAUDE_BRIDGE_WORKDIR", os.path.expanduser("~/.local/share/claude-bridge/work")
)
CLAUDE = shutil.which("claude") or os.path.expanduser("~/.local/bin/claude")

# Outils interdits (défense en profondeur ; -p sans skip-permissions refuse déjà le reste)
DISALLOWED_TOOLS = ["Bash", "Edit", "Write", "NotebookEdit", "WebFetch", "WebSearch"]
APPEND_SYSTEM_PROMPT = (
    "Tu es une API de complétion appelée par un orchestrateur automatisé. "
    "Réponds directement et uniquement à la demande, sans préambule, sans plan, "
    "sans poser de question, sans utiliser d'outils."
)


def run_claude(prompt: str, model: str) -> dict:
    env = {
        k: v
        for k, v in os.environ.items()
        if k not in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN")
    }
    env.setdefault("PATH", "/usr/bin:/bin")
    cmd = [
        CLAUDE,
        "-p",
        prompt,
        "--model",
        model,
        "--output-format",
        "json",
        "--append-system-prompt",
        APPEND_SYSTEM_PROMPT,
        "--disallowed-tools",
        *DISALLOWED_TOOLS,
    ]
    proc = subprocess.run(
        cmd, cwd=WORKDIR, env=env, capture_output=True, text=True, timeout=TIMEOUT
    )
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or f"claude exit {proc.returncode}")
    return json.loads(proc.stdout)


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):  # silence les logs d'accès par défaut
        pass

    def _send(self, code: int, payload: dict) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/health":
            self._send(200, {"status": "ok", "model": DEFAULT_MODEL})
        else:
            self._send(404, {"error": "not found"})

    def do_POST(self):
        if self.path != "/run":
            self._send(404, {"error": "not found"})
            return
        if not TOKEN or self.headers.get("Authorization") != f"Bearer {TOKEN}":
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
        model = data.get("model") or DEFAULT_MODEL
        try:
            res = run_claude(prompt, model)
        except subprocess.TimeoutExpired:
            self._send(504, {"error": f"timeout > {TIMEOUT}s"})
            return
        except Exception as exc:
            self._send(502, {"error": str(exc)})
            return
        if res.get("is_error"):
            self._send(502, {"error": "claude error", "raw": res})
            return
        self._send(
            200,
            {
                "result": res.get("result"),
                "model": model,
                "cost_usd": res.get("total_cost_usd"),
                "session_id": res.get("session_id"),
            },
        )


def main():
    if not TOKEN:
        raise SystemExit("BRIDGE_TOKEN requis (cf. .env)")
    os.makedirs(WORKDIR, exist_ok=True)
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    print(
        f"claude-bridge sur {HOST}:{PORT} (modèle défaut: {DEFAULT_MODEL})", flush=True
    )
    server.serve_forever()


if __name__ == "__main__":
    main()
