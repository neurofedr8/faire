"""Remotes of a dataset, created from a distribution's DataLad URL (its ``access_url``).

How a remote is created follows from the URL:

- ``ria+…``: a RIA store; for ``collection``/``accepted`` only its storage part is created,
  git history lives on the platform. Repositories are located in the store by dataset id.
- a local path, ``file://``, ``ssh://`` or ``host:path``: a plain sibling. A stream's URL is
  shared by its instances, so each instance gets ``<url>/<instance>``.
- ``datalad-annex::?type=S3&…``: an S3 bucket (git-annex S3 parameters). Early stages get a
  content-only special remote; ``release`` also stores history there (datalad-next). A stream's
  instances each store under ``<fileprefix><instance>/``.
- other ``datalad-annex::`` URLs: not supported yet.
- anything else must already exist and is added as is.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from urllib.parse import urlencode, urlsplit

from datalad.api import Dataset

from faire.plan import DATALAD_ANNEX, Distribution, annex_parameters, s3_parameters


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
        elif instance and kind(url) == "s3":
            url = s3_url_for_instance(url, instance)
        out.append(RemoteSpec(name, url, dist.wanted, dist.stage))
    return out


FORGES = {"gin.g-node.org": "gin"}
CREDENTIALS = {
    "gin": ("DATALAD_CREDENTIAL_GIN_TOKEN",),
    "platform": ("FAIRE_GITLAB_TOKEN",),
    "s3": ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY"),
}
# kinds whose credentials are not stored with the remote: needed for every transfer
EVERY_TRANSFER = {"s3"}


def s3_url_for_instance(url: str, instance: str) -> str:
    """The S3 URL of a stream instance: ``<instance>/`` appended to the ``fileprefix``."""
    params = s3_parameters(url)
    params["fileprefix"] = f"{params.get('fileprefix', '')}{instance}/"
    return DATALAD_ANNEX + "?" + urlencode(params, safe="/:")


def s3_initremote(name: str, url: str) -> list[str]:
    """``git annex initremote`` arguments of a content-only S3 remote at ``url``."""
    params = annex_parameters(url)
    return ["initremote", name, *(f"{k}={v}" for k, v in params.items()), "autoenable=true"]


def kind(url: str, platform_host: str | None = None) -> str:
    """How a remote at ``url`` is created: ria, s3, plain, gin, platform, datalad-annex,
    existing."""
    if url.startswith("ria+"):
        return "ria"
    if s3_parameters(url) is not None:
        return "s3"
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
    if _git_only(ds, target):
        return "ok"
    if ds.repo.get_preferred_content("wanted", target) != spec.wanted:
        return "wanted-differs"
    return "ok"


def _git_only(ds: Dataset, name: str) -> bool:
    """A remote holding no annexed content (a forge repository)."""
    return ds.config.get(f"remote.{name}.annex-ignore") == "true"


def create(ds: Dataset, spec: RemoteSpec, storage_only: bool = True, platform=None) -> None:
    """Create (or enable) the remote if missing and set its wanted expression.

    ``storage_only`` applies to RIA stores and S3: early stages keep git history on the
    platform.
    """
    if spec.name not in ds.repo.get_remotes() and spec.name in special_names(ds):
        ds.repo.enable_remote(spec.name)
    elif spec.name not in ds.repo.get_remotes():
        platform_host = host_of(platform.url) if platform and hasattr(platform, "url") else None
        k = kind(spec.url, platform_host)
        try:
            if k == "ria":
                ds.create_sibling_ria(
                    # reconfigure: a fresh clone must get the remote of an existing entry
                    spec.url, name=spec.name, new_store_ok=True, existing="reconfigure",
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
                # forges carry git only: annexed content needs a storage distribution
                ds.config.set(f"remote.{spec.name}.annex-ignore", "true", scope="local")
            elif k == "s3":
                storage = spec.name if storage_only else f"{spec.name}-storage"
                _s3_storage(ds, storage, spec.url)
                if not storage_only:  # history too, through datalad-next's remote helper
                    ds.repo.add_remote(spec.name, spec.url)
                    ds.config.set(f"remote.{spec.name}.annex-ignore", "true", scope="local")
                    ds.config.set(f"remote.{spec.name}.datalad-publish-depends", storage,
                                  scope="local")
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
    target = content_target(ds, spec.name)
    if not _git_only(ds, target):
        ds.repo.set_preferred_content("wanted", spec.wanted, remote=target)


def _s3_storage(ds: Dataset, name: str, url: str) -> None:
    """Content-only S3 special remote: enabled if known to git-annex, else initialised."""
    if name in special_names(ds):
        if name not in ds.repo.get_remotes():
            ds.repo.enable_remote(name)
    else:
        ds.repo.call_annex(s3_initremote(name, url))


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
