# Tasks

## 1. Fake dates

- [ ] 1.1 Init creates a dataset with fake dates when the rendered `.datalad/config` enables them; a test shows `datalad check-dates` reports nothing on all branches, `git-annex` included.
- [ ] 1.2 Document `datalad.fake-dates` in `templates/base` (`.datalad/config` comment and `TEMPLATE.md`); the starter-template tests still pass.

## 2. Merge

- [ ] 2.1 Platform adapter (fake and GitLab): approvals of a pull request and status of its head's latest pipeline; adapter tests cover approved, unapproved and failed-pipeline cases.
- [ ] 2.2 `faire merge` on a session branch: refuse without approval or passing pipeline; otherwise merge with `--no-ff` into the target and push; tests on the fake platform cover refusal and a fake-dated merge commit.
- [ ] 2.3 `faire plan` adds a manual merge job on a settled session branch; the CI rendering test shows it next to the waiver jobs.
- [ ] 2.4 Branch protection: merge access "no one" on `dev` and `pilot`, approval rule removed from the merge policy; init tests and the fake platform reflect it.

## 3. Release

- [ ] 3.1 `faire release` runs `check_dates` on each fake-dated dataset at its released commit before release-stage checks; a test with an injected real-dated commit fails before any push and names the dataset.

## 4. End to end

- [ ] 4.1 Update the CI-driven end-to-end test and `docs/lifecycle.md` and `docs/gitlab.md` for merging through `faire merge`; `ruff` and `pytest` pass, and the live GitLab test passes when enabled.
