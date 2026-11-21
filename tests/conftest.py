"""Local fixtures: copier templates and a container collection as git repositories, and a
ma-DMP using them with storage in the test's temporary directory."""

from __future__ import annotations

import copy
import json
import os
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

import pytest
from datalad.api import Dataset, create
from datalad.support.gitrepo import GitRepo

# Tests must not depend on the developer's git configuration (e.g. annex.private=true hides
# location information from clones); give them a global configuration of their own.
_GITCONFIG = Path(tempfile.mkdtemp(prefix="faire-tests-")) / "gitconfig"
_GITCONFIG.write_text("[user]\n\tname = faire tests\n\temail = tests@example.org\n"
                      "[init]\n\tdefaultBranch = main\n")
os.environ["GIT_CONFIG_GLOBAL"] = str(_GITCONFIG)
# recorded steps call `faire` itself
os.environ["PATH"] = str(Path(sys.executable).parent) + os.pathsep + os.environ["PATH"]

ANSWERS = "{{ _copier_answers|to_nice_yaml }}"
GITATTRIBUTES = "* annex.largefiles=(not(mimetype=text/*))\n"

STREAM_TEMPLATE = {
    "copier.yml": "_answers_file: .copier-answers.yml\n",
    "{{ _copier_conf.answers_file }}.jinja": ANSWERS,
    "README.md.jinja": "# {{ dataset_id }} from {{ instance }}\n",
    ".gitattributes": GITATTRIBUTES,
}

DERIVED_TEMPLATE = {
    "copier.yml": (
        "collection_url:\n  type: str\n  default: ''\n"
        "image:\n  type: str\n  default: images/tool-1.0.sif\n"
        "_answers_file: .copier-answers.yml\n"
    ),
    "{{ _copier_conf.answers_file }}.jinja": ANSWERS,
    "README.md.jinja": "# {{ title }}\n",
    ".gitattributes": GITATTRIBUTES,
    ".datalad/config.jinja": (
        "{% if collection_url %}"
        '[faire "collection.tools"]\n'
        "\turl = {{ collection_url }}\n"
        "\tpath = code/containers\n"
        "\trevision = v1\n"
        '[datalad "containers.tool"]\n'
        "\timage = code/containers/{{ image }}\n"
        "\tcmdexec = {img} {cmd}\n"
        "\tfaire-sourcedata = .\n"
        "{% endif %}"
    ),
}

SUPER_TEMPLATE = {
    "copier.yml": "_answers_file: .copier-answers.yml\n",
    "{{ _copier_conf.answers_file }}.jinja": ANSWERS,
    "README.md": "# Study\n",
    ".gitattributes": GITATTRIBUTES,
}


