# Proposal

## Why

The only dataset template, `templates/standard/`, is a test fixture: it runs every rule kind on a toy image. A study needs a clean starting point to write its own templates from, and the derived-dataset case (for example, preprocessing from `sourcedata/bids`) has no template at all.

## What Changes

- New `templates/base/`: fixed CI, `.gitattributes`, README and `copier.yml`, with no active rule or check. `.datalad/config` holds only a commented example of a rule and a check.
- New `templates/standard/`, derived from `base`: placeholder entries for a conversion rule from a stream, a rule on the dataset's own output, and a blocking and an advisory check.
- New `templates/derivative/`, derived from `base`: one placeholder primary rule on a source dataset and placeholder checks.
- The current `templates/standard/` fixture is renamed `templates/toy-standard/`, and tests point at it.

## Capabilities

### New Capabilities
- `dataset-templates`: the reference templates faire ships, what each contains, and how new templates are derived from them.

### Modified Capabilities

## Impact

`templates/` (new directories, fixture renamed), `templates/README.md`, and test references to `templates/standard` (`tests/conftest.py`, `tests/test_e2e.py`, `tests/test_gitlab_live.py`, `tests/test_reference_templates.py`). No change to the `faire` package.
