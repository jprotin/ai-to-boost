# 0006 — Contrat de gateway unifié + transports (sync direct / async n8n)

- **Status** : accepted
- **Date** : 2026-06-26
- **Auteur(s)** : protin
- **Tags** : architecture, gateway, n8n, llm, standardisation

## Contexte

Objectif : un **hub agentic standardisé** où tous les frontends (webui, futur mobile,
voix, etc.) communiquent de façon **homogène** avec la plateforme (n8n, LiteLLM, LM Studio,
Claude, BMAD). Tentation initiale : faire de **n8n le point d'entrée unique** par lequel
**chaque** appel transite (frontend → n8n → LLM → n8n → frontend).

Contraintes mesurées :

- **n8n ne streame pas** : les webhooks sont requête/réponse **bufferisée**
  (`Respond to Webhook` renvoie le corps complet). Pas de token-par-token.
- Tout router via n8n ⇒ **+1 à +2 hops** + exécution workflow par appel, **goulot** et
  **SPOF** pour toutes les apps, logique en **JSON n8n** difficile à tester/versionner.
- Le pattern « 2 workflows » (aller + retour LiteLLM→n8n→frontend) ne donne que de
  l'**async** (réponse complète livrée plus tard), pas du streaming.

## Décision

On standardise le **contrat**, pas le **chemin réseau**.

1. **Un contrat de gateway stable** (spec API : `/chat`, `/pipeline`, `/run`, `/projects`…)
   que **tous** les frontends appellent à l'identique. Le **BFF de la webui** en est l'amorce ;
   le **worker** en est le cœur côté backend. Un futur mobile/voix réutilise le même contrat.
2. **Deux transports, selon la nature de l'appel** :
   - **Sync / streaming** (chat) → **appel direct** au gateway/BFF (bridge `claude -p`,
     LiteLLM) → **streaming token-par-token** possible.
   - **Async** (pipeline, jalons, jobs longs) → worker, et **n8n relaie les notifications**
     vers les canaux (déjà en place pour Telegram, Lot C).
3. **n8n = hub d'automatisation / edge** (Telegram, voix-in, cron, human-in-loop,
   intégrations), **pas** le proxy LLM obligatoire.

## Conséquences

### Positives

- **Homogénéisation** réelle (un seul contrat) sans imposer n8n comme hop universel.
- **Streaming** chat préservé ; pas de goulot/SPOF n8n sur la voie LLM.
- Chaque outil à sa place : n8n pour l'edge/async, BFF/worker pour le sync/LLM.
- Nouveau frontend = il parle le contrat gateway → intégration uniforme.

### Négatives / Coûts

- Il faut **définir et maintenir** le contrat gateway (versionné, documenté).
- Deux patterns de transport à comprendre (sync direct vs async-via-n8n).

### Neutres / À surveiller

- **CGU** inchangée : Claude via bridge `claude -p` (forfait), jamais l'API.
- Si un besoin d'**observabilité centralisée** des appels LLM émerge, le faire au niveau du
  **gateway** (logs/quotas), pas en réinsérant n8n dans la boucle.

## Alternatives non explorées (et pourquoi)

- **n8n comme proxy LLM unique** : pas de streaming, goulot/SPOF, non testable — rejeté.
- **Tout async (callbacks) même pour le chat** : latence + complexité, sans le bénéfice du
  streaming — rejeté pour le chat (réservé aux tâches longues/jalons).

## Références

- [ADR 0002](0002-litellm-modeles-locaux-uniquement.md) — LiteLLM local, Claude via `claude -p`
- [ADR 0004](0004-pipeline-bmad-multi-persona-multi-llm.md) — async/jalons via worker + n8n
- [ADR 0005](0005-webapp-tour-de-controle-nextjs.md) — webui + BFF (amorce du gateway)
