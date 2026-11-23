# Proposal

## Why

A study's datasets depend on each other: a derivative's rules expect the naming its source's template produces. If each template lives in its own repository, there's nothing to say which versions work together, and a template fix can't reach existing datasets, because init refuses any change to a pinned version.

## What Changes

- A template repository can hold several templates of one domain (streams, raw data, derivatives, superdataset), picked by a template data answer. They're versioned and tested together, and a study pins every dataset to the same tag. The ma-DMP schema doesn't change.
- Changing a dataset's pinned template version in the ma-DMP is no longer refused. Init proposes the update as a pull request on that dataset's `base`, and the existing `update` spreads it to `dev`, `pilot` and open sessions once it's merged.
- An update that leaves the rendered content unchanged only records the new version. An update that conflicts, or that changes fake dates, fails for that dataset.

Non-goals: re-running sessions already merged when an update changes a rule (they keep their run records), changing a dataset's template repository or selected template, and a study-level default template in the profile.

## Capabilities

### New Capabilities

### Modified Capabilities
- `dataset-templates`: template repositories holding several templates selected by an answer.
- `project-init`: template version changes are applied as pull requests instead of being reported as non-additive.

## Impact

`faire init` reconcile (template comparison, rendering of the old and new versions, pull request on `base`), platform adapter (pull requests on `base`, already used for new instruments), `templates/README.md` and `base/TEMPLATE.md` (domain repository layout), docs. No new dependency.
