import json
from pathlib import Path

import pytest
from datalad.api import Dataset, clone

from conftest import make_env, reference_doc, write_doc
from faire import lifecycle as L
from faire import tasks as T
from faire.indexing import Indexer
from faire.plan import Plan
from faire.platform.fake import FakePlatform
from faire.project import Project
from test_tasks import received


@pytest.fixture(scope="module")
def project(tmp_path_factory, reference, templates_root):
    env = make_env(tmp_path_factory.mktemp("life"), templates_root)
    doc = reference_doc(env, reference)
    proj = Project(Plan.from_document(doc), write_doc(env.root / "dmp.json", doc), env.root / "w")
    proj.init()
    return proj


@pytest.fixture
def platform(tmp_path):
    p = FakePlatform(tmp_path / "platform")
    return p, p.ensure_repository("lab/study/rawdata")


def mri(project, tmp, subject, pilot=False):
    name = f"sub-{subject}_ses-a" + ("_pilot" if pilot else "")
    Indexer(project, "dicoms").index(received(tmp / f"mri{subject}", name, "PrismaFit16001",
                                              {"scan.dat": b"mri"}))


def physio(project, tmp, subject):
    Indexer(project, "physio").index(received(tmp / f"phys{subject}", f"sub-{subject}_ses-a",
                                              "Biopac01", {"rec.log": b"physio"}))


def bids(project, tmp, name="bids"):
    return clone(source=str(project.path("rawdata")), path=str(tmp / name),
                 result_renderer="disabled")


def on(ds, branch):
    ds.repo.call_git(["fetch", "-q", "origin"])
    ds.repo.call_git(["checkout", "-q", "-B", branch, f"refs/remotes/origin/{branch}"])
    return ds


def files_vs_dev(ds, branch):
    ds.repo.call_git(["fetch", "-q", "origin"])
    out = ds.repo.call_git(["diff", "--name-only", "refs/remotes/origin/dev...refs/remotes/"
                            f"origin/{branch}"])
    return out.split()


def test_new_session_opens_branch_and_draft(project, tmp_path, platform):
    fake, repo = platform
    mri(project, tmp_path, "01")
    ds = bids(project, tmp_path)
    lines = L.update(ds, fake, repo)
    assert "updated sourcedata/dicoms/a_PrismaFit16001 on base" in lines
    assert "merged base into dev" in lines and "merged base into pilot" in lines
    assert "opened convert/subject-01_session-a" in lines
    [pr] = fake.open_pull_requests(repo)
    assert (pr.source, pr.target, pr.draft) == ("convert/subject-01_session-a", "dev", True)
    origin = Dataset(project.path("rawdata"))
    assert origin.repo.get_hexsha("convert/subject-01_session-a") == origin.repo.get_hexsha("base")
    assert not any("opened" in line for line in L.update(ds, fake, repo))


def test_status_pending_completeness_and_late_streams(project, tmp_path):
    for subject in ("02", "03"):
        mri(project, tmp_path, subject)
    ds = bids(project, tmp_path)
    L.update(ds)
    on(ds, "convert/subject-02_session-a")
    T.run_all(ds)
    assert L.record_status(ds)
    assert L.current(ds, "subject-02_session-a") == {"dicoms": "present", "physio": "pending"}
    table = Path(ds.path) / "sub-02" / "sub-02_sessions.tsv"
    assert table.read_text() == "session_id\tdicoms\tphysio\nses-a\tpresent\tpending\n"
    sidecar = json.loads((Path(ds.path) / "sessions.json").read_text())
    assert sidecar["physio"]["Levels"]["pending"] == "expected, not yet converted"
    message = ds.repo.call_git(["log", "-1", "--format=%B"])
    assert "faire-status: subject-02_session-a" in message and "faire status --write" in message
    ok, text = L.completeness(ds, "subject-02_session-a")
    assert not ok and "pending: physio" in text
    # physio arrives: base moves and is merged into both waiting branches
    for subject in ("02", "03"):
        physio(project, tmp_path, subject)
    other = bids(project, tmp_path, "other")
    lines = L.update(other)
    assert "updated sourcedata/physio/a_Biopac01 on base" in lines
    assert "merged base into convert/subject-02_session-a" in lines
    assert "merged base into convert/subject-03_session-a" in lines
    on(ds, "convert/subject-02_session-a")
    assert [t.id for t in T.plan(ds)] == ["merge-physio:subject-02_session-a"]
    T.run_all(ds)
    L.record_status(ds)
    assert L.current(ds, "subject-02_session-a")["physio"] == "present"
    assert L.completeness(ds, "subject-02_session-a")[0]
    # the pull request shows only this sample's changes
    changed = files_vs_dev(ds, "convert/subject-02_session-a")
    assert changed and all(f.startswith("sub-02/") or f == "sessions.json" for f in changed)


