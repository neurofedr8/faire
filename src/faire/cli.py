"""Command-line entry point."""

import json
import sys

import click

from faire import __version__
from faire.plan import load_document
from faire.validate import validate


@click.group()
@click.version_option(__version__)
def main() -> None:
    """Act on a machine-actionable DMP: create, index, process, distribute, release."""


@main.command("validate")
@click.argument("dmp_file", type=click.Path(exists=True, dir_okay=False))
def validate_cmd(dmp_file: str) -> None:
    """Check DMP_FILE against RDA DMP v1.3 and the faire profile."""
    try:
        doc = load_document(dmp_file)
    except json.JSONDecodeError as e:
        click.echo(f"{dmp_file}: not valid JSON: {e}", err=True)
        sys.exit(1)
    violations = validate(doc)
    for v in violations:
        click.echo(str(v), err=True)
    if violations:
        sys.exit(1)
    click.echo(f"{dmp_file}: valid")


def _platform(kind: str, group: str | None, url: str | None):
    if kind == "none":
        return None
    if not group:
        raise click.UsageError("--group is required with a platform")
    if kind == "gitlab":
        import os

        from faire.platform.gitlab import GitLabPlatform

        token = os.environ.get("FAIRE_GITLAB_TOKEN")
        if not url or not token:
            raise click.UsageError("GitLab needs --platform-url and FAIRE_GITLAB_TOKEN")
        return GitLabPlatform(url, token, group)
    raise click.UsageError(f"unknown platform {kind!r}")


@main.command("init")
@click.argument("dmp_file", type=click.Path(exists=True, dir_okay=False))
@click.option("--workdir", type=click.Path(file_okay=False), default=".",
              help="Working directory holding one clone per repository.")
@click.option("--platform", "platform_kind", type=click.Choice(["none", "gitlab"]),
              default="none", help="Without a platform the working directory is the project.")
@click.option("--group", help="Root group on the platform.")
@click.option("--platform-url", help="Platform URL, e.g. https://gitlab.example.org.")
@click.option("--dry-run", is_flag=True, help="Report what would change, change nothing.")
def init_cmd(dmp_file, workdir, platform_kind, group, platform_url, dry_run) -> None:
    """Create the project described by DMP_FILE, or reconcile it after an edit."""
    from faire.plan import Plan
    from faire.project import Project

    doc = load_document(dmp_file)
    violations = validate(doc)
    if violations:
        for v in violations:
            click.echo(str(v), err=True)
        click.echo("nothing created: the ma-DMP is not valid", err=True)
        sys.exit(1)
    project = Project(Plan.from_document(doc), dmp_file, workdir,
                      _platform(platform_kind, group, platform_url))
    report = project.init(dry_run=dry_run)
    prefix = "would " if dry_run else ""
    for action in report.actions:
        click.echo(f"{prefix}{action}")
    for setup in report.local:
        click.echo(f"{prefix}{setup} (this working directory only)")
    for diff in report.differences:
        click.echo(f"not applied: {diff}", err=True)
    if not report.actions and not report.differences:
        click.echo("no change")
    if report.differences:
        sys.exit(1)


def _project(dmp_file: str, workdir: str, platform_kind: str, group, platform_url):
    from faire.plan import Plan
    from faire.project import Project

    doc = load_document(dmp_file)
    violations = validate(doc)
    if violations:
        for v in violations:
            click.echo(str(v), err=True)
        raise click.ClickException("the ma-DMP is not valid")
    return Project(Plan.from_document(doc), dmp_file, workdir,
                   _platform(platform_kind, group, platform_url))


def project_options(func):
    """Options locating the project: its ma-DMP, working directory and platform."""
    for option in reversed([
        click.option("--dmp", "dmp_file", required=True,
                     type=click.Path(exists=True, dir_okay=False), help="The ma-DMP file."),
        click.option("--workdir", type=click.Path(file_okay=False), default=".",
                     help="Working directory holding one clone per repository."),
        click.option("--platform", "platform_kind", type=click.Choice(["none", "gitlab"]),
                     default="none"),
        click.option("--group", help="Root group on the platform."),
        click.option("--platform-url", help="Platform URL."),
    ]):
        func = option(func)
    return func


@main.command("index")
@click.argument("stream")
@click.argument("directory", type=click.Path(exists=True, file_okay=False))
@project_options
@click.option("--dry-run", is_flag=True, help="Show the heuristic's decisions only.")
def index_cmd(stream, directory, dmp_file, workdir, platform_kind, group, platform_url,
              dry_run) -> None:
    """Add the received files in DIRECTORY to the sourcedata stream STREAM."""
    from pathlib import Path

    from faire.indexing import Indexer, IndexingError

    project = _project(dmp_file, workdir, platform_kind, group, platform_url)
    try:
        for line in Indexer(project, stream).index(Path(directory), dry_run=dry_run):
            click.echo(line)
    except IndexingError as exc:
        raise click.ClickException(str(exc)) from exc


