# dataset-lifecycle Specification

## Purpose

Defines how data moves through branches and stages: one reviewed pull request per session, completeness tracked per stream, cascade to derived datasets, and study-wide release.

## Requirements

### Requirement: Branches and stages
Streams SHALL have a single `dev` branch. Standard and derived datasets SHALL use `base` for source pointers and configuration (template content, rules, checks), `dev` for accepted data, `pilot` for pilot data (never merged into `dev`), and `convert/<sample>` or `convert-pilot/<sample>`, started from `base`, for sessions under review. The superdataset SHALL use `dev`, `rel/<version>` and `main`.

#### Scenario: Pilot isolation
- **WHEN** a sample marked pilot is converted
- **THEN** its branch `convert-pilot/<sample>` starts from `base` and targets `pilot`, and `dev` is unchanged

#### Scenario: Session diff
- **WHEN** a session pull request is opened
- **THEN** its changes against `dev` are only that sample's outputs and status

### Requirement: Stages
Stage `collection` SHALL cover stream `dev` and session branches, `accepted` the `dev` branches of standard, derived and superdataset, and `release` the `rel/*` branches of the superdataset.

#### Scenario: Accepted superdataset
- **WHEN** the superdataset declares an `accepted` distribution
- **THEN** its `dev` is synced there

### Requirement: Downstream update
A push to `dev` of a stream or a session merge into `dev` SHALL start `update` on `base` of every dataset derived from it; a push to `base` SHALL start its own. `update` SHALL commit the source pointers at their sources' `dev` heads on `base`, recomputing them on the latest `base` when another update pushed first, then merge `base` into `dev`, `pilot` and every open session branch, and open sessions.

#### Scenario: New session
- **WHEN** session `sub-01 ses-001` is indexed in `dicoms`
- **THEN** `bids` `base` points at the new `dicoms` commit, and `bids` has branch `convert/sub-01_ses-001` and a draft pull request

#### Scenario: Late stream
- **WHEN** physio is indexed while two `bids` branches have `physio` pending
- **THEN** `base` is merged into both, which then see the new physio files

#### Scenario: Rule fixed
- **WHEN** a rule's command is changed on `base`
- **THEN** `update` merges the change into every open session branch

### Requirement: Session opening
`update` SHALL open `convert/<sample>`, or `convert-pilot/<sample>` for a sample indexed as pilot, with a draft pull request, for each sample of a primary source having no run record on its target branch and no open branch.

#### Scenario: Already converted
- **WHEN** a sample's session was merged into `dev`
- **THEN** no branch is opened for it again

### Requirement: Session status
faire SHALL maintain per-subject `sessions.tsv` and `participants.tsv` columns, one per source stream, with values `present`, `pending`, `partial` or `missing`, described with their levels in the JSON sidecar, and record each update as a re-executable step. A column is `pending` until a rule consuming that stream produced output for the sample.

#### Scenario: Status after conversion
- **WHEN** `heudiconv` produced output and `bidsphysio` has not
- **THEN** the row shows `dicoms` present and `physio` pending

### Requirement: Completeness blocks merging
A built-in blocking check SHALL fail while any stream of the session is `pending`.

#### Scenario: Pending stream
- **WHEN** a session has `physio` pending
- **THEN** the check fails and names the stream

### Requirement: Reviewer waiver
`faire mark --sample <entities> <stream>=missing` SHALL set `partial` when converted output for the stream exists and `missing` otherwise, commit it to the session branch recording who marked it, and SHALL pass the output patterns of waived streams to checks so they treat those files as optional. It SHALL be runnable as a manual CI job, by a comment command where the platform supports it, and from the command line.

#### Scenario: Partial physio
- **WHEN** physio exists for two of three runs and the reviewer marks it missing
- **THEN** the status becomes `partial` and completeness passes with a warning

### Requirement: Human approval
A session pull request SHALL be mergeable only with passing blocking checks and one human approval, and SHALL NOT be squashed.

#### Scenario: Checks pass
- **WHEN** all blocking checks pass and nobody approved
- **THEN** the pull request cannot be merged

### Requirement: Release branch
`faire release` on `rel/<version>` of the superdataset SHALL bump every subdataset pointer to its dataset's `dev` head, then fail if any `sourcedata/` pointer is not an ancestor of the commit referenced for its source, and report derived datasets missing sessions of their sources.

#### Scenario: Lagging derivative
- **WHEN** `fmriprep` points at an older `bids` commit that is an ancestor of the released one
- **THEN** the release proceeds and reports the sessions `fmriprep` lacks

#### Scenario: Diverged pointer
- **WHEN** a `sourcedata/` pointer is not an ancestor of its source's released commit
- **THEN** the release fails before any push, naming the dataset

### Requirement: Release checks before publication
After the consistency checks, the release SHALL run checks of stage `release`, then fulfil `release` distributions, then fail unless every referenced commit and its wanted content is present on every release remote. Nothing SHALL be pushed to release remotes before the release checks pass.

#### Scenario: Security check fails
- **WHEN** a blocking release-stage check fails
- **THEN** no content is pushed to any release remote

### Requirement: Tag when reachable
Merging `rel/<version>` into `main` with human approval SHALL tag the superdataset and each dataset at its referenced commit with the version and push the tags. No tag SHALL exist before the reachability check passed.

#### Scenario: Release complete
- **WHEN** the release pull request is merged
- **THEN** tag `<version>` exists on the superdataset and on every dataset it references
