import copy
import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from faire.cli import main
from faire.plan import Plan
from faire.validate import _validator, validate

EXAMPLE = Path(__file__).parents[1] / "examples" / "madmp" / "single_site.json"
SCHEMA_DIR = Path(__file__).parents[1] / "src" / "faire" / "schema"


@pytest.fixture
def doc():
    return json.loads(EXAMPLE.read_text())


def ds(doc, ident):
    return next(d for d in doc["dmp"]["dataset"] if d["dataset_id"]["identifier"] == ident)


def messages(doc):
    return [str(v) for v in validate(doc)]


def strip_faire(obj):
    if isinstance(obj, dict):
        return {k: strip_faire(v) for k, v in obj.items() if k != "faire"}
    if isinstance(obj, list):
        return [strip_faire(v) for v in obj]
    return obj


def test_example_is_valid(doc):
    assert validate(doc) == []


@pytest.mark.parametrize("name", ["ex9-dmp-long.json", "ex7-dataset-many.json"])
def test_official_examples_pass_base_schema(name):
    official = json.loads((SCHEMA_DIR / name).read_text())
    assert list(_validator("maDMP-schema-1.3.json").iter_errors(official)) == []


def test_extension_removed_is_base_valid(doc):
    assert list(_validator("maDMP-schema-1.3.json").iter_errors(strip_faire(doc))) == []


def test_duplicate_identifier(doc):
    doc["dmp"]["dataset"].append(copy.deepcopy(ds(doc, "fmriprep")))
    ds(doc, "fmriprep")["faire"]["path"] = "derivatives/other"  # keep paths unique
    assert any("duplicate dataset identifier 'fmriprep'" in m for m in messages(doc))


def test_unpinned_template(doc):
    del ds(doc, "bids")["faire"]["template"]["version"]
    assert any("'version' is a required property" in m for m in messages(doc))


def test_superdataset_with_release(doc):
    plan = Plan.from_document(doc)
    assert plan.superdataset.id == "studyx"
    assert [d.stage for d in plan.superdataset.distributions] == ["release"]


def test_paths_without_superdataset(doc):
    doc["dmp"]["dataset"].remove(ds(doc, "studyx"))
    assert any("none declares '.'" in m for m in messages(doc))


def test_two_superdatasets(doc):
    ds(doc, "fmriprep")["faire"]["path"] = "."
    assert any("already declares path '.'" in m for m in messages(doc))


def test_superdataset_without_sources(doc):
    ds(doc, "studyx")["related_identifier"] = [
        {"identifier": "bids", "type": "other", "relation_type": "IsDerivedFrom"}]
    assert any("must not have sources" in m for m in messages(doc))


def test_derivative_path_valid(doc):
    assert Plan.from_document(doc).datasets["fmriprep"].path == "derivatives/fmriprep"


def test_dot_in_path_segment(doc):
    ds(doc, "fmriprep")["faire"]["path"] = "derivatives/fmri.prep"
    assert any("(fmriprep)" in m and "'.'" in m for m in messages(doc))


def test_nested_paths(doc):
    ds(doc, "fmriprep")["faire"]["path"] = "rawdata/derivatives"
    assert any("nests with the path of 'bids'" in m for m in messages(doc))


def test_stream_with_path(doc):
    ds(doc, "dicoms")["faire"]["path"] = "sourcedata/dicoms"
    assert any("(dicoms)" in m and "must not declare a path" in m for m in messages(doc))


def test_several_sources(doc):
    assert Plan.from_document(doc).datasets["bids"].sources == ("dicoms", "physio", "notes")


def test_unresolved_source(doc):
    ds(doc, "fmriprep")["related_identifier"].append(
        {"identifier": "bidz", "type": "other", "relation_type": "IsDerivedFrom"}
    )
    assert any("source 'bidz' is not in the plan" in m for m in messages(doc))


def test_external_source_ignored(doc):
    ds(doc, "fmriprep")["related_identifier"].append(
        {"identifier": "10.1234/atlas", "type": "doi", "relation_type": "IsDerivedFrom"}
    )
    assert validate(doc) == []
    assert Plan.from_document(doc).datasets["fmriprep"].sources == ("bids",)


def test_cycle(doc):
    ds(doc, "bids")["related_identifier"].append(
        {"identifier": "fmriprep", "type": "other", "relation_type": "IsDerivedFrom"}
    )
    assert any("cycle" in m and "bids" in m and "fmriprep" in m for m in messages(doc))


