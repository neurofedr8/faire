import shutil
from pathlib import Path

import pytest
from datalad.api import Dataset, clone

from conftest import by_id, make_env, reference_doc, write_doc
from faire import release as R
from faire import remotes
from faire.branches import bump_source
from faire.plan import Plan
from faire.project import Project
from faire.tasks import pipeline


@pytest.fixture(scope="module")
def setup(tmp_path_factory, reference, templates_root):
    env = make_env(tmp_path_factory.mktemp("rel"), templates_root)
    doc = reference_doc(env, reference)
    ria = f"ria+file://{env.root / 'release-ria'}"
    by_id(doc, "study")["distribution"] = [env.dist("Archive", "release", ria)]
    by_id(doc, "bids")["distribution"].append(env.dist("Archive", "release", ria))
    doc["dmp"]["dataset"].append(env.dataset(
        "fmriprep", "fMRIPrep", env.derived_tpl, path="derivatives/fmriprep", sources=["bids"],
        data={"collection_url": env.collection},
        distributions=[env.dist("Mirror", "release", str(env.root / "mirror" / "fmriprep"))]))
    proj = Project(Plan.from_document(doc), write_doc(env.root / "dmp.json", doc), env.root / "w")
    proj.init()
    work = env.root / "edits"
    bids = on_dev(proj, "rawdata", work / "bids")
    commit(bids, {"sub-01/ses-a/anat/scan.dat": b"\0scan 01"}, "subject-01_session-a")
    fmriprep = on_dev(proj, "derivatives/fmriprep", work / "fmriprep")
    assert bump_source(fmriprep, "sourcedata/bids", "dev")
    commit(fmriprep, {"sub-01/out.dat": b"\0out 01"}, "subject-01_session-a")
    commit(bids, {"sub-02/ses-a/anat/scan.dat": b"\0scan 02"}, "subject-02_session-a")
    return env, Plan.from_document(doc), proj, bids, fmriprep


def on_dev(proj, logical, path) -> Dataset:
    ds = clone(source=str(proj.path(logical)), path=str(path), result_renderer="disabled")
    ds.repo.call_git(["checkout", "-q", "-b", "dev", "refs/remotes/origin/dev"])
    return ds


def commit(ds: Dataset, files: dict[str, bytes], sample: str | None = None) -> None:
    for name, data in files.items():
        (Path(ds.path) / name).parent.mkdir(parents=True, exist_ok=True)
        (Path(ds.path) / name).write_bytes(data)
    message = "data" + (f"\n\nfaire-sample: {sample}" if sample else "")
    ds.save(message=message, result_renderer="disabled")
    remotes.verify_all(ds)  # clones must confirm faire's special remotes before writing
    ds.push(to="origin", data="anything", result_renderer="disabled")


def superdataset(proj, tmp, version) -> Dataset:
    sup = clone(source=str(proj.path("superdataset")), path=str(tmp / "sup"),
                result_renderer="disabled")
    sup.repo.call_git(["checkout", "-q", "-b", f"rel/{version}", "refs/remotes/origin/dev"])
    return sup


def test_release_check_blocks_before_any_push(setup, tmp_path):
    env, plan, proj, bids, _ = setup
    commit(bids, {"bad-name.dat": b"\0x"})
    sup = superdataset(proj, tmp_path, "0.1")
    with pytest.raises(R.ReleaseError, match="bids: release check validate failed"):
        R.release(sup, plan)
    assert not (env.root / "release-ria").exists()
    assert not (env.root / "mirror").exists()
    bids.repo.call_git(["rm", "-q", "bad-name.dat"])
    bids.repo.call_git(["commit", "-q", "-m", "remove bad file"])
    bids.repo.call_git(["push", "-q", "--no-verify", "origin", "dev", "git-annex"])


