#!/usr/bin/env python3
"""Tests autonomes (sans pytest) de la normalisation des commandes vocales du poller.

Lancer : python3 services/telegram-poller/tests/test_voice_command.py
"""

import importlib.util
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_MODULE = os.path.join(_HERE, "..", "poller.py")


def _load():
    spec = importlib.util.spec_from_file_location("poller", _MODULE)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


m = _load()
vc = m._voice_to_command


def test_verbes_pipeline():
    cases = {
        "lance une page html qui dit bonjour": "/run une page html qui dit bonjour",
        "démarre le projet": "/run le projet",
        "run une todo": "/run une todo",
        "approuve": "/approve",
        "valide": "/approve",
        "ok": "/approve",
        "révise ajoute un titre": "/revise ajoute un titre",
        "corrige le bug de date": "/revise le bug de date",
        "stop": "/stop",
        "arrête": "/stop",
        "annule": "/stop",
    }
    for raw, expected in cases.items():
        got = vc(raw)
        assert got == expected, f"vc({raw!r}) = {got!r}, attendu {expected!r}"


def test_ponctuation_et_casse():
    # whisper renvoie souvent une majuscule + un point final
    assert vc("Stop.") == "/stop"
    assert vc("Approuve !") == "/approve"
    assert vc("Lance, une page") == "/run une page"


def test_slash_ou_barre_dictes():
    assert vc("slash run une page") == "/run une page"
    assert vc("barre stop") == "/stop"
    assert vc("slash approve") == "/approve"


def test_non_commande_inchangee():
    # une phrase de chat qui ne commence pas par un verbe de commande
    for s in ["bonjour comment ça va", "explique-moi le RAG", "merci beaucoup"]:
        assert vc(s) == s, f"vc({s!r}) ne doit pas changer"


def test_deja_slash_inchange():
    assert vc("/run déjà formaté") == "/run déjà formaté"


def test_vide():
    assert vc("") == ""
    assert vc("   ") == "   "


def main():
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = 0
    for t in tests:
        try:
            t()
            print(f"PASS {t.__name__}")
        except AssertionError as exc:
            failed += 1
            print(f"FAIL {t.__name__}: {exc}")
    print(f"\n{len(tests) - failed}/{len(tests)} tests OK")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
