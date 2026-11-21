# Stages, branches and release

## Branches

| Repository | Branches |
|---|---|
| sourcedata stream instance | `dev`: everything indexed; pilot items carry a `faire-pilot: true` trailer |
| standard or derived dataset | `base` (default): template content, rules, checks and `sourcedata/` pointers; `dev`: accepted data; `pilot`: pilot data, never merged into `dev`; `convert/<sample>` and `convert-pilot/<sample>`: one session under review each |
| superdataset (path `.`) | `dev`: registered datasets and the ma-DMP; `rel/<version>`: a release in preparation; `main`: released versions, tagged |

Upstream changes land on `base` only. The `update` task (`faire run --task update`, planned
on `base`) points the sources at their `dev` heads, merges `base` into `dev`, `pilot` and every
open session, and opens a session branch with a draft pull request for each new sample of a
primary source. A session branch therefore differs from `dev` by its sample's outputs and
status only. Merging it needs passing blocking checks (including `completeness`) and one
human approval; squash merges are refused so run records survive.

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
