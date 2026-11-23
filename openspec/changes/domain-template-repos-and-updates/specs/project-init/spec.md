## MODIFIED Requirements

### Requirement: Non-additive edits reported
A changed template repository, template data, source list or path of an existing dataset, or a removed dataset, SHALL NOT be applied; init SHALL report each difference and exit non-zero. A changed template version is applied as a template update.

#### Scenario: Removed dataset
- **WHEN** an existing dataset is no longer in the plan
- **THEN** init reports it and deletes nothing

## ADDED Requirements

### Requirement: Template updates
When the pinned template version of an existing dataset changes, init SHALL render the recorded and the new version with the recorded answers, apply the difference to the dataset's `base` with the new version recorded, and propose it as a pull request on `base`. Re-running init while that pull request is open SHALL NOT open another.

#### Scenario: Fix in a rule
- **WHEN** the ma-DMP moves `bids` from `v1.3.0` to `v1.3.1`, which changes a rule command
- **THEN** `bids` has a pull request on `base` changing that command and its recorded version, and `base` is unchanged until it is merged

#### Scenario: Merged update
- **WHEN** the update pull request is merged into `base`
- **THEN** `update` merges it into `dev`, `pilot` and every open session branch, and sessions already merged are not re-run

### Requirement: Unchanged rendering
When the recorded and the new version render the same content for a dataset, init SHALL record the new version on its `base` without a pull request.

#### Scenario: Fix in another template
- **WHEN** the study moves to `v1.3.1`, which only changes the `bids` template
- **THEN** `fmriprep` records `v1.3.1` on `base` and has no pull request

### Requirement: Refused updates
Init SHALL fail the update of a dataset, leave it unchanged and name the cause when the difference conflicts with the dataset's `base` or changes the fake-dates setting.

#### Scenario: Conflict
- **WHEN** a file changed by the update was also edited on the dataset's `base`
- **THEN** init reports the dataset and the conflicting files, exits non-zero, and opens no pull request

#### Scenario: Fake dates toggled
- **WHEN** the new version enables fake dates that the recorded version did not
- **THEN** init refuses the update for that dataset
