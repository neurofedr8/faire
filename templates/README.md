# Reference templates

Copier templates used by the tests and as starting points. Publish each one as its own git
repository (with tags) to reference it from a ma-DMP.

- `stream/`: a sourcedata stream instance, with an example indexing heuristic.
- `standard/`: a standard dataset with every kind of rule and check, as container entries.
- `superdataset/`: the study superdataset.
- `toy-collection/`: files of a toy container collection (a DataLad dataset in use); its
  "image" is a shell script run with `sh`, so rules work without a container runtime.

Each template ships the same fixed `.gitlab-ci.yml`: it only runs `faire plan --ci-render gitlab`
and executes the rendered child pipeline, so what runs is decided by the branch and the dataset.
