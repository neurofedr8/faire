"""Session lifecycle: session branches, status of each source stream, reviewer waivers, and
triggering downstream datasets.

The status table is a TSV with one row per sample and one column per source of the dataset.
Its location comes from the dataset's configuration (defaults are BIDS-like)::

    faire.status-file    = sub-{subject}/sub-{subject}_sessions.tsv
    faire.status-key     = session_id
    faire.status-value   = ses-{session}
    faire.status-sidecar = sessions.json
"""

from __future__ import annotations

import csv
import io
import json
import os
from dataclasses import dataclass
from pathlib import Path

from datalad.api import Dataset

from faire.branches import bump_source, checkout_sources, start_session
from faire.rules import expand, load
from faire.state import (
    TRAILER_SAMPLE,
    base_of,
    branch_base,
    branch_for,
    git,
    log,
    parse_label,
    records,
    sample_of,
    tree,
)
from faire.tasks import active_branch, publish

PRESENT, PENDING, PARTIAL, MISSING = "present", "pending", "partial", "missing"
WAIVED = (PARTIAL, MISSING)
LEVELS = {
    PRESENT: "converted",
    PENDING: "expected, not yet converted",
    PARTIAL: "converted in part; a reviewer declared the rest absent",
    MISSING: "declared absent by a reviewer",
}
DEFAULTS = {
    "faire.status-file": "sub-{subject}/sub-{subject}_sessions.tsv",
    "faire.status-key": "session_id",
    "faire.status-value": "ses-{session}",
    "faire.status-sidecar": "sessions.json",
}
TRAILER_STATUS = "faire-status"
COMPLETENESS = "completeness"


class LifecycleError(RuntimeError):
    pass


# -- sources -------------------------------------------------------------------------------


def sources(ds: Dataset, commit: str = "HEAD") -> dict[str, list[str]]:
    """Source id -> subdataset paths (one per instance for a stream)."""
    out: dict[str, list[str]] = {}
    for path, (kind, _) in tree(ds, commit).items():
        parts = path.split("/")
        if kind == "commit" and parts[0] == "sourcedata" and len(parts) >= 2:
            out.setdefault(parts[1], []).append(path)
    return out


def primary_sources(ds: Dataset) -> set[str]:
    rules, _ = load(ds)
    return {s for r in rules.values() if r.primary for s in r.sources}


# -- status table --------------------------------------------------------------------------


@dataclass
class Table:
    path: str
    sidecar: str
    key: str
    value: str


def table_spec(ds: Dataset, label: str) -> Table:
    entities = parse_label(label)
    get = {k: ds.config.get(k) or v for k, v in DEFAULTS.items()}
    spec = Table(expand(get["faire.status-file"], entities), get["faire.status-sidecar"],
                 get["faire.status-key"], expand(get["faire.status-value"], entities))
    if "{" in spec.path + spec.value:
        raise LifecycleError(f"configure faire.status-file and faire.status-value for the "
                             f"entities of {label!r}")
    return spec


def read_rows(ds: Dataset, path: str, commit: str | None = None) -> list[dict[str, str]]:
    if commit:
        try:
            text = git(ds, "show", f"{commit}:{path}")
        except Exception:
            return []
    else:
        file = Path(ds.path) / path
        if not file.exists():
            return []
        text = file.read_text()
    return list(csv.DictReader(io.StringIO(text), delimiter="\t"))


def write_rows(ds: Dataset, path: str, rows: list[dict[str, str]], key: str) -> None:
    columns = [key] + sorted({c for r in rows for c in r} - {key})
    out = io.StringIO()
    writer = csv.DictWriter(out, columns, delimiter="\t", lineterminator="\n", restval="n/a")
    writer.writeheader()
    for row in sorted(rows, key=lambda r: r[key]):
        writer.writerow(row)
    file = Path(ds.path) / path
    file.parent.mkdir(parents=True, exist_ok=True)
    file.write_text(out.getvalue())


def produced(ds: Dataset, stream: str, label: str, branch: str) -> bool:
    """A rule consuming ``stream`` committed output for the sample on the branch."""
    rules, _ = load(ds)
    base = branch_base(ds, branch)
    for rule in rules.values():
        if stream in rule.sources:
            for commit in records(ds, rule.name, label, base):
                if git(ds, "diff-tree", "--no-commit-id", "-r", commit).strip():
                    return True
    return False


def current(ds: Dataset, label: str) -> dict[str, str]:
    """The sample's row as committed, without the key column."""
    spec = table_spec(ds, label)
    for row in read_rows(ds, spec.path, "HEAD"):
        if row.get(spec.key) == spec.value:
            return {k: v for k, v in row.items() if k != spec.key}
    return {}


