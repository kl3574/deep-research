# Controlled network patch contracts

## Authority boundary

`NetworkPatchProposal/v1` is audit-only. It loses report, dossier, source-bundle,
claim, evidence, span, and independent-verification identities, so it can never
enter `prepare-patch` or `apply-patch`.

`NetworkPatchProposal/v2` closes the machine-verifiable handoff from
`network-gap-discovery`, but remains a proposal. The RKN consumer recomputes all
content-derived IDs and digests, checks the current exported network snapshot,
and enforces decisive independently verified full-text evidence. Scientific
meaning is authorized only by a separate `NetworkPatchAcceptance/v1`.

`NetworkPatchProposal/v3` is the original applicable multi-reading route for a
new high-impact claim. It preserves the one-paper boundary of
`PaperReadingReportSet/v2` and
binds two or more such lineages through a replayed
`PaperReadingEvidenceCollection/v1`. The proposal is emitted only after NGD
replays a detached
`ReviewedEvidenceCollectionConsumptionAuthority/v1` against the exact
preconsumption `ReviewedGapSelection/v2` hypotheses, LFR request set, and
reading collection. A v2 high-impact, single-source proposal remains readable
for audit, but preparation, appraisal binding, and apply reject it.

`NetworkPatchProposal/v4` preserves v3's authorized multi-reading envelope and
adds a closed existing-claim evidence-extension route. V4 route selection is
determined only from the exact current origin-gap rows: all claimless origins
use the unchanged new-claim route; origins that all carry one identical,
nonempty `claim_id` use the extension route. Mixed claimless/claim-bound origins
or multiple claim IDs are invalid. V4 never converts to v3 for hashing or
validation; its proposal/action IDs bind the native v4 object.

The acceptance is a governance authorization, not scientific verification.
Without a configured cryptographic trust store, its operator and authority
identities are auditable assertions. The CLI therefore always requires a
separate explicit acceptance file and never manufactures or self-authorizes one.

Every accepted scientific operation additionally requires a schema-matched
`EvidenceAppraisalBinding/v1|v2` and reviewed
`EvidenceAppraisalNetworkProjection/v1|v2`. `bind-appraisal` accepts only a package
that the evidence-appraisal owner can replay from the detached approval,
prepared request, independent review, actual `EvidenceAppraisalOwnerBundle/v1`
files and verification receipts, complete predecessor lineage, and an externally
supplied expected authority digest. A self-contained candidate set
or self-resealed package is not authority. The binding remains
`mutation_authorized=false`; only the separate projection review may authorize
exact operations whose relation and scope mapping agree with the appraisal.

## `NetworkPatchEvidencePack/v1`

Every validate, prepare, dry-run, and apply operation requires a runtime evidence
pack. It is a closed, content-addressed path inventory binding the current
`network_ref` and exact proposal ID/digest. Its `artifacts` object contains
canonical absolute path plus SHA-256 pairs for `hypotheses`, `review_requests`,
`reading_reports`, `dossier`, `source_bundle`, and `source_artifact`. A separate
`verification_root` contains a canonical absolute directory path and a digest of
its sorted relative-file-path, SHA-256, and size inventory.

The pack is not a receipt or trust proof. The consumer rejects missing files,
symlinks in any path component, unstable reads, and hash drift, then calls the
strict upstream `network_gap_discovery.propose_patch` with the live network
export. That call reopens the source bundle/source, dossier/report projection,
and independent verification artifacts. Its regenerated v2 proposal must equal
the submitted proposal exactly. Runtime absolute paths never enter the proposal,
network ledger, or published examples.

## `NetworkPatchEvidencePack/v2`

Proposal v3/v4 uses the closed runtime inventory
`preconsumption_hypotheses`, `review_requests`, `reading_collection`, and
`consumption_authority`, each as a canonical absolute path plus raw SHA-256.
The first artifact must be the directly reviewed, still-`selected`
`KnowledgeGapHypotheses/v1`; caller-authored `results` or `content_found` state
is not a substitute. `review_requests` is the exact
`LearnFromPapersRequestSet/v1`, and `consumption_authority` is the detached
`ReviewedEvidenceCollectionConsumptionAuthority/v1`.

