# PaperKnowledgeNote/v2 Zotero projection

`PaperKnowledgeNote/v2` is a deterministic, offline projection of the reviewed
`PaperUnderstandingNoteInput/v1` handoff from `$learn-from-papers`. It is a
retrieval surface, not new scientific evidence and not a Zotero metadata editor.

## Field ownership

Zotero's current `note` item template contains a note body, tags, collections,
and relations; it does not expose bibliographic `title` or `shortTitle` fields:

- [official note item template](https://api.zotero.org/items/new?itemType=note)
- [official journal-article item template](https://api.zotero.org/items/new?itemType=journalArticle)
- [Zotero item types and fields](https://www.zotero.org/support/kb/item_types_and_fields)

Zotero defines **Short Title** as the short form of a work's title used chiefly
by citation styles. Therefore:

| Value | Owner | Projection target |
| --- | --- | --- |
| canonical research title | source metadata | existing parent `title`, preserved |
| source-supplied bibliographic short title | separate metadata curation | optional parent `shortTitle` update after separate authorization |
| generated research retrieval title | `PaperUnderstandingNoteInput/v1` | child note's first and only `h1` |

This version never generates or writes a parent `shortTitle`. A future opt-in
bibliographic metadata workflow would have to verify that the short title comes
from the source, feature-probe the exact item-type template, obtain separate
authorization, use a version guard, and read back the parent field. It is outside
this renderer and existing-note update contract.

## Input boundary

The accepted upstream schema is exactly `PaperUnderstandingNoteInput/v1`. Its
top-level content domains are:

```text
understanding_binding
executive_summary
applicability
workflow
mathematical_principles
algorithmic_principles
conclusion
contributions
source_binding
coverage
```

Unknown fields fail closed. The consumer validates claim references before
rendering and preserves, rather than infers, each consequential claim's:

```text
claim_id
hypothesis_id
target_id
supports | qualifies | refutes | not_tested
scope assumptions/conditions/units/exclusions
evidence ID, summary, and exact locator
verifier status and confidence rationale
```

The note handoff is a narrow projection, not the full `PaperUnderstanding/v1`
record. In particular, full claim rows and terminal failure boundaries live
under `coverage`; access/read-depth/time also live there. `source_binding`
contains source identity, content digests, dossier/card/ledger references, and
the explicit-agent-inference flag. It does not duplicate coverage fields.
Claims, boundaries, provenance, or a second title at the top level are rejected.

The remaining domain shapes are deliberately explicit:

```text
understanding_binding = understanding ID/digest + validation record ID/digest
executive_summary = research_retrieval_title + summary + claim_ids
domain metadata = status + rationale + evidence_ids + missing_information
applicability = domain metadata + primary_use_case + applies_when + does_not_apply_when
workflow = domain metadata + inputs + preconditions + steps + outputs + data_flow + graph
workflow graph node = ID/kind/description + semantic type/representation/format/shape/unit
workflow graph operation = ID/operation + consumes/produces node IDs
mathematics = domain metadata + assumptions/results + dependency-linked derivation steps
algorithmics = domain metadata + objective/state/invariants/failures + dependency-linked ordered steps
conclusion = domain metadata + statement + claim_ids + confidence/rationale
contributions[] = ID + statement + claim_ids + evidence_ids + domain_refs
coverage = access_level + reading_depth + verified_at + claims + boundaries
```

Each mathematical derivation step retains dependencies, origin, locator, and
evidence IDs. Each algorithm step additionally retains consumed and produced
state. Every mathematical or algorithmic principle retains its structured
steps, origin, claim references, and locator. Every claim/evidence/domain
reference must resolve within the handoff.

`research_retrieval_title` is supplied by the reviewed handoff and becomes the
note `h1`. It must be a single plain-text line in the form
`适用：<scenario>｜结论...：<bounded result>`, use no more than 100 Unicode code
points, and contain no HTML, absolute local path, Zotero-key-shaped token,
digest, DOI, or other provenance identifier. The renderer rejects an overlong
title instead of truncating it.

## Exact pyramid projection

The schema-9 HTML has one root, one `h1`, and exactly these `h2` sections:

1. `适用场景与结论`
2. `工作流程与 I/O / 数据流`
3. `数学原理与推导`
4. `算法原理`
5. `证据、边界与溯源`

The first layer gives the bounded answer and domain status/rationale/evidence.
The second records inputs, preconditions, ordered steps, outputs, checks, data
flow, and typed workflow graph nodes/operations. The third records equations,
assumptions/results, and dependency-linked derivations with origins, locators,
and evidence IDs. The fourth records the objective, state variables, invariants,
failure modes, structured I/O steps, update/stopping rules, complexity, risks,
origins, and locators. The last layer retains contribution claim/evidence/domain
references, the complete claim/evidence table, failure boundaries, source and
understanding/validation bindings, coverage, and the write boundary.

Mathematics or algorithms may be `not_applicable` only with a nonempty reason;
an empty section is invalid.

## HTML, privacy, and size

The projection uses a tag-and-attribute allowlist. Human content is escaped.
Links, remote or embedded images, iframes, objects, embedded resources, event
handlers, URL-bearing attributes, absolute local paths, and private
Zotero-key-shaped tokens are forbidden. All HTML comments are forbidden too,
including comments that hide paths or item keys. Full local file paths remain
in the private ingestion manifest, not the synchronized note.

The project hard limit is 512 KiB of UTF-8 HTML. This is a local policy for
predictable editing, hashing, and readback, not a claim about a universal Zotero
server limit.

## Offline preview and verification

The renderer performs no Zotero request:

```bash
python scripts/paper_knowledge_note.py preview \
  /absolute/private/PaperUnderstandingNoteInput.json \
  --understanding /absolute/private/PaperUnderstanding.json \
  --validation-record /absolute/private/PaperUnderstandingValidation.json \
  --source-bundle /absolute/private/PaperSourceBundle.json \
  --source /absolute/private/paper.pdf \
  --dossier /absolute/private/PaperReadingDossier.json

python scripts/paper_knowledge_note.py render \
  /absolute/private/PaperUnderstandingNoteInput.json \
  --output /absolute/private/paper-note.schema9.html \
  --manifest /absolute/private/paper-note.projection.json \
  --understanding /absolute/private/PaperUnderstanding.json \
  --validation-record /absolute/private/PaperUnderstandingValidation.json \
  --source-bundle /absolute/private/PaperSourceBundle.json \
  --source /absolute/private/paper.pdf \
  --dossier /absolute/private/PaperReadingDossier.json

python scripts/paper_knowledge_note.py verify \
  /absolute/private/PaperUnderstandingNoteInput.json \
  /absolute/private/paper-note.schema9.html \
  --understanding /absolute/private/PaperUnderstanding.json \
  --validation-record /absolute/private/PaperUnderstandingValidation.json \
  --source-bundle /absolute/private/PaperSourceBundle.json \
  --source /absolute/private/paper.pdf \
  --dossier /absolute/private/PaperReadingDossier.json
```

These live provenance arguments are mandatory for all three commands. Keep the
examples synchronized with `paper_knowledge_note.py -h`; a note-input path alone
is not sufficient validation evidence.

`render` creates both outputs exclusively with mode `0600`. It never overwrites
an existing file. `PaperKnowledgeNoteProjection/v1` is content-addressed: its
`projection_digest` hashes the canonical manifest content, its `projection_id`
is derived from that digest, and it retains the exact understanding and
validation-record binding. The manifest binds normalized input and HTML digests
and declares:

```json
{
  "target_item_type": "note",
  "allowed_mutation_fields": ["note"],
  "forbidden_parent_fields": [
    "title",
    "shortTitle",
    "creators",
    "DOI",
    "date",
    "publicationTitle"
  ],
  "parent_bibliographic_fields_preserved": true,
  "zotero_write_performed": false
}
```

`verify` requires byte-for-byte equality with a fresh deterministic projection.
The shared schema-9 verifier also recognizes `PaperKnowledgeNote/v2`, so later
curation staging rechecks title, section order, privacy, provenance columns,
source artifact hash, and the parent-field preservation statement.

Any migration preparation that consumes v2 HTML must receive the matching
manifest explicitly:

```bash
python scripts/prepare_note_migration.py ... \
  --projection-manifest /absolute/private/paper-note.projection.json
```

Preparation, direct update, and Zotero Desktop execution re-read the manifest
and source HTML, verify the content address, HTML hash, exact H1, preserved
parent-field contract (including unchanged `shortTitle`), and staged/read-back
HTML before accepting the child-note mutation.

## Later Zotero readback

This offline result grants no write authority. A later approved curation batch
must still bind the exact parent and collection, old note version/content,
projection digest, and source PDF hash. Readback must verify the note item type,
parent, collection membership through the parent, `h1`, exact pyramid sections,
claim table, source and stored digests, and unchanged parent bibliographic
fields. Searchability must be tested with note/full-text search (`qmode=everything`)
or separately authorized note tags; `titleCreatorYear` does not prove that note
content is retrievable.