def git_template(path: Path, files: dict[str, str], tag: str = "v0.1.0") -> str:
    path.mkdir(parents=True)
    for name, text in files.items():
        (path / name).parent.mkdir(parents=True, exist_ok=True)
        (path / name).write_text(text)
    repo = GitRepo(str(path), create=True)
    repo.call_git(["add", "-A"])
    repo.call_git(["-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "template"])
    repo.call_git(["tag", tag])
    return str(path)


def collection(path: Path) -> str:
    ds = create(path=str(path), result_renderer="disabled")
    (path / "images").mkdir()
    (path / "images" / "tool-1.0.sif").write_bytes(b"\0image")
    ds.save(message="add tool 1.0", result_renderer="disabled")
    ds.repo.call_git(["tag", "v1"])
    return str(path)


@dataclass
class Env:
    root: Path
    stream_tpl: str
    derived_tpl: str
    super_tpl: str
    collection: str

    def dataset(self, ident, title, template, path=None, sources=(), instruments=(),
                distributions=(), data=None):
        d = {
            "title": title,
            "dataset_id": {"identifier": ident, "type": "other"},
            "personal_data": "no",
            "sensitive_data": "no",
            "faire": {"template": {"repository": template, "version": "v0.1.0"}},
            "distribution": list(distributions),
        }
        if data:
            d["faire"]["template"]["data"] = data
        if path:
            d["faire"]["path"] = path
        if sources:
            d["related_identifier"] = [
                {"identifier": s, "type": "other", "relation_type": "IsDerivedFrom"}
                for s in sources
            ]
        if instruments:
            d["technical_resource"] = [
                {"name": i, "faire": {"instrument_id": i, "site": "a"}} for i in instruments
            ]
        return d

    def dist(self, title, stage, url, wanted="anything"):
        return {"title": title, "data_access": "closed", "access_url": url,
                "faire": {"stage": stage, "wanted": wanted}}

    def doc(self) -> dict:
        ria = f"ria+file://{self.root / 'ria'}"
        tools = {"collection_url": self.collection}
        return {"dmp": {
            "title": "test study", "language": "eng", "ethical_issues_exist": "no",
            "created": "2026-11-21T00:00:00Z", "modified": "2026-11-21T00:00:00Z",
            "dmp_id": {"identifier": "https://example.org/dmp", "type": "url"},
            "contact": {"name": "x", "mbox": "x@example.org",
                        "contact_id": {"identifier": "x", "type": "other"}},
            "faire": {"sample_entities": ["subject", "session"],
                      "superdataset": {"template": {"repository": self.super_tpl,
                                                    "version": "v0.1.0"}}},
            "dataset": [
                self.dataset("dicoms", "scanner", self.stream_tpl,
                             instruments=["PrismaFit16001"],
                             distributions=[self.dist("Site storage", "collection", ria)]),
                self.dataset("physio", "physio", self.stream_tpl, instruments=["Biopac01"],
                             distributions=[self.dist("Site storage", "collection", ria)]),
                self.dataset("bids", "BIDS", self.derived_tpl, path="rawdata",
                             sources=["dicoms", "physio"], data=tools,
                             distributions=[
                                 self.dist("Site storage", "collection", ria),
                                 self.dist("Shared", "accepted",
                                           str(self.root / "shared" / "bids"),
                                           "not metadata=distribution-restrictions=*"),
                             ]),
                self.dataset("fmriprep", "fMRIPrep", self.derived_tpl,
                             path="derivatives/fmriprep", sources=["bids"], data=tools,
                             distributions=[self.dist(
                                 "Shared", "accepted",
                                 f"file://{self.root / 'shared' / 'fmriprep'}")]),
            ],
        }}


@pytest.fixture(scope="session")
def templates_root(tmp_path_factory) -> Path:
    root = tmp_path_factory.mktemp("templates")
    git_template(root / "stream", STREAM_TEMPLATE)
    git_template(root / "derived", DERIVED_TEMPLATE)
    git_template(root / "super", SUPER_TEMPLATE)
    collection(root / "tools")
    return root


def make_env(root: Path, templates_root: Path) -> Env:
    return Env(root, str(templates_root / "stream"), str(templates_root / "derived"),
               str(templates_root / "super"), str(templates_root / "tools"))


@pytest.fixture
def env(tmp_path, templates_root) -> Env:
    return make_env(tmp_path, templates_root)


def write_doc(path: Path, doc: dict) -> Path:
    path.write_text(json.dumps(doc, indent=1))
    return path


def by_id(doc: dict, ident: str) -> dict:
    return next(d for d in doc["dmp"]["dataset"] if d["dataset_id"]["identifier"] == ident)


def deep(doc: dict) -> dict:
    return copy.deepcopy(doc)


def commits(path: Path) -> str:
    return Dataset(path).repo.call_git(["rev-parse", "--all"])


REFERENCE = Path(__file__).parents[1] / "templates"


def git_template_dir(src: Path, dest: Path, tag: str = "v0.1.0") -> str:
    files = {str(p.relative_to(src)): p.read_text() for p in src.rglob("*") if p.is_file()}
    return git_template(dest, files, tag)


@dataclass
class Reference:
    """The repository's reference templates, as tagged git repositories."""

    stream: str
    standard: str
    superdataset: str
    collection: str


@pytest.fixture(scope="session")
def reference(tmp_path_factory) -> Reference:
    root = tmp_path_factory.mktemp("reference")
    col = root / "toy-collection"
    ds = create(path=str(col), result_renderer="disabled")
    (col / "images").mkdir()
    (col / "images" / "toy-1.0.sh").write_text(
        (REFERENCE / "toy-collection" / "images" / "toy-1.0.sh").read_text())
    ds.save(message="toy 1.0", result_renderer="disabled")
    ds.repo.call_git(["tag", "v1"])
    return Reference(
        git_template_dir(REFERENCE / "stream", root / "stream"),
        git_template_dir(REFERENCE / "standard", root / "standard"),
        git_template_dir(REFERENCE / "superdataset", root / "superdataset"),
        str(col),
    )


def reference_doc(env: Env, ref: Reference) -> dict:
    """Two streams feeding one standard dataset, all from the reference templates."""
    ria = f"ria+file://{env.root / 'ria'}"
    doc = env.doc()
    doc["dmp"]["faire"]["superdataset"]["template"]["repository"] = ref.superdataset
    doc["dmp"]["dataset"] = [
        env.dataset("dicoms", "scanner", ref.stream, instruments=["PrismaFit16001"],
                    distributions=[env.dist("Site storage", "collection", ria)]),
        env.dataset("physio", "physio", ref.stream, instruments=["Biopac01"],
                    distributions=[env.dist("Site storage", "collection", ria)]),
        env.dataset("bids", "BIDS", ref.standard, path="rawdata", sources=["dicoms", "physio"],
                    data={"collection_url": ref.collection},
                    distributions=[env.dist("Site storage", "collection", ria)]),
    ]
    return doc
