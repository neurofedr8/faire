"""Rendering copier templates into DataLad datasets."""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

import copier
from datalad.api import Dataset

from faire.plan import Template

ANSWERS_FILE = ".copier-answers.yml"


class TemplateError(RuntimeError):
    pass


def render(template: Template, dest: Path, context: dict[str, Any]) -> None:
    """Render ``template`` at its pinned version into the new directory ``dest``.

    ``context`` is available to the template besides its own answers (``template.data``),
    but only answers are recorded in the answers file.
    """
    try:
        copier.run_copy(
            template.repository, str(dest), data={**context, **template.data},
            vcs_ref=template.version, defaults=True, quiet=True, unsafe=False,
        )
    except Exception as exc:  # copier raises many types for fetch and render failures
        shutil.rmtree(dest, ignore_errors=True)
        raise TemplateError(
            f"cannot render {template.repository} at {template.version}: {exc}"
        ) from exc


def config_entries(ds: Dataset, config_file: Path) -> list[tuple[str, str]]:
    """Entries of a git-config file, in order, multi-valued keys repeated."""
    out = ds.repo.call_git(["config", "-f", str(config_file), "--list", "-z"])
    entries = []
    for item in filter(None, out.split("\0")):
        key, _, value = item.partition("\n")
        entries.append((key, value))
    return entries


def merge(ds: Dataset, rendered: Path) -> None:
    """Merge a rendered template into the (freshly created) dataset ``ds``; nothing is saved.

    The dataset's own `.datalad/config` and `.gitattributes` are extended, not replaced, so
    the dataset identifier and DataLad's defaults survive. The answers file is kept in git.
    """
    root = Path(ds.path)
    for src in sorted(rendered.rglob("*")):
        rel = src.relative_to(rendered)
        if rel.parts[0] == ".git" or src.is_dir():
            continue
        dest = root / rel
        if rel == Path(".datalad/config"):
            for key, value in config_entries(ds, src):
                ds.config.add(key, value, scope="branch", reload=False)
            ds.config.reload()
        elif rel == Path(".gitattributes") and dest.exists():
            dest.write_text(dest.read_text().rstrip("\n") + "\n" + src.read_text())
        else:
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dest)
    # last rules win: keep git's own files and the answers file out of the annex whatever
    # the template says
    attrs = root / ".gitattributes"
    text = attrs.read_text() if attrs.exists() else ""
    for rule in ("**/.git* annex.largefiles=nothing", f"{ANSWERS_FILE} annex.largefiles=nothing",
                 ".faire/** annex.largefiles=nothing"):
        text = text.rstrip("\n") + ("\n" if text else "") + rule + "\n"
    attrs.write_text(text)