def test_mark_partial_and_missing(project, tmp_path):
    mri(project, tmp_path, "04")
    physio(project, tmp_path, "04")
    mri(project, tmp_path, "05")
    ds = bids(project, tmp_path)
    L.update(ds)
    on(ds, "convert/subject-04_session-a")
    T.run_all(ds)
    assert L.mark(ds, "physio", "reviewer") == "partial"
    assert L.current(ds, "subject-04_session-a")["physio"] == "partial"
    assert "faire-marked-by: reviewer" in ds.repo.call_git(["log", "-1", "--format=%B"])
    ok, text = L.completeness(ds, "subject-04_session-a")
    assert ok and "physio (partial)" in text
    assert L.waived_patterns(ds, "subject-04_session-a") == ("sub-04/ses-a/func",)
    L.record_status(ds)  # the waiver survives recomputation
    assert L.current(ds, "subject-04_session-a")["physio"] == "partial"
    on(ds, "convert/subject-05_session-a")
    T.run_all(ds)
    assert L.mark(ds, "physio", "reviewer") == "missing"


def test_rule_fixed_and_merged_session(project, tmp_path):
    mri(project, tmp_path, "06")
    ds = bids(project, tmp_path)
    L.update(ds)
    on(ds, "convert/subject-06_session-a")
    T.run_all(ds)
    # a configuration change on base reaches the open session
    on(ds, "base")
    (Path(ds.path) / "CHANGES").write_text("rule fixed\n")
    ds.save(path="CHANGES", to_git=True, message="fix a rule", result_renderer="disabled")
    ds.repo.call_git(["push", "-q", "--no-verify", "origin", "base"])
    assert "merged base into convert/subject-06_session-a" in L.update(ds)
    on(ds, "convert/subject-06_session-a")
    assert (Path(ds.path) / "CHANGES").exists()
    # once merged into dev, the session is not opened again
    on(ds, "dev")
    ds.repo.call_git(["merge", "-q", "--no-edit",
                      "refs/remotes/origin/convert/subject-06_session-a"])
    ds.repo.call_git(["push", "-q", "--no-verify", "origin", "dev",
                      ":convert/subject-06_session-a"])
    assert not any("subject-06" in line for line in L.update(ds) if line.startswith("opened"))


def test_pilot_isolation(project, tmp_path, platform):
    fake, repo = platform
    origin = Dataset(project.path("rawdata"))
    mri(project, tmp_path, "09", pilot=True)
    ds = bids(project, tmp_path)
    lines = L.update(ds, fake, repo)
    assert "opened convert-pilot/subject-09_session-a" in lines
    pr = next(p for p in fake.open_pull_requests(repo) if "subject-09" in p.source)
    assert pr.target == "pilot"
    dev_before = origin.repo.get_hexsha("dev")
    on(ds, "convert-pilot/subject-09_session-a")
    assert ds.repo.get_hexsha() == origin.repo.get_hexsha("base")
    T.run_all(ds)
    assert origin.repo.get_hexsha("dev") == dev_before
