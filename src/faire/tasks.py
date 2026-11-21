"""Planning and running a dataset's rules and checks on a session branch.

These commands act on one dataset clone (a CI checkout or a person's clone); they do not need
the ma-DMP. The sample is read from the branch name (``convert/<label>``).
"""

from __future__ import annotations

import glob
import json
import os
import re
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path

import yaml
from datalad.api import Dataset
from datalad.runner.exception import CommandError

from faire import remotes
from faire.containers import entries, get_image
from faire.rules import Check, expand, load
from faire.state import (
    TRAILER_RULE,
    TRAILER_SAMPLE,
    branch_base,
    ensure_subdatasets,
    git,
    log,
    parse_label,
    records,
    rule_state,
    sample_of,
    tree,
)

PUSH_RETRIES = 5
COLLECTION_PREFIX = "collection-"


class TaskError(RuntimeError):
    pass


@dataclass(frozen=True)
class Task:
    id: str
    rule: str
    sample: str
    after: tuple[str, ...] = ()
    runner: str | None = None


def active_branch(ds: Dataset) -> str:
    branch = ds.repo.get_active_branch()
    if not branch:
        raise TaskError("not on a branch")
    return branch


def _sample(ds: Dataset, branch: str) -> str:
    label = sample_of(branch)
    if label is None:
        raise TaskError(f"{branch!r} is not a session branch")
    return label


# -- plan ----------------------------------------------------------------------------------


def plan(ds: Dataset, branch: str | None = None) -> list[Task]:
    """Due tasks of the branch's sample, plus tasks ordered after them, in run order."""
    branch = branch or active_branch(ds)
    label = sample_of(branch)
    if label is None:
        return []
    rules, _ = load(ds)
    planned = {n for n, r in rules.items() if rule_state(ds, rules, r, label, branch).due}
    grew = True
    while grew:
        extra = {r.name for r in rules.values() if set(r.after) & planned} - planned
        planned |= extra
        grew = bool(extra)
    tasks, done = [], set()
    while len(done) < len(planned):  # topological order on faire-after
        ready = sorted(n for n in planned - done if not (set(rules[n].after) & planned) - done)
        for name in ready:
            rule = rules[name]
            tasks.append(Task(f"{name}:{label}", name, label,
                              tuple(f"{a}:{label}" for a in rule.after if a in planned),
                              rule.runner))
        done |= set(ready)
    return tasks


def levels(tasks: list[Task]) -> list[list[Task]]:
    depth: dict[str, int] = {}
    for t in tasks:  # tasks are in topological order
        depth[t.id] = 1 + max((depth[a] for a in t.after), default=-1)
    out: list[list[Task]] = [[] for _ in range(max(depth.values(), default=-1) + 1)]
    for t in tasks:
        out[depth[t.id]].append(t)
    return out


# -- run -----------------------------------------------------------------------------------


def run_task(ds: Dataset, task_id: str, push: bool = True) -> str:
    """Run one task if it is still due; return ``ran``, ``up-to-date`` or ``no-inputs``."""
    name, _, label = task_id.partition(":")
    rules, _ = load(ds)
    if name not in rules:
        raise TaskError(f"no rule {name!r} in this dataset")
    rule = rules[name]
    branch = active_branch(ds)
    state = rule_state(ds, rules, rule, label, branch)
    if not state.present:
        return "no-inputs"
    if not state.due:
        return "up-to-date"
    entities = parse_label(label)
    message = f"faire: {name} {label}\n\n{TRAILER_RULE}: {name}\n{TRAILER_SAMPLE}: {label}"
    if os.environ.get("GITHUB_ACTIONS"):
        message += "\n\n[skip ci]"
    get_image(ds, name)
    ds.containers_run(
        expand(rule.cmd, entities), container_name=name,
        inputs=[expand(p, entities) for p in rule.inputs],
        outputs=[expand(p, entities) for p in rule.outputs],
        message=message, explicit=True, result_renderer="disabled",
    )
    if push:
        publish(ds, branch)
    return "ran"


