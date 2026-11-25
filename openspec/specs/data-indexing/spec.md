# data-indexing Specification

## Purpose

Adds received raw files to a sourcedata stream instance, guided by a heuristic versioned in that stream, and hands them to the pipeline.

## Requirements

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

### Requirement: Heuristic from the stream
The heuristic SHALL be a Python module loaded from the stream's own versioned content. It SHALL provide `instrument`, `entities` and `place`, and MAY provide `pilot`. The commit SHALL record the sample entities and the heuristic's revision.

#### Scenario: Placement
- **WHEN** the heuristic returns subject `01`, session `a` and a relative path
- **THEN** the files are saved at that path and the commit message carries the entities and heuristic revision

### Requirement: Declared instruments only
Files attributed to an instrument other than the instance's own SHALL NOT be indexed; the command SHALL fail, name the instrument, and leave the directory untouched.

#### Scenario: Unknown scanner
- **WHEN** the heuristic returns an instrument absent from the plan
- **THEN** indexing fails naming it and nothing is committed

#### Scenario: Other instance's instrument
- **WHEN** the heuristic returns an instrument declared for another instance of the stream
- **THEN** indexing fails naming it and nothing is committed

### Requirement: Pilot marking
Streams SHALL have a single `dev` branch. An item the heuristic marks as pilot SHALL be committed there like any other, with a trailer marking its sample as pilot.

#### Scenario: Pilot session
- **WHEN** `pilot` returns true for an item
- **THEN** it is committed to `dev` and the commit marks its sample as pilot

### Requirement: Content before history
Annexed content SHALL be pushed to the stream's `collection` remotes before its history is pushed, so a pushed commit never references unavailable content.

#### Scenario: Storage failure
- **WHEN** the content push fails
- **THEN** the history is not pushed and the error is reported

### Requirement: Repeatable indexing
Indexing the same files again SHALL create no commit.

#### Scenario: Re-run
- **WHEN** an already indexed directory is indexed again
- **THEN** no commit is created

### Requirement: Dry run
`--dry-run` SHALL report, per item, the heuristic's decisions without changing anything.

#### Scenario: Preview
- **WHEN** index runs with `--dry-run`
- **THEN** instrument, entities, placement and pilot status are listed and nothing is written

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