RKN stable-reads all four files, validates the authority through NGD's public
owner API, and copies their exact bytes into a private snapshot. It then calls
the schema-matched path-based
`network_gap_discovery.propose_patch_v3|propose_patch_v4`, which replays the
authorized consume before proposing. The regenerated proposal must equal the
submitted proposal exactly, including `consumption_ref`; all four original
files are postchecked for drift. The collection owner separately reopens every
reading group with the official LFP validators and retains ownership of its
report, dossier, source, and verification-tree paths.

For every v3/v4 `validate-patch`, `prepare-patch`, `bind-appraisal`, and
`apply-patch` call, the caller must also pass
`--expected-authority-file-sha256`. This is the SHA-256 of the exact authority
file bytes and is independent of the pack, proposal, and authority's canonical
content digest. It is never inferred from those self-resealable artifacts.
Missing or wrong external pins, missing or tampered authorities, raw/canonical
binding drift, and handcrafted postconsumption hypotheses fail closed. Proposal
v1/v2 plus EvidencePack/v1 retain their existing behavior and require no such
pin.

## Digest convention

`network_ref.sha256` is exactly the validated `KnowledgeNetwork/v1.content_sha256`:
the canonical SHA-256 of the export payload before the top-level
`content_sha256` field is added. It is not a second hash of the completed export
envelope. `snapshot_id` and this digest must both match the live export.

Every cross-skill digest in these contracts is a bare lowercase 64-character
SHA-256 hexadecimal string. Canonical JSON uses UTF-8, sorted keys, compact
separators, and rejects non-finite numbers.

| Object | Digest subject | ID |
| --- | --- | --- |
| evidence basis | omit `basis_id`, `basis_digest` | `network-patch-basis-<16>` |
| action | omit `action_id`, `action_digest` | `network-patch-action-<16>` |
| proposal | omit `proposal_id`, `proposal_digest` | `network-patch-proposal-<16>` |
| plan | omit `plan_id`, `plan_digest` | `network-patch-plan-<16>` |
| typed operation | omit `operation_id`, `operation_digest` | `network-operation-<16>` |
| acceptance | omit `acceptance_id`, `acceptance_digest` | `network-patch-acceptance-<16>` |

## `NetworkPatchProposal/v2`

Top-level fields are closed:

```json
{
  "schema": "NetworkPatchProposal/v2",
  "schema_version": "2.0",
  "proposal_id": "network-patch-proposal-...",
  "proposal_digest": "<64hex>",
  "network_ref": {
    "network_id": "KN", "snapshot_id": "KN-S...", "sha256": "<64hex>"
  },
  "request_ref": {
    "request_set_id": "...", "request_set_digest": "<64hex>",
    "review_request_set_id": "...", "review_request_set_digest": "<64hex>"
  },
  "generated_at": "2026-08-05T00:00:00Z",
  "proposal_only": true,
  "novelty_claimed": false,
  "review_gate": "pending_research_knowledge_network_acceptance",
  "actions": []
}
```

Each action has exactly `action_id`, `action_digest`, `action_type`,
`action_status`, `hypothesis_id`, `target_signature`, `hypothesis`, and
`reviewed_evidence`; `propose_relation` additionally requires `target_claim`.
Allowed action types are `propose_node`,
`propose_relation`, and `propose_evidence`; status is deterministically
`proposed` only for losslessly materializable relation/evidence targets and
`blocked` otherwise. Blocked actions may be rejected or deferred for audit but
can never be accepted or applied, and their plan operation allowlist is empty.
`target_signature` is exactly `{ "target_kind": "...", "signature": "..." }`.
The closed target-kind route is: `node -> propose_node`, `relation ->
propose_relation`, and each of `evidence`, `boundary`, `counterexample`,
`version`, `benchmark`, `benchmark_profile`, `assumption`, `mechanism`, `metric`,
`measurement`, `estimator`, `failure_mode`, and `context` -> `propose_evidence`.
Only relation and exact evidence targets are materializable. Every other valid
kind must carry `action_status=blocked`; it retains complete digest/provenance
validation but has no typed operation allowlist.

