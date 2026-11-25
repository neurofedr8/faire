# Stages, branches and release

## Branches

| Repository | Branches |
|---|---|
| sourcedata stream instance | `dev`: everything indexed; pilot items carry a `faire-pilot: true` trailer |
| standard or derived dataset | `base`: template content, rules, checks and `sourcedata/` pointers; `dev`: accepted data; `pilot`: pilot data, never merged into `dev`; `convert/<sample>` and `convert-pilot/<sample>`: one session under review each |
| superdataset (path `.`) | `dev`: registered datasets and the ma-DMP; `rel/<version>`: a release in preparation; `main`: released versions, tagged |

Upstream changes land on `base` only. The `update` task (`faire run --task update`, planned
on `base`) points the sources at their `dev` heads, merges `base` into `dev`, `pilot` and every
open session, and opens a session branch with a draft pull request for each new sample of a
primary source. A session branch therefore differs from `dev` by its sample's outputs and
status only. Sessions are merged by faire, never through the platform: once the blocking
checks (including `completeness`) passed, the session pipeline offers a manual `merge` job.
`faire merge` refuses unless the pull request has a human approval and the branch is still at
the checked commit; it then merges with a merge commit (never squashed, so run records
survive), pushes the target and deletes the session branch. Because faire makes the merge
commit, datasets whose template sets `datalad.fake-dates = true` keep fake dates throughout,
and `faire release` refuses to publish one whose history holds a real date.

A merge into `dev` syncs the `accepted` distributions and triggers the `base` pipeline of the
datasets derived from this one. Pilots do not cascade.

## Stages

| Stage | Covers | Fulfilled by |
|---|---|---|
| `collection` | stream `dev`, session branches | `faire index` and `faire run`, to `collection-*` remotes |
| `accepted` | `dev` of standard, derived and superdataset | `faire sync --stage accepted` on `dev` |
| `release` | `rel/*` of the superdataset | `faire release` |

A distribution's `wanted` expression is set as the remote's preferred content, so later plain
`datalad push` calls honour it too.

## Indexing

`faire index <instance> <directory>` adds received items to one stream instance, given as a
local clone or a repository URL (cloned once into `--clone`, default `./<repository name>`, and
reused). It needs nothing else: the ma-DMP copy, the heuristic and the `collection` remotes come
from the instance, whose `dev` is first fast-forwarded to `origin`. Items the heuristic
attributes to another instrument than the instance's are refused. Content goes to the existing
`collection` remotes (created by `faire init`) before history is pushed to `origin`, over HTTPS
with `FAIRE_GITLAB_TOKEN` when set.

## Release

1. Create `rel/<version>` from the superdataset's `dev`. Its pipeline runs `faire release`:
   - every registered dataset is pointed at its `dev` head (once per version), and its first
     `release` distribution is recorded as `datalad-url` in `.gitmodules`, so the released tree
     installs without the platform;
   - each `sourcedata/` pointer to a registered dataset must be an ancestor of that dataset's
     released commit, otherwise the release stops before any push;
   - derived datasets lacking samples of their sources are reported (not blocking);
   - blocking checks of stage `release` (for instance a sensitivity or security check) must
     pass, otherwise nothing is pushed;
   - each dataset's commit is pushed as `rel/<version>` with its wanted content to every
     `release` distribution, creating the remote on first use;
   - every commit and its wanted content must then be on every release remote;
   - `rel/<version>` is pushed and a pull request to `main` opened.
2. A person reviews and merges the pull request. The `main` pipeline runs
   `faire release --tag`: it refuses if `main` differs from the released branch, checks
   reachability again, tags the superdataset and every dataset `<version>` at the released
   commits, and pushes the tags (and `main` at the tag) to origin and release remotes.

No tag exists before the data is reachable. Re-running `faire release` transfers only what is
missing.

Raw sourcedata streams are not released: they are not registered in the superdataset, and a
released tree's `sourcedata/` subdatasets are not expected to install.
