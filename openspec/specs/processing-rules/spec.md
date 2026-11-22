# processing-rules Specification

## Purpose

Defines how a dataset declares its computations and checks as container entries, how faire decides what is due, and how tasks are planned, rendered for CI and run.

## Requirements

### Requirement: Rules are container entries
A rule SHALL be a datalad-container entry of the dataset carrying faire keys: one or more `faire-sourcedata` (source ids, or `.` for the dataset itself), `faire-input` and `faire-output` patterns using sample entities, and `faire-cmd`. A rule without `.` among its sources is primary; a rule with `.` is secondary.

#### Scenario: Primary and secondary
- **WHEN** `heudiconv` lists `dicoms` and `bidsphysio` lists `.` and `physio`
- **THEN** `heudiconv` is reported primary and `bidsphysio` secondary

### Requirement: Checks are container entries
A check SHALL be a container entry with `faire-check` set to `blocking` or `advisory` and one or more `faire-stage`. `faire test` SHALL execute checks for a stage with the entry's call format, without recording a run, and SHALL fail a check that modifies the worktree. A failing blocking check SHALL make `faire test` exit non-zero; a failing advisory check SHALL only warn.

#### Scenario: Check modifies files
- **WHEN** a check writes a file in the dataset
- **THEN** the check fails and the change is reported

### Requirement: Due tasks
A task is a rule applied to one sample. It SHALL be due when its inputs exist at HEAD and either no run record of the rule for that sample exists since the branch left its base, or the fingerprint of its inputs (contents of the files its patterns match, inside source subdatasets as well) at HEAD differs from that at its last record commit. Differences introduced only by commits of rules ordered after it SHALL be ignored.

#### Scenario: In-place rule
- **WHEN** a defacing rule rewrote the file it reads and nothing else changed
- **THEN** it is not due

#### Scenario: Source moved
- **WHEN** the `sourcedata/physio` pointer moves after `bidsphysio` ran and the sample's physio files changed
- **THEN** `bidsphysio` is due

#### Scenario: Other samples arrived
- **WHEN** the `sourcedata/dicoms` pointer moves only because another session was indexed
- **THEN** no rule of this session is due

### Requirement: Optional ordering
`faire-after` MAY name rules a rule runs after. It SHALL only order rules; a rule SHALL NOT be forced to run by it.

#### Scenario: Ordered chain
- **WHEN** `pydeface` declares `faire-after = unwarp` and both are due
- **THEN** `pydeface` runs after `unwarp` finishes

### Requirement: Plan
`faire plan` SHALL decide from the branch: on `base`, the `update` task; on `dev` or `pilot`, `accepted` distributions and triggers of downstream datasets' `base`; on a session branch, the due tasks (id, rule, sample, order constraints, runner) followed by `faire status`, or the checks and a manual waiver job per pending stream when no task is due; on the superdataset's `rel/*` and `main`, the release steps.

#### Scenario: Branch decides
- **WHEN** plan runs on `base`
- **THEN** it plans only `update`

### Requirement: CI rendering
`--ci-render gitlab` SHALL produce a GitLab child pipeline and `--ci-render github` a GitHub Actions matrix definition, each running `faire run --task <id>` per task. Each dataset template SHALL ship a fixed CI configuration that only calls `faire plan --ci-render` and executes its output.

#### Scenario: Render
- **WHEN** two independent tasks and one ordered after the first are due
- **THEN** the rendered pipeline runs the first two in parallel and the third after the first, then status, and no checks

#### Scenario: Nothing due
- **WHEN** no task is due on a session branch
- **THEN** the rendered pipeline runs the checks

### Requirement: Run
`faire run --task <id>` SHALL re-check that the task is due, retrieve only its inputs, execute it with `datalad containers-run` with declared inputs and outputs, commit, merge the branch's remote head, and push with retries; it SHALL push content to the dataset's `collection` remotes. A task whose inputs are absent SHALL exit with status zero and no commit. `faire run --all` SHALL run all due tasks in order in one process. Behaviour SHALL be the same in and out of CI.

#### Scenario: Concurrent pushes
- **WHEN** two tasks on one branch push at the same time
- **THEN** the second merges the first's commit and its push succeeds

#### Scenario: No longer due
- **WHEN** a task is run after another job already ran it
- **THEN** it exits with status zero and no commit

### Requirement: Loop guard
`faire plan` SHALL refuse when a task ran twice on the branch without its inputs changing, naming the rules involved.

#### Scenario: Loop
- **WHEN** two in-place rules without `faire-after` keep rewriting each other's input
- **THEN** plan fails naming both

### Requirement: Waves
Task pushes SHALL NOT start pipelines. `faire status`, ending a wave, SHALL start the next pipeline on the branch when its head moved during the pipeline, through its own push or the platform.

#### Scenario: Next wave
- **WHEN** `heudiconv` committed converted files in a pipeline
- **THEN** a new pipeline plans the rules now finding their inputs

### Requirement: Re-executable results
Every committed result SHALL carry a DataLad run record sufficient for `datalad rerun` in a fresh clone.

#### Scenario: Rerun
- **WHEN** a result commit is rerun in a fresh clone
- **THEN** the same outputs are produced from the recorded inputs and container
