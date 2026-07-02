# Audit — Documentation

**Date** : 2026-07-02 · **Portée** : état de la documentation du projet et plan de nettoyage · **Méthode** : lecture seule (README, CLAUDE.md, docs/, ADR, runbooks, docs services).

## Verdict

**~70 % à jour.** Le socle documentaire (ADR, runbooks, guide de déploiement) est solide et cohérent. Trois axes d'amélioration : un fichier placeholder, quelques références obsolètes, et de l'hygiène (doc service webui, manques de spec).

## Inventaire (synthèse)

| Document                      | Statut               | Note                                                                           |
| ----------------------------- | -------------------- | ------------------------------------------------------------------------------ |
| `README.md`                   | À jour               | Vue d'ensemble + liens                                                         |
| `CLAUDE.md` (racine)          | **Placeholder**      | Sections `<à remplir>` (objectif, stack, ADR, commandes)                       |
| `CHANGELOG.md`, `VERSION`     | À jour               |                                                                                |
| `docs/guide-deploiement.md`   | À jour               | Complet (install, config, parcours, CLI, ports)                                |
| `docs/adr/0001…0008`          | À jour               | Cohérents ; 0004/0005/0006 ont des en-têtes en anglais (incohérence de format) |
| `docs/runbooks/*`             | À jour               | Complets ; qq mentions résiduelles « LM Studio »                               |
| `docs/phase6-plan.md`         | **Obsolète**         | Réfs « LM Studio » (post-ADR 0007 = Ollama)                                    |
| `docs/runbooks/webui.md`      | **Obsolète (1 réf)** | « chargé dans LM Studio » → Ollama                                             |
| `services/webui/README.md`    | **Boilerplate**      | Template Next.js par défaut, pas de doc métier                                 |
| `services/webui/CLAUDE.md`    | **Placeholder**      | `@AGENTS.md` quasi vide                                                        |
| `knowledge/exemple-projet.md` | **À supprimer**      | Marqué « tu peux le supprimer » (aussi ingéré dans le RAG `knowledge`)         |

## Actions de nettoyage (priorisées)

**Haute**

1. Remplir `CLAUDE.md` racine (objectif, stack, statut, contraintes, ADR en bref, commandes essentielles).
2. Corriger « LM Studio → Ollama » : `docs/phase6-plan.md`, `docs/runbooks/webui.md`, `docs/adr/0006-*`.

**Moyenne** 3. Documenter `services/webui/README.md` (archi BFF, auth, chat, projets, pipeline, archive) + réparer `services/webui/CLAUDE.md`. 4. Harmoniser les en-têtes des ADR 0004/0005/0006 (français, comme les autres).

**Basse** 5. Supprimer `knowledge/exemple-projet.md` (+ ré-ingérer le RAG).

## Manques principaux (à créer plus tard)

- Doc d'**architecture d'ensemble** détaillée (flux entre les 8 services / workers ; le SVG existe mais n'est pas explicité).
- **Référence des variables d'environnement** (type/défaut/impact).
- **Troubleshooting centralisé** (aujourd'hui éparpillé dans les runbooks).
- Doc **métier du service webui** (BFF, routes API).
- Spec du **contrat gateway** (ADR 0006) — endpoints formels.

**Effort de nettoyage (actions 1–5) : ~3–4 h.**
