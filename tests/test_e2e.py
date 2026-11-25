"""End-to-end run on a fake platform, driven the way CI drives faire.

Every pipeline is a fresh clone of one repository on one branch, running `faire plan
--ci-render gitlab` and then the jobs it rendered, each through the command line. A trigger job
runs the downstream pipeline; a pushed session branch gets its own pipeline; a wave is followed
by a new pipeline on the same branch until the branch settles.
"""

import shlex
from pathlib import Path

import pytest
import yaml
from click.testing import CliRunner
from datalad.api import Dataset, clone

from conftest import by_id, git_template, make_env, reference_doc, write_doc
from faire import cli
from faire.indexing import Indexer
from faire.plan import Plan
from faire.platform.fake import FakePlatform
from faire.project import Project
from test_tasks import received

GROUP = "lab/study"

# A derived dataset whose primary rule reads the standard dataset (toy image: `copy`).
DERIVED = {
    "copier.yml": ("collection_url:\n  type: str\n_answers_file: .copier-answers.yml\n"),
    "{{ _copier_conf.answers_file }}.jinja": "{{ _copier_answers|to_nice_yaml }}",
    "README.md.jinja": "# {{ title }}\n",
    ".gitattributes": "* annex.largefiles=(not(mimetype=text/*))\n",
    ".gitlab-ci.yml": (Path(__file__).parents[1] / "templates/toy-standard/.gitlab-ci.yml")
    .read_text(),
    ".datalad/config.jinja": (
        '[faire "collection.toy"]\n\turl = {{ collection_url }}\n\tpath = code/containers\n'
        "\trevision = v1\n"
        '[datalad "containers.derive"]\n\timage = code/containers/images/toy-1.0.sh\n'
        "\tcmdexec = sh {img} {cmd}\n\tfaire-sourcedata = bids\n"
        "\tfaire-input = sourcedata/bids/sub-{subject}/ses-{session}/anat/*.dat\n"
        "\tfaire-output = sub-{subject}/ses-{session}/derived\n"
        "\tfaire-cmd = copy sub-{subject}/ses-{session}/derived {inputs}\n"
    ),
}