`target_claim` is the closed `NetworkPatchTargetClaim/v1` projection. Its
content-derived `claim_id`/`target_claim_digest` bind the reviewed scientific
statement, nullable entity, exact `low|medium|high` impact, coverage dimensions,
benchmark profiles, null supersession, exact typed scope plus scope digest,
epistemic projection (`projection_status`, `claim_support_eligible`,
`inspection_depth`, and evidence relation), gap hypothesis ID, target signature,
and reviewed report claim ID/digest. The consumer never derives these fields from
the target query string or substitutes a default impact. A relation action that
lacks this payload fails closed until the upstream producer emits it from the
hypothesis/request/reviewed-report chain.

The typed `scope` is closed to exactly `scope_statement`, `assumptions`,
`conditions`, `units`, `exclusions`, `defeaters`, `coverage_dimensions`, and
`benchmark_profiles`. The statement is a string; every other field is an ordered
list of non-empty unique strings and may be empty. Top-level coverage dimensions
and benchmark profiles must equal their same-named scope lists item-for-item.
No category is inferred, concatenated, or projected into another. Accepted
claims persist the scope statement and all seven typed lists in the claim ledger
and export.

Each reviewed-evidence basis has these closed fields:

```text
basis_id, basis_digest,
review_request_id, review_request_digest,
report_set_id, report_set_digest,
dossier_id, dossier_digest,
reading_report_id, reading_report_digest,
source_bundle_id, source_bundle_digest, source_artifact_sha256,
source_id, source_digest,
claim_id, claim_digest,
evidence_id, evidence_digest,
span_id, span_hash,
source_ref, acquisition_locator, evidence_locator,
relation, access_level, inspection_depth,
claim_support_eligible, projection_status,
verification
```

`verification` is exactly `{mode, verifier_id, artifact_sha256}`. Eligibility
requires `relation=supports`, `access_level=full_text`,
`inspection_depth=evidence|reconstruction`, `claim_support_eligible=true`,
`projection_status=decisive`, and
`verification.mode=independent_source_check|expert_review`. A URL cannot be an
evidence locator, and `source_ref` must be a local artifact filename.
`evidence_id` must already satisfy the materializable RKN evidence-ID grammar:
2–255 characters from `[A-Za-z0-9._-]`, starting alphanumerically. Proposal
validation rejects an out-of-grammar ID before appraisal, planning, or staging.
RKN `independence_group` is always the evidence `source_id` lineage. Reviewer or
verifier identity remains audit provenance and must never stand in for source
independence: two verifiers of one source are one source stream, while one
verifier checking two sources leaves two source streams.

## `NetworkPatchProposal/v3`

V3 adds top-level `reading_collection_ref {collection_id, collection_digest}`
and the exact authorized-consumption receipt:

```text
consumption_ref = {
  schema = ReviewedEvidenceCollectionConsumption/v1,
  route = direct_reviewed_selection,
  authority_id, authority_digest, authority_file_sha256,
  consumed_hypotheses_sha256
}
```

The authority ID is derived from the canonical authority digest, while
`authority_file_sha256` binds the detached file's exact bytes. The consumed hash
binds the deterministic consumed hypotheses with `cycle_state.consumption_ref`
omitted to avoid self-reference. NGD copies the cycle receipt byte-for-byte into
the proposal; the RKN proposal validators revalidate it, and EvidencePack/v2
must reconstruct the identical receipt from the authority plus caller-held raw
pin.

V3 admits only materializable `propose_relation` actions. Each action adds exact
`subject_ref`, ordered `origin_gap_refs`, and ordered `reading_group_refs`:

```text
subject_ref = {subject_id, subject_digest}
origin_gap_ref = {gap_id, record_id, sequence, status, sha256}
reading_group_ref = {
  reading_group_id, reading_group_digest, source_id,
  report_set_id, report_set_digest
}
```

Every origin ref must be a real current exported gap record, never a `KGH-*`
hypothesis ID. Every group ref equals the collection projection in the same
order. Reviewed bases preserve that order, cover every group, use at least two
distinct source IDs, and contain full-text decisive support.

