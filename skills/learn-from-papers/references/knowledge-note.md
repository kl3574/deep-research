# Structured literature knowledge note

Use this artifact only after the paper card and evidence ledger pass their acceptance gates. It is a compact retrieval surface, not a replacement for the source.

## Note template

```markdown
# <paper title>

## Source and reading status
- Canonical identity:
- Version/publication status:
- Full-text hash:
- Source bundle ID/digest:
- Reading dossier ID/digest:
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
| Claim ID | Target/hypothesis | Claim | Relation | Evidence and exact locator | Conditions/exclusions | Confidence |
| --- | --- | --- | --- | --- | --- | --- |

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
- Preserve `supports | qualifies | refutes | not_tested`; never collapse them into a generic positive note.
- Record abstained required questions and terminal unknowns so retrieval does not turn absence into support.
- Do not paste long copyrighted passages. Paraphrase, using only short necessary quotations.
- Keep the top half useful for breadth retrieval and the lower sections sufficient for depth recovery.

## Machine handoff coordination

This Markdown knowledge note is a human-oriented view and is not equivalent to the machine contract.

For machine-facing note projection, always use `project-note-input` on a validated `PaperUnderstanding/v1`.

Projection requirements:
- input must be schema-valid `PaperUnderstanding/v1`;
- a content-addressed `PaperUnderstandingValidation/v1` must bind the exact
  understanding and have `source_binding_verified: true` after live source,
  bundle, and dossier validation;
- final projection must reopen the understanding, validation record, source
  bundle, source, and dossier; it must reject the supplied record unless it is
  exactly equal to deterministic live regeneration;
- `source_binding.reading_depth` must be `evidence` or `reconstruction`;
- no projected domain may have `unresolved` status;
- all domain status/rationale/evidence metadata, workflow graph metadata,
  structured derivation/algorithm steps, and contribution bindings must remain
  explicit;
- executive-summary claim IDs must be preserved exactly and each must be in
  understood coverage.

If projection fails due to schema or route constraints, capture the CLI error and keep the failure output with the source handoff log.

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

## Zotero projection boundary

Produce source-related semantic content, equations as raw LaTeX, evidence
locators, and natural-language limitations. Do not emit Zotero HTML or embed
hashes, paths, timestamps, transaction state, or tool state in prose. Delegate
HTML escaping, math-node projection, and clean-note validation to
`$curate-research-to-zotero`'s `ZoteroCleanLiteratureNote/v1` contract.
