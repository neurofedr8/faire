from pathlib import Path

import pytest
from datalad.api import Dataset, clone

from conftest import by_id, make_env, reference_doc, write_doc
from faire.distribution import SyncError, release_refs, sync
from faire.plan import Plan
from faire.project import Project

RESTRICTED = "not metadata=distribution-restrictions=*"


@pytest.fixture(scope="module")
def setup(tmp_path_factory, reference, templates_root):
    env = make_env(tmp_path_factory.mktemp("dist"), templates_root)
    doc = reference_doc(env, reference)
    by_id(doc, "bids")["distribution"] += [
        env.dist("Shared", "accepted", str(env.root / "shared" / "bids"), RESTRICTED),
        env.dist("Archive", "release", f"ria+file://{env.root / 'release-ria'}", RESTRICTED),
        env.dist("Mirror", "release", str(env.root / "mirror" / "rawdata"), RESTRICTED),
    ]
    proj = Project(Plan.from_document(doc), write_doc(env.root / "dmp.json", doc), env.root / "w")
    proj.init()
    # accepted data on dev: one shareable file, one restricted
    ds = clone(source=str(proj.path("rawdata")), path=str(env.root / "c"),
               result_renderer="disabled")
    ds.repo.call_git(["checkout", "-q", "-b", "dev", "refs/remotes/origin/dev"])
    (Path(ds.path) / "data.bin").write_bytes(b"\0shared")
    (Path(ds.path) / "secret.bin").write_bytes(b"\0secret")
    ds.save(result_renderer="disabled")
    ds.repo.call_annex(["metadata", "-s", "distribution-restrictions=sensitive", "secret.bin"])
    ds.repo.call_git(["push", "-q", "--no-verify", "origin", "dev", "git-annex"])
    return env, doc, proj, ds


def where(ds: Dataset, path: str) -> set[str]:
    return set(ds.repo.whereis(path))


def uuid(ds: Dataset, remote: str) -> str:
    return ds.config.get(f"remote.{remote}.annex-uuid")


def test_accepted_wanted_and_resumable(setup):
    env, doc, _, ds = setup
    plan = Plan.from_document(doc)
    first = sync(plan, ds, "accepted", ["dev"])
    assert first == ["bids: Shared (accepted-shared): 1 files sent"]
    shared = uuid(ds, "accepted-shared")
    assert shared in where(ds, "data.bin") and shared not in where(ds, "secret.bin")
    # a plain push afterwards honours the wanted expression too
    ds.push(to="accepted-shared", result_renderer="disabled")
    assert shared not in where(ds, "secret.bin")
    assert Dataset(env.root / "shared" / "bids").repo.get_hexsha("dev") == ds.repo.get_hexsha()
    assert sync(plan, ds, "accepted", ["dev"]) == ["bids: Shared (accepted-shared): 0 files sent"]


def test_release_remotes_created_on_first_use(setup, tmp_path):
    env, doc, _, ds = setup
    plan = Plan.from_document(doc)
    ds.repo.call_git(["tag", "v1.0"])
    lines = sync(plan, ds, "release", release_refs("v1.0"))
    assert lines == ["bids: Archive (release-archive): 1 files sent",
                     "bids: Mirror (release-mirror): 1 files sent"]
    got = clone(source=f"ria+file://{env.root / 'release-ria'}#{ds.id}", path=str(tmp_path / "r"),
                result_renderer="disabled")
    got.get("data.bin", result_renderer="disabled")
    assert (Path(got.path) / "data.bin").read_bytes() == b"\0shared"
    res = got.get("secret.bin", on_failure="ignore", result_renderer="disabled")
    assert [r["status"] for r in res] == ["error"]
    mirror = Dataset(env.root / "mirror" / "rawdata")
    assert "v1.0" in mirror.repo.get_tags()[0]["name"]


def test_missing_credential(setup, monkeypatch):
    env, doc, _, ds = setup
    doc = {**doc}
    by_id(doc, "bids")["distribution"].append(
        env.dist("GIN", "release", "ssh://git@gin.g-node.org/lab/studyx.rawdata.git", RESTRICTED))
    monkeypatch.delenv("DATALAD_CREDENTIAL_GIN_TOKEN", raising=False)
    remotes_before = set(ds.repo.get_remotes())
    with pytest.raises(SyncError, match="'GIN' needs DATALAD_CREDENTIAL_GIN_TOKEN"):
        sync(Plan.from_document(doc), ds, "release", ["dev"], only=None)
    assert set(ds.repo.get_remotes()) == remotes_before
    by_id(doc, "bids")["distribution"].pop()


@pytest.mark.parametrize("absent", ["AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY"])
def test_missing_s3_credential(setup, monkeypatch, absent):
    env, doc, _, ds = setup
    url = "datalad-annex::?type=S3&encryption=none&bucket=studyx&fileprefix=rawbids/"
    by_id(doc, "bids")["distribution"].append(env.dist("Lab S3", "release", url, RESTRICTED))
    for variable in ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY"):
        monkeypatch.setenv(variable, "x")
    monkeypatch.delenv(absent)
    remotes_before = set(ds.repo.get_remotes())
    try:
        with pytest.raises(SyncError, match=f"'Lab S3' needs {absent}"):
            sync(Plan.from_document(doc), ds, "release", ["dev"], only="Lab S3")
        assert set(ds.repo.get_remotes()) == remotes_before
    finally:
        by_id(doc, "bids")["distribution"].pop()


def test_unknown_distribution(setup):
    _, doc, _, ds = setup
    with pytest.raises(SyncError, match="no accepted distribution titled 'Nope'"):
        sync(Plan.from_document(doc), ds, "accepted", ["dev"], only="Nope")
