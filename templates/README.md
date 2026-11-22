# Reference templates

Copier templates used by the tests and as starting points. Publish each one as its own git
repository (with tags) to reference it from a ma-DMP.

Starting points for a study's own dataset templates (copy one, then edit; see
`base/TEMPLATE.md`):

- `base/`: the fixed CI and no rule or check; `.datalad/config` only has a commented example.
- `standard/`: a converted dataset, with placeholder rules converting a stream and processing
  the dataset's own output, and a blocking and an advisory check.
- `derivative/`: a dataset derived from another of the plan, with one placeholder rule and
  checks.

The placeholders (`TODO` images and commands) must be replaced: a dataset rendered from an
unedited starter fails `faire init`, naming the containers whose image is missing.

Others:

- `stream/`: a sourcedata stream instance, with an example indexing heuristic.
- `superdataset/`: the study superdataset.
- `toy-standard/`: a standard dataset with every kind of rule and check, run by the tests.
- `toy-collection/`: files of a toy container collection (a DataLad dataset in use); its
  "image" is a shell script run with `sh`, so rules work without a container runtime.

Each template ships the same fixed `.gitlab-ci.yml`: it only runs `faire plan --ci-render gitlab`
and executes the rendered child pipeline, so what runs is decided by the branch and the dataset.
