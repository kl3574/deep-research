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
4. Emit search requests only for hypotheses marked `selected` by `prioritize`.
   Structural or semantically unenriched proposals remain unselected. Search, reading, and
   evidence review happen in their owning skills.
5. Consume reviewed results and emit a proposal-only network patch. A separate
   `$research-knowledge-network` step validates and applies any accepted change.

Use `scripts/network_gap_discovery.py --help` for commands and schemas.

## Gates

- Work under open-world assumptions. Absence is a candidate gap, not proof of
  novelty, nonexistence, or completeness.
- Keep candidate signals and generated hypotheses within the documented total
  budget; preserve suppression counts and full inventories for audit.
- Dedupe semantically equivalent signals across gap, claim, isolate, and
  structural families.
- Missing, malformed, stale, or mismatched inputs fail closed. Never promote an
  unreviewed search result into evidence or a graph mutation.

## Boundaries

This skill does not browse, query Google Scholar, deep-read papers, adjudicate
claims, write Zotero, or merge the network. Route those actions to
`$scholar-discovery`, `$learn-from-papers`, `$curate-research-to-zotero`, and
`$research-knowledge-network` respectively.
