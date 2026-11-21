## Purpose

Defines how data moves through branches and stages: one reviewed pull request per session, completeness tracked per stream, cascade to derived datasets, and study-wide release.

## ADDED Requirements

### Requirement: Branches and stages
Datasets SHALL use `dev` for accepted data, `pilot` for pilot data (never merged into `dev`) and `convert/<sample>` for sessions under review. The superdataset SHALL use `dev`, `rel/<version>` and `main`. Stage `collection` covers stream branches and session branches, `accepted` covers `dev` of standard and derived datasets, and `release` covers `rel/*` branches of the superdataset.

#### Scenario: Pilot isolation
- **WHEN** a pilot session is converted
- **THEN** its branch starts from and targets `pilot`, and `dev` is unchanged

### Requirement: Downstream trigger
A push to `dev` or `pilot` of a stream, and a merge into `dev` or `pilot` of a dataset, SHALL trigger every dataset listing it as a source. A triggered dataset SHALL create `convert/<sample>` with a draft pull request for each sample of a primary source having no run record and no open branch, and SHALL bump the source pointer on every open branch whose status for that source is `pending`.

#### Scenario: New session
- **WHEN** session `sub-01 ses-001` is indexed in `dicoms`
- **THEN** `bids` has branch `convert/sub-01_ses-001` and a draft pull request

#### Scenario: Late stream
- **WHEN** physio is indexed while two `bids` branches have `physio` pending
- **THEN** both branches get the new `sourcedata/physio` pointer

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
