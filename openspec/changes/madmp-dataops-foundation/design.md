## Context

Greenfield: the repository holds only OpenSpec artifacts. Motivation is in `proposal.md`, behaviour in `specs/`. A first implementation of an earlier, larger version of this change (branch `write`) was judged too complex; this design keeps the same foundations (DataLad, YODA, git-annex, copier, a DevOps platform) with a narrower scope. It generalises a GitLab CI proof of concept for neuroimaging (BIDSFlux, `ni-dataops/ci-pipelines`), but nothing in faire is domain-specific.

```
 PROVENANCE (drives processing)                 USER VIEW (study superdataset)

 dicoms/a_Prisma  physio/a_Biopac  notes/a_ELN   study/
        \              |              /           +-- rawdata/          <- bids
         +-------------+-------------+            +-- derivatives/
                       v                          |     +-- fmriprep/
                     bids                         +-- dmp.json
                    /    \
              fmriprep   mriqc                    sourcedata streams are not registered
```

## Goals / Non-Goals

**Goals:**
- A small command set; CI jobs call the same commands a person would.
- Every mechanism testable locally, without a platform.
- Reuse existing DataLad concepts (container entries, run records, URLs) rather than adding parallel ones.

**Non-Goals:** see Future work.

## Decisions

### D1. Profile in one `faire` property
Extension data lives under a `faire` key on `dmp`, `dataset`, `technical_resource` and `distribution`. Dataset: `template` (repository, version, data), optional `path`. Distribution: `stage`, `wanted`. Instrument: `instrument_id`, `site`. `dmp`: superdataset template, sample entities. Everything else uses standard fields: sources are `related_identifier` with `IsDerivedFrom`, the remote is `distribution.access_url`, retention is `available_until` / `host.certified_with`.
*Alternative:* a `faire.sourcedata` id list. Rejected: provenance would be invisible to standard tools.

