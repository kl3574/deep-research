---
name: evidence-appraisal
description: Create replayable claim-to-evidence candidate sets and independently approved final packages. Use after evidence collection when a claim relation needs a fail-closed admission, qualification, contradiction, or unresolved decision.
---

# Evidence Appraisal

## Required workflow

1. Create an `EvidenceAppraisalRequest/v1` and run `prepare_appraisal`.
2. Bind the exact owner universe as `OwnerArtifactBinding/v1` records. Each
   record names a LFP source bundle, reading dossier, finalized report set, or
   external passed attestation, plus its raw-file SHA-256, semantic digest,
   allowlisted validator, and status. Runtime paths and validation receipts are
   supplied separately in `EvidenceAppraisalOwnerBundle/v1`.
3. An independent reviewer creates `EvidenceAppraisalIndependentReview/v1`; its
   review-file digest, reviewer context, owner-binding digests, relation
   attestations, challenge drafts, and evidence-need drafts are fixed.
4. Run `finalize_appraisal` with the owner bundle to create a candidate
   `EvidenceAppraisalSet/v1`.
   A candidate is not an approved deliverable.
5. A distinct reviewer issues `ReviewedEvidenceAppraisalAuthority/v1`, binding
   the exact prepared-request SHA/digest, review SHA/digest, replayed owner
   universe digests,
   candidate set digest, and candidate package digest.
6. Use `build_appraisal_package` and `validate_appraisal_package` with the
   actual authority artifact and an externally supplied expected authority
   digest. A package without that trust-boundary value is invalid even if its
   own SHA-256 seal was recomputed.
7. Use `reconcile_appraisal` only for the next lineage cycle. It preserves the
   predecessor seal, carries an immutable predecessor summary, and requires a
   same-claim/evidence replacement to reference the exact prior appraisal.

## Non-negotiable evidence gates

- Eight categorical domains have no numeric score. Any `defeated` domain makes
  the result `inadmissible`; decisive results require every key domain to be
  `satisfied` or `not_applicable`, a reproduced state, and a passed decisive
  attestation.
- Every locator is one exact atom from `source_lineage`. Plain atoms such as
  `p. 1` are allowed, as is the exact learn-from-papers page-character atom
  `p.N [start:end]` when `N` is positive and `end > start`. A path/fragment atom must exactly use
  `safe/relative-path#(char|line|page|eq|fig|table|section)=safe-span`, for
  example `pages/page-0001.txt#char=10-80`. Other ranges, commas, slashes without a
  valid fragment, conjunctions, ampersands, and multiple markers must be split.
- An attestation binds the prepared request, claim/evidence relation, exact
  locator, and reviewer context. Every failed attestation requires exactly one
  passed replacement for the same atom and binding.
- A selected owner attestation must replay through its finalized LFP report and
  match the current relation's `claim_id`, evidence binding, and exact locator.
  A local `decisive=true`, or a decisive/qualified outcome, is valid only when
  that owner report is `claim_support_eligible=true`, has
  `projection_status=decisive`, and uses a decisive external verification mode.
- Challenge/need IDs are content-addressed. Set seals carry their semantic
  digests. Confirm/refute observations share the exact same value or state and
  use complementary operators.
- `scholar_discovery` needs must carry two through six short, unique
  `domain_anchors`; their exact list is semantic content for query compilation.
  Non-scholar routes carry an empty list.
- A final report must replay through LFP with `require_finalized=True`, and all
  report verification artifacts must be covered by external passed attestation
  bindings. A missing, unsupported, unfinalized, swapped, or newline-modified
  owner artifact fails before complete-scope approval. Public packages retain
  binding digests only, never runtime paths.

## CLI

```bash
python3 scripts/evidence_appraisal.py prepare request.json prepared.json \
  --owner-binding source.binding.json --owner-binding dossier.binding.json \
  --owner-binding report.binding.json --owner-binding attestation.binding.json \
  --owner-bundle owner-runtime.json
python3 scripts/evidence_appraisal.py finalize prepared.json review.json candidate-set.json \
  --owner-bundle owner-runtime.json
python3 scripts/evidence_appraisal.py authority prepared.json review.json candidate-set.json approval.json \
  --reviewer-ref authority-1 --review-method independent-check --reviewed-at time-1 \
  --owner-bundle owner-runtime.json
python3 scripts/evidence_appraisal.py package candidate-set.json prepared.json review.json approval.json final-package.json \
  --expected-authority-sha256 <externally-pinned-authority-digest> --owner-bundle owner-runtime.json
python3 scripts/evidence_appraisal.py validate final-package.json \
  --approval approval.json --prepared prepared.json --review review.json \
  --expected-authority-sha256 <externally-pinned-authority-digest> --owner-bundle owner-runtime.json
```

For reconciliation, prepare the exact next-cycle request independently, then
pass that prepared artifact rather than allowing reconcile to construct one:

```bash
python3 scripts/evidence_appraisal.py reconcile prior-set.json next-prepared.json return-set.json return-review.json next-set.json \
  --owner-bundle next-owner-runtime.json
```

Run `python3 scripts/quick_validate.py` for the bounded fixture health check.
