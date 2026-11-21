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


def kind(url: str) -> str:
    if url.startswith("ria+"):
        return "ria"
    if url.startswith("datalad-annex::"):
        return "datalad-annex"
    scheme = urlsplit(url).scheme
    if scheme in ("", "file", "ssh") or re.match(r"^[\w.-]+@?[\w.-]*:[^/]", url):
        return "plain"
    return "existing"


def plain_target(url: str) -> str:
    """Form accepted by ``create_sibling``: ``file://`` URLs become paths."""
    return urlsplit(url).path if url.startswith("file://") else url


def special_names(ds: Dataset) -> set[str]:
    """Special remotes recorded in the git-annex branch, enabled here or not."""
    return {r.get("name") for r in ds.repo.get_special_remotes().values()}


def status(ds: Dataset, spec: RemoteSpec) -> str:
    """``missing``, ``disabled`` (known to git-annex, not enabled here), ``wanted-differs``
    or ``ok``."""
    if spec.name not in ds.repo.get_remotes():
        return "disabled" if spec.name in special_names(ds) else "missing"
    if ds.repo.get_preferred_content("wanted", spec.name) != spec.wanted:
        return "wanted-differs"
    return "ok"


def create(ds: Dataset, spec: RemoteSpec, storage_only: bool = True) -> None:
    """Create (or enable) the remote if missing and set its wanted expression."""
    if spec.name not in ds.repo.get_remotes() and spec.name in special_names(ds):
        ds.repo.enable_remote(spec.name)
    elif spec.name not in ds.repo.get_remotes():
        k = kind(spec.url)
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
    ds.repo.set_preferred_content("wanted", spec.wanted, remote=spec.name)
