# Corpus-first knowledge network

`KnowledgeNetwork/v1` is the content-addressed synthesis state for a research
run. When Zotero is in scope, build it from a read-only snapshot of the existing
target corpus before external search. Missing, conflicting, stale, and
low-confidence relations drive subsequent research.

## Contract

```json
{
  "schema": "KnowledgeNetwork/v1",
  "network_id": "KN-001",
  "snapshot_id": "KN-001-S001",
  "corpus_snapshot": {
    "source": "zotero",
    "target_ref": "private:zotero-target",
    "captured_at": "2026-08-04T00:00:00Z",
    "inventory_digest": "<64 lowercase hex>",
    "item_count": 1,
    "item_refs": ["private:item:SRC-001"]
  },
  "nodes": [
    {
      "node_id": "source:SRC-001",
      "kind": "source",
      "label": "Canonical source identity",
      "status": "active",
      "confidence": "high",
      "provenance": [
        {
          "source_id": "source:SRC-001",
          "locator": "DOI and exact read version"
        }
      ]
    }
  ],
  "relations": [
    {
      "relation_id": "REL-001",
      "from_id": "claim:C1",
      "to_id": "entity:method",
      "predicate": "supports",
      "status": "supported",
      "confidence": "high",
      "provenance": [
        {
          "source_id": "source:SRC-001",
          "locator": "PDF p.4 | Eq. (7)"
        }
      ]
    }
  ],
  "gap_derivation": {
    "rules": ["missing", "conflict", "low_confidence"],
    "derived_gap_ids": ["GAP-001"]
  },
  "gaps": [
    {
      "gap_id": "GAP-001",
      "derived_from": ["REL-001"],
      "reason": "low_confidence",
      "priority": "decision_critical",
      "status": "resolved",
      "next_action": "none; resolved by source:SRC-002"
    }
  ],
  "change_history": [
    {
      "change_id": "CHG-001",
      "action": "merge",
      "object_ids": ["REL-001", "GAP-001"],
      "basis_refs": ["source:SRC-002"],
      "recorded_at": "2026-08-04T00:00:00Z"
    }
  ],
  "completion": {
    "status": "passed",
    "open_gap_ids": [],
    "gate_checks": {
      "corpus_snapshotted": true,
      "provenance_complete": true,
      "conflicts_terminal": true,
      "low_confidence_edges_terminal": true,
      "change_history_recorded": true
    }
  }
}
```

## Merge rules

- Use stable source, claim, entity, relation, and gap IDs.
- Keep relations as first-class records with provenance, locator, confidence, and
  status; never replace an earlier contradiction by silently overwriting it.
- Deduplicate reports of the same study before counting independent support.
- Every merge, update, qualification, deprecation, or conflict resolution adds a
  change-history record and produces a new snapshot digest.
- Worker outputs are proposals. One controller validates and merges them.

## Gap derivation and completion

Every missing decision-critical relation, unresolved support/contradiction pair,
or low-confidence decisive relation derives a gap. A `passed` completion gate
requires a corpus snapshot, locators on consequential relations, terminal
conflicts and low-confidence edges, recorded change history, and no open gaps.
`partial` and `blocked` preserve open gap IDs and the next highest-information
action.

`ResearchHandoff/v1` stores the snapshot path, ID, and actual SHA-256. Public
reports use a redacted projection and never expose the private corpus snapshot.
