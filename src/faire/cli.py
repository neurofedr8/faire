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
