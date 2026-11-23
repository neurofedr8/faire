## ADDED Requirements

### Requirement: Fake dates
A template SHALL enable fake dates by committing `datalad.fake-dates = true` in `.datalad/config`. In a dataset rendered from it, every commit and tag faire makes, from the dataset's first commit, SHALL carry DataLad fake dates. The `base` template SHALL document the setting.

#### Scenario: From creation
- **WHEN** init creates a dataset from a template enabling fake dates
- **THEN** no commit of the dataset, on any branch including `git-annex`, is dated after 2018-01-01, the default reference of `datalad check-dates`
