"""Service RAG — recherche et indexation dans Qdrant avec le MÊME stack FastEmbed que
`ingest.py` et `mcp-server-qdrant` (embeddings nomic 768d, vecteur nommé
`fast-nomic-embed-text-v1.5`) → compatibilité vecteur garantie.

Exposé pour la webui (chat projet) et pour antares_ai (fiches de connaissance), qui ne
peuvent pas reproduire fidèlement ces embeddings côté client.

  POST /query {"collections": ["knowledge","proj-x"], "query": "...", "limit": 5}
    -> {"hits": [{"score":.., "source":"..","collection":"..","text":"..", ...}]}
    Les documents obsolètes (status "obsolete") ou expirés (valid_until_ts passé) sont
    exclus ; les documents indexés par ingest.py n'ont pas ces champs et restent visibles.
  POST /documents {"collection": "proj-x", "doc_id": "...", "text": "...",
                   "metadata": {"source": "...", "origin": "antares", ...}}
    -> {"doc_id": "...", "chunks": n}  (remplace les chunks existants du même doc_id)
  DELETE /documents {"collection": "proj-x", "doc_id": "..."} -> {"deleted": "..."}
  GET /health -> {"status":"ok"}

Écriture (POST/DELETE /documents) : refusée si RAG_WRITE_TOKEN n'est pas défini ;
sinon, en-tête « Authorization: Bearer <RAG_WRITE_TOKEN> » exigé.

Config (env) : QDRANT_URL, EMBEDDING_MODEL, RAG_PORT, RAG_WRITE_TOKEN.
"""

import hmac
import json
import os
import re
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from qdrant_client import QdrantClient, models

QDRANT_URL = os.environ.get("QDRANT_URL", "http://qdrant:6333")
MODEL = os.environ.get("EMBEDDING_MODEL", "nomic-ai/nomic-embed-text-v1.5")
PORT = int(os.environ.get("RAG_PORT", "8100"))
WRITE_TOKEN = os.environ.get("RAG_WRITE_TOKEN", "")
MAX_LIMIT = 10
CHUNK_CHARS = 1000  # même découpage que ingest.py
MAX_TEXT_CHARS = 200_000
COLLECTION_RE = re.compile(r"^(knowledge|proj-[a-z0-9_-]{1,64})$")
DOC_ID_RE = re.compile(r"^[A-Za-z0-9_.:-]{1,128}$")

_client = None


def client() -> QdrantClient:
    """Client unique, créé au premier appel : set_model charge le modèle FastEmbed."""
    global _client
    if _client is None:
        _client = QdrantClient(url=QDRANT_URL)
        _client.set_model(MODEL)
    return _client


def chunk(text: str) -> list[str]:
    """Découpe en blocs ~CHUNK_CHARS, en respectant les paragraphes (cf. ingest.py)."""
    out, buf = [], ""
    for para in text.split("\n\n"):
        para = para.strip()
        if not para:
            continue
        if len(buf) + len(para) + 2 > CHUNK_CHARS and buf:
            out.append(buf.strip())
            buf = ""
        buf += para + "\n\n"
    if buf.strip():
        out.append(buf.strip())
    return out


def active_filter(now: float | None = None) -> models.Filter:
    """Exclut les documents obsolètes ou expirés (champs absents : document conservé)."""
    now = time.time() if now is None else now
    return models.Filter(
        must_not=[
            models.FieldCondition(
                key="status", match=models.MatchValue(value="obsolete")
            ),
            models.FieldCondition(key="valid_until_ts", range=models.Range(lt=now)),
        ]
    )


def doc_filter(doc_id: str) -> models.Filter:
    return models.Filter(
        must=[
            models.FieldCondition(key="doc_id", match=models.MatchValue(value=doc_id))
        ]
    )


def point_ids(doc_id: str, count: int) -> list[str]:
    return [
        str(uuid.uuid5(uuid.NAMESPACE_URL, f"doc:{doc_id}#{i}")) for i in range(count)
    ]


