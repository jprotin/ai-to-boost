# Runbook Phase 6b — Worker agentique (claude -p +outils, isolé)

Worker qui laisse Claude **agir** (créer/éditer des fichiers) en isolation totale, sur
le **forfait Max**. Évolution du claude-bridge (texte seul). Cf. `docs/phase6-plan.md`.

## Palier 6b.1 (FAIT) — worker core, outils fichiers seuls

- Service : `services/claude-agent/claude_agent.py` (Python stdlib), **systemd user**,
  `0.0.0.0:8089`, token Bearer `AGENT_TOKEN`.
- Outils : `Read,Edit,Write` + `--permission-mode acceptEdits`. **Pas de Bash, pas de web**
  → l'agent ne peut rien exécuter (Bash scopé prévu en 6b.3 avec BMAD).
- Isolation : un `git worktree` + branche `agent/<job_id>` par job ; commit sur cette
  branche ; **jamais de push/merge** ; worktree retiré après coup (branche conservée).
- Forfait : `ANTHROPIC_API_KEY`/`AUTH_TOKEN` retirés de l'env enfant ; le service
  **refuse de démarrer** si l'une est présente.
- Repo `ai-to-boost` (orchestrateur) **interdit** comme cible (`AGENT_FORBID`).
- Async : 1 job à la fois (sérialisé), résultat via `GET /jobs/<id>`.

## Installation

```bash
cp services/claude-agent/claude-agent.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now claude-agent
loginctl enable-linger "$USER"   # déjà actif (bridge)
```

Variables (`.env`, gitignoré) : `AGENT_TOKEN` (`openssl rand -hex 24`), `AGENT_PORT=8089`,
`AGENT_MODEL=opus`, `AGENT_TIMEOUT=600`, `AGENT_MAXTURNS=30`. Repo cible de test :
`~/agent-workspace/sandbox` (git init + README).

## API

| Méthode | Chemin       | Corps                            | Réponse                                                                |
| ------- | ------------ | -------------------------------- | ---------------------------------------------------------------------- |
| GET     | `/health`    | —                                | `{status, model}`                                                      |
| POST    | `/jobs`      | `{prompt, repo, return_target?}` | `202 {job_id, status:"accepted"}`                                      |
| GET     | `/jobs/<id>` | —                                | `{status, branch, base, changed, summary, diff_stat, files, cost_usd}` |

`status` : `accepted` → `running` → `done` | `error`. Auth : `Authorization: Bearer <AGENT_TOKEN>`.

## Validation (faite le 2026-06-16)

```bash
AT=$(grep -E '^AGENT_TOKEN=' .env | cut -d= -f2-)
# job
curl -s -X POST http://localhost:8089/jobs -H "Authorization: Bearer $AT" \
  -H 'Content-Type: application/json' \
  -d '{"prompt":"Crée hello.sh qui affiche bonjour","repo":"/home/jprotin/agent-workspace/sandbox"}'
# suivi
curl -s http://localhost:8089/jobs/<id> -H "Authorization: Bearer $AT"
```

Résultat attendu : branche `agent/<id>` avec le fichier, `master` intact, aucun push.
Garde-fous testés : repo interdit → 400, sans token → 401.

## Revue & application du travail de l'agent

L'agent **ne merge rien**. Pour récupérer son travail dans le repo cible :

```bash
cd ~/agent-workspace/sandbox
git diff master..agent/<id>      # revue
git checkout agent/<id>          # ou cherry-pick / merge manuel après validation
```

## Dépannage

- Service ne démarre pas + log « refus de démarrer (forfait only) » : une
  `ANTHROPIC_API_KEY` est exportée dans l'env du service → la retirer (`.env` / shell).
- `claude exit …` : vérifier `claude login` fait pour l'utilisateur du service ; binaire
  dans `~/.local/bin/claude` (PATH de l'unit).
- Job `error` « repo cible interdit » : cibler un repo hors `AGENT_FORBID`.

## Palier 6b.2 (FAIT) — boucle async vers l'origine

Chaîne complète : `/code` depuis n'importe quelle entrée → diff renvoyé à l'origine.

```
dispatcher /code → POST worker /jobs {prompt, return_target}  → ack "Tâche #id acceptée"
worker (async) → fin de job → POST n8n /webhook/job-callback {job state}
n8n (11-job-callback) → POST poller :8090/notify {chat_id, text}  → Telegram
```

- Worker : `AGENT_DEFAULT_REPO` (repo cible si `/code` ne le précise pas),
  `AGENT_CALLBACK_URL` (n8n) appelé en fin de job (best-effort).
- Poller : endpoint `POST /notify {chat_id, text}` (port `NOTIFY_PORT=8090`, interne au
  réseau Docker, token `NOTIFY_TOKEN`). **Le token Telegram reste confiné au poller**
  (ADR 0003) ; l'allowlist s'applique aussi aux notifications.
- n8n : workflow `11-job-callback.json` (webhook `job-callback`) ; credentials
  `Agent token` + `Poller notify token`. Dispatcher : route `/code` → worker.
- UX Telegram : 2 messages — l'ack immédiat, puis le résultat (branche + diff) en async.

Test (sans spammer le vrai Telegram, chat_id non-allowlisté → poller 403) :

```bash
curl -s -X POST http://localhost:5678/webhook/assistant-in -H 'Content-Type: application/json' \
  -d '{"chat_id":999,"text":"/code Crée note.txt contenant OK"}'
# → ack ; branche agent/<id> créée ; callback OK (worker sans erreur)
```

Test réel : envoyer `/code …` au bot Telegram → ack puis résultat.

## Suite

- **6b.3** : Bash scopé + hook `PreToolUse` (anti push/rm/sudo) + installation BMAD.
