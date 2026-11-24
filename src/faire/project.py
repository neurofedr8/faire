"""`faire init`: create a project from its ma-DMP, and reconcile it after edits.

Every run first compares the plan with what exists (working directory, platform) and builds a
list of actions; ``dry_run`` reports them without executing. Differences that would alter an
existing dataset are reported and never applied.
"""

from __future__ import annotations

import os
import shutil
import tempfile
from collections.abc import Callable
from contextlib import nullcontext
from dataclasses import dataclass, field
from functools import partial
from pathlib import Path

import yaml
from datalad.api import Dataset, clone, create
from datalad.runner.exception import CommandError

from faire import containers, layout, remotes, templates
from faire.layout import SOURCEDATA, Unit
from faire.plan import Plan
from faire.platform import Platform, relative_url
from faire.state import BASE

DATASET_ID = "faire.dataset-id"
INSTANCE = "faire.instance"
TEMPLATE_REPOSITORY = "faire.template-repository"
TEMPLATE_VERSION = "faire.template-version"
DMP_FILE = "dmp.json"  # in the superdataset, for users
DMP_COPY = ".faire/dmp.json"  # in every other dataset, for its pipelines
DMP_ACTION = "update the ma-DMP in"
EARLY_STAGES = ("collection", "accepted")
DATASET_BRANCHES = ("base", "dev", "pilot")  # the first is the default branch
STREAM_BRANCHES = ("dev",)
SUPERDATASET_BRANCHES = ("dev", "main")
PROTECTED = ("base", "dev", "pilot", "convert/*", "convert-pilot/*")
MERGED_BY_FAIRE = ("dev", "pilot")  # session targets: no merge through the platform
SUPERDATASET_PROTECTED = ("dev", "main", "rel/*")


class InitError(RuntimeError):
    pass


@dataclass
class Report:
    actions: list[str] = field(default_factory=list)  # changes to the project
    differences: list[str] = field(default_factory=list)  # reported, not applied
    local: list[str] = field(default_factory=list)  # setup of this working directory only


def _quiet(**kw):
    return {"result_renderer": "disabled", **kw}


