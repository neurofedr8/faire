# Design

## Context

`Indexer` takes a `Project` (whole plan, workdir, platform) and a stream id; it resolves one `Unit` per instrument, clones missing instances from the platform, and creates missing `collection` remotes. Every dataset already holds `.faire/dmp.json` and `faire.dataset-id` / `faire.instance` in `.datalad/config`; `cli._dataset_plan` already turns a clone into `(plan, unit)` for the CI commands.

## Goals / Non-Goals

**Goals:** index into one instance from its clone or URL, with no project-level input.

**Non-Goals:** routing items across instances or studies; creating repositories or remotes.

## Decisions

- **One instance per run.** The target is a repository, so an indexer is bound to one instrument's instance. Indexing several instruments of a stream means one run per instance. Fits the acquisition-site deployment and the later routing work, which will choose a repository per item.
- **`Indexer(ds)` instead of `Indexer(project, stream)`.** Plan and unit come from `_dataset_plan` (moved out of `cli.py` to be shared). Heuristic, entities check and commit logic are unchanged.
- **Clone handling in the CLI.** URL → `datalad clone` into `--clone` if absent; if present it must be a clone of that URL (`origin` matches), else fail. Then `checkout dev`, `fetch origin`, `merge --ff-only origin/dev`. A local path is used as is, with the same update.
- **Remotes.** `remotes.verify_all(ds)` (needed in a fresh clone), then push to each `collection` remote from `remote_specs`; status other than `ok` fails instead of `remotes.create`. Content-before-history rollback is kept.
- **Auth.** History push uses `credentials.git_auth(origin URL, token)` with the platform token from the environment when set, else git's own credential helpers. No platform API calls are needed.

## Risks / Trade-offs

- [Stale ma-DMP copy in the instance] → it is what the instance's pipeline uses too; `faire init` keeps it current.
- [Concurrent indexers on one instance] → push rejected after the fast-forward; the run fails and is rerun (indexing is repeatable).
