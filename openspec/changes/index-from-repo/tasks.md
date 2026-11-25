# Tasks

## 1. Indexer from a dataset

- [x] 1.1 Move `_dataset_plan` from `cli.py` to a shared module and use it in the CI commands; verify existing CLI tests pass
- [x] 1.2 Make `Indexer` take the instance dataset: plan and unit from its ma-DMP copy, instrument checked against the instance's, failure when not a stream instance; verify with `tests/test_indexing.py` updated for the new scenarios (other instance's instrument, not an instance, entities)
- [x] 1.3 Fast-forward `dev` from `origin` before indexing, failing when not possible; verify with a test where `origin/dev` moved and one where it diverged
- [x] 1.4 Use existing `collection` remotes only (verify, push, fail when missing) and keep the rollback; verify the no-collection-remote and content-before-history tests

## 2. CLI

- [x] 2.1 `faire index <dataset> <directory> [--clone PATH] [--dry-run]`: clone a URL or reuse a matching clone, auth from the environment token; verify with CLI tests for path, URL, and mismatched clone
- [x] 2.2 Update `tests/test_e2e.py`, `tests/test_gitlab_live.py`, templates and `docs/lifecycle.md` to the new invocation; verify `pytest` and `ruff` pass
