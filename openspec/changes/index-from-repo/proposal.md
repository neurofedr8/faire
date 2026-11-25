# Proposal

## Why

`faire index` needs the ma-DMP and the project options (`--dmp`, `--workdir`, `--platform`, `--group`) only to find the target repository and check the heuristic's output. An acquisition-side indexer should only need the address of the repository it feeds: the instance already carries its ma-DMP copy, its heuristic and its `collection` remotes.

## What Changes

- **BREAKING**: `faire index <dataset> <directory>` replaces `faire index <stream> <directory> --dmp … [project options]`. `<dataset>` is a local clone or the URL of a stream instance.
- A URL is cloned once into `--clone` (default `./<repository name>`); the clone is reused and brought up to date with `origin` before indexing.
- The plan comes from the instance's `.faire/dmp.json`; the instance is identified by its recorded dataset id and instance.
- The heuristic's instrument must be the instance's own; any other is refused.
- `collection` remotes are used as found in the clone; indexing no longer creates them (`faire init` does).
- Multi-study routing is out of scope.

## Capabilities

### New Capabilities

### Modified Capabilities
- `data-indexing`: target given by repository instead of the project; instrument checked against the instance; clone kept up to date.

## Impact

`faire index` CLI and `indexing.py`; `tests/test_indexing.py`, `tests/test_e2e.py`, `tests/test_gitlab_live.py` callers; `docs/lifecycle.md`. Stream template's `.gitlab-ci.yml` / docs if they invoke `faire index`.
