# Changelog

Toutes les évolutions notables de ce projet. Format inspiré de [Keep a Changelog](https://keepachangelog.com/),
versionnage [SemVer](https://semver.org/).

## [Non publié]

### Ajouté

- **BMAD en interactif par projet** : `ai-to-boost-init.sh` expose désormais BMAD
  (symlinks `_bmad/` + `.claude/skills/bmad-*` vers le partagé `~/agent-workspace/.bmad-shared`)
  dans le projet cible. Les skills `/bmad-help`, `/bmad-prd`, … deviennent disponibles en
  session Claude Code interactive (en miroir de l'injection temporaire du worker). Symlinks
  non versionnés.

## [1.0.0] — 2026-06-17

Première version stable : assistant IA **local-first orchestré**, de la voix à
l'exécution agentique pilotée.

### Phase 0–2 — Socle, modèles, voix

- Socle Docker Compose + réseau `ai-assistant-net`, gestion `.env`/secrets.
- **LiteLLM** : gateway unique des modèles **locaux** (LM Studio), Postgres de persistance.
  Local-only (ADR 0002) ; Claude n'y passe pas.
- **STT GPU** faster-whisper (service `whisper`), transcription FR.

### Phase 3–4 — Orchestrateur & entrées

- **n8n** orchestrateur (réutilise l'instance Postgres).
- **Bridge `claude -p`** (systemd user) : Claude sur le **forfait** appelable depuis n8n
  (texte seul).
- **Telegram** par long-polling local (ADR 0003), allowlist, voix+texte ; token confiné
  au poller.

### Phase 5 — RAG

- **Qdrant** + ingestion (`services/rag/ingest.py`, embeddings nomic) + serveur MCP
  branché à Claude Code.

### Phase 6 — Exécution agentique mutualisée

- **Dispatcher n8n unique** (`assistant-in`) : routage par commande `/chat` (LiteLLM),
  `/claude` (bridge), `/code`·`/build` (worker). Secrets en credentials chiffrés.
- **Worker agentique** (`services/claude-agent`, forfait) : exécution `claude -p` **avec
  outils**, isolée en `git worktree` (branche `agent/<id>`, jamais de push/merge), async.
  - Mode `file` (édition) / `build` (Bash) sous **garde-fou `PreToolUse`** (denylist
    push/rm/sudo/…, confinement des écritures) + **audit** des commandes.
  - **Opt-in projet** : marqueur `.ai-to-boost/` requis (`scripts/ai-to-boost-init.sh`),
    branchement depuis une base stable.
  - **BMAD commun** injecté par job (installé une fois, partagé, éjecté avant commit).
  - **RAG double-portée** : commun (`knowledge`) + par projet (`proj-<slug>`,
    `scripts/ai-to-boost-rag-sync.sh`), via MCP `qdrant-find`.
- Boucle async complète : ordre → exécution → **diff renvoyé sur Telegram** pour revue.

### Outillage

- **bmad-ui** : dashboard BMAD installé une seule fois (`scripts/bmad-ui-setup.sh`) et
  focalisé sur le projet courant par **`bmad-start`** (port dédié 5273).

### Sécurité / conformité

- Forfait Max garanti (refus si `ANTHROPIC_API_KEY`) ; SDK écarté (CGU).
- Local-first : aucune exposition internet ; secrets hors dépôt.
