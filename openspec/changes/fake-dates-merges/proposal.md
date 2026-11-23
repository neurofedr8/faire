# Proposal

## Why

For some data, commit dates must not reveal when data was acquired. DataLad fake dates cover every commit faire makes, but a session merged through GitLab gets a merge commit with the real date. Because DataLad dates each new commit one second after the newest one, every later commit then gets a near-real date too.

## What Changes

- A template enables fake dates by committing `datalad.fake-dates = true`; faire fake-dates every commit and tag it makes in such datasets, from the first commit.
- **BREAKING** faire performs every session merge: a manual `faire merge` job in the session pipeline checks for one human approval and a passing pipeline, then merges with DataLad and pushes. Merging through the platform UI is disabled for `dev` and `pilot`.
- `faire release` runs `datalad check-dates` on each fake-dated dataset before anything is published, and fails if a real date is found.

## Capabilities

### New Capabilities

### Modified Capabilities
- `dataset-templates`: templates can enable fake dates, and faire honours them from creation.
- `dataset-lifecycle`: the human-approval requirement becomes "faire merges after approval"; release adds a date check.
- `processing-rules`: the session plan adds a manual merge job.
- `project-init`: platform policies disable UI merges instead of requiring approvals.

## Impact

`faire init` (dataset creation), `faire plan` (session pipeline), new `faire merge` command, `faire release`, platform adapters (approval and pipeline queries, branch protection), `templates/base` (documented setting), docs. No new dependency.