class CI:
    """Runs pipelines of the fake platform's repositories, recording what happened."""

    def __init__(self, platform: FakePlatform, root: Path, monkeypatch):
        self.platform, self.root, self.mp = platform, root, monkeypatch
        self.count = 0
        self.log: list[str] = []
        self.failed_checks: dict[tuple[str, str], list[str]] = {}
        self.current: str | None = None
        monkeypatch.setattr(cli, "_platform_from_env", lambda: (
            platform, platform.get_repository(self.current)))

    def clone(self, path: str, branch: str) -> Dataset:
        self.count += 1
        repo = self.platform.get_repository(f"{GROUP}/{path}")
        ds = clone(source=repo.url, path=str(self.root / f"ci{self.count}"),
                   result_renderer="disabled")
        ds.repo.call_git(["checkout", "-q", "-B", branch, f"refs/remotes/origin/{branch}"])
        return ds

    def faire(self, ds: Dataset, command: str) -> tuple[int, str]:
        self.mp.chdir(ds.path)
        result = CliRunner().invoke(cli.main, shlex.split(command)[1:])
        if result.exception and not isinstance(result.exception, SystemExit):
            raise result.exception
        return result.exit_code, result.output

    def pipeline(self, path: str, branch: str, max_waves: int = 6) -> None:
        """Run the pipelines of ``branch`` until one changes nothing on it."""
        for _ in range(max_waves):
            if not self._once(path, branch):
                return
        raise AssertionError(f"{path} {branch} did not settle")

    def _once(self, path: str, branch: str) -> bool:
        """One pipeline; True when the branch moved (a further pipeline would follow)."""
        ds = self.clone(path, branch)
        self.current = f"{GROUP}/{path}"
        self.mp.setenv("CI_PROJECT_PATH", self.current)
        self.mp.setenv("CI_COMMIT_SHA", ds.repo.get_hexsha())
        code, out = self.faire(ds, "faire plan --ci-render gitlab")
        assert code == 0, out
        jobs = {k: v for k, v in yaml.safe_load(out).items() if k not in ("stages", "default")}
        self.log.append(f"{path} {branch}: {', '.join(jobs)}")
        before = self._head(path, branch)
        sessions = {s: self._head(path, s) for s in self._sessions(path)}
        failed = []
        for stage in ("jobs", "tasks", "status", "checks", "downstream"):
            for name, job in jobs.items():
                if job["stage"] != stage or job.get("when") == "manual":
                    continue
                if "trigger" in job:
                    project = job["trigger"]["project"].removeprefix(GROUP + "/")
                    self.pipeline(project, job["trigger"]["branch"])
                    continue
                for command in job["script"]:
                    if command.startswith("echo"):
                        continue
                    work = self.clone(path, branch)  # every job is a fresh checkout
                    code, out = self.faire(work, command.replace(" --next-wave", ""))
                    if code and stage == "checks":
                        failed.append(name)
                    else:
                        assert code == 0, f"{command}: {out}"
        if any(j["stage"] == "checks" for j in jobs.values()):
            self.failed_checks[(path, branch)] = failed
        for session in self._sessions(path):  # pushed by update: their own pipelines
            if session != branch and self._head(path, session) != sessions.get(session):
                self.pipeline(path, session)
        return branch != "base" and self._head(path, branch) != before

    def _repo(self, path: str):
        return self.platform.get_repository(f"{GROUP}/{path}")

    def _head(self, path: str, branch: str) -> str:
        return Dataset(self._repo(path).url).repo.call_git(
            ["rev-parse", "--verify", "-q", f"refs/heads/{branch}"]).strip()

    def _sessions(self, path: str) -> list[str]:
        out = Dataset(self._repo(path).url).repo.call_git(
            ["for-each-ref", "--format=%(refname:strip=2)", "refs/heads/convert"])
        return out.split()

    def mark_missing(self, path: str, branch: str, stream: str) -> None:
        """The reviewer's manual job."""
        ds = self.clone(path, branch)
        self.current = f"{GROUP}/{path}"
        code, out = self.faire(ds, f"faire mark '{stream}=missing' --by reviewer")
        assert code == 0, out
        self.pipeline(path, branch)

    def merge(self, path: str, branch: str, target: str) -> None:
        """A reviewer approves the session's pull request and runs the manual merge job of
        its settled pipeline."""
        repo = self._repo(path)
        [pr] = [pr for pr in self.platform.open_pull_requests(repo)
                if pr.source == branch and pr.target == target]
        self.platform.approve(repo, pr.number, "reviewer")
        ds = self.clone(path, branch)
        self.current = f"{GROUP}/{path}"
        self.mp.setenv("CI_PROJECT_PATH", self.current)
        self.mp.setenv("CI_COMMIT_SHA", ds.repo.get_hexsha())
        jobs = yaml.safe_load(self.faire(ds, "faire plan --ci-render gitlab")[1])
        assert jobs["merge"]["needs"] == [f"check-{c}" for c in self.blocking(path, branch)]
        code, out = self.faire(ds, "faire merge")
        assert code == 0, out
        assert pr not in self.platform.open_pull_requests(repo)
        self.pipeline(path, target)

    def blocking(self, path: str, branch: str) -> list[str]:
        """Blocking checks of the last pipeline of ``branch``, all of which passed."""
        assert self.failed_checks[(path, branch)] == []
        ds = self.clone(path, branch)
        jobs = yaml.safe_load(self.faire(ds, "faire plan --ci-render gitlab")[1])
        return [k.removeprefix("check-") for k, v in jobs.items()
                if k.startswith("check-") and not v["allow_failure"]]

    def platform_merge(self, path: str, branch: str, target: str) -> None:
        """A reviewer merges the pull request on the platform (the release into main)."""
        repo = self._repo(path)
        assert any(pr.source == branch and pr.target == target
                   for pr in self.platform.open_pull_requests(repo)), branch
        ds = self.clone(path, target)
        ds.repo.call_git(["merge", "-q", "--no-ff", "--no-edit",
                          f"refs/remotes/origin/{branch}"])
        ds.repo.call_git(["push", "-q", "--no-verify", "origin", target,
                          f":refs/heads/{branch}"])
        self.pipeline(path, target)


