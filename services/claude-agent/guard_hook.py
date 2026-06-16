#!/usr/bin/env python3
"""Garde-fou PreToolUse du worker agentique (Phase 6b.3a).

Reçoit sur stdin le payload PreToolUse de Claude Code et :
- pour Bash : journalise la commande (audit) puis BLOQUE (exit 2) si elle matche la
  denylist (push, reset --hard, rm -rf, sudo, dd, curl|sh, persistance, accès distant…) ;
- pour Edit/Write/MultiEdit/NotebookEdit : BLOQUE toute écriture HORS du worktree
  (confinement) et toute écriture dans `.git/config|hooks`.

exit 2 = bloc (renvoyé au modèle via stderr) ; il bloque même en bypassPermissions.
exit 0 = laisse passer.
"""

import json
import os
import re
import sys

_DENY_SRC = [
    (r"\bgit\s+push\b", "git push interdit"),
    (r"\bgit\s+remote\b", "git remote interdit (ajout d'origine)"),
    (r"\bgit\s+reset\s+--hard\b", "git reset --hard interdit"),
    (r"\bgit\s+rebase\b", "git rebase interdit"),
    (r"\bgit\b[^\n]*(--force|\s-f\b)", "git --force interdit"),
    (r"\brm\s+-[a-z]*r[a-z]*f|\brm\s+-[a-z]*f[a-z]*r", "rm -rf interdit"),
    (r"\b(sudo|doas|su)\b", "élévation de privilèges interdite"),
    (r"\b(mkfs|fdisk|parted|shred)\b", "manipulation disque interdite"),
    (r"\bdd\b[^\n]*\bof=", "dd of= interdit"),
    (r">\s*/dev/(sd|nvme|disk)", "écriture disque brute interdite"),
    (r"\bchmod\s+(-[a-zA-Z]*\s+)?[0-7]*777", "chmod 777 interdit"),
    (r"\bchown\b", "chown interdit"),
    (r"(curl|wget)\b[^|]*\|\s*(sudo\s+)?(ba)?sh", "download | shell interdit"),
    (r":\(\)\s*\{.*\}\s*;", "fork bomb interdite"),
    (r"\b(systemctl|crontab|at)\b", "persistance système interdite"),
    (r"\.git/(config|hooks)\b", "écriture .git/config|hooks interdite"),
    (r"\b(ssh|scp|sftp)\b", "accès distant interdit"),
]
DENY = [(re.compile(p, re.I), m) for p, m in _DENY_SRC]


def _under(path, root):
    try:
        rp = os.path.realpath(path)
        root = os.path.realpath(root)
        return rp == root or rp.startswith(root + os.sep)
    except Exception:
        return False


def _block(reason):
    print(f"BLOQUÉ (garde-fou ai-to-boost) : {reason}", file=sys.stderr)
    sys.exit(2)


def main():
    try:
        data = json.load(sys.stdin)
    except Exception:
        sys.exit(0)  # payload illisible : ne pas casser l'exécution
    tool = data.get("tool_name", "")
    ti = data.get("tool_input") or {}
    cwd = data.get("cwd") or os.getcwd()

    if tool in ("Edit", "Write", "MultiEdit", "NotebookEdit"):
        fp = ti.get("file_path") or ti.get("notebook_path") or ""
        if fp and not _under(fp, cwd):
            _block(f"écriture hors du worktree : {fp}")
        if re.search(r"\.git/(config|hooks)\b", fp):
            _block("écriture dans .git/config|hooks")
        sys.exit(0)

    if tool == "Bash":
        cmd = ti.get("command", "")
        audit = os.environ.get("AGENT_AUDIT_LOG")
        if audit:
            try:
                with open(audit, "a", encoding="utf-8") as f:
                    f.write(cmd.replace("\n", " ⏎ ") + "\n")
            except Exception:
                pass
        for rx, msg in DENY:
            if rx.search(cmd):
                _block(msg)
        sys.exit(0)

    sys.exit(0)


if __name__ == "__main__":
    main()
