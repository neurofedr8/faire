# Rules and checks

A dataset's computations are DataLad container entries in its `.datalad/config`, shipped by
its template. faire reads `faire-*` keys on those entries; everything else is plain
datalad-container configuration (`image`, `cmdexec`).

## Rules

```ini
[datalad "containers.convert"]
    image = code/containers/images/toy-1.0.sh
    cmdexec = sh {img} {cmd}
    faire-sourcedata = dicoms                       ; multi-valued; "." is this dataset
    faire-input = sourcedata/dicoms/*/sub-{subject}/ses-{session}/*.dat   ; multi-valued
    faire-output = sub-{subject}/ses-{session}/anat                       ; multi-valued
    faire-cmd = copy sub-{subject}/ses-{session}/anat {inputs}
    faire-after = unwarp                            ; optional, multi-valued
    faire-runner = gpu                              ; optional runner tag
```

| Key | Meaning |
|---|---|
| `faire-sourcedata` | Sources the rule reads. Without `.` the rule is **primary**: it runs first on a new session branch. With `.` it is **secondary**: it works on the converted data of the branch. |
| `faire-input` | Files the rule reads. All patterns must match before the rule runs. |
| `faire-output` | Files or directories the rule writes; passed to `datalad containers-run --output`. |
| `faire-cmd` | Arguments substituted for `{cmd}` in `cmdexec`. May use DataLad's `{inputs}` and `{outputs}`. |
| `faire-after` | Rules this one runs after when both are planned. Changes made by later rules never make an earlier rule due again. |
| `faire-runner` | Runner tag of the CI job running this rule. |

Patterns and commands use `{entity}` placeholders, filled from the session's sample (the entity
names of the ma-DMP), and glob wildcards: `*` within a path segment, `**` across segments.
Patterns may reach into `sourcedata/` subdatasets.

A rule is **due** on a session branch when its inputs exist and either it has not run on the
branch, or its inputs (file contents and source subdataset commits) differ from what they were
right after its last run. A run is a commit carrying DataLad's run record and the trailers
`faire-rule` and `faire-sample`; `datalad rerun` re-executes it.

Rules of one session run in parallel. The template must ensure that rules write different
files; files every rule might touch (e.g. `dataset_description.json`) must stay out of rule
outputs. Two rules modifying the same file in place must be ordered with `faire-after`;
otherwise `faire plan` stops with a message naming them once one of them ran twice without the
sample's source data changing.

## Checks

```ini
[datalad "containers.validate"]
    image = code/containers/images/toy-1.0.sh
    cmdexec = sh {img} {cmd}
    faire-check = blocking          ; or advisory
    faire-stage = collection        ; multi-valued: collection, accepted, release
    faire-cmd = check .
    faire-input = sub-{subject}/ses-{session}/**   ; optional: content to retrieve first
```

A check runs its `cmdexec` directly (no run record) and must leave the dataset unchanged; a
check that modifies a file fails. A failing blocking check makes `faire test` exit non-zero;
an advisory one only warns. Checks see the environment variables `FAIRE_STAGE`,
`FAIRE_SAMPLE` and `FAIRE_WAIVED` (output patterns of streams a reviewer declared missing or
partial, one per line).

## Branches

- `base` (default branch): template content, rules, checks and `sourcedata/` pointers. Upstream
  changes land here only.
- `convert/<sample>` and `convert-pilot/<sample>`: one per session, started from `base`, merged
  into `dev` or `pilot` after review. Their diff is the sample's outputs and status only.
- `dev` and `pilot`: accepted data; faire merges `base` into them without review.

## Commands and CI

Each template ships a fixed `.gitlab-ci.yml` that runs `faire plan --ci-render gitlab` and
executes the child pipeline it renders. The branch decides:

| Branch | Pipeline |
|---|---|
| `base` | `faire run --task update`: sources to their `dev` heads on `base`, `base` merged into `dev`, `pilot` and every open session, sessions opened (with draft pull requests) for new samples |
| `dev` | `faire sync --stage accepted` when the dataset has accepted distributions; trigger the `base` pipeline of each dataset derived from this one (from the ma-DMP the dataset tracks in `.faire/dmp.json`) |
| `pilot` | nothing: pilots are not distributed and do not cascade to derived datasets |
| session, tasks due | `faire run --task <id>` per task (parallel, ordered by `faire-after`), then `faire status --next-wave` |
| session, nothing due | `faire test` per check, including `completeness`, and a manual `faire mark <stream>=missing` job per pending stream |

```
faire plan                       # due tasks of the session as JSON
faire plan --ci-render gitlab    # the GitLab child pipeline of the current branch
faire plan --ci-render github    # inputs for GitHub Actions: jobs, task matrices, checks
faire run --task convert:subject-01_session-a
faire run --all                  # every wave in one process (works on any CI)
faire test --stage collection
```

`faire run --task` commits, pushes content to the dataset's `collection-*` remotes, then
merges the remote branch and pushes, retrying when other tasks pushed first. On GitLab its
pushes skip CI (`-o ci.skip`). `faire status --next-wave` ends the wave: its push starts the
next pipeline, or, when the status did not change but the branch moved, it starts one through
the platform. Pipelines on a settled branch run the checks.
