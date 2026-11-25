# Spec Delta

## MODIFIED Requirements

### Requirement: Index command
`faire index <dataset> <directory>` SHALL add the files of a local directory to the stream instance `<dataset>`, given as a local clone or a URL, save them with DataLad, and push them to its `origin`. It SHALL NOT require the ma-DMP file or project options. Fetching files from external systems is not part of indexing.

#### Scenario: New session
- **WHEN** a directory of files from one session is indexed into a clone of the `dicoms` instance
- **THEN** the instance's `dev` holds them in a new commit and it is pushed

#### Scenario: From a URL
- **WHEN** `<dataset>` is the URL of an instance not yet cloned
- **THEN** it is cloned into `--clone` (default `./<repository name>`) and the files are indexed there

#### Scenario: Not an instance
- **WHEN** `<dataset>` has no `.faire/dmp.json` or is not a stream instance of it
- **THEN** indexing fails and nothing is committed

### Requirement: Declared instruments only
Files attributed to an instrument other than the instance's own SHALL NOT be indexed; the command SHALL fail, name the instrument, and leave the directory untouched.

#### Scenario: Unknown scanner
- **WHEN** the heuristic returns an instrument absent from the plan
- **THEN** indexing fails naming it and nothing is committed

#### Scenario: Other instance's instrument
- **WHEN** the heuristic returns an instrument declared for another instance of the stream
- **THEN** indexing fails naming it and nothing is committed

## ADDED Requirements

### Requirement: Plan from the instance
Sample entities and declared instruments SHALL be read from the instance's own ma-DMP copy on `dev`.

#### Scenario: Entities checked
- **WHEN** the heuristic returns entities other than those of the instance's ma-DMP copy
- **THEN** indexing fails and nothing is committed

### Requirement: Up to date before indexing
Before indexing, the clone's `dev` SHALL be fast-forwarded to `origin`; if it cannot be, indexing SHALL fail without committing.

#### Scenario: Reused clone
- **WHEN** `origin/dev` moved since the clone was last used
- **THEN** the clone is fast-forwarded, the heuristic and ma-DMP copy are read from the new revision, and the new commit is pushed on top

### Requirement: Existing collection remotes
Indexing SHALL push content to the `collection` remotes already configured for the instance and SHALL NOT create remotes; if none is available, it SHALL fail before pushing history.

#### Scenario: No collection remote
- **WHEN** the instance has no usable `collection` remote
- **THEN** indexing fails naming the missing remote and no history is pushed
