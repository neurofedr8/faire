## MODIFIED Requirements

### Requirement: Branches and platform policies
Init SHALL create `base` as the default branch of each standard and derived dataset, with `dev` and `pilot` starting from it. It SHALL protect `base`, `dev`, `pilot` and session branches, and allow no one to merge into `dev` or `pilot` through the platform; squash merges SHALL stay forbidden.

#### Scenario: Base branch
- **WHEN** init creates `bids`
- **THEN** `base` is its default branch, holding the rendered template and source pointers, and `dev` and `pilot` start from it

#### Scenario: No platform merge
- **WHEN** init configures a dataset repository
- **THEN** the platform refuses to merge a pull request into `dev` or `pilot`

#### Scenario: Squash forbidden
- **WHEN** init configures a dataset repository
- **THEN** the platform rejects squash merges for it
