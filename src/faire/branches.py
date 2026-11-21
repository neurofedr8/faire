"""Session branches and source pointers of a dataset clone."""

from __future__ import annotations

from datalad.api import Dataset

from faire.state import BASE, branch_for, tree


def bump_source(ds: Dataset, sub: str, ref: str = "dev", save: bool = True) -> bool:
    """Point subdataset ``sub`` at its origin's ``ref``; True when the recorded pointer moves.

    The subdataset is checked out at the target either way, so a following save records it.
    """
    path = ds.pathobj / sub
    if not (path / ".git").exists():
        ds.get(sub, get_data=False, result_renderer="disabled")
    source = Dataset(path)
    source.repo.call_git(["fetch", "-q", "origin"])
    target = source.repo.call_git(["rev-parse", f"refs/remotes/origin/{ref}"]).strip()
    if source.repo.get_hexsha() != target:
        source.repo.call_git(["checkout", "-q", "--detach", target])
    recorded = tree(ds, "HEAD").get(sub, ("", ""))[1]
    if recorded == target:
        return False
    if save:
        ds.save(sub, message=f"faire: update {sub} to {ref}", result_renderer="disabled")
    return True


def start_session(ds: Dataset, label: str, pilot: bool = False) -> str:
    """Create and check out the session branch from ``base`` on origin."""
    branch = branch_for(label, pilot)
    ds.repo.call_git(["fetch", "-q", "origin"])
    ds.repo.call_git(["checkout", "-q", "-b", branch, f"refs/remotes/origin/{BASE}"])
    return branch


def checkout_sources(ds: Dataset) -> None:
    """Check installed subdatasets out at the commits recorded in HEAD.

    Git leaves subdatasets where they are when the branch changes; commands that read their
    files must see the branch's versions.
    """
    for path, (kind, oid) in tree(ds, "HEAD").items():
        sub = ds.pathobj / path
        if kind != "commit" or not (sub / ".git").exists():
            continue
        source = Dataset(sub)
        if source.repo.get_hexsha() == oid:
            continue
        try:
            source.repo.call_git(["cat-file", "-e", f"{oid}^{{commit}}"])
        except Exception:
            source.repo.call_git(["fetch", "-q", "origin"])
        source.repo.call_git(["checkout", "-q", "--detach", oid])
