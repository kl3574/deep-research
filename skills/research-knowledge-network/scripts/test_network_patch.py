from __future__ import annotations

import copy
import contextlib
import hashlib
import importlib.util
import io
import json
import os
import sys
import tempfile
from pathlib import Path
import unittest
from unittest import mock


SCRIPT_DIR = Path(__file__).parent
sys.path.insert(0, str(SCRIPT_DIR))
import network_patch as PATCH  # noqa: E402

KN = PATCH.kn


def invoke(module, argv: list[str]):
    stdout = io.StringIO()
    stderr = io.StringIO()
    with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
        code = module.main(argv)
    return code, stdout.getvalue(), stderr.getvalue()


def attach(value: dict, id_field: str, digest_field: str, prefix: str) -> dict:
    subject = {
        key: item for key, item in value.items() if key not in {id_field, digest_field}
    }
    digest = PATCH.digest_json(subject)
    value[digest_field] = digest
    value[id_field] = prefix + digest[:16]
    return value


def request_set_file_sha256(request_set):
    return hashlib.sha256(
        json.dumps(
            request_set,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")
        + b"\n"
    ).hexdigest()


class NetworkPatchTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.network_id = "patch-network"
        self._active_proposal = None
        self.gap_stub = mock.Mock()
        self.gap_stub.propose_patch.side_effect = lambda *args, **kwargs: (
            self._active_proposal
        )
        self.gap_stub.propose_patch_v3.side_effect = lambda *args, **kwargs: (
            self._active_proposal
        )
        self.gap_stub.propose_patch_v4.side_effect = lambda *args, **kwargs: (
            self._active_proposal
        )
        self.gap_stub.validate_reviewed_collection_consumption_authority.side_effect = (
            lambda value: value
        )
        self.gap_patcher = mock.patch.object(
            PATCH, "load_gap_module", return_value=self.gap_stub
        )
        self.gap_patcher.start()
        self._real_validate_acceptance = PATCH.validate_acceptance
        fake_gate = {
            "refs": {
                "status": "reviewed_appraisal",
                "appraisal_package_ref": {
                    "package_digest": "c" * 64,
                },
                "appraisal_set_ref": {
                    "appraisal_set_id": "test-appraisal-set",
                    "appraisal_set_digest": "d" * 64,
                },
                "approval_ref": {
                    "authority_id": "authority-" + "b" * 64,
                    "authority_digest": "b" * 64,
                },
                "owner_artifact_binding_digests": ["d" * 64],
                "expected_authority_sha256": "b" * 64,
                "binding_ref": {
                    "binding_id": "evidence-appraisal-binding-" + "e" * 16,
                    "binding_digest": "e" * 64,
                },
                "projection_ref": {
                    "projection_id": "evidence-appraisal-projection-" + "f" * 16,
                    "projection_digest": "f" * 64,
                },
            }
        }
        self.fake_gate = fake_gate

        def legacy_append(paths, records, ledger, record_id, payload, **_):
            return KN._append_candidate(paths, records, ledger, record_id, payload)

        self.science_append_patcher = mock.patch.object(
            KN,
            "_append_scientific_candidate",
            side_effect=legacy_append,
        )
        self.gate_patcher = mock.patch.object(
            PATCH,
            "_load_optional_appraisal_gate",
            return_value=(fake_gate, []),
        )
        self.acceptance_patcher = mock.patch.object(
            PATCH,
            "validate_acceptance",
            side_effect=lambda value, proposal, plan, network_ref, **_: (
                self._real_validate_acceptance(value, proposal, plan, network_ref)
            ),
        )
        self.appraised_acceptance_patcher = mock.patch.object(
            PATCH,
            "validate_appraised_acceptance",
            return_value=None,
        )
        self.science_append_patcher.start()
        self.gate_patcher.start()
        self.acceptance_patcher.start()
        self.appraised_acceptance_patcher.start()
        snapshot = self.root / "corpus.json"
        snapshot.write_text('{"papers": []}', encoding="utf-8")
        code, _, error = self.kn(
            [
                "init",
                "--question",
                "Should a reviewed relation enter the network?",
                "--scope",
                "reviewed-only",
                "--snapshot-path",
                str(snapshot),
                "--snapshot-digest",
                KN._sha256_file(snapshot),
            ]
        )
        self.assertEqual(code, 0, error)
        code, _, error = self.kn(
            [
                "add-source",
                "--source-id",
                "source-01",
                "--canonical-identity",
                "doi:10.1000/example",
                "--canonical-version",
                "v1",
                "--read-version",
                "reviewed-v1",
                "--read-depth",
                "full",
                "--version-hash",
                "sha256:" + "a" * 64,
                "--role",
                "source",
            ]
        )
        self.assertEqual(code, 0, error)
        code, _, error = self.kn(
            [
                "add-claim",
                "--claim-id",
                "claim-01",
                "--claim-text",
                "Calibrated sparse dynamics recover the benchmark.",
                "--impact",
                "high",
            ]
        )
        self.assertEqual(code, 0, error)

    def tearDown(self):
        self.appraised_acceptance_patcher.stop()
        self.acceptance_patcher.stop()
        self.gate_patcher.stop()
        self.science_append_patcher.stop()
        self.gap_patcher.stop()
        self.temp.cleanup()

    def kn(self, arguments: list[str]):
        return invoke(
            KN,
            ["--root", str(self.root), "--network-id", self.network_id, *arguments],
        )

    def patch(self, arguments: list[str]):
        return invoke(
            PATCH,
            ["--root", str(self.root), "--network-id", self.network_id, *arguments],
        )

    def current_ref(self) -> dict[str, str]:
        paths = KN._safe_paths(str(self.root), self.network_id)
        state, records = KN._load_state(paths)
        return PATCH.current_network_ref(paths, state, records)

    def basis(self, suffix: str) -> dict:
        value = {
            "review_request_id": f"review-request-{suffix}",
            "review_request_digest": "1" * 64,
            "report_set_id": "report-set-01",
            "report_set_digest": "2" * 64,
            "dossier_id": f"dossier-{suffix}",
            "dossier_digest": "3" * 64,
            "reading_report_id": f"reading-report-{suffix}",
            "reading_report_digest": "4" * 64,
            "source_bundle_id": f"source-bundle-{suffix}",
            "source_bundle_digest": "5" * 64,
            "source_artifact_sha256": "a" * 64,
            "source_id": "source-01",
            "source_digest": "6" * 64,
            "claim_id": "claim-01",
            "claim_digest": "7" * 64,
            "evidence_id": f"paper-evidence-{suffix}",
            "evidence_digest": "8" * 64,
            "span_id": f"span-{suffix}",
            "span_hash": "9" * 64,
            "source_ref": "paper.txt",
            "acquisition_locator": "https://doi.org/10.1000/example",
            "evidence_locator": "pages/page-0001.txt#char=12-48",
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
        }
        return attach(value, "basis_id", "basis_digest", "network-patch-basis-")

    def action(self, action_type: str, hypothesis_id: str, suffix: str) -> dict:
        kind = action_type.removeprefix("propose_")
        signature = {
            "relation": "entity:A ? entity:C",
            "evidence": f"paper-evidence-{suffix}",
            "node": f"claim-node-{suffix}",
        }[kind]
        reviewed_evidence = [self.basis(suffix)]
        target_signature = {
            "target_kind": kind,
            "signature": signature,
        }
        value = {
            "action_type": action_type,
            "action_status": "blocked" if kind == "node" else "proposed",
            "hypothesis_id": hypothesis_id,
            "target_signature": target_signature,
            "hypothesis": f"Reviewed hypothesis {suffix}",
            "reviewed_evidence": reviewed_evidence,
        }
        if kind == "relation":
            basis = reviewed_evidence[0]
            scope = {
                "scope_statement": f"Reviewed report scope {suffix}",
                "assumptions": ["sparse governing dynamics"],
                "conditions": ["noise-controlled observations"],
                "units": ["dimensionless benchmark units"],
                "exclusions": ["fully observed dense systems"],
                "defeaters": ["non-identifiable reaction sets"],
                "coverage_dimensions": ["structural-identifiability"],
                "benchmark_profiles": ["sparse-dynamics-toy-model"],
            }
            target_claim = {
                "schema": "NetworkPatchTargetClaim/v1",
                "schema_version": "1.0",
                "claim_text": f"Reviewed scientific relation {suffix}",
                "entity_id": None,
                "impact": "low",
                "coverage_dimensions": scope["coverage_dimensions"],
                "benchmark_profiles": scope["benchmark_profiles"],
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
            }
            target_claim["target_claim_digest"] = PATCH.digest_json(target_claim)
            target_claim["claim_id"] = (
                "claim-target-" + target_claim["target_claim_digest"][:16]
            )
            value["target_claim"] = target_claim
        return attach(value, "action_id", "action_digest", "network-patch-action-")

    def proposal(self) -> dict:
        value = {
            "schema": "NetworkPatchProposal/v2",
            "schema_version": "2.0",
            "network_ref": self.current_ref(),
            "request_ref": {
                "request_set_id": "request-set-01",
                "request_set_digest": "c" * 64,
                "review_request_set_id": "review-request-set-01",
                "review_request_set_digest": "d" * 64,
            },
            "generated_at": "2026-08-05T01:00:00Z",
            "proposal_only": True,
            "novelty_claimed": False,
            "review_gate": "pending_research_knowledge_network_acceptance",
            "actions": [
                self.action("propose_relation", "gap-relation", "1"),
                self.action("propose_node", "gap-node", "2"),
                self.action("propose_evidence", "gap-evidence", "3"),
            ],
        }
        return attach(
            value,
            "proposal_id",
            "proposal_digest",
            "network-patch-proposal-",
        )

    def proposal_v3(self) -> tuple[dict, dict]:
        code, _, error = self.kn(
            [
                "add-source",
                "--source-id",
                "source-02",
                "--canonical-identity",
                "doi:10.1000/example-2",
                "--canonical-version",
                "v1",
                "--read-version",
                "reviewed-v1",
                "--read-depth",
                "full",
                "--version-hash",
                "sha256:" + "e" * 64,
                "--role",
                "source",
            ]
        )
        self.assertEqual(code, 0, error)
        code, _, error = self.kn(
            [
                "record-gap",
                "--gap-id",
                "gap-v3-explicit",
                "--gap-type",
                "explicit",
                "--impact",
                "high",
                "--priority",
                "P0",
                "--decision-impact",
                "high",
                "--status",
                "open",
                "--source",
                "manual-test",
                "--description",
                "A second real origin gap requires the same atomic evidence.",
            ]
        )
        self.assertEqual(code, 0, error)
        code, _, error = self.kn(["derive-gaps"])
        self.assertEqual(code, 0, error)
        paths = KN._safe_paths(str(self.root), self.network_id)
        state, records = KN._load_state(paths)
        live_network = KN._knowledge_network_export(paths, state, records)
        open_gaps = [item for item in live_network["gaps"] if item["status"] == "open"]
        self.assertGreaterEqual(len(open_gaps), 2)
        origin_refs = [
            {"gap_id": gap["gap_id"], **gap["record_ref"]} for gap in open_gaps[:2]
        ]

        first = self.basis("v3-a")
        first.update(
            {
                "report_set_id": "report-set-v3-a",
                "report_set_digest": "2" * 64,
                "claim_id": "report-claim-v3-a",
                "claim_digest": "7" * 64,
            }
        )
        first = attach(
            PATCH.without(first, "basis_id", "basis_digest"),
            "basis_id",
            "basis_digest",
            "network-patch-basis-",
        )
        second = self.basis("v3-b")
        second.update(
            {
                "source_id": "source-02",
                "source_digest": "e" * 64,
                "source_artifact_sha256": "e" * 64,
                "report_set_id": "report-set-v3-b",
                "report_set_digest": "f" * 64,
                "claim_id": "report-claim-v3-b",
                "claim_digest": "0" * 64,
            }
        )
        second = attach(
            PATCH.without(second, "basis_id", "basis_digest"),
            "basis_id",
            "basis_digest",
            "network-patch-basis-",
        )
        bases = [first, second]
        groups = [
            {
                "reading_group_id": "paper-reading-evidence-group-" + prefix * 16,
                "reading_group_digest": prefix * 64,
                "source_id": basis["source_id"],
                "report_set_id": basis["report_set_id"],
                "report_set_digest": basis["report_set_digest"],
            }
            for prefix, basis in zip(("1", "2"), bases)
        ]
        target_signature = {
            "target_kind": "relation",
            "signature": "two independent readings support a bounded relation",
        }
        subject_ref = {
            "subject_id": "reviewed-gap-claim-subject-" + "c" * 16,
            "subject_digest": "c" * 64,
        }
        scope = {
            "scope_statement": "Bounded two-source claim scope.",
            "assumptions": ["fixed reviewed estimand"],
            "conditions": ["two independent source lineages"],
            "units": ["dimensionless"],
            "exclusions": ["single-source extrapolation"],
            "defeaters": ["source identity collapse"],
            "coverage_dimensions": [],
            "benchmark_profiles": [],
        }
        target = {
            "schema": "NetworkPatchTargetClaim/v2",
            "schema_version": "2.0",
            "claim_text": "Two independent readings support this bounded relation.",
            "entity_id": None,
            "impact": "high",
            "coverage_dimensions": scope["coverage_dimensions"],
            "benchmark_profiles": scope["benchmark_profiles"],
            "supersedes": None,
            "target_signature": target_signature,
            "subject_ref": subject_ref,
            "origin_gap_refs": origin_refs,
            "report_claim_refs": [
                {
                    "basis_id": basis["basis_id"],
                    "basis_digest": basis["basis_digest"],
                    "reading_group_id": group["reading_group_id"],
                    "claim_id": basis["claim_id"],
                    "claim_digest": basis["claim_digest"],
                    "reading_report_id": basis["reading_report_id"],
                    "reading_report_digest": basis["reading_report_digest"],
                }
                for basis, group in zip(bases, groups)
            ],
            "scope": scope,
            "scope_digest": PATCH.digest_json(scope),
        }
        target["target_claim_digest"] = PATCH.digest_json(target)
        target["claim_id"] = "claim-target-" + target["target_claim_digest"][:16]
        action = attach(
            {
                "action_type": "propose_relation",
                "action_status": "proposed",
                "hypothesis_id": "KGH-v3-multi-source",
                "target_signature": target_signature,
                "hypothesis": "Two sources support a bounded high-impact claim.",
                "subject_ref": subject_ref,
                "origin_gap_refs": origin_refs,
                "reading_group_refs": groups,
                "reviewed_evidence": bases,
                "target_claim": target,
            },
            "action_id",
            "action_digest",
            "network-patch-action-",
        )
        proposal = attach(
            {
                "schema": "NetworkPatchProposal/v3",
                "schema_version": "3.0",
                "network_ref": self.current_ref(),
                "request_ref": {
                    "request_set_id": "request-set-v3",
                    "request_set_digest": "a" * 64,
                    "review_request_set_id": "review-request-set-v3",
                    "review_request_set_digest": "b" * 64,
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
                    "collection_id": "paper-reading-evidence-collection-" + "d" * 16,
                    "collection_digest": "d" * 64,
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
        return proposal, live_network

    def proposal_v4_extension(self) -> tuple[dict, dict]:
        code, _, error = self.kn(
            [
                "add-source",
                "--source-id",
                "source-02",
                "--canonical-identity",
                "doi:10.1000/example-2",
                "--canonical-version",
                "v1",
                "--read-version",
                "reviewed-v1",
                "--read-depth",
                "full",
                "--version-hash",
                "sha256:" + "e" * 64,
                "--role",
                "source",
            ]
        )
        self.assertEqual(code, 0, error)
        claim_text = "Two independent readings extend this bounded existing claim."
        code, _, error = self.kn(
            [
                "add-claim",
                "--claim-id",
                "claim-existing-v4",
                "--claim-text",
                claim_text,
                "--impact",
                "high",
                "--scope-statement",
                "Bounded existing-claim extension scope.",
                "--assumption",
                "fixed reviewed estimand",
                "--condition",
                "two independent source lineages",
                "--unit",
                "dimensionless",
                "--exclusion",
                "single-source extrapolation",
                "--defeater",
                "source identity collapse",
            ]
        )
        self.assertEqual(code, 0, error)
        code, _, error = self.kn(["derive-gaps"])
        self.assertEqual(code, 0, error)
        paths = KN._safe_paths(str(self.root), self.network_id)
        state, records = KN._load_state(paths)
        live_network = KN._knowledge_network_export(paths, state, records)
        origin_refs = [
            {"gap_id": gap["gap_id"], **gap["record_ref"]}
            for gap in live_network["gaps"]
            if gap.get("claim_id") == "claim-existing-v4" and gap["status"] == "open"
        ]
        self.assertEqual(len(origin_refs), 2)

        first = self.basis("v4-a")
        first.update(
            {
                "report_set_id": "report-set-v4-a",
                "report_set_digest": "2" * 64,
                "claim_id": "report-claim-v4-a",
                "claim_digest": "7" * 64,
            }
        )
        first = attach(
            PATCH.without(first, "basis_id", "basis_digest"),
            "basis_id",
            "basis_digest",
            "network-patch-basis-",
        )
        second = self.basis("v4-b")
        second.update(
            {
                "source_id": "source-02",
                "source_digest": "e" * 64,
                "source_artifact_sha256": "e" * 64,
                "report_set_id": "report-set-v4-b",
                "report_set_digest": "f" * 64,
                "claim_id": "report-claim-v4-b",
                "claim_digest": "0" * 64,
            }
        )
        second = attach(
            PATCH.without(second, "basis_id", "basis_digest"),
            "basis_id",
            "basis_digest",
            "network-patch-basis-",
        )
        bases = [first, second]
        groups = [
            {
                "reading_group_id": "paper-reading-evidence-group-" + prefix * 16,
                "reading_group_digest": prefix * 64,
                "source_id": basis["source_id"],
                "report_set_id": basis["report_set_id"],
                "report_set_digest": basis["report_set_digest"],
            }
            for prefix, basis in zip(("3", "4"), bases)
        ]
        claim_row = next(
            row
            for row in live_network["claims"]
            if row["claim_id"] == "claim-existing-v4"
        )
        semantic_fields = (
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
        claim_semantics = {field: claim_row[field] for field in semantic_fields}
        scope = {
            field: claim_semantics[field]
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
        existing_claim_ref = {
            "schema": "NetworkPatchExistingClaimRef/v1",
            "schema_version": "1.0",
            "claim_id": claim_row["claim_id"],
            "claim_record_ref": {
                "record_id": claim_row["record_id"],
                "sequence": claim_row["sequence"],
                "sha256": PATCH.digest_json(claim_row),
            },
            "claim_semantics": claim_semantics,
            "scope_digest": PATCH.digest_json(scope),
            "claim_semantic_digest": PATCH.digest_json(claim_semantics),
        }
        hypothesis_id = "KGH-v4-existing-claim-extension"
        target_signature = {
            "target_kind": "relation",
            "signature": "two independent readings extend a bounded existing claim",
        }
        subject = {
            "hypothesis_id": hypothesis_id,
            "claim_text": claim_text,
            "impact": claim_row["impact"],
            "target_signature": target_signature["signature"],
            **scope,
            "origin_gap_refs": origin_refs,
        }
        subject_digest = PATCH.digest_json(subject)
        subject_ref = {
            "subject_id": "reviewed-gap-claim-subject-" + subject_digest[:16],
            "subject_digest": subject_digest,
        }
        action = attach(
            {
                "action_type": "propose_evidence_extension",
                "action_status": "proposed",
                "hypothesis_id": hypothesis_id,
                "target_signature": target_signature,
                "hypothesis": claim_text,
                "subject_ref": subject_ref,
                "origin_gap_refs": origin_refs,
                "reading_group_refs": groups,
                "reviewed_evidence": bases,
                "existing_claim_ref": existing_claim_ref,
            },
            "action_id",
            "action_digest",
            "network-patch-action-",
        )
        proposal = attach(
            {
                "schema": "NetworkPatchProposal/v4",
                "schema_version": "4.0",
                "network_ref": self.current_ref(),
                "request_ref": {
                    "request_set_id": "request-set-v4",
                    "request_set_digest": "a" * 64,
                    "review_request_set_id": "review-request-set-v4",
                    "review_request_set_digest": "b" * 64,
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
                    "collection_id": "paper-reading-evidence-collection-" + "d" * 16,
                    "collection_digest": "d" * 64,
                },
                "generated_at": "2026-08-12T00:00:00Z",
                "proposal_only": True,
                "novelty_claimed": False,
                "review_gate": "pending_research_knowledge_network_acceptance",
                "actions": [action],
            },
            "proposal_id",
            "proposal_digest",
            "network-patch-proposal-",
        )
        return proposal, live_network

    def operation(
        self, operation_type: str, payload: dict, basis_rows: list[dict]
    ) -> dict:
        return attach(
            {
                "operation_type": operation_type,
                "basis_refs": [
                    {
                        "basis_id": item["basis_id"],
                        "basis_digest": item["basis_digest"],
                    }
                    for item in basis_rows
                ],
                "payload": payload,
            },
            "operation_id",
            "operation_digest",
            "network-operation-",
        )

    def authority(self) -> dict:
        authority_artifact = self.root / "acceptance-review.json"
        authority_artifact.write_text(
            '{"decision":"approved-by-scientific-curator"}\n',
            encoding="utf-8",
        )
        value = {
            "basis_type": "expert_review",
            "source_ref": "acceptance-review.json",
            "locator": "decision:relation-1",
            "artifact_sha256": hashlib.sha256(
                authority_artifact.read_bytes()
            ).hexdigest(),
        }
        value["basis_id"] = "patch-authority-basis-" + PATCH.digest_json(value)[:16]
        return value

    def acceptance(self, proposal: dict, plan: dict) -> dict:
        authority = self.authority()
        action = proposal["actions"][0]
        relation_basis = action["reviewed_evidence"]
        target_claim = self.operation(
            "add-claim",
            {
                field: action["target_claim"][field]
                for field in (
                    "claim_id",
                    "claim_text",
                    "entity_id",
                    "impact",
                    "coverage_dimensions",
                    "benchmark_profiles",
                    "supersedes",
                )
            }
            | {
                "scope_statement": action["target_claim"]["scope"]["scope_statement"],
                **{
                    field: action["target_claim"]["scope"][field]
                    for field in (
                        "assumptions",
                        "conditions",
                        "units",
                        "exclusions",
                        "defeaters",
                    )
                },
            },
            relation_basis,
        )
        evidence = self.operation(
            "add-evidence",
            {
                "evidence_id": "paper-evidence-1",
                "claim_id": PATCH.target_claim_id(action),
                "source_id": "source-01",
                "polarity": "supports",
                "exact_locator": "pages/page-0001.txt#char=12-48",
                "independence_group": "source-01",
                "summary": action["hypothesis"],
                "notes": "accepted from NetworkPatchProposal/v2",
                "supersedes": None,
            },
            relation_basis,
        )
        relation = self.operation(
            "add-relation",
            {
                "relation_id": PATCH.relation_operation_id(action, relation_basis[0]),
                "relation_type": "supports",
                "from_ref": "claim:" + PATCH.target_claim_id(action),
                "to_ref": "evidence:paper-evidence-1",
                "notes": "network-patch-action:" + action["action_digest"],
                "supersedes": None,
            },
            relation_basis,
        )
        decisions = [
            {
                "action_id": proposal["actions"][0]["action_id"],
                "action_digest": proposal["actions"][0]["action_digest"],
                "decision": "accept",
                "rationale": "Independent evidence and typed mapping passed review.",
                "authority_basis_ids": [authority["basis_id"]],
                "operations": [target_claim, evidence, relation],
            },
            {
                "action_id": proposal["actions"][1]["action_id"],
                "action_digest": proposal["actions"][1]["action_digest"],
                "decision": "reject",
                "rationale": "The node duplicates an existing construct.",
                "authority_basis_ids": [authority["basis_id"]],
                "operations": [],
            },
            {
                "action_id": proposal["actions"][2]["action_id"],
                "action_digest": proposal["actions"][2]["action_digest"],
                "decision": "defer",
                "rationale": "A second independent source is still required.",
                "authority_basis_ids": [authority["basis_id"]],
                "operations": [],
            },
        ]
        value = {
            "schema": "NetworkPatchAcceptance/v1",
            "schema_version": "1.0",
            "network_ref": proposal["network_ref"],
            "proposal_ref": {
                "proposal_id": proposal["proposal_id"],
                "proposal_digest": proposal["proposal_digest"],
            },
            "plan_ref": {
                "plan_id": plan["plan_id"],
                "plan_digest": plan["plan_digest"],
            },
            "decided_at": "2026-08-05T02:00:00Z",
            "operator": {
                "operator_id": "review-board-01",
                "operator_role": "scientific-curator",
                "authority_basis": [authority],
            },
            "decisions": decisions,
        }
        return attach(
            value,
            "acceptance_id",
            "acceptance_digest",
            "network-patch-acceptance-",
        )

    def extension_acceptance(self, proposal: dict, plan: dict) -> dict:
        authority = self.authority()
        action = proposal["actions"][0]
        bases = action["reviewed_evidence"]
        operations = [
            self.operation(
                "add-evidence",
                {
                    "evidence_id": basis["evidence_id"],
                    "claim_id": action["existing_claim_ref"]["claim_id"],
                    "source_id": basis["source_id"],
                    "polarity": "supports",
                    "exact_locator": basis["evidence_locator"],
                    "independence_group": basis["source_id"],
                    "summary": action["hypothesis"],
                    "notes": "accepted from NetworkPatchProposal/v4",
                    "supersedes": None,
                },
                [basis],
            )
            for basis in bases
        ]
        operations.extend(
            self.operation(
                "add-relation",
                {
                    "relation_id": PATCH.relation_operation_id(action, basis),
                    "relation_type": "supports",
                    "from_ref": "claim:" + action["existing_claim_ref"]["claim_id"],
                    "to_ref": "evidence:" + basis["evidence_id"],
                    "notes": "network-patch-action:" + action["action_digest"],
                    "supersedes": None,
                },
                [basis],
            )
            for basis in bases
        )
        operations.extend(
            self.operation(
                "transition-gap",
                {
                    "gap_id": origin["gap_id"],
                    "from_record_id": origin["record_id"],
                    "status": "resolved",
                    "reason": "The existing claim now has decisive multi-source evidence.",
                    "evidence_refs": [basis["evidence_id"] for basis in bases],
                    "resolution_source": action["existing_claim_ref"]["claim_id"],
                },
                bases,
            )
            for origin in action["origin_gap_refs"]
        )
        value = {
            "schema": "NetworkPatchAcceptance/v1",
            "schema_version": "1.0",
            "network_ref": proposal["network_ref"],
            "proposal_ref": {
                "proposal_id": proposal["proposal_id"],
                "proposal_digest": proposal["proposal_digest"],
            },
            "plan_ref": {
                "plan_id": plan["plan_id"],
                "plan_digest": plan["plan_digest"],
            },
            "decided_at": "2026-08-12T00:20:00Z",
            "operator": {
                "operator_id": "review-board-v4",
                "operator_role": "scientific-curator",
                "authority_basis": [authority],
            },
            "decisions": [
                {
                    "action_id": action["action_id"],
                    "action_digest": action["action_digest"],
                    "decision": "accept",
                    "rationale": "Every new source and origin gap passed review.",
                    "authority_basis_ids": [authority["basis_id"]],
                    "operations": operations,
                }
            ],
        }
        return attach(
            value,
            "acceptance_id",
            "acceptance_digest",
            "network-patch-acceptance-",
        )

    def write(self, name: str, value: dict) -> Path:
        path = self.root / name
        path.write_text(json.dumps(value, sort_keys=True), encoding="utf-8")
        return path

    def evidence_pack(self, proposal: dict) -> dict:
        artifact_root = self.root / "runtime-artifacts"
        artifact_root.mkdir(exist_ok=True)
        verification_root = self.root / "verification-root"
        verification_root.mkdir(exist_ok=True)
        attestation = verification_root / "independent.json"
        attestation.write_text('{"fixture": true}\n', encoding="utf-8")
        artifacts = {}
        for role in sorted(PATCH.EVIDENCE_PACK_FILE_ROLES):
            suffix = ".txt" if role == "source_artifact" else ".json"
            path = artifact_root / f"{role}{suffix}"
            content = "fixture source" if suffix == ".txt" else "{}"
            path.write_text(content, encoding="utf-8")
            artifacts[role] = {
                "path": str(path),
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            }
        _, tree_digest = PATCH._verification_tree_digest(str(verification_root))
        value = {
            "schema": "NetworkPatchEvidencePack/v1",
            "schema_version": "1.0",
            "proposal_ref": {
                "proposal_id": proposal["proposal_id"],
                "proposal_digest": proposal.get("proposal_digest")
                or PATCH.digest_json(proposal),
            },
            "network_ref": proposal["network_ref"],
            "artifacts": artifacts,
            "verification_root": {
                "path": str(verification_root),
                "tree_sha256": tree_digest,
            },
        }
        self._active_proposal = proposal
        return attach(
            value,
            "pack_id",
            "pack_digest",
            "network-patch-evidence-pack-",
        )

    def evidence_pack_from_artifacts(
        self,
        proposal: dict,
        artifact_paths: dict[str, Path],
        verification_root: Path,
    ) -> dict:
        artifacts = {
            role: {
                "path": str(path.resolve()),
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            }
            for role, path in sorted(artifact_paths.items())
        }
        _, tree_digest = PATCH._verification_tree_digest(str(verification_root))
        return attach(
            {
                "schema": "NetworkPatchEvidencePack/v1",
                "schema_version": "1.0",
                "proposal_ref": {
                    "proposal_id": proposal["proposal_id"],
                    "proposal_digest": proposal["proposal_digest"],
                },
                "network_ref": proposal["network_ref"],
                "artifacts": artifacts,
                "verification_root": {
                    "path": str(verification_root.resolve()),
                    "tree_sha256": tree_digest,
                },
            },
            "pack_id",
            "pack_digest",
            "network-patch-evidence-pack-",
        )

    def contracts(self):
        proposal = self.proposal()
        plan = PATCH.create_plan(
            proposal,
            proposal["network_ref"],
            prepared_at="2026-08-05T01:30:00Z",
        )
        return proposal, plan, self.acceptance(proposal, plan)

    def test_real_relation_apply_is_dry_runnable_atomic_and_audited(self):
        proposal, plan, acceptance = self.contracts()
        evidence_pack = self.evidence_pack(proposal)
        proposal_path = self.write("proposal.json", proposal)
        plan_path = self.write("plan.json", plan)
        acceptance_path = self.write("acceptance.json", acceptance)
        pack_path = self.write("evidence-pack.json", evidence_pack)
        before = self.current_ref()
        network_dir = self.root / KN.NETWORK_ROOT / self.network_id
        live_before = {
            path.name: (
                path.stat().st_ino,
                hashlib.sha256(path.read_bytes()).hexdigest(),
            )
            for path in [network_dir / "network.json"]
            + [network_dir / f"{name}.jsonl" for name in KN.LEDGER_NAMES]
        }

        validated = self.patch(
            [
                "validate-patch",
                "--proposal",
                str(proposal_path),
                "--evidence-pack",
                str(pack_path),
            ]
        )
        self.assertEqual(validated[0], 0, validated[2])
        self.assertTrue(json.loads(validated[1])["apply_eligible"])

        prepared_path = self.root / "patch-plans" / "prepared-plan.json"
        prepared = self.patch(
            [
                "prepare-patch",
                "--proposal",
                str(proposal_path),
                "--evidence-pack",
                str(pack_path),
                "--output",
                str(prepared_path),
            ]
        )
        self.assertEqual(prepared[0], 0, prepared[2])
        self.assertEqual(json.loads(prepared[1])["proposal_ref"], plan["proposal_ref"])

        dry = self.patch(
            [
                "apply-patch",
                "--proposal",
                str(proposal_path),
                "--evidence-pack",
                str(pack_path),
                "--plan",
                str(plan_path),
                "--acceptance",
                str(acceptance_path),
                "--dry-run",
            ]
        )
        self.assertEqual(dry[0], 0, dry[2])
        self.assertEqual(self.current_ref(), before)
        live_after_dry = {
            path.name: (
                path.stat().st_ino,
                hashlib.sha256(path.read_bytes()).hexdigest(),
            )
            for path in [network_dir / "network.json"]
            + [network_dir / f"{name}.jsonl" for name in KN.LEDGER_NAMES]
        }
        self.assertEqual(live_after_dry, live_before)
        self.assertGreaterEqual(self.gap_stub.propose_patch.call_count, 3)

        applied = self.patch(
            [
                "apply-patch",
                "--proposal",
                str(proposal_path),
                "--evidence-pack",
                str(pack_path),
                "--plan",
                str(plan_path),
                "--acceptance",
                str(acceptance_path),
            ]
        )
        self.assertEqual(applied[0], 0, applied[2])
        result = json.loads(applied[1])
        self.assertEqual(
            result["decision_counts"], {"accept": 1, "defer": 1, "reject": 1}
        )
        self.assertNotEqual(self.current_ref(), before)
        paths = KN._safe_paths(str(self.root), self.network_id)
        _, records = KN._load_state(paths)
        self.assertEqual(
            [item["evidence_id"] for item in records["evidence"]],
            ["paper-evidence-1"],
        )
        self.assertEqual(
            [item["relation_id"] for item in records["relations"]],
            [
                PATCH.relation_operation_id(
                    proposal["actions"][0],
                    proposal["actions"][0]["reviewed_evidence"][0],
                )
            ],
        )
        events = [
            item
            for item in records["events"]
            if item.get("event_type") == "patch_decision"
        ]
        self.assertEqual(len(events), 1)
        self.assertEqual(
            [item["decision"] for item in events[0]["decisions"]],
            ["accept", "reject", "defer"],
        )
        exported = self.kn(["export"])
        self.assertEqual(exported[0], 0, exported[2])
        patch_changes = [
            item
            for item in json.loads(exported[1])["change_history"]
            if item["action"] == "patch-decision"
        ]
        self.assertEqual(len(patch_changes), 1)
        self.assertTrue(
            all(
                item.startswith("authority:sha256:")
                for item in patch_changes[0]["basis_refs"]
            )
        )
        self.assertNotIn("source:source-01", patch_changes[0]["basis_refs"])
        self.assertIn(
            proposal["actions"][0]["action_id"], patch_changes[0]["object_ids"]
        )

        duplicate = self.patch(
            [
                "apply-patch",
                "--proposal",
                str(proposal_path),
                "--evidence-pack",
                str(pack_path),
                "--plan",
                str(plan_path),
                "--acceptance",
                str(acceptance_path),
            ]
        )
        self.assertEqual(duplicate[0], 1)
        self.assertIn("stale", duplicate[2])

    def test_tampering_noneligibility_unmapped_and_stale_fail_closed(self):
        proposal, plan, acceptance = self.contracts()
        evidence_pack = self.evidence_pack(proposal)
        tampered = json.loads(json.dumps(proposal))
        tampered["actions"][0]["hypothesis"] = "forged"
        with self.assertRaises(ValueError):
            PATCH.validate_proposal_v2(tampered, self.current_ref())

        noneligible = json.loads(json.dumps(proposal))
        basis = noneligible["actions"][0]["reviewed_evidence"][0]
        basis["verification"]["mode"] = "same_context_diagnostic"
        attach(basis, "basis_id", "basis_digest", "network-patch-basis-")
        attach(
            noneligible["actions"][0],
            "action_id",
            "action_digest",
            "network-patch-action-",
        )
        attach(
            noneligible,
            "proposal_id",
            "proposal_digest",
            "network-patch-proposal-",
        )
        with self.assertRaises(ValueError):
            PATCH.validate_proposal_v2(noneligible, self.current_ref())

        unmapped = json.loads(json.dumps(acceptance))
        unmapped["decisions"][0]["operations"] = []
        attach(
            unmapped,
            "acceptance_id",
            "acceptance_digest",
            "network-patch-acceptance-",
        )
        with self.assertRaises(ValueError):
            PATCH.validate_acceptance(unmapped, proposal, plan, self.current_ref())

        proposal_path = self.write("stale-proposal.json", proposal)
        plan_path = self.write("stale-plan.json", plan)
        acceptance_path = self.write("stale-acceptance.json", acceptance)
        pack_path = self.write("stale-pack.json", evidence_pack)
        changed = self.kn(
            [
                "add-entity",
                "--entity-id",
                "later-entity",
                "--entity-type",
                "method",
                "--name",
                "Later entity",
                "--description",
                "Makes the proposal snapshot stale",
            ]
        )
        self.assertEqual(changed[0], 0, changed[2])
        stale = self.patch(
            [
                "apply-patch",
                "--proposal",
                str(proposal_path),
                "--evidence-pack",
                str(pack_path),
                "--plan",
                str(plan_path),
                "--acceptance",
                str(acceptance_path),
            ]
        )
        self.assertEqual(stale[0], 1)
        self.assertIn("stale", stale[2])

    def test_evidence_pack_reopens_artifacts_and_rejects_missing_or_forged_chain(self):
        proposal, _, _ = self.contracts()
        forged = json.loads(json.dumps(proposal))
        basis = forged["actions"][0]["reviewed_evidence"][0]
        basis["source_id"] = "forged-source-not-in-network"
        basis["claim_id"] = "forged-claim-not-in-network"
        basis["verification"] = {
            "mode": "independent_source_check",
            "verifier_id": "proposal-self",
            "artifact_sha256": "f" * 64,
        }
        attach(basis, "basis_id", "basis_digest", "network-patch-basis-")
        attach(
            forged["actions"][0],
            "action_id",
            "action_digest",
            "network-patch-action-",
        )
        attach(
            forged,
            "proposal_id",
            "proposal_digest",
            "network-patch-proposal-",
        )
        pack = self.evidence_pack(forged)
        proposal_path = self.write("forged-proposal.json", forged)
        pack_path = self.write("forged-pack.json", pack)

        self.gap_patcher.stop()
        try:
            rejected = self.patch(
                [
                    "validate-patch",
                    "--proposal",
                    str(proposal_path),
                    "--evidence-pack",
                    str(pack_path),
                ]
            )
        finally:
            self.gap_patcher.start()
        self.assertEqual(rejected[0], 1)
        self.assertRegex(
            rejected[2],
            "strict upstream evidence reopening failed|does not bind a reviewed report claim",
        )

        missing = json.loads(json.dumps(pack))
        missing["artifacts"]["source_artifact"] = {
            "path": str(self.root / "does-not-exist.txt"),
            "sha256": "0" * 64,
        }
        attach(
            missing,
            "pack_id",
            "pack_digest",
            "network-patch-evidence-pack-",
        )
        missing_path = self.write("missing-pack.json", missing)
        rejected_missing = self.patch(
            [
                "validate-patch",
                "--proposal",
                str(proposal_path),
                "--evidence-pack",
                str(missing_path),
            ]
        )
        self.assertEqual(rejected_missing[0], 1)
        self.assertRegex(
            rejected_missing[2],
            "unavailable|does not bind a reviewed report claim",
        )

    def test_evidence_pack_upstream_uses_private_stable_snapshot(self):
        proposal, _, _ = self.contracts()
        pack = self.evidence_pack(proposal)
        original_source = Path(pack["artifacts"]["source_artifact"]["path"])
        declared = pack["artifacts"]["source_artifact"]["sha256"]
        proposal_path = self.write("snapshot-proposal.json", proposal)
        pack_path = self.write("snapshot-pack.json", pack)
        observed_stage_paths = []

        def drift_original_then_return(*args, **kwargs):
            observed_stage_paths.append(Path(kwargs["source_artifact_path"]))
            original_source.write_text("concurrent drift", encoding="utf-8")
            return proposal

        self.gap_stub.propose_patch.side_effect = drift_original_then_return
        validated = self.patch(
            [
                "validate-patch",
                "--proposal",
                str(proposal_path),
                "--evidence-pack",
                str(pack_path),
            ]
        )
        self.assertEqual(validated[0], 1)
        self.assertIn("drifted during regeneration", validated[2])
        self.assertEqual(len(observed_stage_paths), 1)
        self.assertNotEqual(observed_stage_paths[0], original_source)
        self.assertNotEqual(
            hashlib.sha256(original_source.read_bytes()).hexdigest(), declared
        )
        self.gap_stub.propose_patch.side_effect = lambda *args, **kwargs: (
            self._active_proposal
        )

    def test_operation_smuggling_and_cross_basis_identity_are_rejected(self):
        proposal, plan, acceptance = self.contracts()
        basis = proposal["actions"][0]["reviewed_evidence"]
        smuggled = json.loads(json.dumps(acceptance))
        smuggled["decisions"][0]["operations"].append(
            self.operation(
                "add-claim",
                {
                    "claim_id": "unrelated-injected-claim",
                    "claim_text": "unrelated",
                    "entity_id": None,
                    "impact": "low",
                    "coverage_dimensions": [],
                    "benchmark_profiles": [],
                    "supersedes": None,
                },
                basis,
            )
        )
        attach(
            smuggled,
            "acceptance_id",
            "acceptance_digest",
            "network-patch-acceptance-",
        )
        with self.assertRaisesRegex(
            ValueError,
            "does not match its basis|relation operation sequence|canonical semantic mapping|payload fields invalid",
        ):
            PATCH.validate_acceptance(smuggled, proposal, plan, self.current_ref())

        crossed = json.loads(json.dumps(acceptance))
        evidence = crossed["decisions"][0]["operations"][0]
        evidence["payload"]["source_id"] = "source-foreign"
        attach(
            evidence,
            "operation_id",
            "operation_digest",
            "network-operation-",
        )
        attach(
            crossed,
            "acceptance_id",
            "acceptance_digest",
            "network-patch-acceptance-",
        )
        with self.assertRaisesRegex(
            ValueError, "does not match its basis|payload fields invalid"
        ):
            PATCH.validate_acceptance(crossed, proposal, plan, self.current_ref())

    def test_prepare_output_is_exclusive_confined_and_cannot_clobber_live_state(self):
        proposal, _, _ = self.contracts()
        pack = self.evidence_pack(proposal)
        proposal_path = self.write("output-proposal.json", proposal)
        pack_path = self.write("output-pack.json", pack)
        network_state = self.root / KN.NETWORK_ROOT / self.network_id / "network.json"
        before = (
            network_state.stat().st_ino,
            hashlib.sha256(network_state.read_bytes()).hexdigest(),
        )
        common = [
            "prepare-patch",
            "--proposal",
            str(proposal_path),
            "--evidence-pack",
            str(pack_path),
            "--output",
        ]
        clobber = self.patch([*common, str(network_state)])
        self.assertEqual(clobber[0], 1)

        plan_root = self.root / "patch-plans"
        symlink = plan_root / "state-link.json"
        symlink.symlink_to(network_state)
        self.assertEqual(self.patch([*common, str(symlink)])[0], 1)
        hardlink = plan_root / "state-hardlink.json"
        os.link(network_state, hardlink)
        self.assertEqual(self.patch([*common, str(hardlink)])[0], 1)

        output = plan_root / "exclusive-plan.json"
        created = self.patch([*common, str(output)])
        self.assertEqual(created[0], 0, created[2])
        self.assertEqual(self.patch([*common, str(output)])[0], 1)
        after = (
            network_state.stat().st_ino,
            hashlib.sha256(network_state.read_bytes()).hexdigest(),
        )
        self.assertEqual(after, before)

    def test_reject_defer_only_advances_audit_snapshot_and_requires_rebase(self):
        proposal, plan, acceptance = self.contracts()
        acceptance["decisions"][0]["decision"] = "defer"
        acceptance["decisions"][0]["rationale"] = "Await another review."
        acceptance["decisions"][0]["operations"] = []
        attach(
            acceptance,
            "acceptance_id",
            "acceptance_digest",
            "network-patch-acceptance-",
        )
        pack = self.evidence_pack(proposal)
        proposal_path = self.write("defer-proposal.json", proposal)
        plan_path = self.write("defer-plan.json", plan)
        acceptance_path = self.write("defer-acceptance.json", acceptance)
        pack_path = self.write("defer-pack.json", pack)
        paths = KN._safe_paths(str(self.root), self.network_id)
        _, before_records = KN._load_state(paths)
        scientific_before = {
            name: json.loads(json.dumps(before_records[name]))
            for name in (
                "sources",
                "entities",
                "claims",
                "evidence",
                "relations",
                "gaps",
            )
        }
        before_ref = self.current_ref()
        applied = self.patch(
            [
                "apply-patch",
                "--proposal",
                str(proposal_path),
                "--evidence-pack",
                str(pack_path),
                "--plan",
                str(plan_path),
                "--acceptance",
                str(acceptance_path),
            ]
        )
        self.assertEqual(applied[0], 0, applied[2])
        _, after_records = KN._load_state(paths)
        for name, rows in scientific_before.items():
            self.assertEqual(after_records[name], rows)
        self.assertNotEqual(self.current_ref(), before_ref)
        stale = self.patch(
            [
                "validate-patch",
                "--proposal",
                str(proposal_path),
                "--evidence-pack",
                str(pack_path),
            ]
        )
        self.assertEqual(stale[0], 1)
        self.assertIn("stale", stale[2])

    def test_patch_decision_event_is_closed_and_content_addressed(self):
        proposal, plan, acceptance = self.contracts()
        pack = self.evidence_pack(proposal)
        proposal_path = self.write("event-proposal.json", proposal)
        plan_path = self.write("event-plan.json", plan)
        acceptance_path = self.write("event-acceptance.json", acceptance)
        pack_path = self.write("event-pack.json", pack)
        applied = self.patch(
            [
                "apply-patch",
                "--proposal",
                str(proposal_path),
                "--evidence-pack",
                str(pack_path),
                "--plan",
                str(plan_path),
                "--acceptance",
                str(acceptance_path),
            ]
        )
        self.assertEqual(applied[0], 0, applied[2])
        events_path = self.root / KN.NETWORK_ROOT / self.network_id / "events.jsonl"
        original = events_path.read_text(encoding="utf-8")
        rows = [json.loads(line) for line in original.splitlines() if line]
        patch_event = next(
            item for item in rows if item.get("event_type") == "patch_decision"
        )
        patch_event["unknown_bypass"] = True
        events_path.write_text(
            "".join(json.dumps(item, sort_keys=True) + "\n" for item in rows),
            encoding="utf-8",
        )
        malformed = self.kn(["validate"])
        self.assertEqual(malformed[0], 1)
        self.assertIn("patch_decision fields invalid", malformed[1])

        rows = [json.loads(line) for line in original.splitlines() if line]
        patch_event = next(
            item for item in rows if item.get("event_type") == "patch_decision"
        )
        patch_event["decisions"][0]["action_digest"] = "0" * 64
        events_path.write_text(
            "".join(json.dumps(item, sort_keys=True) + "\n" for item in rows),
            encoding="utf-8",
        )
        tampered = self.kn(["validate"])
        self.assertEqual(tampered[0], 1)
        self.assertIn("event_digest mismatch", tampered[1])
        self.assertIn("action ID/digest mismatch", tampered[1])

    def test_apply_replace_failure_rolls_back_every_live_file(self):
        proposal, plan, acceptance = self.contracts()
        pack = self.evidence_pack(proposal)
        proposal_path = self.write("rollback-proposal.json", proposal)
        plan_path = self.write("rollback-plan.json", plan)
        acceptance_path = self.write("rollback-acceptance.json", acceptance)
        pack_path = self.write("rollback-pack.json", pack)
        network_dir = self.root / KN.NETWORK_ROOT / self.network_id
        live_files = [network_dir / "network.json"] + [
            network_dir / f"{name}.jsonl" for name in KN.LEDGER_NAMES
        ]
        before = {path.name: path.read_bytes() for path in live_files}
        original_replace = os.replace
        call_count = 0
        live_replace_count = 0
        live_targets = set(live_files)

        def fail_after_first_live_replace(source, target):
            nonlocal call_count, live_replace_count
            call_count += 1
            if Path(target) in live_targets:
                live_replace_count += 1
                if live_replace_count == 2:
                    raise OSError("injected transaction replace failure")
            return original_replace(source, target)

        with mock.patch.object(
            KN.os, "replace", side_effect=fail_after_first_live_replace
        ):
            failed = self.patch(
                [
                    "apply-patch",
                    "--proposal",
                    str(proposal_path),
                    "--evidence-pack",
                    str(pack_path),
                    "--plan",
                    str(plan_path),
                    "--acceptance",
                    str(acceptance_path),
                ]
            )
        self.assertEqual(failed[0], 1)
        self.assertIn("injected transaction replace failure", failed[2])
        self.assertGreaterEqual(call_count, 4)
        self.assertGreaterEqual(live_replace_count, 3)
        after = {path.name: path.read_bytes() for path in live_files}
        self.assertEqual(after, before)
        self.assertFalse((network_dir / ".transaction.json").exists())
        validated = self.kn(["validate"])
        self.assertEqual(validated[0], 0, validated[2])

    def test_apply_base_exception_rolls_back_bytes_inodes_and_temps(self):
        class CommitAbort(BaseException):
            pass

        proposal, plan, acceptance = self.contracts()
        pack = self.evidence_pack(proposal)
        proposal_path = self.write("base-rollback-proposal.json", proposal)
        plan_path = self.write("base-rollback-plan.json", plan)
        acceptance_path = self.write("base-rollback-acceptance.json", acceptance)
        pack_path = self.write("base-rollback-pack.json", pack)
        network_dir = self.root / KN.NETWORK_ROOT / self.network_id
        live_files = [network_dir / "network.json"] + [
            network_dir / f"{name}.jsonl" for name in KN.LEDGER_NAMES
        ]

        for injected in (
            KeyboardInterrupt("injected keyboard interrupt"),
            SystemExit("injected system exit"),
            CommitAbort("injected custom abort"),
        ):
            with self.subTest(exception=type(injected).__name__):
                before = {
                    path: (path.stat().st_ino, path.read_bytes()) for path in live_files
                }
                original_replace = os.replace
                live_replace_count = 0
                live_targets = set(live_files)

                def fail_second_live_replace(source, target):
                    nonlocal live_replace_count
                    if Path(target) in live_targets:
                        live_replace_count += 1
                        if live_replace_count == 2:
                            raise injected
                    return original_replace(source, target)

                with mock.patch.object(
                    KN.os, "replace", side_effect=fail_second_live_replace
                ):
                    with self.assertRaises(type(injected)) as caught:
                        self.patch(
                            [
                                "apply-patch",
                                "--proposal",
                                str(proposal_path),
                                "--evidence-pack",
                                str(pack_path),
                                "--plan",
                                str(plan_path),
                                "--acceptance",
                                str(acceptance_path),
                            ]
                        )
                self.assertIs(caught.exception, injected)
                self.assertGreaterEqual(live_replace_count, 3)
                for path, expected in before.items():
                    self.assertEqual((path.stat().st_ino, path.read_bytes()), expected)
                self.assertFalse((network_dir / ".transaction.json").exists())
                self.assertFalse(list(network_dir.glob(".*.stage.*")))
                self.assertFalse(list(network_dir.glob(".*.restore.*")))

        validated = self.kn(["validate"])
        self.assertEqual(validated[0], 0, validated[2])

    def test_v1_is_audit_only_and_cannot_directly_apply(self):
        proposal = {
            "schema": "NetworkPatchProposal/v1",
            "proposal_id": "NPP-audit-only",
            "network_ref": self.current_ref(),
            "generated_at": "2026-08-05T00:30:00Z",
            "basis_gap_ids": [],
            "proposal_only": True,
            "novelty_claimed": False,
            "nodes": [],
            "relations": [],
            "evidence": [],
            "review_gate": "pending_research_knowledge_network_validation",
        }
        evidence_pack = self.evidence_pack(proposal)
        path = self.write("v1.json", proposal)
        pack_path = self.write("v1-pack.json", evidence_pack)
        validated = self.patch(
            [
                "validate-patch",
                "--proposal",
                str(path),
                "--evidence-pack",
                str(pack_path),
            ]
        )
        self.assertEqual(validated[0], 0, validated[2])
        self.assertFalse(json.loads(validated[1])["apply_eligible"])
        prepared = self.patch(
            [
                "prepare-patch",
                "--proposal",
                str(path),
                "--evidence-pack",
                str(pack_path),
                "--output",
                str(self.root / "patch-plans" / "v1-plan.json"),
            ]
        )
        self.assertEqual(prepared[0], 1)
        direct = self.patch(["apply-patch", "--proposal", str(path)])
        self.assertEqual(direct[0], 2)

    def test_relation_requires_lossless_target_claim_and_never_defaults_impact(self):
        proposal = self.proposal()
        relation = proposal["actions"][0]
        self.assertEqual(relation["target_claim"]["impact"], "low")
        self.assertNotEqual(
            relation["target_claim"]["claim_text"],
            relation["target_signature"]["signature"],
        )
        relation = PATCH.without(relation, "action_id", "action_digest")
        relation.pop("target_claim")
        proposal["actions"][0] = attach(
            relation, "action_id", "action_digest", "network-patch-action-"
        )
        proposal = attach(
            PATCH.without(proposal, "proposal_id", "proposal_digest"),
            "proposal_id",
            "proposal_digest",
            "network-patch-proposal-",
        )
        with self.assertRaisesRegex(ValueError, "target_claim"):
            PATCH.validate_proposal_v2(proposal, self.current_ref())

    def test_v3_requires_two_source_collection_and_current_origin_gap(self):
        proposal, live_network = self.proposal_v3()
        validated = PATCH.validate_proposal_v3(
            copy.deepcopy(proposal), self.current_ref(), live_network
        )
        self.assertEqual(validated, proposal)
        self.assertEqual(
            [row["source_id"] for row in validated["actions"][0]["reading_group_refs"]],
            ["source-01", "source-02"],
        )

        missing_consumption = copy.deepcopy(proposal)
        missing_consumption.pop("consumption_ref")
        missing_consumption = attach(
            PATCH.without(missing_consumption, "proposal_id", "proposal_digest"),
            "proposal_id",
            "proposal_digest",
            "network-patch-proposal-",
        )
        with self.assertRaisesRegex(ValueError, "consumption_ref"):
            PATCH.validate_proposal_v3(
                missing_consumption, self.current_ref(), live_network
            )

        wrong_authority_identity = copy.deepcopy(proposal)
        wrong_authority_identity["consumption_ref"]["authority_id"] = (
            "reviewed-collection-consumption-authority-" + "0" * 16
        )
        wrong_authority_identity = attach(
            PATCH.without(wrong_authority_identity, "proposal_id", "proposal_digest"),
            "proposal_id",
            "proposal_digest",
            "network-patch-proposal-",
        )
        with self.assertRaisesRegex(ValueError, "authority_id"):
            PATCH.validate_proposal_v3(
                wrong_authority_identity, self.current_ref(), live_network
            )

        malformed_raw_pin = copy.deepcopy(proposal)
        malformed_raw_pin["consumption_ref"]["authority_file_sha256"] = "A" * 64
        malformed_raw_pin = attach(
            PATCH.without(malformed_raw_pin, "proposal_id", "proposal_digest"),
            "proposal_id",
            "proposal_digest",
            "network-patch-proposal-",
        )
        with self.assertRaisesRegex(ValueError, "authority_file_sha256"):
            PATCH.validate_proposal_v3(
                malformed_raw_pin, self.current_ref(), live_network
            )

        repeated_across_actions = copy.deepcopy(proposal)
        second_action = PATCH.without(
            copy.deepcopy(proposal["actions"][0]), "action_id", "action_digest"
        )
        second_action["hypothesis_id"] = "KGH-v3-second-subject"
        second_action["subject_ref"] = {
            "subject_id": "reviewed-gap-claim-subject-" + "e" * 16,
            "subject_digest": "e" * 64,
        }
        second_target = PATCH.without(
            second_action["target_claim"], "claim_id", "target_claim_digest"
        )
        second_target["subject_ref"] = second_action["subject_ref"]
        second_action["target_claim"] = attach(
            second_target,
            "claim_id",
            "target_claim_digest",
            "claim-target-",
        )
        repeated_across_actions["actions"].append(
            attach(
                second_action,
                "action_id",
                "action_digest",
                "network-patch-action-",
            )
        )
        repeated_across_actions = attach(
            PATCH.without(repeated_across_actions, "proposal_id", "proposal_digest"),
            "proposal_id",
            "proposal_digest",
            "network-patch-proposal-",
        )
        with self.assertRaisesRegex(ValueError, "proposal evidence IDs"):
            PATCH.validate_proposal_v3(
                repeated_across_actions, self.current_ref(), live_network
            )

        stale = copy.deepcopy(proposal)
        stale["actions"][0]["origin_gap_refs"][0]["sha256"] = "0" * 64
        stale["actions"][0]["target_claim"]["origin_gap_refs"] = copy.deepcopy(
            stale["actions"][0]["origin_gap_refs"]
        )
        stale["actions"][0]["target_claim"] = attach(
            PATCH.without(
                stale["actions"][0]["target_claim"],
                "claim_id",
                "target_claim_digest",
            ),
            "claim_id",
            "target_claim_digest",
            "claim-target-",
        )
        stale["actions"][0] = attach(
            PATCH.without(stale["actions"][0], "action_id", "action_digest"),
            "action_id",
            "action_digest",
            "network-patch-action-",
        )
        stale = attach(
            PATCH.without(stale, "proposal_id", "proposal_digest"),
            "proposal_id",
            "proposal_digest",
            "network-patch-proposal-",
        )
        with self.assertRaisesRegex(ValueError, "current gap record"):
            PATCH.validate_proposal_v3(stale, self.current_ref(), live_network)

        collapsed = copy.deepcopy(proposal)
        second = collapsed["actions"][0]["reviewed_evidence"][1]
        second["source_id"] = "source-01"
        second = attach(
            PATCH.without(second, "basis_id", "basis_digest"),
            "basis_id",
            "basis_digest",
            "network-patch-basis-",
        )
        collapsed["actions"][0]["reviewed_evidence"][1] = second
        collapsed["actions"][0]["reading_group_refs"][1]["source_id"] = "source-01"
        with self.assertRaisesRegex(ValueError, "source_id"):
            PATCH.validate_proposal_v3(collapsed, self.current_ref(), live_network)

        colliding_evidence = copy.deepcopy(proposal)
        second = colliding_evidence["actions"][0]["reviewed_evidence"][1]
        second["evidence_id"] = colliding_evidence["actions"][0]["reviewed_evidence"][
            0
        ]["evidence_id"]
        colliding_evidence["actions"][0]["reviewed_evidence"][1] = attach(
            PATCH.without(second, "basis_id", "basis_digest"),
            "basis_id",
            "basis_digest",
            "network-patch-basis-",
        )
        with self.assertRaisesRegex(ValueError, "evidence IDs"):
            PATCH.validate_proposal_v3(
                colliding_evidence, self.current_ref(), live_network
            )

        injected = copy.deepcopy(proposal)
        target = PATCH.without(
            injected["actions"][0]["target_claim"],
            "claim_id",
            "target_claim_digest",
        )
        target["coverage_dimensions"] = ["unbound-injected-dimension"]
        target["scope"]["coverage_dimensions"] = ["unbound-injected-dimension"]
        target["scope_digest"] = PATCH.digest_json(target["scope"])
        injected["actions"][0]["target_claim"] = attach(
            target,
            "claim_id",
            "target_claim_digest",
            "claim-target-",
        )
        injected["actions"][0] = attach(
            PATCH.without(injected["actions"][0], "action_id", "action_digest"),
            "action_id",
            "action_digest",
            "network-patch-action-",
        )
        injected = attach(
            PATCH.without(injected, "proposal_id", "proposal_digest"),
            "proposal_id",
            "proposal_digest",
            "network-patch-proposal-",
        )
        with self.assertRaisesRegex(ValueError, "injects unrequired"):
            PATCH.validate_proposal_v3(injected, self.current_ref(), live_network)

    def test_v4_existing_claim_extension_has_no_add_claim_operation(self):
        proposal, live_network = self.proposal_v4_extension()
        self.assertEqual(
            PATCH.validate_proposal_v4(
                copy.deepcopy(proposal), self.current_ref(), live_network
            ),
            proposal,
        )
        plan = PATCH.create_plan(
            proposal,
            self.current_ref(),
            prepared_at="2026-08-12T00:10:00Z",
        )
        self.assertEqual(
            plan["actions"][0]["allowed_operation_types"],
            ["add-evidence", "add-relation", "transition-gap"],
        )
        acceptance = self.extension_acceptance(proposal, plan)
        action = proposal["actions"][0]
        validated = self._real_validate_acceptance(
            acceptance, proposal, plan, self.current_ref()
        )
        operation_types = [
            operation["operation_type"]
            for operation in validated["decisions"][0]["operations"]
        ]
        basis_count = len(proposal["actions"][0]["reviewed_evidence"])
        origin_count = len(proposal["actions"][0]["origin_gap_refs"])
        self.assertEqual(
            operation_types,
            ["add-evidence"] * basis_count
            + ["add-relation"] * basis_count
            + ["transition-gap"] * origin_count,
        )
        self.assertNotIn("add-claim", operation_types)

        semantics = action["existing_claim_ref"]["claim_semantics"]
        injected = copy.deepcopy(acceptance)
        injected["decisions"][0]["operations"].insert(
            0,
            self.operation(
                "add-claim",
                {
                    "claim_id": action["existing_claim_ref"]["claim_id"],
                    "claim_text": semantics["claim_text"],
                    "entity_id": semantics["entity_id"],
                    "impact": semantics["impact"],
                    "scope_statement": semantics["scope_statement"],
                    "assumptions": semantics["assumptions"],
                    "conditions": semantics["conditions"],
                    "units": semantics["units"],
                    "exclusions": semantics["exclusions"],
                    "defeaters": semantics["defeaters"],
                    "coverage_dimensions": semantics["coverage_dimensions"],
                    "benchmark_profiles": semantics["benchmark_profiles"],
                    "supersedes": semantics["supersedes"],
                },
                action["reviewed_evidence"],
            ),
        )
        injected = attach(
            PATCH.without(injected, "acceptance_id", "acceptance_digest"),
            "acceptance_id",
            "acceptance_digest",
            "network-patch-acceptance-",
        )
        with self.assertRaisesRegex(ValueError, "requires a closed target_node"):
            self._real_validate_acceptance(injected, proposal, plan, self.current_ref())

        wrong_resolution_source = copy.deepcopy(acceptance)
        transition_index = next(
            index
            for index, operation in enumerate(
                wrong_resolution_source["decisions"][0]["operations"]
            )
            if operation["operation_type"] == "transition-gap"
        )
        transition = PATCH.without(
            wrong_resolution_source["decisions"][0]["operations"][transition_index],
            "operation_id",
            "operation_digest",
        )
        transition["payload"]["resolution_source"] = proposal["proposal_id"]
        wrong_resolution_source["decisions"][0]["operations"][transition_index] = (
            attach(
                transition,
                "operation_id",
                "operation_digest",
                "network-operation-",
            )
        )
        wrong_resolution_source = attach(
            PATCH.without(
                wrong_resolution_source, "acceptance_id", "acceptance_digest"
            ),
            "acceptance_id",
            "acceptance_digest",
            "network-patch-acceptance-",
        )
        with self.assertRaisesRegex(ValueError, "resolution_source"):
            self._real_validate_acceptance(
                wrong_resolution_source, proposal, plan, self.current_ref()
            )

    def test_v4_existing_claim_ref_rejects_stale_or_rewritten_claim_state(self):
        proposal, live_network = self.proposal_v4_extension()
        stale = copy.deepcopy(proposal)
        stale["actions"][0]["existing_claim_ref"]["claim_record_ref"]["sha256"] = (
            "0" * 64
        )
        stale["actions"][0] = attach(
            PATCH.without(stale["actions"][0], "action_id", "action_digest"),
            "action_id",
            "action_digest",
            "network-patch-action-",
        )
        stale = attach(
            PATCH.without(stale, "proposal_id", "proposal_digest"),
            "proposal_id",
            "proposal_digest",
            "network-patch-proposal-",
        )
        with self.assertRaisesRegex(ValueError, "claim_record_ref"):
            PATCH.validate_proposal_v4(stale, self.current_ref(), live_network)

        rewritten = copy.deepcopy(proposal)
        semantics = rewritten["actions"][0]["existing_claim_ref"]["claim_semantics"]
        semantics["claim_text"] = "Caller-authored replacement semantics."
        rewritten["actions"][0]["existing_claim_ref"]["claim_semantic_digest"] = (
            PATCH.digest_json(semantics)
        )
        rewritten["actions"][0] = attach(
            PATCH.without(rewritten["actions"][0], "action_id", "action_digest"),
            "action_id",
            "action_digest",
            "network-patch-action-",
        )
        rewritten = attach(
            PATCH.without(rewritten, "proposal_id", "proposal_digest"),
            "proposal_id",
            "proposal_digest",
            "network-patch-proposal-",
        )
        with self.assertRaisesRegex(ValueError, "claim_semantics"):
            PATCH.validate_proposal_v4(rewritten, self.current_ref(), live_network)

        wrong_subject = copy.deepcopy(proposal)
        wrong_subject["actions"][0]["subject_ref"]["subject_digest"] = "0" * 64
        wrong_subject["actions"][0] = attach(
            PATCH.without(wrong_subject["actions"][0], "action_id", "action_digest"),
            "action_id",
            "action_digest",
            "network-patch-action-",
        )
        wrong_subject = attach(
            PATCH.without(wrong_subject, "proposal_id", "proposal_digest"),
            "proposal_id",
            "proposal_digest",
            "network-patch-proposal-",
        )
        with self.assertRaisesRegex(ValueError, "subject_ref"):
            PATCH.validate_proposal_v4(wrong_subject, self.current_ref(), live_network)

    def test_v4_existing_claim_ref_requires_one_live_active_row(self):
        proposal, live_network = self.proposal_v4_extension()
        duplicate = copy.deepcopy(live_network)
        duplicate["claims"].append(
            copy.deepcopy(
                next(
                    row
                    for row in duplicate["claims"]
                    if row["claim_id"] == "claim-existing-v4"
                )
            )
        )
        with self.assertRaisesRegex(ValueError, "exactly one live claim row"):
            PATCH.validate_proposal_v4(proposal, self.current_ref(), duplicate)

        missing = copy.deepcopy(live_network)
        missing["claims"] = [
            row for row in missing["claims"] if row["claim_id"] != "claim-existing-v4"
        ]
        with self.assertRaisesRegex(ValueError, "exactly one live claim row"):
            PATCH.validate_proposal_v4(proposal, self.current_ref(), missing)

    def test_v4_action_union_and_origin_claim_route_fail_closed(self):
        proposal, live_network = self.proposal_v4_extension()
        union = copy.deepcopy(proposal)
        union["actions"][0]["target_claim"] = {}
        union["actions"][0] = attach(
            PATCH.without(union["actions"][0], "action_id", "action_digest"),
            "action_id",
            "action_digest",
            "network-patch-action-",
        )
        union = attach(
            PATCH.without(union, "proposal_id", "proposal_digest"),
            "proposal_id",
            "proposal_digest",
            "network-patch-proposal-",
        )
        with self.assertRaisesRegex(ValueError, "fields invalid"):
            PATCH.validate_proposal_v4(union, self.current_ref(), live_network)

        another_claim_gap = next(
            gap
            for gap in live_network["gaps"]
            if gap.get("claim_id") == "claim-01" and gap["status"] == "open"
        )
        multiple = copy.deepcopy(proposal)
        multiple["actions"][0]["origin_gap_refs"][1] = {
            "gap_id": another_claim_gap["gap_id"],
            **another_claim_gap["record_ref"],
        }
        multiple["actions"][0] = attach(
            PATCH.without(multiple["actions"][0], "action_id", "action_digest"),
            "action_id",
            "action_digest",
            "network-patch-action-",
        )
        multiple = attach(
            PATCH.without(multiple, "proposal_id", "proposal_digest"),
            "proposal_id",
            "proposal_digest",
            "network-patch-proposal-",
        )
        with self.assertRaisesRegex(ValueError, "multiple existing-claim routes"):
            PATCH.validate_proposal_v4(multiple, self.current_ref(), live_network)

        code, _, error = self.kn(
            [
                "record-gap",
                "--gap-id",
                "gap-v4-claimless",
                "--gap-type",
                "explicit",
                "--impact",
                "low",
                "--status",
                "open",
                "--source",
                "manual-test",
                "--description",
                "A claimless gap cannot share an existing-claim action.",
            ]
        )
        self.assertEqual(code, 0, error)
        paths = KN._safe_paths(str(self.root), self.network_id)
        state, records = KN._load_state(paths)
        current_network = KN._knowledge_network_export(paths, state, records)
        claimless = next(
            gap
            for gap in current_network["gaps"]
            if gap["gap_id"] == "gap-v4-claimless"
        )
        mixed = copy.deepcopy(proposal)
        mixed["network_ref"] = self.current_ref()
        mixed["actions"][0]["origin_gap_refs"][1] = {
            "gap_id": claimless["gap_id"],
            **claimless["record_ref"],
        }
        mixed["actions"][0] = attach(
            PATCH.without(mixed["actions"][0], "action_id", "action_digest"),
            "action_id",
            "action_digest",
            "network-patch-action-",
        )
        mixed = attach(
            PATCH.without(mixed, "proposal_id", "proposal_digest"),
            "proposal_id",
            "proposal_digest",
            "network-patch-proposal-",
        )
        with self.assertRaisesRegex(ValueError, "mix claimless"):
            PATCH.validate_proposal_v4(mixed, self.current_ref(), current_network)

    def test_v4_rejects_a_claim_superseded_after_proposal_generation(self):
        proposal, _ = self.proposal_v4_extension()
        code, _, error = self.kn(
            [
                "add-claim",
                "--claim-id",
                "claim-existing-v4-successor",
                "--claim-text",
                "A successor claim with separately reviewed semantics.",
                "--impact",
                "high",
                "--scope-statement",
                "Successor scope.",
                "--defeater",
                "scope mismatch",
                "--supersedes",
                "claim-existing-v4",
            ]
        )
        self.assertEqual(code, 0, error)
        paths = KN._safe_paths(str(self.root), self.network_id)
        state, records = KN._load_state(paths)
        live_network = KN._knowledge_network_export(paths, state, records)
        proposal["network_ref"] = self.current_ref()
        proposal = attach(
            PATCH.without(proposal, "proposal_id", "proposal_digest"),
            "proposal_id",
            "proposal_digest",
            "network-patch-proposal-",
        )
        with self.assertRaisesRegex(ValueError, "superseded claim"):
            PATCH.validate_proposal_v4(proposal, self.current_ref(), live_network)

    def test_v4_preserves_the_new_claim_route_for_claimless_origin_gaps(self):
        proposal, _ = self.proposal_v3()
        code, _, error = self.kn(
            [
                "record-gap",
                "--gap-id",
                "gap-v4-second-claimless",
                "--gap-type",
                "explicit",
                "--impact",
                "low",
                "--status",
                "open",
                "--source",
                "manual-test",
                "--description",
                "A second claimless origin for the new-claim route.",
            ]
        )
        self.assertEqual(code, 0, error)
        paths = KN._safe_paths(str(self.root), self.network_id)
        state, records = KN._load_state(paths)
        live_network = KN._knowledge_network_export(paths, state, records)
        claimless = [
            gap
            for gap in live_network["gaps"]
            if gap.get("claim_id") is None and gap["status"] == "open"
        ]
        self.assertGreaterEqual(len(claimless), 2)
        origin_refs = [
            {"gap_id": gap["gap_id"], **gap["record_ref"]} for gap in claimless[:2]
        ]
        proposal["schema"] = "NetworkPatchProposal/v4"
        proposal["schema_version"] = "4.0"
        proposal["network_ref"] = self.current_ref()
        action = proposal["actions"][0]
        action["origin_gap_refs"] = origin_refs
        target = PATCH.without(
            action["target_claim"], "claim_id", "target_claim_digest"
        )
        target["origin_gap_refs"] = copy.deepcopy(origin_refs)
        action["target_claim"] = attach(
            target,
            "claim_id",
            "target_claim_digest",
            "claim-target-",
        )
        proposal["actions"][0] = attach(
            PATCH.without(action, "action_id", "action_digest"),
            "action_id",
            "action_digest",
            "network-patch-action-",
        )
        proposal = attach(
            PATCH.without(proposal, "proposal_id", "proposal_digest"),
            "proposal_id",
            "proposal_digest",
            "network-patch-proposal-",
        )
        self.assertEqual(
            PATCH.validate_proposal_v4(
                copy.deepcopy(proposal), self.current_ref(), live_network
            ),
            proposal,
        )

    def test_v4_apply_rolls_back_when_a_resolved_derived_predicate_still_holds(self):
        proposal, _ = self.proposal_v4_extension()
        plan = PATCH.create_plan(
            proposal,
            self.current_ref(),
            prepared_at="2026-08-12T00:10:00Z",
        )
        acceptance = self.extension_acceptance(proposal, plan)
        action = proposal["actions"][0]
        basis_by_id = {
            basis["basis_id"]: basis for basis in action["reviewed_evidence"]
        }
        operations = acceptance["decisions"][0]["operations"]
        for index, operation in enumerate(operations):
            operation = PATCH.without(operation, "operation_id", "operation_digest")
            if operation["operation_type"] == "add-evidence":
                operation["payload"]["polarity"] = "qualifies"
            elif operation["operation_type"] == "add-relation":
                basis = basis_by_id[operation["basis_refs"][0]["basis_id"]]
                operation["payload"]["relation_type"] = "qualifies"
                operation["payload"]["relation_id"] = PATCH.relation_operation_id(
                    action, basis, "qualifies"
                )
            operations[index] = attach(
                operation,
                "operation_id",
                "operation_digest",
                "network-operation-",
            )
        acceptance = attach(
            PATCH.without(acceptance, "acceptance_id", "acceptance_digest"),
            "acceptance_id",
            "acceptance_digest",
            "network-patch-acceptance-",
        )
        gate = copy.deepcopy(self.fake_gate)
        gate["binding"] = {
            "relation_bindings": [
                {
                    "action_id": action["action_id"],
                    "basis_id": basis["basis_id"],
                    "allowed_relation": "qualifies",
                    "independence_group": basis["source_id"],
                }
                for basis in action["reviewed_evidence"]
            ]
        }
        proposal_path = self.write("proposal-v4-derived.json", proposal)
        plan_path = self.write("plan-v4-derived.json", plan)
        acceptance_path = self.write("acceptance-v4-derived.json", acceptance)
        pack_path = self.write("pack-v4-derived.json", {})
        before = self.current_ref()

        def validate_with_qualified_gate(value, bound_proposal, bound_plan, ref, **_):
            return self._real_validate_acceptance(
                value,
                bound_proposal,
                bound_plan,
                ref,
                appraisal_gate=gate,
            )

        with (
            mock.patch.object(PATCH, "validate_evidence_pack", return_value={}),
            mock.patch.object(
                PATCH, "_load_optional_appraisal_gate", return_value=(gate, [])
            ),
            mock.patch.object(
                PATCH, "validate_acceptance", side_effect=validate_with_qualified_gate
            ),
        ):
            applied = self.patch(
                [
                    "apply-patch",
                    "--proposal",
                    str(proposal_path),
                    "--evidence-pack",
                    str(pack_path),
                    "--plan",
                    str(plan_path),
                    "--acceptance",
                    str(acceptance_path),
                ]
            )
        self.assertEqual(applied[0], 1, applied[1])
        self.assertRegex(applied[2], "derived gap postcondition")
        self.assertEqual(self.current_ref(), before)

    def test_v4_existing_claim_extension_applies_atomically_without_a_new_claim(self):
        proposal, _ = self.proposal_v4_extension()
        plan = PATCH.create_plan(
            proposal,
            self.current_ref(),
            prepared_at="2026-08-12T00:10:00Z",
        )
        acceptance = self.extension_acceptance(proposal, plan)
        proposal_path = self.write("proposal-v4-apply.json", proposal)
        plan_path = self.write("plan-v4-apply.json", plan)
        acceptance_path = self.write("acceptance-v4-apply.json", acceptance)
        pack_path = self.write("pack-v4-apply.json", {})
        paths = KN._safe_paths(str(self.root), self.network_id)
        _, before_records = KN._load_state(paths)
        before_claim_count = len(before_records["claims"])
        with mock.patch.object(PATCH, "validate_evidence_pack", return_value={}):
            applied = self.patch(
                [
                    "apply-patch",
                    "--proposal",
                    str(proposal_path),
                    "--evidence-pack",
                    str(pack_path),
                    "--plan",
                    str(plan_path),
                    "--acceptance",
                    str(acceptance_path),
                ]
            )
        self.assertEqual(applied[0], 0, applied[2])
        _, after_records = KN._load_state(paths)
        self.assertEqual(len(after_records["claims"]), before_claim_count)
        action = proposal["actions"][0]
        self.assertEqual(
            [row["evidence_id"] for row in after_records["evidence"]],
            [basis["evidence_id"] for basis in action["reviewed_evidence"]],
        )
        latest = KN._latest_gaps_by_id(after_records["gaps"])
        self.assertTrue(
            all(
                latest[ref["gap_id"]]["status"] == "resolved"
                for ref in action["origin_gap_refs"]
            )
        )

    def test_v2_high_impact_single_source_is_audit_only(self):
        proposal = self.proposal()
        injected_ref = copy.deepcopy(proposal)
        injected_ref["consumption_ref"] = {
            "schema": "ReviewedEvidenceCollectionConsumption/v1"
        }
        with self.assertRaisesRegex(ValueError, "consumption_ref"):
            PATCH.validate_proposal_v2(injected_ref, self.current_ref())
        action = proposal["actions"][0]
        target = PATCH.without(
            action["target_claim"], "claim_id", "target_claim_digest"
        )
        target["impact"] = "high"
        target = attach(
            target,
            "claim_id",
            "target_claim_digest",
            "claim-target-",
        )
        action = PATCH.without(action, "action_id", "action_digest")
        action["target_claim"] = target
        proposal["actions"][0] = attach(
            action, "action_id", "action_digest", "network-patch-action-"
        )
        proposal = attach(
            PATCH.without(proposal, "proposal_id", "proposal_digest"),
            "proposal_id",
            "proposal_digest",
            "network-patch-proposal-",
        )
        PATCH.validate_proposal_v2(proposal, self.current_ref())
        with self.assertRaisesRegex(ValueError, "two distinct source IDs"):
            PATCH.require_applicable_source_independence(proposal)

    def test_v3_acceptance_requires_all_origin_gap_transitions_atomically(self):
        proposal, _ = self.proposal_v3()
        plan = PATCH.create_plan(
            proposal,
            self.current_ref(),
            prepared_at="2026-08-11T00:10:00Z",
        )
        action = proposal["actions"][0]
        bases = action["reviewed_evidence"]
        operations = [
            self.operation(
                "add-claim",
                {
                    "claim_id": action["target_claim"]["claim_id"],
                    "claim_text": action["target_claim"]["claim_text"],
                    "entity_id": action["target_claim"]["entity_id"],
                    "impact": action["target_claim"]["impact"],
                    "scope_statement": action["target_claim"]["scope"][
                        "scope_statement"
                    ],
                    "assumptions": action["target_claim"]["scope"]["assumptions"],
                    "conditions": action["target_claim"]["scope"]["conditions"],
                    "units": action["target_claim"]["scope"]["units"],
                    "exclusions": action["target_claim"]["scope"]["exclusions"],
                    "defeaters": action["target_claim"]["scope"]["defeaters"],
                    "coverage_dimensions": action["target_claim"][
                        "coverage_dimensions"
                    ],
                    "benchmark_profiles": action["target_claim"]["benchmark_profiles"],
                    "supersedes": None,
                },
                bases,
            )
        ]
        for basis in bases:
            operations.append(
                self.operation(
                    "add-evidence",
                    {
                        "evidence_id": basis["evidence_id"],
                        "claim_id": action["target_claim"]["claim_id"],
                        "source_id": basis["source_id"],
                        "polarity": "supports",
                        "exact_locator": basis["evidence_locator"],
                        "independence_group": basis["source_id"],
                        "summary": action["hypothesis"],
                        "notes": "accepted from NetworkPatchProposal/v3",
                        "supersedes": None,
                    },
                    [basis],
                )
            )
        for basis in bases:
            operations.append(
                self.operation(
                    "add-relation",
                    {
                        "relation_id": PATCH.relation_operation_id(action, basis),
                        "relation_type": "supports",
                        "from_ref": "claim:" + action["target_claim"]["claim_id"],
                        "to_ref": "evidence:" + basis["evidence_id"],
                        "notes": "network-patch-action:" + action["action_digest"],
                        "supersedes": None,
                    },
                    [basis],
                )
            )
        for origin in action["origin_gap_refs"]:
            operations.append(
                self.operation(
                    "transition-gap",
                    {
                        "gap_id": origin["gap_id"],
                        "from_record_id": origin["record_id"],
                        "status": "resolved",
                        "reason": "All reviewed multi-source evidence is admitted.",
                        "evidence_refs": [basis["evidence_id"] for basis in bases],
                        "resolution_source": proposal["proposal_id"],
                    },
                    bases,
                )
            )
        authority = self.authority()
        acceptance = attach(
            {
                "schema": "NetworkPatchAcceptance/v1",
                "schema_version": "1.0",
                "network_ref": proposal["network_ref"],
                "proposal_ref": {
                    "proposal_id": proposal["proposal_id"],
                    "proposal_digest": proposal["proposal_digest"],
                },
                "plan_ref": {
                    "plan_id": plan["plan_id"],
                    "plan_digest": plan["plan_digest"],
                },
                "decided_at": "2026-08-11T00:20:00Z",
                "operator": {
                    "operator_id": "review-board-v3",
                    "operator_role": "scientific-curator",
                    "authority_basis": [authority],
                },
                "decisions": [
                    {
                        "action_id": action["action_id"],
                        "action_digest": action["action_digest"],
                        "decision": "accept",
                        "rationale": "Every source and origin gap passed review.",
                        "authority_basis_ids": [authority["basis_id"]],
                        "operations": operations,
                    }
                ],
            },
            "acceptance_id",
            "acceptance_digest",
            "network-patch-acceptance-",
        )
        self._real_validate_acceptance(acceptance, proposal, plan, self.current_ref())
        missing = copy.deepcopy(acceptance)
        missing["decisions"][0]["operations"].pop()
        missing = attach(
            PATCH.without(missing, "acceptance_id", "acceptance_digest"),
            "acceptance_id",
            "acceptance_digest",
            "network-patch-acceptance-",
        )
        with self.assertRaisesRegex(ValueError, "every origin gap atomically"):
            self._real_validate_acceptance(missing, proposal, plan, self.current_ref())

    def test_v3_basis_rejects_unmaterializable_evidence_id_before_appraisal(self):
        proposal, _ = self.proposal_v3()
        basis = copy.deepcopy(proposal["actions"][0]["reviewed_evidence"][0])
        basis["evidence_id"] = "e" + "x" * 254
        basis = attach(
            PATCH.without(basis, "basis_id", "basis_digest"),
            "basis_id",
            "basis_digest",
            "network-patch-basis-",
        )
        self.assertEqual(
            PATCH.validate_basis(basis, "proposal.actions[0].reviewed_evidence[0]")[
                "evidence_id"
            ],
            "e" + "x" * 254,
        )

        basis["evidence_id"] = "e-zeger2000-" + "x" * 244
        basis = attach(
            PATCH.without(basis, "basis_id", "basis_digest"),
            "basis_id",
            "basis_digest",
            "network-patch-basis-",
        )
        with self.assertRaisesRegex(ValueError, "materializable evidence ID"):
            PATCH.validate_basis(basis, "proposal.actions[0].reviewed_evidence[0]")

    def test_evidence_pack_v2_binds_collection_groups_and_regenerates_v3(self):
        proposal, live_network = self.proposal_v3()
        artifact_root = self.root / "v3-pack-artifacts"
        artifact_root.mkdir()
        action = proposal["actions"][0]
        collection = {
            "schema": "PaperReadingEvidenceCollection/v1",
            "schema_version": "v1",
            "collection_id": proposal["reading_collection_ref"]["collection_id"],
            "collection_digest": proposal["reading_collection_ref"][
                "collection_digest"
            ],
            "network_ref": proposal["network_ref"],
            "review_request_set_ref": {
                "review_request_set_id": proposal["request_ref"][
                    "review_request_set_id"
                ],
                "review_request_set_digest": proposal["request_ref"][
                    "review_request_set_digest"
                ],
            },
            "reading_groups": [
                {
                    "reading_group_id": ref["reading_group_id"],
                    "reading_group_digest": ref["reading_group_digest"],
                    "source_ref": {
                        "source_id": ref["source_id"],
                        "source_digest": "6" * 64,
                    },
                    "report_set_ref": {
                        "report_set_id": ref["report_set_id"],
                        "report_set_digest": ref["report_set_digest"],
                    },
                }
                for ref in action["reading_group_refs"]
            ],
        }
        values = {
            "preconsumption_hypotheses": {"fixture": "selected hypotheses"},
            "review_requests": {"fixture": "requests"},
            "reading_collection": collection,
            "consumption_authority": {
                "authority_id": proposal["consumption_ref"]["authority_id"],
                "authority_digest": proposal["consumption_ref"]["authority_digest"],
                "expected_consumed_hypotheses_sha256": proposal["consumption_ref"][
                    "consumed_hypotheses_sha256"
                ],
            },
        }
        artifacts = {}
        for role, value in values.items():
            path = artifact_root / f"{role}.json"
            path.write_text(json.dumps(value, sort_keys=True), encoding="utf-8")
            artifacts[role] = {
                "path": str(path),
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            }
        authority_raw_sha = artifacts["consumption_authority"]["sha256"]
        proposal["consumption_ref"]["authority_file_sha256"] = authority_raw_sha
        proposal = attach(
            PATCH.without(proposal, "proposal_id", "proposal_digest"),
            "proposal_id",
            "proposal_digest",
            "network-patch-proposal-",
        )
        self._active_proposal = proposal
        pack = attach(
            {
                "schema": "NetworkPatchEvidencePack/v2",
                "schema_version": "2.0",
                "proposal_ref": {
                    "proposal_id": proposal["proposal_id"],
                    "proposal_digest": proposal["proposal_digest"],
                },
                "network_ref": proposal["network_ref"],
                "artifacts": artifacts,
            },
            "pack_id",
            "pack_digest",
            "network-patch-evidence-pack-",
        )
        collection_owner = mock.Mock()
        collection_owner.ContractError = ValueError
        collection_owner.validate_collection.side_effect = lambda value: value
        with mock.patch.object(
            PATCH, "load_reading_collection_module", return_value=collection_owner
        ):
            validated = PATCH.validate_evidence_pack_v2(
                pack,
                proposal,
                self.current_ref(),
                live_network=live_network,
                expected_authority_file_sha256=authority_raw_sha,
            )
            self.assertEqual(validated, pack)
            producer_call = self.gap_stub.propose_patch_v3.call_args
            self.assertEqual(len(producer_call.args), 5)
            self.assertTrue(
                all(
                    isinstance(producer_call.args[index], Path)
                    for index in (0, 2, 3, 4)
                )
            )
            self.assertEqual(
                producer_call.kwargs["expected_authority_file_sha256"],
                authority_raw_sha,
            )
            reversed_collection = copy.deepcopy(collection)
            reversed_collection["reading_groups"].reverse()
            collection_owner.validate_collection.side_effect = lambda value: (
                reversed_collection
            )
            with self.assertRaisesRegex(ValueError, "every collection group in order"):
                PATCH.validate_evidence_pack_v2(
                    pack,
                    proposal,
                    self.current_ref(),
                    live_network=live_network,
                    expected_authority_file_sha256=authority_raw_sha,
                )

    def test_evidence_pack_v2_regenerates_v4_through_the_v4_owner_seam(self):
        proposal, live_network = self.proposal_v4_extension()
        artifact_root = self.root / "v4-pack-artifacts"
        artifact_root.mkdir()
        action = proposal["actions"][0]
        basis_by_source = {
            basis["source_id"]: basis for basis in action["reviewed_evidence"]
        }
        collection = {
            "schema": "PaperReadingEvidenceCollection/v1",
            "schema_version": "v1",
            "collection_id": proposal["reading_collection_ref"]["collection_id"],
            "collection_digest": proposal["reading_collection_ref"][
                "collection_digest"
            ],
            "network_ref": proposal["network_ref"],
            "review_request_set_ref": {
                "review_request_set_id": proposal["request_ref"][
                    "review_request_set_id"
                ],
                "review_request_set_digest": proposal["request_ref"][
                    "review_request_set_digest"
                ],
            },
            "reading_groups": [
                {
                    "reading_group_id": ref["reading_group_id"],
                    "reading_group_digest": ref["reading_group_digest"],
                    "source_ref": {
                        "source_id": ref["source_id"],
                        "source_digest": basis_by_source[ref["source_id"]][
                            "source_digest"
                        ],
                    },
                    "report_set_ref": {
                        "report_set_id": ref["report_set_id"],
                        "report_set_digest": ref["report_set_digest"],
                    },
                }
                for ref in action["reading_group_refs"]
            ],
        }
        values = {
            "preconsumption_hypotheses": {"fixture": "selected hypotheses"},
            "review_requests": {"fixture": "requests"},
            "reading_collection": collection,
            "consumption_authority": {
                "authority_id": proposal["consumption_ref"]["authority_id"],
                "authority_digest": proposal["consumption_ref"]["authority_digest"],
                "expected_consumed_hypotheses_sha256": proposal["consumption_ref"][
                    "consumed_hypotheses_sha256"
                ],
            },
        }
        artifacts = {}
        for role, value in values.items():
            path = artifact_root / f"{role}.json"
            path.write_text(json.dumps(value, sort_keys=True), encoding="utf-8")
            artifacts[role] = {
                "path": str(path),
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            }
        authority_raw_sha = artifacts["consumption_authority"]["sha256"]
        proposal["consumption_ref"]["authority_file_sha256"] = authority_raw_sha
        proposal = attach(
            PATCH.without(proposal, "proposal_id", "proposal_digest"),
            "proposal_id",
            "proposal_digest",
            "network-patch-proposal-",
        )
        self._active_proposal = proposal
        pack = attach(
            {
                "schema": "NetworkPatchEvidencePack/v2",
                "schema_version": "2.0",
                "proposal_ref": {
                    "proposal_id": proposal["proposal_id"],
                    "proposal_digest": proposal["proposal_digest"],
                },
                "network_ref": proposal["network_ref"],
                "artifacts": artifacts,
            },
            "pack_id",
            "pack_digest",
            "network-patch-evidence-pack-",
        )
        collection_owner = mock.Mock()
        collection_owner.ContractError = ValueError
        collection_owner.validate_collection.side_effect = lambda value: value
        with mock.patch.object(
            PATCH, "load_reading_collection_module", return_value=collection_owner
        ):
            self.assertEqual(
                PATCH.validate_evidence_pack_v2(
                    pack,
                    proposal,
                    self.current_ref(),
                    live_network=live_network,
                    expected_authority_file_sha256=authority_raw_sha,
                ),
                pack,
            )
        self.assertIsNotNone(self.gap_stub.propose_patch_v4.call_args)
        self.assertIsNone(self.gap_stub.propose_patch_v3.call_args)

    def test_evidence_pack_v2_replays_detached_authority_and_rejects_forgery(self):
        self.gap_patcher.stop()
        real_gap = PATCH.load_gap_module()
        gap_test_path = (
            SCRIPT_DIR.parent.parent
            / "network-gap-discovery"
            / "scripts"
            / "test_network_gap_discovery.py"
        )
        sys.path.insert(0, str(gap_test_path.parent))
        spec = importlib.util.spec_from_file_location(
            "rkn_authority_gap_test_support", gap_test_path
        )
        self.assertIsNotNone(spec)
        self.assertIsNotNone(spec.loader)
        gap_support = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = gap_support
        spec.loader.exec_module(gap_support)

        artifact_root = self.root / "real-v3-authority-pack"
        artifact_root.mkdir()
        fixture = gap_support.multi_reading_collection_fixture(
            artifact_root, direct_selected=True
        )
        upstream = gap_support.reviewed_collection_consumption_artifacts(
            artifact_root, fixture
        )
        proposal = real_gap.propose_patch_v3(
            upstream["hypotheses_path"],
            fixture["network"],
            upstream["review_requests_path"],
            upstream["collection_path"],
            upstream["authority_path"],
            expected_authority_file_sha256=upstream["authority_raw_sha"],
        )
        PATCH.validate_proposal_v3(
            proposal, proposal["network_ref"], fixture["network"]
        )
        artifact_paths = {
            "preconsumption_hypotheses": upstream["hypotheses_path"],
            "review_requests": upstream["review_requests_path"],
            "reading_collection": upstream["collection_path"],
            "consumption_authority": upstream["authority_path"],
        }

        def make_pack(paths: dict[str, Path]) -> dict:
            return attach(
                {
                    "schema": "NetworkPatchEvidencePack/v2",
                    "schema_version": "2.0",
                    "proposal_ref": {
                        "proposal_id": proposal["proposal_id"],
                        "proposal_digest": proposal["proposal_digest"],
                    },
                    "network_ref": proposal["network_ref"],
                    "artifacts": {
                        role: {
                            "path": str(path),
                            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                        }
                        for role, path in sorted(paths.items())
                    },
                },
                "pack_id",
                "pack_digest",
                "network-patch-evidence-pack-",
            )

        pack = make_pack(artifact_paths)
        validated = PATCH.validate_evidence_pack_v2(
            pack,
            proposal,
            proposal["network_ref"],
            live_network=fixture["network"],
            expected_authority_file_sha256=upstream["authority_raw_sha"],
        )
        self.assertEqual(validated, pack)

        with self.assertRaisesRegex(ValueError, "caller-held raw SHA-256"):
            PATCH.validate_evidence_pack_v2(
                pack,
                proposal,
                proposal["network_ref"],
                live_network=fixture["network"],
                expected_authority_file_sha256="0" * 64,
            )
        with self.assertRaisesRegex(ValueError, "caller-held expected authority"):
            PATCH.validate_evidence_pack(
                pack,
                proposal,
                proposal["network_ref"],
                live_network=fixture["network"],
            )

        missing_authority = copy.deepcopy(pack)
        missing_authority["artifacts"].pop("consumption_authority")
        missing_authority = attach(
            PATCH.without(missing_authority, "pack_id", "pack_digest"),
            "pack_id",
            "pack_digest",
            "network-patch-evidence-pack-",
        )
        with self.assertRaisesRegex(ValueError, "consumption_authority"):
            PATCH.validate_evidence_pack_v2(
                missing_authority,
                proposal,
                proposal["network_ref"],
                live_network=fixture["network"],
                expected_authority_file_sha256=upstream["authority_raw_sha"],
            )

        tampered_authority = copy.deepcopy(upstream["authority"])
        tampered_authority["complete_scope"] = False
        tampered_authority_path = artifact_root / "tampered-authority.json"
        tampered_authority_path.write_text(
            json.dumps(tampered_authority, sort_keys=True), encoding="utf-8"
        )
        tampered_paths = {
            **artifact_paths,
            "consumption_authority": tampered_authority_path,
        }
        tampered_pack = make_pack(tampered_paths)
        tampered_sha = hashlib.sha256(tampered_authority_path.read_bytes()).hexdigest()
        with self.assertRaisesRegex(
            ValueError,
            "ReviewedEvidenceCollectionConsumptionAuthority/v1 replay failed",
        ):
            PATCH.validate_evidence_pack_v2(
                tampered_pack,
                proposal,
                proposal["network_ref"],
                live_network=fixture["network"],
                expected_authority_file_sha256=tampered_sha,
            )

        for status in ("results", "content_found"):
            handcrafted = copy.deepcopy(upstream["preconsumption"])
            handcrafted["hypotheses"][0]["status"] = status
            handcrafted_path = artifact_root / f"handcrafted-{status}.json"
            handcrafted_path.write_text(
                json.dumps(handcrafted, sort_keys=True), encoding="utf-8"
            )
            forged_pack = make_pack(
                {
                    **artifact_paths,
                    "preconsumption_hypotheses": handcrafted_path,
                }
            )
            with self.subTest(handcrafted_status=status):
                with self.assertRaisesRegex(
                    ValueError, "strict authorized multi-reading regeneration failed"
                ):
                    PATCH.validate_evidence_pack_v2(
                        forged_pack,
                        proposal,
                        proposal["network_ref"],
                        live_network=fixture["network"],
                        expected_authority_file_sha256=upstream["authority_raw_sha"],
                    )

    def test_unmocked_real_producer_to_atomic_rkn_apply(self):
        self.gap_patcher.stop()
        real_gap = PATCH.load_gap_module()
        gap_test_path = (
            SCRIPT_DIR.parent.parent
            / "network-gap-discovery"
            / "scripts"
            / "test_network_gap_discovery.py"
        )
        sys.path.insert(0, str(gap_test_path.parent))
        spec = importlib.util.spec_from_file_location(
            "rkn_real_gap_test_support", gap_test_path
        )
        self.assertIsNotNone(spec)
        self.assertIsNotNone(spec.loader)
        gap_support = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = gap_support
        spec.loader.exec_module(gap_support)

        source_text = (
            "The primary result proves it converges under the stated assumptions."
        )
        source_sha = hashlib.sha256(source_text.encode("utf-8")).hexdigest()
        onboarded = self.kn(
            [
                "add-source",
                "--source-id",
                "SRC-1",
                "--canonical-identity",
                "url:https://example.org/fixture-paper",
                "--canonical-version",
                "reviewed-v1",
                "--read-version",
                "full-text-v1",
                "--read-depth",
                "full",
                "--version-hash",
                "sha256:" + source_sha,
                "--role",
                "source",
            ]
        )
        self.assertEqual(onboarded[0], 0, onboarded[2])
        for entity_id in ("entity-a", "entity-b", "entity-c"):
            created = self.kn(
                [
                    "add-entity",
                    "--entity-id",
                    entity_id,
                    "--entity-type",
                    "benchmark-construct",
                    "--name",
                    entity_id,
                    "--description",
                    f"Benchmark entity {entity_id}",
                ]
            )
            self.assertEqual(created[0], 0, created[2])
        ground_evidence = self.kn(
            [
                "add-evidence",
                "--evidence-id",
                "ground-evidence",
                "--claim-id",
                "claim-01",
                "--source-id",
                "source-01",
                "--polarity",
                "supports",
                "--exact-locator",
                "page=1",
                "--independence-group",
                "source-01",
                "--summary",
                "Reviewed grounding evidence",
            ]
        )
        self.assertEqual(ground_evidence[0], 0, ground_evidence[2])
        grounded = self.kn(
            [
                "add-relation",
                "--relation-id",
                "rel-ab",
                "--relation-type",
                "supports",
                "--from-ref",
                "claim:claim-01",
                "--to-ref",
                "evidence:ground-evidence",
                "--notes",
                "Reviewed A-B grounding relation",
            ]
        )
        self.assertEqual(grounded[0], 0, grounded[2])
        exported = self.kn(["export"])
        self.assertEqual(exported[0], 0, exported[2])
        live_network = json.loads(exported[1])

        hypotheses = gap_support.hypotheses_fixture(live_network)
        hypotheses["hypotheses"][0]["decision_impact"] = "low"
        hypotheses["hypotheses"][0]["grounds"][0]["ref_id"] = "evidence:ground-evidence"
        hypotheses["hypotheses"][0]["backing"][0]["locator"] = (
            "evidence:ground-evidence"
        )
        hypotheses["hypotheses"][0]["backing"][0]["ref_id"] = "evidence:ground-evidence"
        selected_ids = [
            hypothesis["hypothesis_id"]
            for hypothesis in hypotheses["hypotheses"]
            if hypothesis["status"] == "selected"
        ]
        unscheduled = copy.deepcopy(hypotheses)
        unscheduled.pop("priority_order", None)
        unscheduled.pop("selection_summary", None)
        for hypothesis in unscheduled["hypotheses"]:
            hypothesis["status"] = "proposed"
        prioritized = real_gap.prioritize(unscheduled, live_network)
        selection = {
            "schema": real_gap.REVIEWED_GAP_SELECTION_SCHEMA,
            "input_ref": {
                "schema": "KnowledgeGapHypotheses/v1",
                "sha256": real_gap.sha256_json(prioritized),
            },
            "network_ref": copy.deepcopy(prioritized["network_ref"]),
            "round_id": prioritized["round_id"],
            "selected_hypothesis_ids": selected_ids,
            "review_status": "approved",
        }
        hypotheses = real_gap.select_hypotheses(prioritized, selection, live_network)
        request_set = real_gap.emit_search_requests(hypotheses, live_network)
        request = request_set["requests"][0]
        result_set = gap_support.make_result_set(
            request_set,
            request,
            [gap_support.reviewed_candidate_fixture()],
            request_digest=real_gap.sha256_json(request),
        )
        execution_authority_contexts, request_set_file_sha256_value = (
            gap_support._TEST_RESULT_CONTEXTS[id(result_set)]
        )
        discovered = real_gap.consume_results(
            hypotheses,
            live_network,
            request_set,
            [result_set],
            execution_authority_contexts=execution_authority_contexts,
            request_set_file_sha256=request_set_file_sha256_value,
        )
        review_set = discovered["review_requests"]
        review_request = review_set["requests"][0]
        artifact_root = self.root / "real-producer-chain"
        artifact_root.mkdir()
        verification_root = artifact_root / "verification"
        verification_root.mkdir()
        report_set, dossier, bundle_raw, source_raw = (
            gap_support.real_producer_projection(
                artifact_root,
                review_set,
                review_request,
                live_network,
                verification_root=verification_root,
            )
        )
        bundle_path = Path(bundle_raw)
        source_path = Path(source_raw)
        self.assertEqual(
            hashlib.sha256(source_path.read_bytes()).hexdigest(), source_sha
        )
        reviewed = real_gap.consume_reviewed_evidence(
            discovered,
            live_network,
            review_set,
            report_set,
            dossier,
            source_bundle_path=bundle_path,
            source_artifact_path=source_path,
            verification_root=verification_root,
        )
        proposal = real_gap.propose_patch(
            reviewed,
            live_network,
            review_set,
            report_set,
            dossier,
            source_bundle_path=bundle_path,
            source_artifact_path=source_path,
            verification_root=verification_root,
        )
        self.assertEqual(proposal["schema"], "NetworkPatchProposal/v2")
        self.assertEqual(len(proposal["actions"]), 1)
        mixed_proposal = json.loads(json.dumps(proposal))
        for kind in ("assumption", "boundary"):
            blocked_action = json.loads(json.dumps(proposal["actions"][0]))
            blocked_action.pop("target_claim")
            blocked_action.update(
                {
                    "action_type": "propose_evidence",
                    "action_status": "blocked",
                    "hypothesis_id": f"KGH-BLOCKED-{kind}",
                    "target_signature": {
                        "target_kind": kind,
                        "signature": f"{kind}:reviewed-boundary",
                    },
                    "hypothesis": f"Reviewed {kind} requires a future typed adapter.",
                }
            )
            mixed_proposal["actions"].append(blocked_action)
        gap_support.rehash_patch_v2(mixed_proposal)
        real_gap.validate_patch_v2(mixed_proposal, live_network)
        PATCH.validate_proposal_v2(mixed_proposal, self.current_ref())
        mixed_plan = PATCH.create_plan(
            mixed_proposal,
            self.current_ref(),
            prepared_at="2026-08-05T03:30:00Z",
        )
        self.assertEqual(
            [item["action_status"] for item in mixed_plan["actions"]],
            ["pending_acceptance", "blocked", "blocked"],
        )
        self.assertEqual(mixed_plan["actions"][1]["allowed_operation_types"], [])
        self.assertEqual(mixed_plan["actions"][2]["allowed_operation_types"], [])

        artifact_paths = {
            "hypotheses": self.write("real-reviewed-hypotheses.json", reviewed),
            "review_requests": self.write("real-review-requests.json", review_set),
            "reading_reports": self.write("real-reading-reports.json", report_set),
            "dossier": self.write("real-dossier.json", dossier),
            "source_bundle": bundle_path,
            "source_artifact": source_path,
        }
        evidence_pack = self.evidence_pack_from_artifacts(
            proposal, artifact_paths, verification_root
        )
        proposal_path = self.write("real-proposal.json", proposal)
        pack_path = self.write("real-evidence-pack.json", evidence_pack)

        validated = self.patch(
            [
                "validate-patch",
                "--proposal",
                str(proposal_path),
                "--evidence-pack",
                str(pack_path),
            ]
        )
        self.assertEqual(validated[0], 0, validated[2])

        tampered_path = artifact_paths["hypotheses"]
        original_reviewed = tampered_path.read_bytes()
        tampered_path.write_text('{"tampered":true}', encoding="utf-8")
        tampered = self.patch(
            [
                "validate-patch",
                "--proposal",
                str(proposal_path),
                "--evidence-pack",
                str(pack_path),
            ]
        )
        self.assertEqual(tampered[0], 1)
        self.assertIn("sha256 mismatch", tampered[2])
        tampered_path.write_bytes(original_reviewed)

        unonboarded_proposal = json.loads(json.dumps(proposal))
        unonboarded_proposal["actions"][0]["reviewed_evidence"][0]["source_id"] = (
            "SRC-NOT-ONBOARDED"
        )
        gap_support.rehash_patch_v2(unonboarded_proposal)
        unonboarded_pack = json.loads(json.dumps(evidence_pack))
        unonboarded_pack["proposal_ref"] = {
            "proposal_id": unonboarded_proposal["proposal_id"],
            "proposal_digest": unonboarded_proposal["proposal_digest"],
        }
        unonboarded_pack = attach(
            PATCH.without(unonboarded_pack, "pack_id", "pack_digest"),
            "pack_id",
            "pack_digest",
            "network-patch-evidence-pack-",
        )
        unonboarded_proposal_path = self.write(
            "real-unonboarded-proposal.json", unonboarded_proposal
        )
        unonboarded_pack_path = self.write(
            "real-unonboarded-pack.json", unonboarded_pack
        )
        unonboarded = self.patch(
            [
                "validate-patch",
                "--proposal",
                str(unonboarded_proposal_path),
                "--evidence-pack",
                str(unonboarded_pack_path),
            ]
        )
        self.assertEqual(unonboarded[0], 1)
        self.assertIn("source onboarding required", unonboarded[2])

        plan_path = self.root / "patch-plans" / "real-plan.json"
        prepared = self.patch(
            [
                "prepare-patch",
                "--proposal",
                str(proposal_path),
                "--evidence-pack",
                str(pack_path),
                "--output",
                str(plan_path),
            ]
        )
        self.assertEqual(prepared[0], 0, prepared[2])
        plan = json.loads(prepared[1])
        action = proposal["actions"][0]
        basis_rows = action["reviewed_evidence"]
        basis = basis_rows[0]
        target = action["target_claim"]
        claim_operation = self.operation(
            "add-claim",
            {
                field: target[field]
                for field in (
                    "claim_id",
                    "claim_text",
                    "entity_id",
                    "impact",
                    "coverage_dimensions",
                    "benchmark_profiles",
                    "supersedes",
                )
            }
            | {
                "scope_statement": target["scope"]["scope_statement"],
                **{
                    field: target["scope"][field]
                    for field in (
                        "assumptions",
                        "conditions",
                        "units",
                        "exclusions",
                        "defeaters",
                    )
                },
            },
            basis_rows,
        )
        evidence_operation = self.operation(
            "add-evidence",
            {
                "evidence_id": basis["evidence_id"],
                "claim_id": target["claim_id"],
                "source_id": basis["source_id"],
                "polarity": "supports",
                "exact_locator": basis["evidence_locator"],
                "independence_group": basis["source_id"],
                "summary": action["hypothesis"],
                "notes": "accepted from NetworkPatchProposal/v2",
                "supersedes": None,
            },
            basis_rows,
        )
        relation_id = PATCH.relation_operation_id(action, basis)
        relation_operation = self.operation(
            "add-relation",
            {
                "relation_id": relation_id,
                "relation_type": "supports",
                "from_ref": "claim:" + target["claim_id"],
                "to_ref": "evidence:" + basis["evidence_id"],
                "notes": "network-patch-action:" + action["action_digest"],
                "supersedes": None,
            },
            basis_rows,
        )
        authority = self.authority()
        mixed_acceptance = attach(
            {
                "schema": "NetworkPatchAcceptance/v1",
                "schema_version": "1.0",
                "network_ref": mixed_proposal["network_ref"],
                "proposal_ref": {
                    "proposal_id": mixed_proposal["proposal_id"],
                    "proposal_digest": mixed_proposal["proposal_digest"],
                },
                "plan_ref": {
                    "plan_id": mixed_plan["plan_id"],
                    "plan_digest": mixed_plan["plan_digest"],
                },
                "decided_at": "2026-08-05T03:45:00Z",
                "operator": {
                    "operator_id": "external-governance-board",
                    "operator_role": "scientific-curator",
                    "authority_basis": [authority],
                },
                "decisions": [
                    {
                        "action_id": mixed_proposal["actions"][0]["action_id"],
                        "action_digest": mixed_proposal["actions"][0]["action_digest"],
                        "decision": "accept",
                        "rationale": "Accept only the lossless relation mapping.",
                        "authority_basis_ids": [authority["basis_id"]],
                        "operations": [
                            claim_operation,
                            evidence_operation,
                            relation_operation,
                        ],
                    },
                    {
                        "action_id": mixed_proposal["actions"][1]["action_id"],
                        "action_digest": mixed_proposal["actions"][1]["action_digest"],
                        "decision": "reject",
                        "rationale": "No lossless assumption adapter exists.",
                        "authority_basis_ids": [authority["basis_id"]],
                        "operations": [],
                    },
                    {
                        "action_id": mixed_proposal["actions"][2]["action_id"],
                        "action_digest": mixed_proposal["actions"][2]["action_digest"],
                        "decision": "defer",
                        "rationale": "Boundary materialization remains blocked.",
                        "authority_basis_ids": [authority["basis_id"]],
                        "operations": [],
                    },
                ],
            },
            "acceptance_id",
            "acceptance_digest",
            "network-patch-acceptance-",
        )
        PATCH.validate_acceptance(
            mixed_acceptance, mixed_proposal, mixed_plan, self.current_ref()
        )
        blocked_acceptance = json.loads(json.dumps(mixed_acceptance))
        blocked_acceptance["decisions"][1].update(
            {
                "decision": "accept",
                "rationale": "Attempt to bypass the blocked operation gate.",
                "operations": [evidence_operation],
            }
        )
        blocked_acceptance = attach(
            PATCH.without(blocked_acceptance, "acceptance_id", "acceptance_digest"),
            "acceptance_id",
            "acceptance_digest",
            "network-patch-acceptance-",
        )
        with self.assertRaisesRegex(ValueError, "blocked action cannot be accepted"):
            PATCH.validate_acceptance(
                blocked_acceptance,
                mixed_proposal,
                mixed_plan,
                self.current_ref(),
            )
        acceptance = attach(
            {
                "schema": "NetworkPatchAcceptance/v1",
                "schema_version": "1.0",
                "network_ref": proposal["network_ref"],
                "proposal_ref": {
                    "proposal_id": proposal["proposal_id"],
                    "proposal_digest": proposal["proposal_digest"],
                },
                "plan_ref": {
                    "plan_id": plan["plan_id"],
                    "plan_digest": plan["plan_digest"],
                },
                "decided_at": "2026-08-05T04:00:00Z",
                "operator": {
                    "operator_id": "external-governance-board",
                    "operator_role": "scientific-curator",
                    "authority_basis": [authority],
                },
                "decisions": [
                    {
                        "action_id": action["action_id"],
                        "action_digest": action["action_digest"],
                        "decision": "accept",
                        "rationale": "External review accepted the exact typed projection.",
                        "authority_basis_ids": [authority["basis_id"]],
                        "operations": [
                            claim_operation,
                            evidence_operation,
                            relation_operation,
                        ],
                    }
                ],
            },
            "acceptance_id",
            "acceptance_digest",
            "network-patch-acceptance-",
        )
        acceptance_path = self.write("real-acceptance.json", acceptance)
        before_apply = self.current_ref()
        dry_run = self.patch(
            [
                "apply-patch",
                "--proposal",
                str(proposal_path),
                "--evidence-pack",
                str(pack_path),
                "--plan",
                str(plan_path),
                "--acceptance",
                str(acceptance_path),
                "--dry-run",
            ]
        )
        self.assertEqual(dry_run[0], 0, dry_run[2])
        self.assertEqual(self.current_ref(), before_apply)
        applied = self.patch(
            [
                "apply-patch",
                "--proposal",
                str(proposal_path),
                "--evidence-pack",
                str(pack_path),
                "--plan",
                str(plan_path),
                "--acceptance",
                str(acceptance_path),
            ]
        )
        self.assertEqual(applied[0], 0, applied[2])
        core_valid = self.kn(["validate"])
        self.assertEqual(core_valid[0], 0, core_valid[2])

        paths = KN._safe_paths(str(self.root), self.network_id)
        _, records = KN._load_state(paths)
        claim = next(
            item for item in records["claims"] if item["claim_id"] == target["claim_id"]
        )
        for field in (
            "claim_text",
            "entity_id",
            "impact",
            "coverage_dimensions",
            "benchmark_profiles",
            "supersedes",
        ):
            self.assertEqual(claim[field], target[field])
        self.assertEqual(claim["scope_statement"], target["scope"]["scope_statement"])
        for field in (
            "assumptions",
            "conditions",
            "units",
            "exclusions",
            "defeaters",
        ):
            self.assertEqual(claim[field], target["scope"][field])
        post_apply_export = self.kn(["export"])
        self.assertEqual(post_apply_export[0], 0, post_apply_export[2])
        exported_claim = next(
            item
            for item in json.loads(post_apply_export[1])["claims"]
            if item["claim_id"] == target["claim_id"]
        )
        for field in (
            "scope_statement",
            "assumptions",
            "conditions",
            "units",
            "exclusions",
            "defeaters",
        ):
            self.assertEqual(exported_claim[field], claim[field])
        evidence = next(
            item
            for item in records["evidence"]
            if item["evidence_id"] == basis["evidence_id"]
        )
        self.assertEqual(evidence["claim_id"], target["claim_id"])
        self.assertEqual(evidence["source_id"], basis["source_id"])
        self.assertEqual(evidence["exact_locator"], basis["evidence_locator"])
        self.assertEqual(evidence["polarity"], "supports")
        self.assertEqual(evidence["supersedes"], None)
        relation = next(
            item for item in records["relations"] if item["relation_id"] == relation_id
        )
        self.assertEqual(relation["relation_type"], "supports")
        self.assertEqual(relation["from"], "claim:" + target["claim_id"])
        self.assertEqual(relation["to"], "evidence:" + basis["evidence_id"])

        stale = self.patch(
            [
                "apply-patch",
                "--proposal",
                str(proposal_path),
                "--evidence-pack",
                str(pack_path),
                "--plan",
                str(plan_path),
                "--acceptance",
                str(acceptance_path),
            ]
        )
        self.assertEqual(stale[0], 1)
        self.assertIn("stale", stale[2])

    def test_evidence_projection_cannot_supersede_active_evidence_on_real_apply(self):
        seeded = self.kn(
            [
                "add-evidence",
                "--evidence-id",
                "old-evidence",
                "--claim-id",
                "claim-01",
                "--source-id",
                "source-01",
                "--polarity",
                "supports",
                "--exact-locator",
                "page=1",
                "--independence-group",
                "source-01",
                "--summary",
                "Previously reviewed evidence",
            ]
        )
        self.assertEqual(seeded[0], 0, seeded[2])
        before = self.current_ref()
        proposal, plan, acceptance = self.contracts()
        action = proposal["actions"][0]
        evidence_operation = acceptance["decisions"][0]["operations"][1]
        malicious_payload = dict(evidence_operation["payload"])
        malicious_payload["supersedes"] = "evidence:old-evidence"
        acceptance["decisions"][0]["operations"][1] = self.operation(
            "add-evidence", malicious_payload, action["reviewed_evidence"]
        )
        acceptance = attach(
            PATCH.without(acceptance, "acceptance_id", "acceptance_digest"),
            "acceptance_id",
            "acceptance_digest",
            "network-patch-acceptance-",
        )
        pack = self.evidence_pack(proposal)
        proposal_path = self.write("supersede-proposal.json", proposal)
        plan_path = self.write("supersede-plan.json", plan)
        acceptance_path = self.write("supersede-acceptance.json", acceptance)
        pack_path = self.write("supersede-pack.json", pack)

        rejected = self.patch(
            [
                "apply-patch",
                "--proposal",
                str(proposal_path),
                "--evidence-pack",
                str(pack_path),
                "--plan",
                str(plan_path),
                "--acceptance",
                str(acceptance_path),
            ]
        )
        self.assertEqual(rejected[0], 1)
        self.assertIn("supersedes must be null", rejected[2])
        self.assertEqual(self.current_ref(), before)
        exported = self.kn(["export"])
        self.assertEqual(exported[0], 0, exported[2])
        self.assertEqual(
            [item["evidence_id"] for item in json.loads(exported[1])["evidence"]],
            ["old-evidence"],
        )

    def test_evidence_projection_rejects_any_noncanonical_closed_field(self):
        proposal, plan, acceptance = self.contracts()
        action = proposal["actions"][0]
        canonical = acceptance["decisions"][0]["operations"][1]
        mutations = {
            "polarity": "qualifies",
            "notes": "operator supplied note",
            "summary": "different scientific statement",
        }
        for field, value in mutations.items():
            with self.subTest(field=field):
                candidate = json.loads(json.dumps(acceptance))
                payload = dict(canonical["payload"])
                payload[field] = value
                candidate["decisions"][0]["operations"][1] = self.operation(
                    "add-evidence", payload, action["reviewed_evidence"]
                )
                candidate = attach(
                    PATCH.without(candidate, "acceptance_id", "acceptance_digest"),
                    "acceptance_id",
                    "acceptance_digest",
                    "network-patch-acceptance-",
                )
                with self.assertRaisesRegex(ValueError, "exact reviewed projection"):
                    PATCH.validate_acceptance(
                        candidate, proposal, plan, self.current_ref()
                    )

    def test_propose_node_acceptance_is_fail_closed_without_target_node(self):
        proposal, plan, acceptance = self.contracts()
        self.assertEqual(plan["actions"][1]["allowed_operation_types"], [])
        node_action = proposal["actions"][1]
        malicious_claim = self.operation(
            "add-claim",
            {
                "claim_id": node_action["target_signature"]["signature"],
                "claim_text": node_action["hypothesis"],
                "entity_id": "entity:injected",
                "impact": "high",
                "coverage_dimensions": ["injected-dimension"],
                "benchmark_profiles": ["injected-profile"],
                "supersedes": "claim:claim-01",
            },
            node_action["reviewed_evidence"],
        )
        acceptance["decisions"][1].update(
            {
                "decision": "accept",
                "rationale": "Attempt an unconstrained node projection.",
                "operations": [malicious_claim],
            }
        )
        acceptance = attach(
            PATCH.without(acceptance, "acceptance_id", "acceptance_digest"),
            "acceptance_id",
            "acceptance_digest",
            "network-patch-acceptance-",
        )
        with self.assertRaisesRegex(ValueError, "blocked action cannot be accepted"):
            PATCH.validate_acceptance(acceptance, proposal, plan, self.current_ref())

    def test_every_evidence_pack_artifact_and_verification_tree_rejects_drift(self):
        proposal, _, _ = self.contracts()
        pack = self.evidence_pack(proposal)
        paths = KN._safe_paths(self.root, self.network_id)
        state, records, network_ref = PATCH.validate_live_network(paths)
        live_network = KN._knowledge_network_export(paths, state, records)

        for role, reference in sorted(pack["artifacts"].items()):
            with self.subTest(role=role):
                artifact = Path(reference["path"])
                original = artifact.read_bytes()
                artifact.write_bytes(
                    original + b"\nconcurrent-drift"
                    if role == "source_artifact"
                    else b'{"concurrent_drift":true}'
                )
                try:
                    with self.assertRaisesRegex(ValueError, "sha256 mismatch"):
                        PATCH.validate_evidence_pack(
                            pack,
                            proposal,
                            network_ref,
                            live_network=live_network,
                        )
                finally:
                    artifact.write_bytes(original)

        verification_root = Path(pack["verification_root"]["path"])
        verification_artifact = next(
            path for path in verification_root.rglob("*") if path.is_file()
        )
        original = verification_artifact.read_bytes()
        verification_artifact.write_bytes(original + b"\nconcurrent-drift")
        try:
            with self.assertRaisesRegex(ValueError, "tree digest mismatch"):
                PATCH.validate_evidence_pack(
                    pack,
                    proposal,
                    network_ref,
                    live_network=live_network,
                )
        finally:
            verification_artifact.write_bytes(original)

    def test_source_independence_is_lineage_not_verifier_identity(self):
        first = self.basis("source-a")
        same_source_second_verifier = self.basis("source-b")
        same_source_second_verifier["source_id"] = first["source_id"]
        same_source_second_verifier["verification"]["verifier_id"] = "reviewer-99"
        self.assertEqual(
            PATCH.source_independence_group(first),
            PATCH.source_independence_group(same_source_second_verifier),
        )

        second_source_same_verifier = self.basis("source-c")
        second_source_same_verifier["source_id"] = "source-02"
        second_source_same_verifier["verification"]["verifier_id"] = first[
            "verification"
        ]["verifier_id"]
        self.assertNotEqual(
            PATCH.source_independence_group(first),
            PATCH.source_independence_group(second_source_same_verifier),
        )

    def test_unonboarded_basis_source_fails_before_patch_preparation(self):
        proposal = self.proposal()
        relation = proposal["actions"][0]
        basis = PATCH.without(
            relation["reviewed_evidence"][0], "basis_id", "basis_digest"
        )
        basis["source_id"] = "source-not-onboarded"
        basis = attach(basis, "basis_id", "basis_digest", "network-patch-basis-")
        relation["reviewed_evidence"] = [basis]
        relation = attach(
            PATCH.without(relation, "action_id", "action_digest"),
            "action_id",
            "action_digest",
            "network-patch-action-",
        )
        proposal["actions"][0] = relation
        proposal = attach(
            PATCH.without(proposal, "proposal_id", "proposal_digest"),
            "proposal_id",
            "proposal_digest",
            "network-patch-proposal-",
        )
        proposal = PATCH.validate_proposal_v2(proposal, self.current_ref())
        paths = KN._safe_paths(self.root, self.network_id)
        state, records, _ = PATCH.validate_live_network(paths)
        live_network = KN._knowledge_network_export(paths, state, records)
        with self.assertRaisesRegex(ValueError, "source onboarding required"):
            PATCH.require_onboarded_sources(proposal, live_network)


if __name__ == "__main__":
    unittest.main()
