# Runbook — Worker agentique (`claude-agent`)

Moteur agentique d'ai-to-boost : exécute `claude -p` **avec outils** en isolation git
worktree, et déroule le **pipeline BMAD** multi-persona (ADR 0004). Source de vérité unique
de la web-app (ADR 0005). Persistance/reprise/archive : [ADR 0008](../adr/0008-persistance-reprise-archive-pipelines.md).

- Code : `services/claude-agent/claude_agent.py`
- Service : **systemd user** (`systemctl --user … claude-agent`), pas un conteneur (il
  utilise le `claude` de l'hôte, forfait). Écoute `:8089`, auth `Bearer AGENT_TOKEN`.
- Worktrees : `~/.local/share/claude-agent/worktrees/` ; registre projets :
  `~/.config/ai-to-boost/projects.json`.

> **Forfait only** : le worker retire `ANTHROPIC_API_KEY`/`ANTHROPIC_AUTH_TOKEN` de l'env
> enfant et **refuse de démarrer** si l'une est présente (anti-bascule API payante).

## Cycle d'un pipeline

`accepted → running` (analyst → PM → architecte → epics → implémentation), avec arrêt en
`awaiting_approval` à chaque jalon, puis `done` (ou `error` / `stopped`). Chaque run vit sur
une branche `pipeline/<id>` + worktree `pl-<id>`. État dans `<repo>/.ai-to-boost/pipeline.json`
(pointeur courant) **et** `<repo>/.ai-to-boost/pipelines/<id>.json` (snapshot d'archive).

## Endpoints (`:8089`, `Authorization: Bearer AGENT_TOKEN`)

| Méthode & chemin                                                          | Rôle                                                      |
| ------------------------------------------------------------------------- | --------------------------------------------------------- |
| `GET /health`                                                             | sonde (publique)                                          |
| `GET /projects`                                                           | liste des projets du registre (+ statut pipeline)         |
| `POST /projects`                                                          | créer + enregistrer un projet (git + develop + marqueur)  |
| `DELETE /projects/<name>`                                                 | désinscrire un projet (non destructif)                    |
| `GET /projects/<name>/board`                                              | board courant (epics/stories + tokens + artefacts)        |
| `POST /projects/<name>/run`                                               | lancer un pipeline (`{prompt}`)                           |
| `POST /projects/<name>/resume`                                            | décision de jalon (`{decision: approve\|revise:…\|stop}`) |
| `POST /projects/<name>/collect`                                           | merge `pipeline/<id>` → base (`{clean?}`)                 |
| `GET /projects/<name>/artifact/<key>`                                     | artefact courant (brief/pm/architect/epics)               |
| `GET /projects/<name>/history`                                            | runs archivés (snapshots)                                 |
| `GET /projects/<name>/history/<pid>`                                      | board read-only d'un run passé                            |
| `GET /projects/<name>/history/<pid>/artifact/<key>`                       | artefact d'un run passé                                   |
| `POST /jobs`, `GET /jobs/<id>`                                            | tâche one-shot (hors pipeline)                            |
| `POST /pipelines`, `GET /pipelines/<id>`, `POST /pipelines[/<id>]/resume` | API pipeline bas niveau                                   |

## Exploitation

```bash
systemctl --user status claude-agent
systemctl --user restart claude-agent          # ⚠️ voir « Redémarrage » ci-dessous
journalctl --user -u claude-agent -f           # logs
curl -s localhost:8089/health                  # {"status":"ok","model":"opus"}
```

### Redémarrage (⚠️ pipelines en cours)

L'état pipeline vit **en mémoire** : un restart tue le thread d'exécution. La **réhydratation**
au démarrage recharge `pipeline.json` et **reprend** les pipelines `running`/`accepted` (phases
idempotentes) — mais une story en cours est rejouée. **Avant un restart**, vérifier qu'aucun
pipeline ne tourne :

```bash
curl -s localhost:8089/projects -H "Authorization: Bearer $AGENT_TOKEN" \
  | python3 -c "import sys,json;[print(p['name'],p.get('pipeline_status')) for p in json.load(sys.stdin)['projects']]"
```

## Dépannage

- **Pipeline « bloqué » / orphelin (running depuis des heures, aucun process `claude`)** :
  symptôme d'un thread tué (restart/reboot du worker) avant la réhydratation, ou d'un état
  resté `running`. Vérifier `GET /pipelines/<id>` (en mémoire ?) et `ps -ef | grep claude`.
  **Remède** : `systemctl --user restart claude-agent` → la réhydratation reprend le run depuis
  sa `phase_index` (worktree conservé). Si le worktree a disparu, le run est marqué `error`.
- **Board vide sur un projet** : `pipeline.json` perdu (gitignoré : `git clean`, reclone).
  Le board retombe en filet sur la **dernière branche `pipeline/*`** ; sinon relancer un run.
- **`réponse vide de local-qwen`** : `qwen3.5:9b` est un _reasoner_ bavard → `_llm_local` utilise
  `max_tokens=16000` ; vérifier ce budget si un appel custom renvoie vide.
- **Story en échec** : laissée `in-progress` (ou `error`), le pipeline **continue** ; elle est
  rejouée à la reprise/`revise`. Détail dans `pipeline.json:impl_failed`.
- **Récupérer un run écrasé** : son code/PRD vit sur sa branche `pipeline/<id>` ;
  `git -C <repo> log --all --oneline | grep pipeline` puis `ai2b collect` (après l'avoir
  pointé) ou merge manuel.

## Sécurité

Repo orchestrateur **interdit** comme cible (`AGENT_FORBID`). Bash agentique sous hook
garde-fou (`guard_hook.py`, denylist + confinement des écritures). Jamais de push/merge
automatique vers un remote.
