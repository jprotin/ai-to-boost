#!/usr/bin/env python3
"""Tests autonomes (sans pytest) du service RAG : fonctions pures + intégration Qdrant.

Unitaires : découpage, validation des écritures, identifiants stables, filtre actif.
Intégration (si RAG_IT_QDRANT est défini, ex. http://qdrant:6333) : indexe dans une
collection temporaire, recherche, exclut obsolète / expiré, supprime.

Lancer (dans l'image rag, sur le réseau ai-assistant-net) :
  docker run --rm --network ai-assistant-net -e RAG_IT_QDRANT=http://qdrant:6333 \\
    -v "$PWD/services/rag:/app" -v rag-cache:/cache -e FASTEMBED_CACHE_PATH=/cache \\
    --entrypoint python <image rag> /app/tests/test_server.py
"""

import importlib.util
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))


def _load():
    if os.environ.get("RAG_IT_QDRANT"):
        os.environ["QDRANT_URL"] = os.environ["RAG_IT_QDRANT"]
    spec = importlib.util.spec_from_file_location(
        "rag_server", os.path.join(HERE, "..", "server.py")
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


S = _load()


def test_chunk_respects_paragraphs():
    text = "\n\n".join(["a" * 600, "b" * 600, "c" * 100])
    parts = S.chunk(text)
    assert len(parts) == 2, parts
    assert parts[0] == "a" * 600
    assert parts[1].startswith("b" * 600) and parts[1].endswith("c" * 100)
    assert S.chunk("   \n\n  ") == []


def test_validate_write():
    assert S.validate_write(
        {"collection": "proj-idp-galaxy", "doc_id": "fiche:42"}
    ) == (
        "proj-idp-galaxy",
        "fiche:42",
    )
    assert (
        S.validate_write({"collection": "knowledge", "doc_id": "a"})[0] == "knowledge"
    )
    for bad in (
        {"collection": "autre", "doc_id": "a"},
        {"collection": "proj-../x", "doc_id": "a"},
        {"collection": "knowledge", "doc_id": ""},
        {"collection": "knowledge", "doc_id": "a b"},
    ):
        try:
            S.validate_write(bad)
        except ValueError:
            continue
        raise AssertionError(f"accepté à tort : {bad}")


def test_point_ids_stable_and_distinct():
    ids = S.point_ids("fiche:1", 3)
    assert ids == S.point_ids("fiche:1", 3)
    assert len(set(ids)) == 3
    assert set(ids).isdisjoint(S.point_ids("fiche:2", 3))


def test_active_filter_excludes_obsolete_and_expired():
    f = S.active_filter(now=1000.0)
    keys = {c.key for c in f.must_not}
    assert keys == {"status", "valid_until_ts"}
    expiry = next(c for c in f.must_not if c.key == "valid_until_ts")
    assert expiry.range.lt == 1000.0


def test_integration_qdrant():
    if not os.environ.get("RAG_IT_QDRANT"):
        print("  (intégration ignorée : RAG_IT_QDRANT non défini)")
        return
    coll = "proj-rag-it-temp"
    client = S.client()
    if client.collection_exists(coll):
        client.delete_collection(coll)
    try:
        base = {"source": "fiche.md", "origin": "antares"}
        S.index_document(
            coll, "fiche:actif", "Le port du service de paie est 8443.", base
        )
        S.index_document(
            coll,
            "fiche:obsolete",
            "Le port du service de paie était 8080.",
            {**base, "status": "obsolete"},
        )
        S.index_document(
            coll,
            "fiche:expiree",
            "Le port du service de paie sera 9090 jusqu'en 2020.",
            {**base, "valid_until_ts": time.time() - 3600},
        )
        hits = S._query([coll], "port du service de paie", 5)
        ids = {h["doc_id"] for h in hits}
        assert ids == {"fiche:actif"}, ids
        assert hits[0]["origin"] == "antares"
        # Réindexation : remplace sans doublon
        S.index_document(
            coll, "fiche:actif", "Le port du service de paie est 8443.", base
        )
        count = client.count(coll, count_filter=S.doc_filter("fiche:actif")).count
        assert count == 1, count
        S.delete_document(coll, "fiche:actif")
        assert S._query([coll], "port du service de paie", 5) == []
    finally:
        if client.collection_exists(coll):
            client.delete_collection(coll)


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = 0
    for test in tests:
        try:
            test()
            print(f"OK   {test.__name__}")
        except Exception as exc:  # noqa: BLE001
            failed += 1
            print(f"FAIL {test.__name__}: {exc!r}")
    sys.exit(1 if failed else 0)
