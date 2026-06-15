# ADR 0003 — Entrée Telegram par polling local (sans exposition internet)

- **Statut** : Accepté
- **Date** : 2026-06-15
- **Décideurs** : protin
- **Amende** : [ADR 0001](0001-architecture-assistant-ia-local-orchestre.md), Phase 4
  (« webhook n8n derrière tunnel »).

## Contexte

n8n écoute en `127.0.0.1` uniquement. Pour recevoir les messages Telegram, deux voies :

1. **Webhook + tunnel** : exposer le webhook n8n via un tunnel (cloudflared…) pour que
   Telegram puisse l'atteindre. Node Telegram natif n8n, mais : surface internet ouverte,
   et les tunnels gratuits « quick » changent d'URL à chaque redémarrage (ré-enregistrement
   du webhook). Gestion lourde pour un poste perso.
2. **Long-polling** : un service local interroge l'API Telegram (`getUpdates`) et pousse
   en interne vers n8n. Aucune connexion entrante, aucune URL publique.

## Décision

**Entrée Telegram par long-polling**, via un service `telegram-poller` (conteneur).
Aucune exposition internet — cohérent avec le caractère local-first/confidentiel du projet.

Le poller est un **adaptateur Telegram** ; n8n reste le **cerveau** :

- `telegram-poller` : `getUpdates`, **allowlist de chat IDs** (sécurité accès distant),
  transcription voix via `whisper`, envoi des réponses. Le **token Telegram ne vit que
  dans ce service**.
- `n8n` : webhook **local** `POST /webhook/telegram-in` `{chat_id, text}` → routage LLM
  (local `litellm` par défaut ; Claude via bridge en option) → réponse renvoyée au poller.

## Conséquences

### Positives

- Zéro surface internet, pas de tunnel à gérer, URL stable.
- Token Telegram confiné à un seul service.
- Allowlist appliquée au plus tôt (le poller jette les expéditeurs non autorisés).

### Négatives / points d'attention

- Pas de node Telegram-trigger natif : logique d'I/O Telegram portée par le poller (code maison).
- Le workflow n8n doit être **actif** pour exposer le webhook de production.
- Latence de polling (long-poll ~30 s, quasi temps réel en pratique).

## Alternatives écartées

- **Webhook + tunnel cloudflared** : surface internet + gestion d'URL ; réservé au cas où
  un push temps-réel strict ou des fonctions webhook-only deviendraient nécessaires.
- **Tout dans le poller (sans n8n)** : sortirait n8n de la boucle d'orchestration voulue.
