---
name: network-gap-discovery
description: Use when an existing research knowledge network must be audited under open-world assumptions to propose, prioritize, search, refute, and document likely missing nodes, relations, boundary conditions, or evidence. Does not browse directly, declare novelty or completeness, merge the graph, or write Zotero.
---

# Network Gap Discovery

## Contract

Act as an auditable gap-hypothesis controller, not an automatic graph completer.
Read an immutable, validated `KnowledgeNetwork/v1`; propose missing-content
hypotheses; make each hypothesis falsifiable; route searches to
`$scholar-discovery`; send decisive papers to `$learn-from-papers`; and emit only
a `NetworkPatchProposal/v2`. The existing `$research-knowledge-network`
controller alone may validate and merge accepted records.

Every paper-reading request carries a closed `epistemic_task`: question,
hypothesis, target signature, scope, defeaters, falsifiers, acceptance criteria,
canonical relation vocabulary, and required inspection depth. This skill sets
that task but has no paper-reading authority.

Absence from an open-world graph means `unknown`. It becomes a deterministic
gap only relative to an explicit competency question, promised dimension,
benchmark profile, completeness statement, or schema constraint. Topological
isolates, low degree, analogy, embeddings, co-occurrence, and empty searches can
only generate `implicit_candidate` hypotheses.

Use `scripts/network_gap_discovery.py` for structural scans, contract
validation, transparent prioritization, scholar-request emission, and patch
proposal validation. Read [contracts.md](references/contracts.md) first.

## Autonomous bounded loop

1. Validate the network with `$research-knowledge-network`; bind its exact path,
   `network_id`, `snapshot_id`, and canonical export `content_sha256`. The
   cross-skill `network_ref.sha256` is this content digest, not the file hash or
   a second hash of the envelope containing `content_sha256`. Never reason over
   a stale export.
2. Run `scan` to inventory declared gaps, unmet gates, isolates, disconnected
   components, dangling relations, low-confidence edges, and provenance
   omissions. Treat scan signals as prompts, never facts.
3. Generate candidates through independent probe families:
   - competency questions, promised dimensions, benchmark grids, and local
     completeness contracts;
   - taxonomy contrast against landmark reviews or reference ontologies;
   - multi-perspective questioning across object, mechanism, method, evidence,
     context, boundary, implementation, and stakeholder views;
   - Swanson-style A-B-C bridging and citation-neighborhood expansion;
   - missing null, failure, replication, correction, retraction, incompatible
     version, counterexample, or discriminating experiment evidence;
   - population/regime/version/measurement applicability holes;
   - pairwise relations hiding necessary context, n-ary events, or conditions.
4. Represent every implicit candidate with grounds, warrant, backing,
   qualifier, defeaters, confirm and refute searches, acceptance criteria,
   decision impact, uncertainty, dependencies, and `novelty_claimed: false`.
   Validate and prioritize it. Do not auto-merge aliases or sibling concepts.
5. Emit `ScholarDiscoveryRequest/v1` requests. For each candidate perform
   internal alias/direct-coverage checks, positive search, direct-relation
   search, counterexample/null search, citation chaining, version/correction
   checks, and full-text locator review. Preserve all routes and exclusions.
6. Transition to `content_found`, `already_covered`, `supported_gap`, `refuted`,
   `unresolved`, or `blocked`. A search miss is `no_signal`, not nonexistence.
7. Draft `NetworkPatchProposal/v2` with candidate nodes, relations, and evidence
   plus source-rooted evidence locators and provenance. A DOI or URL is only an
   acquisition identity and can never become patch provenance. Keep
   `proposal_only: true`; never invoke network mutation or Zotero writes.
8. Re-scan the new validated snapshot after the controller merges an accepted
   patch. Continue only while a named high-information gap remains.

9. `consume-results` accepts only `ScholarDiscoveryResultSet/v1` payloads and
   requires request-set/network binding to the current discovery cycle.
10. Decisive `consume-reviewed-evidence` and `propose-patch` derive review
    records directly from a strictly reprojected `PaperReadingReportSet/v2`, its
    dossier, verified source bundle, source artifact, and reopenable verifier
    attestation. Caller-built `ReviewedEvidenceSet/v1` and
    `PaperReadingReportSet/v1` remain audit-only and cannot change graph state.

## Hypothesis and status rules

- `content_found` means plausible missing content was located, not accepted as
  true or novel.
- `supported_gap` means sources support bounded missing research or corpus
  coverage; it does not validate the proposed scientific relation.
- `already_covered` means alias resolution, a direct study, or an existing node
  defeated the hypothesis.
- `refuted` means a hard negative, scope mismatch, or contrary evidence defeats
  it; `unresolved` preserves inadequate or conflicting evidence.
- Only a controller-reviewed patch can add content.

Do not infer a negative edge from missing data. Do not upgrade a link-prediction
score, LLM suggestion, search rank, abstract, or snippet into evidence. Keep
claims scoped by population/system, regime, intervention, comparator, outcome,
version, and time when those conditions matter.

## Independent-verifier boundary

Use the frozen three-stage producer contract: `prepare-attestations` emits only a
`VerificationAttestationRequest/v1`; an external verifier in a different context
emits `VerificationAttestation/v1`; `finalize-attestations` reopens both artifacts
and recomputes report identities. The bridge repeats those checks. It requires
canonical bytes and hashes, `origin: external_verifier`, distinct producer and
verifier context IDs, `verdict: passed`, and exact request/report bindings.
Explicit producer/self/generated verifier names remain an additional negative
guard, never the proof of independence.

