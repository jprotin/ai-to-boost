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

## Palier 6b.3a (FAIT) — Bash sous garde-fou + audit

Deux modes de job (champ `mode`) :

| Mode            | Route dispatcher | Outils                      | Permission                      |
| --------------- | ---------------- | --------------------------- | ------------------------------- |
| `file` (défaut) | `/code`          | Read, Edit, Write           | `acceptEdits`                   |
| `build`         | `/build`         | Read, Edit, Write, **Bash** | `bypassPermissions` + garde-fou |

**Garde-fou** `services/claude-agent/guard_hook.py` (hook `PreToolUse`, injecté via
`--settings` inline → **prime sur tout `.claude/settings.json` du worktree**, et
**bloque même en `bypassPermissions`** — confirmé doc Claude Code) :

- **Bash** : BLOQUE (exit 2) `git push|remote|reset --hard|rebase|--force`, `.git/config|hooks`,
  `rm -rf|sudo|mkfs|dd|chmod 777|chown`, `curl|wget … | sh`, fork bomb, `systemctl|crontab`,
  `ssh|scp`. Le reste (npm, node, git add/commit/diff…) passe.
- **Edit/Write/MultiEdit** : BLOQUE toute écriture **hors du worktree** et dans `.git/config|hooks`.
- **Audit** : toute commande Bash est journalisée (`AGENT_AUDIT_LOG`) et renvoyée dans
  `GET /jobs/<id>` → champ `audit` (revue a posteriori de ce qu'a fait l'agent).

`WebFetch`/`WebSearch` restent coupés (`--disallowed-tools`). Confinement inchangé
(worktree, aucun remote, jamais de push/merge, max-turns, timeout).

Validation (2026-06-16) : `/build` exécute `node`/shell légitime (audit l'atteste) ;
une tentative `git push` est **bloquée** par le hook ; `/code` reste fichiers-seuls.

> Limite assumée : garde-fous contre l'**erreur accidentelle**, pas un agent adversarial ;
> le confinement (worktree + sans remote + non mergé) borne les dégâts.
> À affiner en 6b.3b : brancher depuis une **base stable** (main) définie par l'init, pas
> depuis le HEAD courant du repo cible.

## Palier 6b.3b (FAIT) — init projet + marqueur + base stable

ai-to-boost ne pilote que des projets **explicitement initialisés** (opt-in).

- **`scripts/ai-to-boost-init.sh [<projet>]`** : pose `.ai-to-boost/config.json`
  (`{name, base_branch, agent_enabled}`) + `.ai-to-boost/rag/` (RAG par projet, 6b.3d),
  et ajoute `.ai-to-boost/` au `.gitignore` du projet (config privée). Refuse de cibler
  ai-to-boost lui-même.
- **Worker** : `_validate_repo` **exige** le marqueur `.ai-to-boost/` (sinon `400 :
projet non initialisé`), togglable par `AGENT_REQUIRE_MARKER` (défaut `true`). Le job
  branche désormais depuis **`base_branch`** (config), plus depuis le HEAD courant.

Validation (2026-06-16) : repo sans marqueur → `400` ; sandbox initialisé → job branché
depuis `master` (base stable). 1er projet enregistré : `~/agent-workspace/sandbox`.

## Palier 6b.3c (FAIT) — BMAD commun, injecté par job

BMAD est **installé une seule fois** (commun à tous les projets), pas par projet.

- **Install partagée** (`AGENT_BMAD_DIR`, défaut `~/agent-workspace/.bmad-shared`) :

  ```bash
  npx bmad-method@latest install --yes --directory <dir> --modules bmm --tools claude-code
  ```

  → produit `_bmad/` (config + modules) + `.claude/skills/` (44 skills `bmad-*`).
  Auto-contenu : **aucune écriture** dans `~/.claude` perso ni `$HOME`.

- **Injection par job** : le worker symlink `_bmad` et `.claude/skills` (du partagé) dans
  le worktree avant de lancer claude → l'agent voit les skills `bmad-*` ; puis **éjecte**
  les symlinks avant `git add` → **aucune pollution du diff**.
- Avantages : source unique (MAJ en un endroit), pas de réseau/install par projet, pas de
  pollution `.claude/` perso ni des repos cibles.

Validation (2026-06-16) : `/build` invoquant l'agent architecte BMAD a produit un
`architecture.md` (persona « Winston ») ; diff = `architecture.md` seul (symlinks éjectés).

## Palier 6b.3d (FAIT) — RAG double-portée

L'agent s'appuie sur **deux RAG** via MCP (lecture `qdrant-find`) :

- **commun** : collection `knowledge` (doc transverse, Phase 5).
- **par projet** : collection `proj-<slug>` alimentée par `<projet>/.ai-to-boost/rag/`.

Indexation projet :

```bash
scripts/ai-to-boost-rag-sync.sh <projet>   # → collection proj-<slug> (via ingest.py)
```

(le RAG commun s'indexe via `uv run services/rag/ingest.py` à la racine d'ai-to-boost).

Injection par job (worker) : construit un `--mcp-config` éphémère avec `rag-common`
(toujours) + `rag-project` (si la collection existe), lancé en `--strict-mcp-config`
(ignore tout `.mcp.json` du projet) ; ajoute `mcp__rag-common__qdrant-find` et
`mcp__rag-project__qdrant-find` aux `--allowed-tools`. Le system prompt indique à l'agent
de consulter ces RAG. Config Qdrant reprise de l'env (`QDRANT_URL`, `RAG_COLLECTION`,
`EMBEDDING_MODEL` — mêmes valeurs que le MCP commun pour la compatibilité des embeddings).

Validation (2026-06-16) : doc `conventions.md` dans `sandbox/.ai-to-boost/rag/` → sync →
`proj-sandbox` ; un `/build` a consulté `rag-project` et produit `server-config.md`
reprenant les conventions (préfixe `sbx_`, port 7421, logs JSON). Diff propre.

## Phase 6 — terminée

6a (dispatcher) + 6b.1→6b.3d (worker agentique : isolation, async/Telegram, Bash sous
garde-fou + audit, opt-in projet, BMAD commun, RAG double-portée). Voir `docs/phase6-plan.md`.
