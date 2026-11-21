from pathlib import Path

import pytest
import yaml
from click.testing import CliRunner
from datalad.api import Dataset, clone

from conftest import by_id, commits, make_env, write_doc
from faire import project as P
from faire.cli import main
from faire.plan import Plan
from faire.platform.fake import FakePlatform
from faire.templates import TemplateError
from faire.validate import validate

UNITS = ["sourcedata/dicoms/a_PrismaFit16001", "sourcedata/physio/a_Biopac01", "rawdata",
         "derivatives/fmriprep", "superdataset"]


def run(env, doc, workdir=None, platform=None, dry_run=False):
    assert validate(doc) == []
    dmp = write_doc(env.root / "dmp.json", doc)
    proj = P.Project(Plan.from_document(doc), dmp, workdir or env.root / "work", platform)
    return proj, proj.init(dry_run=dry_run)


@pytest.fixture(scope="module")
def shared(tmp_path_factory, templates_root):
    """One project for tests that only read it."""
    env = make_env(tmp_path_factory.mktemp("shared"), templates_root)
    doc = env.doc()
    by_id(doc, "dicoms")["technical_resource"].append(
        {"name": "Skyra", "faire": {"instrument_id": "Skyra45012", "site": "a"}})
    proj, report = run(env, doc)
    return env, doc, proj, report


@pytest.fixture
def created(env):
    doc = env.doc()
    proj, report = run(env, doc)
    return doc, proj, report


def test_fresh_project(shared):
    _, _, proj, report = shared
    assert report.differences == []
    created_order = [a.split(" at ")[1] for a in report.actions]
    # sources before derived datasets, superdataset last
    assert created_order == [UNITS[0], "sourcedata/dicoms/a_Skyra45012", *UNITS[1:]]
    for logical, ident in [("rawdata", "bids"), ("derivatives/fmriprep", "fmriprep")]:
        ds = Dataset(proj.path(logical))
        assert ds.config.get(P.DATASET_ID) == ident
        assert ds.repo.get_active_branch() == "base"  # default branch
        assert set(ds.repo.get_branches()) - {"git-annex"} == {"base", "dev", "pilot"}
        assert ds.repo.get_hexsha("dev") == ds.repo.get_hexsha("base")
    stream = Dataset(proj.path("sourcedata/dicoms/a_PrismaFit16001"))
    assert stream.config.get(P.DATASET_ID) == "dicoms"
    assert set(stream.repo.get_branches()) - {"git-annex"} == {"dev"}


def test_recorded_template(shared):
    env, _, proj, _ = shared
    ds = Dataset(proj.path("rawdata"))
    answers = yaml.safe_load((Path(ds.path) / ".copier-answers.yml").read_text())
    assert answers["_src_path"] == env.derived_tpl
    assert answers["_commit"] == "v0.1.0"
    assert answers["collection_url"] == env.collection
    assert (Path(ds.path) / "README.md").read_text() == "# BIDS\n"
    assert ds.config.get(P.TEMPLATE_VERSION) == "v0.1.0"


def test_container_available(shared):
    _, _, proj, _ = shared
    ds = Dataset(proj.path("rawdata"))
    names = [r["name"] for r in ds.containers_list(result_renderer="disabled")]
    assert names == ["tool"]
    sub = Dataset(proj.path("rawdata") / "code" / "containers")
    assert sub.repo.call_git(["describe", "--tags"]).strip() == "v1"


def test_missing_image(env):
    doc = env.doc()
    by_id(doc, "fmriprep")["faire"]["template"]["data"]["image"] = "images/tool-9.sif"
    with pytest.raises(P.InitError, match=r"tool \(code/containers/images/tool-9.sif in "
                                          r"collection tools\)"):
        run(env, doc)
    assert not (env.root / "work" / "derivatives" / "fmriprep").exists()


def test_unreachable_template(env):
    doc = env.doc()
    by_id(doc, "fmriprep")["faire"]["template"]["version"] = "v9"
    with pytest.raises(TemplateError, match="v9"):
        run(env, doc)
    assert not (env.root / "work" / "derivatives" / "fmriprep").exists()


def test_sources_and_stream_instances(shared):
    _, _, proj2, _ = shared
    bids = Dataset(proj2.path("rawdata"))
    subs = {Path(r["path"]).relative_to(bids.path).as_posix()
            for r in bids.subdatasets(result_renderer="disabled")}
    assert {"sourcedata/dicoms/a_PrismaFit16001", "sourcedata/dicoms/a_Skyra45012",
            "sourcedata/physio/a_Biopac01"} <= subs
    assert not (Path(bids.path) / "sourcedata" / "dicoms" / ".datalad").exists()
    gitmodules = (Path(bids.path) / ".gitmodules").read_text()
    assert "url = ../sourcedata/dicoms/a_Skyra45012" in gitmodules
    assert "datalad-url" not in gitmodules  # no path of the working directory travels
    fmriprep = (proj2.path("derivatives/fmriprep") / ".gitmodules").read_text()
    assert "url = ../../rawdata" in fmriprep