def compute(ds: Dataset, label: str, branch: str) -> dict[str, str]:
    """Status of every source stream for the sample."""
    row = current(ds, label)
    out = {}
    for stream in sorted(sources(ds)):
        made = produced(ds, stream, label, branch)
        recorded = row.get(stream)
        if recorded == PARTIAL or (recorded == MISSING and not made):
            out[stream] = recorded
        else:
            out[stream] = PRESENT if made else PENDING
    return out


def write_status(ds: Dataset, label: str, values: dict[str, str]) -> list[str]:
    """Write the sample's row and the sidecar; return the paths written."""
    spec = table_spec(ds, label)
    rows = [r for r in read_rows(ds, spec.path) if r.get(spec.key) != spec.value]
    previous = current(ds, label)
    rows.append({spec.key: spec.value, **previous, **values})
    write_rows(ds, spec.path, rows, spec.key)
    sidecar = Path(ds.path) / spec.sidecar
    meta = json.loads(sidecar.read_text()) if sidecar.exists() else {}
    for stream in values:
        meta[stream] = {"Description": f"Conversion status of the {stream} stream",
                        "Levels": LEVELS}
    sidecar.write_text(json.dumps(meta, indent=2, sort_keys=True) + "\n")
    return [spec.path, spec.sidecar]


def record_status(ds: Dataset, push: bool = True) -> bool:
    """Update the status of the branch's sample as a recorded, re-executable step."""
    branch = active_branch(ds)
    label = sample_of(branch)
    if label is None:
        raise LifecycleError(f"{branch!r} is not a session branch")
    spec = table_spec(ds, label)
    before = ds.repo.get_hexsha()
    ds.run("faire status --write", outputs=[spec.path, spec.sidecar], explicit=True,
           message=f"faire: status {label}\n\n{TRAILER_STATUS}: {label}",
           result_renderer="disabled")
    changed = ds.repo.get_hexsha() != before
    if changed and push:
        publish(ds, branch)
    return changed


def mark(ds: Dataset, stream: str, by: str, push: bool = True) -> str:
    """A reviewer declares ``stream`` absent for the branch's sample: partial or missing."""
    branch = active_branch(ds)
    label = sample_of(branch)
    if label is None:
        raise LifecycleError(f"{branch!r} is not a session branch")
    if stream not in sources(ds):
        raise LifecycleError(f"{stream!r} is not a source of this dataset")
    value = PARTIAL if produced(ds, stream, label, branch) else MISSING
    paths = write_status(ds, label, {**compute(ds, label, branch), stream: value})
    ds.save(path=paths, message=(f"faire: {stream} {value} for {label}\n\n"
                                 f"faire-marked: {stream}={value}\nfaire-marked-by: {by}"),
            result_renderer="disabled")
    if push:
        publish(ds, branch)
    return value


def waived_patterns(ds: Dataset, label: str) -> tuple[str, ...]:
    """Output patterns of rules consuming streams declared missing or partial."""
    row = current(ds, label)
    waived = {s for s, v in row.items() if v in WAIVED}
    rules, _ = load(ds)
    entities = parse_label(label)
    return tuple(sorted({expand(o, entities) for r in rules.values()
                         if waived & set(r.sources) for o in r.outputs}))


def completeness(ds: Dataset, label: str) -> tuple[bool, str]:
    """Built-in blocking check: no stream of the sample may be pending."""
    row = current(ds, label)
    expected = sorted(sources(ds))
    pending = [s for s in expected if row.get(s, PENDING) == PENDING]
    waived = [f"{s} ({row[s]})" for s in expected if row.get(s) in WAIVED]
    lines = []
    if pending:
        lines.append("pending: " + ", ".join(pending))
    if waived:
        lines.append("declared absent: " + ", ".join(waived))
    return not pending, "\n".join(lines)


# -- sessions from upstream ----------------------------------------------------------------


def _fetch(ds: Dataset) -> None:
    ds.repo.call_git(["fetch", "-q", "origin"])


def _remote_branches(ds: Dataset) -> set[str]:
    out = git(ds, "for-each-ref", "--format=%(refname:strip=3)", "refs/remotes/origin/")
    return set(out.split())


