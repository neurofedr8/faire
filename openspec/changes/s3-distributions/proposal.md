# Proposal

## Why

Many institutions provide storage as S3 object stores, and Hugging Face-style hosting expects the same. faire accepts no S3 location today: an `s3://` URL becomes a git remote that can't be pushed, and `datalad-annex::` URLs are refused.

## What Changes

- An `access_url` can address S3 as `datalad-annex::?type=S3&...`, with git-annex S3 special-remote parameters (`bucket`, `fileprefix`, `host`, `encryption`...). This works at every stage.
- `collection` and `accepted` S3 distributions get a content-only remote, with git history staying on the platform, like RIA storage today. `release` distributions get both git history and content, so a release can be cloned from S3 alone.
- The ma-DMP decides where each dataset goes through `bucket` and `fileprefix`. Validation refuses two datasets at the same location, and credentials embedded in the remote. Stream instances, which share their stream's URL, each get their own sub-prefix.
- datalad-next becomes a dependency (git remote helper for `datalad-annex::`).

## Capabilities

### New Capabilities

### Modified Capabilities
- `madmp-profile`: S3 locations and their validation.
- `data-distribution`: S3 remotes at every stage.

## Impact

`faire validate`, remote creation in `faire init` and `faire sync`/`faire release` (`remotes.py`), the credential check, `docs/profile.md`. New dependency: `datalad-next` (already added to `pyproject.toml`). Consumers cloning an S3 release need datalad-next too.
