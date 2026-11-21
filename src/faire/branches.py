"""Session branches and source pointers of a dataset clone."""

from __future__ import annotations

from datalad.api import Dataset

from faire.state import base_of, branch_for


def bump_source(ds: Dataset, sub: str, ref: str = "dev", save: bool = True) -> bool:
    """Point subdataset ``sub`` at its origin's ``ref``; True when the pointer moved."""
    path = ds.pathobj / sub
    if not (path / ".git").exists():
        ds.get(sub, get_data=False, result_renderer="disabled")
    source = Dataset(path)
    source.repo.call_git(["fetch", "-q", "origin"])
    target = source.repo.call_git(["rev-parse", f"refs/remotes/origin/{ref}"]).strip()
    if source.repo.get_hexsha() == target:
        return False
    source.repo.call_git(["checkout", "-q", "--detach", target])
    if save:
        ds.save(sub, message=f"faire: update {sub} to {ref}", result_renderer="disabled")
    return True


def start_session(ds: Dataset, label: str, pilot: bool = False) -> str:
    """Create and check out the session branch from the base branch on origin."""
    branch = branch_for(label, pilot)
    base = base_of(branch)
    ds.repo.call_git(["fetch", "-q", "origin"])
    ds.repo.call_git(["checkout", "-q", "-b", branch, f"refs/remotes/origin/{base}"])
    return branch
