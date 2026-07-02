# Audit — Portabilité locale (autre développeur, mono-utilisateur)

**Date** : 2026-07-02 · **Cas d'usage** : un autre développeur installe et fait tourner ai-to-boost **en local chez lui** (pas de mutualisation, mono-utilisateur) · **Méthode** : lecture seule.

## Verdict

**~50–60 % prêt.** La stack Docker Compose est portable, mais plusieurs blocages empêchent un « git clone → ça tourne » : les services hôte (systemd) contiennent des chemins en dur, le binaire `claude` n'est pas documenté, et il n'y a pas de script d'installation.

## Blocages CRITIQUES (empêchent l'installation ailleurs)

| Problème                                                                                                                                 | Où                                                                                           | Effort |
| ---------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------- | ------ |
| **Chemins en dur dans les units systemd** (`.service`) : `/datadisk/…` (EnvironmentFile, ExecStart) et `/home/jprotin/.local/bin` (PATH) | `services/claude-agent/claude-agent.service`, `services/claude-bridge/claude-bridge.service` | Petit  |
| **`AGENT_DEFAULT_REPO` pointe un chemin jprotin** (`/home/jprotin/dev/mon-projet-demo`)                                                  | `.env`                                                                                       | Petit  |
| **Binaire `claude` CLI jamais installé/documenté** → worker + bridge échouent sans lui, sans message clair                               | `docs/guide-deploiement.md` (mention vague)                                                  | Moyen  |
| **Fallback PATH `/home/jprotin/…` en dur** dans le code                                                                                  | `services/claude-agent/claude_agent.py` (fallback `env["PATH"]`)                             | Petit  |
| **Aucun script d'install des services systemd** (4 commandes manuelles ×2, risque d'erreur)                                              | runbooks (instructions manuelles)                                                            | Moyen  |

## Blocages IMPORTANTS

- **GPU NVIDIA obligatoire** (Ollama + Whisper via `deploy.resources.devices`), pas de fallback CPU documenté → un dev sans GPU est bloqué.
- **Prérequis non vérifiés** : aucun pre-flight check (Docker, GPU, Python 3.12+, `claude` CLI, `jq`, git) → erreurs cryptiques au démarrage.
- **`host.docker.internal`** (n8n/webui → services hôte) peut différer sur Linux natif vs Docker Desktop.
- **Symlink `ai2b`** documenté avec un chemin absolu jprotin.

## Ce qui manque (checklist onboarding « autre dev local »)

- [ ] `scripts/install-local-dev.sh` — bootstrap 1-clic : copie `.env.example`→`.env`, génère les secrets, crée les dossiers requis (`AGENT_BMAD_DIR`), génère les units systemd depuis un **template** (chemins courants, pas en dur), installe, lance `ai2b up`, health-check.
- [ ] `scripts/verify-prereqs.sh` — vérifie Docker, GPU (+ warning/fallback si absent), Python, `claude` CLI, `jq`, git ; messages d'install clairs.
- [ ] `docs/INSTALLATION.md` — prérequis / config / démarrage / vérification / dépannage.
- [ ] Remplacer les chemins `/home/jprotin` par `$HOME` / `shutil.which("claude")` dans le code et les units.
- [ ] Fallback GPU→CPU pour Ollama (compose conditionnel) + doc.

**Effort MVP (critique + important) : ~12 h.** Version complète (fallback GPU, health-checks, FAQ) : ~18 h.

## Conclusion

Le code applicatif est propre (peu de hardcoding hors fallback PATH), la stack Docker est portable. Les vrais points durs sont les **services hôte systemd** (chemins absolus) et le **binaire `claude` non documenté**. Un script d'install + une doc d'installation débloquent l'essentiel.

> Estimations d'effort indicatives. Les chemins/lignes exacts sont à revérifier avant correction.
