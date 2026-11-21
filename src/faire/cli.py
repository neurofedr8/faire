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
