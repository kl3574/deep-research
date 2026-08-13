from __future__ import annotations

import contextlib
import copy
import io
import importlib.util
import json
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest import mock

SCRIPT_DIR = Path(__file__).parent
sys.path.insert(0, str(SCRIPT_DIR))
import evidence_appraisal_binding as BINDING  # noqa: E402
import knowledge_network as KN  # noqa: E402
import network_patch as PATCH  # noqa: E402


def attach(value: dict, id_field: str, digest_field: str, prefix: str) -> dict:
    digest = BINDING.digest_json(BINDING.without(value, id_field, digest_field))
    value[digest_field] = digest
    value[id_field] = prefix + digest[:16]
    return value


def attach_patch(value: dict, id_field: str, digest_field: str, prefix: str) -> dict:
    digest = PATCH.digest_json(PATCH.without(value, id_field, digest_field))
    value[digest_field] = digest
    value[id_field] = prefix + digest[:16]
    return value


def invoke(module, argv: list[str]):
    stdout = io.StringIO()
    stderr = io.StringIO()
    with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
        code = module.main(argv)
    return code, stdout.getvalue(), stderr.getvalue()


class EvidenceAppraisalBindingTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.owner_fixture_counter = 0
        self.network_id = "appraisal-network"
        snapshot = self.root / "corpus.json"
        snapshot.write_text('{"papers":[]}', encoding="utf-8")
        self.assertEqual(
            self.kn(
                [
                    "init",
                    "--question",
                    "Can reviewed evidence enter the network?",
                    "--scope",
                    "reviewed-only",
                    "--snapshot-path",
                    str(snapshot),
                    "--snapshot-digest",
                    KN._sha256_file(snapshot),
                ]
            )[0],
            0,
        )
        self.assertEqual(
            self.kn(
                [
                    "add-source",
                    "--source-id",
                    "source-02",
                    "--canonical-identity",
                    "doi:10.1000/anonymous-two",
                    "--canonical-version",
                    "v1",
                    "--read-version",
                    "full-v1",
                    "--read-depth",
                    "full",
                    "--version-hash",
                    "sha256:" + "b" * 64,
                    "--role",
                    "source",
                ]
            )[0],
            0,
        )
        self.assertEqual(
            self.kn(
                [
                    "add-source",
                    "--source-id",
                    "source-01",
                    "--canonical-identity",
                    "doi:10.1000/anonymous",
                    "--canonical-version",
                    "v1",
                    "--read-version",
                    "full-v1",
                    "--read-depth",
                    "full",
                    "--version-hash",
                    "sha256:" + "a" * 64,
                    "--role",
                    "source",
                ]
            )[0],
            0,
        )
        legacy_append = lambda paths, records, ledger, record_id, payload, **_: (  # noqa: E731
            KN._append_candidate(paths, records, ledger, record_id, payload)
        )
        with mock.patch.object(
            KN, "_append_scientific_candidate", side_effect=legacy_append
        ):
            result = self.kn(
                [
                    "add-claim",
                    "--claim-id",
                    "claim-01",
                    "--claim-text",
                    "The bounded effect is positive.",
                    "--impact",
                    "high",
                ]
            )
        self.assertEqual(result[0], 0, result[2])

    def tearDown(self) -> None:
        self.temp.cleanup()

    def kn(self, arguments: list[str]):
        return invoke(
            KN,
            ["--root", str(self.root), "--network-id", self.network_id, *arguments],
        )

    def state(self):
        paths = KN._safe_paths(str(self.root), self.network_id)
        state, records = KN._load_state(paths)
        return paths, state, records

    def network_ref(self):
        paths, state, records = self.state()
        return PATCH.current_network_ref(paths, state, records)

    def basis(
        self,
        evidence_id: str = "evidence-01",
        *,
        source_id: str = "source-01",
        source_index: int = 1,
    ) -> dict:
        suffix = f"{source_index:02d}"
        digest_char = "a" if source_index == 1 else "b"
        return attach(
            {
                "basis_id": "",
                "basis_digest": "",
                "review_request_id": f"review-request-{suffix}",
                "review_request_digest": "1" * 64,
                "report_set_id": f"report-set-{suffix}",
                "report_set_digest": str(source_index + 1) * 64,
                "dossier_id": f"dossier-{suffix}",
                "dossier_digest": "3" * 64,
                "reading_report_id": f"reading-report-{suffix}",
                "reading_report_digest": "4" * 64,
                "source_bundle_id": f"source-bundle-{suffix}",
                "source_bundle_digest": "5" * 64,
                "source_artifact_sha256": digest_char * 64,
                "source_id": source_id,
                "source_digest": "6" * 64,
                "claim_id": "claim-01",
                "claim_digest": "7" * 64,
                "evidence_id": evidence_id,
                "evidence_digest": "8" * 64,
                "span_id": f"span-{suffix}",
                "span_hash": "9" * 64,
                "source_ref": f"anonymous-paper-{suffix}.txt",
                "acquisition_locator": f"https://doi.org/10.1000/anonymous-{suffix}",
                "evidence_locator": "pages/page-0001.txt#char=10-29",
                "relation": "supports",
                "access_level": "full_text",
                "inspection_depth": "evidence",
                "claim_support_eligible": True,
                "projection_status": "decisive",
                "verification": {
                    "mode": "independent_source_check",
                    "verifier_id": "reviewer-02",
                    "artifact_sha256": "b" * 64,
                },
            },
            "basis_id",
            "basis_digest",
            "network-patch-basis-",
        )

    def proposal(self, evidence_ids: tuple[str, ...] = ("evidence-01",)) -> dict:
        actions = []
        for index, evidence_id in enumerate(evidence_ids):
            basis = self.basis(evidence_id)
            action = attach_patch(
                {
                    "action_id": "",
                    "action_digest": "",
                    "action_type": "propose_evidence",
                    "action_status": "proposed",
                    "hypothesis_id": f"gap-{index + 1}",
                    "target_signature": {
                        "target_kind": "evidence",
                        "signature": evidence_id,
                    },
                    "hypothesis": "Reviewed bounded evidence.",
                    "reviewed_evidence": [basis],
                },
                "action_id",
                "action_digest",
                "network-patch-action-",
            )
            actions.append(action)
        return attach_patch(
            {
                "schema": "NetworkPatchProposal/v2",
                "schema_version": "2.0",
                "proposal_id": "",
                "proposal_digest": "",
                "network_ref": self.network_ref(),
                "request_ref": {
                    "request_set_id": "request-set-01",
                    "request_set_digest": "c" * 64,
                    "review_request_set_id": "review-set-01",
                    "review_request_set_digest": "d" * 64,
                },
                "generated_at": "2026-08-10T00:00:00Z",
                "proposal_only": True,
                "novelty_claimed": False,
                "review_gate": "pending_research_knowledge_network_acceptance",
                "actions": actions,
            },
            "proposal_id",
            "proposal_digest",
            "network-patch-proposal-",
        )

    def proposal_v2_high_impact(self) -> dict:
        basis = self.basis("evidence-01")
        target_signature = {
            "target_kind": "relation",
            "signature": "single-source-high-impact-target",
        }
        scope = {
            "scope_statement": "A bounded high-impact single-source claim.",
            "assumptions": ["The one source is internally valid."],
            "conditions": ["Only one source lineage is available."],
            "units": ["standardized effect"],
            "exclusions": ["Independent external replication."],
            "defeaters": ["A second independent source changes the result."],
            "coverage_dimensions": [],
            "benchmark_profiles": [],
        }
        hypothesis_id = "KGH-v2-high-impact-single-source"
        target = attach_patch(
            {
                "schema": "NetworkPatchTargetClaim/v1",
                "schema_version": "1.0",
                "claim_id": "",
                "claim_text": "A high-impact conclusion from one source.",
                "entity_id": None,
                "impact": "high",
                "coverage_dimensions": [],
                "benchmark_profiles": [],
                "supersedes": None,
                "epistemic_status": {
                    "projection_status": basis["projection_status"],
                    "claim_support_eligible": basis["claim_support_eligible"],
                    "inspection_depth": basis["inspection_depth"],
                    "relation": basis["relation"],
                },
                "gap_hypothesis_id": hypothesis_id,
                "target_signature": target_signature,
                "report_claim_id": basis["claim_id"],
                "report_claim_digest": basis["claim_digest"],
                "scope": scope,
                "scope_digest": PATCH.digest_json(scope),
                "target_claim_digest": "",
            },
            "claim_id",
            "target_claim_digest",
            "claim-target-",
        )
        action = attach_patch(
            {
                "action_id": "",
                "action_digest": "",
                "action_type": "propose_relation",
                "action_status": "proposed",
                "hypothesis_id": hypothesis_id,
                "target_signature": target_signature,
                "hypothesis": target["claim_text"],
                "reviewed_evidence": [basis],
                "target_claim": target,
            },
            "action_id",
            "action_digest",
            "network-patch-action-",
        )
        return attach_patch(
            {
                "schema": "NetworkPatchProposal/v2",
                "schema_version": "2.0",
                "proposal_id": "",
                "proposal_digest": "",
                "network_ref": self.network_ref(),
                "request_ref": {
                    "request_set_id": "request-set-v2-high-impact",
                    "request_set_digest": "c" * 64,
                    "review_request_set_id": "review-set-v2-high-impact",
                    "review_request_set_digest": "d" * 64,
                },
                "generated_at": "2026-08-11T00:00:00Z",
                "proposal_only": True,
                "novelty_claimed": False,
                "review_gate": "pending_research_knowledge_network_acceptance",
                "actions": [action],
            },
            "proposal_id",
            "proposal_digest",
            "network-patch-proposal-",
        )

    def origin_gap_ref(self, gap_id: str) -> dict:
        _, _, records = self.state()
        row = max(
            (item for item in records["gaps"] if item.get("gap_id") == gap_id),
            key=lambda item: item["sequence"],
        )
        return {
            "gap_id": gap_id,
            "record_id": row["record_id"],
            "sequence": row["sequence"],
            "status": row["status"],
            "sha256": BINDING.digest_json(row),
        }

    def proposal_v3(self, origin_gap_refs: list[dict]) -> dict:
        bases = [
            self.basis("evidence-01"),
            self.basis("evidence-02", source_id="source-02", source_index=2),
        ]
        reading_groups = [
            {
                "reading_group_id": "reading-group-01",
                "reading_group_digest": "a" * 64,
                "source_id": "source-01",
                "report_set_id": bases[0]["report_set_id"],
                "report_set_digest": bases[0]["report_set_digest"],
            },
            {
                "reading_group_id": "reading-group-02",
                "reading_group_digest": "b" * 64,
                "source_id": "source-02",
                "report_set_id": bases[1]["report_set_id"],
                "report_set_digest": bases[1]["report_set_digest"],
            },
        ]
        subject_ref = {
            "subject_id": "reviewed-gap-subject-01",
            "subject_digest": "e" * 64,
        }
        target_signature = {
            "target_kind": "relation",
            "signature": "multi-source-bounded-effect",
        }
        scope = {
            "scope_statement": "Bounded two-source effect under declared conditions.",
            "assumptions": ["Both source models are correctly specified."],
            "conditions": ["The estimand is shared across sources."],
            "units": ["standardized effect"],
            "exclusions": ["Unmeasured target changes."],
            "defeaters": ["Source versions no longer match."],
            "coverage_dimensions": ["multi-source support"],
            "benchmark_profiles": ["bounded-effect benchmark"],
        }
        target = attach_patch(
            {
                "schema": "NetworkPatchTargetClaim/v2",
                "schema_version": "2.0",
                "claim_id": "",
                "claim_text": "The bounded effect is supported by two sources.",
                "entity_id": None,
                "impact": "high",
                "coverage_dimensions": copy.deepcopy(scope["coverage_dimensions"]),
                "benchmark_profiles": copy.deepcopy(scope["benchmark_profiles"]),
                "supersedes": None,
                "target_signature": target_signature,
                "subject_ref": subject_ref,
                "origin_gap_refs": copy.deepcopy(origin_gap_refs),
                "report_claim_refs": [
                    {
                        "basis_id": basis["basis_id"],
                        "basis_digest": basis["basis_digest"],
                        "reading_group_id": reading_group["reading_group_id"],
                        "claim_id": basis["claim_id"],
                        "claim_digest": basis["claim_digest"],
                        "reading_report_id": basis["reading_report_id"],
                        "reading_report_digest": basis["reading_report_digest"],
                    }
                    for basis, reading_group in zip(bases, reading_groups)
                ],
                "scope": scope,
                "scope_digest": PATCH.digest_json(scope),
                "target_claim_digest": "",
            },
            "claim_id",
            "target_claim_digest",
            "claim-target-",
        )
        action = attach_patch(
            {
                "action_id": "",
                "action_digest": "",
                "action_type": "propose_relation",
                "action_status": "proposed",
                "hypothesis_id": "KGH-review-routing-only",
                "target_signature": target_signature,
                "hypothesis": "Two-source evidence supports the bounded effect.",
                "subject_ref": subject_ref,
                "origin_gap_refs": copy.deepcopy(origin_gap_refs),
                "reading_group_refs": reading_groups,
                "reviewed_evidence": bases,
                "target_claim": target,
            },
            "action_id",
            "action_digest",
            "network-patch-action-",
        )
        return attach_patch(
            {
                "schema": "NetworkPatchProposal/v3",
                "schema_version": "3.0",
                "proposal_id": "",
                "proposal_digest": "",
                "network_ref": self.network_ref(),
                "request_ref": {
                    "request_set_id": "request-set-v3-01",
                    "request_set_digest": "c" * 64,
                    "review_request_set_id": "review-set-v3-01",
                    "review_request_set_digest": "d" * 64,
                },
                "consumption_ref": {
                    "schema": "ReviewedEvidenceCollectionConsumption/v1",
                    "route": "direct_reviewed_selection",
                    "authority_id": (
                        "reviewed-collection-consumption-authority-" + "9" * 16
                    ),
                    "authority_digest": "9" * 64,
                    "authority_file_sha256": "8" * 64,
                    "consumed_hypotheses_sha256": "7" * 64,
                },
                "reading_collection_ref": {
                    "collection_id": "paper-reading-evidence-collection-01",
                    "collection_digest": "f" * 64,
                },
                "generated_at": "2026-08-11T00:00:00Z",
                "proposal_only": True,
                "novelty_claimed": False,
                "review_gate": "pending_research_knowledge_network_acceptance",
                "actions": [action],
            },
            "proposal_id",
            "proposal_digest",
            "network-patch-proposal-",
        )

    def proposal_v4_extension(self, origin_gap_refs: list[dict]) -> dict:
        proposal = self.proposal_v3(origin_gap_refs)
        _, _, records = self.state()
        claim = next(
            row for row in records["claims"] if row.get("claim_id") == "claim-01"
        )
        scope = {
            field: copy.deepcopy(claim[field])
            for field in (
                "scope_statement",
                "assumptions",
                "conditions",
                "units",
                "exclusions",
                "defeaters",
                "coverage_dimensions",
                "benchmark_profiles",
            )
        }
        claim_semantics = {
            field: copy.deepcopy(claim[field])
            for field in (
                "claim_text",
                "entity_id",
                "impact",
                "is_factual",
                "scope_statement",
                "assumptions",
                "conditions",
                "units",
                "exclusions",
                "defeaters",
                "coverage_dimensions",
                "benchmark_profiles",
                "supersedes",
            )
        }
        existing_claim_ref = {
            "schema": "NetworkPatchExistingClaimRef/v1",
            "schema_version": "1.0",
            "claim_id": claim["claim_id"],
            "claim_record_ref": {
                "record_id": claim["record_id"],
                "sequence": claim["sequence"],
                "sha256": PATCH.digest_json(claim),
            },
            "claim_semantics": claim_semantics,
            "scope_digest": PATCH.digest_json(scope),
            "claim_semantic_digest": PATCH.digest_json(claim_semantics),
        }
        action = PATCH.without(
            copy.deepcopy(proposal["actions"][0]),
            "action_id",
            "action_digest",
            "target_claim",
        )
        action["action_type"] = "propose_evidence_extension"
        action["hypothesis"] = claim["claim_text"]
        action["existing_claim_ref"] = existing_claim_ref
        proposal["actions"] = [
            attach_patch(
                action,
                "action_id",
                "action_digest",
                "network-patch-action-",
            )
        ]
        proposal["schema"] = "NetworkPatchProposal/v4"
        proposal["schema_version"] = "4.0"
        return attach_patch(
            PATCH.without(proposal, "proposal_id", "proposal_digest"),
            "proposal_id",
            "proposal_digest",
            "network-patch-proposal-",
        )

    def relation_appraisal(
        self,
        evidence_id: str = "evidence-01",
        *,
        overall: str = "decisive_within_scope",
        relation: str = "supports",
        locator: str = "pages/page-0001.txt#char=10-29",
        lineage: str = "study-lineage-01",
        source_id: str = "source-01",
    ) -> dict:
        locator_ref = {"source_ref": source_id, "locator": locator}
        return {
            "schema": "EvidenceAppraisal/v1",
            "claim_ref": "claim-01",
            "evidence_ref": evidence_id,
            "supersedes_prior_appraisal_ref": None,
            "relation_verdict": relation,
            "domain_verdicts": {
                "provenance": "satisfied",
                "scope_match": "satisfied",
                "design": "satisfied",
                "measurement": "satisfied",
                "analysis": "satisfied",
                "independence": "satisfied",
                "reproducibility": "satisfied",
                "reporting_completeness": "satisfied",
            },
            "overall": overall,
            "scope": {
                "population": "bounded fixture",
                "setting": "simulation",
                "boundary": "declared estimand",
            },
            "source_lineage": [source_id, lineage],
            "locator_refs": [locator_ref],
            "attestation_refs": [
                {
                    "attestation_id": "attestation-" + evidence_id,
                    "state": "passed",
                    "decisive": True,
                    "locator_ref": copy.deepcopy(locator_ref),
                    "binding_digest": "0" * 64,
                    "supersedes_ref": None,
                }
            ],
            "reproducibility_state": "reproduced",
        }

    def test_qualified_only_preserves_only_qualified_projection(self) -> None:
        domains = {
            "provenance": "satisfied",
            "scope_match": "satisfied",
            "design": "concern",
            "measurement": "satisfied",
            "analysis": "satisfied",
            "independence": "satisfied",
            "reproducibility": "satisfied",
            "reporting_completeness": "satisfied",
        }

        def allowed(verdict: str) -> str | None:
            return BINDING._allowed_relation(
                {
                    "relation_verdict": verdict,
                    "overall": "qualified_only",
                    "domain_verdicts": domains,
                    "attestation_refs": [{"state": "passed", "decisive": True}],
                }
            )

        self.assertEqual(allowed("supports"), "qualifies")
        self.assertEqual(allowed("qualifies"), "qualifies")
        self.assertEqual(allowed("contradicts"), "qualifies")
        self.assertIsNone(allowed("not_tested"))
        self.assertIsNone(allowed("unresolved"))

    def appraisal_package(
        self, relations: list[dict], *, unresolved_need: bool = False
    ) -> dict[str, dict]:
        owner = BINDING.load_appraisal_module()
        owner_fixture_path = (
            Path(__file__).resolve().parents[2]
            / "evidence-appraisal"
            / "scripts"
            / "fixtures"
            / "owner_fixture.py"
        )
        spec = importlib.util.spec_from_file_location(
            "rkn_evidence_appraisal_owner_fixture", owner_fixture_path
        )
        if spec is None or spec.loader is None:
            raise RuntimeError("cannot load evidence-appraisal owner fixture")
        owner_fixture = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(owner_fixture)
        self.owner_fixture_counter += 1
        claim_refs = {relation["claim_ref"] for relation in relations}
        if len(claim_refs) != 1:
            raise RuntimeError("fixture requires one owner claim per appraisal package")
        locators = {relation["locator_refs"][0]["locator"] for relation in relations}
        owner_locator = (
            next(iter(locators))
            if len(locators) == 1
            else "pages/page-0001.txt#char=10-29"
        )
        bindings, owner_bundle = owner_fixture.make_anonymous_owner_bundle(
            self.root / f"owner-fixture-{self.owner_fixture_counter}",
            "rkn",
            claim_specs=[
                {
                    "claim_id": next(iter(claim_refs)),
                    "evidence_ids": [
                        relation["evidence_ref"] for relation in relations
                    ],
                    "exact_locator": owner_locator,
                }
            ],
        )
        passed_owner_attestation = next(
            binding
            for binding in bindings
            if binding["role"] == "attestation" and binding["status"] == "passed"
        )
        owner_lineage_id = passed_owner_attestation["lineage_id"]
        owner_attestation_binding_digest = owner._digest(passed_owner_attestation)
        request = {
            "schema": "EvidenceAppraisalRequest/v1",
            "appraisal_set_id": "set-anonymous",
            "cycle": 0,
            "prior_cycle_ref": None,
            "relation_keys": [
                {
                    "claim_ref": relation["claim_ref"],
                    "evidence_ref": relation["evidence_ref"],
                }
                for relation in relations
            ],
        }
        prepared = owner.prepare_appraisal(request, owner_artifact_bindings=bindings)
        reviewer_context = {
            "reviewer_ref": "reviewer-01",
            "review_method": "independent-context",
            "reviewed_at": "time-review",
        }
        for relation in relations:
            relation["source_lineage"].append(owner_lineage_id)
            for attestation in relation["attestation_refs"]:
                attestation["owner_attestation_binding_digest"] = (
                    owner_attestation_binding_digest
                )
                attestation["binding_digest"] = (
                    owner.compute_attestation_binding_digest(
                        prepared,
                        relation["claim_ref"],
                        relation["evidence_ref"],
                        attestation["locator_ref"],
                        reviewer_context,
                    )
                )
        targeted_evidence_needs = []
        if unresolved_need:
            materialized = owner._materialize_relation(
                relations[0], prepared, reviewer_context, "fixture relation"
            )
            targeted_evidence_needs.append(
                {
                    "schema": "TargetedEvidenceNeed/v1",
                    "route": "full_text_review",
                    "domain_anchors": [],
                    "relation_ref": {
                        "claim_ref": materialized["claim_ref"],
                        "evidence_ref": materialized["evidence_ref"],
                        "appraisal_id": materialized["appraisal_id"],
                        "semantic_digest": materialized["semantic_digest"],
                    },
                    "adversarial_observation_pair": {
                        "common": {
                            "target_metric": "bounded effect",
                            "comparator": "review threshold",
                            "boundary": "declared estimand",
                        },
                        "confirm": {
                            "operator": "gte",
                            "value_or_state": "0.8",
                            "claim_implication": "supports",
                        },
                        "refute": {
                            "operator": "lt",
                            "value_or_state": "0.8",
                            "claim_implication": "challenges",
                        },
                    },
                }
            )
        review = {
            "schema": "EvidenceAppraisalIndependentReview/v1",
            "prepared_request_digest": prepared["request_digest"],
            "prepared_request_file_sha256": prepared["prepared_request_file_sha256"],
            "independent_review_file_sha256": "",
            "independent_review_digest": "",
            "reviewer_context": reviewer_context,
            "owner_artifact_binding_digests": copy.deepcopy(
                prepared["owner_artifact_binding_digests"]
            ),
            "relation_appraisals": relations,
            "challenges": [],
            "targeted_evidence_needs": targeted_evidence_needs,
        }
        review["independent_review_file_sha256"] = owner._digest(
            owner._review_file_projection(review)
        )
        review["independent_review_digest"] = owner._digest(
            owner._review_semantic(review)
        )
        appraisal_set = owner.finalize_appraisal(prepared, review, owner_bundle)
        approval = owner.create_reviewed_authority(
            prepared,
            review,
            appraisal_set,
            {
                "reviewer_ref": "authority-01",
                "review_method": "independent-approval",
                "reviewed_at": "time-authority",
            },
            owner_bundle,
        )
        package = owner.build_appraisal_package(
            appraisal_set,
            prepared,
            review,
            approval,
            owner_bundle,
            expected_authority_sha256=approval["authority_digest"],
        )
        return {
            "package": package,
            "approval": approval,
            "prepared": prepared,
            "review": review,
            "set": appraisal_set,
            "owner_bundle": owner_bundle,
        }

    def binding_and_projection(
        self,
        proposal: dict,
        artifacts: dict[str, dict],
        gap_transition: dict | None = None,
        relation_scope_alignment: str = "match",
        project_relations: bool | None = None,
    ):
        paths, _, records = self.state()
        binding = BINDING.create_binding(
            artifacts["package"],
            artifacts["approval"],
            artifacts["prepared"],
            artifacts["review"],
            artifacts["owner_bundle"],
            [],
            artifacts["approval"]["authority_digest"],
            proposal,
            proposal["network_ref"],
            KN._scientific_binding_guard(paths, records),
            KN._claim_scopes_from_records(records),
            bound_at="2026-08-10T00:01:00Z",
        )
        decisions = []
        for action in proposal["actions"]:
            action_transition = (
                copy.deepcopy(gap_transition)
                if gap_transition is not None
                and gap_transition["gap_id"] == action["hypothesis_id"]
                else None
            )
            relation_projection = (
                project_relations
                if project_relations is not None
                else not (
                    action_transition is not None
                    and action_transition["to_status"] in {"blocked", "open"}
                )
            )
            decisions.append(
                {
                    "action_id": action["action_id"],
                    "action_digest": action["action_digest"],
                    "decision": "authorize",
                    "rationale": "Scope and operation mapping reviewed.",
                    "relation_reviews": [
                        {
                            "binding_row_id": row["binding_row_id"],
                            "binding_row_digest": row["binding_row_digest"],
                            "scope_alignment": relation_scope_alignment,
                            "projected_relation": (
                                row["allowed_relation"] if relation_projection else None
                            ),
                        }
                        for row in binding["relation_bindings"]
                        if row["action_id"] == action["action_id"]
                    ],
                    "gap_transition": action_transition,
                }
            )
        review = {
            "schema": "EvidenceAppraisalProjectionReview/v1",
            "binding_ref": {
                "binding_id": binding["binding_id"],
                "binding_digest": binding["binding_digest"],
            },
            "proposal_ref": binding["proposal_ref"],
            "reviewer": {
                "reviewer_id": "scientific-curator-01",
                "reviewer_role": "independent-appraisal-reviewer",
            },
            "decisions": decisions,
        }
        projection = BINDING.create_reviewed_projection(
            binding,
            proposal,
            review,
            reviewed_at="2026-08-10T00:02:00Z",
        )
        return binding, projection

    def resolved_v3_transitions(
        self, proposal: dict, artifacts: dict[str, dict]
    ) -> list[dict]:
        appraisal_refs = sorted(
            [
                {
                    "appraisal_id": item["appraisal_id"],
                    "semantic_digest": item["semantic_digest"],
                }
                for item in artifacts["set"]["relation_appraisals"]
            ],
            key=lambda item: (item["appraisal_id"], item["semantic_digest"]),
        )
        evidence_refs = sorted(
            basis["evidence_id"]
            for basis in proposal["actions"][0]["reviewed_evidence"]
        )
        return [
            {
                "gap_id": origin["gap_id"],
                "from_record_id": origin["record_id"],
                "from_status": origin["status"],
                "to_status": "resolved",
                "reason": "The complete reviewed multi-source basis resolves this gap.",
                "evidence_refs": copy.deepcopy(evidence_refs),
                "resolution_source": "",
                "basis_appraisal_refs": copy.deepcopy(appraisal_refs),
                "basis_need_refs": [],
            }
            for origin in proposal["actions"][0]["origin_gap_refs"]
        ]

    def binding_and_projection_v3(
        self,
        proposal: dict,
        artifacts: dict[str, dict],
        transitions: list[dict],
        *,
        scope_alignment: str = "match",
    ):
        paths, _, records = self.state()
        binding = BINDING.create_binding(
            artifacts["package"],
            artifacts["approval"],
            artifacts["prepared"],
            artifacts["review"],
            artifacts["owner_bundle"],
            [],
            artifacts["approval"]["authority_digest"],
            proposal,
            proposal["network_ref"],
            KN._scientific_binding_guard(paths, records),
            KN._claim_scopes_from_records(records),
            bound_at="2026-08-11T00:01:00Z",
        )
        action = proposal["actions"][0]
        review = {
            "schema": "EvidenceAppraisalProjectionReview/v2",
            "binding_ref": {
                "binding_id": binding["binding_id"],
                "binding_digest": binding["binding_digest"],
            },
            "proposal_ref": binding["proposal_ref"],
            "reviewer": {
                "reviewer_id": "scientific-curator-v3-01",
                "reviewer_role": "independent-appraisal-reviewer",
            },
            "decisions": [
                {
                    "action_id": action["action_id"],
                    "action_digest": action["action_digest"],
                    "decision": "authorize",
                    "rationale": "Every source basis and origin gap was reviewed.",
                    "relation_reviews": [
                        {
                            "binding_row_id": row["binding_row_id"],
                            "binding_row_digest": row["binding_row_digest"],
                            "scope_alignment": scope_alignment,
                            "projected_relation": row["allowed_relation"],
                        }
                        for row in binding["relation_bindings"]
                    ],
                    "gap_transitions": copy.deepcopy(transitions),
                }
            ],
        }
        projection = BINDING.create_reviewed_projection(
            binding,
            proposal,
            review,
            reviewed_at="2026-08-11T00:02:00Z",
        )
        return binding, projection

    def write_gate(self, proposal, artifacts, binding, projection):
        values = {
            "proposal.json": proposal,
            "package.json": artifacts["package"],
            "approval.json": artifacts["approval"],
            "prepared.json": artifacts["prepared"],
            "independent-review.json": artifacts["review"],
            "owner-bundle.json": artifacts["owner_bundle"],
            "candidate-set.json": artifacts["set"],
            "binding.json": binding,
            "projection.json": projection,
        }
        paths = {}
        for name, value in values.items():
            path = self.root / name
            path.write_text(json.dumps(value, sort_keys=True), encoding="utf-8")
            paths[name] = path
        return paths

    def gate_arguments(self, paths: dict[str, Path]) -> list[str]:
        return [
            "--appraisal-package",
            str(paths["package.json"]),
            "--appraisal-approval",
            str(paths["approval.json"]),
            "--appraisal-prepared",
            str(paths["prepared.json"]),
            "--appraisal-independent-review",
            str(paths["independent-review.json"]),
            "--appraisal-owner-bundle",
            str(paths["owner-bundle.json"]),
            "--expected-authority-sha256",
            json.loads(paths["approval.json"].read_text(encoding="utf-8"))[
                "authority_digest"
            ],
            "--appraisal-proposal",
            str(paths["proposal.json"]),
            "--appraisal-binding",
            str(paths["binding.json"]),
            "--appraisal-projection",
            str(paths["projection.json"]),
        ]

    def test_direct_scientific_write_requires_and_consumes_exact_gate(self) -> None:
        proposal = self.proposal()
        artifacts = self.appraisal_package([self.relation_appraisal()])
        network_paths, _, initial_records = self.state()
        with self.assertRaisesRegex(Exception, "external trust boundary"):
            BINDING.create_binding(
                artifacts["package"],
                artifacts["approval"],
                artifacts["prepared"],
                artifacts["review"],
                artifacts["owner_bundle"],
                [],
                "0" * 64,
                proposal,
                proposal["network_ref"],
                KN._scientific_binding_guard(network_paths, initial_records),
                KN._claim_scopes_from_records(initial_records),
                bound_at="2026-08-10T00:00:30Z",
            )
        binding, projection = self.binding_and_projection(proposal, artifacts)
        paths = self.write_gate(proposal, artifacts, binding, projection)
        network_paths, _, records = self.state()
        loaded_gate, cli_args = PATCH._load_optional_appraisal_gate(
            SimpleNamespace(
                proposal=str(paths["proposal.json"]),
                appraisal_package=str(paths["package.json"]),
                appraisal_approval=str(paths["approval.json"]),
                appraisal_prepared=str(paths["prepared.json"]),
                appraisal_independent_review=str(paths["independent-review.json"]),
                appraisal_owner_bundle=str(paths["owner-bundle.json"]),
                appraisal_lineage=[],
                expected_authority_sha256=artifacts["approval"]["authority_digest"],
                appraisal_binding=str(paths["binding.json"]),
                appraisal_projection=str(paths["projection.json"]),
            ),
            proposal,
            proposal["network_ref"],
            network_paths,
            records,
        )
        self.assertEqual(loaded_gate["refs"]["status"], "reviewed_appraisal")
        self.assertIn("--expected-authority-sha256", cli_args)
        arguments = [
            "add-evidence",
            "--evidence-id",
            "evidence-01",
            "--claim-id",
            "claim-01",
            "--source-id",
            "source-01",
            "--polarity",
            "supports",
            "--exact-locator",
            "pages/page-0001.txt#char=10-29",
            "--independence-group",
            binding["relation_bindings"][0]["independence_group"],
            "--summary",
            "Reviewed bounded evidence.",
            "--notes",
            "accepted from NetworkPatchProposal/v2",
        ]
        denied = self.kn(arguments)
        self.assertEqual(denied[0], 1)
        self.assertIn("scientific mutation requires", denied[2])
        gated = self.kn(
            [
                *arguments,
                *self.gate_arguments(paths),
            ]
        )
        self.assertEqual(gated[0], 0, gated[2])
        self.assertEqual(self.kn(["validate"])[0], 0)
        self.assertEqual(self.kn(arguments)[0], 0, "exact no-op remains compatible")
        _, _, records = self.state()
        events = [
            row
            for row in records["events"]
            if row["event_type"] == "appraised_mutation"
        ]
        self.assertEqual(len(events), 1)
        self.assertNotIn("Reviewed bounded evidence", json.dumps(events[0]))
        self.assertNotIn(str(self.root), json.dumps(events[0]))
        self.assertIn("appraisal_package_ref", events[0])
        candidate_only = self.gate_arguments(paths)
        candidate_only[1] = str(paths["candidate-set.json"])
        denied_candidate = self.kn(
            [
                *arguments,
                "--evidence-id",
                "evidence-candidate-only",
                *candidate_only,
            ]
        )
        self.assertEqual(denied_candidate[0], 1)
        self.assertIn("EvidenceAppraisalPackage/v1", denied_candidate[2])

    def test_non_ascii_appraised_mutation_event_validates(self) -> None:
        summary = "Reviewed bounded evidence from Pötscher."
        proposal = self.proposal()
        action = PATCH.without(
            copy.deepcopy(proposal["actions"][0]), "action_id", "action_digest"
        )
        action["hypothesis"] = summary
        proposal["actions"][0] = attach_patch(
            action,
            "action_id",
            "action_digest",
            "network-patch-action-",
        )
        proposal = attach_patch(
            PATCH.without(proposal, "proposal_id", "proposal_digest"),
            "proposal_id",
            "proposal_digest",
            "network-patch-proposal-",
        )
        artifacts = self.appraisal_package([self.relation_appraisal()])
        binding, projection = self.binding_and_projection(proposal, artifacts)
        gate_paths = self.write_gate(proposal, artifacts, binding, projection)
        payload = {
            "evidence_id": "evidence-01",
            "claim_id": "claim-01",
            "source_id": "source-01",
            "polarity": "supports",
            "exact_locator": "pages/page-0001.txt#char=10-29",
            "independence_group": binding["relation_bindings"][0][
                "independence_group"
            ],
            "summary": summary,
            "notes": "accepted from NetworkPatchProposal/v2",
            "supersedes": None,
        }

        written = self.kn(
            [
                "add-evidence",
                "--evidence-id",
                payload["evidence_id"],
                "--claim-id",
                payload["claim_id"],
                "--source-id",
                payload["source_id"],
                "--polarity",
                payload["polarity"],
                "--exact-locator",
                payload["exact_locator"],
                "--independence-group",
                payload["independence_group"],
                "--summary",
                payload["summary"],
                "--notes",
                payload["notes"],
                *self.gate_arguments(gate_paths),
            ]
        )
        self.assertEqual(written[0], 0, written[2])
        validated = self.kn(["validate"])
        self.assertEqual(validated[0], 0, validated[2] or validated[1])

        _, _, records = self.state()
        event = next(
            row
            for row in records["events"]
            if row.get("event_type") == "appraised_mutation"
        )
        self.assertEqual(
            event["mutation_subject_digest"],
            BINDING.mutation_subject_digest("add-evidence", payload),
        )

    def test_direct_gate_replays_owner_files_despite_injected_cache(self) -> None:
        proposal = self.proposal()
        artifacts = self.appraisal_package([self.relation_appraisal()])
        binding, projection = self.binding_and_projection(proposal, artifacts)
        gate_paths = self.write_gate(proposal, artifacts, binding, projection)
        paths, _, records = self.state()
        gate_args = SimpleNamespace(
            proposal=str(gate_paths["proposal.json"]),
            appraisal_package=str(gate_paths["package.json"]),
            appraisal_approval=str(gate_paths["approval.json"]),
            appraisal_prepared=str(gate_paths["prepared.json"]),
            appraisal_independent_review=str(gate_paths["independent-review.json"]),
            appraisal_owner_bundle=str(gate_paths["owner-bundle.json"]),
            appraisal_lineage=[],
            expected_authority_sha256=artifacts["approval"]["authority_digest"],
            appraisal_binding=str(gate_paths["binding.json"]),
            appraisal_projection=str(gate_paths["projection.json"]),
        )
        loaded_gate, _ = PATCH._load_optional_appraisal_gate(
            gate_args,
            proposal,
            proposal["network_ref"],
            paths,
            records,
        )
        gate_args._validated_appraisal_gate = loaded_gate
        source_path = Path(
            next(
                row["source_path"]
                for row in artifacts["owner_bundle"]["artifacts"]
                if row["source_path"] is not None
            )
        )
        source_path.write_bytes(source_path.read_bytes() + b"\nsource-byte-tamper\n")
        watched = [paths.ledger("evidence"), paths.ledger("events")]
        before = {path: path.read_bytes() for path in watched}
        payload = {
            "evidence_id": "evidence-01",
            "claim_id": "claim-01",
            "source_id": "source-01",
            "polarity": "supports",
            "exact_locator": "pages/page-0001.txt#char=10-80",
            "independence_group": binding["relation_bindings"][0]["independence_group"],
            "summary": "Reviewed bounded evidence.",
            "notes": "accepted from NetworkPatchProposal/v2",
            "supersedes": None,
        }
        with self.assertRaises(Exception):
            KN._append_scientific_candidate(
                paths,
                records,
                "evidence",
                KN._record_id("evidence", "evidence-01"),
                payload,
                args=gate_args,
                operation_type="add-evidence",
            )
        self.assertEqual({path: path.read_bytes() for path in watched}, before)

    def test_every_direct_scientific_entrypoint_fails_closed_without_gate(self) -> None:
        denied_claim = self.kn(
            [
                "add-claim",
                "--claim-id",
                "claim-denied",
                "--claim-text",
                "Unappraised claim.",
                "--impact",
                "high",
            ]
        )
        self.assertEqual(denied_claim[0], 1)
        self.assertIn("scientific mutation requires", denied_claim[2])

        legacy_append = lambda paths, records, ledger, record_id, payload, **_: (  # noqa: E731
            KN._append_candidate(paths, records, ledger, record_id, payload)
        )
        with mock.patch.object(
            KN, "_append_scientific_candidate", side_effect=legacy_append
        ):
            seeded = self.kn(
                [
                    "add-evidence",
                    "--evidence-id",
                    "evidence-seeded",
                    "--claim-id",
                    "claim-01",
                    "--source-id",
                    "source-01",
                    "--polarity",
                    "supports",
                    "--exact-locator",
                    "pages/page-0001.txt#char=10-80",
                    "--independence-group",
                    "seed-lineage",
                    "--summary",
                    "Historical fixture only.",
                ]
            )
        self.assertEqual(seeded[0], 0, seeded[2])
        denied_relation = self.kn(
            [
                "add-relation",
                "--relation-id",
                "relation-denied",
                "--relation-type",
                "supports",
                "--from-ref",
                "claim:claim-01",
                "--to-ref",
                "evidence:evidence-seeded",
            ]
        )
        self.assertEqual(denied_relation[0], 1)
        self.assertIn("scientific mutation requires", denied_relation[2])

        opened = self.kn(
            [
                "record-gap",
                "--gap-id",
                "gap-denied",
                "--gap-type",
                "explicit",
                "--claim-id",
                "claim-01",
                "--impact",
                "high",
                "--status",
                "open",
                "--description",
                "Historical open gap.",
            ]
        )
        self.assertEqual(opened[0], 0, opened[2])
        _, _, records = self.state()
        gap_record_id = next(
            row["record_id"]
            for row in records["gaps"]
            if row.get("gap_id") == "gap-denied"
        )
        paths, _, _ = self.state()
        guarded_paths = [paths.ledger("gaps"), paths.ledger("events")]
        before_blocked = {
            path: (path.stat().st_ino, path.read_bytes()) for path in guarded_paths
        }
        denied_blocked = self.kn(
            [
                "transition-gap",
                "--gap-id",
                "gap-denied",
                "--from-record-id",
                gap_record_id,
                "--status",
                "blocked",
                "--reason",
                "No provider is currently available.",
            ]
        )
        self.assertEqual(denied_blocked[0], 1)
        self.assertIn("scientific mutation requires", denied_blocked[2])
        for path, expected in before_blocked.items():
            self.assertEqual((path.stat().st_ino, path.read_bytes()), expected)

        denied_transition = self.kn(
            [
                "transition-gap",
                "--gap-id",
                "gap-denied",
                "--from-record-id",
                gap_record_id,
                "--status",
                "resolved",
                "--reason",
                "Unappraised evidence cannot resolve it.",
                "--evidence-ref",
                "evidence-seeded",
            ]
        )
        self.assertEqual(denied_transition[0], 1)
        self.assertIn("scientific mutation requires", denied_transition[2])

        with mock.patch.object(
            KN, "_append_scientific_candidate", side_effect=legacy_append
        ):
            seeded_resolution = self.kn(
                [
                    "transition-gap",
                    "--gap-id",
                    "gap-denied",
                    "--from-record-id",
                    gap_record_id,
                    "--status",
                    "resolved",
                    "--reason",
                    "Historical fixture resolution.",
                    "--evidence-ref",
                    "evidence-seeded",
                ]
            )
        self.assertEqual(seeded_resolution[0], 0, seeded_resolution[2])
        _, _, records = self.state()
        resolved_record_id = max(
            (row for row in records["gaps"] if row.get("gap_id") == "gap-denied"),
            key=lambda row: row["sequence"],
        )["record_id"]
        before_reopen = {
            path: (path.stat().st_ino, path.read_bytes()) for path in guarded_paths
        }
        denied_reopen = self.kn(
            [
                "transition-gap",
                "--gap-id",
                "gap-denied",
                "--from-record-id",
                resolved_record_id,
                "--status",
                "open",
                "--reason",
                "Unappraised reopen is forbidden.",
            ]
        )
        self.assertEqual(denied_reopen[0], 1)
        self.assertIn("scientific mutation requires", denied_reopen[2])
        for path, expected in before_reopen.items():
            self.assertEqual((path.stat().st_ino, path.read_bytes()), expected)

        missing_command = self.kn(["resolve-conflict"])
        self.assertEqual(missing_command[0], 2)
        self.assertIn("invalid choice", missing_command[2])

    def test_reviewed_unresolved_need_can_authorize_exact_blocked_transition(
        self,
    ) -> None:
        opened = self.kn(
            [
                "record-gap",
                "--gap-id",
                "gap-1",
                "--gap-type",
                "explicit",
                "--claim-id",
                "claim-01",
                "--impact",
                "high",
                "--status",
                "open",
                "--description",
                "Awaiting a targeted adversarial check.",
            ]
        )
        self.assertEqual(opened[0], 0, opened[2])
        _, _, records = self.state()
        from_record_id = next(
            row["record_id"] for row in records["gaps"] if row.get("gap_id") == "gap-1"
        )
        proposal = self.proposal()
        artifacts = self.appraisal_package(
            [self.relation_appraisal()], unresolved_need=True
        )
        need = artifacts["package"]["targeted_evidence_need_set"]["needs"][0]
        transition = {
            "gap_id": "gap-1",
            "from_record_id": from_record_id,
            "from_status": "open",
            "to_status": "blocked",
            "reason": "Targeted evidence route remains pending.",
            "evidence_refs": [],
            "resolution_source": "",
            "basis_appraisal_refs": [],
            "basis_need_refs": [
                {
                    "need_id": need["need_id"],
                    "semantic_digest": need["semantic_digest"],
                }
            ],
        }
        binding, projection = self.binding_and_projection(
            proposal, artifacts, transition
        )
        gate_paths = self.write_gate(proposal, artifacts, binding, projection)
        paths, _, _ = self.state()
        guarded_paths = [paths.ledger("gaps"), paths.ledger("events")]
        before = {
            path: (path.stat().st_ino, path.read_bytes()) for path in guarded_paths
        }
        mismatched = self.kn(
            [
                "transition-gap",
                "--gap-id",
                "gap-1",
                "--from-record-id",
                from_record_id,
                "--status",
                "blocked",
                "--reason",
                "A different unreviewed reason.",
                *self.gate_arguments(gate_paths),
            ]
        )
        self.assertEqual(mismatched[0], 1)
        self.assertIn("does not authorize this exact", mismatched[2])
        for path, expected in before.items():
            self.assertEqual((path.stat().st_ino, path.read_bytes()), expected)

        applied = self.kn(
            [
                "transition-gap",
                "--gap-id",
                "gap-1",
                "--from-record-id",
                from_record_id,
                "--status",
                "blocked",
                "--reason",
                transition["reason"],
                *self.gate_arguments(gate_paths),
            ]
        )
        self.assertEqual(applied[0], 0, applied[2])
        _, _, records = self.state()
        self.assertEqual(
            max(
                (row for row in records["gaps"] if row.get("gap_id") == "gap-1"),
                key=lambda row: row["sequence"],
            )["status"],
            "blocked",
        )
        self.assertEqual(
            sum(
                row.get("event_type") == "appraised_mutation"
                for row in records["events"]
            ),
            1,
        )

    def test_resolved_transition_requires_current_scope_match_and_relation(
        self,
    ) -> None:
        legacy_append = lambda paths, records, ledger, record_id, payload, **_: (  # noqa: E731
            KN._append_candidate(paths, records, ledger, record_id, payload)
        )
        with mock.patch.object(
            KN, "_append_scientific_candidate", side_effect=legacy_append
        ):
            seeded = self.kn(
                [
                    "add-evidence",
                    "--evidence-id",
                    "evidence-01",
                    "--claim-id",
                    "claim-01",
                    "--source-id",
                    "source-01",
                    "--polarity",
                    "supports",
                    "--exact-locator",
                    "pages/page-0001.txt#char=10-80",
                    "--independence-group",
                    "resolved-fixture-lineage",
                    "--summary",
                    "Historical evidence fixture.",
                ]
            )
        self.assertEqual(seeded[0], 0, seeded[2])
        opened = self.kn(
            [
                "record-gap",
                "--gap-id",
                "gap-1",
                "--gap-type",
                "explicit",
                "--claim-id",
                "claim-01",
                "--impact",
                "high",
                "--status",
                "open",
                "--description",
                "Awaiting exact in-scope evidence.",
            ]
        )
        self.assertEqual(opened[0], 0, opened[2])
        paths, _, records = self.state()
        from_record_id = next(
            row["record_id"] for row in records["gaps"] if row.get("gap_id") == "gap-1"
        )
        proposal = self.proposal()
        artifacts = self.appraisal_package([self.relation_appraisal()])
        appraisal = artifacts["set"]["relation_appraisals"][-1]
        transition = {
            "gap_id": "gap-1",
            "from_record_id": from_record_id,
            "from_status": "open",
            "to_status": "resolved",
            "reason": "The reviewed evidence resolves the scoped gap.",
            "evidence_refs": ["evidence-01"],
            "resolution_source": "",
            "basis_appraisal_refs": [
                {
                    "appraisal_id": appraisal["appraisal_id"],
                    "semantic_digest": appraisal["semantic_digest"],
                }
            ],
            "basis_need_refs": [],
        }
        guarded_paths = [paths.ledger("gaps"), paths.ledger("events")]
        before = {
            path: (path.stat().st_ino, path.read_bytes()) for path in guarded_paths
        }
        with self.assertRaisesRegex(
            BINDING.BindingError, "scope-matched relation projections"
        ):
            self.binding_and_projection(
                proposal,
                artifacts,
                transition,
                relation_scope_alignment="mismatch",
                project_relations=False,
            )
        for path, expected in before.items():
            self.assertEqual((path.stat().st_ino, path.read_bytes()), expected)

        binding, projection = self.binding_and_projection(
            proposal, artifacts, transition
        )
        gate_paths = self.write_gate(proposal, artifacts, binding, projection)
        resolved = self.kn(
            [
                "transition-gap",
                "--gap-id",
                "gap-1",
                "--from-record-id",
                from_record_id,
                "--status",
                "resolved",
                "--reason",
                transition["reason"],
                "--evidence-ref",
                "evidence-01",
                *self.gate_arguments(gate_paths),
            ]
        )
        self.assertEqual(resolved[0], 0, resolved[2])
        _, _, records = self.state()
        self.assertEqual(
            max(
                (row for row in records["gaps"] if row.get("gap_id") == "gap-1"),
                key=lambda row: row["sequence"],
            )["status"],
            "resolved",
        )
        self.assertEqual(
            sum(
                row.get("event_type") == "appraised_mutation"
                for row in records["events"]
            ),
            1,
        )

    def test_compound_locator_and_failed_supersession_cannot_authorize(self) -> None:
        proposal = self.proposal()
        compound = self.relation_appraisal(locator="pp. 1-3 and tables 1, 2")
        with self.assertRaisesRegex(Exception, "non-compound"):
            self.appraisal_package([compound])

        inadmissible_relation = self.relation_appraisal(
            overall="inadmissible", relation="unresolved"
        )
        inadmissible_relation["domain_verdicts"]["analysis"] = "defeated"
        inadmissible_relation["attestation_refs"][0]["decisive"] = False
        inadmissible = self.appraisal_package([inadmissible_relation])
        paths, _, records = self.state()
        binding = BINDING.create_binding(
            inadmissible["package"],
            inadmissible["approval"],
            inadmissible["prepared"],
            inadmissible["review"],
            inadmissible["owner_bundle"],
            [],
            inadmissible["approval"]["authority_digest"],
            proposal,
            proposal["network_ref"],
            KN._scientific_binding_guard(paths, records),
            KN._claim_scopes_from_records(records),
            bound_at="2026-08-10T00:03:00Z",
        )
        review = {
            "schema": "EvidenceAppraisalProjectionReview/v1",
            "binding_ref": {
                "binding_id": binding["binding_id"],
                "binding_digest": binding["binding_digest"],
            },
            "proposal_ref": binding["proposal_ref"],
            "reviewer": {"reviewer_id": "reviewer-01", "reviewer_role": "curator"},
            "decisions": [
                {
                    "action_id": proposal["actions"][0]["action_id"],
                    "action_digest": proposal["actions"][0]["action_digest"],
                    "decision": "authorize",
                    "rationale": "Attempted compound-locator acceptance.",
                    "relation_reviews": [
                        {
                            "binding_row_id": binding["relation_bindings"][0][
                                "binding_row_id"
                            ],
                            "binding_row_digest": binding["relation_bindings"][0][
                                "binding_row_digest"
                            ],
                            "scope_alignment": "match",
                            "projected_relation": "supports",
                        }
                    ],
                    "gap_transition": None,
                }
            ],
        }
        with self.assertRaisesRegex(BINDING.BindingError, "cannot authorize"):
            BINDING.create_reviewed_projection(
                binding, proposal, review, reviewed_at="2026-08-10T00:04:00Z"
            )

        failed = self.relation_appraisal()
        failed["attestation_refs"] = [
            {
                "attestation_id": "attestation-failed",
                "state": "failed",
                "decisive": False,
                "locator_ref": copy.deepcopy(failed["locator_refs"][0]),
                "binding_digest": "0" * 64,
                "supersedes_ref": "attestation-old",
            }
        ]
        with self.assertRaisesRegex(
            Exception, r"failed attestation .* cannot supersede"
        ):
            self.appraisal_package([failed])

    def test_binding_independence_group_is_exact_basis_source_id(self) -> None:
        proposal = self.proposal(("evidence-01", "evidence-02"))
        artifacts = self.appraisal_package(
            [
                self.relation_appraisal(
                    "evidence-01", lineage="untrusted-study-label-a"
                ),
                self.relation_appraisal(
                    "evidence-02", lineage="untrusted-study-label-b"
                ),
            ]
        )
        paths, _, records = self.state()
        binding = BINDING.create_binding(
            artifacts["package"],
            artifacts["approval"],
            artifacts["prepared"],
            artifacts["review"],
            artifacts["owner_bundle"],
            [],
            artifacts["approval"]["authority_digest"],
            proposal,
            proposal["network_ref"],
            KN._scientific_binding_guard(paths, records),
            KN._claim_scopes_from_records(records),
            bound_at="2026-08-10T00:05:00Z",
        )
        self.assertEqual(
            {row["independence_group"] for row in binding["relation_bindings"]},
            {"source-01"},
        )
        self.assertTrue(
            all(
                row["owner_lineage_id"]
                and row["independence_group"] != row["owner_lineage_id"]
                for row in binding["relation_bindings"]
            )
        )

    def test_v3_projection_binds_two_sources_and_all_origin_gaps_in_order(
        self,
    ) -> None:
        for gap_id in ("gap-current-a", "gap-current-b"):
            opened = self.kn(
                [
                    "record-gap",
                    "--gap-id",
                    gap_id,
                    "--gap-type",
                    "deterministic_structural",
                    "--claim-id",
                    "claim-01",
                    "--impact",
                    "high",
                    "--status",
                    "open",
                    "--description",
                    "Awaiting a complete multi-source appraisal.",
                ]
            )
            self.assertEqual(opened[0], 0, opened[2])
        proposal = self.proposal_v3(
            [
                self.origin_gap_ref("gap-current-a"),
                self.origin_gap_ref("gap-current-b"),
            ]
        )
        wrong_consumption_ref = copy.deepcopy(proposal)
        wrong_consumption_ref["consumption_ref"]["authority_id"] = (
            "reviewed-collection-consumption-authority-" + "0" * 16
        )
        wrong_consumption_ref = attach_patch(
            PATCH.without(wrong_consumption_ref, "proposal_id", "proposal_digest"),
            "proposal_id",
            "proposal_digest",
            "network-patch-proposal-",
        )
        with self.assertRaisesRegex(BINDING.BindingError, "authority_id"):
            BINDING.validate_proposal_integrity(wrong_consumption_ref)
        artifacts = self.appraisal_package(
            [
                self.relation_appraisal("evidence-01", source_id="source-01"),
                self.relation_appraisal("evidence-02", source_id="source-02"),
            ]
        )
        transitions = self.resolved_v3_transitions(proposal, artifacts)
        binding, projection = self.binding_and_projection_v3(
            proposal, artifacts, transitions
        )

        self.assertEqual(binding["schema"], "EvidenceAppraisalBinding/v2")
        self.assertEqual(projection["schema"], "EvidenceAppraisalNetworkProjection/v2")
        self.assertEqual(
            [row["independence_group"] for row in binding["relation_bindings"]],
            ["source-01", "source-02"],
        )
        decision = projection["decisions"][0]
        self.assertEqual(
            [item["gap_id"] for item in decision["gap_transitions"]],
            ["gap-current-a", "gap-current-b"],
        )
        self.assertEqual(
            [item["operation_type"] for item in decision["authorized_mutations"]],
            [
                "add-claim",
                "add-evidence",
                "add-evidence",
                "add-relation",
                "add-relation",
                "transition-gap",
                "transition-gap",
            ],
        )
        paths, _, records = self.state()
        self.assertEqual(
            BINDING.validate_binding(
                binding,
                artifacts["package"],
                artifacts["approval"],
                artifacts["prepared"],
                artifacts["review"],
                artifacts["owner_bundle"],
                [],
                artifacts["approval"]["authority_digest"],
                proposal,
                proposal["network_ref"],
                KN._claim_scopes_from_records(records),
            ),
            binding,
        )
        self.assertEqual(
            BINDING.validate_reviewed_projection(projection, binding, proposal),
            projection,
        )
        gate = BINDING.validate_gate(
            artifacts["package"],
            artifacts["approval"],
            artifacts["prepared"],
            artifacts["review"],
            artifacts["owner_bundle"],
            [],
            artifacts["approval"]["authority_digest"],
            proposal,
            binding,
            projection,
            proposal["network_ref"],
            KN._claim_scopes_from_records(records),
        )
        consumed: set[str] = set()
        for transition in transitions:
            authorization = BINDING.authorize_mutation(
                gate,
                "transition-gap",
                {},
                authorization_subject=BINDING._transition_subject(transition),
                consumed_authorization_digests=consumed,
            )
            consumed.add(authorization["authorization_digest"])
        self.assertEqual(len(consumed), 2)
        with self.assertRaisesRegex(BINDING.BindingError, "already consumed"):
            BINDING.authorize_mutation(
                gate,
                "transition-gap",
                {},
                authorization_subject=BINDING._transition_subject(transitions[0]),
                consumed_authorization_digests=consumed,
            )

    def test_v4_extension_binds_new_evidence_to_existing_claim_without_add_claim(
        self,
    ) -> None:
        opened = self.kn(
            [
                "record-gap",
                "--gap-id",
                "gap-existing-claim-evidence",
                "--gap-type",
                "explicit",
                "--claim-id",
                "claim-01",
                "--impact",
                "high",
                "--status",
                "open",
                "--description",
                "The existing claim needs another decisive source.",
            ]
        )
        self.assertEqual(opened[0], 0, opened[2])
        proposal = self.proposal_v4_extension(
            [self.origin_gap_ref("gap-existing-claim-evidence")]
        )
        artifacts = self.appraisal_package(
            [
                self.relation_appraisal("evidence-01", source_id="source-01"),
                self.relation_appraisal("evidence-02", source_id="source-02"),
            ]
        )
        transitions = self.resolved_v3_transitions(proposal, artifacts)
        transitions[0]["resolution_source"] = "claim-01"
        binding, projection = self.binding_and_projection_v3(
            proposal, artifacts, transitions
        )

        self.assertEqual(binding["schema"], "EvidenceAppraisalBinding/v2")
        self.assertEqual(projection["schema"], "EvidenceAppraisalNetworkProjection/v2")
        self.assertEqual(
            [row["network_claim_ref"] for row in binding["relation_bindings"]],
            ["claim-01", "claim-01"],
        )
        self.assertEqual(
            [
                mutation["operation_type"]
                for mutation in projection["decisions"][0]["authorized_mutations"]
            ],
            [
                "add-evidence",
                "add-evidence",
                "add-relation",
                "add-relation",
                "transition-gap",
            ],
        )
        self.assertEqual(BINDING.validate_proposal_integrity(proposal), proposal)
        self.assertEqual(
            BINDING.validate_reviewed_projection(projection, binding, proposal),
            projection,
        )

    def test_v4_extension_rejects_non_network_claim_and_ambiguous_routes(
        self,
    ) -> None:
        opened = self.kn(
            [
                "record-gap",
                "--gap-id",
                "gap-existing-claim-negative",
                "--gap-type",
                "explicit",
                "--claim-id",
                "claim-01",
                "--impact",
                "high",
                "--status",
                "open",
                "--description",
                "The existing claim needs another decisive source.",
            ]
        )
        self.assertEqual(opened[0], 0, opened[2])
        proposal = self.proposal_v4_extension(
            [self.origin_gap_ref("gap-existing-claim-negative")]
        )

        non_network_claim = copy.deepcopy(proposal)
        action = PATCH.without(
            non_network_claim["actions"][0], "action_id", "action_digest"
        )
        existing = copy.deepcopy(action["existing_claim_ref"])
        existing["claim_semantics"]["is_factual"] = True
        existing["claim_semantic_digest"] = PATCH.digest_json(
            existing["claim_semantics"]
        )
        action["existing_claim_ref"] = existing
        non_network_claim["actions"][0] = attach_patch(
            action,
            "action_id",
            "action_digest",
            "network-patch-action-",
        )
        non_network_claim = attach_patch(
            PATCH.without(non_network_claim, "proposal_id", "proposal_digest"),
            "proposal_id",
            "proposal_digest",
            "network-patch-proposal-",
        )
        with self.assertRaisesRegex(BINDING.BindingError, "is_factual must be false"):
            BINDING.validate_proposal_integrity(non_network_claim)

        ambiguous = copy.deepcopy(proposal)
        ambiguous_action = PATCH.without(
            ambiguous["actions"][0], "action_id", "action_digest"
        )
        ambiguous_action["target_claim"] = copy.deepcopy(
            self.proposal_v3([self.origin_gap_ref("gap-existing-claim-negative")])[
                "actions"
            ][0]["target_claim"]
        )
        ambiguous["actions"][0] = attach_patch(
            ambiguous_action,
            "action_id",
            "action_digest",
            "network-patch-action-",
        )
        ambiguous = attach_patch(
            PATCH.without(ambiguous, "proposal_id", "proposal_digest"),
            "proposal_id",
            "proposal_digest",
            "network-patch-proposal-",
        )
        with self.assertRaisesRegex(BINDING.BindingError, "fields mismatch"):
            BINDING.validate_proposal_integrity(ambiguous)

        artifacts = self.appraisal_package(
            [
                self.relation_appraisal("evidence-01", source_id="source-01"),
                self.relation_appraisal("evidence-02", source_id="source-02"),
            ]
        )
        transitions = self.resolved_v3_transitions(proposal, artifacts)
        transitions[0]["resolution_source"] = "claim-other"
        with self.assertRaisesRegex(BINDING.BindingError, "existing claim"):
            self.binding_and_projection_v3(proposal, artifacts, transitions)

    def test_proposal_integrity_uses_patch_utf8_canonicalization(self) -> None:
        self.assertNotEqual(
            BINDING.digest_json({"claim_text": "中文测量主张"}),
            PATCH.digest_json({"claim_text": "中文测量主张"}),
        )

        proposal_v2 = self.proposal()
        action_v2 = PATCH.without(
            copy.deepcopy(proposal_v2["actions"][0]),
            "action_id",
            "action_digest",
        )
        action_v2["hypothesis"] = "中文审查证据。"
        proposal_v2["actions"][0] = attach_patch(
            action_v2,
            "action_id",
            "action_digest",
            "network-patch-action-",
        )
        proposal_v2 = attach_patch(
            PATCH.without(proposal_v2, "proposal_id", "proposal_digest"),
            "proposal_id",
            "proposal_digest",
            "network-patch-proposal-",
        )
        self.assertEqual(
            PATCH.validate_proposal_v2(proposal_v2, proposal_v2["network_ref"]),
            proposal_v2,
        )
        self.assertEqual(BINDING.validate_proposal_integrity(proposal_v2), proposal_v2)

        for gap_id in ("gap-unicode-a", "gap-unicode-b"):
            opened = self.kn(
                [
                    "record-gap",
                    "--gap-id",
                    gap_id,
                    "--gap-type",
                    "deterministic_structural",
                    "--claim-id",
                    "claim-01",
                    "--impact",
                    "high",
                    "--status",
                    "open",
                    "--description",
                    "UTF-8 proposal digest fixture.",
                ]
            )
            self.assertEqual(opened[0], 0, opened[2])
        proposal_v3 = self.proposal_v3(
            [self.origin_gap_ref("gap-unicode-a"), self.origin_gap_ref("gap-unicode-b")]
        )
        action_v3 = PATCH.without(
            copy.deepcopy(proposal_v3["actions"][0]),
            "action_id",
            "action_digest",
        )
        target = PATCH.without(
            action_v3["target_claim"], "claim_id", "target_claim_digest"
        )
        target["claim_text"] = "中文测量主张由两个来源支持。"
        target["scope"]["scope_statement"] = "中文限定范围。"
        target["scope_digest"] = PATCH.digest_json(target["scope"])
        action_v3["target_claim"] = attach_patch(
            target,
            "claim_id",
            "target_claim_digest",
            "claim-target-",
        )
        proposal_v3["actions"][0] = attach_patch(
            action_v3,
            "action_id",
            "action_digest",
            "network-patch-action-",
        )
        proposal_v3 = attach_patch(
            PATCH.without(proposal_v3, "proposal_id", "proposal_digest"),
            "proposal_id",
            "proposal_digest",
            "network-patch-proposal-",
        )
        self.assertEqual(
            PATCH.validate_proposal_v3(proposal_v3, proposal_v3["network_ref"]),
            proposal_v3,
        )
        self.assertEqual(BINDING.validate_proposal_integrity(proposal_v3), proposal_v3)

    def test_v2_high_impact_single_source_cannot_reach_direct_write(self) -> None:
        proposal = self.proposal_v2_high_impact()
        self.assertEqual(
            PATCH.validate_proposal_v2(proposal, proposal["network_ref"]),
            proposal,
        )
        self.assertRegex(
            "; ".join(BINDING.proposal_independence_errors(proposal)),
            "at least two distinct source IDs",
        )
        artifacts = self.appraisal_package([self.relation_appraisal()])
        paths, _, records = self.state()
        with self.assertRaisesRegex(
            BINDING.BindingError, "at least two distinct source IDs"
        ):
            BINDING.create_binding(
                artifacts["package"],
                artifacts["approval"],
                artifacts["prepared"],
                artifacts["review"],
                artifacts["owner_bundle"],
                [],
                artifacts["approval"]["authority_digest"],
                proposal,
                proposal["network_ref"],
                KN._scientific_binding_guard(paths, records),
                KN._claim_scopes_from_records(records),
                bound_at="2026-08-11T00:03:00Z",
            )

        # Reconstruct the legacy bytes the pre-gate implementation could emit.
        # They remain structurally readable for audit, but cannot authorize a
        # direct scientific write.
        with mock.patch.object(
            BINDING,
            "require_applicable_source_independence",
            return_value=None,
        ):
            binding, projection = self.binding_and_projection(proposal, artifacts)
        self.assertEqual(
            BINDING.validate_binding(
                binding,
                artifacts["package"],
                artifacts["approval"],
                artifacts["prepared"],
                artifacts["review"],
                artifacts["owner_bundle"],
                [],
                artifacts["approval"]["authority_digest"],
                proposal,
                proposal["network_ref"],
                KN._claim_scopes_from_records(records),
            ),
            binding,
        )
        with self.assertRaisesRegex(
            BINDING.BindingError, "at least two distinct source IDs"
        ):
            BINDING.validate_gate(
                artifacts["package"],
                artifacts["approval"],
                artifacts["prepared"],
                artifacts["review"],
                artifacts["owner_bundle"],
                [],
                artifacts["approval"]["authority_digest"],
                proposal,
                binding,
                projection,
                proposal["network_ref"],
                KN._claim_scopes_from_records(records),
            )

        gate_paths = self.write_gate(proposal, artifacts, binding, projection)
        target = proposal["actions"][0]["target_claim"]
        scope = target["scope"]
        arguments = [
            "add-claim",
            "--claim-id",
            target["claim_id"],
            "--claim-text",
            target["claim_text"],
            "--impact",
            target["impact"],
            "--scope-statement",
            scope["scope_statement"],
        ]
        for option, field in (
            ("--assumption", "assumptions"),
            ("--condition", "conditions"),
            ("--unit", "units"),
            ("--exclusion", "exclusions"),
            ("--defeater", "defeaters"),
            ("--coverage-dimension", "coverage_dimensions"),
            ("--benchmark-profile", "benchmark_profiles"),
        ):
            for item in scope[field]:
                arguments.extend([option, item])
        denied = self.kn([*arguments, *self.gate_arguments(gate_paths)])
        self.assertNotEqual(denied[0], 0)
        self.assertIn("at least two distinct source IDs", denied[2])
        _, _, current_records = self.state()
        self.assertNotIn(
            target["claim_id"],
            {row.get("claim_id") for row in current_records["claims"]},
        )

    def test_v3_projection_rejects_gap_subsets_reordering_and_partial_bases(
        self,
    ) -> None:
        for gap_id in ("gap-exact-a", "gap-exact-b"):
            opened = self.kn(
                [
                    "record-gap",
                    "--gap-id",
                    gap_id,
                    "--gap-type",
                    "deterministic_structural",
                    "--claim-id",
                    "claim-01",
                    "--impact",
                    "high",
                    "--status",
                    "open",
                    "--description",
                    "Exact transition coverage fixture.",
                ]
            )
            self.assertEqual(opened[0], 0, opened[2])
        proposal = self.proposal_v3(
            [self.origin_gap_ref("gap-exact-a"), self.origin_gap_ref("gap-exact-b")]
        )
        duplicate_evidence = copy.deepcopy(proposal)
        duplicate_action = BINDING.without(
            duplicate_evidence["actions"][0], "action_id", "action_digest"
        )
        duplicate_basis = BINDING.without(
            duplicate_action["reviewed_evidence"][1], "basis_id", "basis_digest"
        )
        duplicate_basis["evidence_id"] = "evidence-01"
        duplicate_basis = attach(
            duplicate_basis,
            "basis_id",
            "basis_digest",
            "network-patch-basis-",
        )
        duplicate_action["reviewed_evidence"][1] = duplicate_basis
        duplicate_target = BINDING.without(
            duplicate_action["target_claim"], "claim_id", "target_claim_digest"
        )
        duplicate_target["report_claim_refs"][1]["basis_id"] = duplicate_basis[
            "basis_id"
        ]
        duplicate_target["report_claim_refs"][1]["basis_digest"] = duplicate_basis[
            "basis_digest"
        ]
        duplicate_action["target_claim"] = attach(
            duplicate_target,
            "claim_id",
            "target_claim_digest",
            "claim-target-",
        )
        duplicate_evidence["actions"][0] = attach(
            duplicate_action,
            "action_id",
            "action_digest",
            "network-patch-action-",
        )
        duplicate_evidence = attach(
            BINDING.without(duplicate_evidence, "proposal_id", "proposal_digest"),
            "proposal_id",
            "proposal_digest",
            "network-patch-proposal-",
        )
        with self.assertRaisesRegex(BINDING.BindingError, "evidence IDs"):
            BINDING.validate_proposal_integrity(duplicate_evidence)

        artifacts = self.appraisal_package(
            [
                self.relation_appraisal("evidence-01", source_id="source-01"),
                self.relation_appraisal("evidence-02", source_id="source-02"),
            ]
        )
        transitions = self.resolved_v3_transitions(proposal, artifacts)

        with self.assertRaisesRegex(BINDING.BindingError, "exactly cover"):
            self.binding_and_projection_v3(proposal, artifacts, transitions[:1])
        with self.assertRaisesRegex(BINDING.BindingError, "canonical order"):
            self.binding_and_projection_v3(
                proposal, artifacts, list(reversed(transitions))
            )

        hypothesis_transition = copy.deepcopy(transitions)
        hypothesis_transition[0]["gap_id"] = proposal["actions"][0]["hypothesis_id"]
        with self.assertRaisesRegex(BINDING.BindingError, "exactly cover"):
            self.binding_and_projection_v3(proposal, artifacts, hypothesis_transition)

        partial_appraisal = copy.deepcopy(transitions)
        partial_appraisal[0]["basis_appraisal_refs"] = partial_appraisal[0][
            "basis_appraisal_refs"
        ][:1]
        with self.assertRaisesRegex(BINDING.BindingError, "every action appraisal"):
            self.binding_and_projection_v3(proposal, artifacts, partial_appraisal)

        partial_evidence = copy.deepcopy(transitions)
        partial_evidence[0]["evidence_refs"] = partial_evidence[0]["evidence_refs"][:1]
        with self.assertRaisesRegex(BINDING.BindingError, "exactly match"):
            self.binding_and_projection_v3(proposal, artifacts, partial_evidence)

        with self.assertRaisesRegex(BINDING.BindingError, "scope-mismatched"):
            self.binding_and_projection_v3(
                proposal, artifacts, transitions, scope_alignment="mismatch"
            )

    def test_v1_binding_validator_retains_legacy_owner_lineage_artifacts(
        self,
    ) -> None:
        proposal = self.proposal()
        artifacts = self.appraisal_package([self.relation_appraisal()])
        paths, _, records = self.state()
        legacy = BINDING._create_binding(
            artifacts["package"],
            artifacts["approval"],
            artifacts["prepared"],
            artifacts["review"],
            artifacts["owner_bundle"],
            [],
            artifacts["approval"]["authority_digest"],
            proposal,
            proposal["network_ref"],
            KN._scientific_binding_guard(paths, records),
            KN._claim_scopes_from_records(records),
            bound_at="2026-08-10T00:05:30Z",
            legacy_owner_lineage_independence=True,
        )
        self.assertTrue(
            legacy["relation_bindings"][0]["independence_group"].startswith(
                "owner-lineage-"
            )
        )
        self.assertEqual(
            BINDING.validate_binding(
                legacy,
                artifacts["package"],
                artifacts["approval"],
                artifacts["prepared"],
                artifacts["review"],
                artifacts["owner_bundle"],
                [],
                artifacts["approval"]["authority_digest"],
                proposal,
                proposal["network_ref"],
                KN._claim_scopes_from_records(records),
            ),
            legacy,
        )
        row = legacy["relation_bindings"][0]
        legacy_review = {
            "schema": "EvidenceAppraisalProjectionReview/v1",
            "binding_ref": {
                "binding_id": legacy["binding_id"],
                "binding_digest": legacy["binding_digest"],
            },
            "proposal_ref": legacy["proposal_ref"],
            "reviewer": {
                "reviewer_id": "legacy-reader-01",
                "reviewer_role": "scientific-curator",
            },
            "decisions": [
                {
                    "action_id": proposal["actions"][0]["action_id"],
                    "action_digest": proposal["actions"][0]["action_digest"],
                    "decision": "authorize",
                    "rationale": "Historical replay fixture only.",
                    "relation_reviews": [
                        {
                            "binding_row_id": row["binding_row_id"],
                            "binding_row_digest": row["binding_row_digest"],
                            "scope_alignment": "match",
                            "projected_relation": row["allowed_relation"],
                        }
                    ],
                    "gap_transition": None,
                }
            ],
        }
        legacy_projection = BINDING.create_reviewed_projection(
            legacy,
            proposal,
            legacy_review,
            reviewed_at="2026-08-10T00:05:31Z",
        )
        self.assertEqual(
            BINDING.validate_reviewed_projection(legacy_projection, legacy, proposal),
            legacy_projection,
        )
        with self.assertRaisesRegex(BINDING.BindingError, "remain readable"):
            BINDING.validate_gate(
                artifacts["package"],
                artifacts["approval"],
                artifacts["prepared"],
                artifacts["review"],
                artifacts["owner_bundle"],
                [],
                artifacts["approval"]["authority_digest"],
                proposal,
                legacy,
                legacy_projection,
                proposal["network_ref"],
                KN._claim_scopes_from_records(records),
            )

    def test_cross_trusted_owner_lineage_fails_closed(self) -> None:
        proposal = self.proposal()
        artifacts = self.appraisal_package([self.relation_appraisal()])
        package = copy.deepcopy(artifacts["package"])
        cross_binding = copy.deepcopy(
            next(
                binding
                for binding in package["appraisal_set"]["owner_artifact_bindings"]
                if binding["role"] == "attestation" and binding["status"] == "passed"
            )
        )
        cross_binding["lineage_id"] = "rkn-cross-owner-lineage"
        package["appraisal_set"]["owner_artifact_bindings"].append(cross_binding)
        package["owner_artifact_binding_digests"].append(
            BINDING.digest_json(cross_binding)
        )
        package["appraisal_set"]["relation_appraisals"][0]["source_lineage"].append(
            cross_binding["lineage_id"]
        )
        paths, _, records = self.state()
        with mock.patch.object(
            BINDING, "_validated_appraisal_package", return_value=package
        ):
            with self.assertRaisesRegex(BINDING.BindingError, "source_lineage"):
                BINDING.create_binding(
                    package,
                    artifacts["approval"],
                    artifacts["prepared"],
                    artifacts["review"],
                    artifacts["owner_bundle"],
                    [],
                    artifacts["approval"]["authority_digest"],
                    proposal,
                    proposal["network_ref"],
                    KN._scientific_binding_guard(paths, records),
                    KN._claim_scopes_from_records(records),
                    bound_at="2026-08-10T00:06:00Z",
                )


if __name__ == "__main__":
    unittest.main()
