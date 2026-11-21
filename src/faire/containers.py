"""Container collections and container entries of a dataset.

A template declares collections in `.datalad/config`::

    [faire "collection.<name>"]
        url = <clone URL>
        path = <path in the dataset>
        revision = <tag or commit>

and ships complete datalad-container entries whose image lies inside a collection.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from datalad.api import Dataset, clone

CONTAINER_PREFIX = "datalad.containers."
COLLECTION_PREFIX = "faire.collection."


class ContainerError(RuntimeError):
    pass


@dataclass(frozen=True)
class Collection:
    name: str
    url: str
    path: str
    revision: str


def _grouped(ds: Dataset, prefix: str) -> dict[str, dict[str, str | tuple[str, ...]]]:
    out: dict[str, dict] = {}
    for key in ds.config.keys():
        if key.startswith(prefix):
            name, _, prop = key[len(prefix):].rpartition(".")
            if name:
                out.setdefault(name, {})[prop] = ds.config.get(key, get_all=True)
    return out


def entries(ds: Dataset) -> dict[str, dict[str, str | tuple[str, ...]]]:
    """Container entries: name -> {property: value or tuple of values}."""
    return _grouped(ds, CONTAINER_PREFIX)


def collections(ds: Dataset) -> list[Collection]:
    out = []
    for name, props in sorted(_grouped(ds, COLLECTION_PREFIX).items()):
        try:
            out.append(Collection(name, props["url"], props["path"], props["revision"]))
        except KeyError as exc:
            raise ContainerError(f"collection {name!r} lacks {exc.args[0]!r}") from None
    return out


def install(ds: Dataset, col: Collection) -> None:
    """Install a collection as a subdataset at its pinned revision (not saved)."""
    try:
        sub = clone(source=col.url, path=str(Path(ds.path) / col.path), dataset=ds,
                    result_renderer="disabled")
        sub.repo.call_git(["checkout", "-q", "--detach", col.revision])
    except Exception as exc:
        raise ContainerError(
            f"cannot install collection {col.name!r} from {col.url}: {exc}"
        ) from exc


def missing_images(ds: Dataset) -> list[tuple[str, str]]:
    """(container, image path) for every container entry whose image is not in the tree."""
    out = []
    for name, props in sorted(entries(ds).items()):
        image = props.get("image")
        if not isinstance(image, str) or not os.path.lexists(Path(ds.path) / image):
            out.append((name, str(image)))
    return out


def collection_of(image: str, cols: list[Collection]) -> str:
    for col in cols:
        if image.startswith(col.path.rstrip("/") + "/"):
            return col.name
    return "(no collection)"


def get_image(ds: Dataset, name: str) -> str:
    """Retrieve the image of container ``name``; return its path.

    A collection subdataset installed through an intermediate clone may not know where its
    content is; then the collection's own URL (from `.gitmodules`) is added as a remote.
    """
    image = entries(ds)[name]["image"]
    try:
        ds.get(image, result_renderer="disabled")
        return image
    except Exception:
        pass
    for col in collections(ds):
        if image.startswith(col.path.rstrip("/") + "/"):
            sub = Dataset(Path(ds.path) / col.path)
            if "faire-collection" not in sub.repo.get_remotes():
                sub.repo.call_git(["remote", "add", "faire-collection", col.url])
            sub.repo.call_git(["fetch", "-q", "faire-collection"])
            sub.repo.call_annex(["merge"])
            break
    ds.get(image, result_renderer="disabled")
    return image
