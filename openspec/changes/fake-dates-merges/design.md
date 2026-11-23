# Design

## Context

DataLad dates each commit one second after the newest commit of `refs/heads/*` when `datalad.fake-dates` is true, starting from 2005, and sets `GIT_ANNEX_VECTOR_CLOCK` for git-annex. A single real-dated commit on a branch therefore makes every later commit near-real. Today GitLab creates the session merge commit (`merge_method = "merge"`), and `faire init` runs `datalad create` before merging the rendered template's `.datalad/config`, so a dataset's first commits are real-dated whatever the template says. Release tags are annotated, so they carry a tagger date. GitLab approval rules need a paid tier and are skipped on Free.

## Goals / Non-Goals

**Goals:** no real date in the git history of a fake-dated dataset; GitLab's UI may show real dates.

**Non-Goals:** recording real dates (audit trail); hiding platform metadata (pull request, pipeline and push times).

## Decisions

- **faire merges every session.** No commit created by the platform ever reaches a branch, so there's nothing to rewrite and no force-push. Alternatives considered: rewriting the GitLab merge commit after the fact (force-pushes protected branches, races with downstream `update`, and leaves the original reachable through `refs/merge-requests/*`), and fast-forward-only merges (every merge forces `dev` into every open session). A Gitaly merge driver can't help: it only resolves file contents, never commit metadata. Doing this for all datasets keeps a single merge path and makes approval enforced on GitLab Free.
- **Trigger: a manual job in the session pipeline**, next to the waiver jobs. GitLab can't start a pipeline on approval without a webhook service. In the rendered pipeline the merge job `needs` the blocking check jobs, so the platform only lets it run once they passed; `faire merge` asks the platform adapter for the pull request's approvers and refuses if the session branch on the remote moved past the commit the pipeline checked (`CI_COMMIT_SHA`). Outside CI, it runs the blocking checks itself first. (Asking the platform for the head's pipeline status can't work: the merge job runs inside that pipeline, which is still running.) It merges with `git merge --no-ff` through the DataLad API, and pushes with the existing retry loop. The platform marks the pull request merged when its commits reach the target; `faire merge` then deletes the session branch through the platform adapter (git can't delete protected branches), as the platform's merge used to, so `update` stops merging `base` into it. Approvals from faire's own token user don't count.
- **Platform policy:** protected `dev` and `pilot` get merge access "no one" and push access maintainers, which covers faire's CI identity. GitHub needs the faire identity allowed to bypass the pull-request rule.
- **Fake dates from creation:** init reads `datalad.fake-dates` from the rendered `.datalad/config` before creating the dataset and passes `fake_dates=True` to `create`, so the first commit and the `git-annex` branch are fake-dated too.
- **Built-in date check, triggered by the setting.** `check-dates` runs in faire's environment, not in a container, so a template-declared check would need a placeholder image. `faire release` calls `datalad.api.check_dates` with the default reference (2018-01-01) on every dataset whose committed configuration enables fake dates, at the released commit, alongside the consistency checks and before the release-stage checks.

## Risks / Trade-offs

- [A human maintainer can still push a real-dated commit, because GitLab Free can't restrict pushes to one user] → the release date check stops it reaching external remotes. Self-managed instances can also add a pre-receive hook rejecting commits dated after 2018 in fake-dated datasets (documented, not installed by faire).
- [Stale approval: GitLab Free doesn't reset approvals on push, and fake dates can't order commits against approval time] → accepted for now (Future work).
- [Reviewers lose the platform merge button] → the manual job is in the same pipeline view.

- [The superdataset's release pull request (`rel/<version>` into `main`) is still merged through the platform, so a fake-dated superdataset gets one real-dated merge commit on `main` per release] → not covered by this change (Future work).

## Migration Plan

Existing projects: re-run init to apply the new branch protection. Datasets created before fake dates were enabled keep their real-dated history; the release check reports them.

## Future work

- Audit trail of real dates, likely upstream in DataLad as a fake-dates option that also stores the real date encrypted with a public key, so any tool saving through DataLad keeps it.
- Rejecting approvals older than the pull request's head.
- Merging the release pull request with faire too, for fake-dated superdatasets.
