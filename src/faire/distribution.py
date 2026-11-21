"""`faire sync`: fulfil a dataset's distributions bound to a lifecycle stage.

Works on a clone of one dataset (or of the superdataset, for each registered dataset), using
the ma-DMP for the distributions. Content goes first, then history, so a pushed commit never
references unavailable content; re-running transfers only what is missing.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from datalad.api import Dataset

from faire import remotes
from faire.plan import Plan
from faire.project import DATASET_ID, INSTANCE


class SyncError(RuntimeError):
    pass


@dataclass(frozen=True)
class Target:
    title: str
    spec: remotes.RemoteSpec


def targets(plan: Plan, ds: Dataset, stage: str, only: str | None = None) -> list[Target]:
    ident, instance = ds.config.get(DATASET_ID), ds.config.get(INSTANCE)
    if ident not in plan.datasets:
        raise SyncError(f"{ds.path} realises no dataset of the plan ({ident!r})")
    dists = [d for d in plan.datasets[ident].distributions if d.stage == stage]
    specs = remotes.specs(dists, instance)
    out = [Target(d.title, s) for d, s in zip(dists, specs, strict=True)]
    if only is not None:
        out = [t for t in out if t.title == only]
        if not out:
            raise SyncError(f"{ident} has no {stage} distribution titled {only!r}")
    return out


def missing_credentials(ds: Dataset, target: Target, platform=None) -> str | None:
    """Name of the environment variable a remote still to be created needs, if absent."""
    if remotes.status(ds, target.spec) != "missing":
        return None
    host = remotes.host_of(platform.url) if platform and hasattr(platform, "url") else None
    variable = remotes.CREDENTIALS.get(remotes.kind(target.spec.url, host))
    return variable if variable and not os.environ.get(variable) else None


def sync(plan: Plan, ds: Dataset, stage: str, refs: list[str], only: str | None = None,
         platform=None) -> list[str]:
    """Push ``refs`` and wanted content to every distribution of ``stage``."""
    found = targets(plan, ds, stage, only)
    for t in found:  # fail before any transfer
        variable = missing_credentials(ds, t, platform)
        if variable:
            raise SyncError(f"distribution {t.title!r} needs {variable} to create its remote")
    lines = []
    remotes.verify_all(ds)
    for t in found:
        spec = t.spec
        state = remotes.status(ds, spec)
        if state != "ok":
            remotes.create(ds, spec, storage_only=stage != "release", platform=platform)
        target = remotes.content_target(ds, spec.name)
        if target in remotes.special_names(ds):
            remotes.verify(ds, target)
        copied = 0
        if ds.config.get(f"remote.{target}.annex-ignore") != "true":
            # from anywhere: a CI clone holds no content; copies go through it
            out = ds.repo.call_annex(["copy", "--auto", "--from-anywhere", "--to", target, "."])
            copied = sum(1 for line in out.splitlines()  # "(to x...)": a real transfer
                         if line.startswith("copy ") and "(to " in line)
        if ds.config.get(f"remote.{spec.name}.url"):  # a git remote, not storage only
            push_history(ds, spec.name, refs)
        lines.append(f"{ds.config.get(DATASET_ID)}: {t.title} ({spec.name}): "
                     f"{copied} files sent")
    return lines


def push_history(ds: Dataset, remote: str, refs: list[str]) -> None:
    """Push ``refs`` and the git-annex branch, merging the remote's git-annex branch first
    (copying content into a git remote updates its location records)."""
    try:
        ds.repo.call_git(["fetch", "-q", remote,
                          f"+refs/heads/git-annex:refs/remotes/{remote}/git-annex"])
        ds.repo.call_annex(["merge"])
    except Exception:
        pass  # new remote without a git-annex branch yet
    ds.repo.call_git(["push", "-q", "--no-verify", remote, *refs, "git-annex"])


def release_refs(tag: str) -> list[str]:
    """Refs pushed to release remotes: the tag, and ``main`` at the tagged commit so that a
    plain clone of the release remote gets the latest release."""
    return [f"refs/tags/{tag}", f"refs/tags/{tag}^{{commit}}:refs/heads/main"]