def _dataset(path: str):
    from datalad.api import Dataset

    return Dataset(path)


def _dataset_plan(ds):
    """(plan, unit) of a dataset clone, from the ma-DMP it tracks; (None, None) without one."""
    from pathlib import Path

    from faire import layout
    from faire.plan import Plan, load_document
    from faire.project import DATASET_ID, DMP_COPY, DMP_FILE, INSTANCE

    for name in (DMP_COPY, DMP_FILE):
        path = Path(ds.path) / name
        if path.is_file():
            plan = Plan.from_document(load_document(path))
            ident, instance = ds.config.get(DATASET_ID), ds.config.get(INSTANCE)
            unit = next((u for u in layout.units(plan) if u.dataset.id == ident and
                         (u.instrument.instance if u.instrument else None) == instance), None)
            return plan, unit
    return None, None


@main.command("plan")
@click.option("--dataset", "dataset_path", default=".", type=click.Path(file_okay=False))
@click.option("--ci-render", type=click.Choice(["gitlab", "github"]),
              help="Emit a CI-native pipeline instead of the neutral task list.")
@click.option("--stage", default="collection", help="Stage whose checks a session runs.")
@click.option("--project-path", envvar="CI_PROJECT_PATH",
              help="Platform path of this repository (default: CI_PROJECT_PATH).")
def plan_cmd(dataset_path, ci_render, stage, project_path) -> None:
    """Say what a pipeline does on the current branch (tasks of a session by default)."""
    import os

    from faire import layout
    from faire import tasks as T

    ds = _dataset(dataset_path)
    branch = ds.repo.get_active_branch() or os.environ.get("CI_COMMIT_REF_NAME", "")
    plan, unit = _dataset_plan(ds)
    downstream: tuple[str, ...] = ()
    sync = False
    if plan and unit:
        targets = [layout.logical_path(d) for d in plan.derived_from(unit.dataset.id)]
        downstream = (T.downstream_paths(project_path, unit.logical, targets)
                      if project_path else tuple(targets))
        sync = bool(unit.dataset.distributions_at("accepted"))
    try:
        pipe = T.pipeline(ds, branch, stage, downstream, sync)
    except T.TaskError as exc:
        raise click.ClickException(str(exc)) from exc
    if ci_render == "gitlab":
        click.echo(T.render_gitlab(pipe), nl=False)
    elif ci_render == "github":
        click.echo(T.render_github(pipe))
    else:
        click.echo(T.as_json(pipe.tasks))


@main.command("run")
@click.option("--dataset", "dataset_path", default=".", type=click.Path(file_okay=False))
@click.option("--task", "task_id", help="Task id from `faire plan`.")
@click.option("--all", "run_all", is_flag=True, help="Run every due task, wave after wave.")
@click.option("--no-push", is_flag=True, help="Commit locally only.")
def run_cmd(dataset_path, task_id, run_all, no_push) -> None:
    """Run one task, or all due tasks, of the current session branch.

    Task ``update`` (planned on ``base``) moves source pointers, merges ``base`` into ``dev``,
    ``pilot`` and open sessions, and opens sessions for new samples."""
    from faire import tasks as T

    if bool(task_id) == bool(run_all):
        raise click.UsageError("give either --task or --all")
    ds = _dataset(dataset_path)
    try:
        if task_id == "update":
            from faire import lifecycle as L

            try:
                platform, repo = _platform_from_env()
            except click.ClickException:
                platform = repo = None
            for line in L.update(ds, platform, repo) or ["nothing to update"]:
                click.echo(line)
        elif task_id:
            click.echo(f"{task_id}: {T.run_task(ds, task_id, push=not no_push)}")
        else:
            for line in T.run_all(ds, push=not no_push):
                click.echo(line)
    except T.TaskError as exc:
        raise click.ClickException(str(exc)) from exc


@main.command("test")
@click.option("--dataset", "dataset_path", default=".", type=click.Path(file_okay=False))
@click.option("--stage", required=True, type=click.Choice(["collection", "accepted", "release"]))
@click.option("--check", "only", help="Run only this check.")
def test_cmd(dataset_path, stage, only) -> None:
    """Run the checks of STAGE; exit non-zero when a blocking check fails."""
    from faire import tasks as T
    from faire.state import sample_of

    ds = _dataset(dataset_path)
    branch = ds.repo.get_active_branch() or ""
    sample = sample_of(branch)
    waived = _waived(ds, sample)
    from faire import lifecycle as L

    results = []
    if sample and stage == "collection" and only in (None, L.COMPLETENESS):
        ok, text = L.completeness(ds, sample)
        results.append(T.CheckResult(L.COMPLETENESS, True, ok, text, []))
    if only != L.COMPLETENESS:
        results += T.run_checks(ds, stage, sample, only, waived)
    failed = False
    for r in results:
        verdict = "ok" if r.passed else ("FAILED" if r.blocking else "warning")
        click.echo(f"{r.name}: {verdict}")
        if r.output:
            click.echo("  " + r.output.replace("\n", "\n  "))
        for m in r.modified:
            click.echo(f"  modified the dataset: {m}")
        failed |= r.blocking and not r.passed
    if failed:
        sys.exit(1)


