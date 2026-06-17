# ADR 0002 — LiteLLM route les modèles locaux uniquement ; Claude via abonnement

- **Statut** : Accepté
- **Date** : 2026-06-14
- **Décideurs** : protin
- **Amende** : [ADR 0001](0001-architecture-assistant-ia-local-orchestre.md), décision structurante n°2
  (« LiteLLM = gateway unique routant vers API Claude, LM Studio local, Bedrock »).

## Contexte

L'ADR 0001 faisait de LiteLLM la gateway unique vers **tous** les modèles, Claude
API compris. Deux éléments invalident ce choix pour Claude :

1. **Abonnement ≠ API.** Le forfait Claude Max (claude.ai / Claude Code) et l'API
   Anthropic (console développeur, `sk-ant-…`) sont deux systèmes de facturation
   **séparés**. L'API est facturée au token, indépendamment du forfait.
2. **CGU.** Depuis début 2026, l'authentification OAuth des plans (Pro/Max) est
   réservée à l'usage individuel ordinaire de Claude Code et des apps natives.
   Brancher le token d'abonnement dans un outil tiers (LiteLLM, Agent SDK custom…)
   viole explicitement les CGU — des comptes ont été suspendus. Il n'existe donc
   **aucun moyen légitime** d'alimenter LiteLLM en Claude via le forfait.

Conséquence : router Claude par LiteLLM imposerait une clé API payante au token,
alors que le forfait Max est déjà payé et couvre l'essentiel des usages Claude.

## Décision

**LiteLLM ne route que les modèles locaux** (LM Studio : `local-gemma`,
`local-qwen`, `local-embed`). Claude n'est pas routé par LiteLLM.

Routage Claude par mode d'usage :

| Usage Claude                                                 | Vecteur                            | Facturation                |
| ------------------------------------------------------------ | ---------------------------------- | -------------------------- |
| À la main (BMAD, dev)                                        | Claude Code (terminal / IDE)       | Forfait Max                |
| Automatisé (n8n)                                             | `claude -p` headless / Agent SDK   | Forfait / crédit Agent SDK |
| Tâche programmatique lourde exigeant Claude sans `claude -p` | route Claude au token dans LiteLLM | Clé API console (au token) |

Le 3ᵉ cas est une **exception future** : on n'ajoute une route `anthropic/` dans
`config.yaml` que si le besoin se présente, et la clé reste confinée au `.env` du
conteneur.

## Règle de sécurité / FinOps

**Ne jamais exporter `ANTHROPIC_API_KEY` dans le shell global.** Claude Code
détecte cette variable et l'utilise à la place du forfait → facturation API
silencieuse. La clé (si un jour ajoutée) reste dans le `.env` lu par docker-compose,
jamais dans l'environnement interactif.

## Conséquences

### Positives

- Coût Claude maîtrisé : l'usage courant passe par le forfait déjà payé.
- Conforme aux CGU (pas de bridge OAuth).
- LiteLLM recentré sur son rôle légitime et gratuit : porte d'entrée unifiée
  (API OpenAI-compatible + budgets/logs) vers les modèles **locaux**.

### Négatives / points d'attention

- Deux chemins distincts pour Claude (Claude Code vs `claude -p`) à orchestrer en
  Phase 3 (n8n) au lieu d'un endpoint unique.
- Le piège `ANTHROPIC_API_KEY` exporté doit être connu de tout l'outillage local.

## Alternatives écartées

- **Bridge OAuth du forfait dans LiteLLM** : hors CGU, risque de suspension.
- **Tout passer par une clé API au token** (ADR 0001 d'origine) : coût inutile
  alors que le forfait Max couvre l'usage interactif et l'automatisation individuelle.
