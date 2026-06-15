#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = ["qdrant-client[fastembed]>=1.12"]
# ///
"""Ingestion RAG — indexe knowledge/ dans Qdrant (embeddings nomic, 768d).

Utilise la même intégration FastEmbed que `mcp-server-qdrant` (client.add/query)
avec le même modèle → collection compatible entre ingestion et recherche.

Usage :
  uv run services/rag/ingest.py                 # (ré)indexe le dossier knowledge/
  uv run services/rag/ingest.py --search "..."  # test de recherche

Config (env, défauts entre parenthèses) :
  QDRANT_URL        (http://127.0.0.1:6333)
  RAG_COLLECTION    (knowledge)
  EMBEDDING_MODEL   (nomic-ai/nomic-embed-text-v1.5)
  KNOWLEDGE_DIR     (knowledge)
"""

import argparse
import os
import pathlib
import uuid

from qdrant_client import QdrantClient

QDRANT_URL = os.environ.get("QDRANT_URL", "http://127.0.0.1:6333")
COLLECTION = os.environ.get("RAG_COLLECTION", "knowledge")
MODEL = os.environ.get("EMBEDDING_MODEL", "nomic-ai/nomic-embed-text-v1.5")
KNOWLEDGE_DIR = pathlib.Path(os.environ.get("KNOWLEDGE_DIR", "knowledge"))
EXTS = {".md", ".txt", ".markdown"}
CHUNK_CHARS = 1000


def chunk(text: str) -> list[str]:
    """Découpe en blocs ~CHUNK_CHARS, en respectant les paragraphes."""
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


def ingest(client: QdrantClient) -> None:
    files = [
        p
        for p in KNOWLEDGE_DIR.rglob("*")
        if p.suffix.lower() in EXTS and p.name != "README.md"
    ]
    if not files:
        print(
            f"Aucun document ({'/'.join(EXTS)}) dans {KNOWLEDGE_DIR}/ — rien à indexer."
        )
        return
    docs, metas, ids = [], [], []
    for f in files:
        rel = f.relative_to(KNOWLEDGE_DIR).as_posix()
        for i, c in enumerate(chunk(f.read_text(encoding="utf-8"))):
            docs.append(c)
            metas.append({"source": rel, "chunk": i})
            ids.append(str(uuid.uuid5(uuid.NAMESPACE_URL, f"{rel}#{i}")))
    client.add(collection_name=COLLECTION, documents=docs, metadata=metas, ids=ids)
    print(
        f"Indexé {len(docs)} chunks depuis {len(files)} fichier(s) -> collection '{COLLECTION}'."
    )


def search(client: QdrantClient, query: str) -> None:
    res = client.query(collection_name=COLLECTION, query_text=query, limit=3)
    print(f"Top {len(res)} pour : {query!r}\n")
    for i, r in enumerate(res, 1):
        src = (r.metadata or {}).get("source", "?")
        doc = (r.metadata or {}).get("document", "")
        print(f"[{i}] score={r.score:.3f} source={src}\n{doc[:300]}\n")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--search", metavar="QUERY", help="tester une recherche au lieu d'indexer"
    )
    args = ap.parse_args()
    client = QdrantClient(url=QDRANT_URL)
    client.set_model(MODEL)
    if args.search:
        search(client, args.search)
    else:
        ingest(client)


if __name__ == "__main__":
    main()
