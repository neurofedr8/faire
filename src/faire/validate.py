"""Validation of a ma-DMP against the base standard and the faire profile."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from functools import cache
from importlib import resources
from typing import Any
from urllib.parse import parse_qsl, urlsplit

from jsonschema import Draft202012Validator

from faire.plan import DERIVED_FROM

SECRET_QUERY_KEYS = re.compile(r"(token|password|passwd|secret|api[_-]?key|access[_-]?key)", re.I)


@dataclass(frozen=True)
class Violation:
    location: str
    message: str

    def __str__(self) -> str:
        return f"{self.location}: {self.message}"


@cache
def _validator(name: str) -> Draft202012Validator:
    text = resources.files("faire.schema").joinpath(name).read_text(encoding="utf-8")
    return Draft202012Validator(json.loads(text))


def _location(path) -> str:
    out = ""
    for part in path:
        out += f"[{part}]" if isinstance(part, int) else (f".{part}" if out else str(part))
    return out or "(document)"


def validate(doc: Any) -> list[Violation]:
    """Return every violation; an empty list means the document is a conformant ma-DMP."""
    violations = []
    for schema in ("maDMP-schema-1.3.json", "faire-profile-1.json"):
        for err in sorted(_validator(schema).iter_errors(doc), key=lambda e: list(e.path)):
            violations.append(Violation(_location(err.path), err.message))
    if violations:
        return violations  # cross-field rules assume the schemas hold
    datasets = doc["dmp"]["dataset"]
    violations += _identity(datasets)
    violations += _paths(datasets)
    violations += _sources(datasets)
    violations += _instruments(datasets)
    violations += _urls(datasets)
    return violations


def _where(i: int, d: dict) -> str:
    return f"dmp.dataset[{i}] ({d['dataset_id']['identifier']})"


def _identity(datasets: list[dict]) -> list[Violation]:
    seen: dict[str, int] = {}
    out = []
    for i, d in enumerate(datasets):
        ident = d["dataset_id"]["identifier"]
        if ident in seen:
            out.append(Violation(_where(i, d), f"duplicate dataset identifier {ident!r}"))
        seen.setdefault(ident, i)
    return out


def _paths(datasets: list[dict]) -> list[Violation]:
    out = []
    owners: dict[tuple[str, ...], str] = {}
    for i, d in enumerate(datasets):
        path = d["faire"].get("path")
        if path is None:
            continue
        where = _where(i, d)
        if any("faire" in t for t in d.get("technical_resource", [])):
            out.append(Violation(where, "a dataset declaring instruments must not declare a path"))
            continue
        parts = tuple(path.split("/"))
        if path.startswith("/") or any(p == "" for p in parts):
            out.append(Violation(where, f"path {path!r} must be relative without empty segments"))
            continue
        if any("." in p for p in parts):
            out.append(Violation(where, f"path {path!r} has a segment containing '.'"))
            continue
        for other, owner in owners.items():
            shorter = min(len(other), len(parts))
            if other[:shorter] == parts[:shorter]:
                out.append(
                    Violation(where, f"path {path!r} equals or nests with the path of {owner!r}")
                )
        owners[parts] = d["dataset_id"]["identifier"]
    return out


def _sources(datasets: list[dict]) -> list[Violation]:
    out = []
    ids = {d["dataset_id"]["identifier"] for d in datasets}
    plan_types = {d["dataset_id"]["type"] for d in datasets}
    graph: dict[str, list[str]] = {}
    for i, d in enumerate(datasets):
        deps = []
        for link in d.get("related_identifier", []):
            if link["relation_type"] != DERIVED_FROM:
                continue
            if link["identifier"] in ids:
                deps.append(link["identifier"])
            elif link["type"] in plan_types:
                out.append(
                    Violation(_where(i, d), f"source {link['identifier']!r} is not in the plan")
                )
        graph[d["dataset_id"]["identifier"]] = deps
    cycle = _find_cycle(graph)
    if cycle:
        out.append(Violation("dmp.dataset", "sources form a cycle: " + " -> ".join(cycle)))
    return out


def _find_cycle(graph: dict[str, list[str]]) -> list[str] | None:
    state: dict[str, int] = {}
    stack: list[str] = []

    def visit(node: str) -> list[str] | None:
        state[node] = 1
        stack.append(node)
        for nxt in graph.get(node, []):
            if state.get(nxt) == 1:
                return stack[stack.index(nxt):] + [nxt]
            if nxt not in state:
                found = visit(nxt)
                if found:
                    return found
        stack.pop()
        state[node] = 2
        return None

    for node in graph:
        if node not in state:
            found = visit(node)
            if found:
                return found
    return None


def _instruments(datasets: list[dict]) -> list[Violation]:
    out = []
    ids = {d["dataset_id"]["identifier"] for d in datasets}
    for i, d in enumerate(datasets):
        instruments = [t["faire"] for t in d.get("technical_resource", []) if "faire" in t]
        if not instruments:
            continue
        where = _where(i, d)
        if any(
            link["relation_type"] == DERIVED_FROM and link["identifier"] in ids
            for link in d.get("related_identifier", [])
        ):
            out.append(Violation(where, "a dataset declaring instruments must have no sources"))
        seen = set()
        for inst in instruments:
            name = f"{inst['site']}_{inst['instrument_id']}"
            if name in seen:
                out.append(Violation(where, f"instrument instance {name!r} declared twice"))
            seen.add(name)
    return out


def _urls(datasets: list[dict]) -> list[Violation]:
    out = []
    for i, d in enumerate(datasets):
        for j, dist in enumerate(d.get("distribution", [])):
            if _has_credentials(dist["access_url"]):
                out.append(
                    Violation(
                        f"{_where(i, d)}.distribution[{j}] ({dist['title']})",
                        "access_url must not carry credentials",
                    )
                )
    return out


def _has_credentials(url: str) -> bool:
    for prefix in ("datalad-annex::", "ria+"):
        if url.startswith(prefix):
            url = url[len(prefix):]
    parts = urlsplit(url)
    if parts.password:
        return True
    return any(SECRET_QUERY_KEYS.search(key) for key, _ in parse_qsl(parts.query))
