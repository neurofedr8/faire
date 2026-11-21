import os
import stat
from pathlib import Path

import pytest
from click.testing import CliRunner
from datalad.api import Dataset

from conftest import make_env, reference_doc, write_doc
from faire.cli import main
from faire.indexing import Indexer, IndexingError
from faire.plan import Plan
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


def head(project, branch="dev") -> str:
    return Dataset(project.path(INSTANCE)).repo.get_hexsha(branch)


def test_new_session(project, tmp_path):
    src = received(tmp_path / "in", ("sub-01_ses-a", "PrismaFit16001"))
    lines = Indexer(project, "dicoms").index(src)
    assert "committed subject-01_session-a to dicoms/a_PrismaFit16001 dev" in lines
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
    Indexer(project, "dicoms").index(src)
    before = head(project)
    lines = Indexer(project, "dicoms").index(src)
    assert not any(line.startswith("committed") for line in lines)
    assert head(project) == before


def test_unknown_instrument(project, tmp_path):
    src = received(tmp_path / "in", ("sub-03_ses-a", "PrismaFit16001"),
                   ("sub-03_ses-b", "Skyra45012"))
    before = head(project)
    with pytest.raises(IndexingError, match="'Skyra45012' is not declared"):
        Indexer(project, "dicoms").index(src)
    assert head(project) == before
    assert sorted(p.name for p in src.iterdir()) == ["sub-03_ses-a", "sub-03_ses-b"]


def test_pilot_routing(project, tmp_path):
    src = received(tmp_path / "in", ("sub-04_ses-a_pilot", "PrismaFit16001"))
    before_dev = head(project)
    lines = Indexer(project, "dicoms").index(src)
    assert "committed subject-04_session-a to dicoms/a_PrismaFit16001 pilot" in lines
    assert head(project) == before_dev
    ds = Dataset(project.path(INSTANCE))
    files = ds.repo.call_git(["ls-tree", "-r", "--name-only", "pilot"])
    assert "sub-04/ses-a/scan.dat" in files


def test_dry_run(project, tmp_path):
    src = received(tmp_path / "in", ("sub-05_ses-a", "PrismaFit16001"))
    before = head(project)
    result = CliRunner().invoke(main, [
        "index", "dicoms", str(src), "--dmp", str(project.dmp_file),
        "--workdir", str(project.workdir), "--dry-run"])
    assert result.exit_code == 0, result.output
    assert ("sub-05_ses-a: dicoms/a_PrismaFit16001 subject-05_session-a -> sub-05/ses-a on dev"
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
            Indexer(project, "dicoms").index(src)
    finally:
        for p, mode in modes.items():
            p.chmod(mode)
    assert head(project) == before
