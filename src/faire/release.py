"""`faire release`: publish the study from a ``rel/<version>`` branch of the superdataset,
and tag it once everything is reachable.

On ``rel/<version>``: point every registered dataset at its ``dev`` head (once), require each
``sourcedata/`` pointer to be an ancestor of its released source, report derived datasets
lacking samples of their sources, refuse real dates in datasets using fake dates, run release
checks, fulfil ``release`` distributions, and
require every commit and its wanted content to be on every release remote. Nothing is pushed to
a release remote before the checks pass. On ``main`` (after the reviewed merge): tag the
superdataset and every dataset at its released commit, and push the tags.
"""

from __future__ import annotations

import os
import posixpath
from dataclasses import dataclass
from pathlib import Path

from datalad.api import Dataset
from datalad.runner.exception import CommandError
from datalad.support.repodates import check_dates

from faire import remotes
from faire.branches import bump_source, checkout_sources
from faire.distribution import Target, push_history, release_refs, sync, targets
from faire.plan import Plan
from faire.project import DATASET_ID
from faire.state import TRAILER_SAMPLE, git, log, tree
from faire.tasks import run_checks

PREFIX = "rel/"
DATES_REFERENCE = 1514764800  # 2018-01-01, the default of `datalad check-dates`
TRAILER_RELEASE = "faire-release"


class ReleaseError(RuntimeError):
    pass


@dataclass(frozen=True)
class Member:
    """A dataset of the release: its path in the superdataset and released commit."""

    path: str
    commit: str
    ds: Dataset

    @property
    def ident(self) -> str:
        return self.ds.config.get(DATASET_ID) or self.path


def version_of(branch: str) -> str:
    if not branch.startswith(PREFIX):
        raise ReleaseError(f"{branch!r} is not a release branch ({PREFIX}<version>)")
    return branch[len(PREFIX):]


def members(sup: Dataset, commit: str = "HEAD") -> list[Member]:
    """Registered datasets, installed and checked out at their released commits."""
    out = []
    for path, (kind, oid) in sorted(tree(sup, commit).items()):
        if kind != "commit":
            continue
        if not (sup.pathobj / path / ".git").exists():
            sup.get(path, get_data=False, result_renderer="disabled")
        out.append(Member(path, oid, Dataset(sup.pathobj / path)))
    checkout_sources(sup)
    return out


def _released(sup: Dataset, version: str) -> bool:
    return any(t.get(TRAILER_RELEASE) == [version] for _, t in log(sup, "HEAD"))


def bump(sup: Dataset, plan: Plan, version: str) -> list[str]:
    """Point every registered dataset at its ``dev`` head, once per release, and record where
    each can be installed from without the platform (``datalad-url`` in ``.gitmodules``)."""
    if _released(sup, version):
        return []
    lines = []
    paths = [p for p, (kind, _) in tree(sup, "HEAD").items() if kind == "commit"]
    for path in paths:
        if bump_source(sup, path, "dev", save=False):
            lines.append(f"{path} -> dev")
        source = _release_url(plan, Dataset(sup.pathobj / path))
        if source:
            gitmodules = str(sup.pathobj / ".gitmodules")
            sup.repo.call_git(["config", "-f", gitmodules, f"submodule.{path}.datalad-url",
                               source])
    sup.save(path=[".gitmodules", *paths],
             message=f"faire: release {version}\n\n{TRAILER_RELEASE}: {version}",
             result_renderer="disabled")
    return lines


def _release_url(plan: Plan, ds: Dataset) -> str | None:
    ident = ds.config.get(DATASET_ID)
    if ident not in plan.datasets:
        return None
    for d in plan.datasets[ident].distributions_at("release"):
        url = d.access_url
        if url.startswith("ria+"):
            return f"{url}#{ds.id}"
        if remotes.kind(url, None) == "plain":
            return remotes.plain_target(url)
        return url
    return None


def ancestry(sup: Dataset, found: list[Member]) -> list[str]:
    """Pointers of registered datasets to registered sources that are not ancestors of the
    released source commit."""
    by_id = {m.ident: m for m in found}
    errors = []
    for m in found:
        for path, (kind, oid) in tree(m.ds, m.commit).items():
            parts = path.split("/")
            if kind != "commit" or parts[0] != "sourcedata" or len(parts) != 2:
                continue
            source = by_id.get(parts[1])
            if source is None:
                continue  # streams are not released
            try:
                git(source.ds, "merge-base", "--is-ancestor", oid, source.commit)
            except CommandError:
                errors.append(f"{m.ident}: {path} at {oid[:8]} is not an ancestor of the "
                              f"released {source.ident} ({source.commit[:8]})")
    return errors


