"""Remotes of a dataset, created from a distribution's DataLad URL (its ``access_url``).

How a remote is created follows from the URL:

- ``ria+…``: a RIA store; for ``collection``/``accepted`` only its storage part is created,
  git history lives on the platform. Repositories are located in the store by dataset id.
- a local path, ``file://``, ``ssh://`` or ``host:path``: a plain sibling. A stream's URL is
  shared by its instances, so each instance gets ``<url>/<instance>``.
- ``datalad-annex::``: needs the datalad-next extension (not supported yet).
- anything else must already exist and is added as is.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from urllib.parse import urlsplit

from datalad.api import Dataset

from faire.plan import Distribution


class RemoteError(RuntimeError):
    pass


@dataclass(frozen=True)
class RemoteSpec:
    name: str
    url: str
    wanted: str
    stage: str


def slug(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "-", text).strip("-").lower() or "remote"


def specs(distributions: Iterable[Distribution], instance: str | None = None) -> list[RemoteSpec]:
    """One remote per distribution, named ``<stage>-<title>`` (deduplicated)."""
    out, used = [], set()
    for dist in distributions:
        name = base = f"{dist.stage}-{slug(dist.title)}"
        n = 1
        while name in used:
            n += 1
            name = f"{base}-{n}"
        used.add(name)
        url = dist.access_url
        if instance and kind(url) == "plain":
            url = f"{url.rstrip('/')}/{instance}"
        out.append(RemoteSpec(name, url, dist.wanted, dist.stage))
    return out


FORGES = {"gin.g-node.org": "gin"}
CREDENTIALS = {"gin": "DATALAD_CREDENTIAL_GIN_TOKEN", "platform": "FAIRE_GITLAB_TOKEN"}


def kind(url: str, platform_host: str | None = None) -> str:
    """How a remote at ``url`` is created: ria, plain, gin, platform, datalad-annex, existing."""
    if url.startswith("ria+"):
        return "ria"
    if url.startswith("datalad-annex::"):
        return "datalad-annex"
    host = host_of(url)
    if host in FORGES:
        return FORGES[host]
    if platform_host and host == platform_host:
        return "platform"
    scheme = urlsplit(url).scheme
    if scheme in ("", "file", "ssh") or re.match(r"^[\w.-]+@?[\w.-]*:[^/]", url):
        return "plain"
    return "existing"


def host_of(url: str) -> str | None:
    if "://" in url:
        return urlsplit(url).hostname
    found = re.match(r"^(?:[\w.-]+@)?([\w.-]+):", url)  # scp-like user@host:path
    return found.group(1) if found else None


def repo_path(url: str) -> str:
    """``org/name`` of a repository URL (scheme or scp-like), without ``.git``."""
    path = urlsplit(url).path if "://" in url else url.split(":", 1)[1]
    return path.strip("/").removesuffix(".git")


def plain_target(url: str) -> str:
    """Form accepted by ``create_sibling``: ``file://`` URLs become paths."""
    return urlsplit(url).path if url.startswith("file://") else url


def special_names(ds: Dataset) -> set[str]:
    """Special remotes recorded in the git-annex branch, enabled here or not."""
    return {r.get("name") for r in ds.repo.get_special_remotes().values()}


def content_target(ds: Dataset, name: str) -> str:
    """Remote receiving annexed content: a RIA sibling's storage part, else the remote."""
    storage = f"{name}-storage"
    if storage in ds.repo.get_remotes() or storage in special_names(ds):
        return storage
    return name


def status(ds: Dataset, spec: RemoteSpec) -> str:
    """``missing``, ``disabled`` (known to git-annex, not enabled here), ``wanted-differs``
    or ``ok``."""
    if spec.name not in ds.repo.get_remotes():
        return "disabled" if spec.name in special_names(ds) else "missing"
    target = content_target(ds, spec.name)
    if ds.repo.get_preferred_content("wanted", target) != spec.wanted:
        return "wanted-differs"
    return "ok"


def create(ds: Dataset, spec: RemoteSpec, storage_only: bool = True, platform=None) -> None:
    """Create (or enable) the remote if missing and set its wanted expression.

    ``storage_only`` applies to RIA stores: early stages keep git history on the platform.
    """
    if spec.name not in ds.repo.get_remotes() and spec.name in special_names(ds):
        ds.repo.enable_remote(spec.name)
    elif spec.name not in ds.repo.get_remotes():
        platform_host = host_of(platform.url) if platform and hasattr(platform, "url") else None
        k = kind(spec.url, platform_host)
        try:
            if k == "ria":
                ds.create_sibling_ria(
                    spec.url, name=spec.name, new_store_ok=True, existing="skip",
                    storage_sibling="only" if storage_only else True,
                    result_renderer="disabled",
                )
            elif k == "plain":
                ds.create_sibling(plain_target(spec.url), name=spec.name,
                                  existing="reconfigure", result_renderer="disabled")
            elif k == "gin":
                ds.create_sibling_gin(repo_path(spec.url), name=spec.name, existing="skip",
                                      access_protocol="ssh", result_renderer="disabled")
            elif k == "platform":
                platform.ensure_repository(repo_path(spec.url))
                ds.siblings("add", name=spec.name, url=spec.url, result_renderer="disabled")
            elif k == "datalad-annex":
                raise RemoteError(
                    f"{spec.name}: datalad-annex:: URLs need the datalad-next extension"
                )
            else:
                ds.siblings("add", name=spec.name, url=spec.url, result_renderer="disabled")
        except RemoteError:
            raise
        except Exception as exc:
            raise RemoteError(f"cannot create remote {spec.name} at {spec.url}: {exc}") from exc
    ds.repo.set_preferred_content("wanted", spec.wanted, remote=content_target(ds, spec.name))


def verify(ds: Dataset, name: str) -> None:
    """Confirm a special remote's configuration as safe to git-annex.

    Recent git-annex refuses to write to a special remote enabled in a fresh clone until it is
    verified. faire does this only for the remotes it created from the ma-DMP, whose
    configuration comes from the dataset's (protected) git-annex branch.
    """
    try:
        out = ds.repo.call_annex(["verifyremote", name])
    except Exception as exc:  # unknown command (older git-annex): nothing to verify
        out = str(exc)
    found = re.search(r"--safe (\S+)", out)
    if found:
        ds.repo.call_annex(["verifyremote", name, "--safe", found.group(1)])


STAGE_PREFIXES = ("collection-", "accepted-", "release-")


def verify_all(ds: Dataset) -> None:
    """Verify every special remote faire created (named after its stage).

    git-annex refuses writes in a repository where any auto-enabled special remote is
    unverified, so this is needed before any transfer from a fresh clone.
    """
    for name in sorted(special_names(ds)):
        if name and name.startswith(STAGE_PREFIXES):
            verify(ds, name)
