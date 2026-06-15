# Runbook — Phase 4 : entrée/sortie Telegram

Assistant pilotable par **texte ou voix** via un bot Telegram, sans exposition
internet (polling local). Voir [ADR 0001](../adr/0001-architecture-assistant-ia-local-orchestre.md)
et [ADR 0003](../adr/0003-telegram-polling-sans-exposition.md).

## Architecture

- `telegram-poller` (conteneur) = adaptateur : `getUpdates`, allowlist chat IDs,
  voix→`whisper`, envoi des réponses. **Token Telegram confiné ici.**
- `n8n` = cerveau : webhook local `POST /webhook/telegram-in` `{chat_id, text}` →
  LiteLLM `local-gemma` → réponse.

Parcours : message Telegram → poller (allowlist ; si voix → whisper) → n8n → LiteLLM
→ réponse renvoyée dans Telegram.

## Prérequis (côté Telegram)

1. Compte Telegram (gratuit).
2. **@BotFather** → `/newbot` → nom + username en `…bot` → récupérer le **token**.
3. **@userinfobot** → récupérer ton **chat ID** numérique.
4. Renseigner `.env` :

```
TELEGRAM_BOT_TOKEN=123456:ABC-...
TELEGRAM_ALLOWED_CHAT_IDS=123456789      # plusieurs IDs séparés par des virgules
```

## n8n — workflow cerveau

1. Importer `services/n8n/workflows/03-telegram-assistant.json` (UI → Import from File).
2. **Vérifier les flèches** Webhook → LiteLLM → Répondre (raccorder si besoin).
3. Nœud _LiteLLM local-gemma_ : remplacer `CHANGEME_LITELLM_MASTER_KEY` par la
   `LITELLM_MASTER_KEY` du `.env` (ou credential _Header Auth_).
4. **Activer** le workflow (toggle _Active_ en haut) — indispensable pour exposer
   le webhook de production `/webhook/telegram-in`.

## Démarrage du poller

```bash
docker compose up -d telegram-poller
docker compose logs -f telegram-poller   # "telegram-poller démarré (allowlist: [...])"
```

## Validation

- Dans Telegram, écris à ton bot : **un message texte** (ex. « Dis bonjour ») →
  réponse de l'assistant (local-gemma).
- Envoie un **message vocal** en français → le bot répond « 🎙️ Transcription en
  cours… » puis la réponse basée sur la transcription whisper.

Logs utiles : `docker compose logs -f telegram-poller`.

## Dépannage

- **Aucune réaction** : workflow n8n non **actif** (webhook de prod absent) ; ou
  `chat_id` absent de l'allowlist (voir logs `[skip]`).
- **Erreur traitement** renvoyée dans Telegram : voir logs poller ; souvent le
  placeholder `CHANGEME_LITELLM_MASTER_KEY` non remplacé (401 LiteLLM) ou `local-gemma`
  déchargé (`lms ps`).
- **Voix non transcrite** : whisper down/froid (1er appel ~20 s) ; vérifier
  `docker compose ps` et `WHISPER_URL`.
- **Token invalide** : logs poller `Telegram HTTP 401` → vérifier `TELEGRAM_BOT_TOKEN`.

## Évolutions

- Routage par commande (`/opus` → Claude via bridge, défaut local) : ajouter une
  branche dans le workflow n8n selon le préfixe du message.
- Sorties enrichies (Markdown, fichiers, livrables) et veille classée : Phase 6.
