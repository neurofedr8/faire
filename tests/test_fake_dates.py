"""Datasets whose template enables DataLad fake dates carry no real date in their history."""

import pytest
from datalad.support.repodates import check_dates

from conftest import DERIVED_TEMPLATE, by_id, git_template, write_doc
from faire.plan import Plan
from faire.project import Project

REFERENCE = 1514764800  # 2018-01-01, the default reference of `datalad check-dates`


# The git-annex branch also gets the real date of `git annex init` in siblings made by
# `datalad create-sibling`, which ignores fake dates (reported upstream); strict, so that the
# mark is removed once DataLad is fixed.
UPSTREAM_SIBLING_DATES = pytest.mark.xfail(
    strict=True, reason="datalad create-sibling inits the sibling's annex with real dates")


def real_dates(path, annex=True) -> dict:
    """Real dates in commits and tags, and with ``annex`` in the git-annex branch too."""
    revs = ["--all"] if annex else ["--exclude=git-annex", "--branches", "--tags"]
    return check_dates(str(path), REFERENCE, revs=revs, annex=annex)["objects"]


@pytest.fixture(scope="module")
def fake_template(tmp_path_factory):
    files = dict(DERIVED_TEMPLATE)
    files[".datalad/config.jinja"] = "[datalad]\n\tfake-dates = true\n" + files[
        ".datalad/config.jinja"]
    return git_template(tmp_path_factory.mktemp("fake") / "derived-fake", files)


@pytest.fixture
def project(env, fake_template):
    doc = env.doc()
    by_id(doc, "bids")["faire"]["template"]["repository"] = fake_template
    proj = Project(Plan.from_document(doc), write_doc(env.root / "dmp.json", doc),
                   env.root / "work")
    proj.init()
    return proj


def test_fake_dates_from_creation(project):
    path = project.path("rawdata")
    assert real_dates(path, annex=False) == {}  # commits and tags
    config = (path / ".datalad" / "config").read_text()
    assert config.count("fake-dates") == 1
    # a dataset whose template does not enable them keeps real dates
    assert real_dates(project.path("derivatives/fmriprep"))


@UPSTREAM_SIBLING_DATES
def test_no_real_date_in_annex_branch(project):
    assert real_dates(project.path("rawdata")) == {}


def test_merge_commit_is_fake_dated(project, tmp_path):
    from datalad.api import Dataset, clone

    from faire import lifecycle as L
    from faire.platform import Repository
    from faire.platform.fake import FakePlatform, FakeRepo

    origin = project.path("rawdata")
    fake = FakePlatform(tmp_path / "platform")
    repo = Repository("lab/study/rawdata", str(origin))
    fake.repos[repo.path] = FakeRepo(repo)
    branch = "convert/subject-01_session-a"
    ds = clone(source=str(origin), path=str(tmp_path / "c"), result_renderer="disabled")
    ds.repo.call_git(["checkout", "-q", "-b", branch, "refs/remotes/origin/base"])
    (tmp_path / "c" / "out.txt").write_text("converted\n")
    ds.save(message="convert", result_renderer="disabled")
    ds.repo.call_git(["push", "-q", "--no-verify", "origin", branch])
    pr = fake.ensure_pull_request(repo, branch, "dev", "Session", "")
    fake.approve(repo, pr.number, "reviewer")
    L.merge_session(ds, fake, repo, ds.repo.get_hexsha())
    assert fake.open_pull_requests(repo) == []
    assert real_dates(origin, annex=False) == {}
    assert Dataset(origin).repo.call_git(["log", "-1", "--format=%cd", "--date=format:%Y",
                                          "dev"]).strip() == "2005"
