## MODIFIED Requirements

### Requirement: Human approval
Sessions SHALL be merged only by `faire merge`, never through the platform. On a session branch, `faire merge` SHALL refuse unless the session pull request has one human approval and the latest pipeline of its head passed; otherwise it SHALL merge the branch into its target with a merge commit, following the dataset's date settings, and push it. The pull request is then reported merged by the platform.

#### Scenario: Checks pass
- **WHEN** all blocking checks pass and nobody approved
- **THEN** `faire merge` fails and the target branch is unchanged

#### Scenario: Approved
- **WHEN** the pull request is approved and its pipeline passed
- **THEN** the target branch has a merge commit of the session and the pull request is reported merged

## ADDED Requirements

### Requirement: Date check before release
For each dataset of the release whose configuration enables fake dates, the superdataset included, `faire release` SHALL run `datalad check-dates` on the released commit and fail before any push if it reports a date.

#### Scenario: Real-dated commit
- **WHEN** a fake-dated dataset contains a commit made with the real date
- **THEN** the release fails before any push, naming the dataset and the commit
