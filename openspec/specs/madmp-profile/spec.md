# madmp-profile Specification

## Purpose

Defines the minimal extension of the RDA DMP Common Standard v1.3 that makes a data management plan executable by faire, and how a plan is validated against it.

## Requirements

### Requirement: Conformance to the base standard
A profile-conformant ma-DMP SHALL be a valid RDA DMP Common Standard v1.3 document. All profile additions SHALL be carried under a property named `faire` on the objects they extend.

#### Scenario: Extension removed
- **WHEN** every `faire` property is removed from a conformant ma-DMP
- **THEN** the result validates against the v1.3 schema

### Requirement: Dataset identity
Each dataset SHALL have a `dataset_id` unique within the document. That identifier SHALL be used for every reference between datasets.

#### Scenario: Duplicate identifier
- **WHEN** two datasets carry the same identifier
- **THEN** validation fails and names it

### Requirement: Dataset template
Each dataset SHALL declare its template: a git repository, a pinned version, and optional template data.

#### Scenario: Unpinned template
- **WHEN** a dataset's template has no version
- **THEN** validation fails and names the dataset

### Requirement: Path in the study superdataset
A dataset MAY declare a relative path in the study superdataset. Path segments SHALL NOT contain `.` and paths SHALL be unique. A dataset declaring instruments SHALL NOT declare a path.

#### Scenario: Derivative path
- **WHEN** a dataset declares path `derivatives/fmriprep`
- **THEN** validation succeeds

#### Scenario: Dot in a segment
- **WHEN** a dataset declares path `derivatives/fmri.prep`
- **THEN** validation fails and names the dataset

### Requirement: Study superdataset
The study superdataset SHALL be a dataset of the plan declaring path `.`. At most one dataset SHALL declare it; it SHALL have no sources and no instruments, and it SHALL exist when any other dataset declares a path. Its distributions follow the same rules as any dataset's.

#### Scenario: Superdataset with annexed content
- **WHEN** the dataset with path `.` declares a `release` distribution with a RIA URL
- **THEN** validation succeeds and the superdataset's history and wanted content go to that store

#### Scenario: Paths without a superdataset
- **WHEN** datasets declare paths and none declares `.`
- **THEN** validation fails

### Requirement: Sources
A dataset derived from datasets of the plan SHALL declare each source with the standard's `related_identifier`, relation type `IsDerivedFrom`, and the source's `dataset_id`. These links SHALL form a directed acyclic graph. Links whose identifier matches no dataset of the plan and uses an external identifier type (for example a DOI) are not sources.

#### Scenario: Several sources
- **WHEN** `bids` is derived from `dicoms`, `physio` and `notes`
- **THEN** validation succeeds and reports three sources

#### Scenario: Cycle
- **WHEN** the links form a cycle
- **THEN** validation fails and lists the datasets in it

### Requirement: Instruments
An instrument or data-capture system producing collected data SHALL be declared with the standard's `technical_resource` on the dataset it feeds, with an instrument identifier and a site in the extension. A dataset declaring instruments is a sourcedata stream, realised as one instance named `<site>_<instrument>` per instrument. A stream SHALL have no sources.

#### Scenario: Two instruments
- **WHEN** stream `dicoms` declares `PrismaFit16001` at site `a` and `Skyra45012` at site `a`
- **THEN** tooling reports instances `a_PrismaFit16001` and `a_Skyra45012`

#### Scenario: Missing site
- **WHEN** an instrument has no site
- **THEN** validation fails and names it

### Requirement: Sample entities
The `dmp` SHALL declare the ordered entity names identifying a sample (for example `subject`, `session`).

#### Scenario: No entities
- **WHEN** the `dmp` declares no sample entities
- **THEN** validation fails

### Requirement: Distribution stage and content
Each distribution SHALL declare a stage, one of `collection`, `accepted`, `release`, and a git-annex preferred-content expression (`wanted`) selecting the content it receives.

#### Scenario: Unknown stage
- **WHEN** a distribution declares stage `archival`
- **THEN** validation fails and names the distribution

### Requirement: Distribution location
Each distribution SHALL give a DataLad-resolvable URL in the standard's `access_url`. The URL SHALL NOT carry credentials.

#### Scenario: Credentials in the URL
- **WHEN** an `access_url` contains a password or token
- **THEN** validation fails and names the distribution

### Requirement: Validation command
`faire validate <file>` SHALL check the base schema, the profile and the rules above, report every violation with its location, and exit non-zero on any violation.

#### Scenario: Valid plan
- **WHEN** a conformant ma-DMP is validated
- **THEN** the command exits with status zero
