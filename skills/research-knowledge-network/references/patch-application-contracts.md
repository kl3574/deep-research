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

The acceptance is a governance authorization, not scientific verification.
Without a configured cryptographic trust store, its operator and authority
identities are auditable assertions. The CLI therefore always requires a
separate explicit acceptance file and never manufactures or self-authorizes one.

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
RKN `independence_group` is always the evidence `source_id` lineage. Reviewer or
verifier identity remains audit provenance and must never stand in for source
independence: two verifiers of one source are one source stream, while one
verifier checking two sources leaves two source streams.

## Plan and acceptance

`prepare-patch` projects every v2 action into a content-addressed
`NetworkPatchPlan/v1` with status `pending_acceptance`. It cannot execute.

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
basis-matched relation and an optional final transition. `propose_evidence`
allows one exact evidence append and optional transition. Until the upstream
action carries a closed, hashed target-node payload, `propose_node` may be
rejected or deferred but can never be accepted. It cannot inject source metadata
or unconstrained claim entity, impact, coverage, benchmark, or supersession
fields. Foreign operations,
cross-basis source/claim/evidence/locator changes, reordered prerequisites, and
unrelated entity injection fail closed. A relation is materialized as the exact
content-addressed `target_claim`, one reviewed evidence record per basis, and one
typed `supports` claim-to-evidence relation per basis; the query-like
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
leaves the live network unchanged. Without `--dry-run`, the same validated copy
replaces live state and all ledgers through the existing transaction journal
under an exclusive lock. Repeated acceptances and second terminal decisions
fail closed. Governance events advance the network audit snapshot even when
every decision is reject or defer. Therefore a deferred action requires a newly
regenerated, rebased proposal/plan/acceptance bound to the next snapshot; the
original proposal cannot be reused.

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
