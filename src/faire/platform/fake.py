"""In-memory platform for tests. Repositories are real bare git repositories on disk."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from datalad.runner.exception import CommandError
from datalad.support.gitrepo import GitRepo

from faire.platform import Platform, PlatformError, PullRequest, Repository


@dataclass
class FakeRepo:
    repo: Repository
    protected: set[str] = field(default_factory=set)
    merge_policy: bool = False
    unmergeable: set[str] = field(default_factory=set)  # merged only by faire
    variables: dict[str, str] = field(default_factory=dict)
    pull_requests: list[PullRequest] = field(default_factory=list)
    comments: list[tuple[int, str]] = field(default_factory=list)
    merged: set[int] = field(default_factory=set)
    approved: dict[int, list[str]] = field(default_factory=dict)
    opened_empty: dict[int, str] = field(default_factory=dict)  # source head, if in target


class FakePlatform(Platform):
    name = "fake"

    def __init__(self, root: str | Path, group: str = "lab/study", subgroups: bool = True):
        super().__init__(group)
        self.root = Path(root)
        self.subgroups = subgroups
        self.repos: dict[str, FakeRepo] = {}
        self.pipelines: list[tuple[str, str, dict[str, str]]] = []

    def get_repository(self, path: str) -> Repository | None:
        entry = self.repos.get(path)
        return entry.repo if entry else None

    def ensure_repository(self, path: str) -> Repository:
        existing = self.get_repository(path)
        if existing:
            return existing
        where = self.root / f"{path}.git"
        where.parent.mkdir(parents=True, exist_ok=True)
        GitRepo(str(where), create=True, bare=True)
        repo = Repository(path, str(where))
        self.repos[path] = FakeRepo(repo)
        return repo

    def list_repositories(self) -> list[Repository]:
        return [e.repo for p, e in self.repos.items() if p.startswith(self.group + "/")]

    def entry(self, repo: Repository) -> FakeRepo:
        try:
            return self.repos[repo.path]
        except KeyError:
            raise PlatformError(f"unknown repository {repo.path!r}") from None

    def protect_branch(self, repo: Repository, pattern: str, mergeable: bool = True) -> None:
        entry = self.entry(repo)
        entry.protected.add(pattern)
        if mergeable:
            entry.unmergeable.discard(pattern)
        else:
            entry.unmergeable.add(pattern)

    def set_merge_policy(self, repo: Repository) -> None:
        self.entry(repo).merge_policy = True

    def set_variable(self, repo: Repository, key: str, value: str) -> None:
        self.entry(repo).variables[key] = value

    def get_variables(self, repo: Repository) -> dict[str, str]:
        return dict(self.entry(repo).variables)

    def ensure_pull_request(
        self, repo: Repository, source: str, target: str, title: str, description: str,
        draft: bool = False,
    ) -> PullRequest:
        entry = self.entry(repo)
        for pr in self.open_pull_requests(repo):
            if (pr.source, pr.target) == (source, target):
                return pr
        number = len(entry.pull_requests) + 1
        pr = PullRequest(number, source, target, title, description, draft,
                         f"fake://{repo.path}/pr/{number}")
        entry.pull_requests.append(pr)
        if self._contains(repo, target, source):  # nothing to merge yet
            entry.opened_empty[number] = self._head(repo, source)
        return pr

    def open_pull_requests(self, repo: Repository) -> list[PullRequest]:
        entry = self.entry(repo)
        for pr in entry.pull_requests:  # like a forge: merged once the target contains it
            if (pr.number not in entry.merged
                    and entry.opened_empty.get(pr.number) != self._head(repo, pr.source)
                    and self._contains(repo, pr.target, pr.source)):
                entry.merged.add(pr.number)
        return [pr for pr in entry.pull_requests if pr.number not in entry.merged]

    @staticmethod
    def _head(repo: Repository, branch: str) -> str | None:
        try:
            return GitRepo(repo.url).call_git(["rev-parse", f"refs/heads/{branch}"]).strip()
        except CommandError:
            return None

    @staticmethod
    def _contains(repo: Repository, target: str, source: str) -> bool:
        try:
            git = GitRepo(repo.url)
            git.call_git(["merge-base", "--is-ancestor", f"refs/heads/{source}",
                          f"refs/heads/{target}"])
            return True
        except CommandError:
            return False

    def comment(self, repo: Repository, number: int, body: str) -> None:
        self.entry(repo).comments.append((number, body))

    def delete_branch(self, repo: Repository, branch: str) -> None:
        self.open_pull_requests(repo)  # a forge records merges before the branch goes
        GitRepo(self.entry(repo).repo.url).call_git(["update-ref", "-d", f"refs/heads/{branch}"])

    def approvers(self, repo: Repository, number: int) -> list[str]:
        return list(self.entry(repo).approved.get(number, []))

    def approve(self, repo: Repository, number: int, user: str) -> None:
        """What a reviewer does on the platform."""
        self.entry(repo).approved.setdefault(number, []).append(user)

    def start_pipeline(self, repo: Repository, ref: str, variables: dict[str, str]) -> str:
        self.entry(repo)
        self.pipelines.append((repo.path, ref, dict(variables)))
        return str(len(self.pipelines))
