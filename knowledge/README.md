# knowledge/ — base de connaissances RAG

Dépose ici tes documents (`.md`, `.txt`) à rendre interrogeables par l'assistant
(via le RAG Qdrant + serveur MCP, cf. [runbook Phase 5](../docs/runbooks/phase5-rag.md)).

- Le **contenu de ce dossier est gitignoré** (documents perso, non poussés sur GitHub).
  Seul ce `README.md` est versionné.
- Après ajout/modification de documents, (ré)indexe :

  ```bash
  uv run services/rag/ingest.py
  ```

- Formats pris en charge en v1 : `.md`, `.txt`, `.markdown` (PDF/docx → convertir
  en texte d'abord).
