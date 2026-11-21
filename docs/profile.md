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
| `superdataset.template` | yes | Copier template of the study superdataset (see Template) |

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
| `path` | no | Relative path in the study superdataset, e.g. `derivatives/fmriprep`. No segment may contain `.`, and no path may equal or contain another. Without a path the dataset is not registered in the superdataset. |

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
