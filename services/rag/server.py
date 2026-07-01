"""Service de requête RAG — interroge Qdrant avec le MÊME stack FastEmbed que
`ingest.py` et `mcp-server-qdrant` (embeddings nomic 768d, vecteur nommé
`fast-nomic-embed-text-v1.5`) → compatibilité vecteur garantie.

Exposé pour la webui (chat projet), qui ne peut pas reproduire fidèlement ces
embeddings côté Node.

  POST /query {"collections": ["knowledge","proj-x"], "query": "...", "limit": 5}
    -> {"hits": [{"score":.., "source":"..","collection":"..","text":".."}]}
  GET /health -> {"status":"ok"}

Config (env) : QDRANT_URL, EMBEDDING_MODEL, RAG_PORT.
"""

import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from qdrant_client import QdrantClient

QDRANT_URL = os.environ.get("QDRANT_URL", "http://qdrant:6333")
MODEL = os.environ.get("EMBEDDING_MODEL", "nomic-ai/nomic-embed-text-v1.5")
PORT = int(os.environ.get("RAG_PORT", "8100"))
MAX_LIMIT = 10

# Un seul client : set_model charge (télécharge au 1er run) le modèle FastEmbed.
_client = QdrantClient(url=QDRANT_URL)
_client.set_model(MODEL)


def _query(collections: list[str], query: str, limit: int) -> list[dict]:
    hits: list[dict] = []
    for coll in collections:
        try:
            if not _client.collection_exists(coll):
                continue
            res = _client.query(collection_name=coll, query_text=query, limit=limit)
        except Exception:
            continue  # collection illisible → on l'ignore, dégradation douce
        for r in res:
            meta = r.metadata or {}
            hits.append(
                {
                    "score": float(r.score),
                    "source": meta.get("source", "?"),
                    "collection": coll,
                    "text": meta.get("document", ""),
                }
            )
    hits.sort(key=lambda h: h["score"], reverse=True)
    return hits[:limit]


class Handler(BaseHTTPRequestHandler):
    def _send(self, code: int, obj: dict) -> None:
        body = json.dumps(obj).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802
        if self.path == "/health":
            self._send(200, {"status": "ok"})
        else:
            self._send(404, {"error": "not found"})

    def do_POST(self) -> None:  # noqa: N802
        if self.path != "/query":
            self._send(404, {"error": "not found"})
            return
        try:
            n = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(n) or b"{}")
        except Exception:
            self._send(400, {"error": "JSON invalide"})
            return
        query = (body.get("query") or "").strip()
        collections = body.get("collections")
        if not query or not isinstance(collections, list):
            self._send(400, {"error": "query/collections requis"})
            return
        try:
            limit = max(1, min(int(body.get("limit") or 5), MAX_LIMIT))
        except (TypeError, ValueError):
            limit = 5
        try:
            hits = _query([str(c) for c in collections], query, limit)
        except Exception as e:  # pragma: no cover
            self._send(502, {"error": str(e)})
            return
        self._send(200, {"hits": hits})

    def log_message(self, *args) -> None:  # silencieux
        pass


def main() -> None:
    srv = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    print(
        f"RAG query service on :{PORT} (qdrant={QDRANT_URL}, model={MODEL})",
        flush=True,
    )
    srv.serve_forever()


if __name__ == "__main__":
    main()