def test_early_stage_remotes(shared):
    _, _, proj, _ = shared
    bids = Dataset(proj.path("rawdata"))
    assert bids.repo.get_preferred_content("wanted", "collection-site-storage") == "anything"
    assert (bids.repo.get_preferred_content("wanted", "accepted-shared")
            == "not metadata=distribution-restrictions=*")
    fmriprep = Dataset(proj.path("derivatives/fmriprep"))
    assert "accepted-shared" in fmriprep.repo.get_remotes()  # from a file:// URL
    assert (proj.workdir.parent / "shared" / "fmriprep").is_dir()


def test_release_distribution_gets_no_remote(env):
    doc = env.doc()
    by_id(doc, "bids")["distribution"].append(
        env.dist("GIN", "release", str(env.root / "gin" / "bids")))
    proj, _ = run(env, doc)
    names = Dataset(proj.path("rawdata")).repo.get_remotes()
    assert not any(r.startswith("release") for r in names)


def test_superdataset_clone(shared, tmp_path):
    env, _, proj, _ = shared
    sup = clone(source=str(proj.path("superdataset")), path=str(tmp_path / "user"),
                result_renderer="disabled")
    sup.get(".", recursive=True, recursion_limit=1, get_data=False, result_renderer="disabled")
    for path, ident in [("rawdata", "bids"), ("derivatives/fmriprep", "fmriprep")]:
        assert Dataset(Path(sup.path) / path).config.get(P.DATASET_ID) == ident
    assert not (Path(sup.path) / "sourcedata").exists()
    assert (Path(sup.path) / "dmp.json").read_text() == (env.root / "dmp.json").read_text()
    assert "url = ../derivatives/fmriprep" in (Path(sup.path) / ".gitmodules").read_text()


def test_platform_repositories(env):
    doc = env.doc()
    platform = FakePlatform(env.root / "platform", group="lab/study")
    run(env, doc, platform=platform)
    paths = {r.path for r in platform.list_repositories()}
    assert paths == {f"lab/study/{u}" for u in UNITS}
    bids = platform.get_repository("lab/study/rawdata")
    entry = platform.entry(bids)
    assert entry.protected == {"base", "dev", "pilot", "convert/*", "convert-pilot/*"}
    assert entry.approvals == 1
    assert entry.variables[P.DOWNSTREAM_VARIABLE] == "lab/study/derivatives/fmriprep"
    dicoms = platform.get_repository("lab/study/sourcedata/dicoms/a_PrismaFit16001")
    assert platform.entry(dicoms).variables[P.DOWNSTREAM_VARIABLE] == "lab/study/rawdata"
    sup = clone(source=platform.get_repository("lab/study/superdataset").url,
                path=str(env.root / "user"), result_renderer="disabled")
    sup.get("derivatives/fmriprep", get_data=False, result_renderer="disabled")
    assert Dataset(Path(sup.path) / "derivatives/fmriprep").config.get(P.DATASET_ID) == "fmriprep"


def test_flat_platform(env):
    platform = FakePlatform(env.root / "platform", group="lab", subgroups=False)
    proj, _ = run(env, env.doc(), platform=platform)
    assert platform.get_repository("lab/derivatives.fmriprep") is not None
    assert "url = ../rawdata" in (proj.path("derivatives/fmriprep") / ".gitmodules").read_text()


def test_second_run_no_change(created, env):
    doc, proj, _ = created
    before = {u: commits(proj.path(u)) for u in UNITS}
    _, report = run(env, doc)
    assert report.actions == [] and report.differences == []
    assert {u: commits(proj.path(u)) for u in UNITS} == before


def test_second_run_no_change_with_platform(env):
    platform = FakePlatform(env.root / "platform")
    doc = env.doc()
    run(env, doc, platform=platform)
    _, report = run(env, doc, workdir=env.root / "fresh", platform=platform)
    assert report.actions == [] and report.differences == []
    assert "enable remote accepted-shared of bids" in report.local
    _, again = run(env, doc, workdir=env.root / "fresh", platform=platform)
    assert again.actions == again.local == again.differences == []


