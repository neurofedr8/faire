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


@main.command("plan")
@click.option("--dataset", "dataset_path", default=".", type=click.Path(file_okay=False))
@click.option("--ci-render", type=click.Choice(["gitlab", "github"]),
              help="Emit a CI-native pipeline instead of the neutral task list.")
@click.option("--stage", default="collection", help="Stage whose checks the pipeline runs.")
def plan_cmd(dataset_path, ci_render, stage) -> None:
    """List the due tasks of the current session branch."""
    from faire import tasks as T

    ds = _dataset(dataset_path)
    found = T.plan(ds)
    if ci_render == "gitlab":
        click.echo(T.render_gitlab(found, T.check_list(ds, stage), stage), nl=False)
    elif ci_render == "github":
        click.echo(T.render_github(found, T.check_list(ds, stage)))
    else:
        click.echo(T.as_json(found))


@main.command("run")
@click.option("--dataset", "dataset_path", default=".", type=click.Path(file_okay=False))
@click.option("--task", "task_id", help="Task id from `faire plan`.")
@click.option("--all", "run_all", is_flag=True, help="Run every due task, wave after wave.")
@click.option("--no-push", is_flag=True, help="Commit locally only.")
def run_cmd(dataset_path, task_id, run_all, no_push) -> None:
    """Run one task, or all due tasks, of the current session branch."""
    from faire import tasks as T

    if bool(task_id) == bool(run_all):
        raise click.UsageError("give either --task or --all")
    ds = _dataset(dataset_path)
    try:
        if task_id:
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
    failed = False
    for r in T.run_checks(ds, stage, sample, only, waived):
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
    return ()


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


@main.command("replan")
@click.option("--dataset", "dataset_path", default=".", type=click.Path(file_okay=False))
@click.option("--since", envvar="CI_COMMIT_SHA", required=True,
              help="Commit the pipeline ran for (default: CI_COMMIT_SHA).")
def replan_cmd(dataset_path, since) -> None:
    """Start the next wave when the branch moved during this pipeline."""
    from faire import tasks as T

    platform, repo = _platform_from_env()
    try:
        click.echo(T.replan(_dataset(dataset_path), since, platform, repo))
    except T.TaskError as exc:
        raise click.ClickException(str(exc)) from exc
