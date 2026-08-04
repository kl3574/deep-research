from __future__ import annotations

import copy
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from validate_research_handoff import validate_handoff


def _write_json(root: Path, name: str, value: object) -> tuple[str, str]:
    path = root / name
    path.write_text(
        json.dumps(value, ensure_ascii=False, sort_keys=True),
        encoding="utf-8",
    )
    return str(path), hashlib.sha256(path.read_bytes()).hexdigest()


class ResearchHandoffValidationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.network = {
            "schema": "KnowledgeNetwork/v1",
            "network_id": "KN-1",
            "snapshot_id": "KN-1-S1",
            "corpus_snapshot": {
                "source": "zotero",
                "target_ref": "private:target",
                "captured_at": "2026-08-04T00:00:00Z",
                "inventory_digest": "a" * 64,
                "item_count": 1,
                "item_refs": ["private:item:SRC-1"],
            },
            "nodes": [
                {
                    "node_id": "source:SRC-1",
                    "kind": "source",
                    "label": "Source",
                    "status": "active",
                    "confidence": "high",
                    "provenance": [
                        {"source_id": "source:SRC-1", "locator": "DOI"}
                    ],
                },
                {
                    "node_id": "claim:C1",
                    "kind": "claim",
                    "label": "Claim",
                    "status": "active",
                    "confidence": "high",
                    "provenance": [
                        {
                            "source_id": "source:SRC-1",
                            "locator": "PDF p.4 | Eq. (7)",
                        }
                    ],
                },
                {
                    "node_id": "entity:method",
                    "kind": "entity",
                    "label": "Method",
                    "status": "active",
                    "confidence": "high",
                    "provenance": [
                        {"source_id": "source:SRC-1", "locator": "PDF p.1"}
                    ],
                },
            ],
            "relations": [
                {
                    "relation_id": "REL-1",
                    "from_id": "claim:C1",
                    "to_id": "entity:method",
                    "predicate": "supports",
                    "status": "supported",
                    "confidence": "high",
                    "provenance": [
                        {
                            "source_id": "source:SRC-1",
                            "locator": "PDF p.4 | Eq. (7)",
                        }
                    ],
                }
            ],
            "gap_derivation": {
                "rules": ["missing", "conflict", "low_confidence"],
                "derived_gap_ids": ["GAP-1"],
            },
            "gaps": [
                {
                    "gap_id": "GAP-1",
                    "derived_from": ["REL-1"],
                    "reason": "low_confidence",
                    "priority": "decision_critical",
                    "status": "resolved",
                    "next_action": "none",
                }
            ],
            "change_history": [
                {
                    "change_id": "CHG-1",
                    "action": "merge",
                    "object_ids": ["REL-1", "GAP-1"],
                    "basis_refs": ["source:SRC-1"],
                    "recorded_at": "2026-08-04T00:00:00Z",
                }
            ],
            "completion": {
                "status": "passed",
                "open_gap_ids": [],
                "gate_checks": {
                    "corpus_snapshotted": True,
                    "provenance_complete": True,
                    "conflicts_terminal": True,
                    "low_confidence_edges_terminal": True,
                    "change_history_recorded": True,
                },
            },
        }
        network_path, network_hash = _write_json(
            self.root, "network.json", self.network
        )
        batch_path, batch_hash = _write_json(
            self.root, "curation.json", {"schema": "CurationBatch/test"}
        )
        self.handoff = {
            "schema": "ResearchHandoff/v1",
            "run_id": "run-1",
            "task_modes": ["research", "acquisition", "zotero"],
            "privacy": {
                "classification": "private",
                "public_export": "redacted_only",
            },
            "research": {
                "status": "complete",
                "contract_ref": "run:contract",
                "coverage_audit_ref": "run:coverage",
            },
            "knowledge_network": {
                "schema": "KnowledgeNetwork/v1",
                "snapshot_id": "KN-1-S1",
                "path": network_path,
                "sha256": network_hash,
            },
            "preflight": {
                "completed": True,
                "zotero_corpus_first": True,
                "golden_bundle": {
                    "item_id": "SRC-1",
                    "status": "passed",
                    "bundle_ref": "bundle:SRC-1",
                    "validation_ref": "validation:SRC-1",
                },
            },
            "items": [
                {
                    "item_id": "SRC-1",
                    "source_id": "source:SRC-1",
                    "evidence_role": "decisive",
                    "reading_tier": "A",
                    "learn_from_papers": {
                        "paper_card_ref": "paper-card:SRC-1",
                        "evidence_ledger_ref": "ledger:SRC-1",
                        "locator_audit_ref": "locator:SRC-1",
                        "locator_audit_status": "passed",
                    },
                    "attachments": [
                        {
                            "attachment_id": "ATT-1",
                            "role": "main_text",
                            "source_kind": "version_of_record_main",
                            "path": str(self.root / "paper.pdf"),
                            "sha256": "b" * 64,
                        }
                    ],
                    "benchmark_use": True,
                    "benchmark_ids": ["BENCH-1"],
                }
            ],
            "benchmark_profile_required": True,
            "benchmarks": [
                {
                    "schema": "BenchmarkProfile/v1",
                    "benchmark_id": "BENCH-1",
                    "name": "Toy model",
                    "task_modes": [
                        "support_recovery",
                        "fixed_support_calibration",
                    ],
                    "model": {
                        "equations_or_model_ref": "claim:C1",
                        "candidate_library": "quadratic library",
                        "ground_truth": "support and coefficients",
                        "parameters": "source values",
                        "initial_conditions": "source values",
                        "inputs_or_perturbations": "none",
                    },
                    "observation_protocol": {
                        "observed_states": "all",
                        "inputs_or_perturbations": "none",
                        "noise": "Gaussian measurement noise",
                        "sampling": "uniform grid",
                        "trajectories": "ten grouped trajectories",
                    },
                    "evaluation": {
                        "split": "held-out trajectories",
                        "metrics": ["support TP/FP/FN", "parameter error"],
                        "equivalence_rule": "exact support",
                    },
                    "failure_boundaries": ["library omission"],
                    "evidence": {
                        "source_claim_refs": ["claim:C1"],
                        "exact_locators": ["source:SRC-1 | PDF p.4 | Eq. (7)"],
                    },
                }
            ],
            "request": {
                "requirements": [
                    {
                        "requirement_id": "REQ-1",
                        "required": True,
                        "item_ids": ["SRC-1"],
                        "operations": [
                            "research_note",
                            "benchmark_card",
                            "acquire_main_text",
                            "zotero_note",
                        ],
                    }
                ]
            },
            "delivery": {
                "status": "complete",
                "authorization": {
                    "target_approved": True,
                    "batch_approved": True,
                    "approval_ref": "private:approval",
                    "target_ref": "private:target",
                },
                "capability_matrix": [
                    {
                        "operation": "acquire_main_text",
                        "required": True,
                        "status": "available",
                        "paths": [
                            {
                                "path_id": "publisher",
                                "status": "available",
                                "evidence_ref": "probe:publisher",
                            },
                            {
                                "path_id": "repository",
                                "status": "unknown",
                                "evidence_ref": "probe:repository",
                            },
                        ],
                    },
                    {
                        "operation": "zotero_note",
                        "required": True,
                        "status": "available",
                        "paths": [
                            {
                                "path_id": "desktop",
                                "status": "available",
                                "evidence_ref": "probe:desktop",
                            },
                            {
                                "path_id": "web",
                                "status": "unknown",
                                "evidence_ref": "probe:web",
                            },
                        ],
                    },
                ],
                "curation_batches": [
                    {
                        "batch_id": "CUR-1",
                        "manifest_path": batch_path,
                        "sha256": batch_hash,
                        "visibility": "private",
                        "target_ref": "private:target",
                    }
                ],
                "completion_matrix": [],
            },
        }
        for operation in self.handoff["request"]["requirements"][0]["operations"]:
            self.handoff["delivery"]["completion_matrix"].append(
                {
                    "requirement_id": "REQ-1",
                    "item_id": "SRC-1",
                    "operation": operation,
                    "status": "complete",
                    "evidence_refs": [f"evidence:{operation}"],
                }
            )

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def test_valid_complete_handoff(self) -> None:
        self.assertEqual(validate_handoff(self.handoff), [])

    def test_missing_required_field(self) -> None:
        handoff = copy.deepcopy(self.handoff)
        del handoff["research"]["coverage_audit_ref"]
        errors = validate_handoff(handoff)
        self.assertTrue(
            any("research.coverage_audit_ref is required" in error for error in errors)
        )

    def test_tier_a_requires_learn_from_papers_and_locator(self) -> None:
        handoff = copy.deepcopy(self.handoff)
        del handoff["items"][0]["learn_from_papers"]["paper_card_ref"]
        handoff["items"][0]["learn_from_papers"]["locator_audit_status"] = "failed"
        errors = validate_handoff(handoff)
        self.assertTrue(any("paper_card_ref is required" in error for error in errors))
        self.assertTrue(any("locator audit must be passed" in error for error in errors))

    def test_benchmark_card_requires_protocol_and_evidence(self) -> None:
        handoff = copy.deepcopy(self.handoff)
        handoff["benchmarks"][0]["failure_boundaries"] = []
        handoff["benchmarks"][0]["evidence"]["exact_locators"] = []
        errors = validate_handoff(handoff)
        self.assertTrue(any("failure_boundaries" in error for error in errors))
        self.assertTrue(any("exact_locators" in error for error in errors))

    def test_partial_delivery_is_valid_with_explicit_blocker(self) -> None:
        handoff = copy.deepcopy(self.handoff)
        handoff["delivery"]["status"] = "partial"
        row = handoff["delivery"]["completion_matrix"][-1]
        row["status"] = "partial"
        row["blocker"] = "existing note update awaits authorized Desktop path"
        self.assertEqual(validate_handoff(handoff), [])

    def test_empty_gap_arrays_and_zero_zotero_corpus_are_valid(self) -> None:
        network = copy.deepcopy(self.network)
        network["corpus_snapshot"]["item_count"] = 0
        network["corpus_snapshot"]["item_refs"] = []
        network["gap_derivation"]["derived_gap_ids"] = []
        network["gaps"] = []
        network["completion"]["open_gap_ids"] = []
        network_path, network_hash = _write_json(
            self.root, "empty-network.json", network
        )
        handoff = copy.deepcopy(self.handoff)
        handoff["knowledge_network"]["path"] = network_path
        handoff["knowledge_network"]["sha256"] = network_hash
        self.assertEqual(validate_handoff(handoff), [])

    def test_semantically_required_fields_must_be_nonempty(self) -> None:
        handoff = copy.deepcopy(self.handoff)
        handoff["run_id"] = ""
        handoff["benchmarks"][0]["model"]["ground_truth"] = ""
        handoff["delivery"]["completion_matrix"][0]["evidence_refs"] = []
        errors = validate_handoff(handoff)
        self.assertTrue(
            any("handoff.run_id must be non-empty" in error for error in errors)
        )
        self.assertTrue(
            any("model.ground_truth must be non-empty" in error for error in errors)
        )
        self.assertTrue(
            any(
                "evidence_refs must be non-empty for complete rows" in error
                for error in errors
            )
        )

    def test_supplement_cannot_masquerade_as_main_text(self) -> None:
        handoff = copy.deepcopy(self.handoff)
        handoff["items"][0]["attachments"][0][
            "source_kind"
        ] = "supplementary_information"
        errors = validate_handoff(handoff)
        self.assertTrue(
            any("supplementary information cannot be main_text" in error for error in errors)
        )

    def test_two_failed_paths_force_blocked_capability(self) -> None:
        handoff = copy.deepcopy(self.handoff)
        capability = handoff["delivery"]["capability_matrix"][1]
        capability["paths"][0]["status"] = "failed"
        capability["paths"][1]["status"] = "unavailable"
        errors = validate_handoff(handoff)
        self.assertTrue(any("require blocked_capability" in error for error in errors))

    def test_curation_batch_hash_is_verified(self) -> None:
        handoff = copy.deepcopy(self.handoff)
        handoff["delivery"]["curation_batches"][0]["sha256"] = "0" * 64
        errors = validate_handoff(handoff)
        self.assertTrue(any("sha256 mismatch" in error for error in errors))


if __name__ == "__main__":
    unittest.main()