@dataclass
class Project:
    plan: Plan
    dmp_file: Path
    workdir: Path
    platform: Platform | None = None

    def __post_init__(self) -> None:
        self.workdir = Path(self.workdir).resolve()
        self.dmp_file = Path(self.dmp_file)
        self._fresh: set[str] = set()  # logical paths cloned from the platform in this run
        self._moved: dict[str, str] = {}  # planned logical path -> where the dataset is

    # -- locations ---------------------------------------------------------------------------

    def path(self, unit: Unit | str) -> Path:
        return self.workdir / (unit.logical if isinstance(unit, Unit) else unit)

    def relative_url(self, own: str, target: str) -> str:
        if self.platform:
            return self.platform.relative_url(own, target)
        return relative_url(own, target)

    def location(self, unit: Unit) -> str:
        return self.platform.location(unit.logical) if self.platform else unit.logical

    # -- entry point -------------------------------------------------------------------------

    def init(self, dry_run: bool = False) -> Report:
        with self.platform.git_auth() if self.platform else nullcontext():
            return self._init(dry_run)

    def _init(self, dry_run: bool) -> Report:
        report = Report()
        todo: list[tuple[str, Callable[[], None]]] = []
        setup: list[tuple[str, Callable[[], None]]] = []
        units = layout.units(self.plan)
        unplanned = self._inventory(units)
        elsewhere = {key: loc for loc, key in unplanned.items()}
        for unit in units:
            ds = self._obtain(unit)
            if ds is None and _key(unit) in elsewhere:
                where = elsewhere.pop(_key(unit))
                self._moved[unit.logical] = where
                report.differences.append(
                    f"{unit.label} is at {where}, plan says {unit.logical}"
                )
            elif ds is None:
                todo.append((f"create {unit.label} at {unit.logical}", partial(self._create, unit)))
            else:
                self._reconcile(unit, ds, report, todo, setup)
                if unit.is_superdataset:
                    self._reconcile_superdataset(ds, report, todo)
        report.differences += [f"{loc}: exists but is not in the plan"
                               for loc, key in unplanned.items() if key in elsewhere.keys()]
        if report.differences:  # the copies must describe the project as it is
            todo = [(d, a) for d, a in todo if not d.startswith(DMP_ACTION)]
        report.actions = [desc for desc, _ in todo]
        report.local = [desc for desc, _ in setup]
        if not dry_run:
            for _, action in setup + todo:
                action()
        return report

    def _inventory(self, units: list[Unit]) -> dict[str, tuple[str, str | None]]:
        """Datasets of the project found where the plan expects none: location -> key."""
        found: dict[str, tuple[str, str | None]] = {}
        if self.platform:
            planned = {self.location(u) for u in units}
            for repo in self.platform.list_repositories():
                if repo.path in planned:
                    continue
                with tempfile.TemporaryDirectory() as tmp, self.platform.git_auth():
                    ds = clone(source=repo.url, path=str(Path(tmp) / "x"), **_quiet())
                    found[repo.path] = _recorded_key(ds)
            return found
        planned = {u.logical for u in units}
        for root, dirs, _ in os.walk(self.workdir):
            rel = Path(root).relative_to(self.workdir).as_posix()
            if (Path(root) / ".datalad").is_dir():
                if rel not in planned:
                    found[rel] = _recorded_key(Dataset(root))
                dirs[:] = []
            else:
                dirs[:] = [d for d in dirs if d != ".git"]
        return found

    def dataset(self, unit: Unit) -> Dataset | None:
        """The unit's working dataset (cloned from the platform when missing), or None."""
        return self._obtain(unit)

    def _obtain(self, unit: Unit) -> Dataset | None:
        """The unit's working dataset: local, else cloned from the platform, else None."""
        path = self.path(unit)
        if (path / ".datalad").is_dir():
            return Dataset(path)
        if path.exists() and any(path.iterdir()):
            raise InitError(f"{path} exists and is not a dataset")
        if self.platform:
            repo = self.platform.get_repository(self.location(unit))
            if repo is not None:
                with self.platform.git_auth():
                    ds = clone(source=repo.url, path=str(path), **_quiet())
                # the platform's default is `dev`; reconcile works on the first branch
                ds.repo.call_git(["checkout", "-q", _branches(unit)[0]])
                self._fresh.add(unit.logical)
                return ds
        return None

    # -- creation ------------------------------------------------------------------------------

    def _context(self, unit: Unit) -> dict[str, str]:
        ctx = {"dataset_id": unit.dataset.id, "title": unit.dataset.title}
        if unit.instrument:
            ctx |= {"site": unit.instrument.site, "instrument_id": unit.instrument.instrument_id,
                    "instance": unit.instrument.instance}
        return ctx

    def _create(self, unit: Unit) -> None:
        template = unit.dataset.template
        path = self.path(unit)
        branches = _branches(unit)
        with tempfile.TemporaryDirectory() as tmp:
            rendered = Path(tmp) / "rendered"
            templates.render(template, rendered, self._context(unit))  # fails before creating
            # fake dates must hold from the first commit, so they are enabled at creation
            ds = create(path=str(path), fake_dates=templates.fake_dates(rendered), **_quiet())
            try:
                ds.repo.call_git(["branch", "-M", branches[0]])
                templates.merge(ds, rendered)
                ds.config.set(DATASET_ID, unit.dataset.id, scope="branch", reload=False)
                if unit.instrument:
                    ds.config.set(INSTANCE, unit.instrument.instance, scope="branch", reload=False)
                ds.config.set(TEMPLATE_REPOSITORY, template.repository, scope="branch",
                              reload=False)
                ds.config.set(TEMPLATE_VERSION, template.version, scope="branch")
                ds.save(message=f"faire: render {template.repository} at {template.version}",
                        **_quiet())
                self._install_collections(ds, unit)
            except Exception:
                shutil.rmtree(path, ignore_errors=True)
                raise
        for sub, src in layout.source_links(self.plan, unit.dataset):
            self._install_source(ds, unit, sub, src)
        if unit.is_superdataset:
            self._populate_superdataset(ds)
        self._write_dmp(unit, ds)
        for spec in self._remote_specs(unit):
            remotes.create(ds, spec)
        for branch in branches[1:]:
            ds.repo.call_git(["branch", branch, branches[0]])
        if self.platform:
            self._publish(unit, ds, branches)
        else:  # the working dataset is the repository others clone from and push to
            ds.config.set("receive.denyCurrentBranch", "updateInstead", scope="local")

    def _install_collections(self, ds: Dataset, unit: Unit) -> None:
        cols = containers.collections(ds)
        if not cols:
            return
        for col in cols:
            containers.install(ds, col)
            set_submodule_url(ds, col.path, col.url)
        missing = containers.missing_images(ds)
        if missing:
            names = ", ".join(
                f"{name} ({image} in collection {containers.collection_of(image, cols)})"
                for name, image in missing
            )
            raise InitError(f"{unit.label}: images missing for containers: {names}")
        ds.save(message="faire: install container collections", **_quiet())

    def _install_source(self, ds: Dataset, unit: Unit, sub: str, src: Unit) -> None:
        clone(source=str(self.path(src)), path=str(Path(ds.path) / sub), dataset=ds, **_quiet())
        set_submodule_url(ds, sub, self.relative_url(unit.logical, src.logical))
        ds.save(path=[".gitmodules", sub], message=f"faire: register source {sub}", **_quiet())

    def remote_specs(self, unit: Unit, stages: tuple[str, ...] = EARLY_STAGES) -> list:
        """Remotes of ``unit`` for the distributions bound to ``stages``."""
        dists = [d for d in unit.dataset.distributions if d.stage in stages]
        return remotes.specs(dists, unit.instrument.instance if unit.instrument else None)

    def _remote_specs(self, unit: Unit) -> list[remotes.RemoteSpec]:
        dists = [d for d in unit.dataset.distributions if d.stage in EARLY_STAGES]
        return remotes.specs(dists, unit.instrument.instance if unit.instrument else None)

    def _populate_superdataset(self, sup: Dataset) -> None:
        for unit in layout.registered(self.plan):
            self._register(sup, unit)

    def _register(self, sup: Dataset, unit: Unit, push: bool = False) -> None:
        sup_unit = layout.superdataset(self.plan)
        self._install_source(sup, sup_unit, unit.dataset.path, unit)
        if push:
            self._push_default(sup_unit, sup)

    @staticmethod
    def dmp_path(unit: Unit) -> str:
        return DMP_FILE if unit.is_superdataset else DMP_COPY

    def _write_dmp(self, unit: Unit, ds: Dataset, push: bool = False) -> None:
        dest = Path(ds.path) / self.dmp_path(unit)
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(self.dmp_file, dest)
        ds.save(path=self.dmp_path(unit), to_git=True, message="faire: update ma-DMP",
                **_quiet())
        if push:
            self._push_default(unit, ds)

    def _push_default(self, unit: Unit, ds: Dataset) -> None:
        """Publish a change made by reconcile on the default branch."""
        if self.platform:
            with self.platform.git_auth():
                ds.repo.call_git(["push", "-q", "--no-verify", "origin",
                                  f"HEAD:refs/heads/{_branches(unit)[0]}"])

    def _publish(self, unit: Unit, ds: Dataset, branches: tuple[str, ...]) -> None:
        platform = self.platform
        repo = platform.ensure_repository(self.location(unit))
        if "origin" not in ds.repo.get_remotes():
            ds.repo.call_git(["remote", "add", "origin", repo.url])
        skip = ["-o", "ci.skip"] if platform.name == "gitlab" else []  # creating starts nothing
        with platform.git_auth():
            ds.repo.call_git(["push", *skip, "origin", *branches, "git-annex"])
        platform.set_default_branch(repo, default_branch(unit))
        for pattern in (SUPERDATASET_PROTECTED if unit.is_superdataset
                        else STREAM_BRANCHES if unit.instrument else PROTECTED):
            # sessions reach dev and pilot only through `faire merge`
            mergeable = unit.is_superdataset or unit.instrument or pattern not in MERGED_BY_FAIRE
            platform.protect_branch(repo, pattern, mergeable=bool(mergeable))
        platform.set_merge_policy(repo)

    # -- reconcile -----------------------------------------------------------------------------

    def _reconcile(self, unit: Unit, ds: Dataset, report: Report, todo: list,
                   setup: list) -> None:
        tpl = unit.dataset.template
        label = unit.label
        recorded = (ds.config.get(TEMPLATE_REPOSITORY), ds.config.get(TEMPLATE_VERSION))
        if recorded != (tpl.repository, tpl.version):
            report.differences.append(
                f"{label}: template is {recorded[0]} at {recorded[1]}, "
                f"plan says {tpl.repository} at {tpl.version}"
            )
        answers_file = Path(ds.path) / templates.ANSWERS_FILE
        answers = yaml.safe_load(answers_file.read_text()) if answers_file.exists() else {}
        for key, value in tpl.data.items():
            if answers.get(key) != value:
                report.differences.append(
                    f"{label}: template data {key!r} is {answers.get(key)!r}, plan says {value!r}"
                )
        self._reconcile_sources(unit, ds, report, todo)
        for spec in self._remote_specs(unit):
            state = remotes.status(ds, spec)
            action = partial(remotes.create, ds, spec)
            if state == "wanted-differs":
                todo.append((f"set wanted on {spec.name} of {label}", action))
            elif state == "disabled" or (state == "missing" and unit.logical in self._fresh):
                setup.append((f"enable remote {spec.name} of {label}", action))
            elif state == "missing":
                todo.append((f"create remote {spec.name} of {label}", action))
        current = Path(ds.path) / self.dmp_path(unit)
        if not current.exists() or current.read_bytes() != self.dmp_file.read_bytes():
            todo.append((f"{DMP_ACTION} {label}",
                         partial(self._write_dmp, unit, ds, push=True)))

    def _registered(self, ds: Dataset, under: str | None = None) -> dict[str, str]:
        """Registered subdatasets: path relative to ``ds`` -> DataLad dataset id."""
        out = {}
        for r in ds.subdatasets(state="any", **_quiet()):
            rel = Path(r["path"]).relative_to(ds.path).as_posix()
            if under is None or rel.startswith(under + "/"):
                out[rel] = r.get("gitmodule_datalad-id", "")
        return out

    def _reconcile_sources(self, unit: Unit, ds: Dataset, report: Report, todo: list) -> None:
        expected = dict(layout.source_links(self.plan, unit.dataset))
        actual = set(self._registered(ds, SOURCEDATA))
        for sub in sorted(set(expected) - actual):
            stream_dir = sub.rsplit("/", 1)[0]
            src = expected[sub]
            if src.instrument and any(a.startswith(stream_dir + "/") for a in actual):
                branch = f"faire/register-{src.dataset.id}-{src.instrument.instance}"
                if not self._branch_exists(ds, branch):
                    todo.append((f"propose registering {sub} in {unit.label} on {branch}",
                                 partial(self._propose_source, unit, ds, sub, src, branch)))
            else:
                report.differences.append(f"{unit.label}: source {sub} is in the plan only")
        for sub in sorted(actual - set(expected)):
            report.differences.append(f"{unit.label}: source {sub} is not in the plan")

    @staticmethod
    def _branch_exists(ds: Dataset, branch: str) -> bool:
        refs = ds.repo.call_git(["branch", "-a", "--list", branch, f"*/{branch}"])
        return bool(refs.strip())

    def _propose_source(self, unit: Unit, ds: Dataset, sub: str, src: Unit, branch: str) -> None:
        """Register a new source on ``branch`` in a throwaway clone, leaving ``ds`` as it is."""
        with tempfile.TemporaryDirectory() as tmp:
            work = clone(source=ds.path, path=str(Path(tmp) / "work"), **_quiet())
            work.repo.call_git(["checkout", "-q", "-b", branch, f"origin/{BASE}"])
            self._install_source(work, unit, sub, src)
            # git-annex refuses pushes from clones with unverified special remotes; this only
            # moves a branch into the working dataset
            work.repo.call_git(["push", "-q", "--no-verify", "origin", branch])
        if self.platform:
            repo = self.platform.get_repository(self.location(unit))
            with self.platform.git_auth():
                ds.repo.call_git(["push", "origin", branch])
            self.platform.ensure_pull_request(
                repo, branch, BASE, f"Register {sub}",
                f"New instrument instance {src.label} declared in the ma-DMP.",
            )

    def _reconcile_superdataset(self, sup: Dataset, report: Report, todo: list) -> None:
        registered = self._registered(sup)
        by_id = {v: k for k, v in registered.items()}
        expected = {}
        for unit in layout.registered(self.plan):
            if unit.logical in self._moved:  # reported already; keep its current registration
                expected[self._moved[unit.logical]] = unit
                continue
            path = unit.dataset.path
            expected[path] = unit
            uuid = self._uuid(unit)
            if path in registered:
                if uuid and registered[path] != uuid:
                    report.differences.append(f"superdataset: {path} holds another dataset")
            elif uuid and uuid in by_id:
                report.differences.append(
                    f"superdataset: {unit.label} is at {by_id[uuid]}, plan says {path}"
                )
            else:
                todo.append((f"register {unit.label} at {path} in the superdataset",
                             partial(self._register, sup, unit, push=True)))
        for path in sorted(set(registered) - set(expected)):
            report.differences.append(f"superdataset: {path} is not in the plan")

    def _uuid(self, unit: Unit) -> str | None:
        path = self.path(unit)
        return Dataset(path).id if (path / ".datalad").is_dir() else None