def _waived(ds, sample) -> tuple[str, ...]:
    from faire.lifecycle import waived_patterns

    return waived_patterns(ds, sample) if sample else ()


def _platform_from_env():
    """The platform of the running CI job (GitLab), with a token from FAIRE_GITLAB_TOKEN."""
    import os

    from faire.platform.gitlab import GitLabPlatform

    url, token = os.environ.get("CI_SERVER_URL"), os.environ.get("FAIRE_GITLAB_TOKEN")
    path = os.environ.get("CI_PROJECT_PATH")
    if not (url and token and path):
        raise click.ClickException("needs CI_SERVER_URL, CI_PROJECT_PATH and FAIRE_GITLAB_TOKEN")
    platform = GitLabPlatform(url, token, path.rsplit("/", 1)[0])
    return platform, platform.get_repository(path)


@main.command("status")
@click.option("--dataset", "dataset_path", default=".", type=click.Path(file_okay=False))
@click.option("--write", is_flag=True,
              help="Only write the table (the recorded step run by plain `faire status`).")
@click.option("--no-push", is_flag=True)
@click.option("--next-wave", is_flag=True,
              help="End a CI wave: start the next pipeline if the branch moved since "
                   "CI_COMMIT_SHA and recording the status did not.")
def status_cmd(dataset_path, write, no_push, next_wave) -> None:
    """Update the source-stream status of the current session's sample."""
    from faire import lifecycle as L
    from faire.state import sample_of

    ds = _dataset(dataset_path)
    branch = ds.repo.get_active_branch() or ""
    label = sample_of(branch)
    if label is None:
        raise click.ClickException(f"{branch!r} is not a session branch")
    if write:
        L.write_status(ds, label, L.compute(ds, label, branch))
        return
    changed = L.record_status(ds, push=not no_push)
    for stream, value in sorted(L.current(ds, label).items()):
        click.echo(f"{stream}: {value}")
    if not changed:
        click.echo("no change")
        if next_wave and not no_push:
            import os

            from faire import tasks as T

            platform, repo = _platform_from_env()
            click.echo(T.next_wave(ds, os.environ.get("CI_COMMIT_SHA", ""), platform, repo))


@main.command("mark")
@click.argument("assignment", metavar="STREAM=missing")
@click.option("--dataset", "dataset_path", default=".", type=click.Path(file_okay=False))
@click.option("--by", help="Who declares it (default: the CI user).")
@click.option("--no-push", is_flag=True)
def mark_cmd(assignment, dataset_path, by, no_push) -> None:
    """Declare a source stream absent for the current session (missing or partial)."""
    from faire import lifecycle as L

    stream, _, value = assignment.partition("=")
    if value != "missing":
        raise click.UsageError("use STREAM=missing")
    try:
        result = L.mark(_dataset(dataset_path), stream, by or L.reviewer(), push=not no_push)
    except L.LifecycleError as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(f"{stream}: {result}")


@main.command("sync")
@click.option("--stage", required=True, type=click.Choice(["collection", "accepted", "release"]))
@click.option("--dmp", "dmp_file", type=click.Path(exists=True, dir_okay=False),
              help="ma-DMP (default: the one the dataset tracks).")
@click.option("--dataset", "dataset_path", default=".", type=click.Path(file_okay=False))
@click.option("--distribution", "only", help="Only the distribution with this title.")
@click.option("--ref", "refs", multiple=True,
              help="Branches or tags to push (default: the checked-out branch).")
def sync_cmd(stage, dmp_file, dataset_path, only, refs) -> None:
    """Push to the dataset's distributions bound to STAGE."""
    from faire.distribution import SyncError, sync
    from faire.plan import Plan

    ds = _dataset(dataset_path)
    if dmp_file:
        doc = load_document(dmp_file)
        if validate(doc):
            raise click.ClickException("the ma-DMP is not valid")
        plan = Plan.from_document(doc)
    else:
        plan, _ = _dataset_plan(ds)
        if plan is None:
            raise click.ClickException("the dataset tracks no ma-DMP; give --dmp")
    refs = list(refs) or [ds.repo.get_active_branch()]
    try:
        for line in sync(plan, ds, stage, refs, only):
            click.echo(line)
    except SyncError as exc:
        raise click.ClickException(str(exc)) from exc
