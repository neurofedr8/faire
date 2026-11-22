# data-distribution Specification

## Purpose

Fulfils the distributions the ma-DMP binds to each lifecycle stage by pushing history and selected content with DataLad and git-annex.

## Requirements

### Requirement: Sync per stage
`faire sync --stage <stage>` SHALL push, for each dataset concerned, the stage's branch or tags and the annexed content matching each distribution's `wanted` expression to that distribution's remote. `--distribution` SHALL restrict it to one distribution.

#### Scenario: Accepted
- **WHEN** a session is merged into `dev` of `bids` with an `accepted` distribution
- **THEN** `dev` and its wanted content are on that remote

### Requirement: Content selected by `wanted`
Each remote SHALL carry its distribution's `wanted` expression as preferred content, so that any later push honours it.

#### Scenario: Excluded content
- **WHEN** a file's content does not match a remote's `wanted` expression
- **THEN** sync does not send it and a plain `datalad push` does not either

### Requirement: Release remotes on first use
A `release` remote SHALL be created at its first fulfilment, by a method inferred from the `access_url` (RIA store, plain sibling, `datalad-annex` URL, or known forge API); a URL matching none of these SHALL be required to exist already.

#### Scenario: First release to GIN
- **WHEN** a release distribution's URL points at GIN and the repository does not exist
- **THEN** sync creates it and pushes

### Requirement: Credentials from the environment
Credentials SHALL come from the CI environment or the user's configuration and SHALL NOT be written to the ma-DMP or any dataset.

#### Scenario: Missing credential
- **WHEN** a remote needs a credential that is not provided
- **THEN** sync fails naming the distribution, before any transfer

### Requirement: Resumable
Re-running sync after an interruption SHALL transfer only what is missing.

#### Scenario: Interrupted release
- **WHEN** a release push is interrupted and sync runs again
- **THEN** content already on the remote is not sent again

### Requirement: Resolvable without the platform
A released tree SHALL be installable from the release remotes alone, its subdataset references resolving there.

#### Scenario: Platform gone
- **WHEN** a user clones the released superdataset from its release remote with the platform unreachable
- **THEN** its subdatasets install from the release remotes
