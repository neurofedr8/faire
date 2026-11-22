# Tasks

## 1. Fixture

- [x] 1.1 Rename `templates/standard/` to `templates/toy-standard/` and update references in `tests/conftest.py`, `tests/test_e2e.py`, `tests/test_gitlab_live.py` and `tests/test_reference_templates.py`; `pytest` passes.

## 2. Templates

- [x] 2.1 Add `templates/base/` (CI, `.gitattributes`, answers file, README on deriving, `.datalad/config` with only a commented rule and check); a test renders it and `faire plan` on a session branch plans nothing.
- [x] 2.2 Add `templates/standard/` from `base` with placeholder conversion, self-sourced rule and both kinds of check; a test shows init fails on it unedited, naming the container.
- [x] 2.3 Add `templates/derivative/` from `base` with one placeholder primary rule and checks; its `.datalad/config` parses, and the rule is reported primary.
- [x] 2.4 Make the CI-match test in `tests/test_reference_templates.py` cover every template directory that has a `.gitlab-ci.yml`; it covers `base`, `standard` and `derivative`.
- [x] 2.5 Update `templates/README.md` to list `base`, `standard`, `derivative` and `toy-standard`; `ruff` and `pytest` pass.
