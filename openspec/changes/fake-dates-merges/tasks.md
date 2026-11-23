# Tasks

## 1. Fake dates

- [x] 1.1 Init creates a dataset with fake dates when the rendered `.datalad/config` enables them; a test shows `datalad check-dates` reports nothing on all branches, `git-annex` included (the `git-annex` part is a strict xfail until DataLad's `create-sibling` honours fake dates, reported upstream).
- [x] 1.2 Document `datalad.fake-dates` in `templates/base` (`.datalad/config` comment and `TEMPLATE.md`); the starter-template tests still pass.

## 2. Merge

- [ ] 2.1 Platform adapter (fake and GitLab): approvers of a pull request, the automation identity excluded; fake-platform tests cover approved and unapproved cases, the live GitLab test approves through the API.
- [x] 2.2 `faire merge` on a session branch: refuse without approval or when the remote branch moved past the checked commit; outside CI run the blocking checks first; otherwise merge with `--no-ff` into the target and push; tests on the fake platform cover each refusal and a fake-dated merge commit.
- [x] 2.3 `faire plan` adds a manual merge job on a settled session branch, needing the blocking check jobs; the CI rendering test shows it next to the waiver jobs.
- [x] 2.4 Branch protection: merge access "no one" on `dev` and `pilot`, approval rule removed from the merge policy; init tests and the fake platform reflect it.

## 3. Release

- [x] 3.1 `faire release` runs `check_dates` on each fake-dated dataset at its released commit before release-stage checks; a test with an injected real-dated commit fails before any push and names the dataset.

## 4. End to end

- [ ] 4.1 Update the CI-driven end-to-end test and `docs/lifecycle.md` and `docs/gitlab.md` for merging through `faire merge`; `ruff` and `pytest` pass, and the live GitLab test passes when enabled.
