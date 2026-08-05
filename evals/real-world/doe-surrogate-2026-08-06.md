# DoE and surrogate-model real-world forward test, 2026-08-06

## Objective

Test the skill group in an end-to-end research scenario rather than auditing
interfaces in isolation. The run started from an existing Zotero corpus,
repaired local delivery, persisted reviewed claims and gaps, rendered a usable
knowledge network, executed a gap-driven discovery round, and converted actual
failures into tested skill changes.

## Bounded result

| Surface | Result | What it does not prove |
| --- | --- | --- |
| Zotero corpus | 45 parents; 45 short titles; 45 exactly-one nonempty notes | Cloud sync |
| Local full text | 42 parents with readable PDFs; 3 explicit metadata-only parents | Lawful access to every paper |
| Attachment writes | 12 committed and read back; no deletions | An independent `0.1.5` mutation |
| Network | 423 nodes, 437 relations, 45 current sources, 233 visible gaps | Complete domain ontology |
| Structure fix | 196 reviewed `about` edges; isolated entities 111/112 to 0/112 | Inferred entity-to-entity semantics |
| Publication | Two byte-identical private HTML renders; browser-load clean | Public release of private research data |
| Gap discovery | 3 gaps, 12 candidates, 8 Tier A, 0 gaps closed | Candidate metadata as evidence |

## Runtime evidence

Bridge `0.1.4` executed the live writes. The hardened `0.1.5` packed XPI was
then activated in Zotero `9.0.6` and passed allow-list probe, three positive
transaction readbacks and a real negative target-membership readback. Repeating
the attachment mutation was intentionally avoided because proving a version
number is not a valid reason to create a duplicate PDF.

The private evidence pack is checked by:

```bash
python evals/real-world/audit_zotero_bridge_run.py \
  --evidence-pack /approved/private/evidence-pack.json \
  --output /approved/private/audit.json
```

The auditor fails closed on artifact hash drift, wrong execution profiles,
unverified attachment rows, local acceptance count drift, false target
membership, stale map binding, missing current bibliography, nondeterministic
HTML, remote resources, or a cloud-sync completion claim.

## Gap-driven discovery observations

Crossref, OpenAlex and Semantic Scholar were exercised as autonomous providers.
The final status is `partial_provider`: Crossref returned useful bounded
candidates plus one 429, anonymous Semantic Scholar calls returned 429, and
Google Scholar was preserved as `not_provided_manual_optional`.

Representative Tier-A identities include:

- [Distributed active subspaces for function-valued outputs](https://doi.org/10.1007/s10915-020-01346-2)
- [Input and field-output dimensionality reduction for fast surrogates](https://doi.org/10.1016/j.ress.2020.106986)
- [Deep operator surrogate models with uncertainty quantification](https://doi.org/10.1016/j.ijheatmasstransfer.2023.124813)
- [Active-subspace benchmarking against Sobol and Morris](https://doi.org/10.1016/j.envsoft.2022.105310)
- [Inverse stochastic microstructure design](https://doi.org/10.1016/j.actamat.2024.119877)
- [Batch Bayesian optimization for materials design](https://doi.org/10.1016/j.commatsci.2022.111417)

These are discovery candidates only. None was promoted into Zotero notes,
evidence relations or a closed gap without full-text review.

## Improvements caused by the run

1. Replaced source-existence readback with exact target-membership enforcement.
2. Split database-atomic metadata writes from exactly-one attachment imports.
3. Added `0600` structured failure receipts and commit-state-safe errors.
4. Fixed Zotero pagination beyond 100 parent and child rows.
5. Added current bibliography enrichment to network export and publication.
6. Added deterministic claim-to-entity relations from explicit reviewed fields.
7. Preserved scientific semantic labels and removed internal IDs from queries.
8. Stopped manual Scholar placeholders from consuming autonomous query budget.
9. Removed the stable development proxy installer and expanded XPI negative tests.
10. Separated source acquisition from Zotero curation ownership.

## Honest stopping state

The research network is useful and persistent, but not complete. Ten explicit
high-priority gaps and eleven high-impact claims without decisive evidence stay
open. HTTP 429 coordination, DOI identity closeout, work-family grouping and
stronger domain screening remain deferred. Google Scholar remains a manual
export path. This is pragmatic, audited partial coverage rather than a novelty
or completeness claim.
