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


def test_new_session_opens_branch_and_draft(project, tmp_path, platform):
    fake, repo = platform
    mri(project, tmp_path, "01")
    ds = bids(project, tmp_path)
    lines = L.sessions(ds, fake, repo)
    assert "opened convert/subject-01_session-a" in lines
    [pr] = fake.open_pull_requests(repo)
    assert (pr.source, pr.target, pr.draft) == ("convert/subject-01_session-a", "dev", True)
    origin = Dataset(project.path("rawdata"))
    assert "convert/subject-01_session-a" in origin.repo.get_branches()
    assert not any("opened" in line for line in L.sessions(ds, fake, repo))


def test_status_pending_completeness_and_late_streams(project, tmp_path):
    for subject in ("02", "03"):
        mri(project, tmp_path, subject)
    ds = bids(project, tmp_path)
    L.sessions(ds)
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
    # physio arrives: both waiting branches get it
    for subject in ("02", "03"):
        physio(project, tmp_path, subject)
    other = bids(project, tmp_path, "other")
    lines = L.sessions(other)
    assert "updated sourcedata/physio/a_Biopac01 on convert/subject-02_session-a" in lines
    assert "updated sourcedata/physio/a_Biopac01 on convert/subject-03_session-a" in lines
    on(ds, "convert/subject-02_session-a")
    T.run_all(ds)
    L.record_status(ds)
    assert L.current(ds, "subject-02_session-a")["physio"] == "present"
    assert L.completeness(ds, "subject-02_session-a")[0]


def test_mark_partial_and_missing(project, tmp_path):
    mri(project, tmp_path, "04")
    physio(project, tmp_path, "04")
    mri(project, tmp_path, "05")
    ds = bids(project, tmp_path)
    L.sessions(ds)
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


@pytest.mark.xfail(reason="pilot sessions move to base in task 8.3", strict=True)
def test_pilot_isolation(project, tmp_path, platform):
    fake, repo = platform
    origin = Dataset(project.path("rawdata"))
    dev_before = origin.repo.get_hexsha("dev")
    mri(project, tmp_path, "09", pilot=True)
    ds = bids(project, tmp_path)
    lines = L.sessions(ds, fake, repo)
    assert "opened convert-pilot/subject-09_session-a" in lines
    pr = next(p for p in fake.open_pull_requests(repo) if "subject-09" in p.source)
    assert pr.target == "pilot"
    on(ds, "convert-pilot/subject-09_session-a")
    assert ds.repo.call_git(["merge-base", "HEAD", "refs/remotes/origin/pilot"]).strip() == \
        origin.repo.get_hexsha("pilot")
    T.run_all(ds)
    assert origin.repo.get_hexsha("dev") == dev_before


def test_trigger(tmp_path):
    fake = FakePlatform(tmp_path / "p")
    fake.ensure_repository("lab/study/rawdata")
    fake.ensure_repository("lab/study/derivatives/x")
    lines = L.trigger("lab/study/rawdata, lab/study/derivatives/x", "dev", fake, "lab/study/up")
    assert len(lines) == 2
    assert fake.pipelines[0] == ("lab/study/rawdata", "dev", {
        "FAIRE_TRIGGERED_BY": "lab/study/up", "FAIRE_UPSTREAM_REF": "dev"})


def test_manual_mark_job():
    text = T.render_gitlab([], [], "collection", pending=("physio",))
    assert "mark-missing-physio:" in text and "when: manual" in text
    assert "faire mark 'physio=missing'" in text
