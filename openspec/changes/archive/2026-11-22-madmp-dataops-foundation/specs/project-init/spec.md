## Purpose

Turns a valid ma-DMP into a working project: one DataLad dataset per planned dataset, linked to its sources, with storage remotes and platform repositories, gathered in a study superdataset, and kept in step with additive edits.

## ADDED Requirements

### Requirement: Init from a ma-DMP
`faire init` SHALL refuse an invalid ma-DMP. Otherwise it SHALL create one DataLad dataset per dataset of the plan, one per instrument instance for streams, in an order where sources exist before the datasets derived from them. Each dataset SHALL record the `dataset_id` it realises.

#### Scenario: Chain
- **WHEN** the plan declares `dicoms`, `bids` derived from it, and `fmriprep` derived from `bids`
- **THEN** the datasets are created in that order, each recording its identifier

#### Scenario: Invalid plan
- **WHEN** the ma-DMP fails validation
- **THEN** nothing is created and the violations are reported

### Requirement: Rendering from the template
Each dataset SHALL be rendered from its template at the pinned version with its template data, and SHALL record template, version and data. A template that cannot be fetched SHALL fail that dataset without leaving a partial dataset.

#### Scenario: Recorded template
- **WHEN** a dataset is created
- **THEN** it contains the rendered content and a record of template location, version and data

### Requirement: Container collections
Container collections declared by a template SHALL be installed as subdatasets at their pinned revisions, and every image referenced by the dataset's container entries SHALL exist in them; otherwise init SHALL fail for that dataset and name the container.

#### Scenario: Missing image
- **WHEN** a container entry references an image absent from its collection at the pinned revision
- **THEN** init fails, naming the container and the collection

### Requirement: Sources as subdatasets
Each source SHALL be installed in the derived dataset at `sourcedata/<source id>`; for a stream, each instance at `sourcedata/<stream>/<site>_<instrument>`, with only the last level a subdataset.

#### Scenario: Stream instances
- **WHEN** `bids` is derived from stream `dicoms` with instances `a_PrismaFit16001` and `a_Skyra45012`
- **THEN** `bids` has subdatasets `sourcedata/dicoms/a_PrismaFit16001` and `sourcedata/dicoms/a_Skyra45012`

### Requirement: Early-stage remotes
For each distribution at stage `collection` or `accepted`, init SHALL configure a remote from its `access_url` with its `wanted` expression. No remote SHALL be created for `release` distributions.

#### Scenario: Wanted set
- **WHEN** a dataset has a `collection` distribution with a `wanted` expression
- **THEN** the dataset has a remote for it with that preferred-content expression

### Requirement: Study superdataset
The superdataset is the dataset with path `.`, rendered like any other. Init SHALL register in it every dataset that declares a path at that path, track the ma-DMP file there, and record subdataset URLs as relative URLs. Datasets without a path SHALL NOT be registered.

#### Scenario: Whole project from one clone
- **WHEN** the superdataset is cloned and its subdatasets installed
- **THEN** every dataset with a path is present there and the ma-DMP is present

### Requirement: Platform repositories
With a platform configured, init SHALL create a repository per dataset at `<group>/<path>` (as subgroups, or with `/` replaced by `.` on platforms without subgroups), stream instances at `<group>/sourcedata/<stream>/<site>_<instrument>`, and the superdataset at `<group>/superdataset`. Without a platform, init SHALL create the same structure locally.

#### Scenario: Flat platform
- **WHEN** init targets a platform without subgroups and a dataset has path `derivatives/fmriprep`
- **THEN** its repository is named `derivatives.fmriprep`

#### Scenario: Local mode
- **WHEN** init runs without a platform
- **THEN** the same datasets, links and remotes exist locally and no platform request is made

### Requirement: Branches and platform policies
Init SHALL create `base` as the default branch of each standard and derived dataset, with `dev` and `pilot` starting from it. It SHALL protect `base`, `dev`, `pilot` and session branches, require one approval to merge a session, and forbid squash merges.

#### Scenario: Base branch
- **WHEN** init creates `bids`
- **THEN** `base` is its default branch, holding the rendered template and source pointers, and `dev` and `pilot` start from it

#### Scenario: Squash forbidden
- **WHEN** init configures a dataset repository
- **THEN** the platform rejects squash merges for it

### Requirement: Idempotent reconcile
Re-running init on an unchanged plan SHALL change nothing in the project; configuring remotes in a fresh working directory is reported separately as local setup. `--dry-run` SHALL report what would change.

#### Scenario: Second run
- **WHEN** init runs twice on the same plan
- **THEN** the second run reports no change and creates no commit

### Requirement: Additive evolution
New datasets, instruments and `collection`/`accepted` distributions SHALL be created and linked; changed `wanted` expressions SHALL be applied. Registering a new stream instance under `sourcedata/` of an existing dataset SHALL be proposed as a pull request on that dataset.

#### Scenario: New instrument
- **WHEN** an instrument is added to stream `dicoms` and init runs
- **THEN** its instance is created and each dataset derived from `dicoms` has a pull request registering it

### Requirement: Non-additive edits reported
A changed template, version, template data, source list or path of an existing dataset, or a removed dataset, SHALL NOT be applied; init SHALL report each difference and exit non-zero.

#### Scenario: Removed dataset
- **WHEN** an existing dataset is no longer in the plan
- **THEN** init reports it and deletes nothing
