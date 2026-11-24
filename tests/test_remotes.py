import pytest
from datalad.api import clone, create

from faire import remotes
from faire.distribution import push_history
from faire.plan import Distribution, s3_parameters

S3 = "datalad-annex::?type=S3&encryption=none&bucket=studyx{}&host=s3.example.org"


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        (S3.format(""), "s3"),
        ("datalad-annex::?type=s3&bucket=b&encryption=none", "s3"),
        ("datalad-annex::?type=webdav&url=https://x", "datalad-annex"),
        ("ria+ssh://host/store", "ria"),
        ("ssh://host/path", "plain"),
    ],
)
def test_kind(url, expected):
    assert remotes.kind(url) == expected


@pytest.mark.parametrize(
    ("prefix", "expected"),
    [("", "a_PrismaFit16001/"), ("&fileprefix=dicoms/", "dicoms/a_PrismaFit16001/")],
)
def test_stream_instance_prefix(prefix, expected):
    dist = Distribution("Lab S3", "collection", "anything", S3.format(prefix))
    (spec,) = remotes.specs([dist], instance="a_PrismaFit16001")
    params = s3_parameters(spec.url)
    assert params["fileprefix"] == expected
    assert params["bucket"] == "studyx" and params["host"] == "s3.example.org"


def test_no_instance_keeps_url():
    url = S3.format("&fileprefix=rawbids/")
    (spec,) = remotes.specs([Distribution("Lab S3", "accepted", "anything", url)])
    assert spec.url == url


def test_initremote_arguments():
    args = remotes.s3_initremote("accepted-lab-s3", S3.format("&fileprefix=rawbids/"))
    assert args == ["initremote", "accepted-lab-s3", "type=S3", "encryption=none",
                    "bucket=studyx", "fileprefix=rawbids/", "host=s3.example.org",
                    "autoenable=true"]


# A git-annex directory special remote stands in for a bucket: creation, pushes and clones run
# the real code paths, only the S3 transport is not exercised (see the opt-in Silo test).
@pytest.fixture
def bucket(tmp_path, monkeypatch):
    real = remotes.kind
    monkeypatch.setattr(remotes, "kind", lambda url, platform_host=None: (
        "s3" if "type=directory" in url else real(url, platform_host)))
    path = tmp_path / "bucket"
    path.mkdir()
    return f"datalad-annex::?type=directory&directory={path}&encryption=none", path


@pytest.fixture
def dataset(tmp_path):
    ds = create(str(tmp_path / "ds"), result_renderer="disabled")
    (tmp_path / "ds" / "data.bin").write_bytes(b"\0" * 1024)
    ds.save(message="data", result_renderer="disabled")
    return ds


def stored(path):
    return [p for p in path.rglob("*") if p.is_file()]


def test_early_stage_s3_is_content_only(dataset, bucket):
    url, path = bucket
    spec = remotes.RemoteSpec("accepted-lab-s3", url, "anything", "accepted")
    remotes.create(dataset, spec, storage_only=True)
    assert "accepted-lab-s3" in remotes.special_names(dataset)
    assert not dataset.config.get("remote.accepted-lab-s3.url")  # history stays elsewhere
    assert remotes.content_target(dataset, spec.name) == spec.name
    assert remotes.status(dataset, spec) == "ok"  # wanted set
    dataset.repo.call_annex(["copy", "--auto", "--to", spec.name, "."])
    assert len(stored(path)) == 1


def test_release_s3_holds_history_and_content(dataset, bucket, tmp_path):
    url, path = bucket
    spec = remotes.RemoteSpec("release-lab-s3", url, "anything", "release")
    remotes.create(dataset, spec, storage_only=False)
    assert remotes.content_target(dataset, spec.name) == "release-lab-s3-storage"
    assert dataset.config.get("remote.release-lab-s3.datalad-publish-depends") == (
        "release-lab-s3-storage")
    dataset.repo.call_annex(["copy", "--auto", "--to", "release-lab-s3-storage", "."])
    branch = dataset.repo.get_active_branch()
    push_history(dataset, spec.name, [f"refs/heads/{branch}"])

    copy = clone(source=url, path=str(tmp_path / "copy"), result_renderer="disabled")
    assert copy.repo.get_hexsha() == dataset.repo.get_hexsha()
    # unlike S3's bucket and host, a directory remote's path is not recorded in git-annex
    copy.repo.call_annex(["enableremote", "release-lab-s3-storage", f"directory={path}"])
    remotes.verify(copy, "release-lab-s3-storage")  # git-annex asks to confirm in a clone
    copy.get("data.bin", result_renderer="disabled")
    assert (tmp_path / "copy" / "data.bin").read_bytes() == b"\0" * 1024
    # a fresh clone gets the same remotes back without initialising them again
    remotes.create(copy, spec, storage_only=False)
    assert remotes.status(copy, spec) == "ok"
