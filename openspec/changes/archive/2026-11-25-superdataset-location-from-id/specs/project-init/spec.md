# Spec Delta

## MODIFIED Requirements

### Requirement: Platform repositories
With a platform configured, init SHALL create a repository per dataset at `<group>/<path>` (as subgroups, or with `/` replaced by `.` on platforms without subgroups), stream instances at `<group>/sourcedata/<stream>/<site>_<instrument>`, and the superdataset at `<group>/<dataset_id>`. Without a platform, init SHALL create the same structure locally.

#### Scenario: Flat platform
- **WHEN** init targets a platform without subgroups and a dataset has path `derivatives/fmriprep`
- **THEN** its repository is named `derivatives.fmriprep`

#### Scenario: Local mode
- **WHEN** init runs without a platform
- **THEN** the same datasets, links and remotes exist locally and no platform request is made

#### Scenario: Superdataset named after the study
- **WHEN** the dataset with path `.` has identifier `studyx`
- **THEN** its repository is `<group>/studyx`
