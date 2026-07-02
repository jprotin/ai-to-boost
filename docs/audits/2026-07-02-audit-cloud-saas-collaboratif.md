# Audit — Cloud / SaaS mutualisé + mode collaboratif

**Date** : 2026-07-02 · **Cas d'usage** : déployer ai-to-boost en **SaaS multi-tenant** (ex. Google Cloud) + **mode collaboratif** (une équipe travaillant sur le même projet) · **Méthode** : lecture seule.

## Verdict

**Faisable, mais rewrite architectural majeur — et un bloqueur légal préalable.** Le projet est conçu **local-first mono-utilisateur** ; le passer en SaaS mutualisé change sa nature.

## 🔴 Bloqueur n°1 — CGU Anthropic (rédhibitoire en l'état)

Tout le système appelle Claude via **`claude -p` sur le forfait personnel** (le worker **retire même** `ANTHROPIC_API_KEY`/`ANTHROPIC_AUTH_TOKEN` de l'environnement pour forcer le forfait — cf. ADR 0002, en-têtes de `claude_agent.py` / `claude_bridge.py`).

- Le forfait est une **licence d'usage individuel** → servir plusieurs clients via ce forfait **violerait les CGU** (risque de suspension).
- **Migration obligatoire** : basculer sur l'**API Anthropic facturée** (SDK + clés `sk-ant-…`), avec **facturation au token** et **clés/quotas par tenant**. Le CLI `claude -p` disparaît au profit du SDK.
- C'est une **décision produit/business** (coût API vs forfait) avant d'être technique. **Effort : gros.**

## Autres bloqueurs structurels

| Bloqueur                                | Constat                                                                                                                       | Effort |
| --------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------- | ------ |
| **Auth mono-utilisateur**               | webui = un seul compte (`WEBUI_USER`/`WEBUI_PASSWORD_HASH`), token `AGENT_TOKEN` partagé, pas d'orgs/rôles (ADR 0005)         | Gros   |
| **Services hôte (systemd) hors Docker** | worker `:8089` / bridge `:8088` sur l'hôte → pas cloud-native, pas de scaling horizontal                                      | Gros   |
| **État local stateful**                 | `RUN_LOCK` (1 job à la fois), `PIPELINES`/`LIVE` en mémoire (perdus au restart), worktrees + `pipeline.json` sur disque local | Gros   |
| **Isolation multi-tenant absente**      | registre projets **global** unique, `webui.db` SQLite non partitionné, secrets `.env` partagés                                | Moyen  |
| **Persistance fichiers non requêtable** | métadonnées pipeline en fichiers JSON (pas de DB indexée, pas d'audit centralisé)                                             | Moyen  |

**Cible technique** : API Anthropic + auth multi-tenant (orgs/rôles/RLS) + dockerisation worker/bridge + **Postgres** (pipelines, users, tenants, audit) + **locks distribués** (Redis/Postgres) + **storage partagé** (GCS/disques) pour les worktrees.

## Mode collaboratif (équipe sur le même projet)

**État actuel : 0 %.** Le design est « un projet, une personne à la fois » :

- **`RUN_LOCK` sérialise** : si Alice lance un pipeline, Bob attend puis échoue (timeout), sans feedback.
- **Pas d'isolation par utilisateur** : Bob verrait le pipeline d'Alice.
- **Conflits de merge non gérés** : deux pipelines qui touchent les mêmes fichiers → conflit au `collect`, résolution manuelle.
- **Pas de temps réel** : le live est en polling (~1 s), pas de WebSocket ni de présence.

**Pour le rendre possible** : multi-pipeline en parallèle (retirer `RUN_LOCK`), workspace = projet + équipe (rôles owner/editor/viewer), détection de conflits (pré-check `git merge-base` avant collect), WebSocket + audit trail. **Effort : énorme** (le module le plus complexe).

## Feuille de route indicative

| Phase | Contenu                                                                | Ordre de grandeur |
| ----- | ---------------------------------------------------------------------- | ----------------- |
| P1    | API Anthropic + auth multi-tenant + schéma Postgres                    | fondation         |
| P2    | Dockeriser worker/bridge + storage partagé                             | cloud-native      |
| P3    | Concurrence : job queue + locks distribués (retirer `RUN_LOCK`)        | scaling           |
| P4    | Collaboratif : multi-pipeline, WebSocket, détection de conflits, audit | produit           |
| P5    | Déploiement GCP (Cloud Run/GKE), secrets, observabilité, CI/CD         | mise en prod      |

**Estimation globale (grossière) : ~2 mois, 1–2 devs.**

## Conclusion

- ai-to-boost est **excellent pour sa cible actuelle** (assistant local mono-utilisateur, cf. la vision « tour de contrôle perso »).
- Le SaaS mutualisé est **conditionné par l'abandon du forfait** au profit de l'API payante (le vrai verrou), puis par un rewrite (auth, cloud-native, DB, concurrence, collaboratif).
- Le **mode collaboratif** est faisable **après** ces fondations, pas avant.

> Estimations d'effort indicatives. Les références de fichiers/lignes issues de l'exploration sont à revérifier avant tout chantier.
