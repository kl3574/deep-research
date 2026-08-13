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
   For note-aware Zotero ingest, pair the inventory with its semantic snapshot;
   a one-time legacy migration also requires the prior semantic snapshot bound
   to the currently authoritative inventory.
3. Preserve scope, locator, source version, polarity, independence group,
   assumptions, exclusions, and defeaters. Never upgrade evidence strength.
   Before any new scientific append, replay the finalized evidence-appraisal
   package against its detached approval, prepared request, independent review,
   actual `EvidenceAppraisalOwnerBundle/v1` files and receipts, complete lineage,
   and externally expected authority digest. Then create an owner-derived
   evidence-appraisal binding and separately review its exact operation
   projection. Single-reading v2 proposals use Binding/Projection v1;
   multi-reading `NetworkPatchProposal/v3|v4` uses Binding/Projection v2 and must
   authorize every ordered origin-gap transition. Before appraising v3/v4,
   stable-read its EvidencePack/v2 preconsumption hypotheses, LFR request set,
   reading collection, and detached collection-consumption authority; require
   the caller-held raw authority-file SHA-256 and replay NGD's authorized
   consume-and-propose API. Bindings and events retain only ordered
   owner-binding digests, never runtime paths.
4. Run `derive-gaps`, `validate`, and `status` after substantive changes. Resolve
   or narrow gaps only through append-only transitions with evidence references.
5. Create a snapshot, then export the validated projection. Keep the ledger and
   snapshot as the audit source of truth.

Use `scripts/knowledge_network.py --help` for commands and fields.

## Gates

- Only `supports` is decisive coverage. Preserve `qualifies`, `contradicts`, and
  `not_tested`, but never count them as decisive support.
- New `add-claim`, `add-evidence`, scientific `add-relation`, and evidence-based
  `transition-gap` appends require the same finalized binding and reviewed exact-
  operation projection at the low-level CLI. There is no `resolve-conflict`
  mutation command; conflicts change only through appraised evidence/relation
  appends and derived state. Exact no-ops remain no-ops. `add-source`, unreferenced
  entity maintenance, validation, status, snapshot, export, ingest, and derive do
  not consume appraisal authority.
- `record-gap` creates only an initial `open` row and accepts no resolution
  evidence or resolution source. Use `transition-gap` for every blocked/resolved
  state, so evidence-based resolution cannot bypass the appraisal gate.
- Map `decisive_within_scope` only to `supports` or `contradicts`. For
  `qualified_only`, each admissible upstream `supports`, `qualifies`, or
  `contradicts` verdict projects only to `qualifies`; it never preserves or
  upgrades the directional stance. `context_only`, `inadmissible`,
  `unresolved`, and `not_tested` cannot authorize a scientific mutation. Scope
  must be explicitly reviewed as matching. Duplicate source/study lineages share
  one independence group regardless of reviewer count.
- A candidate set, self-resealed package, stale network binding, relation/scope
  mismatch, or replayed operation fails closed with no override. Legacy ledgers
  remain readable and legacy patch decisions are labeled `not_appraised_legacy`;
  they cannot authorize a new scientific append.
- Proposal v3/v4 must carry the byte-identical
  `ReviewedEvidenceCollectionConsumption/v1` receipt produced by direct reviewed
  selection. Handcrafted `results`/`content_found`, a missing or tampered
  `ReviewedEvidenceCollectionConsumptionAuthority/v1`, or a missing/wrong
  caller-held raw authority-file pin cannot enter validation, preparation,
  appraisal binding, or apply. Proposal v1/v2 behavior remains unchanged.
- Proposal v4 is a closed action union. Claimless origin gaps use the unchanged
  `propose_relation + NetworkPatchTargetClaim/v2` route. Origin gaps that all
  bind the same nonempty current claim ID use
  `propose_evidence_extension + NetworkPatchExistingClaimRef/v1`; mixed,
  multiple-claim, missing, duplicate, stale, or superseded claim routes fail
  closed. The existing-claim reference binds the full live claim row, exact
  semantics, and typed scope. Its accepted operation sequence is exactly
  `N add-evidence`, `N add-relation`, then `M transition-gap`, with zero
  `add-claim` operations.
- A high-impact claim requires decisive evidence from at least two distinct
  source IDs and at least one full-text source. `EvidenceAppraisalNetworkProjection/v2`
  can execute only through the staged `network_patch` transaction; direct
  low-level scientific commands reject it so a multi-gap decision cannot leave
  a partial append.
- Before a staged patch commits, every accepted resolution of a deterministically
  derived gap is re-derived from the staged records. If the same predicate still
  emits that gap, the transaction fails and the live network remains unchanged.
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
