"""Everything faire asks of a DevOps platform, and nothing else.

Supporting another platform means implementing :class:`Platform`.
"""

from __future__ import annotations

import posixpath
from abc import ABC, abstractmethod
from contextlib import AbstractContextManager, nullcontext
from dataclasses import dataclass


class PlatformError(RuntimeError):
    pass


@dataclass(frozen=True)
class Repository:
    path: str  # full path on the platform, e.g. `lab/studyx/derivatives/fmriprep`
    url: str  # where git clones and pushes


@dataclass(frozen=True)
class PullRequest:
    number: int
    source: str
    target: str
    title: str
    description: str
    draft: bool = False
    url: str = ""


class Platform(ABC):
    name = "platform"
    #: True when the platform nests groups; otherwise `a/b` is stored as `a.b` under the root group
    subgroups = True

    def __init__(self, group: str):
        self.group = group.strip("/")

    def location(self, logical: str) -> str:
        """Full platform path of the repository at logical path ``logical`` (slash-separated)."""
        if self.subgroups:
            return f"{self.group}/{logical}"
        return f"{self.group}/{logical.replace('/', '.')}"

    def relative_url(self, own: str, target: str) -> str:
        """URL of ``target`` relative to the URL of ``own`` (both logical paths)."""
        return relative_url(self.location(own), self.location(target))

    def git_auth(self) -> AbstractContextManager[None]:
        """Within the block, git authenticates to this platform."""
        return nullcontext()

    @abstractmethod
    def ensure_repository(self, path: str) -> Repository:
        """Create the repository and its parent groups if missing; return it."""

    @abstractmethod
    def get_repository(self, path: str) -> Repository | None: ...

    @abstractmethod
    def list_repositories(self) -> list[Repository]:
        """Every repository under the root group, at any depth."""

    @abstractmethod
    def protect_branch(self, repo: Repository, pattern: str) -> None:
        """Only merged pull requests or maintainers (and the automation identity) may change
        branches matching ``pattern``; their pipelines see protected CI variables."""

    @abstractmethod
    def set_merge_policy(self, repo: Repository, approvals: int) -> None:
        """Require ``approvals`` human approvals and a passing pipeline to merge, and allow
        only merge commits (never squash): run records in commits must survive."""

    @abstractmethod
    def set_variable(self, repo: Repository, key: str, value: str) -> None: ...

    @abstractmethod
    def get_variables(self, repo: Repository) -> dict[str, str]: ...

    @abstractmethod
    def ensure_pull_request(
        self, repo: Repository, source: str, target: str, title: str, description: str,
        draft: bool = False,
    ) -> PullRequest:
        """Open a pull request, or return the open one for the same branches."""

    @abstractmethod
    def open_pull_requests(self, repo: Repository) -> list[PullRequest]: ...

    @abstractmethod
    def comment(self, repo: Repository, number: int, body: str) -> None: ...

    @abstractmethod
    def start_pipeline(self, repo: Repository, ref: str, variables: dict[str, str]) -> str:
        """Start a pipeline on ``ref``; return its identifier."""


def relative_url(own: str, target: str) -> str:
    """Relative submodule URL from repository path ``own`` to repository path ``target``.

    Git resolves a relative submodule URL against the superproject's remote URL taken as a
    directory, so ``../x`` from ``g/a`` is ``g/x``.
    """
    rel = posixpath.relpath(target, own)
    return rel if rel.startswith("..") else f"./{rel}"
