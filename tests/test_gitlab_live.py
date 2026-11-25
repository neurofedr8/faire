"""End-to-end on a real GitLab, with the pipelines faire renders (opt-in).

Set FAIRE_TEST_GITLAB_URL and FAIRE_TEST_GITLAB_TOKEN (a group access token, Owner, `api`
scope), and optionally FAIRE_TEST_GITLAB_GROUP (default `faire_dev`) and
FAIRE_TEST_GITLAB_REVIEWER_TOKEN (another identity approving sessions; by default a group
access token created in the subgroup). Each run works in a new
subgroup, deleted afterwards unless FAIRE_TEST_KEEP is set.

Runners only need a stock alpine image: FAIRE_SETUP installs git-annex, DataLad and this
working tree of faire (pushed to the subgroup). Everything stays in git (GitLab hosts no
annexed content); release distributions are projects of the subgroup.
"""

import os
import shutil
import subprocess
import time
import uuid
from pathlib import Path

import gitlab
import pytest
from datalad.api import Dataset, create

from conftest import REFERENCE, git_template, make_env, write_doc
from faire.indexing import Indexer
from faire.plan import Plan
from faire.platform.gitlab import GitLabPlatform
from faire.project import Project
from test_tasks import received

URL = os.environ.get("FAIRE_TEST_GITLAB_URL")
TOKEN = os.environ.get("FAIRE_TEST_GITLAB_TOKEN")
PARENT = os.environ.get("FAIRE_TEST_GITLAB_GROUP", "faire_dev")
REVIEWER_TOKEN = os.environ.get("FAIRE_TEST_GITLAB_REVIEWER_TOKEN")
ROOT = Path(__file__).parents[1]

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not (URL and TOKEN), reason="no live GitLab configured"),
]

IN_GIT = "* annex.largefiles=nothing\n"
CI = (REFERENCE / "toy-standard" / ".gitlab-ci.yml").read_text()
ANSWERS = "{{ _copier_answers|to_nice_yaml }}"

STANDARD_CONFIG = """[faire "collection.toy"]
\turl = {{ collection_url }}
\tpath = code/containers
\trevision = v1
[datalad "containers.convert"]
\timage = code/containers/images/toy-1.0.sh
\tcmdexec = sh {img} {cmd}
\tfaire-sourcedata = dicoms
\tfaire-input = sourcedata/dicoms/*/sub-{subject}/ses-{session}/*.dat
\tfaire-output = sub-{subject}/ses-{session}/anat
\tfaire-cmd = copy sub-{subject}/ses-{session}/anat {inputs}
[datalad "containers.validate"]
\timage = code/containers/images/toy-1.0.sh
\tcmdexec = sh {img} {cmd}
\tfaire-check = blocking
\tfaire-stage = collection
\tfaire-stage = release
\tfaire-cmd = check .
"""


def setup_script(src_url: str) -> str:
    return (
        "set -e; apk add --no-cache -q python3 py3-pip git git-annex; "
        "git config --global user.name faire-ci; git config --global user.email ci@faire; "
        "git config --global credential.helper "
        "'!f() { echo username=oauth2; echo \"password=$FAIRE_GITLAB_TOKEN\"; }; f'; "
        # git-annex comes from apk: its PyPI wheel is not built for musl
        "pip install -q --break-system-packages 'click>=8.1' 'datalad>=1.1' "
        "'datalad-container>=1.2' 'copier>=9.3' 'jsonschema>=4.21' 'python-gitlab>=4.4' "
        "'pyyaml>=6'; "
        f"pip install -q --break-system-packages --no-deps 'git+{src_url}'"
    )


def templates(root: Path) -> dict[str, str]:
    stream = {
        "copier.yml": "_answers_file: .copier-answers.yml\n",
        "{{ _copier_conf.answers_file }}.jinja": ANSWERS,
        "README.md.jinja": "# {{ dataset_id }} from {{ instance }}\n",
        ".gitattributes": IN_GIT,
        ".gitlab-ci.yml": CI,
        ".faire/heuristic.py": (REFERENCE / "stream/.faire/heuristic.py").read_text(),
    }
    standard = {
        "copier.yml": "collection_url:\n  type: str\n_answers_file: .copier-answers.yml\n",
        "{{ _copier_conf.answers_file }}.jinja": ANSWERS,
        "README.md.jinja": "# {{ title }}\n",
        ".gitattributes": IN_GIT,
        ".gitlab-ci.yml": CI,
        ".datalad/config.jinja": STANDARD_CONFIG,
    }
    superdataset = {
        "copier.yml": "_answers_file: .copier-answers.yml\n",
        "{{ _copier_conf.answers_file }}.jinja": ANSWERS,
        "README.md": "# Study\n",
        ".gitattributes": IN_GIT,
        ".gitlab-ci.yml": CI,
    }
    return {name: git_template(root / name, files)
            for name, files in [("stream", stream), ("standard", standard),
                                ("superdataset", superdataset)]}


