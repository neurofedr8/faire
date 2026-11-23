# The faire profile of the RDA DMP Common Standard

A faire ma-DMP is a valid [RDA DMP Common Standard v1.3](https://github.com/RDA-DMP-Common/RDA-DMP-Common-Standard)
document. faire adds a `faire` property to a few objects and otherwise reads standard fields.
Remove every `faire` property and the document still validates against v1.3.

Check a plan with:

```
faire validate dmp.json
```

Full example: [`examples/madmp/single_site.json`](../examples/madmp/single_site.json).

## `dmp.faire`

| Key | Required | Meaning |
|---|---|---|
| `sample_entities` | yes | Ordered entity names identifying a sample, e.g. `["subject", "session"]` |

## `dataset`

Standard fields faire reads:

- `dataset_id.identifier`: unique in the plan; letters, digits, `_`, `-`. Used in paths and repository names.
- `related_identifier` with `relation_type: IsDerivedFrom`: the dataset's sources. An identifier that
  matches a plan dataset is a source. One that matches nothing is an error if it uses the same
  identifier `type` as the plan's datasets, and is ignored otherwise (e.g. the DOI of a public atlas).
  Sources must not form a cycle.
- `technical_resource`: an entry with a `faire` property is an instrument (below).

`dataset.faire`:

| Key | Required | Meaning |
|---|---|---|
| `template` | yes | Copier template of the dataset |
| `path` | no | Relative path in the study superdataset, e.g. `derivatives/fmriprep`. No segment may contain `.`, and no path may equal or contain another. Without a path the dataset is not registered in the superdataset. Path `.` makes the dataset the study superdataset (see below). |

### The study superdataset

The superdataset is the dataset declaring `path: "."`: at most one, without sources or instruments,
required as soon as another dataset declares a path. It has a template and distributions like any
dataset, so it may also hold annexed files; a RIA `access_url` hosts both its history and its
content. faire registers every dataset with a path in it and tracks the ma-DMP there.

### Template

```json
{"repository": "https://github.com/lab/faire-template-bids", "version": "v1.2.0", "data": {"task": "rest"}}
```

`version` is a pinned tag or commit; `data` holds copier answers.

## Instruments and streams

An instrument (scanner, physiological recorder, electronic notebook...) is a `technical_resource`
of the dataset it feeds:

```json
{"name": "Siemens Prisma Fit", "faire": {"instrument_id": "PrismaFit16001", "site": "a"}}
```

A dataset declaring instruments is a **sourcedata stream**. It has no sources and no path, and it
is realised as one dataset per instrument, named `<site>_<instrument_id>` (here `a_PrismaFit16001`).

## `distribution`

Standard `access_url` holds the DataLad URL of the remote: `ria+ssh://…`, `ria+file://…`, `ssh://…`,
a local path, or a `datalad-annex::` URL. It must not contain credentials. `host.url` stays the
human landing page of the service.

`distribution.faire`:

| Key | Required | Meaning |
|---|---|---|
| `stage` | yes | `collection`, `accepted` or `release` |
| `wanted` | yes | git-annex preferred-content expression selecting the content this remote receives, e.g. `not metadata=distribution-restrictions=*` |

Each dataset lists its own distributions in full, even when several datasets push to the same host.

### S3

An S3 bucket is addressed with a `datalad-annex::` URL whose query holds the parameters of a
git-annex [S3 special remote](https://git-annex.branchable.com/special_remotes/S3/):

```json
"access_url": "datalad-annex::?type=S3&encryption=none&bucket=studyx&fileprefix=rawbids/&host=s3.example.org&protocol=https&port=443"
```

- `bucket` and `encryption` are required; the bucket must exist. `host` defaults to AWS; use
  `host`, `port`, `protocol`, `requeststyle=path` or `signature=v4` for other stores.
- Each dataset needs its own location: two datasets may not share host, bucket and
  `fileprefix`. A stream's instances share its URL; each stores under
  `<fileprefix><site>_<instrument_id>/`.
- `collection` and `accepted` remotes hold annexed content only (history stays on the
  platform); a `release` remote holds history and content, and `datalad clone <access_url>`
  installs the dataset from it (with [datalad-next](https://github.com/datalad/datalad-next)).
  Recent git-annex asks a clone to confirm the bucket once before getting content:
  `git annex verifyremote <name>-storage` (faire does this for its own remotes).
- Credentials come from `AWS_ACCESS_KEY_ID` and `AWS_SECRET_ACCESS_KEY` in the environment;
  `embedcreds=yes` is refused.
