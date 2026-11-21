# Using faire with GitLab

`faire init` creates one GitLab project per repository of the study under a root group:

| Repository | GitLab project |
|---|---|
| dataset with `path: derivatives/fmriprep` | `<group>/derivatives/fmriprep` (subgroup `derivatives`) |
| dataset without a path | `<group>/<dataset_id>` |
| stream instance `a_PrismaFit16001` of `dicoms` | `<group>/sourcedata/dicoms/a_PrismaFit16001` |
| study superdataset | `<group>/superdataset` |

Subdatasets refer to each other with relative URLs (`../../rawdata`), so the whole tree also
resolves from any mirror with the same layout.

## Running init

```
export FAIRE_GITLAB_TOKEN=<token>      # never written to disk or to remote URLs
faire init dmp.json --platform gitlab --platform-url https://gitlab.example.org \
    --group lab/studyx --workdir ./studyx
```

The token needs the `api` scope and the right to create projects and subgroups in the group
(Maintainer or Owner). Git authenticates with the same token through an in-process credential
helper.

`--workdir` holds one working clone per repository. It is disposable: a later run in an empty
directory clones what exists and reports only real differences. Use `--dry-run` to see what a
run would do.

## What init configures on each project

- Default branch `base` for standard and derived datasets, `dev` for streams and the
  superdataset.
- Protected branches: `base`, `dev`, `pilot`, `convert/*` and `convert-pilot/*` for datasets;
  `dev` for streams; `dev`, `main` and `rel/*` for the superdataset. Protection also exposes
  protected CI variables to session branches.
- Merge policy: merge commits only (no squash, no rebase, so run records survive), a passing
  pipeline, and one approval through an approval rule named `faire: human approval`.
  Approval rules need a GitLab tier that provides them.
- A copy of the ma-DMP in `.faire/dmp.json` (`dmp.json` in the superdataset), from which
  pipelines derive distributions and the downstream projects to trigger. Re-running init
  updates it after an edit.

Pipelines need a CI variable `FAIRE_IMAGE` (an image with faire installed) and
`FAIRE_GITLAB_TOKEN` (opening merge requests, starting the next wave). A downstream trigger
job runs as the user who started the pipeline, who needs the Developer role on the downstream
project.

When a new instrument is added to the ma-DMP, init creates its project and opens a merge request
`faire/register-<stream>-<instance>` on every dataset derived from the stream.

Secrets for storage hosts are CI variables set by operators; they never appear in the ma-DMP.
