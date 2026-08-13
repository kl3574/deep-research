---
name: network-gap-discovery
description: Audit an existing research knowledge network for likely missing nodes, relations, boundary conditions, or evidence, then emit bounded search hypotheses. Use when open-world gap discovery is needed. Not for browsing, novelty or completeness claims, graph mutation, paper reading, or Zotero writes.
---

# Network Gap Discovery

Turn one immutable, validated network snapshot into bounded, refutable search
hypotheses without mutating research state.

## Required workflow

1. Read [references/contracts.md](references/contracts.md) and
   [references/research-basis.md](references/research-basis.md).
2. Run `scan`; retain the complete audit inventory but bound candidate signals by
   the documented semantic deduplication and tier budgets.
3. Run `generate-hypotheses`, then `prioritize`. Explicit high-impact gaps must
   precede single-source, isolate, and structural noise; never use stable IDs as
   the substantive ranking rule. Claim-backed gaps must resolve their human
   meaning from the current claim node label; opaque claim IDs never become
   paper needs, criteria, or query text.
4. When review narrows the deterministic priority set, run `select` with the
   untouched `prioritize` output and a digest-bound `ReviewedGapSelection/v1`
   allowlist. Use `ReviewedGapSelection/v2` when the review must also authorize
   exact claim subjects, coverage dimensions, benchmark profiles, and current
   origin-gap record references for a multi-reading patch. The command preserves
   every unselected candidate as `proposed`, rejects direct scheduling-status
   edits, and records the reviewed selection reference without interpreting
   evidence.
5. Emit search requests only from a completed `select` output. The emitter
   reconstructs the untouched `prioritize` output and the exact
   `ReviewedGapSelection/v1`, then rechecks both digests in
   `reviewed_selection_ref`. It rejects direct `prioritize` output, fabricated
   provenance, and a reviewed empty allowlist. Only `status: selected`
   hypotheses are emitted. Proposed, structural, or semantically unenriched
   hypotheses never become requests. Search, reading, and evidence review
   happen in their owning skills.
6. Consume reviewed results and emit a proposal-only network patch. The legacy
   single-paper route remains separate. Multi-reading collection consumption
   admits only an exact `ReviewedGapSelection/v2` preconsumption file behind a
   detached, independently reviewed, raw-file-pinned
   `ReviewedEvidenceCollectionConsumptionAuthority/v1`; a handwritten
   `results` status is not authority. The path-owned consumer stable-reads and
   replays the exact LFR set plus `PaperReadingEvidenceCollection/v1`, and
   `NetworkPatchProposal/v3` reruns that deterministic consumption internally.
   Use additive `NetworkPatchProposal/v4` when those exact origin gaps either
   all remain claimless or all bind the same current claim: the former preserves
   the v3 new-claim action, while the latter emits only an evidence-extension
   action bound to the full current claim ledger row and exact typed claim
   semantics. Mixed, multi-claim, stale, superseded, or subject-mismatched
   origins fail closed. Both versions preserve collection order, every current
   origin-gap record reference, and one byte-identical `consumption_ref` in
   cycle and proposal. A separate
   `$research-knowledge-network` step appraises, validates, and atomically
   applies any accepted change.

Use `scripts/network_gap_discovery.py --help` for commands and schemas.

## Gates

- Work under open-world assumptions. Absence is a candidate gap, not proof of
  novelty, nonexistence, or completeness.
- Keep candidate signals and generated hypotheses within the documented total
  budget; preserve suppression counts and full inventories for audit.
- Dedupe semantically equivalent signals across gap, claim, isolate, and
  structural families. When multiple current open gaps share one semantic
  claim subject, coalesce every ordered gap reference into the retained signal
  and hypothesis grounds; deduplication must never discard a gap that a later
  atomic patch must transition. Cross-family duplicates remain suppressed audit
  signals and never inject node or relation refs into open-gap grounds.
- Missing, malformed, stale, or mismatched inputs fail closed. Never promote an
  unreviewed search result into evidence or a graph mutation.

## Boundaries

This skill does not browse, query Google Scholar, deep-read papers, adjudicate
claims, write Zotero, or merge the network. Route those actions to
`$scholar-discovery`, `$learn-from-papers`, `$curate-research-to-zotero`, and
`$research-knowledge-network` respectively.

## Evidence-appraisal and missing-content route

Use `compile-appraisal-needs` for finalized `EvidenceChallenge/v1` and
`TargetedEvidenceNeedSet/v1`. Supply every referenced challenge, the exported
live network, scholar-discovery's `SearchHistoryIndex/v1`, and its separately
approved immutable `HistoryAuthorityManifest/v1` plus the exact
`ReviewedHistoryAuthority/v1` approval it references. Only proposed
needs with `route: scholar_discovery` become hypotheses. Acquisition, full-text,
code/data, experiment, and version routes remain exact records in
`routed_needs`; they never masquerade as paper searches.

Confirm and refute goals must have different semantic concept signatures and
must both bind the referenced challenge axis. Mutual exclusion comes only from
the closed `adversarial_observation_pair`: a shared target metric, comparator,
boundary, and value/state plus an ordered complementary operator pair and
`supports`/`challenges` implications. Free-text polarity, negation scope,
same-direction outcomes, and synonymous rewrites are not orthogonal. Canonical or paraphrased reuse from requested,
selection-leaked, failed, partial, result, or candidate history fails closed.
Partial-provider and empty-result outcomes leave appraisal needs unresolved;
absence is never novelty or nonexistence.

The readable `confirm_goal` and `refute_goal` are not free-form inputs. Each
must byte-match the frozen formatter
`target_metric=...; comparator=...; boundary=...; observation=<operator> <value_or_state>; claim_implication=...`.
Provider query terms are regenerated from that structured pair. The target
metric, comparator, boundary, objective-specific operator, and value/state are
non-truncatable slots: they are placed before any free keywords. Only remaining
budget may contain free context. If the structured core itself exceeds the
12-term query budget, compilation fails closed rather than dropping the
adversarial observation.

The compiler preserves need-set, challenge, claim, appraisal, route, and
history digests through prioritize, reviewed selection, and selected-only emit.
History entries are never trusted as a self-report: the complete embedded
artifact universe is owner-validated and replayed. Appraisal request sets embed
the full reviewed selected document, and both skills reconstruct every request;
origin deletion and unreviewed append therefore fail even after rehashing.

Appraisal-origin emission uses only
`AppraisalScholarDiscoveryRequestSet/v1`. Generic request sets cannot enter
appraisal consume/execute even if every projection and origin is deleted and
the payload is rehashed.

For the producer's compact `EvidenceAppraisalPackage/v1` profile, use
`dispatch-appraisal-package`. It requires the actual detached approval,
prepared request, independent review, and the caller-held
`expected_authority_sha256`; that external pin is passed to the producer's
public package validator. It preserves non-search needs exactly. A compact
`scholar_discovery` need fails closed
because that profile lacks the bounded claim/scope/evidence criteria required
to create a paper search; use the rich finalized need adapter instead.
