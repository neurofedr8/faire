"""Session lifecycle: the ``update`` task on ``base``, status of each source stream and
reviewer waivers.

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
from datalad.runner.exception import CommandError

from faire.branches import bump_source, checkout_sources
from faire.rules import expand, load
from faire.state import (
    BASE,
    TRAILER_PILOT,
    TRAILER_SAMPLE,
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
TARGETS = ("dev", "pilot")
UPDATE_RETRIES = 5


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
    """Update the status of the branch's sample as a recorded, re-executable step; its push
    ends a wave and starts the next pipeline."""
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
        publish(ds, branch, ci=True)
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
        publish(ds, branch, ci=True)  # the pipeline of the new head runs the checks
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


def upstream_samples(ds: Dataset, path: str, commit: str) -> dict[str, bool]:
    """Samples of the source at ``path`` as recorded at ``commit`` -> whether it is a pilot."""
    oid = tree(ds, commit).get(path, ("", ""))[1]
    sub = ds.pathobj / path
    if not oid:
        return {}
    if not (sub / ".git").exists():
        ds.get(path, get_data=False, result_renderer="disabled")
    source = Dataset(sub)
    try:
        git(source, "cat-file", "-e", oid)
    except Exception:
        _fetch(source)
    out: dict[str, bool] = {}
    for _, trailers in log(source, oid):
        if "faire-entities" in trailers:
            pairs = [p.split("=", 1) for p in trailers["faire-entities"][0].split(",")]
            label = "_".join(f"{k}-{v}" for k, v in pairs)
            out[label] = out.get(label, False) or TRAILER_PILOT in trailers
        for label in trailers.get(TRAILER_SAMPLE, []):
            out.setdefault(label, False)
    return out


def processed(ds: Dataset, target: str) -> set[str]:
    """Samples whose primary rules have run records on ``target`` (on origin)."""
    if target not in _remote_branches(ds):
        return set()
    rules, _ = load(ds)
    primary = {r.name for r in rules.values() if r.primary}
    out = set()
    for _, t in log(ds, f"refs/remotes/origin/{target}"):
        if t.get("faire-rule", [None])[0] in primary:
            out.update(t.get(TRAILER_SAMPLE, []))
    return out


def open_sessions(ds: Dataset) -> list[str]:
    """The dataset's session branches on origin."""
    return sorted(b for b in _remote_branches(ds) if sample_of(b) is not None)


def _push(ds: Dataset, branch: str, ci: bool) -> None:
    options = [] if ci or not os.environ.get("GITLAB_CI") else ["-o", "ci.skip"]
    ds.repo.call_git(["push", "-q", "--no-verify", *options, "origin",
                      f"HEAD:refs/heads/{branch}"])


def _update_base(ds: Dataset) -> list[str]:
    """Point every source at its ``dev`` head on ``base``; recompute when another update
    pushed first, so the pointer history stays linear."""
    for attempt in range(UPDATE_RETRIES):
        _fetch(ds)
        ds.repo.call_git(["checkout", "-q", "-B", BASE, f"refs/remotes/origin/{BASE}"])
        checkout_sources(ds)
        paths = [p for ps in sources(ds).values() for p in ps]
        moved = [p for p in paths if bump_source(ds, p, "dev", save=False)]
        if not moved:
            return []
        ds.save(path=moved, message="faire: update sources\n\n" + "\n".join(moved),
                result_renderer="disabled")
        try:
            _push(ds, BASE, ci=False)
            return [f"updated {p} on {BASE}" for p in moved]
        except CommandError:
            if attempt == UPDATE_RETRIES - 1:
                raise
    return []


def _merge_base_into(ds: Dataset, branch: str, ci: bool) -> bool:
    """Merge ``base`` into ``branch`` on origin; False when it already contains it."""
    head = f"refs/remotes/origin/{branch}"
    try:
        git(ds, "merge-base", "--is-ancestor", BASE, head)
        return False
    except CommandError:
        pass
    ds.repo.call_git(["checkout", "-q", "-B", branch, head])
    try:
        ds.repo.call_git(["merge", "-q", "--no-edit", "-m",
                          f"faire: merge {BASE} into {branch}", BASE])
    except CommandError as exc:
        ds.repo.call_git(["merge", "--abort"])
        raise LifecycleError(f"merging {BASE} into {branch} conflicts: {exc}") from exc
    _push(ds, branch, ci)
    return True


def update(ds: Dataset, platform=None, repository=None) -> list[str]:
    """The ``update`` task on ``base``: sources to their ``dev`` heads, ``base`` merged into
    ``dev``, ``pilot`` and every open session, and sessions opened for new samples."""
    original = ds.repo.get_active_branch()
    lines = _update_base(ds)
    for target in TARGETS:
        if target in _remote_branches(ds) and _merge_base_into(ds, target, ci=False):
            lines.append(f"merged {BASE} into {target}")
    sessions = set(open_sessions(ds))
    for branch in sorted(sessions):
        if _merge_base_into(ds, branch, ci=True):
            lines.append(f"merged {BASE} into {branch}")
    srcs = sources(ds, BASE)
    samples: dict[str, bool] = {}
    for stream in sorted(primary_sources(ds) & set(srcs)):
        for path in srcs[stream]:
            for label, pilot in upstream_samples(ds, path, BASE).items():
                samples[label] = samples.get(label, False) or pilot
    done = {target: processed(ds, target) for target in TARGETS}
    for label, pilot in sorted(samples.items()):
        branch = branch_for(label, pilot)
        target = "pilot" if pilot else "dev"
        if branch in sessions or label in done[target]:
            continue
        ds.repo.call_git(["checkout", "-q", "-B", branch, BASE])
        _push(ds, branch, ci=True)
        if platform:
            platform.ensure_pull_request(repository, branch, target, f"Session {label}",
                                         f"Conversion of {label}.", draft=True)
        lines.append(f"opened {branch}")
    ds.repo.call_git(["checkout", "-q", original or BASE])
    checkout_sources(ds)
    return lines


def reviewer() -> str:
    return (os.environ.get("GITLAB_USER_LOGIN") or os.environ.get("GITHUB_ACTOR")
            or os.environ.get("USER") or "unknown")
