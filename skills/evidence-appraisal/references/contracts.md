# Evidence appraisal contracts

## Public API

The original public operations remain `ContractError`, `prepare_appraisal`,
`finalize_appraisal`, `validate_appraisal_set`, and `reconcile_appraisal`.
Package-level operations are `create_reviewed_authority`,
`build_appraisal_package`, and `validate_appraisal_package`.

## Candidate and approved artifacts

`EvidenceAppraisalSet/v1` is a sealed candidate, not an approval. It contains
its lineage ID/cycle/prior reference, immutable predecessor summary, exact
`OwnerArtifactBinding/v1` records and their ordered digests, finalized
relation appraisals, content-addressed current challenge and need IDs, and the
exact matching semantic-digest lists. Its SHA seal covers all of that content.

A final `EvidenceAppraisalPackage/v1` contains the candidate set, current
challenge artifacts, current `TargetedEvidenceNeedSet/v1`, immutable
predecessor refs, owner-binding digests, and `approval_ref`; its seal covers
the entire projection. It never contains runtime artifact paths.
The validator requires the actual `ReviewedEvidenceAppraisalAuthority/v1`, the
prepared request, independent review, and `EvidenceAppraisalOwnerBundle/v1`,
then replays all derived content and every owner artifact.
A self-resealed package cannot reuse an old approval.

`validate_appraisal_package` and `build_appraisal_package` require the caller's
external `expected_authority_sha256`. This is the trust boundary: a newly
self-created reviewer reference and authority artifact is rejected unless its
exact authority digest equals the caller-pinned value. No PKI is embedded in
this skill.

The authority artifact binds `prepared_request_file_sha256`,
`prepared_request_digest`, `independent_review_file_sha256`,
`independent_review_digest`, the exact owner-binding digest universe,
`candidate_set_digest`, `candidate_package_digest`, decision, complete-scope,
no-known-omission, and independent reviewer context. File SHA values are SHA-256
of the exact canonical source/review-file projection; review digest additionally
covers that file SHA.

## Owner artifact replay

`prepare_appraisal(request, prepared_request_file_sha256=None,
owner_artifact_bindings=())` requires an exact ordered list of
`OwnerArtifactBinding/v1` objects. Each has exactly `schema`,
`artifact_schema`, `role`, `lineage_id`, `id`, `raw_file_sha256`,
`content_or_semantic_digest`, `owner_validator`, and `status`. The allowlisted
roles are one `source` (`PaperSourceBundle/v1`, verified), one `dossier`
(`PaperReadingDossier/v1`, finalized), one `report`
(`PaperReadingReportSet/v2`, finalized), and one or more `attestation`
(`VerificationAttestation/v1`, passed). Validator IDs are fixed to the LFP
adapter names in the implementation; unsupported schemas and statuses fail.

`finalize_appraisal(prepared, review, owner_bundle)`,
`reconcile_appraisal(prior, prepared, return_set, review, owner_bundle)`,
`create_reviewed_authority(..., owner_bundle)`,
`build_appraisal_package(..., owner_bundle, ...)`, and
`validate_appraisal_package(..., owner_bundle, ...)` require runtime entries
with exact binding digest, actual artifact path, verification-receipt path,
and role-specific LFP inputs. A receipt is necessary but insufficient: the
validator recomputes the raw file SHA and reruns LFP `verify_bundle`,
`validate_dossier`, finalized `validate_report_set_v2`, and external passed
attestation validation. Source/dossier/report/attestation IDs and digests must
form one exact LFP lineage, and report verification raw hashes must exactly
cover the supplied attestation artifacts.

The complete-scope and no-known-omission authority flags are accepted only on
this replay path. For a reconciled package, the owner bundle covers the exact
deduplicated union of every immutable lineage cycle. Paths remain runtime-only;
the package stores digest references only.

## Relation rules

A final `EvidenceAppraisal/v1` adds content-addressed `appraisal_id` and
`semantic_digest` to the claim/evidence, verdict, domain, scope, lineage,
locator, attestation, reproducibility, and optional prior-appraisal-supersession
content. An attestation contains an exact locator atom, non-opaque binding
digest, state, decisive flag, and explicit supersession reference.

Every selected `owner_attestation_binding_digest` must replay to its exact
same-lineage finalized LFP report verification artifact. Its attestation
`subject_digest`, `claim_id`, and full `evidence_bindings` must equal that
report's verified subject; the current relation must match the owner `claim_id`,
one owner `evidence_id`, and its locator. A path atom of the form
`pages/page-%04d.txt#char=start-end` matches an owner binding only when its page
and character endpoints exactly match. A local passed `decisive=true` is not an
assertion by the reviewer: it requires the owner attestation and report to be
passed, support-candidate eligible, in a decisive LFP verification mode, and
projected as decisive. `decisive_within_scope` and `qualified_only` require at
least one such owner-eligible passed reference; a local failed/pass supersession
may cite the same external passed owner attestation for both local states.

The eight fixed domains are `provenance`, `scope_match`, `design`,
`measurement`, `analysis`, `independence`, `reproducibility`, and
`reporting_completeness`. Key domains are the first five plus reproducibility.
Any defeated domain requires `inadmissible`; decisive requires key domains
satisfied/not-applicable, `supports` or `contradicts`, reproduced state, and at
least one passed decisive attestation. Qualified/context/unresolved outcomes are
closed by the validator rather than inferred from a score.

## Locator, need, and reconciliation rules

A locator is exactly `{source_ref, locator}` with its source in `source_lineage`.
Plain atoms such as `p. 1` cannot contain a range, comma, conjunction, slash,
ampersand, Unicode separator, or multi-location separator. The one structured
plain exception is learn-from-papers' exact `p.N [start:end]` page-character
atom, where `N` is positive and `end > start`; it remains one location, not a
page range. A path/fragment atom must exactly match a safe relative path plus one marker:
`safe/relative-path#(char|line|page|eq|fig|table|section)=safe-span`.
For example, `pages/page-0001.txt#char=10-80` is valid, while `p.1/p.2`, a
spaced slash, `&`, multiple `#` markers, and a fragment-free path are rejected.
Split compound citations into individual atoms.

Challenge and need semantic IDs are `challenge-<sha256>` and `need-<sha256>`.
The frozen goal formatter emits:

```text
target_metric=<...>; comparator=<...>; boundary=<...>; observation=<operator> <value_or_state>; claim_implication=<supports|challenges>
```

Confirm and refute share target metric, comparator, boundary, and exact
`value_or_state`; their operators are complementary and implications are
supports/challenges.

A `TargetedEvidenceNeed/v1` includes `domain_anchors` in its semantic content.
For `scholar_discovery`, it is an ordered list of two through six unique short
phrases; for every other route it is exactly `[]`.

For cycle `n > 0`, request, set, and return set all name the exact same-lineage
cycle `n - 1` ID/digest/cycle. New artifacts bind the next set. Previous
artifacts remain bound to their old seal and are retained by immutable
predecessor refs. A repeated claim/evidence pair is allowed only with an exact
`supersedes_prior_appraisal_ref` to the latest prior-lineage relation. Challenge
and need `relation_ref` values name exact claim/evidence plus `appraisal_id` and
`semantic_digest`, so they cannot silently retarget a different appraisal version.

`reconcile_appraisal(prior, prepared, return_set, return_review, owner_bundle)` accepts only
an already-prepared next-cycle request. It never creates a request internally or
substitutes a default raw/canonical file SHA.
