"""In-memory platform for tests. Repositories are real bare git repositories on disk."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from datalad.support.gitrepo import GitRepo

from faire.platform import Platform, PlatformError, PullRequest, Repository


@dataclass
class FakeRepo:
    repo: Repository
    protected: set[str] = field(default_factory=set)
    approvals: int | None = None  # None: merge policy never set
    variables: dict[str, str] = field(default_factory=dict)
    pull_requests: list[PullRequest] = field(default_factory=list)
    comments: list[tuple[int, str]] = field(default_factory=list)
    merged: set[int] = field(default_factory=set)


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

    def protect_branch(self, repo: Repository, pattern: str) -> None:
        self.entry(repo).protected.add(pattern)

    def set_merge_policy(self, repo: Repository, approvals: int) -> None:
        self.entry(repo).approvals = approvals

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
        return pr

    def open_pull_requests(self, repo: Repository) -> list[PullRequest]:
        entry = self.entry(repo)
        return [pr for pr in entry.pull_requests if pr.number not in entry.merged]

    def comment(self, repo: Repository, number: int, body: str) -> None:
        self.entry(repo).comments.append((number, body))

    def start_pipeline(self, repo: Repository, ref: str, variables: dict[str, str]) -> str:
        self.entry(repo)
        self.pipelines.append((repo.path, ref, dict(variables)))
        return str(len(self.pipelines))
