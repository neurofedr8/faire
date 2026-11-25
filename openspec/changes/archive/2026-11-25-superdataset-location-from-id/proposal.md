# Proposal

## Why

The superdataset's repository is always named `superdataset` (`<group>/superdataset`, and the same directory locally), whatever the study. Other datasets without a usable path are already located by their `dataset_id`; the superdataset should be too, so its repository is named after the study.

## What Changes

- **BREAKING**: the superdataset is located at `<group>/<dataset_id>` (locally `<workdir>/<dataset_id>`) instead of `superdataset`. An existing project's superdataset is reported by `faire init` as being elsewhere than planned until its repository is renamed.
- No profile change: identifiers are already restricted to letters, digits, `-` and `_`.

## Capabilities

### New Capabilities

### Modified Capabilities
- `project-init`: superdataset location.

## Impact

`layout.py` (`SUPERDATASET` constant), `docs/gitlab.md`; tests and goldens that hardcode `superdataset` (`conftest.py`, `test_init.py`, `test_e2e.py`, `test_release.py`, `test_reference_templates.py`, `test_gitlab_live.py`). Existing GitLab projects need their superdataset repository renamed.
