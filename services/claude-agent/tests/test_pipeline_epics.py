#!/usr/bin/env python3
"""Tests autonomes (sans pytest) des fonctions pures du pipeline BMAD B2.

Verrouille le contrat de format avec bmad-ui : parsing epics.md, slug identique à
slugifyStoryLabel (parser.ts) et génération sprint-status.yaml conforme aux regex du
parser bmad-ui. Lancer : python3 services/claude-agent/tests/test_pipeline_epics.py
"""

import importlib.util
import os
import re
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_MODULE = os.path.join(_HERE, "..", "claude_agent.py")


def _load():
    spec = importlib.util.spec_from_file_location("claude_agent", _MODULE)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


m = _load()

# Regex du parser bmad-ui (scripts/server/epics/parser.ts) — le YAML généré doit matcher.
EPIC_STATUS_RE = re.compile(r"^\s+epic-\d+:\s*(backlog|in-progress|done)\s*$")
STORY_STATUS_RE = re.compile(
    r"^\s+\d+-\d+-[a-z0-9-]+:\s*" r"(backlog|ready-for-dev|in-progress|review|done)\s*$"
)


def test_slug_matches_bmad_ui():
    """slugifyStoryLabel SUPPRIME les caractères hors [a-z0-9 -] (pas de NFKD)."""
    cases = {
        "Créer une tâche": "crer-une-tche",
        "Gérer l'authentification": "grer-lauthentification",
        "Persistance des données": "persistance-des-donnes",
        "Webhook `checkout.session.completed`": "webhook-checkoutsessioncompleted",
        "**Paiement** (Stripe) !": "paiement-stripe",
        "   Export   CSV   ": "export-csv",
        "é à ç ù": "story",  # tout supprimé -> fallback
    }
    for raw, expected in cases.items():
        got = m._slugify(raw)
        assert got == expected, f"_slugify({raw!r}) = {got!r}, attendu {expected!r}"


def test_parse_epics_nominal():
    md = (
        "## Epic 1: Authentification\n"
        "desc\n"
        "### Story 1.1: Inscription par e-mail\n"
        "### Story 1.2: Connexion\n"
        "## Epic 2: Tableau de bord\n"
        "### Story 2.1: KPIs\n"
    )
    epics = m._parse_epics(md)
    assert len(epics) == 2
    assert [len(e["stories"]) for e in epics] == [2, 1]
    assert epics[0]["title"] == "Authentification"


def test_parse_epics_rejette_format_libre():
    assert m._parse_epics("- Epic A: blabla\n- Epic B: autre\n") == []


def test_sprint_status_conforme_regex_bmad_ui():
    epics = m._parse_epics(
        "## Epic 1: Auth\n### Story 1.1: Créer un compte\n### Story 1.2: Se connecter\n"
    )
    yaml = m._gen_sprint_status(epics, "Mon Projet Démo")
    lines = yaml.splitlines()
    assert lines[0] == "project: Mon Projet Démo"
    # project_key dérivé de _slugify : l'accent de 'Démo' est SUPPRIMÉ (dmo), pas translittéré
    assert lines[1] == "project_key: MON-PROJET-DMO"
    assert "development_status:" in lines
    epic_lines = [ln for ln in lines if ln.strip().startswith("epic-")]
    story_lines = [ln for ln in lines if re.match(r"^\s+\d+-\d+-", ln)]
    assert epic_lines and all(EPIC_STATUS_RE.match(ln) for ln in epic_lines)
    assert story_lines and all(STORY_STATUS_RE.match(ln) for ln in story_lines)
    # slug de la story cohérent avec _slugify (donc avec bmad-ui)
    assert "  1-1-crer-un-compte: backlog" in lines


def test_story_utilise_le_numero_d_epic_parent():
    """Story mal numérotée (2.1 sous Epic 1) -> id rattaché à epic-1, pas d'epic-2 fantôme."""
    epics = m._parse_epics("## Epic 1: Auth\n### Story 2.1: Oups mauvais numero\n")
    yaml = m._gen_sprint_status(epics, "P")
    assert "  epic-1: backlog" in yaml
    assert "  1-1-oups-mauvais-numero: backlog" in yaml
    assert "epic-2" not in yaml


def test_nom_projet_avec_newline_neutralise():
    """Un nom multi-lignes ne doit pas injecter de fausses lignes dans le YAML strict."""
    yaml = m._gen_sprint_status([], "Projet\n  epic-9: done")
    assert yaml.splitlines()[0] == "project: Projet epic-9: done"
    assert "  epic-9: done" not in yaml.splitlines()


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