`NetworkPatchTargetClaim/v2` binds the reviewed claim subject instead of
inferring target semantics from a query. It contains the exact claim text,
impact, typed scope, coverage/profile lists, target signature, `subject_ref`,
`origin_gap_refs`, and one ordered `report_claim_ref` per basis. Each report ref
binds its basis, reading group, report claim, and reading report IDs/digests.
Coverage dimensions and benchmark profiles may be empty, but every supplied
value must already be declared by the bound network requirements; injection or
defaulting fails closed.

## `NetworkPatchProposal/v4`

V4 has the same closed top-level fields as v3, with schema/version
`NetworkPatchProposal/v4` / `4.0`. It retains the exact consumption and reading-
collection references and uses the same EvidencePack/v2 replay. Each action has
the v3 common fields, but is a closed union with exactly one route payload:

- new claim: `action_type=propose_relation` and
  `target_claim=NetworkPatchTargetClaim/v2`, with no `existing_claim_ref`;
- existing claim: `action_type=propose_evidence_extension` and
  `existing_claim_ref=NetworkPatchExistingClaimRef/v1`, with no `target_claim`.

The new-claim route is valid only when every bound current origin gap is
claimless. The extension route is valid only when every origin gap carries the
same nonempty `claim_id`. Mixed claimless/claim-bound origins, multiple claim
IDs, a route/action mismatch, or either union member carrying both/neither
payload fails closed.

`NetworkPatchExistingClaimRef/v1` is closed:

```text
schema = NetworkPatchExistingClaimRef/v1
schema_version = 1.0
claim_id
claim_record_ref = {record_id, sequence, sha256}
claim_semantics = {
  claim_text, entity_id, impact, is_factual,
  scope_statement, assumptions, conditions, units, exclusions, defeaters,
  coverage_dimensions, benchmark_profiles, supersedes
}
scope_digest
claim_semantic_digest
```

`claim_record_ref.sha256` is the canonical SHA-256 of the complete current claim
ledger row as projected in `KnowledgeNetwork/v1.claims`, including its audit
envelope. `scope_digest` hashes exactly `scope_statement` plus the seven typed
lists. `claim_semantic_digest` hashes all thirteen `claim_semantics` fields. The
consumer requires exactly one matching live claim row and rejects a missing,
duplicate, stale, semantically rewritten, or superseded claim.

The reviewed `subject_ref` is reconstructed from the action hypothesis ID and
target signature, the existing claim's exact text, impact, and full typed scope,
plus the ordered origin-gap refs. The action hypothesis must equal the live claim
text. Thus a producer cannot use a newly worded subject to append evidence to an
older claim merely because the claim ID matches.

## Plan and acceptance

`prepare-patch` projects every applicable v2/v3/v4 action into a content-addressed
`NetworkPatchPlan/v1` with status `pending_acceptance`. It cannot execute.

Validation and preparation may retain reject/defer governance without an
appraisal gate, but any accepted scientific apply fails closed unless the full
gate is supplied again and replayed against the current network. The exact
operation digest, target IDs, `network.json`, and all seven ledger byte prefixes
prevent stale use and cross-operation replay. Appraisal does not close or advance
countercheck no-add/streak state.

`NetworkPatchAcceptance/v1` binds the exact network, proposal, and plan. It
records a second-precision UTC decision time, an operator, content-addressed
authority bases, and one ordered decision for every action. Decisions are
`accept|reject|defer`. Accepted actions require one or more content-addressed
typed operations; rejected or deferred actions require zero operations. Every
decision cites an authority basis and a rationale.

