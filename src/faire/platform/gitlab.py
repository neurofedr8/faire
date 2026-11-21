"""GitLab implementation of the platform interface, on python-gitlab."""

from __future__ import annotations

import time
from typing import Any

import gitlab
from gitlab import exceptions as gle

from faire.platform import Platform, PlatformError, PullRequest, Repository, credentials

MAINTAINER = 40  # GitLab access level
APPROVAL_RULE = "faire: human approval"


class GitLabPlatform(Platform):
    name = "gitlab"

    def __init__(self, url: str, token: str, group: str, session: Any = None):
        super().__init__(group)
        self.url, self._token = url, token
        self.gl = gitlab.Gitlab(url, private_token=token, session=session)

    def git_auth(self):
        return credentials.git_auth(self.url, self._token)

    @staticmethod
    def _wrap(exc: Exception) -> PlatformError:
        return PlatformError(f"GitLab: {exc}")

    def _get(self, manager: Any, path: str) -> Any:
        try:
            return manager.get(path)
        except gle.GitlabGetError as exc:
            if exc.response_code == 404:
                return None
            raise self._wrap(exc) from exc

    def _ensure_group(self, path: str) -> Any:
        parent = None
        parts = path.split("/")
        for i, part in enumerate(parts):
            group = self._get(self.gl.groups, "/".join(parts[: i + 1]))
            if group is None:
                payload: dict[str, Any] = {"name": part, "path": part}
                if parent is not None:
                    payload["parent_id"] = parent.id
                try:
                    group = self.gl.groups.create(payload)
                except gle.GitlabError as exc:
                    raise self._wrap(exc) from exc
            parent = group
        return parent

    def get_repository(self, path: str) -> Repository | None:
        project = self._get(self.gl.projects, path)
        return Repository(path, project.http_url_to_repo) if project else None

    def ensure_repository(self, path: str) -> Repository:
        existing = self.get_repository(path)
        if existing:
            return existing
        group_path, name = path.rsplit("/", 1)
        group = self._ensure_group(group_path)
        try:
            project = self.gl.projects.create(
                {"name": name, "path": name, "namespace_id": group.id}
            )
        except gle.GitlabError as exc:
            raise self._wrap(exc) from exc
        return Repository(path, project.http_url_to_repo)

    def list_repositories(self) -> list[Repository]:
        group = self._get(self.gl.groups, self.group)
        if group is None:
            return []
        try:
            found = group.projects.list(include_subgroups=True, get_all=True)
        except gle.GitlabError as exc:
            raise self._wrap(exc) from exc
        return [Repository(p.path_with_namespace, p.http_url_to_repo) for p in found]

    def _project(self, repo: Repository) -> Any:
        project = self._get(self.gl.projects, repo.path)
        if project is None:
            raise PlatformError(f"unknown repository {repo.path!r}")
        return project

    def protect_branch(self, repo: Repository, pattern: str) -> None:
        project = self._project(repo)
        payload = {"name": pattern, "push_access_level": MAINTAINER,
                   "merge_access_level": MAINTAINER, "allow_force_push": False}
        for attempt in range(5):  # GitLab protects the first pushed branch itself, shortly after
            try:
                project.protectedbranches.create(payload)
                return
            except gle.GitlabCreateError as exc:
                if exc.response_code != 409 and "already" not in str(exc.error_message):
                    raise self._wrap(exc) from exc
            try:
                project.protectedbranches.get(pattern).delete()
            except gle.GitlabGetError:
                time.sleep(1)
            if attempt == 4:
                raise PlatformError(f"GitLab: cannot protect {pattern!r} on {repo.path}")

    def set_merge_policy(self, repo: Repository, approvals: int) -> None:
        project = self._project(repo)
        project.only_allow_merge_if_pipeline_succeeds = True
        project.allow_merge_on_skipped_pipeline = False
        project.merge_method = "merge"
        project.squash_option = "never"
        try:
            project.save()
            if approvals:
                names = {r.name for r in project.approvalrules.list(get_all=True)}
                if APPROVAL_RULE not in names:
                    project.approvalrules.create(
                        {"name": APPROVAL_RULE, "approvals_required": approvals}
                    )
        except gle.GitlabError as exc:
            raise self._wrap(exc) from exc

    def set_variable(self, repo: Repository, key: str, value: str) -> None:
        project = self._project(repo)
        try:
            var = self._get(project.variables, key)
            if var is None:
                project.variables.create({"key": key, "value": value})
            else:
                var.value = value
                var.save()
        except gle.GitlabError as exc:
            raise self._wrap(exc) from exc

    def get_variables(self, repo: Repository) -> dict[str, str]:
        try:
            return {v.key: v.value for v in self._project(repo).variables.list(get_all=True)}
        except gle.GitlabError as exc:
            raise self._wrap(exc) from exc

    def _pr(self, mr: Any) -> PullRequest:
        return PullRequest(mr.iid, mr.source_branch, mr.target_branch, mr.title,
                           mr.description or "", bool(getattr(mr, "draft", False)),
                           getattr(mr, "web_url", ""))

    def ensure_pull_request(
        self, repo: Repository, source: str, target: str, title: str, description: str,
        draft: bool = False,
    ) -> PullRequest:
        project = self._project(repo)
        try:
            found = project.mergerequests.list(state="opened", source_branch=source,
                                               target_branch=target, get_all=True)
            if found:
                return self._pr(found[0])
            title = f"Draft: {title}" if draft else title
            for attempt in range(6):  # a branch pushed a moment ago may not be visible yet
                try:
                    mr = project.mergerequests.create({"source_branch": source,
                                                       "target_branch": target,
                                                       "title": title,
                                                       "description": description})
                    return self._pr(mr)
                except gle.GitlabCreateError as exc:
                    if "does not exist" not in str(exc) or attempt == 5:
                        raise
                    time.sleep(2)
        except gle.GitlabError as exc:
            raise self._wrap(exc) from exc
        raise PlatformError("unreachable")

    def open_pull_requests(self, repo: Repository) -> list[PullRequest]:
        try:
            found = self._project(repo).mergerequests.list(state="opened", get_all=True)
        except gle.GitlabError as exc:
            raise self._wrap(exc) from exc
        return [self._pr(mr) for mr in found]

    def comment(self, repo: Repository, number: int, body: str) -> None:
        try:
            self._project(repo).mergerequests.get(number).notes.create({"body": body})
        except gle.GitlabError as exc:
            raise self._wrap(exc) from exc

    def start_pipeline(self, repo: Repository, ref: str, variables: dict[str, str]) -> str:
        try:
            pipeline = self._project(repo).pipelines.create(
                {"ref": ref, "variables": [{"key": k, "value": v} for k, v in variables.items()]}
            )
        except gle.GitlabError as exc:
            raise self._wrap(exc) from exc
        return str(pipeline.id)
