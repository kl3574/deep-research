# Publication contracts

## Trust boundary

The publisher consumes final research state. It does not discover papers,
resolve gaps, decide which claims are true, change the network, or write
Zotero. Produce or update research state with the upstream skills, validate it,
then pass immutable JSON exports here.

Both inputs must be ordinary, non-symlink JSON files with unique object keys.
Each carries `content_sha256`, computed from canonical UTF-8 JSON after removing
that one top-level field: keys sorted, no insignificant whitespace, and Unicode
preserved. A mismatch is fatal.

## `KnowledgeNetwork/v1`

The publisher requires these fields:

```json
{
  "schema": "KnowledgeNetwork/v1",
  "network_id": "KN-001",
  "snapshot_id": "KN-001-S001",
  "nodes": [
    {
      "node_id": "claim:C1",
      "kind": "claim",
      "label": "A reviewed claim",
      "status": "active",
      "confidence": "high"
    }
  ],
  "relations": [
    {
      "relation_id": "REL-001",
      "from_id": "claim:C1",
      "to_id": "entity:M1",
      "predicate": "supports",
      "status": "supported",
      "confidence": "high",
      "provenance": [
        {"source_id": "source:S1", "locator": "PDF p.4 | Eq. (7)"}
      ]
    }
  ],
  "gaps": [],
  "completion": {"status": "passed", "open_gap_ids": [], "gate_checks": {}},
  "content_sha256": "<canonical digest>"
}
```

`sources`, `corpus_snapshot`, `gap_derivation`, and `change_history` remain
valid upstream fields. The public projection selects only presentation-safe
bibliographic source fields and never serializes the full input envelope.

## `ResearchMap/v1`

The optional research map is reviewed presentation metadata. It cannot add or
override evidence. Bind it to one exact network snapshot.

```json
{
  "schema": "ResearchMap/v1",
  "network_snapshot_id": "KN-001-S001",
  "title": "Field title",
  "summary": "Decision-oriented scope statement",
  "field_map": [
    {
      "field_id": "FIELD-1",
      "label": "Method family",
      "summary": "What belongs here",
      "node_ids": ["entity:M1"]
    }
  ],
  "competency_questions": [
    {
      "question_id": "CQ-1",
      "question": "When is the method identifiable?",
      "status": "answered",
      "answer": "Reviewed answer",
      "relation_ids": ["REL-001"],
      "gap_ids": []
    }
  ],
  "routes": [
    {
      "route_id": "ROUTE-1",
      "label": "Route name",
      "summary": "Assumptions and decision use",
      "relation_ids": ["REL-001"]
    }
  ],
  "recommendations": [
    {
      "recommendation_id": "REC-1",
      "title": "Recommended next decision",
      "rationale": "Evidence-bound rationale",
      "priority": "high",
      "evidence_refs": ["REL-001"]
    }
  ],
  "content_sha256": "<canonical digest>"
}
```

All four arrays may be empty. Referenced node, relation, and gap IDs must exist
in the bound network. If no map is supplied, the renderer derives a minimal
field grouping from node kinds, relation routes from predicates, and next-step
recommendations from open gaps. It labels competency questions as unavailable
rather than inventing them.

## Privacy modes

`public-redacted` is the default. It:

- replaces internal node, relation, gap, and source IDs with stable ordinal
  display IDs;
- omits corpus targets, attachments, note fields, full text, paths, hashes,
  Zotero keys, and unselected input fields;
- redacts sensitive fragments that appear inside otherwise allowed labels or
  locators;
- includes only the safe projection used to build visible HTML.

`private` preserves exact network IDs and provenance locators for local review.
It still omits note bodies and full text. Both modes recursively reject
credential-shaped keys and credential values, including passwords, API keys,
bearer tokens, cookies, access tokens, and private keys.

## Output contract

The result is one UTF-8 HTML file containing CSS, JavaScript, and SVG with no
external dependencies. It includes:

- field map;
- competency questions;
- route and relation views;
- source cards and exact safe locators;
- coverage, open gaps, and conflicts;
- evidence-bound recommendations;
- deterministic provenance without a generated-at clock.

Rendering sorts all records by stable IDs and uses a fixed SVG layout. The same
validated inputs, renderer version, and mode must produce byte-identical HTML.
Output creation never overwrites an existing path. For a new target, the
publisher creates a uniquely named temporary file in the target directory,
writes UTF-8 bytes, flushes and file-`fsync`s them, then calls `os.replace` and
directory-`fsync`s the target parent. The source and destination of every
replace are therefore on the same target filesystem; callers must not stage in
the system temporary directory or fall back to a non-atomic copy.

Failures before `os.replace` leave any pre-existing target unchanged and
remove the sibling temporary file. A cleanup failure is explicit and reports
the retained temporary path. A directory-`fsync` failure occurs after the
atomic commit: report that state and preserve the committed target rather than
misreporting rollback. Validation creates no output and uses no temporary
publication path.
