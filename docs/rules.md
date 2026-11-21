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
otherwise `faire replan` stops with a message naming them.

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

## Commands

All act on a clone of the dataset checked out on a session branch (`convert/<sample>`,
`convert-pilot/<sample>` for pilots), e.g. in a CI job:

```
faire plan                       # due tasks as JSON
faire plan --ci-render gitlab    # GitLab child pipeline: tasks, status, checks, replan
faire plan --ci-render github    # matrices for GitHub Actions, one per dependency level
faire run --task convert:subject-01_session-a
faire run --all                  # every wave in one process (works on any CI)
faire test --stage collection
faire replan                     # start the next wave when the branch moved
```

`faire run --task` commits, pushes content to the dataset's `collection-*` remotes, then
merges the remote branch and pushes, retrying when other tasks pushed first. On GitLab its
pushes skip CI (`-o ci.skip`); `faire replan` starts the next pipeline once.
