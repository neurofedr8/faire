import json
import os
import stat
from pathlib import Path

import pytest
from click.testing import CliRunner
from datalad.api import Dataset, clone

from conftest import make_env, reference_doc, write_doc
from faire.cli import main
from faire.indexing import Indexer, IndexingError
from faire.plan import Plan, load_document
from faire.project import Project

INSTANCE = "sourcedata/dicoms/a_PrismaFit16001"


def received(root: Path, *items: tuple[str, str]) -> Path:
    """A directory of received items: (folder name, instrument)."""
    root.mkdir(parents=True)
    for name, instrument in items:
        (root / name).mkdir()
        (root / name / "instrument.txt").write_text(instrument + "\n")
        (root / name / "scan.dat").write_bytes(b"data of " + name.encode())
    return root


@pytest.fixture(scope="module")
def project(tmp_path_factory, reference, templates_root):
    env = make_env(tmp_path_factory.mktemp("idx"), templates_root)
    doc = reference_doc(env, reference)
    dmp = write_doc(env.root / "dmp.json", doc)
    proj = Project(Plan.from_document(doc), dmp, env.root / "work")
    proj.init()
    return proj


def indexer(project) -> Indexer:
    return Indexer(Dataset(project.path(INSTANCE)))


def instance_clone(project, path: Path, doc=None, heuristic=None) -> Dataset:
    """A clone of the instance, with the ma-DMP copy or heuristic changed by a local commit."""
    ds = clone(source=str(project.path(INSTANCE)), path=str(path), result_renderer="disabled")
    if doc:
        (path / ".faire" / "dmp.json").write_text(json.dumps(doc(load_document(
            path / ".faire" / "dmp.json"))))
    if heuristic:
        (path / ".faire" / "heuristic.py").write_text(heuristic)
    if doc or heuristic:
        ds.save(message="local change", result_renderer="disabled")
    return ds


def head(project, branch="dev") -> str:
    return Dataset(project.path(INSTANCE)).repo.get_hexsha(branch)


def test_new_session(project, tmp_path):
    src = received(tmp_path / "in", ("sub-01_ses-a", "PrismaFit16001"))
    lines = indexer(project).index(src)
    assert "committed subject-01_session-a to dicoms/a_PrismaFit16001" in lines
    ds = Dataset(project.path(INSTANCE))
    assert (Path(ds.path) / "sub-01" / "ses-a" / "scan.dat").read_bytes() == b"data of sub-01_ses-a"
    message = ds.repo.call_git(["log", "-1", "--format=%B", "dev"])
    heuristic = ds.repo.call_git(["log", "-1", "--format=%H", "--", ".faire/heuristic.py"])
    assert "faire-entities: subject=01,session=a" in message
    assert f"faire-heuristic: {heuristic.strip()}" in message
    # content is on the collection remote
    where = ds.repo.whereis("sub-01/ses-a/scan.dat")
    remote_uuid = ds.config.get("remote.collection-site-storage.annex-uuid")
    assert remote_uuid in where
    assert ds.repo.get_active_branch() == "dev"


def test_repeat_is_a_no_op(project, tmp_path):
    src = received(tmp_path / "in", ("sub-02_ses-a", "PrismaFit16001"))
    indexer(project).index(src)
    before = head(project)
    lines = indexer(project).index(src)
    assert not any(line.startswith("committed") for line in lines)
    assert head(project) == before


def test_unknown_instrument(project, tmp_path):
    src = received(tmp_path / "in", ("sub-03_ses-a", "PrismaFit16001"),
                   ("sub-03_ses-b", "Skyra45012"))
    before = head(project)
    with pytest.raises(IndexingError, match="'Skyra45012' is not declared"):
        indexer(project).index(src)
    assert head(project) == before
    assert sorted(p.name for p in src.iterdir()) == ["sub-03_ses-a", "sub-03_ses-b"]


def test_pilot_marking(project, tmp_path):
    src = received(tmp_path / "in", ("sub-04_ses-a_pilot", "PrismaFit16001"))
    lines = indexer(project).index(src)
    assert "committed subject-04_session-a (pilot) to dicoms/a_PrismaFit16001" in lines
    ds = Dataset(project.path(INSTANCE))
    assert "sub-04/ses-a/scan.dat" in ds.repo.call_git(["ls-tree", "-r", "--name-only", "dev"])
    assert "faire-pilot: true" in ds.repo.call_git(["log", "-1", "--format=%B", "dev"])
    assert "pilot" not in ds.repo.get_branches()


def test_dry_run(project, tmp_path):
    src = received(tmp_path / "in", ("sub-05_ses-a", "PrismaFit16001"))
    before = head(project)
    result = CliRunner().invoke(main, [
        "index", str(project.path(INSTANCE)), str(src), "--dry-run"])
    assert result.exit_code == 0, result.output
    assert ("sub-05_ses-a: dicoms/a_PrismaFit16001 subject-05_session-a -> sub-05/ses-a"
            in result.output)
    assert head(project) == before


