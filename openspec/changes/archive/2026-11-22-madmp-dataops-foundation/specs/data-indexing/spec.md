## Purpose

Adds received raw files to a sourcedata stream instance, guided by a heuristic versioned in that stream, and hands them to the pipeline.

## ADDED Requirements

### Requirement: Index command
`faire index <stream> <directory>` SHALL add the files of a local directory to the matching instance of the stream, save them with DataLad, and push them. Fetching files from external systems is not part of indexing.

#### Scenario: New session
- **WHEN** a directory of files from one session is indexed into `dicoms`
- **THEN** the instance's `dev` holds them in a new commit and it is pushed

### Requirement: Heuristic from the stream
The heuristic SHALL be a Python module loaded from the stream's own versioned content. It SHALL provide `instrument`, `entities` and `place`, and MAY provide `pilot`. The commit SHALL record the sample entities and the heuristic's revision.

#### Scenario: Placement
- **WHEN** the heuristic returns subject `01`, session `a` and a relative path
- **THEN** the files are saved at that path and the commit message carries the entities and heuristic revision

### Requirement: Declared instruments only
Files attributed to an instrument not declared in the ma-DMP SHALL NOT be indexed; the command SHALL fail, name the instrument, and leave the directory untouched.

#### Scenario: Unknown scanner
- **WHEN** the heuristic returns an instrument absent from the plan
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
