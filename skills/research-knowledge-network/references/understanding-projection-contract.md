# Understanding network projection contract

## Boundary

`UnderstandingNetworkProjection/v1` is the only inbound adapter for rich
single-paper understanding. `$learn-from-papers` alone validates
`PaperUnderstanding/v1` and produces `PaperUnderstandingValidation/v1`. RKN
must create the adapter from both validated source artifacts; caller-authored
projection JSON is never sufficient for ingestion.

Use the production path:

```bash
python3 scripts/understanding_projection.py create-projection \
  --understanding paper-understanding.json \
  --validation-record paper-understanding-validation.json \
  --source-bundle paper-source-bundle.json \
  --source paper.pdf \
  --dossier paper-reading-dossier.json \
  --output understanding-projection.json

python3 scripts/understanding_projection.py validate \
  --input understanding-projection.json \
  --understanding paper-understanding.json \
  --validation-record paper-understanding-validation.json \
  --source-bundle paper-source-bundle.json \
  --source paper.pdf \
  --dossier paper-reading-dossier.json
```

Both commands reopen all five upstream paths, rerun authoritative live
understanding validation, deterministically recreate the validation record, and
require exact equality with the supplied record. A content-addressed record with
forged true flags or digests is not evidence of live validation. Only then are
the five domain sections copied verbatim.

## Envelope

The closed top level contains:

- `schema: UnderstandingNetworkProjection/v1` and `schema_version: 1.0`;
- content-derived `projection_id` and `projection_digest`;
- `payload_digest`, binding the ordered five-row payload manifest;
- `understanding_binding` with `understanding_id`, `understanding_digest`,
  `validation_record_id`, and `validation_record_digest`;
- exactly five `projections` rows;
- `consumer: research-knowledge-network` and
  `mutation_authorized: false`.

The five type/path pairs are fixed:

| projection type | source path |
| --- | --- |
| `applicability` | `applicability` |
| `workflow` | `workflow` |
| `math` | `mathematical_principles` |
| `algorithm` | `algorithmic_principles` |
| `conclusion` | `conclusion` |

Each row contains the full opaque upstream `payload`, its SHA-256
`payload_digest`, the verbatim domain `status`, one typed
`paper_understanding_domain` basis reference, and provenance fixed to the RKN
verbatim-copy producer plus the upstream validation record ID/digest. The row
status must equal `payload.status`; basis and provenance fields must exactly
match the envelope binding.

`payload_digest` hashes the canonical ordered manifest of row types, paths,
statuses, and row payload digests. `projection_digest` hashes the full canonical
envelope excluding only `projection_id` and `projection_digest`, and
`projection_id` is `understanding-projection-<digest[:16]>`.

Structural validation catches payload, status, basis, provenance, and identity
tampering. Production validation additionally recreates the adapter from the
original understanding and validation record and requires exact equality. This
source rebuild is what prevents an internally rehashed semantic rewrite from
being accepted. The adapter never authorizes graph mutation.