Allowed typed operations are `add-claim`, `add-evidence`, `add-relation`, and
`transition-gap`. Their payloads mirror the
existing CLI command arguments exactly, and every operation carries exact
`basis_id`/`basis_digest` references from its own action. `propose_relation`
allows one basis-matched evidence append per basis followed by exactly one
basis-matched relation and an optional final transition in v2. V3 instead
requires one final transition for every ordered `origin_gap_ref`; each binds all
action bases and admitted evidence, targets the exact current record, and
resolves the real gap. Omitting, duplicating, or reordering any transition
rejects the whole acceptance before staging. V4's new-claim route keeps the v3
sequence. Its extension route is exactly `N add-evidence`, then
`N add-relation`, then one `transition-gap` for each of the `M` ordered origins;
it permits zero `add-claim` operations. Both v4 routes reuse
`EvidenceAppraisalBinding/v2` and
`EvidenceAppraisalNetworkProjection/v2`. Each resolved extension transition sets
`resolution_source` to the bound existing `claim_id`. `propose_evidence`
allows one exact evidence append and optional transition. Until the upstream
action carries a closed, hashed target-node payload, `propose_node` may be
rejected or deferred but can never be accepted. It cannot inject source metadata
or unconstrained claim entity, impact, coverage, benchmark, or supersession
fields. Foreign operations,
cross-basis source/claim/evidence/locator changes, reordered prerequisites, and
unrelated entity injection fail closed. A relation is materialized as the exact
content-addressed `target_claim`, one reviewed evidence record per basis, and one
typed claim-to-evidence relation per basis using the exact appraisal projection:
decisive `supports|contradicts` retain their stance, while admissible
`qualified_only` `supports|qualifies|contradicts` all project to `qualifies`;
the query-like
`target_signature` is only an audited binding and is never written as a
scientific claim statement.

Every accepted `add-evidence` payload is the exact closed projection of its
reviewed basis: evidence, target claim, source, supports polarity, exact locator,
source-lineage independence group, action summary, fixed audit note, and
`supersedes=null`. A patch can append reviewed evidence but cannot silently
retire an existing evidence record.

Every basis `source_id` must already exist in the bound live network, and its
live `version_hash` must equal `sha256:<basis.source_artifact_sha256>`. Otherwise
validation/preparation fails with `source onboarding required`; the patch format
does not duplicate bibliographic ingestion. The orthogonal recovery path is
`scholar-discovery` -> `curate-research-to-zotero` -> RKN `add-source` (or
audited snapshot ingestion) -> export a new snapshot -> rerun gap audit,
requests, reviewed reports, and proposal. Onboarding changes the snapshot, so
the old proposal/plan/acceptance is stale and cannot be reused.

## Commit behavior

`apply-patch --dry-run` applies typed operations to an isolated copy, records
all accept/reject/defer decisions there, and runs full RKN validation, but
leaves the live network unchanged. Without `--dry-run`, the validated staged
records are compared with the locked live records. Unchanged state and ledgers
are not replaced; changed ledgers copy the exact live bytes and append only the
validated canonical suffix through the transaction journal. Any staged rewrite
of prior records fails closed. Repeated acceptances and second terminal
decisions fail closed. Governance events advance the network audit snapshot
even when every decision is reject or defer. Therefore a deferred action
requires a newly regenerated, rebased proposal/plan/acceptance bound to the next
snapshot; the original proposal cannot be reused.

After all accepted operations run in staging and before the decision event or
any live replacement, RKN recomputes the complete deterministic derived-gap set.
For each accepted `resolved` transition whose prior row was emitted by
`derive-gaps`, the same gap ID must no longer be derivable. If its predicate
still holds (for example, qualified-only evidence still leaves an unsupported-
high-impact gap), the staged transaction fails and the live bytes remain
unchanged.

`prepare-patch` writes only a previously nonexistent direct child of
`<root>/patch-plans`. Existing targets, symlinks or symlink parents, aliases of
live ledger files, and all paths under `<root>/networks` are refused. Creation is
exclusive and atomic. `--dry-run` writes only an isolated temporary network and
does not alter live state or ledger inodes.

The resulting `patch_decision` event uses a closed field set and its own
recomputed `event_digest`; its record ID, proposal/plan/acceptance IDs, action
IDs, operation IDs, and authority-basis IDs must match their bound digests.
Malformed or extended events block network validation. A handled failure during
multi-file replacement rolls back every replaced live file and removes the
prepared transaction journal; an unrecoverable rollback leaves the journal in
place so later validation and mutation fail closed.

Each accepted typed operation also appends exactly one `appraised_mutation`
event in the same transaction as its scientific row. The event records only
content-addressed package, authority, binding, and projection refs plus operation
and target digests/IDs; it never records scores, note prose, source content, or
private artifact paths. Older decision events remain valid historical input and
are reported as `not_appraised_legacy`, but they cannot be reused for new science.
