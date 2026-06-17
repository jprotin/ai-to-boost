# Runbook — Bridge `claude -p` (Claude via forfait depuis n8n)

Petit wrapper HTTP sur l'**hôte** qui exécute `claude -p` (Claude Code, forfait Max)
et expose un endpoint appelé par n8n. Permet d'utiliser Claude **sans clé API au token**,
conformément à l'[ADR 0002](../adr/0002-litellm-modeles-locaux-uniquement.md).

## Architecture

- Tourne **en natif sur l'hôte** (comme LM Studio), pas dans compose — il lui faut
  le binaire `claude` et l'auth forfait (`~/.claude`).
- n8n (conteneur) l'appelle via `host.docker.internal:8088` (`extra_hosts` déjà en place).
- Endpoint : `POST /run` `{ "prompt": "...", "model": "opus|sonnet|..." }` →
  `{ "result": "...", "model", "cost_usd", "session_id" }`. `GET /health`.
- **Sécurité** : token Bearer (`BRIDGE_TOKEN`) ; outils mutants/web interdits ;
  `ANTHROPIC_API_KEY`/`ANTHROPIC_AUTH_TOKEN` retirés de l'env enfant (force le forfait).

Fichiers : `services/claude-bridge/claude_bridge.py` (serveur, stdlib Python) et
`services/claude-bridge/claude-bridge.service` (unit systemd user).

## Prérequis

- `claude` installé et authentifié sur le **forfait** : `claude --version`, et
  **aucune** variable `ANTHROPIC_API_KEY`/`ANTHROPIC_AUTH_TOKEN` exportée dans le shell
  (sinon Claude Code facture l'API). Vérif : `env | grep -i ANTHROPIC` → vide.
- `.env` : `BRIDGE_TOKEN`, `CLAUDE_BRIDGE_PORT` (8088), `CLAUDE_BRIDGE_MODEL` (opus).

## Installation (service systemd user)

```bash
mkdir -p ~/.config/systemd/user
cp services/claude-bridge/claude-bridge.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now claude-bridge
loginctl enable-linger "$USER"     # démarrage au boot sans session ouverte
```

Gestion : `systemctl --user status|restart|stop claude-bridge`,
logs : `journalctl --user -u claude-bridge -f`.

> Le service charge ses variables depuis le `.env` du projet
> (`EnvironmentFile=/datadisk/ai-projects/ai-to-boost/.env`) et met `~/.local/bin`
> dans le `PATH` (binaire `claude`). Adapter les chemins si le repo est déplacé.

## Validation

```bash
TOK=$(grep '^BRIDGE_TOKEN=' .env | cut -d= -f2)

# Santé
curl -s http://127.0.0.1:8088/health

# Appel direct (hôte)
curl -s -X POST http://127.0.0.1:8088/run \
  -H "Authorization: Bearer $TOK" -H "Content-Type: application/json" \
  -d '{"prompt":"Réponds en un mot: capitale de la France ?"}'

# Depuis le conteneur n8n
docker exec n8n sh -lc "wget -qO- \
  --header='Authorization: Bearer $TOK' --header='Content-Type: application/json' \
  --post-data='{\"prompt\":\"Dis OK\"}' http://host.docker.internal:8088/run"
```

## Workflow n8n d'exemple

`services/n8n/workflows/02-demo-claude-bridge.json` : déclencheur manuel → appel du
bridge. À l'import, remplacer `CHANGEME_BRIDGE_TOKEN` par `BRIDGE_TOKEN` (ou créer un
credential _Header Auth_).

## Dépannage

- **401** : token absent/incorrect dans l'en-tête `Authorization`.
- **502 `claude error`** : voir `journalctl --user -u claude-bridge` ; souvent auth
  forfait expirée (`claude` en interactif une fois pour ré-authentifier) ou modèle invalide.
- **504 timeout** : prompt trop long / modèle lent ; augmenter `CLAUDE_BRIDGE_TIMEOUT`.
- **n8n ne joint pas le bridge** : le bridge doit écouter sur `0.0.0.0`
  (`CLAUDE_BRIDGE_HOST`), pas `127.0.0.1`, sinon `host.docker.internal` est injoignable.
- **Facturation API au lieu du forfait** : une var `ANTHROPIC_API_KEY` traîne dans
  l'environnement du service — la retirer.

## Limites / pistes

- Le binaire `claude -p` charge le `~/.claude/CLAUDE.md` global ; un
  `--append-system-prompt` neutralise le préambule. Pour isoler davantage, pointer
  `CLAUDE_BRIDGE_WORKDIR`/config dédiés.
- Texte seul (pas d'outils). Pour des workflows agentiques, étendre le bridge
  (autoriser certains outils, `--permission-mode`) en connaissance de cause.
