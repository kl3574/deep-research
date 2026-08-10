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

    def basis(self, evidence_id: str = "evidence-01") -> dict:
        return attach(
            {
                "basis_id": "",
                "basis_digest": "",
                "review_request_id": "review-request-01",
                "review_request_digest": "1" * 64,
                "report_set_id": "report-set-01",
                "report_set_digest": "2" * 64,
                "dossier_id": "dossier-01",
                "dossier_digest": "3" * 64,
                "reading_report_id": "reading-report-01",
                "reading_report_digest": "4" * 64,
                "source_bundle_id": "source-bundle-01",
                "source_bundle_digest": "5" * 64,
                "source_artifact_sha256": "a" * 64,
                "source_id": "source-01",
                "source_digest": "6" * 64,
                "claim_id": "claim-01",
                "claim_digest": "7" * 64,
                "evidence_id": evidence_id,
                "evidence_digest": "8" * 64,
                "span_id": "span-01",
                "span_hash": "9" * 64,
                "source_ref": "anonymous-paper.txt",
                "acquisition_locator": "https://doi.org/10.1000/anonymous",
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
            action = attach(
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
        return attach(
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

    def relation_appraisal(
        self,
        evidence_id: str = "evidence-01",
        *,
        overall: str = "decisive_within_scope",
        relation: str = "supports",
        locator: str = "pages/page-0001.txt#char=10-29",
        lineage: str = "study-lineage-01",
    ) -> dict:
        locator_ref = {"source_ref": "source-01", "locator": locator}
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
            "source_lineage": ["source-01", lineage],
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

    def test_free_source_lineage_never_becomes_independent(self) -> None:
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
            len({row["independence_group"] for row in binding["relation_bindings"]}),
            1,
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