For multi-report sets, call external `attest` once per prepared `report_id` and
chain each output into the next call. Requests and attestations bind the full
pending-normalized report-set context, network reference, completion matrix, and
the sorted unique subject identities of every expected report. Artifact paths
must be canonical `verification-requests/<sha256>.json` or
`verification-attestations/<sha256>.json` regular files; aliases and special
files fail in the strict producer validator before bridge derivation.

## Priority and stop rules

Prioritize decision impact, downstream blocking, uncertainty, expected
information gain, and testability. Penalize likely alias/version duplicates and
expensive searches with weak decision effect. The bundled ranker exposes every
component; it is triage, not epistemic confidence.

For an open Web, stop only when promised dimensions have been probed,
high-impact candidates are terminal, contrary and version routes were executed,
and two consecutive independent rounds add no decision-relevant node, relation,
conflict, or evidence. Report `pragmatic_saturation`, never global completeness.
Budget or access exhaustion yields `partial` or `blocked` with the next action.

Read [research-basis.md](references/research-basis.md) when changing candidate
generation, open-world semantics, evidence gates, or evaluation.

## Runbook notes

Use `consume-results` to ingest each `ScholarDiscoveryResultSet/v1`, then use
`consume-reviewed-evidence` with the finalized report set, dossier, source
bundle, source artifact, and verification root. Inspecting only
`discovery_only` candidates does not upgrade
an hypothesis from `results`; it stays `results` for later discoveries or manual
capture.

For v2 reports, derive reviewed outcomes from the report relation only:
`supports -> supports`, `refutes -> contradicts`, and
`qualifies|not_tested -> unknown`. Reject caller relabeling. `already_covered`
requires a future explicit coverage disposition and is not inferred from a
paper relation. Bind the report hypothesis, request digest, source bundle,
artifact hash, report digest, evidence id, source span id/hash, and actual
evidence locator before any status transition. Only a decisive, verifier-passed,
claim-support-eligible `supports` projection may enter a patch.

Never trust verification labels alone. Reopen `verification.artifact_ref` under
the explicit verification root, reject symlinks/path escape, hash the canonical
attestation bytes, and bind its contents to the report subject, claim, scope,
evidence/span, dossier, bundle, source artifact, mode, and verifier. Reproject
the supplied dossier against the explicit source-bundle and source-artifact
paths and require exact semantic equality before deriving records. Final report
IDs may differ from the unsigned projection only through the frozen attestation
descriptor and the excluded `projection_status`/`claim_support_eligible` fields.

Patch eligibility additionally requires exact request/report scope equality,
`full_text`, `evidence|reconstruction`, `decisive`, verifier-passed evidence,
and `independent_source_check|expert_review`. Abstract/partial access, `map`,
`same_context_diagnostic`, `qualifies`, and `not_tested` remain unresolved and
cannot enter `NetworkPatchProposal/v2`.

Every patch basis `source_id` must already exist in the bound live network's
`sources` collection. Missing sources produce terminal `blocked` with
`next_action: onboarding_required`; onboard the source, export a new snapshot,
and rerun discovery. Downstream evidence materialization uses exactly
`independence_group = source_id`.

Patch actions use one closed map rather than deriving types from string
prefixes: `node -> propose_node`, `relation -> propose_relation`, and
`evidence|boundary|counterexample|version|benchmark|benchmark_profile|assumption|
mechanism|metric|measurement|estimator|failure_mode|context -> propose_evidence`.
Only a closed relation target, or an evidence target whose signature equals the
sole reviewed `evidence_id`, is `proposed`. Node targets and all semantic audit
targets are emitted as locally valid `blocked` actions. A blocked action records
the gap proposal but is deliberately ineligible for RKN acceptance or apply.

For `propose_relation`, the action includes a closed, content-addressed
`NetworkPatchTargetClaim/v1`. Its claim text comes from the finalized report,
impact from hypothesis `decision_impact`, scope/profile from the exact
request/report scope, epistemic status from its reviewed basis, and report claim
ID/digest from that same basis. Never substitute the target signature as a claim,
default impact to `medium`, or omit typed scope categories.

The target claim hashes a typed scope with exactly `scope_statement`,
`assumptions`, `conditions`, `units`, `exclusions`, `defeaters`,
`coverage_dimensions`, and `benchmark_profiles`. Never flatten typed scope
categories into `coverage_dimensions`, copy exclusions or defeaters into
`benchmark_profiles`, or invent either field. The current review-request schema
has no explicit same-named coverage/benchmark inputs, so those two lists remain
empty while the typed categories preserve the actual semantics. Consumers that
cannot preserve this exact typed scope must reject the proposal.

Use `report_set.review_source` (`source_id`, `source_digest`, and
`acquisition_locator`) to select the discovery-side request source. Treat
`report_set.source_ref` solely as the verified source-bundle artifact filename;
it is not the request source slot and the two values need not match.

Saturation is reached after two consecutive no-progress discovery/review rounds,
but only when there is no `awaiting` manual result obligation.

`consume-results` and `consume-reviewed-evidence` must be bound to the exact same
`request_set_id`, `network_id`, and `network_snapshot_sha256` for deterministic
cycle state.