@pytest.fixture
def study(tmp_path, reference, templates_root, monkeypatch):
    env = make_env(tmp_path, templates_root)
    doc = reference_doc(env, reference)
    ria = f"ria+file://{env.root / 'ria'}"
    release = f"ria+file://{env.root / 'release-ria'}"
    derived = git_template(env.root / "tpl-derived", DERIVED)
    by_id(doc, "study")["distribution"] = [env.dist("Archive", "release", release)]
    by_id(doc, "bids")["distribution"] += [
        env.dist("Shared", "accepted", str(env.root / "shared" / "bids")),
        env.dist("Archive", "release", release),
    ]
    doc["dmp"]["dataset"].append(env.dataset(
        "fmriprep", "derived", derived, path="derivatives/fmriprep", sources=["bids"],
        data={"collection_url": reference.collection},
        distributions=[env.dist("Site storage", "collection", ria),
                       env.dist("Mirror", "release", str(env.root / "mirror" / "fmriprep"))]))
    platform = FakePlatform(env.root / "platform", group=GROUP)
    proj = Project(Plan.from_document(doc), write_doc(env.root / "dmp.json", doc),
                   env.root / "work", platform)
    report = proj.init()
    assert report.differences == []
    return env, proj, platform, CI(platform, env.root / "ci", monkeypatch)


def index(proj, ci, stream, name, instrument, files):
    instance = f"sourcedata/{stream}/{proj.plan.datasets[stream].instruments[0].instance}"
    Indexer(Dataset(proj.path(instance))).index(
        received(ci.root / f"in-{stream}-{name}", name, instrument, files))
    ci.pipeline(instance, "dev")


def test_study_from_index_to_release(study):
    env, proj, platform, ci = study
    s1, s2 = "subject-01_session-a", "subject-02_session-a"
    bids = platform.get_repository(f"{GROUP}/rawdata")

    # MRI arrives for two sessions: bids opens a session for each and converts them
    for subject in ("01", "02"):
        index(proj, ci, "dicoms", f"sub-{subject}_ses-a", "PrismaFit16001",
              {"scan.dat": f"mri {subject}".encode()})
    assert {pr.source for pr in platform.open_pull_requests(bids)} == {
        f"convert/{s1}", f"convert/{s2}"}
    assert ci.failed_checks[("rawdata", f"convert/{s1}")] == ["check-completeness"]

    # physio arrives later for subject 01 only: base is merged into the waiting sessions
    index(proj, ci, "physio", "sub-01_ses-a", "Biopac01", {"rec.log": b"physio 01"})
    assert ci.failed_checks[("rawdata", f"convert/{s1}")] == [], "\n".join(ci.log)
    assert ci.failed_checks[("rawdata", f"convert/{s2}")] == ["check-completeness"]

    # the reviewer declares physio missing for subject 02
    ci.mark_missing("rawdata", f"convert/{s2}", "physio")
    assert ci.failed_checks[("rawdata", f"convert/{s2}")] == []

    # both sessions are merged; each merge cascades to the derivative
    for label in (s1, s2):
        ci.merge("rawdata", f"convert/{label}", "dev")
    fmriprep = platform.get_repository(f"{GROUP}/derivatives/fmriprep")
    assert {pr.source for pr in platform.open_pull_requests(fmriprep)} >= {
        f"convert/{s1}", f"convert/{s2}"}
    for label in (s1, s2):
        assert ci.failed_checks[("derivatives/fmriprep", f"convert/{label}")] == []
        ci.merge("derivatives/fmriprep", f"convert/{label}", "dev")

    # accepted data reached the shared remote
    shared = Dataset(env.root / "shared" / "bids")
    assert "sub-01/ses-a/anat/scan.dat" in shared.repo.call_git(
        ["ls-tree", "-r", "--name-only", "dev"])

    # release: rel/1.0 from the superdataset's dev, then the reviewed merge into main
    sup = ci.clone("study", "dev")
    sup.repo.call_git(["push", "-q", "--no-verify", "origin", "dev:refs/heads/rel/1.0"])
    ci.pipeline("study", "rel/1.0")
    superdataset = platform.get_repository(f"{GROUP}/study")
    assert any(pr.source == "rel/1.0" and pr.target == "main"
               for pr in platform.open_pull_requests(superdataset))
    ci.platform_merge("study", "rel/1.0", "main")

    for path in ("study", "rawdata", "derivatives/fmriprep"):
        tags = Dataset(platform.get_repository(f"{GROUP}/{path}").url).repo.call_git(["tag"])
        assert "1.0" in tags.split(), path
    mirror = Dataset(env.root / "mirror" / "fmriprep")
    assert "1.0" in mirror.repo.call_git(["tag"]).split()
    released = mirror.repo.call_git(["ls-tree", "-r", "--name-only", "1.0"]).split()
    assert {f"sub-{s}/ses-a/derived/scan.dat" for s in ("01", "02")} <= set(released)
    print("\n".join(ci.log))
