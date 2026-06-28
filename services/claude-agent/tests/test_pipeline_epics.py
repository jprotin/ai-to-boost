#!/usr/bin/env python3
"""Tests autonomes (sans pytest) des fonctions pures du pipeline BMAD B2.

Verrouille le contrat de format avec bmad-ui : parsing epics.md, slug identique à
slugifyStoryLabel (parser.ts) et génération sprint-status.yaml conforme aux regex du
parser bmad-ui. Lancer : python3 services/claude-agent/tests/test_pipeline_epics.py
"""

import importlib.util
import json
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


def test_list_projects():
    """Liste des projets : actif, existence, statut du dernier pipeline enrichi."""
    saved = os.environ.get("XDG_CONFIG_HOME")
    d = tempfile.mkdtemp(prefix="reg-")
    try:
        os.environ["XDG_CONFIG_HOME"] = d
        os.makedirs(os.path.join(d, "ai-to-boost"))
        proj = os.path.join(d, "proj")
        os.makedirs(os.path.join(proj, ".ai-to-boost"))
        with open(os.path.join(proj, ".ai-to-boost", "pipeline.json"), "w") as f:
            json.dump({"status": "done", "phase": "implementation"}, f)
        with open(os.path.join(d, "ai-to-boost", "projects.json"), "w") as f:
            json.dump(
                {
                    "active": "p1",
                    "projects": {
                        "p1": {
                            "path": proj,
                            "base_branch": "develop",
                            "last_pipeline": "x",
                        },
                        "p2": {"path": "/nope", "base_branch": "main"},
                    },
                },
                f,
            )
        by = {r["name"]: r for r in m._list_projects()}
        assert by["p1"]["active"] is True, by["p1"]
        assert by["p1"]["exists"] is True
        assert by["p1"]["pipeline_status"] == "done"
        assert by["p2"]["active"] is False
        assert by["p2"]["exists"] is False
        assert "pipeline_status" not in by["p2"]  # pas de pipeline.json
    finally:
        if saved is None:
            os.environ.pop("XDG_CONFIG_HOME", None)
        else:
            os.environ["XDG_CONFIG_HOME"] = saved


def test_project_board():
    """Board projet : epics+stories depuis le worktree, statuts, détail story, pipeline."""
    saved = os.environ.get("XDG_CONFIG_HOME")
    d = tempfile.mkdtemp(prefix="board-")
    try:
        os.environ["XDG_CONFIG_HOME"] = d
        proj = os.path.join(d, "proj")
        os.makedirs(os.path.join(proj, ".ai-to-boost"))
        wt = os.path.join(d, "wt")
        os.makedirs(os.path.join(wt, "_bmad-output/planning-artifacts"))
        epics_md = "## Epic 1: Auth\n### Story 1.1: Créer un compte\n### Story 1.2: Se connecter\n"
        with open(
            os.path.join(wt, "_bmad-output/planning-artifacts/epics.md"), "w"
        ) as f:
            f.write(epics_md)
        dest = os.path.join(wt, m.SPRINT_REL)
        os.makedirs(os.path.dirname(dest))
        with open(dest, "w") as f:
            f.write(m._gen_sprint_status(m._parse_epics(epics_md), "P"))
        m._set_story_status(wt, "1-1-crer-un-compte", "done")
        m._rollup_epics(wt)
        m._write_story_md(wt, "1-1-crer-un-compte", "done", "résumé dev")
        with open(os.path.join(proj, ".ai-to-boost", "pipeline.json"), "w") as f:
            json.dump(
                {
                    "pipeline_id": "x",
                    "status": "awaiting_approval",
                    "phase": "epics",
                    "branch": "pipeline/x",
                    "worktree": wt,
                },
                f,
            )
        os.makedirs(os.path.join(d, "ai-to-boost"))
        with open(os.path.join(d, "ai-to-boost", "projects.json"), "w") as f:
            json.dump({"active": "proj", "projects": {"proj": {"path": proj}}}, f)

        b = m._project_board("proj")
        assert b["pipeline"]["status"] == "awaiting_approval"
        assert len(b["epics"]) == 1
        e = b["epics"][0]
        assert e["title"] == "Auth"
        assert e["status"] == "in-progress"  # 1 done + 1 backlog
        st = {s["id"]: s["status"] for s in e["stories"]}
        assert st["1-1-crer-un-compte"] == "done"
        assert st["1-2-se-connecter"] == "backlog"
        s11 = next(s for s in e["stories"] if s["id"] == "1-1-crer-un-compte")
        assert "résumé dev" in s11["detail"]
        assert m._project_board("nope") is None  # projet inconnu
    finally:
        if saved is None:
            os.environ.pop("XDG_CONFIG_HOME", None)
        else:
            os.environ["XDG_CONFIG_HOME"] = saved