def push_tree(platform: GitLabPlatform, path: str, src: Path, work: Path) -> str:
    """Push a snapshot of ``src``'s tracked files (working tree) as one commit."""
    files = subprocess.run(["git", "ls-files", "-z"], cwd=src, capture_output=True,
                           check=True, text=True).stdout.split("\0")
    for name in filter(None, files):
        if (src / name).is_file():
            (work / name).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src / name, work / name)
    repo = platform.ensure_repository(path)
    env = {**os.environ, "GIT_DIR": str(work / ".git"), "GIT_WORK_TREE": str(work)}
    for args in (["init", "-q", "-b", "main"], ["add", "-A"],
                 ["commit", "-qm", "faire snapshot"]):
        subprocess.run(["git", *args], cwd=work, env=env, check=True)
    with platform.git_auth():
        subprocess.run(["git", "push", "-q", "-o", "ci.skip", repo.url, "main"], cwd=work,
                       env={**env, **_auth_env()}, check=True)
    return repo.url


def _auth_env() -> dict[str, str]:
    return {k: v for k, v in os.environ.items() if k.startswith(("GIT_CONFIG", "FAIRE_GIT"))}


def toy_collection(platform: GitLabPlatform, path: str, work: Path) -> str:
    ds = create(path=str(work), result_renderer="disabled")
    (work / ".gitattributes").write_text(IN_GIT)
    (work / "images").mkdir()
    shutil.copy2(REFERENCE / "toy-collection/images/toy-1.0.sh", work / "images/toy-1.0.sh")
    ds.save(message="toy 1.0", result_renderer="disabled")
    ds.repo.call_git(["tag", "v1"])
    repo = platform.ensure_repository(path)
    with platform.git_auth():
        ds.repo.call_git(["push", "-q", "-o", "ci.skip", repo.url, "HEAD:refs/heads/main",
                          "v1", "git-annex"])
    return repo.url


class Live:
    """The study's platform (its own subgroup) and the sandbox around it."""

    def __init__(self, platform: GitLabPlatform, tools: GitLabPlatform, reviewer):
        self.platform, self.tools, self.gl = platform, tools, platform.gl
        self.sandbox = platform.group  # where the study's repositories are
        self.reviewer = reviewer  # a python-gitlab client of another identity

    def project(self, path: str):
        return self.gl.projects.get(f"{self.sandbox}/{path}")

    def settle(self, path: str, timeout: int = 2400, quiet: int = 2) -> None:
        """Wait until no pipeline of the project has run for ``quiet`` consecutive polls."""
        project, calm, deadline = self.project(path), 0, time.time() + timeout
        while time.time() < deadline:
            busy = [p for p in project.pipelines.list(get_all=False, per_page=20)
                    if p.status in ("created", "waiting_for_resource", "preparing", "pending",
                                    "running")]
            calm = 0 if busy else calm + 1
            if calm >= quiet:
                return
            time.sleep(20)
        raise AssertionError(f"pipelines of {path} still running after {timeout}s")

    def failed(self, path: str) -> list[str]:
        project = self.project(path)
        return [f"{p.ref} #{p.id}" for p in project.pipelines.list(get_all=True)
                if p.status == "failed"]

    def merge_request(self, path: str, source: str, target: str, timeout: int = 900):
        project, deadline = self.project(path), time.time() + timeout
        while time.time() < deadline:
            found = project.mergerequests.list(state="opened", source_branch=source,
                                               target_branch=target)
            if found:
                return found[0]
            time.sleep(15)
        raise AssertionError(f"no merge request {source} -> {target} on {path}")

    def merge(self, path: str, mr) -> None:
        project = self.project(path)
        mr = project.mergerequests.get(mr.iid)
        if mr.draft:
            mr.title = mr.title.removeprefix("Draft: ")
            mr.save()
        for _ in range(20):  # mergeability is computed asynchronously
            try:
                project.mergerequests.get(mr.iid).merge()
                return
            except Exception:
                time.sleep(15)
        raise AssertionError(f"cannot merge !{mr.iid} on {path}")

    def merge_session(self, path: str, mr) -> None:
        """The reviewer approves, then plays the manual merge job of the session pipeline."""
        project = self.project(path)
        self.reviewer.projects.get(project.id).mergerequests.get(mr.iid).approve()
        assert self.platform.approvers(self.platform.get_repository(project.path_with_namespace),
                                       mr.iid), "the approval is not seen as human"
        [latest] = project.pipelines.list(ref=mr.source_branch, get_all=False, per_page=1)
        for bridge in project.pipelines.get(latest.id).bridges.list(get_all=True):
            child = project.pipelines.get(bridge.downstream_pipeline["id"])
            for job in child.jobs.list(get_all=True):
                if job.name == "merge":
                    project.jobs.get(job.id).play()
                    return
        raise AssertionError(f"no merge job in the last pipeline of {mr.source_branch}")

    def tags(self, path: str) -> set[str]:
        return {t.name for t in self.project(path).tags.list(get_all=True)}


