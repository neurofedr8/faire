## ADDED Requirements

### Requirement: S3 remotes
A `collection` or `accepted` distribution at an S3 location SHALL get a remote holding annexed content only. A `release` distribution at an S3 location SHALL get both history and content there, so that the dataset can be cloned from its `access_url` alone.

#### Scenario: Accepted on S3
- **WHEN** `faire sync --stage accepted` runs for `bids`, which has an `accepted` S3 distribution
- **THEN** its wanted content is in the bucket under the `fileprefix`, and its history stays on the platform only

#### Scenario: Release on S3
- **WHEN** a release is fulfilled to an S3 distribution of `bids`
- **THEN** `datalad clone` of its `access_url` gets the released history and can get its wanted content

### Requirement: S3 stream instances
Each instance of a stream SHALL use the stream's S3 location with `<instance>/` appended to its `fileprefix`.

#### Scenario: Two scanners
- **WHEN** stream `dicoms` with `fileprefix=dicoms/` has instances `a_PrismaFit16001` and `a_Skyra45012`
- **THEN** their content is stored under `dicoms/a_PrismaFit16001/` and `dicoms/a_Skyra45012/`
