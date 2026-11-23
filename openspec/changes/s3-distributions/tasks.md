# Tasks

## 1. Profile

- [x] 1.1 Validate S3 `access_url`s (bucket, encryption, no `embedcreds=yes`) and unique host/bucket/`fileprefix` across datasets; verify with tests for each scenario of the `madmp-profile` delta
- [x] 1.2 Document the S3 form, its parameters and the uniqueness rule in `docs/profile.md`; verify the example validates with `faire validate`

## 2. Remotes

- [x] 2.1 Add kind `s3` and stream-instance `fileprefix` handling in `remotes.py`; verify with unit tests on URLs with and without `fileprefix`
- [x] 2.2 Create content-only S3 remotes for `collection`/`accepted` (`initremote` with the URL's parameters and `autoenable=true`, then `wanted`); verify with a unit test of the `initremote` arguments built from a URL (`initremote` contacts the bucket, so creation itself is covered by 3.1)
- [x] 2.3 Create release remotes as `<name>-storage` plus a `datalad-annex::` git remote with publish dependency; verify that history and content pushed there clone back (local test with a git-annex directory remote standing in for the bucket; S3 transport in 3.1)
- [x] 2.4 Require `AWS_ACCESS_KEY_ID` and `AWS_SECRET_ACCESS_KEY` before creating an S3 remote; verify the missing-credential scenario with a unit test

## 3. Integration

- [ ] 3.1 Opt-in test against MinIO (environment variables, like the live GitLab tests): accepted sync, stream instances under their prefixes, release cloned from the `access_url` with the platform unreachable; add a MinIO service to the tool's CI and verify the test runs there