def test_diverged_pointer(setup, tmp_path):
    env, plan, proj, bids, fmriprep = setup
    bids.repo.call_git(["checkout", "-q", "-b", "side", "HEAD~1"])
    bids.repo.call_git(["commit", "-q", "--allow-empty", "-m", "side"])
    bids.repo.call_git(["push", "-q", "--no-verify", "origin", "side"])
    side = bids.repo.get_hexsha()
    bids.repo.call_git(["checkout", "-q", "dev"])
    sub = Dataset(Path(fmriprep.path) / "sourcedata" / "bids")
    sub.repo.call_git(["fetch", "-q", "origin"])
    sub.repo.call_git(["checkout", "-q", side])
    fmriprep.save(path="sourcedata/bids", message="diverge", result_renderer="disabled")
    fmriprep.repo.call_git(["push", "-q", "--no-verify", "origin", "dev"])
    sup = superdataset(proj, tmp_path, "0.2")
    with pytest.raises(R.ReleaseError, match="fmriprep: sourcedata/bids at .* is not an "
                                             "ancestor of the released bids"):
        R.release(sup, plan)
    assert not (env.root / "release-ria").exists()
    fmriprep.repo.call_git(["reset", "-q", "--hard", "HEAD~1"])
    fmriprep.repo.call_git(["push", "-q", "--no-verify", "-f", "origin", "dev"])


def test_release_tag_and_install_without_platform(setup, tmp_path):
    env, plan, proj, bids, fmriprep = setup
    sup = superdataset(proj, tmp_path, "1.0")
    assert pipeline(sup, "rel/1.0", superdataset=True).jobs == [("release", "faire release")]
    lines = R.release(sup, plan)
    assert "fmriprep lacks samples of bids: subject-02_session-a" in lines
    assert lines[-1] == "1.0 is reachable on every release remote"
    assert R.release(sup, plan)[-1].endswith("reachable on every release remote")  # rerun
    assert not R._has_tag(Dataset(proj.path("rawdata")), "1.0")  # no tag before the merge
    # the reviewed merge into main, then tagging
    sup.repo.call_git(["checkout", "-q", "-b", "main", "refs/remotes/origin/main"])
    sup.repo.call_git(["merge", "-q", "--no-ff", "--no-edit", "rel/1.0"])
    assert pipeline(sup, "main", superdataset=True).jobs == [("tag", "faire release --tag")]
    lines = R.tag(sup, plan)
    assert len(lines) == 3
    for logical in ("rawdata", "derivatives/fmriprep", "superdataset"):
        assert R._has_tag(Dataset(proj.path(logical)), "1.0"), logical
    mirror = Dataset(env.root / "mirror" / "fmriprep")
    assert R._has_tag(mirror, "1.0")
    # the platform is gone: the released tree installs from the release remotes alone
    shutil.move(str(proj.workdir), str(env.root / "gone"))
    try:
        user = clone(source=f"ria+file://{env.root / 'release-ria'}#{sup.id}",
                     path=str(tmp_path / "user"), result_renderer="disabled")
        user.repo.call_git(["checkout", "-q", "1.0"])
        # registered datasets only: raw streams under sourcedata/ are not released
        user.get(".", recursive=True, recursion_limit=1, get_data=False,
                 result_renderer="disabled")
        user.get("rawdata/sub-01/ses-a/anat/scan.dat", result_renderer="disabled")
        assert (Path(user.path) / "rawdata/sub-01/ses-a/anat/scan.dat").read_bytes() == \
            b"\0scan 01"
        user.get("derivatives/fmriprep/sub-01/out.dat", result_renderer="disabled")
        assert (Path(user.path) / "derivatives/fmriprep/sub-01/out.dat").read_bytes() == \
            b"\0out 01"
    finally:
        shutil.move(str(env.root / "gone"), str(proj.workdir))


def test_real_dates_block_fake_dated_dataset(setup, tmp_path):
    env, plan, proj, bids, _ = setup
    # bids turns fake dates on, but its history already has real dates
    bids.config.set("datalad.fake-dates", "true", scope="branch")
    bids.save(path=".datalad/config", message="fake dates", result_renderer="disabled")
    bids.repo.call_git(["push", "-q", "--no-verify", "origin", "dev"])
    sup = superdataset(proj, tmp_path, "0.9")
    before = sorted(p.name for p in (env.root / "mirror").glob("*")) \
        if (env.root / "mirror").exists() else []
    with pytest.raises(R.ReleaseError, match="bids: real date in commit"):
        R.release(sup, plan)
    after = sorted(p.name for p in (env.root / "mirror").glob("*")) \
        if (env.root / "mirror").exists() else []
    assert after == before
    assert "rel/0.9" not in Dataset(proj.path("superdataset")).repo.get_branches()
    bids.repo.call_git(["revert", "--no-edit", "HEAD"])
    bids.repo.call_git(["push", "-q", "--no-verify", "origin", "dev"])
