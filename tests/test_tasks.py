import json
from pathlib import Path

import pytest
from click.testing import CliRunner
from datalad.api import Dataset, clone

from conftest import make_env, reference_doc, write_doc
from faire import tasks as T
from faire.branches import bump_source, start_session
from faire.cli import main
from faire.indexing import Indexer
from faire.plan import Plan
from faire.platform.fake import FakePlatform
from faire.project import Project
from faire.rules import Check, load

GOLDEN = Path(__file__).parent / "golden"


def received(root: Path, name: str, instrument: str, files: dict[str, bytes]) -> Path:
    (root / name).mkdir(parents=True)
    (root / name / "instrument.txt").write_text(instrument)
    for fname, data in files.items():
        (root / name / fname).write_bytes(data)
    return root


@pytest.fixture(scope="module")
def project(tmp_path_factory, reference, templates_root):
    env = make_env(tmp_path_factory.mktemp("tasks"), templates_root)
    doc = reference_doc(env, reference)
    proj = Project(Plan.from_document(doc), write_doc(env.root / "dmp.json", doc), env.root / "w")
    proj.init()
    return proj


def index(project, tmp, subject, physio=b"physio"):
    Indexer(project, "dicoms").index(received(tmp / "mri", f"sub-{subject}_ses-a",
                                              "PrismaFit16001", {"scan.dat": b"mri " + physio}))
    Indexer(project, "physio").index(received(tmp / "phys", f"sub-{subject}_ses-a", "Biopac01",
                                              {"rec.log": physio}))


def session(project, tmp: Path, subject: str, name="clone") -> Dataset:
    """A clone of the standard dataset on the session branch, sources bumped."""
    index(project, tmp, subject)
    return checkout(project, tmp, subject, name, new=True)


def checkout(project, tmp, subject, name, new=False) -> Dataset:
    ds = clone(source=str(project.path("rawdata")), path=str(tmp / name),
               result_renderer="disabled")
    label = f"subject-{subject}_session-a"
    if new:
        start_session(ds, label)
        for sub in ("sourcedata/dicoms/a_PrismaFit16001", "sourcedata/physio/a_Biopac01"):
            bump_source(ds, sub)
    else:
        ds.repo.call_git(["checkout", "-q", "-b", f"convert/{label}",
                          f"refs/remotes/origin/convert/{label}"])
    return ds


def ids(tasks):
    return [t.id for t in tasks]


def test_rules_classified(project, tmp_path):
    ds = clone(source=str(project.path("rawdata")), path=str(tmp_path / "c"),
               result_renderer="disabled")
    rules, checks = load(ds)
    assert {n for n, r in rules.items() if r.primary} == {"convert"}
    assert {n for n, r in rules.items() if not r.primary} == {"merge-physio", "deface"}
    assert checks["validate"].blocking and not checks["summary"].blocking


def test_waves_in_place_and_rerun(project, tmp_path):
    ds = session(project, tmp_path, "01")
    assert ids(T.plan(ds)) == ["convert:subject-01_session-a"]
    assert T.run_task(ds, "convert:subject-01_session-a") == "ran"
    assert ids(T.plan(ds)) == ["deface:subject-01_session-a", "merge-physio:subject-01_session-a"]
    assert T.run_task(ds, "deface:subject-01_session-a") == "ran"
    anat = Path(ds.path) / "sub-01" / "ses-a" / "anat" / "scan.dat"
    assert anat.read_text().endswith("marked\n")
    # in-place: deface rewrote its own input and is not due again
    assert ids(T.plan(ds)) == ["merge-physio:subject-01_session-a"]
    assert T.run_task(ds, "merge-physio:subject-01_session-a") == "ran"
    assert T.plan(ds) == []
    assert (Path(ds.path) / "sub-01/ses-a/func/rec.log").read_bytes() == b"physio"
    message = ds.repo.call_git(["log", "-1", "--format=%B"])
    assert "faire-rule: merge-physio" in message and "faire-sample: subject-01_session-a" in message
    # results re-execute from their record in a fresh clone
    fresh = clone(source=str(project.path("rawdata")), path=str(tmp_path / "fresh"),
                  result_renderer="disabled")
    fresh.repo.call_git(["checkout", "-q", "-b", "x", "refs/remotes/origin/convert/"
                         "subject-01_session-a"])
    fresh.rerun(revision="HEAD", result_renderer="disabled")
    assert fresh.repo.call_git(["status", "--porcelain"]).strip() == ""