def run_all(ds: Dataset, push: bool = True, max_waves: int = 20) -> list[str]:
    """Run waves of due tasks in this process until nothing is due (fallback for any CI)."""
    branch = active_branch(ds)
    lines: list[str] = []
    for _ in range(max_waves):
        ran = 0
        for task in plan(ds, branch):
            status = run_task(ds, task.id, push=False)
            lines.append(f"{task.id}: {status}")
            ran += status == "ran"
        if not ran:
            break
        loop = guard(ds, branch)
        if loop:
            raise TaskError(loop)
    if push and lines:
        publish(ds, branch)
    return lines


def publish(ds: Dataset, branch: str) -> None:
    """Content to the collection remotes, then merge the remote branch and push, with retries."""
    for name in sorted(remotes.special_names(ds) | set(ds.repo.get_remotes())):
        if not name.startswith(COLLECTION_PREFIX):
            continue
        if name not in ds.repo.get_remotes():
            ds.repo.enable_remote(name)
        ds.push(to=name, data="auto-if-wanted", result_renderer="disabled")
    options = ["-o", "ci.skip"] if os.environ.get("GITLAB_CI") else []
    for attempt in range(PUSH_RETRIES):
        try:
            # --no-verify: git-annex's hook refuses pushes from clones with unverified remotes
            ds.repo.call_git(["push", "-q", "--no-verify", *options, "origin",
                              f"HEAD:refs/heads/{branch}", "git-annex"])
            return
        except CommandError:
            if attempt == PUSH_RETRIES - 1:
                raise
            ds.repo.call_git(["fetch", "-q", "origin",
                              f"+refs/heads/{branch}:refs/remotes/origin/{branch}",
                              "+refs/heads/git-annex:refs/remotes/origin/git-annex"])
            ds.repo.call_git(["merge", "-q", "--no-edit", f"refs/remotes/origin/{branch}"])
            ds.repo.call_annex(["merge"])


# -- loop guard and replan -----------------------------------------------------------------


def _sources(ds: Dataset, commit: str) -> dict[str, str]:
    return {p: oid for p, (kind, oid) in tree(ds, commit).items()
            if kind == "commit" and p.startswith("sourcedata/")}


def guard(ds: Dataset, branch: str) -> str | None:
    """A message when a task ran twice on the branch without its sources changing."""
    label = sample_of(branch)
    if label is None:
        return None
    rules, _ = load(ds)
    base = branch_base(ds, branch)
    for name in rules:
        found = records(ds, name, label, base)
        if len(found) >= 2 and _sources(ds, found[1]) == _sources(ds, found[0]):
            between = {t.get(TRAILER_RULE, ["?"])[0] for _, t in log(ds, f"{found[1]}..{found[0]}")}
            involved = ", ".join(sorted(between | {name}))
            return (f"{name} ran twice on {branch} without its sources changing; rules "
                    f"{involved} modify each other's inputs: declare their order with "
                    f"faire-after")
    return None


def replan(ds: Dataset, since: str, platform, repository) -> str:
    """Start a new pipeline when the branch moved since ``since`` (the pipeline's commit)."""
    branch = active_branch(ds)
    loop = guard(ds, branch)
    if loop:
        raise TaskError(loop)
    ds.repo.call_git(["fetch", "-q", "origin",
                      f"+refs/heads/{branch}:refs/remotes/origin/{branch}"])
    head = git(ds, "rev-parse", f"refs/remotes/origin/{branch}").strip()
    if head == since:
        return "nothing new"
    return f"started pipeline {platform.start_pipeline(repository, branch, {})}"


# -- checks --------------------------------------------------------------------------------


@dataclass
class CheckResult:
    name: str
    blocking: bool
    passed: bool
    output: str
    modified: list[str]


def _status(ds: Dataset) -> set[str]:
    out = ds.repo.call_git(["status", "--porcelain", "--untracked-files=all"], read_only=True)
    return set(filter(None, out.splitlines()))


