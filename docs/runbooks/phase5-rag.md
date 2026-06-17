# Runbook — Phase 5 : RAG (Qdrant + MCP)

Base de connaissances vectorielle interrogeable par l'assistant. Voir
[ADR 0001](../adr/0001-architecture-assistant-ia-local-orchestre.md).

## Architecture

- `qdrant` (conteneur) : base vectorielle, **local-only** (`127.0.0.1:6333/6334`),
  volume `qdrant-data`. **Sans clé API en v1** (la liaison localhost est la protection).
- **Ingestion** : `services/rag/ingest.py` — découpe les docs de `knowledge/` en
  chunks, les embedde (**nomic, 768d**) et les upsert dans la collection `knowledge`.
- **Serveur MCP** : `mcp-server-qdrant` lancé par **Claude Code** via `uvx` (cf.
  `.mcp.json`), même Qdrant + même collection + même modèle nomic → expose la
  recherche (`qdrant-find`) à Claude Code.

**Cohérence embeddings** : ingestion et MCP utilisent le **même modèle nomic** via
l'intégration FastEmbed de `qdrant-client` → collection compatible. Ne pas mélanger
les modèles (sinon recherche cassée).

## Prérequis

- `uv`/`uvx` installés.
- Service Qdrant démarré.

## Démarrage de Qdrant

```bash
docker compose up -d qdrant
curl -s http://127.0.0.1:6333/healthz       # "healthz check passed"
```

## Indexer des documents

1. Déposer des fichiers (`.md`, `.txt`) dans `knowledge/` (gitignoré — perso).
2. (Ré)indexer :

   ```bash
   uv run services/rag/ingest.py
   ```

   Le 1er run installe les deps et télécharge le modèle nomic (FastEmbed).

3. Tester une recherche :

   ```bash
   uv run services/rag/ingest.py --search "ta question"
   ```

Ré-indexer après chaque ajout/modif (IDs déterministes → pas de doublons sur
re-run du même contenu ; un doc supprimé du dossier n'est pas retiré de Qdrant
automatiquement — voir Notes).

## Brancher sur Claude Code

Le fichier **`.mcp.json`** (racine du repo) déclare le serveur MCP `qdrant`.

1. **Redémarrer Claude Code** dans ce dossier (les serveurs MCP se chargent au
   démarrage).
2. À l'invite, **approuver** le serveur MCP `qdrant`.
3. Claude Code dispose alors de l'outil **`qdrant-find`** : pose une question, il
   interroge la base de connaissances.

> 1er appel : FastEmbed télécharge le modèle nomic côté serveur MCP (latence initiale).

## Validation (critère de passage Phase 6)

- `uv run services/rag/ingest.py` indexe `knowledge/`.
- `--search "..."` renvoie des passages pertinents avec un score.
- Dans Claude Code, `qdrant-find` retrouve l'info d'un document déposé.

## Dépannage

- **Recherche vide / hors-sujet** : modèle d'embedding différent entre ingestion et
  MCP → vérifier `EMBEDDING_MODEL` identique (`.env` et `.mcp.json`).
- **Connexion refusée** : Qdrant down (`docker compose ps`) ou mauvais `QDRANT_URL`.
- **MCP absent dans Claude Code** : `.mcp.json` non chargé (redémarrer) ou serveur
  non approuvé.

## Notes / évolutions

- **Sans clé API** en v1 (local-only). Pour durcir : activer
  `QDRANT__SERVICE__API_KEY` et fournir la clé au client/MCP.
- **Suppressions** : un fichier retiré de `knowledge/` reste dans Qdrant. Pour repartir
  propre : supprimer la collection (`DELETE /collections/knowledge`) puis ré-indexer.
- **PDF/docx** : convertir en texte avant dépôt (v1 = `.md`/`.txt`).
- **RAG dans n8n/Telegram** : l'assistant Telegram pourra interroger Qdrant (nomic via
  LiteLLM `local-embed`, 768d compatible) — étape ultérieure.
