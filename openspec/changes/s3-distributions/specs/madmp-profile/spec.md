## ADDED Requirements

### Requirement: S3 locations
An S3 `access_url` SHALL have the form `datalad-annex::?type=S3&<parameters>`, the parameters being those of a git-annex S3 special remote. It SHALL name `bucket` and `encryption`, and SHALL NOT set `embedcreds=yes`. Distributions of two different datasets SHALL NOT share host, bucket and `fileprefix`.

#### Scenario: Valid S3 location
- **WHEN** a distribution's `access_url` is `datalad-annex::?type=S3&encryption=none&bucket=studyx&fileprefix=rawbids/&host=s3.example.org`
- **THEN** validation succeeds

#### Scenario: Missing bucket
- **WHEN** an S3 `access_url` has no `bucket`
- **THEN** validation fails and names the distribution

#### Scenario: Shared location
- **WHEN** `bids` and `fmriprep` each have a distribution with the same host, bucket and `fileprefix`
- **THEN** validation fails and names both distributions

#### Scenario: Embedded credentials
- **WHEN** an S3 `access_url` sets `embedcreds=yes`
- **THEN** validation fails and names the distribution
