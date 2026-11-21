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

## CI variables and jobs

Set on the root group:

| Variable | Purpose |
|---|---|
| `FAIRE_GITLAB_TOKEN` | masked; faire pushes, opens merge requests and starts pipelines with it (the job token can do none of these across projects) |
| `FAIRE_IMAGE` | image running every job: one with faire, DataLad, datalad-container and git-annex, or a stock image plus `FAIRE_SETUP` |
| `FAIRE_SETUP` | optional shell commands run first in every job, e.g. installing faire on `alpine:3` |

Every job checks out the latest head of its branch (jobs of a wave push one after the other),
resets `origin` to the project URL and removes the runner's `insteadOf` rules that rewrite
server URLs to the job token, so subdatasets and pushes authenticate with
`FAIRE_GITLAB_TOKEN` through an in-process credential helper. The templates' fixed
`.gitlab-ci.yml` and the rendered child pipelines share these steps
(`faire.tasks.BEFORE_SCRIPT`).

Pushes that must not start work skip CI: init's pushes, task pushes within a wave, `update`'s
pushes to `base`, `dev` and `pilot`, tags, and pushes to release repositories on the same
server. Pushes that end a wave, open or update a session, or record a release start one.

A downstream trigger job runs as the user who started the pipeline, who needs the Developer
role on the downstream project. Approval rules need a paid tier; on the free tier faire skips
them and merging relies on the passing pipeline and the reviewer.

Release distributions may be GitLab projects (`https://<server>/<path>.git`): faire creates
them on first use. They carry git only, so their `wanted` content must live in git.

## Testing against a GitLab instance

`tests/test_gitlab_live.py` runs one session from indexing to a release tag on a real GitLab
with the rendered pipelines. Set `FAIRE_TEST_GITLAB_URL`, `FAIRE_TEST_GITLAB_TOKEN` (a group
access token, Owner, `api` scope) and optionally `FAIRE_TEST_GITLAB_GROUP` (default
`faire_dev`). It works in a new subgroup, pushes this working tree there for `FAIRE_SETUP` to
install on `alpine:3`, and deletes the subgroup afterwards unless `FAIRE_TEST_KEEP` is set. A
run takes about 30 minutes.

When a new instrument is added to the ma-DMP, init creates its project and opens a merge request
`faire/register-<stream>-<instance>` on every dataset derived from the stream.

Secrets for storage hosts are CI variables set by operators; they never appear in the ma-DMP.