def _git_repo(path):
    """Init un dépôt git jetable sur 'develop' avec un commit initial."""
    import subprocess

    os.makedirs(path, exist_ok=True)
    env = {
        **os.environ,
        "GIT_AUTHOR_NAME": "t",
        "GIT_AUTHOR_EMAIL": "t@t",
        "GIT_COMMITTER_NAME": "t",
        "GIT_COMMITTER_EMAIL": "t@t",
    }

    def g(*args):
        subprocess.run(
            ["git", "-C", path, *args],
            check=True,
            env=env,
            capture_output=True,
            text=True,
        )

    subprocess.run(
        ["git", "init", "-b", "develop", path],
        check=True,
        capture_output=True,
        text=True,
    )
    os.makedirs(os.path.join(path, ".ai-to-boost"), exist_ok=True)
    with open(os.path.join(path, ".ai-to-boost", "config.json"), "w") as f:
        json.dump({"base_branch": "develop"}, f)
    with open(os.path.join(path, "README.md"), "w") as f:
        f.write("seed\n")
    g("add", "README.md")
    g("commit", "-m", "init")
    return g


def test_board_fallback_sans_pipeline_json():
    """Board robuste : sans pipeline.json, retrouve la dernière branche pipeline/* et
    lit le board depuis elle (au lieu d'un working tree develop vide)."""
    saved = os.environ.get("XDG_CONFIG_HOME")
    d = tempfile.mkdtemp(prefix="board-fb-")
    try:
        os.environ["XDG_CONFIG_HOME"] = d
        proj = os.path.join(d, "proj")
        g = _git_repo(proj)
        # branche pipeline avec board committé
        g("checkout", "-b", "pipeline/abc123")
        epics_md = "## Epic 1: Auth\n### Story 1.1: Créer un compte\n"
        os.makedirs(os.path.join(proj, "_bmad-output/planning-artifacts"))
        with open(
            os.path.join(proj, "_bmad-output/planning-artifacts/epics.md"), "w"
        ) as f:
            f.write(epics_md)
        dest = os.path.join(proj, m.SPRINT_REL)
        os.makedirs(os.path.dirname(dest))
        with open(dest, "w") as f:
            f.write(m._gen_sprint_status(m._parse_epics(epics_md), "P"))
        g("add", "-A")
        g("commit", "-m", "board")
        g("checkout", "develop")  # working tree develop = pas de board
        os.makedirs(os.path.join(d, "ai-to-boost"))
        with open(os.path.join(d, "ai-to-boost", "projects.json"), "w") as f:
            json.dump({"active": "proj", "projects": {"proj": {"path": proj}}}, f)

        b = m._project_board("proj")
        assert b is not None
        assert len(b["epics"]) == 1, f"board vide malgré la branche pipeline/* : {b}"
        assert b["epics"][0]["title"] == "Auth"
        assert b["pipeline"]["branch"] == "pipeline/abc123"
    finally:
        if saved is None:
            os.environ.pop("XDG_CONFIG_HOME", None)
        else:
            os.environ["XDG_CONFIG_HOME"] = saved


def test_collect_pipeline_merge():
    """collect_pipeline fusionne pipeline/<id> → base et le code arrive sur develop."""
    saved = os.environ.get("XDG_CONFIG_HOME")
    d = tempfile.mkdtemp(prefix="collect-")
    try:
        os.environ["XDG_CONFIG_HOME"] = d
        proj = os.path.join(d, "proj")
        g = _git_repo(proj)
        g("checkout", "-b", "pipeline/zzz")
        with open(os.path.join(proj, "feature.txt"), "w") as f:
            f.write("livrable\n")
        g("add", "feature.txt")
        g("commit", "-m", "feature")
        with open(os.path.join(proj, ".ai-to-boost", "pipeline.json"), "w") as f:
            json.dump(
                {"pipeline_id": "zzz", "branch": "pipeline/zzz", "base": "develop"}, f
            )
        g("checkout", "develop")
        os.makedirs(os.path.join(d, "ai-to-boost"))
        with open(os.path.join(d, "ai-to-boost", "projects.json"), "w") as f:
            json.dump({"active": "proj", "projects": {"proj": {"path": proj}}}, f)

        res = m.collect_pipeline("proj")
        assert res.get("merged") is True, f"collect échoué : {res}"
        assert res["base"] == "develop" and res["branch"] == "pipeline/zzz"
        assert os.path.isfile(
            os.path.join(proj, "feature.txt")
        ), "le livrable n'est pas arrivé sur develop après collect"
    finally:
        if saved is None:
            os.environ.pop("XDG_CONFIG_HOME", None)
        else:
            os.environ["XDG_CONFIG_HOME"] = saved


