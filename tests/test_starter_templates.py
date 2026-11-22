"""The starting-point templates: `base` (no rules), `standard` and `derivative` (placeholders)."""

import pytest
from datalad.api import create

from conftest import REFERENCE, by_id, git_template_dir, make_env, write_doc
from faire import project as P
from faire import templates
from faire.plan import Plan, Template
from faire.rules import load
from faire.tasks import plan


@pytest.fixture(scope="module")
def starters(tmp_path_factory):
    root = tmp_path_factory.mktemp("starters")
    return {name: git_template_dir(REFERENCE / name, root / name)
            for name in ("base", "standard", "derivative")}


def rendered(tmp_path, repository, data=None):
    ds = create(path=str(tmp_path / "ds"), result_renderer="disabled")
    out = tmp_path / "rendered"
    templates.render(Template(repository, "v0.1.0", data or {}), out, {"title": "T"})
    templates.merge(ds, out)
    ds.save(message="template", result_renderer="disabled")
    return ds


def test_base_plans_nothing(tmp_path, starters):
    ds = rendered(tmp_path, starters["base"])
    assert not (tmp_path / "ds" / "TEMPLATE.md").exists()
    assert load(ds) == ({}, {})
    ds.repo.call_git(["checkout", "-q", "-b", "convert/subject-01_session-a"])
    assert plan(ds) == []


def test_derivative_rule_is_primary(tmp_path, starters):
    ds = rendered(tmp_path, starters["derivative"],
                  {"collection_url": "https://example.org/c.git", "collection_revision": "v1"})
    rules, checks = load(ds)
    assert list(rules) == ["process"] and rules["process"].primary
    assert rules["process"].sources == ("bids",)
    assert {n: c.blocking for n, c in checks.items()} == {"report": False, "validate": True}


def test_standard_unedited_fails_init(tmp_path, templates_root, starters):
    env = make_env(tmp_path, templates_root)
    doc = env.doc()
    bids = by_id(doc, "bids")
    bids["faire"]["template"] = {"repository": starters["standard"], "version": "v0.1.0",
                                 "data": {"collection_url": env.collection,
                                          "collection_revision": "v1"}}
    dmp = write_doc(env.root / "dmp.json", doc)
    proj = P.Project(Plan.from_document(doc), dmp, env.root / "work")
    with pytest.raises(P.InitError, match=r"convert \(code/containers/images/TODO in "
                                          r"collection tools\)"):
        proj.init()
    assert not (env.root / "work" / "rawdata").exists()
