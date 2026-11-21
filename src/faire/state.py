"""What a rule has already done on a branch, read from git history only.

A rule's run is a commit with ``faire-rule`` and ``faire-sample`` trailers (and DataLad's run
record). The commit's tree is the state right after the run, so comparing a rule's inputs at
HEAD with its inputs at its last record tells whether it is due again.
"""

from __future__ import annotations

from dataclasses import dataclass
from fnmatch import fnmatchcase
from pathlib import Path

from datalad.api import Dataset
from datalad.runner.exception import CommandError

from faire.rules import Rule, expand, later

TRAILER_RULE = "faire-rule"
TRAILER_SAMPLE = "faire-sample"
TRAILER_PILOT = "faire-pilot"
BASE = "base"  # source pointers and configuration; sessions start here
BRANCH_PREFIXES = {"convert/": "dev", "convert-pilot/": "pilot"}  # session prefix -> target


# -- samples and branches ------------------------------------------------------------------


def sample_of(branch: str) -> str | None:
    for prefix in BRANCH_PREFIXES:
        if branch.startswith(prefix):
            return branch[len(prefix):]
    return None


def base_of(branch: str) -> str:
    for prefix, base in BRANCH_PREFIXES.items():
        if branch.startswith(prefix):
            return base
    return "dev"


def branch_for(label: str, pilot: bool = False) -> str:
    return f"{'convert-pilot' if pilot else 'convert'}/{label}"


def parse_label(label: str) -> dict[str, str]:
    """``subject-01_session-a`` -> ``{"subject": "01", "session": "a"}``."""
    try:
        return dict(part.split("-", 1) for part in label.split("_"))
    except ValueError:
        raise ValueError(
            f"{label!r} is not a sample label (name-value pairs joined by _)"
        ) from None


# -- patterns ------------------------------------------------------------------------------


def match(pattern: str, path: str) -> bool:
    """Segment-wise glob: ``*`` stays within a segment, ``**`` spans segments."""
    return _match(pattern.split("/"), path.split("/"))


def _match(p: list[str], s: list[str]) -> bool:
    if not p:
        return not s
    if p[0] == "**":
        return any(_match(p[1:], s[i:]) for i in range(len(s) + 1))
    return bool(s) and fnmatchcase(s[0], p[0]) and _match(p[1:], s[1:])


def inside(pattern: str, sub: str) -> str | None:
    """Remainder of ``pattern`` inside subdataset path ``sub`` when it reaches into it."""
    p, s = pattern.split("/"), sub.split("/")
    if len(p) <= len(s) or "**" in p[: len(s)]:
        return None
    if all(fnmatchcase(a, b) for a, b in zip(s, p[: len(s)], strict=True)):
        return "/".join(p[len(s):])
    return None


# -- git helpers ---------------------------------------------------------------------------


def git(ds: Dataset, *args: str) -> str:
    return ds.repo.call_git(list(args), read_only=True)


def tree(ds: Dataset, commit: str) -> dict[str, tuple[str, str]]:
    """path -> (object type, object id) of every blob and gitlink at ``commit``."""
    out = {}
    for line in git(ds, "ls-tree", "-r", "-z", "--full-tree", commit).split("\0"):
        if line:
            meta, path = line.split("\t", 1)
            _, kind, oid = meta.split()
            out[path] = (kind, oid)
    return out


def ref(ds: Dataset, name: str) -> str | None:
    for candidate in (f"refs/remotes/origin/{name}", f"refs/heads/{name}"):
        try:
            return git(ds, "rev-parse", "--verify", "-q", candidate).strip()
        except CommandError:
            continue
    return None


def branch_base(ds: Dataset, branch: str, head: str = "HEAD") -> str | None:
    base = ref(ds, base_of(branch))
    if base is None:
        return None
    return git(ds, "merge-base", head, base).strip()


def trailers(message: str) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for line in message.splitlines():
        key, sep, value = line.partition(": ")
        if sep and key.startswith("faire-"):
            out.setdefault(key, []).append(value.strip())
    return out


def log(ds: Dataset, revs: str, *paths: str) -> list[tuple[str, dict[str, list[str]]]]:
    """(commit, faire trailers) newest first, merges excluded."""
    args = ["log", "--no-merges", "--format=%H%x1f%B%x1e", revs]
    if paths:
        args += ["--", *paths]
    out = []
    for chunk in git(ds, *args).split("\x1e"):
        chunk = chunk.strip()
        if chunk:
            commit, _, message = chunk.partition("\x1f")
            out.append((commit, trailers(message)))
    return out