def test_dry_run(created, env):
    doc, proj, _ = created
    doc["dmp"]["dataset"].append(env.dataset("mriqc", "MRIQC", env.derived_tpl,
                                             path="derivatives/mriqc", sources=["bids"]))
    _, report = run(env, doc, dry_run=True)
    assert "create mriqc at derivatives/mriqc" in report.actions
    assert not proj.path("derivatives/mriqc").exists()


def test_new_derivative(created, env):
    doc, proj, _ = created
    before = {u: commits(proj.path(u)) for u in UNITS if u != "superdataset"}
    doc["dmp"]["dataset"].append(env.dataset("mriqc", "MRIQC", env.derived_tpl,
                                             path="derivatives/mriqc", sources=["bids"]))
    _, report = run(env, doc)
    assert report.differences == []
    assert "create mriqc at derivatives/mriqc" in report.actions
    assert "register mriqc at derivatives/mriqc in the superdataset" in report.actions
    assert {u: commits(proj.path(u)) for u in before} == before
    assert proj.path("derivatives/mriqc/sourcedata/bids").is_dir()


def test_new_instrument(env):
    platform = FakePlatform(env.root / "platform")
    doc = env.doc()
    proj, _ = run(env, doc, platform=platform)
    by_id(doc, "dicoms")["technical_resource"].append(
        {"name": "Skyra", "faire": {"instrument_id": "Skyra45012", "site": "a"}})
    _, report = run(env, doc, platform=platform)
    assert report.differences == []
    assert "create dicoms/a_Skyra45012 at sourcedata/dicoms/a_Skyra45012" in report.actions
    bids = platform.get_repository("lab/study/rawdata")
    [pr] = platform.open_pull_requests(bids)
    assert (pr.source, pr.target) == ("faire/register-dicoms-a_Skyra45012", "base")
    ds = Dataset(proj.path("rawdata"))
    assert ds.repo.get_active_branch() == "base"
    assert not proj.path("rawdata/sourcedata/dicoms/a_Skyra45012").exists()
    _, again = run(env, doc, platform=platform)
    assert again.actions == []


def test_new_distribution_and_changed_wanted(created, env):
    doc, proj, _ = created
    by_id(doc, "fmriprep")["distribution"].append(
        env.dist("Site storage", "collection", f"ria+file://{env.root / 'ria'}"))
    by_id(doc, "bids")["distribution"][1]["faire"]["wanted"] = "include=*.json"
    _, report = run(env, doc)
    assert "create remote collection-site-storage of fmriprep" in report.actions
    assert "set wanted on accepted-shared of bids" in report.actions
    bids = Dataset(proj.path("rawdata"))
    assert bids.repo.get_preferred_content("wanted", "accepted-shared") == "include=*.json"


def test_non_additive_edits(created, env):
    doc, proj, _ = created
    by_id(doc, "fmriprep")["faire"]["template"]["version"] = "v0.2.0"
    by_id(doc, "bids")["related_identifier"].pop()  # drop physio
    doc["dmp"]["dataset"] = [d for d in doc["dmp"]["dataset"]
                             if d["dataset_id"]["identifier"] != "physio"]
    before = commits(proj.path("rawdata"))
    _, report = run(env, doc)
    text = "\n".join(report.differences)
    assert "fmriprep: template is" in text and "v0.2.0" in text
    assert "bids: source sourcedata/physio/a_Biopac01 is not in the plan" in text
    assert "sourcedata/physio/a_Biopac01: exists but is not in the plan" in text
    assert commits(proj.path("rawdata")) == before
    assert proj.path("sourcedata/physio/a_Biopac01").is_dir()


def test_moved_path(created, env):
    doc, _, _ = created
    by_id(doc, "fmriprep")["faire"]["path"] = "derivatives/fmriprep-24"
    _, report = run(env, doc)
    assert any("fmriprep is at derivatives/fmriprep, plan says derivatives/fmriprep-24" in d
               for d in report.differences)


def test_cli_invalid_plan(env):
    doc = env.doc()
    del doc["dmp"]["faire"]["sample_entities"]
    dmp = write_doc(env.root / "bad.json", doc)
    result = CliRunner().invoke(main, ["init", str(dmp), "--workdir", str(env.root / "w")])
    assert result.exit_code == 1
    assert "nothing created" in result.output
    assert not (env.root / "w").exists()


def test_cli_local(env):
    dmp = write_doc(env.root / "dmp.json", env.doc())
    runner = CliRunner()
    first = runner.invoke(main, ["init", str(dmp), "--workdir", str(env.root / "w")])
    assert first.exit_code == 0, first.output
    second = runner.invoke(main, ["init", str(dmp), "--workdir", str(env.root / "w")])
    assert second.exit_code == 0 and "no change" in second.output
