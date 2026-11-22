# dataset-templates Specification

## Purpose

Defines the reference dataset templates faire ships as starting points for a study's own templates.

## Requirements

### Requirement: Base template
faire SHALL ship a `base` dataset template with the fixed CI configuration, `.gitattributes`, a README explaining how to derive a template from it, and no active rule or check. A dataset rendered from it SHALL have nothing planned on a session branch.

#### Scenario: Nothing to run
- **WHEN** a dataset rendered from `base` has a session branch
- **THEN** `faire plan` plans no task and no check

### Requirement: Standard and derivative starters
faire SHALL ship two templates derived from `base`. `standard` SHALL hold a conversion rule from a stream, a rule taking the dataset itself as a source, and a blocking and an advisory check. `derivative` SHALL hold one primary rule on a source dataset and checks. Their images and commands SHALL be placeholders the template author replaces; the sample entities of each rule are left to the author.

#### Scenario: Unedited starter
- **WHEN** init renders a dataset from `standard` with its placeholders left in place
- **THEN** init fails for that dataset, naming the container whose image is missing