# -- state of a rule -----------------------------------------------------------------------


@dataclass
class RuleState:
    present: bool
    record: str | None
    changed: list[str]

    @property
    def due(self) -> bool:
        return self.present and (self.record is None or bool(self.changed))


def records(ds: Dataset, rule: str, label: str, base: str | None, head: str = "HEAD") -> list[str]:
    revs = f"{base}..{head}" if base else head
    return [c for c, t in log(ds, revs)
            if t.get(TRAILER_RULE) == [rule] and t.get(TRAILER_SAMPLE) == [label]]


def ensure_subdatasets(ds: Dataset, patterns: list[str], commit: str = "HEAD") -> None:
    """Install (without content) every subdataset the patterns reach into."""
    for path, (kind, _) in tree(ds, commit).items():
        if kind == "commit" and any(inside(p, path) is not None for p in patterns):
            if not (Path(ds.path) / path / ".git").exists():
                ds.get(path, get_data=False, result_renderer="disabled")


def fingerprint(ds: Dataset, patterns: list[str], commit: str) -> dict[str, str]:
    """Blob ids of the files the patterns match at ``commit``, inside subdatasets too (at
    their recorded commits), so moving a source pointer for other samples changes nothing."""
    out = {}
    for path, (kind, oid) in tree(ds, commit).items():
        if kind != "commit":
            if any(match(p, path) for p in patterns):
                out[path] = oid
            continue
        rests = [r for r in (inside(p, path) for p in patterns) if r is not None]
        if not rests:
            continue
        files = _subtree(Dataset(Path(ds.path) / path), oid)
        if files is None:
            out[path] = oid  # not installed or commit unknown: fall back to the pointer
            continue
        for sub_path, (_, sub_oid) in files.items():
            if any(match(r, sub_path) for r in rests):
                out[f"{path}/{sub_path}"] = sub_oid
    return out


def _subtree(sub: Dataset, commit: str) -> dict[str, tuple[str, str]] | None:
    if not (Path(sub.path) / ".git").exists():
        return None
    try:
        return tree(sub, commit)
    except CommandError:
        try:
            sub.repo.call_git(["fetch", "-q", "origin"])
            return tree(sub, commit)
        except CommandError:
            return None


def owner(entries: dict[str, tuple[str, str]], path: str) -> str:
    """``path`` itself, or the subdataset holding it."""
    for p, (kind, _) in entries.items():
        if kind == "commit" and path.startswith(p + "/"):
            return p
    return path


def present(ds: Dataset, patterns: list[str], commit: str = "HEAD") -> bool:
    """Every pattern matches a committed file, looking into subdatasets at their commit."""
    entries = tree(ds, commit)
    for p in patterns:
        found = False
        for path, (kind, oid) in entries.items():
            if kind != "commit":
                found = match(p, path)
            else:
                rest = inside(p, path)
                if rest is not None and (Path(ds.path) / path / ".git").exists():
                    sub = Dataset(Path(ds.path) / path)
                    found = any(match(rest, f) for f in git(
                        sub, "ls-tree", "-r", "-z", "--name-only", oid).split("\0") if f)
            if found:
                break
        if not found:
            return False
    return True


def rule_state(ds: Dataset, rules: dict[str, Rule], rule: Rule, label: str, branch: str,
               head: str = "HEAD") -> RuleState:
    entities = parse_label(label)
    patterns = [expand(p, entities) for p in rule.inputs]
    ensure_subdatasets(ds, patterns, head)
    is_present = present(ds, patterns, head)
    found = records(ds, rule.name, label, branch_base(ds, branch, head), head)
    if not found:
        return RuleState(is_present, None, [])
    record = found[0]
    now, then = fingerprint(ds, patterns, head), fingerprint(ds, patterns, record)
    differing = sorted(k for k in set(now) | set(then) if now.get(k) != then.get(k))
    after = later(rules, rule.name)
    changed = []
    entries = tree(ds, head)
    for path in differing:
        touching = log(ds, f"{record}..{head}", owner(entries, path))
        by_later = touching and all(t.get(TRAILER_RULE, [None])[0] in after for _, t in touching)
        if not by_later:
            changed.append(path)
    return RuleState(is_present, record, changed)
