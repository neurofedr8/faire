"""`faire index`: add received files to a sourcedata stream, guided by its heuristic.

The heuristic is a Python module, ``.faire/heuristic.py`` in the stream (loaded from its first
declared instance, all instances being rendered from the same template). Each top-level entry
of the received directory is one item; the heuristic says which instrument produced it, its
sample entities, where it goes in the instance and whether it is a pilot. Streams have a single
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

from faire import remotes
from faire.layout import Unit, logical_path
from faire.plan import sample_label
from faire.project import Project
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
    def __init__(self, project: Project, stream: str):
        self.project = project
        plan = project.plan
        if stream not in plan.datasets or not plan.datasets[stream].is_stream:
            raise IndexingError(f"{stream!r} is not a stream of the plan")
        self.stream = plan.datasets[stream]
        self.units = {i.instrument_id: Unit(logical_path(self.stream, i), self.stream, i)
                      for i in self.stream.instruments}

    def _dataset(self, unit: Unit) -> Dataset:
        ds = self.project.dataset(unit)
        if ds is None:
            raise IndexingError(f"{unit.label} does not exist; run `faire init` first")
        return ds

    def items(self, directory: Path) -> list[Item]:
        """The heuristic's decision for every item; fails before any change on a bad one."""
        first = self.units[self.stream.instruments[0].instrument_id]
        heuristic = load_heuristic(self._dataset(first))
        order = self.project.plan.sample_entities
        out = []
        for source in sorted(Path(directory).iterdir()):
            instrument = heuristic.instrument(source)
            if instrument not in self.units:
                raise IndexingError(
                    f"{source.name}: instrument {instrument!r} is not declared for stream "
                    f"{self.stream.id!r} in the ma-DMP; nothing was indexed"
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
            out.append(Item(source, self.units[instrument].instrument.instance, entities,
                            place, pilot))
        return out

    def describe(self, item: Item) -> str:
        label = sample_label(item.entities, self.project.plan.sample_entities)
        return (f"{item.source.name}: {self.stream.id}/{item.instance} {label} -> "
                f"{item.place}{' (pilot)' if item.pilot else ''}")

    def index(self, directory: Path, dry_run: bool = False) -> list[str]:
        """Index every item; return one line per item and per commit."""
        items = self.items(directory)
        lines = [self.describe(i) for i in items]
        if dry_run:
            return lines
        groups: dict[str, list[Item]] = {}
        for item in items:
            groups.setdefault(item.instance, []).append(item)
        for instance, group in groups.items():
            unit = next(u for u in self.units.values() if u.instrument.instance == instance)
            lines += self._commit(unit, BRANCH, group)
        return lines

    def _commit(self, unit: Unit, branch: str, items: list[Item]) -> list[str]:
        ds = self._dataset(unit)
        repo = ds.repo
        previous = repo.get_active_branch()
        if previous != branch:
            repo.call_git(["checkout", "-q", branch])
        try:
            before = repo.get_hexsha()
            heuristic_rev = repo.call_git(["log", "-1", "--format=%H", "--", HEURISTIC]).strip()
            order = self.project.plan.sample_entities
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
                                 f"to {unit.label}")
            if repo.get_hexsha() != before:
                self._publish(unit, ds, branch, before)
            return lines
        finally:
            if previous != branch:
                repo.call_git(["checkout", "-q", previous])

    def _publish(self, unit: Unit, ds: Dataset, branch: str, before: str) -> None:
        """Content to the collection remotes, then history to the platform."""
        for spec in self.project.remote_specs(unit, ("collection",)):
            try:
                if remotes.status(ds, spec) != "ok":
                    remotes.create(ds, spec)
                res = ds.push(to=spec.name, data="auto-if-wanted", on_failure="ignore",
                              result_renderer="disabled")
                failed = [r.get("message") for r in res
                          if r.get("status") in ("error", "impossible")]
                if failed:
                    raise RuntimeError(failed[0])
            except Exception as exc:
                ds.repo.call_git(["reset", "-q", "--hard", before])
                raise IndexingError(f"content push to {spec.name} failed, nothing indexed: "
                                    f"{exc}") from exc
        platform = self.project.platform
        if platform:
            with platform.git_auth():
                ds.repo.call_git(["push", "-q", "origin", branch, "git-annex"])


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