def _samples(ds: Dataset, commit: str) -> set[str]:
    return {s for _, t in log(ds, commit) for s in t.get(TRAILER_SAMPLE, [])}


def lagging(found: list[Member]) -> list[str]:
    """Derived datasets lacking samples their released sources have."""
    by_id = {m.ident: m for m in found}
    lines = []
    for m in found:
        for path, (kind, _) in tree(m.ds, m.commit).items():
            parts = path.split("/")
            if kind == "commit" and parts[0] == "sourcedata" and len(parts) == 2 \
                    and parts[1] in by_id:
                source = by_id[parts[1]]
                missing = sorted(_samples(source.ds, source.commit) - _samples(m.ds, m.commit))
                if missing:
                    lines.append(f"{m.ident} lacks samples of {source.ident}: "
                                 + ", ".join(missing))
    return lines


def fake_dated(ds: Dataset, commit: str) -> bool:
    """Whether the dataset's committed configuration at ``commit`` enables fake dates."""
    try:
        value = git(ds, "config", "--blob", f"{commit}:.datalad/config", "--bool",
                    "--get", "datalad.fake-dates")
    except CommandError:  # no such file or key
        return False
    return value.strip() == "true"


def real_dates(sup: Dataset, found: list[Member]) -> list[str]:
    """Dates after the reference in fake-dated datasets: commits reachable from the released
    commit, annotated tags and the git-annex branch (`datalad check-dates`)."""
    errors = []
    for ds, commit in _all(sup, found):
        if not fake_dated(ds, commit):
            continue
        report = check_dates(ds.repo, DATES_REFERENCE, revs=[commit])
        for oid, info in sorted(report["objects"].items()):
            what = info.get("filename") or info["type"]
            errors.append(f"{ds.config.get(DATASET_ID) or ds.path}: real date in {what} "
                          f"{oid[:8]}")
    return errors


def release_checks(found: list[Member]) -> list[str]:
    failures = []
    for m in found:
        for r in run_checks(m.ds, "release"):
            if r.blocking and not r.passed:
                failures.append(f"{m.ident}: release check {r.name} failed: {r.output}")
    return failures


def _all(sup: Dataset, found: list[Member], head: str = "HEAD") -> list[tuple[Dataset, str]]:
    return [(m.ds, m.commit) for m in found] + [(sup, sup.repo.call_git(
        ["rev-parse", head]).strip())]


def unreachable(plan: Plan, sup: Dataset, found: list[Member], ref: str,
                head: str = "HEAD") -> list[str]:
    """Commits or wanted content missing from a release remote (``ref``: the pushed branch;
    ``head``: the superdataset commit released there)."""
    errors = []
    for ds, commit in _all(sup, found, head):
        ident = ds.config.get(DATASET_ID)
        for t in targets(plan, ds, "release"):
            _attach(ds, t)
            errors += _missing(ds, ident, t, commit, ref)
    return errors


def _attach(ds: Dataset, t: Target) -> None:
    """Configure a release remote in this clone and learn what it holds."""
    if remotes.status(ds, t.spec) != "ok":
        remotes.create(ds, t.spec, storage_only=False)
    name = t.spec.name
    if ds.config.get(f"remote.{name}.url"):
        try:
            ds.repo.call_git(["fetch", "-q", name,
                              f"+refs/heads/git-annex:refs/remotes/{name}/git-annex"])
            ds.repo.call_annex(["merge"])
        except CommandError:
            pass  # nothing pushed there yet


def _missing(ds: Dataset, ident: str, t: Target, commit: str, ref: str) -> list[str]:
    name = t.spec.name
    out = []
    if ds.config.get(f"remote.{name}.url"):
        try:
            heads = ds.repo.call_git(["ls-remote", name, ref])
        except CommandError:
            heads = ""
        if commit not in heads:
            out.append(f"{ident}: {t.title} lacks commit {commit[:8]} on {ref}")
    target = remotes.content_target(ds, name)
    if ds.config.get(f"remote.{target}.annex-ignore") != "true":
        left = ds.repo.call_annex(["find", f"--branch={commit}", "--not", f"--in={target}",
                                   f"--want-get-by={target}"])
        if left.strip():
            out.append(f"{ident}: {t.title} lacks content: "
                       + ", ".join(left.split()[:5]))
    return out


