## Why

Research projects using DataLad still wire up datasets, provenance, containers, CI and publication by hand, and their data management plan stays a document nobody executes. Extending the RDA DMP Common Standard just enough for a tool to act on it lets one machine-actionable DMP (ma-DMP) create the project, drive each acquisition session from raw data to reviewed standard and derived datasets, and push data where the plan says, at the right stage.

## What Changes

- A **light profile of RDA DMP Common Standard v1.3**: per dataset, a copier template and an optional path in the study superdataset; sources through the standard's `related_identifier` (`IsDerivedFrom`); instruments as `technical_resource` on the sourcedata streams they feed; per distribution, a lifecycle stage and a git-annex `wanted` expression, with the DataLad URL in the standard's `access_url`. A conformant ma-DMP stays a valid v1.3 document.
- A **`faire` tool** with a few commands:
  - `validate` and `init`: create every dataset from its template, link sources as `sourcedata/` subdatasets, create storage remotes and platform repositories, and render the study superdataset from its own template; re-running applies additive edits.
  - `index`: add received raw files to a sourcedata stream, guided by a heuristic versioned in that stream.
  - `plan`, `run`, `test`, `mark`, `status`: processing rules and checks declared as DataLad container entries; one branch and pull request per session; secondary streams and in-place tools commit to that branch, in parallel; a per-session status table blocks merging until every stream is converted or waived by a reviewer.
  - `sync` and `release`: push to the distributions of a stage; release from a `rel/x.y.z` branch of the superdataset, tagged only once data is reachable.
- **CI integration** through `plan --ci-render gitlab|github`, with GitLab as the reference platform and a single-job fallback.

Out of scope for this iteration (listed as future work in `design.md`): federation across sites, writing facts back into the ma-DMP, DOIs, fetching data from external systems, sensitive-file marking (left to conversion tools).

## Capabilities

### New Capabilities

- `madmp-profile`: the extension of the RDA DMP standard and its validation.
- `project-init`: creating and reconciling datasets, superdataset, remotes and platform repositories from the ma-DMP.
- `data-indexing`: adding received raw data to sourcedata streams.
- `processing-rules`: rules and checks declared in container entries, planning, running and CI rendering.
- `dataset-lifecycle`: branches, stages, per-session pull requests and status, downstream cascade, release.
- `data-distribution`: fulfilling distributions per stage with git-annex.

### Modified Capabilities

None. The project has no existing specs.

## Impact

- **New code**: the `faire` Python package, a profile schema, a reference dataset template and a reference superdataset template.
- **Dependencies**: DataLad, datalad-container, git-annex, copier, a JSON Schema validator, python-gitlab.
- **External systems**: a DevOps platform with CI runners (GitLab first), storage hosts reachable by DataLad URLs.
- **Security**: no credentials in the ma-DMP; what leaves the site is limited by `wanted` expressions and release-stage checks.
