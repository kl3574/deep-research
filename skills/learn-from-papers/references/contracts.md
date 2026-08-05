# Paper-reading machine contracts

The human-readable paper card and atom ledger remain the scientific record. These JSON contracts make source identity, span provenance, state, and handoffs independently checkable; they do not automatically decide whether prose entails a claim.

## Layers

| Layer | Contract | Authority |
| --- | --- | --- |
| Source | `PaperSourceBundle/v1` | Original bytes, extracted page artifacts, optional renders, tools, hashes, canonical spans |
| Reading | `PaperReadingDossier/v1` | Question plan, document coverage, scoped claims, evidence relations, cards, conflicts, reconstruction tasks, terminal unknowns |
| Handoff | `PaperReadingReportSet/v2` | Minimal content-addressed projection for a bound review request and knowledge-network controller |
| Legacy | `PaperReadingReportSet/v1` | Historical audit only; never new decisive network evidence |

## `PaperSourceBundle/v1`

Build and verify it with `paper_source_bundle.py`. Evidence locators are recomputed from the verified page artifact and `(page, start_char, end_char)`; caller-provided hashes are never trusted. See [source-bundle.md](source-bundle.md).

## `PaperReadingDossier/v1`

Required domains:

- exact review-request and network snapshot bindings;
- question plan with required subquestions and abstention conditions;
- source-bundle ID, digest, source reference, and original artifact SHA-256;
- access, inspection, and reconstruction states kept separate;
- component manifest for main text and material artifacts;
- atomic claims bound to `hypothesis_id`, `target_id`, scope, relation, verifier status, and evidence IDs;
- evidence records bound to canonical page/character spans, typed visual/equation cards, and reconstruction tasks;
- correction log and explicit terminal unresolved states.

Computed fields, digests, IDs, completion matrices, and eligibility gates are regenerated. A fully unanswerable read is valid when required questions are explicitly abstained and all claims remain `not_tested`; it must project as terminal coverage, not support.

## `PaperReadingReportSet/v2`

The projection preserves the dossier ID/digest, network and review-request bindings, source-bundle ID/digest, source artifact SHA-256, access/inspection/reconstruction status, and completion matrix. Each claim report carries:

- report ID/digest and dossier binding;
- hypothesis, target, atomic statement, and complete scope;
- `supports | qualifies | refutes | not_tested`;
- computed claim-support eligibility and decisive/terminal status;
- source-rooted evidence bindings with evidence ID, canonical locator, page/offsets, span ID, and span hash.

Only a decisive, eligible `supports` report can support a patch proposal. `refutes` maps to contrary evidence; `qualifies` and `not_tested` remain non-supporting. A discovery DOI/URL is an acquisition locator and must never replace the source passage locator in network provenance.

## Trust boundary

Validation proves closed schemas, exact content digests, ID derivation, source/bundle linkage, locator integrity, cross-record bindings, and honest execution states. It does not prove author identity, source authenticity beyond the supplied bytes, semantic entailment, correctness of an OCR/parser, or successful scientific replication. Those require identity checks, render inspection, independent relation verification, and task-specific evaluation.

## Failure policy

Fail closed on unknown fields, symlinks/path traversal, stale or missing artifacts, non-UTC timestamps, digest/ID mismatch, source tampering, locator laundering, claim/evidence relation mismatch, scope mismatch, false execution state, missing required render, broken request/network binding, or caller-supplied outcome inconsistent with the v2 relation.