@pytest.fixture
def live(tmp_path):
    parent = GitLabPlatform(URL, TOKEN, PARENT)
    sandbox = f"{PARENT}/e2e-{uuid.uuid4().hex[:8]}"
    group = parent._ensure_group(sandbox)
    tools = GitLabPlatform(URL, TOKEN, sandbox)  # tool source and container collection
    src = push_tree(tools, f"{sandbox}/faire-src", ROOT, tmp_path / "src")
    for key, value, masked in [("FAIRE_GITLAB_TOKEN", TOKEN, True),
                               ("FAIRE_IMAGE", "alpine:3", False),
                               ("FAIRE_SETUP", setup_script(src), False)]:
        group.variables.create({"key": key, "value": value, "masked": masked, "raw": True})
    token = REVIEWER_TOKEN or group.access_tokens.create({
        "name": "reviewer", "scopes": ["api"], "access_level": 40,
        "expires_at": time.strftime("%Y-%m-%d", time.gmtime(time.time() + 2 * 86400)),
    }).token
    reviewer = gitlab.Gitlab(URL, private_token=token)
    try:
        yield Live(GitLabPlatform(URL, TOKEN, f"{sandbox}/study"), tools, reviewer), tmp_path
    finally:
        if not os.environ.get("FAIRE_TEST_KEEP"):
            parent.gl.groups.delete(sandbox)


def test_session_reaches_a_release_tag(live, tmp_path_factory, templates_root):
    live, tmp = live
    platform = live.platform
    sandbox_url = f"{URL}/{live.tools.group}"  # release projects outside the study's group
    collection = toy_collection(live.tools, f"{live.tools.group}/toy-collection", tmp / "toy")
    tpl = templates(tmp / "templates")
    env = make_env(tmp / "env", templates_root)
    doc = env.doc()
    doc["dmp"]["dataset"] = [
        env.dataset("study", "Study", tpl["superdataset"], path=".", distributions=[
            env.dist("Archive", "release", f"{sandbox_url}/release/superdataset.git")]),
        env.dataset("dicoms", "scanner", tpl["stream"], instruments=["PrismaFit16001"]),
        env.dataset("bids", "BIDS", tpl["standard"], path="rawdata", sources=["dicoms"],
                    data={"collection_url": collection}, distributions=[
                        env.dist("Archive", "release", f"{sandbox_url}/release/rawdata.git")]),
    ]
    proj = Project(Plan.from_document(doc), write_doc(tmp / "dmp.json", doc), tmp / "work",
                   platform)
    report = proj.init()
    assert report.differences == []

    # a session arrives: the stream pipeline triggers bids, which opens and converts it
    with platform.git_auth():
        Indexer(Dataset(proj.path("sourcedata/dicoms/a_PrismaFit16001"))).index(
            received(tmp / "in", "sub-01_ses-a", "PrismaFit16001", {"scan.dat": b"mri 01"}))
    live.settle("sourcedata/dicoms/a_PrismaFit16001")
    mr = live.merge_request("rawdata", "convert/subject-01_session-a", "dev")
    live.settle("rawdata")
    assert live.failed("rawdata") == []
    bids = live.project("rawdata")
    files = [f["path"] for f in bids.repository_tree(ref="convert/subject-01_session-a",
                                                     recursive=True, get_all=True)]
    assert "sub-01/ses-a/anat/scan.dat" in files and "sub-01/sub-01_sessions.tsv" in files

    # approved and merged by faire's manual job, then released from rel/1.0 and tagged once
    # merged into main
    live.merge_session("rawdata", mr)
    live.settle("rawdata")
    merged = bids.mergerequests.get(mr.iid)
    assert merged.state == "merged", merged.state
    assert "convert/subject-01_session-a" not in [b.name for b in bids.branches.list(
        get_all=True)]
    live.project("study").branches.create({"branch": "rel/1.0", "ref": "dev"})
    rel = live.merge_request("study", "rel/1.0", "main", timeout=3000)
    live.settle("study")
    live.merge("study", rel)
    live.settle("study")
    assert live.failed("study") == []
    for path in ("study", "rawdata"):
        assert "1.0" in live.tags(path), path
    for path in ("release/rawdata", "release/superdataset"):
        tags = {t.name for t in live.gl.projects.get(f"{live.tools.group}/{path}").tags.list()}
        assert "1.0" in tags, path