def test_valid_project_name():
    for ok in ("demo", "mon-projet_2", "avec espace", "A1"):
        assert m._valid_project_name(ok), ok
    for ko in ("", "../x", "a/b", ".hidden", "-lead", "x" * 65):
        assert not m._valid_project_name(ko), ko


def test_create_and_delete_project():
    """create_project (git+develop+marqueur+registre) ; delete_project désinscrit
    SANS supprimer le répertoire."""
    saved_x = os.environ.get("XDG_CONFIG_HOME")
    saved_pd = m.PROJECTS_DIR
    d = tempfile.mkdtemp(prefix="crud-")
    try:
        os.environ["XDG_CONFIG_HOME"] = d
        m.PROJECTS_DIR = os.path.join(d, "projs")

        res = m.create_project("demo crud")
        assert res.get("created") is True, res
        path = res["path"]
        assert os.path.isdir(os.path.join(path, ".git"))
        assert os.path.isfile(os.path.join(path, ".ai-to-boost", "config.json"))
        assert m._git(path, "rev-parse", "--abbrev-ref", "HEAD") == "develop"
        projs = m._read_registry().get("projects") or {}
        assert "demo crud" in projs
        assert projs["demo crud"]["base_branch"] == "develop"

        assert "error" in m.create_project("demo crud")  # doublon
        assert "error" in m.create_project("../evil")  # nom invalide

        dres = m.delete_project("demo crud")
        assert dres.get("deleted") is True
        assert "demo crud" not in (m._read_registry().get("projects") or {})
        assert os.path.isdir(path), "le répertoire ne doit PAS être supprimé"
        assert "error" in m.delete_project("demo crud")  # déjà retiré
    finally:
        m.PROJECTS_DIR = saved_pd
        if saved_x is None:
            os.environ.pop("XDG_CONFIG_HOME", None)
        else:
            os.environ["XDG_CONFIG_HOME"] = saved_x


def test_project_artifacts():
    """Le board expose les artefacts (ordre des phases + titres + awaiting) et
    project_artifact renvoie le contenu, rejette une clé inconnue."""
    saved = os.environ.get("XDG_CONFIG_HOME")
    d = tempfile.mkdtemp(prefix="arts-")
    try:
        os.environ["XDG_CONFIG_HOME"] = d
        proj = os.path.join(d, "proj")
        os.makedirs(os.path.join(proj, ".ai-to-boost"))
        wt = os.path.join(d, "wt")
        os.makedirs(os.path.join(wt, "docs"))
        with open(os.path.join(wt, "docs", "prd.md"), "w") as f:
            f.write("# PRD — Démo\ncontenu prd")
        with open(os.path.join(proj, ".ai-to-boost", "pipeline.json"), "w") as f:
            json.dump(
                {
                    "pipeline_id": "x",
                    "status": "awaiting_approval",
                    "phase": "pm",
                    "awaiting": "pm",
                    "branch": "pipeline/x",
                    "worktree": wt,
                    "artifacts": {"analyst": "docs/brief.md", "pm": "docs/prd.md"},
                },
                f,
            )
        os.makedirs(os.path.join(d, "ai-to-boost"))
        with open(os.path.join(d, "ai-to-boost", "projects.json"), "w") as f:
            json.dump({"active": "proj", "projects": {"proj": {"path": proj}}}, f)

        b = m._project_board("proj")
        arts = b["pipeline"]["artifacts"]
        assert [a["key"] for a in arts] == ["analyst", "pm"], arts
        assert {a["key"]: a["title"] for a in arts}["pm"] == "PRD"
        assert b["pipeline"]["awaiting"] == "pm"

        art = m.project_artifact("proj", "pm")
        assert art["title"] == "PRD" and "contenu prd" in art["content"]
        assert "error" in m.project_artifact("proj", "bogus")  # clé inconnue
        assert m.project_artifact("nope", "pm").get("error") == "projet inconnu"
    finally:
        if saved is None:
            os.environ.pop("XDG_CONFIG_HOME", None)
        else:
            os.environ["XDG_CONFIG_HOME"] = saved


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
