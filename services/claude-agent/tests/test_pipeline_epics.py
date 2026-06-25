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
import tempfile

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
# Override markdown bmad-ui (summarize.ts STORY_MARKDOWN_STATUS_REGEX) : ligne 'Status: ...'.
STORY_MD_STATUS_RE = re.compile(
    r"^Status:\s*(backlog|ready-for-dev|in-progress|review|done)\s*$",
    re.I | re.M,
)


def _seed_worktree():
    """Crée un worktree jetable avec un sprint-status.yaml représentatif."""
    wt = tempfile.mkdtemp(prefix="pl-test-")
    epics = m._parse_epics(
        "## Epic 1: Auth\n### Story 1.1: Créer un compte\n### Story 1.2: Se connecter\n"
        "## Epic 2: Profil\n### Story 2.1: Voir son profil\n"
    )
    dest = os.path.join(wt, m.SPRINT_REL)
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    with open(dest, "w", encoding="utf-8") as f:
        f.write(m._gen_sprint_status(epics, "Demo"))
    return wt


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


def test_read_sprint_status_ordonne_et_ignore_epics():
    wt = _seed_worktree()
    stories = m._read_sprint_status(wt)
    ids = [s["id"] for s in stories]
    assert ids == [
        "1-1-crer-un-compte",
        "1-2-se-connecter",
        "2-1-voir-son-profil",
    ], ids
    assert all(s["status"] == "backlog" for s in stories)
    assert all("epic-" not in s["id"] for s in stories)  # lignes epic non incluses


def test_set_story_status_cible_et_preserve():
    wt = _seed_worktree()
    m._set_story_status(wt, "1-2-se-connecter", "review")
    statuses = {s["id"]: s["status"] for s in m._read_sprint_status(wt)}
    assert statuses["1-2-se-connecter"] == "review"
    assert statuses["1-1-crer-un-compte"] == "backlog"  # autres lignes intactes
    # le fichier reste conforme aux regex bmad-ui après réécriture
    with open(os.path.join(wt, m.SPRINT_REL), encoding="utf-8") as f:
        lines = f.read().splitlines()
    epic_lines = [ln for ln in lines if ln.strip().startswith("epic-")]
    story_lines = [ln for ln in lines if re.match(r"^\s+\d+-\d+-", ln)]
    assert epic_lines and all(EPIC_STATUS_RE.match(ln) for ln in epic_lines)
    assert story_lines and all(STORY_STATUS_RE.match(ln) for ln in story_lines)


def test_skip_des_stories_terminees():
    """La boucle (sans feedback) ne reprend ni 'review' ni 'done'."""
    wt = _seed_worktree()
    m._set_story_status(wt, "1-1-crer-un-compte", "done")
    m._set_story_status(wt, "1-2-se-connecter", "review")
    stories = m._read_sprint_status(wt)
    todo = [s["id"] for s in stories if s["status"] not in ("review", "done")]
    assert todo == ["2-1-voir-son-profil"], todo
    # en révision (avec feedback) : tout sauf 'done' est repris
    todo_revise = [s["id"] for s in stories if s["status"] != "done"]
    assert todo_revise == ["1-2-se-connecter", "2-1-voir-son-profil"], todo_revise


def test_write_story_md_nom_exact_et_status():
    wt = _seed_worktree()
    rel = m._write_story_md(wt, "2-1-voir-son-profil", "review", "Résumé du dev.")
    assert rel == "_bmad-output/implementation-artifacts/2-1-voir-son-profil.md"
    with open(os.path.join(wt, rel), encoding="utf-8") as f:
        content = f.read()
    mt = STORY_MD_STATUS_RE.search(content)  # bmad-ui doit y lire le statut
    assert mt and mt.group(1) == "review", content


def test_rollup_epics_etats():
    """epic-N : done si toutes ses stories done, backlog si toutes backlog, sinon in-progress."""
    wt = _seed_worktree()  # 2 epics, stories toutes backlog
    # état initial : tout backlog -> epics backlog
    assert m._rollup_epics(wt) == {"1": "backlog", "2": "backlog"}
    # une story de l'epic 1 en review -> epic 1 in-progress, epic 2 inchangé
    m._set_story_status(wt, "1-1-crer-un-compte", "review")
    assert m._rollup_epics(wt) == {"1": "in-progress", "2": "backlog"}
    # toutes les stories de l'epic 1 done -> epic 1 done
    m._set_story_status(wt, "1-1-crer-un-compte", "done")
    m._set_story_status(wt, "1-2-se-connecter", "done")
    assert m._rollup_epics(wt)["1"] == "done"
    # in-progress compte comme démarré
    m._set_story_status(wt, "2-1-voir-son-profil", "in-progress")
    assert m._rollup_epics(wt)["2"] == "in-progress"


def test_rollup_epics_conforme_regex_bmad_ui():
    """Après rollup, les lignes epic restent conformes au parser bmad-ui."""
    wt = _seed_worktree()
    m._set_story_status(wt, "1-1-crer-un-compte", "done")
    m._set_story_status(wt, "1-2-se-connecter", "done")
    m._rollup_epics(wt)
    with open(os.path.join(wt, m.SPRINT_REL), encoding="utf-8") as f:
        lines = f.read().splitlines()
    epic_lines = [ln for ln in lines if ln.strip().startswith("epic-")]
    assert epic_lines and all(EPIC_STATUS_RE.match(ln) for ln in epic_lines)
    assert "  epic-1: done" in lines  # rollup appliqué
    assert "  epic-2: backlog" in lines  # epic 2 intact


def test_resolve_pipeline_for_target():
    """Corrélation canal↔pipeline : le pipeline 'awaiting' le plus récent du return_target."""
    saved = dict(m.PIPELINES)
    try:
        m.PIPELINES.clear()
        m.PIPELINES["p1"] = {"return_target": "123", "status": "done"}
        m.PIPELINES["p2"] = {"return_target": "123", "status": "awaiting_approval"}
        m.PIPELINES["p3"] = {"return_target": "999", "status": "awaiting_approval"}
        assert m._resolve_pipeline_for_target("123") == "p2"  # awaiting du bon canal
        assert m._resolve_pipeline_for_target("000") is None  # canal sans pipeline
        assert m._resolve_pipeline_for_target(None) is None
        m.PIPELINES["p4"] = {"return_target": "123", "status": "awaiting_approval"}
        assert m._resolve_pipeline_for_target("123") == "p4"  # le plus récent gagne
        assert m._resolve_pipeline_for_target(123) == "p4"  # tolérance int/str
    finally:
        m.PIPELINES.clear()
        m.PIPELINES.update(saved)


def test_resume_by_target_sans_pipeline():
    saved = dict(m.PIPELINES)
    try:
        m.PIPELINES.clear()
        res = m.resume_pipeline_by_target("approve", "nobody")
        assert res.get("error"), res
    finally:
        m.PIPELINES.clear()
        m.PIPELINES.update(saved)


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
