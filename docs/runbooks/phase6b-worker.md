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

## Suite

- **6b.2** : callback async → n8n `/job-callback` → poller `/notify` → Telegram ; route
  `/code` du dispatcher branchée sur `POST /jobs`.
- **6b.3** : Bash scopé + hook `PreToolUse` (anti push/rm/sudo) + installation BMAD.