def test_content_before_history(project, tmp_path):
    src = received(tmp_path / "in", ("sub-06_ses-a", "PrismaFit16001"))
    store = project.workdir.parent / "ria"
    before = head(project)
    modes = {}
    for root, dirs, _ in os.walk(store):  # make the store unwritable
        for d in dirs:
            p = Path(root) / d
            modes[p] = p.stat().st_mode
            p.chmod(stat.S_IRUSR | stat.S_IXUSR)
    try:
        with pytest.raises(IndexingError, match="content push to collection-site-storage"):
            indexer(project).index(src)
    finally:
        for p, mode in modes.items():
            p.chmod(mode)
    assert head(project) == before


def test_other_instance_instrument(project, tmp_path):
    def second_scanner(doc):
        dicoms = next(d for d in doc["dmp"]["dataset"] if d["title"] == "scanner")
        dicoms["technical_resource"].append(
            {"name": "Skyra45012", "faire": {"instrument_id": "Skyra45012", "site": "a"}})
        return doc

    ds = instance_clone(project, tmp_path / "c", doc=second_scanner)
    src = received(tmp_path / "in", ("sub-07_ses-a", "Skyra45012"))
    before = ds.repo.get_hexsha()
    with pytest.raises(IndexingError, match="'Skyra45012' belongs to another instance"):
        Indexer(ds).index(src)
    assert ds.repo.get_hexsha() == before


def test_not_an_instance(project):
    with pytest.raises(IndexingError, match="not a stream instance"):
        Indexer(Dataset(project.path("rawdata")))


def test_entities_from_the_instance(project, tmp_path):
    heuristic = (project.path(INSTANCE) / ".faire" / "heuristic.py").read_text().replace(
        'return {"subject": parts["sub"], "session": parts["ses"]}',
        'return {"subject": parts["sub"]}')
    ds = instance_clone(project, tmp_path / "c", heuristic=heuristic)
    src = received(tmp_path / "in", ("sub-08_ses-a", "PrismaFit16001"))
    with pytest.raises(IndexingError, match="differ from the ma-DMP"):
        Indexer(ds).index(src)


def test_no_collection_remote(project, tmp_path):
    def rename_storage(doc):
        dicoms = next(d for d in doc["dmp"]["dataset"] if d["title"] == "scanner")
        for dist in dicoms["distribution"]:
            dist["title"] = "Elsewhere"
        return doc

    ds = instance_clone(project, tmp_path / "c", doc=rename_storage)
    before = ds.repo.get_hexsha()
    origin = head(project)
    src = received(tmp_path / "in", ("sub-09_ses-a", "PrismaFit16001"))
    with pytest.raises(IndexingError, match="remote collection-elsewhere is missing"):
        Indexer(ds).index(src)
    assert ds.repo.get_hexsha() == before
    assert head(project) == origin


def test_from_url_then_reused(project, tmp_path):
    url = (project.path(INSTANCE)).as_uri()
    where = tmp_path / "clone"
    src = received(tmp_path / "in", ("sub-10_ses-a", "PrismaFit16001"))
    result = CliRunner().invoke(main, ["index", url, str(src), "--clone", str(where)])
    assert result.exit_code == 0, result.output
    assert "committed subject-10_session-a" in result.output
    assert head(project) == Dataset(where).repo.get_hexsha("dev")  # pushed to origin
    ds = Dataset(project.path(INSTANCE))
    remote_uuid = ds.config.get("remote.collection-site-storage.annex-uuid")
    assert remote_uuid in ds.repo.whereis("sub-10/ses-a/scan.dat")

    # origin moves; the reused clone is fast-forwarded before indexing on top
    indexer(project).index(received(tmp_path / "in2", ("sub-11_ses-a", "PrismaFit16001")))
    moved = head(project)
    src = received(tmp_path / "in3", ("sub-12_ses-a", "PrismaFit16001"))
    result = CliRunner().invoke(main, ["index", url, str(src), "--clone", str(where)])
    assert result.exit_code == 0, result.output
    repo = Dataset(where).repo
    assert repo.call_git(["merge-base", "--is-ancestor", moved, "dev"]) == ""
    assert head(project) == repo.get_hexsha("dev")


def test_mismatched_clone(project, tmp_path):
    other = tmp_path / "other"
    other.mkdir()
    (other / "file").write_text("x")
    src = received(tmp_path / "in", ("sub-13_ses-a", "PrismaFit16001"))
    result = CliRunner().invoke(main, ["index", project.path(INSTANCE).as_uri(), str(src),
                                       "--clone", str(other)])
    assert result.exit_code != 0
    assert "is not a clone of" in result.output


def test_diverged_clone(project, tmp_path):
    ds = instance_clone(project, tmp_path / "c")
    (tmp_path / "c" / "local.txt").write_text("local")
    ds.save(message="local", result_renderer="disabled")
    indexer(project).index(received(tmp_path / "in", ("sub-14_ses-a", "PrismaFit16001")))
    before = ds.repo.get_hexsha()
    with pytest.raises(IndexingError, match="cannot bring dev up to date"):
        Indexer(ds)
    assert ds.repo.get_hexsha() == before
