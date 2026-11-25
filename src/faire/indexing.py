"""`faire index`: add received files to a sourcedata stream instance, guided by its heuristic.

Everything comes from the instance's own clone: the ma-DMP copy, the heuristic
(``.faire/heuristic.py``) and the ``collection`` remotes. Each top-level entry of the received
directory is one item; the heuristic says which instrument produced it (it must be the
instance's), its sample entities, where it goes and whether it is a pilot. Streams have a single
``dev`` branch; a pilot item is committed there with a ``faire-pilot`` trailer.
"""

from __future__ import annotations

import filecmp
import importlib.util
import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType

from datalad.api import Dataset
from datalad.runner.exception import CommandError

from faire import remotes
from faire.plan import sample_label
from faire.project import dataset_plan
from faire.state import TRAILER_PILOT

HEURISTIC = ".faire/heuristic.py"
BRANCH = "dev"
VALUE = re.compile(r"^[A-Za-z0-9-]+$")


class IndexingError(RuntimeError):
    pass


@dataclass(frozen=True)
class Item:
    source: Path
    instance: str
    entities: dict[str, str]
    place: str
    pilot: bool


def load_heuristic(ds: Dataset) -> ModuleType:
    path = Path(ds.path) / HEURISTIC
    if not path.is_file():
        raise IndexingError(f"{ds.path} has no {HEURISTIC}")
    spec = importlib.util.spec_from_file_location("faire_heuristic", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    for name in ("instrument", "entities", "place"):
        if not callable(getattr(module, name, None)):
            raise IndexingError(f"{HEURISTIC} lacks a function {name!r}")
    return module


class Indexer:
    """Indexes into the stream instance ``ds``, after bringing its ``dev`` up to date."""

    def __init__(self, ds: Dataset):
        self.ds = ds
        repo = ds.repo
        if repo is None:
            raise IndexingError(f"{ds.path} is not a dataset")
        if BRANCH not in repo.get_branches():
            raise IndexingError(f"{ds.path} has no {BRANCH!r} branch: not a stream instance")
        if repo.get_active_branch() != BRANCH:
            repo.call_git(["checkout", "-q", BRANCH])
        self._update()
        self.plan, self.unit = dataset_plan(ds)
        if self.plan is None:
            raise IndexingError(f"{ds.path} has no ma-DMP copy: not a faire dataset")
        if self.unit is None or not self.unit.dataset.is_stream or not self.unit.instrument:
            raise IndexingError(f"{ds.path} is not a stream instance of its ma-DMP")
        self.stream = self.unit.dataset

    def _update(self) -> None:
        """Fast-forward ``dev`` to ``origin`` (no origin: the clone is the repository)."""
        repo = self.ds.repo
        if "origin" not in repo.get_remotes():
            return
        try:
            repo.call_git(["fetch", "-q", "origin"])
            repo.call_git(["merge", "-q", "--ff-only", f"origin/{BRANCH}"])
        except CommandError as exc:
            raise IndexingError(f"cannot bring {BRANCH} up to date with origin, nothing "
                                f"indexed: {exc.stderr or exc}") from exc

    def items(self, directory: Path) -> list[Item]:
        """The heuristic's decision for every item; fails before any change on a bad one."""
        heuristic = load_heuristic(self.ds)
        order = self.plan.sample_entities
        own = self.unit.instrument.instrument_id
        declared = {i.instrument_id for i in self.stream.instruments}
        out = []
        for source in sorted(Path(directory).iterdir()):
            instrument = heuristic.instrument(source)
            if instrument not in declared:
                raise IndexingError(
                    f"{source.name}: instrument {instrument!r} is not declared for stream "
                    f"{self.stream.id!r} in the ma-DMP; nothing was indexed"
                )
            if instrument != own:
                raise IndexingError(
                    f"{source.name}: instrument {instrument!r} belongs to another instance "
                    f"than {self.unit.label}; nothing was indexed"
                )
            entities = dict(heuristic.entities(source))
            if set(entities) != set(order):
                raise IndexingError(f"{source.name}: entities {sorted(entities)} differ from "
                                    f"the ma-DMP's {list(order)}")
            bad = [v for v in entities.values() if not VALUE.match(str(v))]
            if bad:
                raise IndexingError(
                    f"{source.name}: entity values {bad} must match {VALUE.pattern}"
                )
            place = str(heuristic.place(source, entities)).strip("/")
            if not place or ".." in Path(place).parts:
                raise IndexingError(f"{source.name}: invalid place {place!r}")
            pilot = hasattr(heuristic, "pilot") and bool(heuristic.pilot(source, entities))
            out.append(Item(source, self.unit.instrument.instance, entities, place, pilot))
        return out

    def describe(self, item: Item) -> str:
        label = sample_label(item.entities, self.plan.sample_entities)
        return (f"{item.source.name}: {self.unit.label} {label} -> "
                f"{item.place}{' (pilot)' if item.pilot else ''}")

    def index(self, directory: Path, dry_run: bool = False) -> list[str]:
        """Index every item; return one line per item and per commit."""
        items = self.items(directory)
        lines = [self.describe(i) for i in items]
        if dry_run or not items:
            return lines
        return lines + self._commit(items)

    def _commit(self, items: list[Item]) -> list[str]:
        ds, repo = self.ds, self.ds.repo
        before = repo.get_hexsha()
        heuristic_rev = repo.call_git(["log", "-1", "--format=%H", "--", HEURISTIC]).strip()
        order = self.plan.sample_entities
        lines = []
        for item in items:
            # a directory's content goes to the place, a file goes into it
            dest = Path(ds.path) / item.place
            if not item.source.is_dir():
                dest = dest / item.source.name
            if _copy(item.source, dest):
                label = sample_label(item.entities, order)
                entities = ",".join(f"{k}={item.entities[k]}" for k in order)
                pilot = f"\n{TRAILER_PILOT}: true" if item.pilot else ""
                ds.save(path=item.place,
                        message=(f"faire index: {label}\n\n"
                                 f"faire-entities: {entities}\n"
                                 f"faire-heuristic: {heuristic_rev}{pilot}"),
                        result_renderer="disabled")
                lines.append(f"committed {label}{' (pilot)' if item.pilot else ''} "
                             f"to {self.unit.label}")
        if repo.get_hexsha() != before:
            self._publish(before)
        return lines

    def _publish(self, before: str) -> None:
        """Content to the existing collection remotes, then history to origin."""
        ds = self.ds
        try:
            specs = remotes.specs(self.stream.distributions_at("collection"),
                                  self.unit.instrument.instance)
            if not specs:
                raise IndexingError(f"{self.unit.label} has no collection distribution")
            remotes.verify_all(ds)
            for spec in specs:
                target = remotes.content_target(ds, spec.name)
                if target not in ds.repo.get_remotes():
                    if target not in remotes.special_names(ds):
                        raise IndexingError(f"remote {spec.name} is missing; run `faire init`")
                    ds.repo.enable_remote(target)
                try:
                    res = ds.push(to=target, data="auto-if-wanted", on_failure="ignore",
                                  result_renderer="disabled")
                    failed = [r.get("message") for r in res
                              if r.get("status") in ("error", "impossible")]
                    if failed:
                        raise RuntimeError(failed[0])
                except Exception as exc:
                    raise IndexingError(f"content push to {target} failed: {exc}") from exc
        except Exception as exc:
            ds.repo.call_git(["reset", "-q", "--hard", before])
            raise IndexingError(f"{exc}; nothing indexed") from exc
        if "origin" in ds.repo.get_remotes():
            ds.repo.call_git(["push", "-q", "origin", BRANCH, "git-annex"])


def _copy(source: Path, dest: Path) -> bool:
    """Copy ``source`` (file or directory) to ``dest``; False when already identical there."""
    if source.is_dir():
        changed = False
        for child in sorted(source.iterdir()):
            changed |= _copy(child, dest / child.name)
        return changed
    if dest.exists() or dest.is_symlink():
        if dest.exists() and filecmp.cmp(source, dest, shallow=False):
            return False
        raise IndexingError(f"{dest} is already indexed with different content")
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, dest)
    return True