def _command(ds: Dataset, check: Check, entities: dict[str, str]) -> str:
    props = entries(ds)[check.name]
    image = props["image"]
    cmdexec = props.get("cmdexec", "{cmd}")
    image_ds = Path(ds.path)
    values = {"img": image, "cmd": expand(check.cmd, entities),
              "img_dspath": str(image_ds), "img_dirpath": str(Path(image).parent),
              "python": "python3"}
    return re.sub(r"\{(img|cmd|img_dspath|img_dirpath|python)\}",
                  lambda m: values[m.group(1)], cmdexec)


def run_checks(ds: Dataset, stage: str, sample: str | None = None, only: str | None = None,
               waived: tuple[str, ...] = ()) -> list[CheckResult]:
    """Run the checks of ``stage``; a check must leave the worktree unchanged."""
    _, checks = load(ds)
    selected = [c for c in checks.values() if stage in c.stages and (only in (None, c.name))]
    if only and not selected:
        raise TaskError(f"no check {only!r} for stage {stage!r}")
    entities = parse_label(sample) if sample else {}
    results = []
    for check in selected:
        get_image(ds, check.name)
        if check.inputs and sample:
            patterns = [expand(p, entities) for p in check.inputs]
            ensure_subdatasets(ds, patterns)
            paths = [p for pat in patterns for p in glob.glob(str(Path(ds.path) / pat),
                                                              recursive=True)]
            if paths:
                ds.get(paths, result_renderer="disabled")
        before = _status(ds)
        env = {**os.environ, "FAIRE_WAIVED": "\n".join(waived), "FAIRE_SAMPLE": sample or "",
               "FAIRE_STAGE": stage}
        proc = subprocess.run(_command(ds, check, entities), shell=True, cwd=ds.path, env=env,
                              capture_output=True, text=True)
        modified = sorted(_status(ds) - before)
        results.append(CheckResult(check.name, check.blocking,
                                   proc.returncode == 0 and not modified,
                                   (proc.stdout + proc.stderr).strip(), modified))
    return results


def check_list(ds: Dataset, stage: str) -> list[Check]:
    _, checks = load(ds)
    return [c for c in checks.values() if stage in c.stages]


# -- CI rendering --------------------------------------------------------------------------


def _job(prefix: str, name: str) -> str:
    return prefix + re.sub(r"[^A-Za-z0-9_.-]+", "-", name)


def render_gitlab(tasks: list[Task], checks: list[Check], stage: str) -> str:
    """A GitLab child pipeline: tasks (ordered by needs), status, checks, replan."""
    jobs: dict[str, dict] = {"stages": ["tasks", "status", "checks", "replan"]}
    for t in tasks:
        job: dict = {"stage": "tasks", "script": [f"faire run --task '{t.id}'"],
                     "needs": [_job("task-", a) for a in t.after]}
        if t.runner:
            job["tags"] = [t.runner]
        jobs[_job("task-", t.id)] = job
    jobs["status"] = {"stage": "status", "script": ["faire status"], "needs": []}
    if tasks:
        jobs["status"]["needs"] = [_job("task-", t.id) for t in tasks]
    for c in checks:
        job = {"stage": "checks", "script": [f"faire test --stage {stage} --check '{c.name}'"],
               "needs": ["status"], "allow_failure": not c.blocking}
        if c.runner:
            job["tags"] = [c.runner]
        jobs[_job("check-", c.name)] = job
    jobs["replan"] = {"stage": "replan", "script": ["faire replan"],
                      "needs": ["status", *[_job("check-", c.name) for c in checks]]}
    return yaml.safe_dump(jobs, sort_keys=False)


def render_github(tasks: list[Task], checks: list[Check]) -> str:
    """Matrices for GitHub Actions: one per dependency level, and one for checks."""
    return json.dumps({
        "levels": [{"include": [{"task": t.id, "runner": t.runner or "ubuntu-latest"}
                                for t in level]} for level in levels(tasks)],
        "checks": {"include": [{"check": c.name, "blocking": c.blocking} for c in checks]},
    }, indent=1)


def as_json(tasks: list[Task]) -> str:
    return json.dumps([asdict(t) for t in tasks], indent=1)