def test_two_instruments(doc):
    ds(doc, "dicoms")["technical_resource"].append(
        {"name": "Siemens Skyra", "faire": {"instrument_id": "Skyra45012", "site": "a"}}
    )
    assert validate(doc) == []
    assert Plan.from_document(doc).datasets["dicoms"].instances == (
        "a_PrismaFit16001",
        "a_Skyra45012",
    )


def test_instrument_without_site(doc):
    del ds(doc, "dicoms")["technical_resource"][0]["faire"]["site"]
    assert any("'site' is a required property" in m for m in messages(doc))


def test_stream_with_sources(doc):
    ds(doc, "physio")["related_identifier"] = [
        {"identifier": "dicoms", "type": "other", "relation_type": "IsDerivedFrom"}
    ]
    assert any("(physio)" in m and "must have no sources" in m for m in messages(doc))


def test_no_sample_entities(doc):
    del doc["dmp"]["faire"]["sample_entities"]
    assert any("'sample_entities' is a required property" in m for m in messages(doc))


def test_unknown_stage(doc):
    ds(doc, "bids")["distribution"][0]["faire"]["stage"] = "archival"
    assert any(
        "dmp.dataset[3].distribution[0].faire.stage" in m and "'archival'" in m
        for m in messages(doc)
    )


@pytest.mark.parametrize(
    "url",
    [
        "ssh://user:secret@host/path",
        "https://host/repo?access_token=abc",
        "datalad-annex::?type=webdav&url=https://x&password=abc",
    ],
)
def test_credentials_in_url(doc, url):
    ds(doc, "bids")["distribution"][2]["access_url"] = url
    assert any("(GIN)" in m and "credentials" in m for m in messages(doc))


def test_ssh_user_without_password_is_fine(doc):
    assert ds(doc, "bids")["distribution"][2]["access_url"].startswith("ssh://git@")
    assert validate(doc) == []


def test_provenance_order(doc):
    order = [d.id for d in Plan.from_document(doc).provenance_order()]
    assert order.index("dicoms") < order.index("bids") < order.index("fmriprep")


def test_cli_valid():
    result = CliRunner().invoke(main, ["validate", str(EXAMPLE)])
    assert result.exit_code == 0
    assert "valid" in result.output


def test_cli_invalid(tmp_path, doc):
    del doc["dmp"]["faire"]["sample_entities"]
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps(doc))
    result = CliRunner().invoke(main, ["validate", str(bad)])
    assert result.exit_code == 1
    assert "sample_entities" in result.output


S3 = "datalad-annex::?type=S3&encryption=none&bucket=studyx&fileprefix={}&host=s3.example.org"


def test_s3_location_valid(doc):
    ds(doc, "bids")["distribution"][2]["access_url"] = S3.format("rawbids/")
    assert validate(doc) == []


@pytest.mark.parametrize("missing", ["bucket", "encryption"])
def test_s3_location_missing_parameter(doc, missing):
    url = S3.format("rawbids/").replace(f"&{missing}=", "&x=")
    ds(doc, "bids")["distribution"][2]["access_url"] = url
    assert any("(GIN)" in m and repr(missing) in m for m in messages(doc))


def test_s3_location_shared(doc):
    ds(doc, "bids")["distribution"][2]["access_url"] = S3.format("study/")
    ds(doc, "fmriprep")["distribution"][2]["access_url"] = S3.format("study/")
    found = [m for m in messages(doc) if "is shared with" in m]
    assert len(found) == 1 and "(bids)" in found[0] and "(fmriprep)" in found[0]


def test_s3_location_shared_within_a_dataset_is_fine(doc):
    for dist in ds(doc, "bids")["distribution"]:
        dist["access_url"] = S3.format("rawbids/")
    assert validate(doc) == []


def test_s3_embedded_credentials(doc):
    ds(doc, "bids")["distribution"][2]["access_url"] = S3.format("rawbids/") + "&embedcreds=yes"
    assert any("(GIN)" in m and "embedcreds" in m for m in messages(doc))


def test_superdataset_named_after_its_identifier(doc):
    from faire import layout

    plan = Plan.from_document(doc)
    assert layout.superdataset(plan).logical == "studyx"
    assert layout.units(plan)[-1].logical == "studyx"
