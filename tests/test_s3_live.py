"""S3 distributions against a real object store (opt-in; Silo in the tool's CI).

Set FAIRE_TEST_S3_HOST (e.g. `localhost`), AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY, and
optionally FAIRE_TEST_S3_PORT (default 9000), FAIRE_TEST_S3_PROTOCOL (default `http`) and
FAIRE_TEST_S3_BUCKET (default `faire-test`). Each run stores under a new prefix of the bucket.
"""

import os
import uuid
from pathlib import Path

import pytest
from datalad.api import clone

from conftest import by_id, make_env, reference_doc, write_doc
from faire import layout, remotes
from faire.distribution import sync
from faire.plan import Plan, s3_parameters
from faire.project import Project

HOST = os.environ.get("FAIRE_TEST_S3_HOST")
PORT = os.environ.get("FAIRE_TEST_S3_PORT", "9000")
PROTOCOL = os.environ.get("FAIRE_TEST_S3_PROTOCOL", "http")
BUCKET = os.environ.get("FAIRE_TEST_S3_BUCKET", "faire-test")
RUN = uuid.uuid4().hex[:8]
INSTANCES = ("a_PrismaFit16001", "a_Skyra45012")

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not (HOST and os.environ.get("AWS_ACCESS_KEY_ID")
             and os.environ.get("AWS_SECRET_ACCESS_KEY")),
        reason="no S3 store configured"),
]


def s3(prefix: str) -> str:
    return ("datalad-annex::?type=S3&encryption=none"
            f"&bucket={BUCKET}&fileprefix={RUN}/{prefix}&host={HOST}&port={PORT}"
            f"&protocol={PROTOCOL}&requeststyle=path&signature=v4")


@pytest.fixture(scope="module")
def setup(tmp_path_factory, reference, templates_root):
    env = make_env(tmp_path_factory.mktemp("s3"), templates_root)
    doc = reference_doc(env, reference)
    dicoms = by_id(doc, "dicoms")
    dicoms["technical_resource"].append(
        {"name": "Skyra45012", "faire": {"instrument_id": "Skyra45012", "site": "a"}})
    dicoms["distribution"].append(env.dist("Lab S3", "collection", s3("dicoms/")))
    by_id(doc, "bids")["distribution"] += [
        env.dist("Lab S3", "accepted", s3("rawbids/")),
        env.dist("Lab S3 release", "release", s3("rawbids-release/")),
    ]
    plan = Plan.from_document(doc)
    proj = Project(plan, write_doc(env.root / "dmp.json", doc), env.root / "w")
    proj.init()
    ds = clone(source=str(proj.path("rawdata")), path=str(env.root / "c"),
               result_renderer="disabled")
    ds.repo.call_git(["checkout", "-q", "-b", "dev", "refs/remotes/origin/dev"])
    (Path(ds.path) / "data.bin").write_bytes(b"\0accepted")
    ds.save(result_renderer="disabled")
    ds.repo.call_git(["push", "-q", "--no-verify", "origin", "dev", "git-annex"])
    return env, plan, proj, ds


def test_stream_instances_under_their_prefix(setup):
    _, _, proj, _ = setup
    for instance in INSTANCES:
        unit = next(u for u in layout.units(proj.plan) if u.label == f"dicoms/{instance}")
        ds = proj.dataset(unit)
        config = next(c for c in ds.repo.get_special_remotes().values()
                      if c.get("name") == "collection-lab-s3")
        assert config["fileprefix"] == f"{RUN}/dicoms/{instance}/"
        (Path(ds.path) / f"{instance}.dcm").write_bytes(instance.encode())
        ds.save(result_renderer="disabled")
        remotes.verify(ds, "collection-lab-s3")
        ds.repo.call_annex(["copy", "--to", "collection-lab-s3", f"{instance}.dcm"])
        assert "collection-lab-s3" in ds.repo.call_annex(["whereis", f"{instance}.dcm"])


def test_accepted_is_content_only(setup):
    _, plan, _, ds = setup
    sync(plan, ds, "accepted", ["dev"])
    assert "accepted-lab-s3" in ds.repo.call_annex(["whereis", "data.bin"])
    assert not ds.config.get("remote.accepted-lab-s3.url")


def test_release_clones_from_s3_alone(setup, tmp_path):
    _, plan, _, ds = setup
    sync(plan, ds, "release", ["dev:refs/heads/main"])
    url = s3("rawbids-release/")
    copy = clone(source=url, path=str(tmp_path / "copy"), result_renderer="disabled")
    assert copy.repo.get_hexsha() == ds.repo.get_hexsha("dev")
    remotes.verify(copy, "release-lab-s3-release-storage")
    copy.get("data.bin", result_renderer="disabled")
    assert (tmp_path / "copy" / "data.bin").read_bytes() == b"\0accepted"
    assert s3_parameters(copy.config.get("remote.origin.url"))["bucket"] == BUCKET
