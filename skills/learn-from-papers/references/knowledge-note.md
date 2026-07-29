# Structured literature knowledge note

Use this artifact only after the paper card and evidence ledger pass their acceptance gates. It is a compact retrieval surface, not a replacement for the source.

## Note template

```markdown
# <paper title>

## Source and reading status
- Canonical identity:
- Version/publication status:
- Full-text hash:
- Reading depth: map | evidence | reconstruction
- Read/verified at:

## Why this source matters
- Research question it helps answer:
- Role in the field or technical route:
- Decision relevance:

## One-sentence result

## Reconstructed mental model
Problem -> assumptions -> method/argument -> evidence -> conclusion

## Key claims and evidence
| Claim ID | Claim | Evidence and exact locator | Conditions | Confidence |
| --- | --- | --- | --- | --- |

## Method or derivation
- Inputs and outputs:
- Core steps/equations:
- Why the design choices matter:
- Reproduction-critical details:

## Results
- Main quantitative or formal result:
- Uncertainty/comparison/baseline:
- Negative or null results:

## Assumptions, failure boundaries, and rivals

## Relationship to the current knowledge map
- Supports:
- Contradicts or qualifies:
- Depends on:
- Compared with:
- Open question created:

## Reuse
- When to apply:
- When not to apply:
- Next experiment, derivation, implementation, or paper:

## Provenance
- Evidence ledger location:
- Local PDF path/hash:
- Agent inferences are explicitly marked:
```

## Note rules

- Write the explanatory note in Chinese unless the user requests another language.
- Preserve exact paper terminology, notation, units, and version.
- Write every mathematical expression in LaTeX: `$...$` inline and `$$...$$` for display equations. Follow each important equation with Chinese symbol definitions, its role, assumptions, and exact source locator.
- Include only claims that were checked against full text; label abstract-only knowledge.
- Keep exact page/section/figure/table/equation/theorem locators for consequential claims.
- Separate author interpretation from agent inference.
- Retain null results, boundary conditions, and unresolved conflicts.
- Link the note to stable claim IDs used by the wider `$deep-research` evidence matrix.
- Do not paste long copyrighted passages. Paraphrase, using only short necessary quotations.
- Keep the top half useful for breadth retrieval and the lower sections sufficient for depth recovery.

## Zotero handoff

Pass to `$curate-research-to-zotero`:

```yaml
source_id:
parent_identity:
note_title:
canonical_note_markdown_path:
zotero_note_html_path:
zotero_note_html_sha256:
paper_card_path:
evidence_ledger_path:
tags:
related_claim_ids:
reading_depth:
verified_at:
```

The Markdown note is the human-readable canonical projection. The Zotero HTML
file is a separate, deterministic projection that follows
`$curate-research-to-zotero`'s
[`zotero-note-html.md`](../../curate-research-to-zotero/references/zotero-note-html.md)
contract. Do not pass Markdown to a route that requires HTML or silently rename
one representation as the other.

The curation workflow must verify that the HTML note is attached to the intended
parent item and read back its content or a stable content digest when supported.