def _query(collections: list[str], query: str, limit: int) -> list[dict]:
    hits: list[dict] = []
    for coll in collections:
        try:
            if not client().collection_exists(coll):
                continue
            res = client().query(
                collection_name=coll,
                query_text=query,
                query_filter=active_filter(),
                limit=limit,
            )
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
                    "doc_id": meta.get("doc_id"),
                    "origin": meta.get("origin"),
                }
            )
    hits.sort(key=lambda h: h["score"], reverse=True)
    return hits[:limit]


def index_document(collection: str, doc_id: str, text: str, metadata: dict) -> int:
    """Remplace les chunks du document puis les indexe (même embedding que ingest.py)."""
    parts = chunk(text)
    if not parts:
        raise ValueError("texte vide")
    delete_document(collection, doc_id)
    base = {k: v for k, v in metadata.items() if k not in ("document", "doc_id")}
    client().add(
        collection_name=collection,
        documents=parts,
        metadata=[{**base, "doc_id": doc_id, "chunk": i} for i in range(len(parts))],
        ids=point_ids(doc_id, len(parts)),
    )
    return len(parts)


def delete_document(collection: str, doc_id: str) -> None:
    if client().collection_exists(collection):
        client().delete(
            collection_name=collection,
            points_selector=models.FilterSelector(filter=doc_filter(doc_id)),
        )


def validate_write(body: dict) -> tuple[str, str]:
    collection = str(body.get("collection") or "")
    doc_id = str(body.get("doc_id") or "")
    if not COLLECTION_RE.match(collection):
        raise ValueError("collection invalide (knowledge ou proj-<slug>)")
    if not DOC_ID_RE.match(doc_id):
        raise ValueError("doc_id invalide")
    return collection, doc_id


class Handler(BaseHTTPRequestHandler):
    def _send(self, code: int, obj: dict) -> None:
        body = json.dumps(obj).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _body(self) -> dict:
        n = int(self.headers.get("Content-Length", 0))
        return json.loads(self.rfile.read(n) or b"{}")

    def _write_allowed(self) -> bool:
        if not WRITE_TOKEN:
            self._send(403, {"error": "écriture désactivée (RAG_WRITE_TOKEN absent)"})
            return False
        given = self.headers.get("Authorization", "")
        if not hmac.compare_digest(given, f"Bearer {WRITE_TOKEN}"):
            self._send(401, {"error": "unauthorized"})
            return False
        return True

    def do_GET(self) -> None:  # noqa: N802
        if self.path == "/health":
            self._send(200, {"status": "ok", "write": bool(WRITE_TOKEN)})
        else:
            self._send(404, {"error": "not found"})

    def do_POST(self) -> None:  # noqa: N802
        if self.path == "/documents":
            self._post_document()
            return
        if self.path != "/query":
            self._send(404, {"error": "not found"})
            return
        try:
            body = self._body()
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

    def _post_document(self) -> None:
        if not self._write_allowed():
            return
        try:
            body = self._body()
            collection, doc_id = validate_write(body)
            text = str(body.get("text") or "")
            if len(text) > MAX_TEXT_CHARS:
                raise ValueError("texte trop long")
            metadata = body.get("metadata") or {}
            if not isinstance(metadata, dict):
                raise ValueError("metadata doit être un objet")
            chunks = index_document(collection, doc_id, text, metadata)
        except ValueError as e:
            self._send(400, {"error": str(e)})
            return
        except Exception as e:  # pragma: no cover
            self._send(502, {"error": str(e)})
            return
        self._send(200, {"doc_id": doc_id, "chunks": chunks})

    def do_DELETE(self) -> None:  # noqa: N802
        if self.path != "/documents":
            self._send(404, {"error": "not found"})
            return
        if not self._write_allowed():
            return
        try:
            collection, doc_id = validate_write(self._body())
            delete_document(collection, doc_id)
        except ValueError as e:
            self._send(400, {"error": str(e)})
            return
        except Exception as e:  # pragma: no cover
            self._send(502, {"error": str(e)})
            return
        self._send(200, {"deleted": doc_id})

    def log_message(self, *args) -> None:  # silencieux
        pass


def main() -> None:
    client()
    srv = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    print(
        f"RAG service on :{PORT} (qdrant={QDRANT_URL}, model={MODEL}, "
        f"write={'on' if WRITE_TOKEN else 'off'})",
        flush=True,
    )
    srv.serve_forever()


if __name__ == "__main__":
    main()
