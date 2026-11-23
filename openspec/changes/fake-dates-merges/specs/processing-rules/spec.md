## MODIFIED Requirements

### Requirement: Plan
`faire plan` SHALL decide from the branch: on `base`, the `update` task; on `dev` or `pilot`, `accepted` distributions and triggers of downstream datasets' `base`; on a session branch, the due tasks (id, rule, sample, order constraints, runner) followed by `faire status`, or the checks, a manual waiver job per pending stream and a manual `faire merge` job when no task is due; on the superdataset's `rel/*` and `main`, the release steps.

#### Scenario: Branch decides
- **WHEN** plan runs on `base`
- **THEN** it plans only `update`

#### Scenario: Settled session
- **WHEN** plan runs on a session branch with no task due
- **THEN** it plans the checks and a manual merge job
