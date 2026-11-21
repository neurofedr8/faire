# Tasks

## 1. Package and spikes

- [x] 1.1 Create the `faire` package (src layout, click CLI entry point, pytest, ruff, GitHub Actions CI); verify `faire --help` runs and CI passes on an empty test suite
- [x] 1.2 Spike: confirm datalad-container keeps `faire-*` keys of an entry in `containers-list` output; record the result in design.md Open Questions
- [x] 1.3 Spike: confirm which DataLad URL schemes (`ria+`, `ssh://`, `file://`, `datalad-annex::`) can create and push a sibling through the Python API; record the result in design.md

## 2. Profile and validation

- [x] 2.1 Vendor the RDA DMP v1.3 schema and write the `faire` profile schema; verify a minimal example validates and an extension-stripped copy validates against v1.3
- [x] 2.2 Implement cross-field rules (identity, paths, sources DAG, instruments, stages, URL credentials) in `faire validate`; verify one test per madmp-profile scenario
- [x] 2.3 Write a single-site example ma-DMP (dicoms, physio, notes, bids, fmriprep) and document the profile in `docs/profile.md`; verify `faire validate` passes on it

## 3. Init

- [x] 3.1 Render a dataset from a copier template at a pinned version into a new DataLad dataset recording `faire.dataset-id`; verify with a local template repository
- [x] 3.2 Install container collections and check referenced images; verify the missing-image scenario
- [x] 3.3 Install sources under `sourcedata/` including stream instances, in provenance order; verify the chain and stream-instances scenarios
- [x] 3.4 Configure `collection`/`accepted` remotes from `access_url` with `wanted`; verify with `file://` and RIA remotes
- [x] 3.5 Render the superdataset, register datasets at their paths with relative URLs, track the ma-DMP; verify a clone installs every dataset with a path
- [x] 3.6 Implement reconcile (idempotent run, additions, reported non-additive edits, `--dry-run`); verify each project-init reconcile scenario locally
- [x] 3.7 Platform adapter interface, in-memory fake and GitLab implementation (groups, repositories, protections, approvals, merge method, CI variables, pull requests, comments, pipeline start); verify init against the fake and document GitLab setup in `docs/gitlab.md`

## 4. Reference templates

- [x] 4.1 Reference stream template with an example heuristic and a reference superdataset template; verify init renders both
- [x] 4.2 Reference standard dataset template with one primary rule, one secondary rule using `.` and another stream, one in-place rule, and one blocking and one advisory check, all as container entries with a tiny test container; verify `containers-list` shows them

## 5. Indexing

- [x] 5.1 `faire index` with heuristic loading, placement, commit entities and heuristic revision, `--dry-run`; verify placement and preview scenarios
- [x] 5.2 Declared-instrument check, pilot routing, content before history, repeatable indexing; verify each data-indexing scenario

## 6. Rules, planning and running

- [x] 6.1 Read rules and checks from container entries; classify primary/secondary; verify the classification scenario
- [x] 6.2 Fingerprints and due-ness (record lookup since branch base, `faire-after` exclusion); verify in-place and source-moved scenarios
- [x] 6.3 `faire run --task` and `--all` (re-check, input retrieval, containers-run, commit, merge, push with retries, content push); verify concurrent-push and no-longer-due scenarios with two local clones
- [x] 6.4 `faire test` (direct execution, worktree-clean check, blocking/advisory, waived patterns via `FAIRE_WAIVED`); verify the check-modifies-files scenario
- [x] 6.5 `faire plan` with neutral output and `--ci-render gitlab|github`; verify rendered output against golden files for the ordered-chain case
- [x] 6.6 `faire replan` with loop guard; verify next-wave and loop scenarios with the fake platform (superseded by 8.4)
- [x] 6.7 Document rule and check keys in `docs/rules.md`; verify the reference template matches the documentation

## 7. Lifecycle

- [x] 7.1 Downstream trigger: create session branches and draft pull requests, bump pending streams on open branches; verify new-session and late-stream scenarios with the fake platform (superseded by 8.3)
- [x] 7.2 `faire status` writing `sessions.tsv`/`participants.tsv` and sidecar levels as a recorded step; built-in completeness check; verify status and pending scenarios
- [x] 7.3 `faire mark` (partial vs missing, reviewer recorded) and the rendered manual job; verify the partial-physio scenario
- [x] 7.4 Pilot base branch through trigger, branch creation and pull request target; verify pilot isolation

## 8. Rework: superdataset as a dataset, `base` branch, single CI entry

- [x] 8.1 Profile and init: superdataset is the dataset with path `.` (schema, validation, example, `docs/profile.md`), rendered and registered like any dataset; drop `dmp.faire.superdataset`; verify the superdataset-profile and init scenarios
- [x] 8.2 Streams on `dev` only, pilot items marked by a `faire-pilot` trailer; per-sample fingerprints looking inside source subdatasets; verify pilot-marking, source-moved and other-samples-arrived scenarios
- [ ] 8.3 `base` as default branch created by init, and the `update` task (pointers on `base`, merge into `dev`, `pilot` and open branches, open sessions from `base`, recompute on concurrent update); remove `faire sessions`; verify new-session, late-stream, rule-fixed, session-diff and pilot-isolation scenarios with the fake platform
- [ ] 8.4 `faire plan` deciding from the branch, loop guard in plan, `status` starting the next wave, checks only when nothing is due, native downstream triggers; remove `faire trigger`, `faire replan` and `FAIRE_DOWNSTREAM`; ship a fixed CI configuration in the reference templates; update golden files and `docs/rules.md`, `docs/gitlab.md`; verify render, nothing-due, loop and next-wave scenarios

## 9. Distribution and release

- [x] 9.1 `faire sync --stage` with `wanted`, credentials from environment, resumability; verify accepted, excluded-content and interrupted scenarios with local remotes
- [x] 9.2 Release remote creation inferred from URL (RIA, plain, `datalad-annex`, GitLab via adapter); verify first-use creation for RIA and plain siblings
- [ ] 9.3 `faire release` on `rel/*` (pointer bump, ancestry, completeness report, release checks, sync, reachability) and tagging on merge to `main`; verify each release scenario and that no tag exists on failure
- [ ] 9.4 Verify a released tree installs from release remotes with the platform unreachable
- [ ] 9.5 Document stages, branches and release in `docs/lifecycle.md`

## 10. Integration

- [ ] 10.1 End-to-end local run on the example ma-DMP with the fake platform: init, index two streams at different times, plan/run waves, mark, merge, cascade to a derivative, release; verify final tags and remote contents
- [ ] 10.2 End-to-end on a GitLab test instance using rendered pipelines; verify one session reaches a release tag