def release(sup: Dataset, plan: Plan, platform=None, repository=None) -> list[str]:
    """Run the release on the checked-out ``rel/<version>`` branch."""
    branch = sup.repo.get_active_branch() or ""
    version = version_of(branch)
    lines = bump(sup, plan, version)
    found = members(sup)
    errors = ancestry(sup, found)
    if errors:
        raise ReleaseError("\n".join(errors))
    lines += lagging(found)
    errors = real_dates(sup, found)
    if errors:
        raise ReleaseError("\n".join(errors))
    failures = release_checks(found)
    if failures:
        raise ReleaseError("\n".join(failures))
    ref = f"refs/heads/{branch}"
    for ds, commit in _all(sup, found):
        if targets(plan, ds, "release"):
            lines += sync(plan, ds, "release", [f"{commit}:{ref}"], platform=platform)
    errors = unreachable(plan, sup, found, ref)
    if errors:
        raise ReleaseError("\n".join(errors))
    # starts a pipeline: it re-runs the release (a no-op now) so that the head of the pull
    # request has a passing pipeline
    sup.repo.call_git(["push", "-q", "--no-verify", "origin", f"HEAD:{ref}"])
    if platform:
        platform.ensure_pull_request(repository, branch, "main", f"Release {version}",
                                     "\n".join(lines) or f"Release {version}.")
    lines.append(f"{version} is reachable on every release remote")
    return lines


def released_version(sup: Dataset) -> str:
    for _, t in log(sup, "HEAD"):
        if TRAILER_RELEASE in t:
            return t[TRAILER_RELEASE][0]
    raise ReleaseError("no release was merged into this branch")


def tag(sup: Dataset, plan: Plan) -> list[str]:
    """On ``main`` after the merge: tag every dataset at its released commit and the
    superdataset, then push the tags (and ``main`` at the tag) to origin and release remotes."""
    version = released_version(sup)
    ref = f"{PREFIX}{version}"
    try:
        sup.repo.call_git(["fetch", "-q", "origin",
                           f"+refs/heads/{ref}:refs/remotes/origin/{ref}"])
        released = f"refs/remotes/origin/{ref}"
    except CommandError:  # the branch was deleted with the merge: its head is merged in
        released = "HEAD^2"
    if git(sup, "rev-parse", "HEAD^{tree}") != git(sup, "rev-parse", released + "^{tree}"):
        raise ReleaseError(f"main differs from the released {ref}; release again")
    found = members(sup)
    errors = unreachable(plan, sup, found, f"refs/heads/{ref}", released)
    if errors:
        raise ReleaseError("\n".join(errors))
    lines = []
    for ds, commit in _all(sup, found):
        if not _has_tag(ds, version):
            ds.repo.call_git(["tag", "-a", "-m", f"Release {version}", version, commit])
        skip = ["-o", "ci.skip"] if os.environ.get("GITLAB_CI") else []  # tags run nothing
        ds.repo.call_git(["push", "-q", "--no-verify", *skip, _home(sup, ds),
                          f"refs/tags/{version}"])
        for t in targets(plan, ds, "release"):
            if ds.config.get(f"remote.{t.spec.name}.url"):
                push_history(ds, t.spec.name, release_refs(version))
        lines.append(f"tagged {ds.config.get(DATASET_ID)} {version} at {commit[:8]}")
    return lines


def _home(sup: Dataset, ds: Dataset) -> str:
    """Remote of ``ds`` on the platform: the superdataset's origin with the relative URL
    recorded in `.gitmodules` (a subdataset may have been installed from a release remote)."""
    if ds.path == sup.path:
        return "origin"
    path = Path(ds.path).relative_to(sup.path).as_posix()
    rel = sup.repo.call_git(["config", "-f", ".gitmodules", f"submodule.{path}.url"]).strip()
    if not rel.startswith("."):
        return rel
    base = sup.config.get("remote.origin.url")
    scheme, sep, rest = base.rpartition("://")
    return f"{scheme}{sep}{posixpath.normpath(posixpath.join(rest, rel))}"


def _has_tag(ds: Dataset, name: str) -> bool:
    return bool(ds.repo.call_git(["tag", "--list", name]).strip())
