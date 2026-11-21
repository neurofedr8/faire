import os
from pathlib import Path

import pytest
from datalad.api import Dataset

from conftest import reference_doc, write_doc
from faire.containers import entries
from faire.plan import Plan
from faire.project import Project


@pytest.fixture(scope="module")
def project(tmp_path_factory, reference, templates_root):
    from conftest import make_env

    env = make_env(tmp_path_factory.mktemp("ref"), templates_root)
    doc = reference_doc(env, reference)
    dmp = write_doc(env.root / "dmp.json", doc)
    proj = Project(Plan.from_document(doc), dmp, env.root / "work")
    report = proj.init()
    assert report.differences == []
    return proj


def test_stream_template(project):
    root = project.path("sourcedata/dicoms/a_PrismaFit16001")
    assert (root / ".faire" / "heuristic.py").is_file()
    assert "instrument `PrismaFit16001` at site `a`" in (root / "README.md").read_text()
    # the heuristic is tracked in git, not annexed, so it can be imported from a clone
    assert not (root / ".faire" / "heuristic.py").is_symlink()


def test_superdataset_template(project):
    root = project.path("superdataset")
    assert (root / "README.md").read_text().startswith("# Study superdataset")
    assert not (root / "dmp.json").is_symlink()


def test_standard_template_rules_and_checks(project):
    ds = Dataset(project.path("rawdata"))
    listed = {r["name"] for r in ds.containers_list(result_renderer="disabled")}
    assert listed == {"convert", "merge-physio", "deface", "validate", "summary"}
    found = entries(ds)
    assert found["merge-physio"]["faire-sourcedata"] == (".", "physio")
    assert found["validate"]["faire-check"] == "blocking"
    assert found["validate"]["faire-stage"] == ("collection", "release")
    assert os.path.lexists(Path(ds.path, "code/containers/images/toy-1.0.sh"))  # annexed


def test_fixed_ci_configuration(project):
    for logical in ("sourcedata/dicoms/a_PrismaFit16001", "rawdata", "superdataset"):
        path = project.path(logical) / ".gitlab-ci.yml"
        assert not path.is_symlink()  # in git
        assert "faire plan --ci-render gitlab" in path.read_text()


def test_tracked_dmp(project):
    for logical in ("sourcedata/dicoms/a_PrismaFit16001", "rawdata"):
        path = project.path(logical) / ".faire" / "dmp.json"
        assert not path.is_symlink() and path.read_bytes() == project.dmp_file.read_bytes()


def test_ci_configuration_matches_rendered_jobs():
    import yaml

    from conftest import REFERENCE
    from faire.tasks import BEFORE_SCRIPT

    for name in ("standard", "stream", "superdataset"):
        config = yaml.safe_load((REFERENCE / name / ".gitlab-ci.yml").read_text())
        assert config["faire-plan"]["before_script"] == BEFORE_SCRIPT, name
