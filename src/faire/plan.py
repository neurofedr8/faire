"""The project plan: the parts of a profile-conformant ma-DMP that faire acts on.

Build a :class:`Plan` only from a document that passed :func:`faire.validate.validate`.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from graphlib import TopologicalSorter
from pathlib import Path
from typing import Any

DERIVED_FROM = "IsDerivedFrom"
STAGES = ("collection", "accepted", "release")


@dataclass(frozen=True)
class Template:
    repository: str
    version: str
    data: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_json(cls, obj: dict[str, Any]) -> Template:
        return cls(obj["repository"], obj["version"], dict(obj.get("data", {})))


@dataclass(frozen=True)
class Instrument:
    name: str
    instrument_id: str
    site: str

    @property
    def instance(self) -> str:
        """Name of the stream instance this instrument feeds."""
        return f"{self.site}_{self.instrument_id}"


@dataclass(frozen=True)
class Distribution:
    title: str
    stage: str
    wanted: str
    access_url: str


@dataclass(frozen=True)
class Dataset:
    id: str
    title: str
    template: Template
    path: str | None
    sources: tuple[str, ...]
    instruments: tuple[Instrument, ...]
    distributions: tuple[Distribution, ...]

    @property
    def is_stream(self) -> bool:
        return bool(self.instruments)

    @property
    def instances(self) -> tuple[str, ...]:
        return tuple(i.instance for i in self.instruments)

    def distributions_at(self, stage: str) -> tuple[Distribution, ...]:
        return tuple(d for d in self.distributions if d.stage == stage)


@dataclass(frozen=True)
class Plan:
    sample_entities: tuple[str, ...]
    superdataset_template: Template
    datasets: dict[str, Dataset]

    @classmethod
    def from_document(cls, doc: dict[str, Any]) -> Plan:
        dmp = doc["dmp"]
        ext = dmp["faire"]
        raw = dmp["dataset"]
        ids = {d["dataset_id"]["identifier"] for d in raw}
        datasets = {}
        for d in raw:
            dext = d["faire"]
            ds = Dataset(
                id=d["dataset_id"]["identifier"],
                title=d["title"],
                template=Template.from_json(dext["template"]),
                path=dext.get("path"),
                sources=tuple(source_ids(d, ids)),
                instruments=tuple(
                    Instrument(t["name"], t["faire"]["instrument_id"], t["faire"]["site"])
                    for t in d.get("technical_resource", [])
                    if "faire" in t
                ),
                distributions=tuple(
                    Distribution(
                        dist["title"], dist["faire"]["stage"], dist["faire"]["wanted"],
                        dist["access_url"],
                    )
                    for dist in d.get("distribution", [])
                ),
            )
            datasets[ds.id] = ds
        return cls(
            sample_entities=tuple(ext["sample_entities"]),
            superdataset_template=Template.from_json(ext["superdataset"]["template"]),
            datasets=datasets,
        )

    def provenance_order(self) -> list[Dataset]:
        """Datasets ordered so that every source comes before the datasets derived from it."""
        graph = {ds.id: set(ds.sources) for ds in self.datasets.values()}
        return [self.datasets[i] for i in TopologicalSorter(graph).static_order()]

    def derived_from(self, dataset_id: str) -> list[Dataset]:
        """Datasets listing ``dataset_id`` as a source."""
        return [ds for ds in self.datasets.values() if dataset_id in ds.sources]


def sample_label(entities: dict[str, str], order: tuple[str, ...]) -> str:
    """Stable text form of a sample, e.g. ``subject-01_session-a``."""
    return "_".join(f"{name}-{entities[name]}" for name in order)


def source_ids(dataset: dict[str, Any], plan_ids: set[str]) -> list[str]:
    """Identifiers of the plan datasets this dataset is derived from, in declaration order."""
    return [
        link["identifier"]
        for link in dataset.get("related_identifier", [])
        if link.get("relation_type") == DERIVED_FROM and link.get("identifier") in plan_ids
    ]


def load_document(path: str | Path) -> dict[str, Any]:
    with open(path, encoding="utf-8") as f:
        return json.load(f)
