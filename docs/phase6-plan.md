# Phase 6 — Exécution agentique mutualisée via n8n (plan)

> Statut : plan validé le 2026-06-16. Mise en œuvre en 3 sous-phases (6a → 6b → 6c),
> chacune sur une branche `feature/*` mergée dans `develop`.

## Décisions verrouillées

| #                   | Décision                                                                           | Raison                                                                                  |
| ------------------- | ---------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------- |
| Routage             | Commandes explicites (`/chat`, `/claude`, `/code`)                                 | Déterministe, cheap, pas de classif LLM                                                 |
| Exécution agentique | **Asynchrone** (job + callback)                                                    | Un build dure des minutes → pas de webhook synchrone                                    |
| Techno worker       | **`claude -p` headless, outils rouverts, forfait** (pas le SDK)                    | Le SDK ne peut pas taper le forfait + interdit CGU (cf. `worker-agentique-cli-pas-sdk`) |
| Garde-fous          | Workspace scopé, branche feature, **jamais de push**, diff pour validation humaine | Cohérent CLAUDE.md (jamais push/commit sans Go)                                         |
| Entrée desktop      | murmure mode commande → webhook n8n (pattern ack)                                  | Réutilise le mécanisme LLM remote de murmure                                            |

## Architecture cible

```
ENTRÉES                          n8n (CERVEAU)                       EXÉCUTANTS
Telegram (txt|voix) ───┐  [Webhook /assistant-in]      /chat ───►  LiteLLM → LM Studio
murmure (mode cmd) ────┼► → normalise                  /claude ─►  bridge claude -p (texte)
prompt/CLI/API ────────┘  → parse /commande            /code ───►  WORKER agentique (async)
                          → ROUTE                            │
                          [Webhook /job-callback] ◄──────────┘  (diff + résumé) → notifie l'origine

WORKER (hôte, forfait) : git worktree isolé → claude -p +outils → branche feature/agent/<id>
   → diff → callback n8n → JAMAIS push/merge.
```

## Sous-phases

### 6a — Dispatcher n8n (routeur unique) ← EN COURS

- Webhook unique `assistant-in` `{source, return_target, text}` (tolérant au `{chat_id, text}` du poller).
- Normalise → parse commande → Switch → routes : `chat`→LiteLLM (credential), `claude`→bridge (credential), `code`→placeholder (branché en 6b).
- Poller Telegram repointé sur `assistant-in`.
- Secrets : **credentials n8n chiffrés** (`LiteLLM master key`, `Bridge token`), jamais en clair dans le workflow.
- Validation : Telegram local + `/claude` + POST direct ; `/code` renvoie un ack placeholder.

### 6b — Worker agentique + BMAD

- `services/claude-agent/` : service hôte systemd user, forfait (`ANTHROPIC_API_KEY` garantie absente).
- API `POST /jobs {prompt, repo, return_target}` → `{job_id, status:"accepted"}` (async).
- Cycle job : worktree `feature/agent/<id>` → `claude -p --allowedTools … --disallowedTools "Bash(git push:*),…" --permission-mode acceptEdits --max-turns N --output-format json` → diff → callback n8n.
- BMAD installé dans un repo cible (sandbox dédié).
- Route `/code` → worker ; webhook `/job-callback` → notifie l'origine.
- ADR 0004 (worker agentique CLI, async, isolé).
- Validation : `/code …` → job accepté → notif avec branche + diff ; **rien sur develop/main, aucun push** ; commande destructive bloquée.

### 6c — Entrée desktop (murmure) + notifications

- murmure mode commande : `remote_url` = webhook n8n `/voice-in` (forme OpenAI) → n8n route → ack OpenAI tapé au curseur.
- Mode chat libre de murmure : **reste en direct LM Studio** (inchangé).
- Retour async des jobs desktop : v1 sur Telegram (sortie unifiée) ; option `notify-send` plus tard.

## Garde-fous (consolidés)

- Worker **sans `ANTHROPIC_API_KEY`** (forfait), `claude login` fait pour son user ; check au démarrage.
- `cwd` = worktree, repo cible ≠ ai-to-boost (sandbox).
- Git : branche `feature/agent/*` only ; push/merge/reset/force **interdits** (`--disallowedTools` + hook `PreToolUse`).
- Shell : whitelist Bash étroite (tests/build) ; `rm`/`sudo` bloqués.
- `--max-turns` + timeout dur ; 1 job concurrent.
- **Humain dans la boucle** : rien livré sans revue du diff.

## Risques & parades

| Risque                                           | Parade                                            |
| ------------------------------------------------ | ------------------------------------------------- |
| BMAD pensé interactif → headless capricieux      | v1 specs simples + human-in-the-loop              |
| Job long > timeout                               | async + callback                                  |
| Action dangereuse de l'agent                     | double barrière disallowedTools + hook PreToolUse |
| `ANTHROPIC_API_KEY` traîne → bascule API payante | unit systemd qui l'unset + check démarrage        |
| Jobs parallèles → conflits repo                  | worktree par job + cap à 1                        |
| murmure envoie `stream:true`                     | forcer `stream:false` côté n8n                    |

## Ordre

`6a` → `6b` (dépend de 6a) → `6c` (dépend de 6a/6b). Merge dans `develop` entre chaque. Commits/merges **uniquement sur Go explicite**.