def _branches(unit: Unit) -> tuple[str, ...]:
    """Branches created for ``unit``; the first is the default branch."""
    if unit.is_superdataset:
        return SUPERDATASET_BRANCHES
    return STREAM_BRANCHES if unit.instrument else DATASET_BRANCHES


def default_branch(unit: Unit) -> str:
    """The platform's default branch, where pull requests go: `dev` everywhere. Datasets are
    released as tags on `dev` commits and `main` only exists in the superdataset."""
    return "dev"


def _key(unit: Unit) -> tuple[str, str | None]:
    return (unit.dataset.id, unit.instrument.instance if unit.instrument else None)


def _recorded_key(ds: Dataset) -> tuple[str, str | None]:
    return (ds.config.get(DATASET_ID) or "", ds.config.get(INSTANCE))


def set_submodule_url(ds: Dataset, sub: str, url: str) -> None:
    """Record ``url`` as the only URL of submodule ``sub`` in `.gitmodules` (not saved).

    DataLad also records the URL it cloned from (``datalad-url``); for sources that is a path
    in this working directory, which must not travel with the dataset.
    """
    gitmodules = str(Path(ds.path) / ".gitmodules")
    ds.repo.call_git(["config", "-f", gitmodules, f"submodule.{sub}.url", url])
    try:
        ds.repo.call_git(["config", "-f", gitmodules, "--unset-all",
                          f"submodule.{sub}.datalad-url"], expect_fail=True)
    except CommandError:
        pass
