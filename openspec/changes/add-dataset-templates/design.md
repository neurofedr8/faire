# Design

## Context

Templates are copier directories in `templates/`, each published as its own git repository. They all carry the same `.gitlab-ci.yml`, and `tests/test_reference_templates.py` checks that it matches `faire.tasks.BEFORE_SCRIPT`. The test suite uses `templates/standard/`, the toy fixture, by name.

## Goals / Non-Goals

**Goals:** clean starting points that are short and commented.

**Non-Goals:** keeping derived templates in sync with `base` automatically (copier template inheritance, update tooling), and domain-specific starters (BIDS, fMRIPrep).

## Decisions

- **Derive by copying, not by rendering.** A new template is a copy of `base` (or of a starter) that the author edits. Producing a copier template by running copier on another template would mean escaping every Jinja tag.
- **Commented example in `base`.** An active entry needs a real image, and `faire plan` would schedule it, so the example rule and check in `.datalad/config` stay comments.
- **Placeholders in the starters.** Entries are active and use sample-entity patterns. `copier.yml` asks for the collection URL and revision and the source id. `image` and `faire-cmd` hold `TODO` values that the author replaces. An unedited starter therefore fails at init through the existing container-collection check, before any run.
- **Fixture renamed `toy-standard`.** It keeps exercising every rule kind for the tests, and the name `standard` now refers to the clean starter.

## Risks / Trade-offs

- [Copies of `base` drift from the fixed CI] → the CI-match test covers every template directory, not a hard-coded list.
