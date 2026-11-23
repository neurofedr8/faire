# Design

## Context

`remotes.kind()` classifies an `access_url` and `remotes.create()` builds the remote. For `collection`/`accepted` it builds storage only (`storage_only=stage != "release"`). A RIA sibling's storage part is named `<name>-storage` and found by `content_target()`. Credentials are checked before any transfer from `CREDENTIALS`, one environment variable per kind. `datalad-annex::` URLs are refused today. datalad-next provides the `git-remote-datalad-annex` helper, which stores a git repository as annex keys in any special remote.

## Goals / Non-Goals

**Goals:** S3 at every stage with one URL syntax. A release can be cloned from S3 with datalad-next.

**Non-Goals:** other `datalad-annex::` types (WebDAV, etc.), which could follow the same path later. Creating buckets: they must exist. Anonymous public read: possible through git-annex's `public`/`publicurl` parameters, but not checked by faire.

## Decisions

- **One syntax, `datalad-annex::?type=S3&...`.** The query holds git-annex `initremote` parameters as they are, so non-AWS stores (`host`, `port`, `protocol`, `requeststyle`, `signature`) need nothing from faire. Alternative: `s3://bucket/prefix`. It has no place for host or encryption, and it isn't a DataLad-resolvable URL, which the profile requires.
- **Kind `s3`**, detected as `datalad-annex::` with `type=S3` (case-insensitive). Any other `datalad-annex::` type stays refused.
- **Early stages: content only.** `git annex initremote <name> <params> autoenable=true`, through `ds.repo`. It is named like the distribution, so `status()` and `content_target()` work unchanged. History stays on the platform, as with RIA storage.
- **Release: storage plus git deposit.** This mirrors datalad-next's `create_sibling_webdav`:
  - a special remote `<name>-storage` with the parameters, found by `content_target()`;
  - a git remote `<name>` with the `datalad-annex::` URL;
  - `remote.<name>.datalad-publish-depends = <name>-storage`.

  Both use the same location. The git deposit is stored as dedicated annex keys, which can't collide with content keys. The superdataset records this URL for the subdataset, so the release resolves without the platform.
- **Stream instances: `fileprefix` + `<instance>/`.** faire sets `fileprefix=<instance>/` when the URL has none. This matches how plain URLs get `/<instance>` appended, and the ma-DMP keeps one distribution per stream.
- **Location uniqueness in validation.** Host, bucket and `fileprefix` are compared across datasets (host defaults to AWS). Stream instances are unique by construction.
- **Credentials:** `CREDENTIALS` maps a kind to a tuple of variables. `s3` maps to `AWS_ACCESS_KEY_ID` and `AWS_SECRET_ACCESS_KEY`, which git-annex reads at `initremote` and `enableremote`. With `embedcreds` refused, git-annex never stores them in the `git-annex` branch.

## Risks / Trade-offs

- [Consumers need datalad-next to clone a release] → stated in the release README and in `docs/profile.md`.
- [Two stages of one dataset at the same location are two remotes over the same keys] → allowed. Each has its own `wanted`. Content sent for one counts only for that remote.
- [S3 tests need an object store] → unit tests cover URL handling. An integration test against MinIO is opt-in through environment variables, like the live GitLab tests, and runs in the tool's CI as a service container.
