"""Where each repository of a project lives, as logical slash-separated paths.

The same logical layout is used for the local working directory, for the platform (through
:meth:`faire.platform.Platform.location`) and for relative subdataset URLs.
"""

from __future__ import annotations

from dataclasses import dataclass

from faire.plan import Dataset, Instrument, Plan

SUPERDATASET = "superdataset"
SOURCEDATA = "sourcedata"


class LayoutError(ValueError):
    pass


@dataclass(frozen=True)
class Unit:
    """One repository to create: a dataset, a stream instance, or the superdataset."""

    logical: str
    dataset: Dataset
    instrument: Instrument | None = None

    @property
    def is_superdataset(self) -> bool:
        return self.dataset.is_superdataset

    @property
    def label(self) -> str:
        if self.instrument:
            return f"{self.dataset.id}/{self.instrument.instance}"
        return self.dataset.id


def logical_path(dataset: Dataset, instrument: Instrument | None = None) -> str:
    if instrument is not None:
        return f"{SOURCEDATA}/{dataset.id}/{instrument.instance}"
    if dataset.is_superdataset:
        return SUPERDATASET
    return dataset.path or dataset.id


def units(plan: Plan) -> list[Unit]:
    """Every repository of the project, sources before the datasets derived from them,
    the superdataset last."""
    out = []
    for ds in plan.provenance_order():
        if ds.is_stream:
            out += [Unit(logical_path(ds, i), ds, i) for i in ds.instruments]
        elif not ds.is_superdataset:
            out.append(Unit(logical_path(ds), ds))
    if plan.superdataset:
        out.append(superdataset(plan))
    seen: dict[str, str] = {}
    for u in out:
        if u.logical in seen:
            raise LayoutError(f"{u.label} and {seen[u.logical]} would share {u.logical!r}")
        seen[u.logical] = u.label
    return out


def superdataset(plan: Plan) -> Unit:
    return Unit(SUPERDATASET, plan.superdataset)


def registered(plan: Plan) -> list[Unit]:
    """Units registered in the superdataset: datasets with a path other than the root."""
    return [Unit(logical_path(d), d) for d in plan.provenance_order()
            if d.path and not d.is_superdataset]


def source_links(plan: Plan, dataset: Dataset) -> list[tuple[str, Unit]]:
    """(path inside ``dataset``, source unit) for every source repository of ``dataset``."""
    out = []
    for sid in dataset.sources:
        src = plan.datasets[sid]
        if src.is_stream:
            out += [(f"{SOURCEDATA}/{sid}/{i.instance}", Unit(logical_path(src, i), src, i))
                    for i in src.instruments]
        else:
            out.append((f"{SOURCEDATA}/{sid}", Unit(logical_path(src), src)))
    return out