def test_source_moved(project, tmp_path):
    ds = session(project, tmp_path, "02")
    T.run_all(ds)
    assert T.plan(ds) == []
    Indexer(project, "physio").index(received(tmp_path / "late", "sub-02_ses-a", "Biopac01",
                                              {"rec2.log": b"more"}))
    assert bump_source(ds, "sourcedata/physio/a_Biopac01")
    assert ids(T.plan(ds)) == ["merge-physio:subject-02_session-a"]


def test_concurrent_pushes_and_no_longer_due(project, tmp_path):
    ds = session(project, tmp_path, "03")
    T.run_task(ds, "convert:subject-03_session-a")
    a = checkout(project, tmp_path, "03", "a")
    b = checkout(project, tmp_path, "03", "b")
    assert T.run_task(a, "deface:subject-03_session-a") == "ran"
    assert T.run_task(b, "merge-physio:subject-03_session-a") == "ran"  # merges a's commit
    origin = Dataset(project.path("rawdata"))
    log = origin.repo.call_git(["log", "--format=%B", "convert/subject-03_session-a"])
    assert "faire-rule: deface" in log and "faire-rule: merge-physio" in log
    before = a.repo.get_hexsha()
    assert T.run_task(a, "deface:subject-03_session-a") == "up-to-date"
    assert a.repo.get_hexsha() == before


def test_checks(project, tmp_path):
    ds = session(project, tmp_path, "04")
    results = {r.name: r for r in T.run_checks(ds, "collection", "subject-04_session-a")}
    assert results["validate"].passed and results["validate"].blocking
    assert results["summary"].passed and not results["summary"].blocking
    image = ds.config.get("datalad.containers.validate.image")
    for key, value in [("image", image), ("cmdexec", "sh {img} {cmd}"),
                       ("faire-check", "blocking"), ("faire-stage", "collection"),
                       ("faire-cmd", "copy newdir README.md")]:
        ds.config.set(f"datalad.containers.toucher.{key}", value, scope="local")
    [r] = T.run_checks(ds, "collection", only="toucher")
    assert not r.passed and r.modified == ["?? newdir/README.md"]


def test_render_golden():
    tasks = [T.Task("unwarp:s", "unwarp", "s"), T.Task("physio:s", "physio", "s"),
             T.Task("deface:s", "deface", "s", ("unwarp:s",), "gpu")]
    checks = [Check("validate", True, ("collection",), "check ."),
              Check("summary", False, ("collection",), "summary .")]
    assert T.render_gitlab(tasks, checks, "collection") == (GOLDEN / "gitlab.yml").read_text()
    assert T.render_github(tasks, checks) + "\n" == (GOLDEN / "github.json").read_text()


def test_replan_and_loop_guard(project, tmp_path):
    ds = session(project, tmp_path, "05")
    platform = FakePlatform(tmp_path / "platform")
    repo = platform.ensure_repository("lab/study/rawdata")
    T.publish(ds, "convert/subject-05_session-a")
    since = ds.repo.get_hexsha()
    assert T.replan(ds, since, platform, repo) == "nothing new"
    T.run_task(ds, "convert:subject-05_session-a")
    assert T.replan(ds, since, platform, repo) == "started pipeline 1"
    assert platform.pipelines == [("lab/study/rawdata", "convert/subject-05_session-a", {})]
    for _ in range(2):
        ds.repo.call_git(["commit", "-q", "--allow-empty", "-m",
                          "faire: deface x\n\nfaire-rule: deface\n"
                          "faire-sample: subject-05_session-a"])
    with pytest.raises(T.TaskError, match="deface ran twice"):
        T.replan(ds, since, platform, repo)


def test_cli_plan(project, tmp_path):
    ds = session(project, tmp_path, "06")
    result = CliRunner().invoke(main, ["plan", "--dataset", ds.path])
    assert result.exit_code == 0, result.output
    assert [t["id"] for t in json.loads(result.output)] == ["convert:subject-06_session-a"]