def upstream_samples(ds: Dataset, path: str, ref: str) -> set[str]:
    """Samples present on ``ref`` of the source at ``path`` (installed and fetched)."""
    sub = ds.pathobj / path
    if not (sub / ".git").exists():
        ds.get(path, get_data=False, result_renderer="disabled")
    source = Dataset(sub)
    _fetch(source)
    head = f"refs/remotes/origin/{ref}"
    try:
        git(source, "rev-parse", "--verify", "-q", head)
    except Exception:
        return set()
    out = set()
    for _, trailers in log(source, head):
        if "faire-entities" in trailers:
            pairs = [p.split("=", 1) for p in trailers["faire-entities"][0].split(",")]
            out.add("_".join(f"{k}-{v}" for k, v in pairs))
        out.update(trailers.get(TRAILER_SAMPLE, []))
    return out


def processed(ds: Dataset, base: str) -> set[str]:
    """Samples whose primary rules have run records on ``base`` (on origin)."""
    rules, _ = load(ds)
    primary = {r.name for r in rules.values() if r.primary}
    out = set()
    for _, t in log(ds, f"refs/remotes/origin/{base}"):
        if t.get("faire-rule", [None])[0] in primary:
            out.update(t.get(TRAILER_SAMPLE, []))
    return out


def open_sessions(ds: Dataset) -> list[str]:
    """Labels of the dataset's session branches on origin."""
    return sorted(b for b in _remote_branches(ds) if sample_of(b) is not None)


def sessions(ds: Dataset, platform=None, repository=None) -> list[str]:
    """Open session branches for new samples of primary sources, and bring newly arrived
    secondary streams to the open branches still waiting for them."""
    _fetch(ds)
    lines = []
    srcs = sources(ds, "refs/remotes/origin/dev")
    primaries = primary_sources(ds) & set(srcs)
    open_branches = set(open_sessions(ds))
    original = ds.repo.get_active_branch()
    for pilot in (False, True):
        base = "pilot" if pilot else "dev"
        if base not in _remote_branches(ds):
            continue
        done = processed(ds, base)
        found = set()
        for stream in sorted(primaries):
            for path in srcs[stream]:
                found |= upstream_samples(ds, path, base)
        for label in sorted(found - done):
            branch = branch_for(label, pilot)
            if branch in open_branches:
                continue
            start_session(ds, label, pilot)
            for paths in srcs.values():
                for path in paths:
                    bump_source(ds, path, base, save=False)
            ds.save(path=[p for ps in srcs.values() for p in ps],
                    message=f"faire: start session {label}", result_renderer="disabled")
            publish(ds, branch)
            if platform:
                platform.ensure_pull_request(repository, branch, base, f"Session {label}",
                                             f"Conversion of {label}.", draft=True)
            lines.append(f"opened {branch}")
            open_branches.add(branch)
    for branch in sorted(open_branches):
        lines += _bring_streams(ds, branch, srcs)
    if original:
        ds.repo.call_git(["checkout", "-q", original])
        checkout_sources(ds)
    return lines


def _bring_streams(ds: Dataset, branch: str, srcs: dict[str, list[str]]) -> list[str]:
    label = sample_of(branch)
    base = base_of(branch)
    ds.repo.call_git(["checkout", "-q", "-B", branch, f"refs/remotes/origin/{branch}"])
    checkout_sources(ds)
    row = current(ds, label)
    moved = []
    for stream, paths in sorted(srcs.items()):
        if row.get(stream, PENDING) != PENDING:
            continue
        for path in paths:
            if bump_source(ds, path, base, save=False):
                moved.append(path)
    if not moved:
        return []
    ds.save(path=moved, message=f"faire: bring {', '.join(moved)} to {label}",
            result_renderer="disabled")
    ds.repo.call_git(["push", "-q", "--no-verify", "origin", f"HEAD:refs/heads/{branch}"])
    return [f"updated {path} on {branch}" for path in moved]


def trigger(downstream: str, ref: str, platform, triggered_by: str) -> list[str]:
    """Start a pipeline on ``dev`` of each downstream repository (comma-separated paths)."""
    out = []
    for path in filter(None, (p.strip() for p in downstream.split(","))):
        repo = platform.get_repository(path)
        if repo is None:
            raise LifecycleError(f"downstream repository {path!r} does not exist")
        pid = platform.start_pipeline(repo, "dev", {"FAIRE_TRIGGERED_BY": triggered_by,
                                                    "FAIRE_UPSTREAM_REF": ref})
        out.append(f"triggered {path} (pipeline {pid})")
    return out


def reviewer() -> str:
    return (os.environ.get("GITLAB_USER_LOGIN") or os.environ.get("GITHUB_ACTOR")
            or os.environ.get("USER") or "unknown")