### D2. Explicit superdataset paths, mirrored on the platform
`faire.path` is written in the ma-DMP (a BIDS-study layout is the author's choice, not faire logic). A dataset without a path is not registered; sourcedata streams have none. Platform repositories mirror the path (`<group>/derivatives/fmriprep` as subgroups, `derivatives.fmriprep` on flat platforms); streams go to `<group>/sourcedata/<stream>/<site>_<instrument>`. Subdataset URLs are relative so the tree resolves on any host with the same layout.

### D3. Distributions written out per dataset
No sharing mechanism in this iteration: JSON instances have no `$ref`, and each distribution will carry its own facts once write-back exists. A future ma-DMP editor generates the repetition.

### D4. DataLad URLs in `access_url`, creation inferred from the scheme
`ria+…` → RIA sibling (storage-only allowed); `ssh://`/`file://` → plain sibling; `datalad-annex::` → created by push; known forge hosts (GIN, the configured platform) → created through their API; anything else must exist. `host.url` stays the human landing page. URLs carrying credentials are rejected.

### D5. Templates and containers are ready-made
Datasets and the superdataset are rendered with copier from a pinned git reference; copier's answers file records template, version and data. A dataset template ships complete datalad-container entries pointing into container-collection subdatasets it declares at pinned revisions. `init` installs the collections and checks that every referenced image exists; it never builds, copies or freezes images.

### D6. Rules and checks are container entries
A rule is a `datalad.containers.<name>` entry with `faire-*` keys: `faire-sourcedata` (multi-valued source ids, `.` for the dataset itself), `faire-input`, `faire-output`, `faire-cmd`, optional `faire-after`, optional `faire-runner`. No `.` in sources: **primary** rule, creates a session branch. With `.`: **secondary** rule, commits to the current branch. A check adds `faire-check = blocking|advisory` and `faire-stage`; it is executed directly from `cmdexec` (not `containers-run`) and fails if it modifies the worktree. One container entry is one rule; the same image may be registered under several names.
*Alternative:* a separate rule file. Rejected: two places describing one call.
*Constraint:* git-config is flat, so ids used in keys stay within `[A-Za-z0-9-]`.

### D7. A session is one branch; samples meet in the converted dataset
The primary rule creates `convert/<sample>` and a draft pull request; secondary streams (physio, eye tracking, notes) and in-place tools (defacing) run on that branch against the converted files, so faire never matches samples across raw streams. When a secondary stream is indexed, every open branch whose status for that stream is `pending` gets its `sourcedata/` pointer bumped; the tool decides whether anything matches.

### D8. A rule is due when its inputs differ from its last run
Fingerprint = blob ids of files matching the rule's inputs plus commit ids of the sourcedata subdatasets it reads. Due if inputs exist and (no run record of the rule since the branch left its base, or fingerprint at HEAD ≠ fingerprint at the record commit). The record commit's tree is the post-run state, so in-place rules do not re-trigger themselves and nothing extra is stored. With `faire-after`, differences introduced only by commits of later rules are ignored. Diffing against the base branch (always differs) or the previous pipeline commit (brittle) were rejected.

### D9. Plan, render, run; waves and parallel tasks
`faire plan` lists due tasks (id = rule + sample) from the current state: rules whose inputs exist, plus rules ordered after a planned rule. `--ci-render gitlab` emits a child pipeline (`needs` for `faire-after`, runner tags from `faire-runner`), `--ci-render github` a matrix per dependency level; `run --all` is the fallback. Tasks on one branch run in parallel; the template guarantees disjoint outputs; `run --task` re-checks due-ness, commits, then merges and pushes with retries (merge, not rebase, to keep run commits). Task pushes skip CI; after tasks, `status`, then checks, then `replan` starts a new pipeline if the head moved. Undeclared dependencies resolve over successive waves; replan stops when a task ran twice without an upstream change and reports it.

### D10. Session status table
`sessions.tsv` (per subject) and `participants.tsv` get one column per source stream: `present`, `pending`, `partial`, `missing`, described with `Levels` in their JSON sidecar. faire writes it as a recorded step after each wave, from run records. `pending` fails faire's built-in completeness check. `faire mark <stream>=missing` records `partial` when converted output for the stream exists, `missing` otherwise; both pass with a warning, and the patterns of waived outputs are handed to checks (`FAIRE_WAIVED`) so a protocol tool (e.g. forbids) downgrades them. Reviewers mark through a manual CI job (GitLab) or a comment command (Actions platforms), or by editing the file.

### D11. Branches and stages
Datasets: `dev` (accepted), `pilot` (never merged into `dev`), `convert/*`. Superdataset: `dev`, `rel/*`, `main`. Stages: `collection` (sourcedata `dev`/`pilot`, session branches), `accepted` (`dev` of standard and derived datasets), `release` (`rel/*` of the superdataset). Pull requests need one human approval and are not squashed (run records must survive). A merge into `dev` or `pilot` triggers the datasets that list this one as a source.

### D12. Release from a branch, tagged when reachable
`faire release` runs on `rel/x.y.z` created from superdataset `dev`: bump all pointers to the datasets' `dev` heads (once), check that every `sourcedata/` pointer is an ancestor of the commit referenced for its source (blocking) and report incomplete derivatives, run release-stage checks, `sync --stage release`, check reachability (commits and wanted content on every release sibling). Merge to `main` (human approval) tags the superdataset and each dataset at its pointed commit and pushes the tags. Equality of pointers (rather than ancestry) was rejected: session-by-session merges almost never satisfy it.

### D13. Reconcile from facts already in the datasets
Comparison uses the copier answers, `faire.dataset-id` in `.datalad/config`, `.gitmodules`, remote configuration and the platform API. Additions are applied (new instruments are registered downstream through a pull request); `wanted` changes are applied; template, version, source or path changes and removed datasets are reported with a non-zero exit.

### D14. Indexing receives, it does not fetch
`faire index <stream> <dir>` loads `.faire/heuristic.py` from the stream (functions `instrument`, `entities`, `place`, `pilot`), saves, pushes content before history to `dev` or `pilot`. Fetching from PACS, XNAT or an ELN is a site script run before `index` by a scheduled job. An undeclared instrument fails indexing. Experimenter notes are an ordinary stream; their conversion extracts the shareable fields.

### D15. Platform adapter
Operations: create group and repository, protect branches, require approval, set merge method, set CI variables, open or update a pull request, post a comment, start a pipeline. GitLab implementation plus an in-memory fake for tests. Sites only map runner tags in this iteration.

## Risks / Trade-offs

- [Parallel rules writing the same file] → template responsibility; merge conflict fails the task loudly. Overlap check is future work.
- [Two in-place rules on one file without `faire-after` loop] → replan's loop guard stops and names them.
- [Many sessions produce many branches and pipelines] → accepted; parallelism across sessions is the point.
- [Release data visible before approval] → content leaving is limited by `wanted` and blocking release checks run before any push.
- [Templates must keep identifiable content out of shared distributions without faire marking it] → relies on conversion tools' annex metadata and `wanted` expressions.
- [Bumping secondary streams onto every waiting branch costs runs] → bounded by the number of open sessions.
- [The heuristic is arbitrary Python run with credentials] → loaded only from the stream's own reviewed history; `--dry-run` shows its decisions.

## Migration Plan

None: nothing deployed. The `write` branch is not migrated; reusable parts are taken case by case.

## Future work

- Federation: hub synchronisation, conflict resolution, federated release, site-dependent hosts.
- ma-DMP write-back (access URLs, dates, sizes), shared distribution templates, a ma-DMP editor.
- Study-level DOI and an archive of the git tree.
- `n/a` status for streams not planned in a session.
- Declared dependencies beyond ordering; output-overlap check between rules.
- A check for identifiable content not marked sensitive.
- Per-sample subdatasets and archive special remotes in indexing; a fetch hook in `index`.
- License and container-retrievability reports at release.
- Further CI renderers (Forgejo, Gitea); platform-native reports.

## Open Questions

- Exact placeholder syntax for `faire-input`/`faire-output`/`faire-cmd` beyond `{entity}` substitution.

Resolved by spikes (datalad 1.8.0, datalad-container 1.2.6, git-annex 10.20261026):
- datalad-container keeps unknown `faire-*` keys in `containers-list` results; multi-valued keys come back as tuples.
- `create_sibling_ria` with `ria+file://` creates, pushes and clones by dataset id; `create_sibling` with a local path or `ssh://` URL creates a plain sibling. `create_sibling` rejects `file://` URLs, so faire converts them to paths. `datalad-annex::` URLs need the datalad-next extension, not yet a dependency.
