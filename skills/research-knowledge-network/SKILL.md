---
name: research-knowledge-network
description: Build or update a persistent, auditable research knowledge network from reviewed evidence. Use when claims, provenance, coverage, conflicts, and gaps must survive across research cycles. Not for discovery, paper reading, Zotero writes, or gap-search planning.
---

# Research Knowledge Network

Persist reviewed research state without changing what the evidence says.

## Required workflow

1. Read [references/knowledge-model.md](references/knowledge-model.md) and
   [references/gap-policy.md](references/gap-policy.md).
2. Use one explicit network root and ID. Validate every reviewed source, entity,
   claim, evidence record, relation, and gap before appending it.
3. Preserve scope, locator, source version, polarity, independence group,
   assumptions, exclusions, and defeaters. Never upgrade evidence strength.
4. Run `derive-gaps`, `validate`, and `status` after substantive changes. Resolve
   or narrow gaps only through append-only transitions with evidence references.
5. Create a snapshot, then export the validated projection. Keep the ledger and
   snapshot as the audit source of truth.

Use `scripts/knowledge_network.py --help` for commands and fields.

## Gates

- Only `supports` is decisive coverage. Preserve `qualifies`, `contradicts`, and
  `not_tested`, but never count them as decisive support.
- Latest open claimless explicit P0/P1 or high-decision-impact gaps block
  completion; apply the documented legacy mapping rather than silently rewriting
  old records.
- Open conflicts, unsupported high-impact claims, stale corpus state, or failed
  provenance/coverage gates remain visible and may block completion.
- A snapshot is bounded evidence state, never a completeness or novelty claim.

## Boundaries

Route discovery to `$scholar-discovery`, one-paper analysis to
`$learn-from-papers`, gap-search planning to `$network-gap-discovery`, Zotero
mutation to `$curate-research-to-zotero`, and HTML rendering to
`$research-network-publish`. This skill does not browse, deep-read papers, search
for missing evidence, or write Zotero.
