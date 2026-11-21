"""Rules and checks, read from the dataset's datalad-container entries.

A container entry with ``faire-sourcedata`` is a rule; one with ``faire-check`` is a check;
other entries are plain containers. Values may use ``{entity}`` placeholders (entity names of
the ma-DMP) and glob wildcards; ``faire-cmd`` may also use DataLad's ``{inputs}``/``{outputs}``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from datalad.api import Dataset

from faire.containers import entries

SELF = "."
PLACEHOLDER = re.compile(r"\{(\w+)\}")


class RuleError(ValueError):
    pass


def _all(props: dict, key: str) -> tuple[str, ...]:
    value = props.get(key, ())
    return (value,) if isinstance(value, str) else tuple(value)


def _one(props: dict, key: str, default: str | None = None) -> str | None:
    values = _all(props, key)
    return values[-1] if values else default


@dataclass(frozen=True)
class Rule:
    name: str
    sources: tuple[str, ...]
    inputs: tuple[str, ...]
    outputs: tuple[str, ...]
    cmd: str
    after: tuple[str, ...] = ()
    runner: str | None = None

    @property
    def primary(self) -> bool:
        """A primary rule creates the session branch; a secondary one commits to it."""
        return SELF not in self.sources


@dataclass(frozen=True)
class Check:
    name: str
    blocking: bool
    stages: tuple[str, ...]
    cmd: str
    inputs: tuple[str, ...] = ()
    runner: str | None = None


def load(ds: Dataset) -> tuple[dict[str, Rule], dict[str, Check]]:
    rules, checks = {}, {}
    for name, props in sorted(entries(ds).items()):
        if "faire-check" in props:
            kind = _one(props, "faire-check")
            if kind not in ("blocking", "advisory"):
                raise RuleError(f"check {name}: faire-check must be blocking or advisory")
            checks[name] = Check(name, kind == "blocking", _all(props, "faire-stage"),
                                 _one(props, "faire-cmd", ""), _all(props, "faire-input"),
                                 _one(props, "faire-runner"))
        elif "faire-sourcedata" in props:
            rules[name] = Rule(name, _all(props, "faire-sourcedata"), _all(props, "faire-input"),
                               _all(props, "faire-output"), _one(props, "faire-cmd", ""),
                               _all(props, "faire-after"), _one(props, "faire-runner"))
    for rule in rules.values():
        unknown = [a for a in rule.after if a not in rules]
        if unknown:
            raise RuleError(f"rule {rule.name}: faire-after names unknown rules {unknown}")
    return rules, checks


def later(rules: dict[str, Rule], name: str) -> set[str]:
    """Rules ordered (transitively) after ``name``."""
    out: set[str] = set()
    frontier = {name}
    while frontier:
        nxt = {r.name for r in rules.values() if set(r.after) & frontier} - out
        out |= nxt
        frontier = nxt
    return out


def expand(text: str, entities: dict[str, str]) -> str:
    """Substitute entity placeholders, leaving others (``{inputs}``...) untouched."""
    return PLACEHOLDER.sub(lambda m: entities.get(m.group(1), m.group(0)), text)
