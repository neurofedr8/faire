## ADDED Requirements

### Requirement: Template collections
A template repository MAY hold several templates and choose the one to render from a template data answer. faire SHALL render and record such a dataset like any other, the answer included, so that datasets of one study can pin the same repository and version with different answers.

#### Scenario: One repository, several datasets
- **WHEN** `bids` and `fmriprep` pin the same repository and version, with answers `kind: bids` and `kind: fmriprep`
- **THEN** each dataset is rendered from its own template and records the repository, version and its answer

#### Scenario: Selection changed
- **WHEN** the answer selecting the template of an existing dataset changes in the ma-DMP
- **THEN** init reports it as a non-additive edit and changes nothing
