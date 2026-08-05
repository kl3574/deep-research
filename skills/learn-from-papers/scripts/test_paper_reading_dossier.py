#!/usr/bin/env python3
"""Tests for PaperReadingDossier/v1 and v2 projection."""

from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import os
import tempfile
from pathlib import Path
from typing import Any
from unittest import TestCase, main


SCRIPT_PATH = Path(__file__).with_name("paper_reading_dossier.py")
SPEC = importlib.util.spec_from_file_location("paper_reading_dossier", SCRIPT_PATH)
assert SPEC and SPEC.loader
module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(module)

SOURCE_BUNDLE_PATH = Path(__file__).with_name("paper_source_bundle.py")
SOURCE_SPEC = importlib.util.spec_from_file_location("paper_source_bundle", SOURCE_BUNDLE_PATH)
assert SOURCE_SPEC and SOURCE_SPEC.loader
source_bundle_module = importlib.util.module_from_spec(SOURCE_SPEC)
SOURCE_SPEC.loader.exec_module(source_bundle_module)


def _build_bundle(tmpdir: Path, text: str) -> tuple[dict[str, Any], str, str]:
    source = tmpdir / "paper.txt"
    source.write_text(text, encoding="utf-8")
    bundle = tmpdir / "bundle.json"
    manifest = source_bundle_module.build_bundle(
        source=str(source),
        output=str(bundle),
        generated_at="2026-08-05T00:00:00Z",
    )
    return manifest, str(source), str(bundle)


def _span_for_phrase(bundle: str, phrase: str) -> tuple[int, int, str, str]:
    bundle_data = json.loads(Path(bundle).read_text(encoding="utf-8"))
    artifact_path = Path(bundle).parent.joinpath(bundle_data["pages"][0]["artifact_path"])
    source_text = artifact_path.read_text(encoding="utf-8")
    start = source_text.index(phrase)
    end = start + len(phrase)
    located = module.locate_span(bundle=bundle, page=1, start_char=start, end_char=end)
    return start, end, located["span_hash"], located["span_id"]


def _verification(mode: str = "independent_source_check") -> dict[str, str]:
    return {
        "mode": mode,
        "verifier_id": "external-verifier-001",
    }


def _base_draft(bundle: dict[str, Any], source_path: str, source_bundle_path: str, phrase: str) -> dict[str, Any]:
    source_text = Path(source_path).read_text(encoding="utf-8")
    first_page = source_text.replace("\f", "\n").splitlines()
    if not first_page:
        raise RuntimeError("empty source text")
    start = source_text.index(phrase)
    end = start + len(phrase)
    _, _, locator_hash, locator_id = _span_for_phrase(source_bundle_path, phrase)
    return {
        "schema": module.SCHEMA,
        "schema_version": module.SCHEMA_VERSION,
        "producer": module.PRODUCER,
        "protocol_version": module.PROTOCOL_VERSION,
        "generated_at": "2026-08-05T00:00:00Z",
        "request_question_plan": {
            "request_text": "Validate the main convergence claim.",
            "subquestions": [
                {"subquestion_id": "sq-1", "text": "Can convergence be reconstructed?", "required": True},
            ],
            "abstention_conditions": [],
        },
        "source_bundle": {
            "bundle_id": bundle["bundle_id"],
            "bundle_digest": bundle["bundle_digest"],
            "source_ref": Path(source_path).name,
            "source_artifact_sha256": bundle["source"]["source_sha256"],
        },
        "review_source": {
            "source_id": "SRC-001",
            "source_digest": "c" * 64,
            "acquisition_locator": "doi:10.1000/xyz",
        },
        "network_ref": {
            "network_id": "KN-001",
            "snapshot_id": "KN-001-S001",
            "sha256": "a" * 64,
        },
        "review_request_set_id": "RFS-1",
        "review_request_set_digest": "b" * 64,
        "review_request_id": "RR-1",
        "review_request_digest": "c" * 64,
        "access_level": "full_text",
        "inspection_depth": "evidence",
        "reconstruction_status": "planned",
        "embedded_documents": [
            {"document_id": "doc-main", "instruction": "Isolate instruction context per document."}
        ],
        "component_manifest": [
            {
                "component_id": "C-1",
                "name": "main",
                "artifact": "paper.txt",
                "status": "covered",
                "inspected_units": 1,
                "covered_units": 1,
                "terminal_units": 0,
                "document_id": "doc-main",
            }
        ],
        "claims": [
            {
                "claim_id": "claim-001",
                "hypothesis_id": "hyp-001",
                "target_id": "target-001",
                "statement": "The method converges under stated assumptions.",
                "relation": "supports",
                "origin": "source",
                "scope": {
                    "assumptions": ["Lipschitz"],
                    "conditions": ["positive_step"],
                    "units": ["loss"],
                    "exclusions": [],
                },
                "verifier_status": "passed",
                "confidence": "medium",
                "evidence_ids": ["evidence-001"],
                "subquestion_id": "sq-1",
                "reconstruction_task_ids": [],
                "citation_chain": [],
                "verification": _verification(),
            }
        ],
        "evidence_records": [
            {
                "evidence_id": "evidence-001",
                "claim_id": "claim-001",
                "hypothesis_id": "hyp-001",
                "target_id": "target-001",
                "page": 1,
                "start_char": start,
                "end_char": end,
                "relation": "supports",
                "verifier_status": "passed",
                "exact_locator": "main p.1",
                "card_type": "page",
                "origin": "source",
                "scope": {
                    "assumptions": ["Lipschitz"],
                    "conditions": ["positive_step"],
                    "units": ["loss"],
                    "exclusions": [],
                },
                "document_id": "doc-main",
                "span_hash": locator_hash,
                "span_id": locator_id,
                "card": {},
                "reconstruction_task_ids": [],
                "citation_chain": [],
            }
        ],
        "reconstruction_tasks": [],
        "correction_log": [],
        "unresolved_terminal_states": [],
    }


class PaperReadingDossierTests(TestCase):
    def _make_inputs(self) -> tuple[tempfile.TemporaryDirectory, dict[str, Any], str, str]:
        tmp = tempfile.TemporaryDirectory()
        tmpdir = Path(tmp.name)
        text = (
            "The paper proposes a method and proves it converges.\f"
            "Supplementary material is discussed separately."
        )
        manifest, source, bundle = _build_bundle(tmpdir, text)
        return tmp, manifest, source, bundle

    def test_tampered_span_rejects(self) -> None:
        tmp, manifest, source, bundle = self._make_inputs()
        self.addCleanup(tmp.cleanup)
        draft = _base_draft(manifest, source, bundle, "proves it converges")
        # Wrong span hash should be rejected even when all other fields match.
        bad = copy.deepcopy(draft)
        bad["evidence_records"][0]["span_hash"] = "0" * 64
        with self.assertRaises(module.ContractError):
            module.create_dossier(bad, bundle=bundle, source=source)

    def test_relation_cross_field_mismatch_is_rejected(self) -> None:
        tmp, manifest, source, bundle = self._make_inputs()
        self.addCleanup(tmp.cleanup)
        draft = _base_draft(manifest, source, bundle, "proves it converges")
        draft["evidence_records"][0]["relation"] = "refutes"
        with self.assertRaises(module.ContractError):
            module.create_dossier(draft, bundle=bundle, source=source)

    def test_noncanonical_evidence_locator_is_normalized(self) -> None:
        tmp, manifest, source, bundle = self._make_inputs()
        self.addCleanup(tmp.cleanup)
        draft = _base_draft(manifest, source, bundle, "proves it converges")
        draft["evidence_records"][0]["exact_locator"] = "legacy locator"
        dossier = module.create_dossier(draft, bundle=bundle, source=source)
        expected_locator = module.locate_span(
            bundle=bundle,
            page=dossier["evidence_records"][0]["page"],
            start_char=dossier["evidence_records"][0]["start_char"],
            end_char=dossier["evidence_records"][0]["end_char"],
        )["exact_locator"]
        self.assertEqual(dossier["evidence_records"][0]["exact_locator"], expected_locator)

    def test_overclaimed_confidence_is_rejected(self) -> None:
        tmp, manifest, source, bundle = self._make_inputs()
        self.addCleanup(tmp.cleanup)
        draft = _base_draft(manifest, source, bundle, "proves it converges")
        draft["claims"][0]["confidence"] = "high"
        draft["claims"][0]["evidence_ids"] = []
        with self.assertRaises(module.ContractError):
            module.create_dossier(draft, bundle=bundle, source=source)

    def test_false_execution_status_is_rejected(self) -> None:
        tmp, manifest, source, bundle = self._make_inputs()
        self.addCleanup(tmp.cleanup)
        draft = _base_draft(manifest, source, bundle, "proves it converges")
        draft["inspection_depth"] = "reconstruction"
        draft["claims"][0]["reconstruction_task_ids"] = ["task-001"]
        draft["reconstruction_tasks"] = [
            {
                "task_id": "task-001",
                "claim_id": "claim-001",
                "hypothesis_id": "hyp-001",
                "command": "python -m validate.py",
                "executed": False,
                "result": "not_run",
                "result_match": False,
                "result_notes": "not run intentionally",
            }
        ]
        with self.assertRaises(module.ContractError):
            module.create_dossier(draft, bundle=bundle, source=source)

    def test_reconstruction_status_executed_requires_tasks(self) -> None:
        tmp, manifest, source, bundle = self._make_inputs()
        self.addCleanup(tmp.cleanup)
        draft = _base_draft(manifest, source, bundle, "proves it converges")
        draft["reconstruction_status"] = "executed"
        with self.assertRaises(module.ContractError):
            module.create_dossier(draft, bundle=bundle, source=source)

    def test_inspection_depth_reconstruction_requires_passed_tasks(self) -> None:
        tmp, manifest, source, bundle = self._make_inputs()
        self.addCleanup(tmp.cleanup)
        draft = _base_draft(manifest, source, bundle, "proves it converges")
        draft["inspection_depth"] = "reconstruction"
        draft["claims"][0]["reconstruction_task_ids"] = ["task-001"]
        draft["reconstruction_tasks"] = [
            {
                "task_id": "task-001",
                "claim_id": "claim-001",
                "hypothesis_id": "hyp-001",
                "command": "python -m validate.py",
                "executed": True,
                "result": "failed",
                "result_match": False,
                "result_notes": "did not pass",
            }
        ]
        with self.assertRaises(module.ContractError):
            module.create_dossier(draft, bundle=bundle, source=source)

    def test_render_required_central_visual_requires_rendered_bundle(self) -> None:
        tmp, manifest, source, bundle = self._make_inputs()
        self.addCleanup(tmp.cleanup)
        draft = _base_draft(manifest, source, bundle, "proves it converges")
        draft["evidence_records"][0]["card_type"] = "figure"
        draft["evidence_records"][0]["card"] = {
            "caption": "Convergence curve",
            "axes": ["sample", "score"],
            "render_required": True,
            "is_central_visual": True,
        }
        with self.assertRaises(module.ContractError):
            module.create_dossier(draft, bundle=bundle, source=source)

    def test_render_required_central_table_requires_rendered_bundle(self) -> None:
        tmp, manifest, source, bundle = self._make_inputs()
        self.addCleanup(tmp.cleanup)
        draft = _base_draft(manifest, source, bundle, "proves it converges")
        draft["evidence_records"][0]["card_type"] = "table"
        draft["evidence_records"][0]["card"] = {
            "title": "Convergence table",
            "rows": ["loss=0.1", "loss=0.2"],
            "columns": ["metric", "value"],
            "render_required": True,
            "is_central_visual": True,
        }
        with self.assertRaises(module.ContractError):
            module.create_dossier(draft, bundle=bundle, source=source)

    def test_required_subquestion_overlap_with_abstention_is_rejected(self) -> None:
        tmp, manifest, source, bundle = self._make_inputs()
        self.addCleanup(tmp.cleanup)
        draft = _base_draft(manifest, source, bundle, "proves it converges")
        draft["request_question_plan"]["abstention_conditions"] = [
            {"subquestion_id": "sq-1", "reason": "data unavailable"}
        ]
        with self.assertRaises(module.ContractError):
            module.create_dossier(draft, bundle=bundle, source=source)

    def test_eligible_modes(self) -> None:
        tmp, manifest, source, bundle = self._make_inputs()
        self.addCleanup(tmp.cleanup)
        draft = _base_draft(manifest, source, bundle, "proves it converges")
        draft["claims"][0]["verification"] = _verification(mode="same_context_diagnostic")
        dossier = module.create_dossier(draft, bundle=bundle, source=source)
        self.assertFalse(dossier["claim_support_eligible"]["claim-001"])
        projected = module.project_report_set(dossier, bundle=bundle, source=source)
        self.assertEqual(projected["reports"][0]["projection_status"], "terminal_coverage")

    def test_access_level_or_depth_can_prevent_decisive_projection(self) -> None:
        tmp, manifest, source, bundle = self._make_inputs()
        self.addCleanup(tmp.cleanup)
        abstract_only_map = _base_draft(manifest, source, bundle, "proves it converges")
        abstract_only_map["access_level"] = "abstract_only"
        abstract_only_map["inspection_depth"] = "map"
        dossier = module.create_dossier(abstract_only_map, bundle=bundle, source=source)
        self.assertFalse(dossier["claim_support_eligible"]["claim-001"])
        projected = module.project_report_set(dossier, bundle=bundle, source=source)
        self.assertEqual(projected["reports"][0]["projection_status"], "terminal_coverage")

        independent = _base_draft(manifest, source, bundle, "proves it converges")
        independent["claims"][0]["verification"] = _verification(mode="independent_source_check")
        independent_dossier = module.create_dossier(independent, bundle=bundle, source=source)
        self.assertTrue(independent_dossier["claim_support_eligible"]["claim-001"])
        independent_projected = module.project_report_set(independent_dossier, bundle=bundle, source=source)
        self.assertFalse(independent_projected["reports"][0]["claim_support_eligible"])
        self.assertEqual(
            independent_projected["reports"][0]["projection_status"],
            "terminal_coverage",
        )

    def test_claim_and_evidence_scope_must_match(self) -> None:
        tmp, manifest, source, bundle = self._make_inputs()
        self.addCleanup(tmp.cleanup)
        draft = _base_draft(manifest, source, bundle, "proves it converges")
        draft["evidence_records"][0]["scope"]["conditions"].append("unshared")
        with self.assertRaises(module.ContractError):
            module.create_dossier(draft, bundle=bundle, source=source)

    def test_validate_and_project_reject_tampered_computed_fields(self) -> None:
        tmp, manifest, source, bundle = self._make_inputs()
        self.addCleanup(tmp.cleanup)
        draft = _base_draft(manifest, source, bundle, "proves it converges")
        draft["claims"][0]["verification"] = _verification(mode="same_context_diagnostic")
        dossier = module.create_dossier(draft, bundle=bundle, source=source)

        tamper_cases = [
            ("dossier_id", "b" * 16),
            ("dossier_digest", "0" * 64),
            (
                "claim_support_eligible",
                {key: (not value) for key, value in dossier["claim_support_eligible"].items()},
            ),
            (
                "gates",
                {**dossier["gates"], "any_claim_eligible": not dossier["gates"]["any_claim_eligible"]},
            ),
            (
                "completion_matrix",
                {
                    "subquestions": {
                        **dossier["completion_matrix"]["subquestions"],
                        "answered": 0,
                    },
                    "claims": dossier["completion_matrix"]["claims"],
                    "evidence": dossier["completion_matrix"]["evidence"],
                    "components": dossier["completion_matrix"]["components"],
                },
            ),
            (
                "audit_metrics",
                {**dossier["audit_metrics"], "eligible_claims": dossier["audit_metrics"]["eligible_claims"] + 1},
            ),
            ("unresolved_terminal_states", []),
        ]
        for field, value in tamper_cases:
            tampered = copy.deepcopy(dossier)
            tampered[field] = value
            with self.assertRaises(module.ContractError):
                module.validate_dossier(tampered, bundle=bundle, source=source)
            with self.assertRaises(module.ContractError):
                module.project_report_set(tampered, bundle=bundle, source=source)

    def test_verified_claim_citation_locator_and_scope_must_match_evidence(self) -> None:
        tmp, manifest, source, bundle = self._make_inputs()
        self.addCleanup(tmp.cleanup)
        draft = _base_draft(manifest, source, bundle, "proves it converges")
        locator = module.locate_span(
            bundle=bundle,
            page=1,
            start_char=draft["evidence_records"][0]["start_char"],
            end_char=draft["evidence_records"][0]["end_char"],
        )["exact_locator"]
        draft["claims"][0]["citation_chain"] = [
            {
                "citation_id": "cite-001",
                "evidence_id": "evidence-001",
                "exact_locator": locator,
                "verified": True,
                "scope": draft["claims"][0]["scope"],
            }
        ]

        with self.assertRaises(module.ContractError):
            bad_locator = copy.deepcopy(draft)
            bad_locator["claims"][0]["citation_chain"][0]["exact_locator"] = "legacy locator"
            module.create_dossier(bad_locator, bundle=bundle, source=source)

        with self.assertRaises(module.ContractError):
            bad_scope = copy.deepcopy(draft)
            bad_scope["claims"][0]["citation_chain"][0]["scope"]["conditions"].append("extra")
            module.create_dossier(bad_scope, bundle=bundle, source=source)

        module.create_dossier(draft, bundle=bundle, source=source)

    def test_fully_unanswerable_dossier_projects_terminal_coverage(self) -> None:
        tmp, manifest, source, bundle = self._make_inputs()
        self.addCleanup(tmp.cleanup)
        draft = _base_draft(manifest, source, bundle, "proves it converges")
        draft["request_question_plan"]["abstention_conditions"] = [
            {"subquestion_id": "sq-1", "reason": "dataset and script withheld"}
        ]
        draft["claims"][0]["verifier_status"] = "unresolved"
        draft["claims"][0]["relation"] = "not_tested"
        draft["claims"][0]["confidence"] = "low"
        draft["claims"][0]["evidence_ids"] = []
        draft["claims"][0]["subquestion_id"] = None
        draft["claims"][0]["reconstruction_task_ids"] = []
        draft["evidence_records"] = []
        draft["reconstruction_tasks"] = []
        draft["claims"].append(
            {
                "claim_id": "claim-002",
                "hypothesis_id": "hyp-002",
                "target_id": "target-002",
                "statement": "The method remains unresolved for a secondary objective.",
                "relation": "not_tested",
                "origin": "source",
                "scope": {
                    "assumptions": [],
                    "conditions": [],
                    "units": [],
                    "exclusions": [],
                },
                "verifier_status": "unresolved",
                "confidence": "low",
                "evidence_ids": [],
                "subquestion_id": None,
                "reconstruction_task_ids": [],
                "citation_chain": [],
                "verification": _verification(mode="same_context_diagnostic"),
            }
        )
        dossier = module.create_dossier(draft, bundle=bundle, source=source)
        self.assertFalse(dossier["claim_support_eligible"]["claim-001"])
        self.assertFalse(dossier["claim_support_eligible"]["claim-002"])

        projected = module.project_report_set(dossier, bundle=bundle, source=source)
        self.assertEqual(projected["dossier_id"], dossier["dossier_id"])
        self.assertEqual(projected["dossier_digest"], dossier["dossier_digest"])
        for report in projected["reports"]:
            self.assertFalse(report["claim_support_eligible"])
            self.assertIn(report["claim_id"], {"claim-001", "claim-002"})
            self.assertEqual(report["projection_status"], "terminal_coverage")
            self.assertIsNone(report["actual_evidence_locator"])
            self.assertEqual(report["evidence_ids"], [])
            self.assertEqual(report["evidence_bindings"], [])

    def test_exact_locator_rejects_doi_url(self) -> None:
        tmp, manifest, source, bundle = self._make_inputs()
        self.addCleanup(tmp.cleanup)
        draft = _base_draft(manifest, source, bundle, "proves it converges")
        draft["evidence_records"][0]["exact_locator"] = "https://example.com/paper#fig"
        with self.assertRaises(module.ContractError):
            module.create_dossier(draft, bundle=bundle, source=source)

        draft = _base_draft(manifest, source, bundle, "proves it converges")
        draft["evidence_records"][0]["exact_locator"] = "10.1000/abc"
        with self.assertRaises(module.ContractError):
            module.create_dossier(draft, bundle=bundle, source=source)

    def test_roundtrip_is_idempotent(self) -> None:
        tmp, manifest, source, bundle = self._make_inputs()
        self.addCleanup(tmp.cleanup)
        draft = _base_draft(manifest, source, bundle, "proves it converges")
        dossier = module.create_dossier(draft, bundle=bundle, source=source)
        revalidated = module.validate_dossier(dossier, bundle=bundle, source=source)
        self.assertEqual(dossier["dossier_id"], revalidated["dossier_id"])
        self.assertEqual(dossier["dossier_digest"], revalidated["dossier_digest"])
        self.assertEqual(dossier["claim_support_eligible"], revalidated["claim_support_eligible"])

    def test_v2_digest_tamper_rejected(self) -> None:
        tmp, manifest, source, bundle = self._make_inputs()
        self.addCleanup(tmp.cleanup)
        draft = _base_draft(manifest, source, bundle, "proves it converges")
        dossier = module.create_dossier(draft, bundle=bundle, source=source)
        v2 = module.project_report_set(dossier, bundle=bundle, source=source)
        v2["report_set_digest"] = "0" * 64
        with self.assertRaises(module.ContractError):
            module.validate_report_set_v2(v2)

    def test_v2_projection_bindings(self) -> None:
        tmp, manifest, source, bundle = self._make_inputs()
        self.addCleanup(tmp.cleanup)
        draft = _base_draft(manifest, source, bundle, "proves it converges")
        draft["claims"].append(
            {
                "claim_id": "claim-002",
                "hypothesis_id": "hyp-002",
                "target_id": "target-002",
                "statement": "The method is unbiased.",
                "relation": "not_tested",
                "origin": "source",
                "scope": {
                    "assumptions": [],
                    "conditions": [],
                    "units": [],
                    "exclusions": [],
                },
                "verifier_status": "unresolved",
                "confidence": "low",
                "evidence_ids": [],
                "subquestion_id": "sq-1",
                "reconstruction_task_ids": [],
                "citation_chain": [],
                "verification": _verification(mode="same_context_diagnostic"),
            }
        )
        draft["evidence_records"].append(
            {
                "evidence_id": "evidence-002",
                "claim_id": "claim-001",
                "hypothesis_id": "hyp-001",
                "target_id": "target-001",
                "page": 1,
                "start_char": 0,
                "end_char": 3,
                "relation": "supports",
                "verifier_status": "passed",
                "exact_locator": "main p.1",
                "card_type": "page",
                "origin": "source",
                "scope": {"assumptions": [], "conditions": [], "units": [], "exclusions": []},
                "document_id": "doc-main",
                "span_hash": module.locate_span(bundle=bundle, page=1, start_char=0, end_char=3)["span_hash"],
                "span_id": module.locate_span(bundle=bundle, page=1, start_char=0, end_char=3)["span_id"],
                "card": {},
                "reconstruction_task_ids": [],
                "citation_chain": [],
            }
        )
        dossier = module.create_dossier(draft, bundle=bundle, source=source)
        projected = module.project_report_set(dossier, bundle=bundle, source=source)
        self.assertEqual(projected["source_bundle_id"], manifest["bundle_id"])
        self.assertEqual(projected["source_bundle_digest"], manifest["bundle_digest"])
        self.assertEqual(projected["access_level"], "full_text")
        self.assertEqual(projected["dossier_id"], dossier["dossier_id"])
        self.assertEqual(projected["dossier_digest"], dossier["dossier_digest"])
        claims_status = {report["claim_id"]: report["projection_status"] for report in projected["reports"]}
        self.assertEqual(claims_status["claim-001"], "terminal_coverage")
        self.assertEqual(claims_status["claim-002"], "terminal_coverage")
        report_001 = [r for r in projected["reports"] if r["claim_id"] == "claim-001"][0]
        self.assertFalse(report_001["claim_support_eligible"])
        self.assertEqual(report_001["hypothesis_id"], "hyp-001")
        self.assertEqual(report_001["target_id"], "target-001")
        self.assertEqual(report_001["claim_statement"], "The method converges under stated assumptions.")
        self.assertEqual(report_001["evidence_relation"], "supports")
        self.assertEqual(report_001["verification"], draft["claims"][0]["verification"])
        self.assertEqual(report_001["source_bundle_id"], manifest["bundle_id"])
        self.assertIsInstance(report_001["actual_evidence_locator"], str)
        self.assertIsInstance(report_001["evidence_bindings"], list)
        self.assertEqual(len(report_001["evidence_bindings"]), 1)
        binding = report_001["evidence_bindings"][0]
        self.assertEqual(binding["evidence_id"], "evidence-001")
        self.assertEqual(binding["exact_locator"], report_001["actual_evidence_locator"])
        self.assertEqual(binding["page"], 1)
        self.assertGreaterEqual(binding["end_char"], binding["start_char"])
        self.assertRegex(binding["span_id"], r"^source-passages-span-[0-9a-f]{16}$")
        self.assertEqual(len(binding["span_hash"]), 64)

    def test_projected_reports_preserve_review_source(self) -> None:
        tmp, manifest, source, bundle = self._make_inputs()
        self.addCleanup(tmp.cleanup)
        draft = _base_draft(manifest, source, bundle, "proves it converges")
        dossier = module.create_dossier(draft, bundle=bundle, source=source)
        projected = module.project_report_set(dossier, bundle=bundle, source=source)

        self.assertEqual(
            projected["review_source"],
            {
                "source_id": "SRC-001",
                "source_digest": "c" * 64,
                "acquisition_locator": "doi:10.1000/xyz",
            },
        )
        for report in projected["reports"]:
            self.assertEqual(report["source_ref"], manifest["source"]["name"])
            self.assertEqual(report["source_artifact_sha256"], manifest["source"]["source_sha256"])
            self.assertEqual(report["review_source"], projected["review_source"])

    def test_validate_report_set_rejects_evidence_binding_mismatch(self) -> None:
        tmp, manifest, source, bundle = self._make_inputs()
        self.addCleanup(tmp.cleanup)
        draft = _base_draft(manifest, source, bundle, "proves it converges")
        dossier = module.create_dossier(draft, bundle=bundle, source=source)
        projected = module.project_report_set(dossier, bundle=bundle, source=source)
        tampered = copy.deepcopy(projected)
        tampered["reports"][0]["evidence_bindings"][0]["evidence_id"] = "evidence-missing"
        with self.assertRaises(module.ContractError):
            module.validate_report_set_v2(tampered)

    def test_validate_report_set_rejects_review_source_tamper(self) -> None:
        tmp, manifest, source, bundle = self._make_inputs()
        self.addCleanup(tmp.cleanup)
        draft = _base_draft(manifest, source, bundle, "proves it converges")
        dossier = module.create_dossier(draft, bundle=bundle, source=source)
        projected = module.project_report_set(dossier, bundle=bundle, source=source)
        tampered = copy.deepcopy(projected)
        tampered["review_source"]["source_id"] = "SRC-TAMPERED"
        with self.assertRaises(module.ContractError):
            module.validate_report_set_v2(tampered)

    def test_validate_report_set_rejects_actual_locator_mismatch(self) -> None:
        tmp, manifest, source, bundle = self._make_inputs()
        self.addCleanup(tmp.cleanup)
        draft = _base_draft(manifest, source, bundle, "proves it converges")
        dossier = module.create_dossier(draft, bundle=bundle, source=source)
        projected = module.project_report_set(dossier, bundle=bundle, source=source)
        tampered = copy.deepcopy(projected)
        tampered["reports"][0]["actual_evidence_locator"] = "main p.99"
        with self.assertRaises(module.ContractError):
            module.validate_report_set_v2(tampered)

    def test_validate_report_set_rejects_source_ref_substitution(self) -> None:
        tmp, manifest, source, bundle = self._make_inputs()
        self.addCleanup(tmp.cleanup)
        draft = _base_draft(manifest, source, bundle, "proves it converges")
        dossier = module.create_dossier(draft, bundle=bundle, source=source)
        projected = module.project_report_set(dossier, bundle=bundle, source=source)
        tampered = copy.deepcopy(projected)
        tampered["source_ref"] = "other-paper.txt"
        with self.assertRaises(module.ContractError):
            module.validate_report_set_v2(tampered)

    def test_prepare_attestations_command(self) -> None:
        tmp, manifest, source, bundle = self._make_inputs()
        self.addCleanup(tmp.cleanup)
        draft = _base_draft(manifest, source, bundle, "proves it converges")
        dossier = module.create_dossier(draft, bundle=bundle, source=source)
        dossier_path = Path(tmp.name) / "dossier.json"
        output_path = Path(tmp.name) / "report-set.json"
        attested_path = Path(tmp.name) / "attested-report-set.json"
        verification_root = Path(tmp.name) / "verification"
        dossier_path.write_text(json.dumps(dossier), encoding="utf-8")

        rc = module.main(
            [
                "prepare-attestations",
                "--input",
                str(dossier_path),
                "--output",
                str(output_path),
                "--bundle",
                bundle,
                "--source",
                source,
                "--producer-context-id",
                "producer-context-001",
                "--verification-root",
                str(verification_root),
            ]
        )
        self.assertEqual(rc, 0)
        projected = json.loads(output_path.read_text(encoding="utf-8"))
        self.assertEqual(len(projected["reports"]), 1)

        report = projected["reports"][0]
        verification = report["verification"]
        self.assertEqual(
            set(verification),
            {
                "mode",
                "verifier_id",
                "artifact_ref",
                "artifact_sha256",
                "subject_digest",
            },
        )
        request_ref = verification["artifact_ref"]
        artifact_path = verification_root / request_ref
        self.assertTrue(artifact_path.exists())
        request_payload = json.loads(artifact_path.read_text(encoding="utf-8"))
        self.assertEqual(
            verification["artifact_sha256"],
            hashlib.sha256(artifact_path.read_bytes()).hexdigest(),
        )
        self.assertEqual(
            request_payload["subject_digest"],
            module.canonical_report_subject_digest(report),
        )
        self.assertEqual(request_payload["verifier_id"], verification["verifier_id"])
        self.assertEqual(request_payload["schema"], module.VERIFICATION_REQUEST_SCHEMA)
        self.assertTrue(request_payload["support_candidate_eligible"])
        self.assertNotIn("verdict", request_payload)
        self.assertRegex(
            request_ref,
            r"^verification-requests/[0-9a-f]{64}\.json$",
        )
        self.assertEqual(artifact_path.read_bytes(), module.canonical_json_bytes(request_payload) + b"\n")
        self.assertFalse(report["claim_support_eligible"])
        self.assertEqual(report["projection_status"], "terminal_coverage")
        module.validate_report_set_v2(projected, verification_root=verification_root)

        rc = module.main(
            [
                "attest",
                "--input",
                str(output_path),
                "--output",
                str(attested_path),
                "--verification-root",
                str(verification_root),
                "--mode",
                "independent_source_check",
                "--verifier-id",
                "external-verifier-001",
                "--verdict",
                "passed",
                "--basis",
                "manual review",
                "--verifier-context-id",
                "external-verifier-001",
            ]
        )
        self.assertEqual(rc, 0)
        attested = json.loads(attested_path.read_text(encoding="utf-8"))
        self.assertEqual(len(attested["reports"]), 1)

        attested_report = attested["reports"][0]
        attestation_binding = attested_report["verification"]
        self.assertEqual(set(attestation_binding), set(verification))
        self.assertEqual(attestation_binding["verifier_id"], "external-verifier-001")
        attestation_path = verification_root / attestation_binding["artifact_ref"]
        self.assertTrue(attestation_path.exists())
        attestation_payload = json.loads(
            attestation_path.read_text(encoding="utf-8")
        )
        self.assertEqual(
            attestation_binding["artifact_sha256"],
            hashlib.sha256(attestation_path.read_bytes()).hexdigest(),
        )
        self.assertEqual(attestation_payload["schema"], module.VERIFICATION_ATTESTATION_SCHEMA)
        self.assertEqual(attestation_payload["origin"], "external_verifier")
        self.assertEqual(attestation_payload["verdict"], "passed")
        self.assertEqual(attestation_payload["verifier_context_id"], "external-verifier-001")
        self.assertEqual(
            attestation_payload["subject_digest"],
            verification["subject_digest"],
        )
        self.assertEqual(
            attestation_payload["request_digest"],
            verification["artifact_sha256"],
        )
        self.assertEqual(attestation_payload["evidence_bindings"], report["evidence_bindings"])
        self.assertFalse(attested_report["claim_support_eligible"])
        self.assertEqual(attested_report["projection_status"], "terminal_coverage")

        finalized_path = Path(tmp.name) / "finalized-report-set.json"
        rc = module.main(
            [
                "finalize-attestations",
                "--input",
                str(attested_path),
                "--output",
                str(finalized_path),
                "--verification-root",
                str(verification_root),
            ]
        )
        self.assertEqual(rc, 0)
        finalized = json.loads(finalized_path.read_text(encoding="utf-8"))
        self.assertTrue(finalized["reports"][0]["claim_support_eligible"])
        self.assertEqual(finalized["reports"][0]["projection_status"], "decisive")
        self.assertEqual(finalized["reports"][0]["verification"], attestation_binding)
        module.validate_report_set_v2(finalized, verification_root=verification_root, require_finalized=True)

        finalized_again_path = Path(tmp.name) / "finalized-report-set-again.json"
        rc = module.main(
            [
                "finalize-attestations",
                "--input",
                str(attested_path),
                "--output",
                str(finalized_again_path),
                "--verification-root",
                str(verification_root),
            ]
        )
        self.assertEqual(rc, 0)
        finalized_again = json.loads(finalized_again_path.read_text(encoding="utf-8"))
        self.assertEqual(finalized_again["report_set_id"], finalized["report_set_id"])
        self.assertEqual(finalized_again["report_set_digest"], finalized["report_set_digest"])

    def test_self_mint_attestations_is_prevented(self) -> None:
        tmp, manifest, source, bundle = self._make_inputs()
        self.addCleanup(tmp.cleanup)
        draft = _base_draft(manifest, source, bundle, "proves it converges")
        dossier = module.create_dossier(draft, bundle=bundle, source=source)
        dossier_path = Path(tmp.name) / "dossier.json"
        output_path = Path(tmp.name) / "report-set.json"
        verification_root = Path(tmp.name) / "verification"
        dossier_path.write_text(json.dumps(dossier), encoding="utf-8")

        rc = module.main(
            [
                "prepare-attestations",
                "--input",
                str(dossier_path),
                "--output",
                str(output_path),
                "--bundle",
                bundle,
                "--source",
                source,
                "--producer-context-id",
                "producer-context-001",
                "--verification-root",
                str(verification_root),
            ]
        )
        self.assertEqual(rc, 0)
        projected = json.loads(output_path.read_text(encoding="utf-8"))
        report = projected["reports"][0]
        verification = report["verification"]
        self.assertNotIn("verdict", verification)
        self.assertEqual(report["projection_status"], "terminal_coverage")
        self.assertFalse(report["claim_support_eligible"])

        verification["verdict"] = "passed"
        report["report_digest"] = module._v2_report_digest(report)
        report["report_id"] = module._canonical_id(module.V2_REPORT_PREFIX, report["report_digest"])
        projected["report_set_digest"] = module._v2_dossier_digest(projected)
        projected["report_set_id"] = module._canonical_id(
            module.V2_SET_PREFIX,
            projected["report_set_digest"],
        )
        self_minted_path = Path(tmp.name) / "self-minted.json"
        self_minted_path.write_text(json.dumps(projected), encoding="utf-8")
        finalized_path = Path(tmp.name) / "finalized.json"
        rc = module.main(
            [
                "finalize-attestations",
                "--input",
                str(self_minted_path),
                "--output",
                str(finalized_path),
                "--verification-root",
                str(verification_root),
            ]
        )
        self.assertNotEqual(rc, 0)

    def test_attest_rejects_same_context_id(self) -> None:
        tmp, manifest, source, bundle = self._make_inputs()
        self.addCleanup(tmp.cleanup)
        draft = _base_draft(manifest, source, bundle, "proves it converges")
        dossier = module.create_dossier(draft, bundle=bundle, source=source)
        dossier_path = Path(tmp.name) / "dossier.json"
        output_path = Path(tmp.name) / "report-set.json"
        attested_path = Path(tmp.name) / "attested-report-set.json"
        verification_root = Path(tmp.name) / "verification"
        dossier_path.write_text(json.dumps(dossier), encoding="utf-8")

        rc = module.main(
            [
                "prepare-attestations",
                "--input",
                str(dossier_path),
                "--output",
                str(output_path),
                "--bundle",
                bundle,
                "--source",
                source,
                "--producer-context-id",
                "producer-context-001",
                "--verification-root",
                str(verification_root),
            ]
        )
        self.assertEqual(rc, 0)

        rc = module.main(
            [
                "attest",
                "--input",
                str(output_path),
                "--output",
                str(attested_path),
                "--verification-root",
                str(verification_root),
                "--mode",
                "independent_source_check",
                "--verifier-id",
                "external-verifier-001",
                "--verdict",
                "passed",
                "--basis",
                "manual review",
                "--verifier-context-id",
                "producer-context-001",
            ]
        )
        self.assertNotEqual(rc, 0)

    def test_finalize_attestations_rejects_tampered_attestation_artifact(self) -> None:
        tmp, manifest, source, bundle = self._make_inputs()
        self.addCleanup(tmp.cleanup)
        draft = _base_draft(manifest, source, bundle, "proves it converges")
        dossier = module.create_dossier(draft, bundle=bundle, source=source)
        dossier_path = Path(tmp.name) / "dossier.json"
        output_path = Path(tmp.name) / "report-set.json"
        attested_path = Path(tmp.name) / "attested-report-set.json"
        finalized_path = Path(tmp.name) / "finalized-report-set.json"
        verification_root = Path(tmp.name) / "verification"
        dossier_path.write_text(json.dumps(dossier), encoding="utf-8")

        rc = module.main(
            [
                "prepare-attestations",
                "--input",
                str(dossier_path),
                "--output",
                str(output_path),
                "--bundle",
                bundle,
                "--source",
                source,
                "--producer-context-id",
                "producer-context-001",
                "--verification-root",
                str(verification_root),
            ]
        )
        self.assertEqual(rc, 0)

        rc = module.main(
            [
                "attest",
                "--input",
                str(output_path),
                "--output",
                str(attested_path),
                "--verification-root",
                str(verification_root),
                "--mode",
                "independent_source_check",
                "--verifier-id",
                "external-verifier-001",
                "--verdict",
                "passed",
                "--basis",
                "manual review",
                "--verifier-context-id",
                "external-verifier-001",
            ]
        )
        self.assertEqual(rc, 0)

        attested = json.loads(attested_path.read_text(encoding="utf-8"))
        attestation = attested["reports"][0]["verification"]
        attestation_payload = json.loads(
            (verification_root / attestation["artifact_ref"]).read_text(encoding="utf-8")
        )
        attestation_payload["verdict"] = "failed"
        (verification_root / attestation["artifact_ref"]).write_bytes(
            module.canonical_json_bytes(attestation_payload) + b"\n"
        )

        rc = module.main(
            [
                "finalize-attestations",
                "--input",
                str(attested_path),
                "--output",
                str(finalized_path),
                "--verification-root",
                str(verification_root),
            ]
        )
        self.assertNotEqual(rc, 0)

    def test_finalize_attestations_rejects_missing_attestation_artifact(self) -> None:
        tmp, manifest, source, bundle = self._make_inputs()
        self.addCleanup(tmp.cleanup)
        draft = _base_draft(manifest, source, bundle, "proves it converges")
        dossier = module.create_dossier(draft, bundle=bundle, source=source)
        dossier_path = Path(tmp.name) / "dossier.json"
        output_path = Path(tmp.name) / "report-set.json"
        attested_path = Path(tmp.name) / "attested-report-set.json"
        finalized_path = Path(tmp.name) / "finalized-report-set.json"
        verification_root = Path(tmp.name) / "verification"
        dossier_path.write_text(json.dumps(dossier), encoding="utf-8")

        rc = module.main(
            [
                "prepare-attestations",
                "--input",
                str(dossier_path),
                "--output",
                str(output_path),
                "--bundle",
                bundle,
                "--source",
                source,
                "--producer-context-id",
                "producer-context-001",
                "--verification-root",
                str(verification_root),
            ]
        )
        self.assertEqual(rc, 0)

        rc = module.main(
            [
                "attest",
                "--input",
                str(output_path),
                "--output",
                str(attested_path),
                "--verification-root",
                str(verification_root),
                "--mode",
                "independent_source_check",
                "--verifier-id",
                "external-verifier-001",
                "--verdict",
                "passed",
                "--basis",
                "manual review",
                "--verifier-context-id",
                "external-verifier-001",
            ]
        )
        self.assertEqual(rc, 0)

        attestation = json.loads(attested_path.read_text(encoding="utf-8"))["reports"][0]["verification"]
        (verification_root / attestation["artifact_ref"]).unlink()
        rc = module.main(
            [
                "finalize-attestations",
                "--input",
                str(attested_path),
                "--output",
                str(finalized_path),
                "--verification-root",
                str(verification_root),
            ]
        )
        self.assertNotEqual(rc, 0)

    def test_multi_report_heterogeneous_verifiers_attest_separately(self) -> None:
        tmp, manifest, source, bundle = self._make_inputs()
        self.addCleanup(tmp.cleanup)
        draft = _base_draft(manifest, source, bundle, "proves it converges")
        second_claim = copy.deepcopy(draft["claims"][0])
        second_claim.update(
            {
                "claim_id": "claim-002",
                "hypothesis_id": "hyp-002",
                "target_id": "target-002",
                "evidence_ids": ["evidence-002"],
                "verification": {
                    "mode": "expert_review",
                    "verifier_id": "external-verifier-002",
                },
            }
        )
        second_evidence = copy.deepcopy(draft["evidence_records"][0])
        second_evidence.update(
            {
                "evidence_id": "evidence-002",
                "claim_id": "claim-002",
                "hypothesis_id": "hyp-002",
                "target_id": "target-002",
            }
        )
        draft["claims"].append(second_claim)
        draft["evidence_records"].append(second_evidence)
        dossier = module.create_dossier(draft, bundle=bundle, source=source)
        dossier_path = Path(tmp.name) / "dossier.json"
        prepared_path = Path(tmp.name) / "prepared.json"
        first_path = Path(tmp.name) / "first.json"
        second_path = Path(tmp.name) / "second.json"
        final_path = Path(tmp.name) / "final.json"
        verification_root = Path(tmp.name) / "verification"
        dossier_path.write_text(json.dumps(dossier), encoding="utf-8")
        self.assertEqual(
            module.main(
                [
                    "prepare-attestations",
                    "--input",
                    str(dossier_path),
                    "--output",
                    str(prepared_path),
                    "--bundle",
                    bundle,
                    "--source",
                    source,
                    "--producer-context-id",
                    "producer-context-001",
                    "--verification-root",
                    str(verification_root),
                ]
            ),
            0,
        )
        prepared = json.loads(prepared_path.read_text(encoding="utf-8"))
        report_ids = {report["claim_id"]: report["report_id"] for report in prepared["reports"]}
        self.assertNotEqual(
            module.main(
                [
                    "attest",
                    "--input",
                    str(prepared_path),
                    "--output",
                    str(first_path),
                    "--verification-root",
                    str(verification_root),
                    "--mode",
                    "independent_source_check",
                    "--verifier-id",
                    "external-verifier-001",
                    "--verdict",
                    "passed",
                    "--basis",
                    "first external review",
                    "--verifier-context-id",
                    "external-context-001",
                ]
            ),
            0,
        )
        self.assertEqual(
            module.main(
                [
                    "attest",
                    "--input",
                    str(prepared_path),
                    "--output",
                    str(first_path),
                    "--verification-root",
                    str(verification_root),
                    "--report-id",
                    report_ids["claim-001"],
                    "--mode",
                    "independent_source_check",
                    "--verifier-id",
                    "external-verifier-001",
                    "--verdict",
                    "passed",
                    "--basis",
                    "first external review",
                    "--verifier-context-id",
                    "external-context-001",
                ]
            ),
            0,
        )
        self.assertEqual(
            module.main(
                [
                    "attest",
                    "--input",
                    str(first_path),
                    "--output",
                    str(second_path),
                    "--verification-root",
                    str(verification_root),
                    "--report-id",
                    report_ids["claim-002"],
                    "--mode",
                    "expert_review",
                    "--verifier-id",
                    "external-verifier-002",
                    "--verdict",
                    "passed",
                    "--basis",
                    "second external review",
                    "--verifier-context-id",
                    "external-context-002",
                ]
            ),
            0,
        )
        self.assertEqual(
            module.main(
                [
                    "finalize-attestations",
                    "--input",
                    str(second_path),
                    "--output",
                    str(final_path),
                    "--verification-root",
                    str(verification_root),
                ]
            ),
            0,
        )
        finalized = json.loads(final_path.read_text(encoding="utf-8"))
        self.assertEqual(
            {report["verification"]["verifier_id"] for report in finalized["reports"]},
            {"external-verifier-001", "external-verifier-002"},
        )
        self.assertTrue(all(report["claim_support_eligible"] for report in finalized["reports"]))
        self.assertTrue(
            all(report["projection_status"] == "decisive" for report in finalized["reports"])
        )
        self.assertEqual(finalized["completion_matrix"]["claims"]["eligible"], 2)
        self.assertEqual(finalized["completion_matrix"]["claims"]["decisive"], 2)

    def test_prepared_set_rejects_retarget_duplicates_and_completion_tamper(self) -> None:
        tmp, manifest, source, bundle = self._make_inputs()
        self.addCleanup(tmp.cleanup)
        draft = _base_draft(manifest, source, bundle, "proves it converges")
        dossier = module.create_dossier(draft, bundle=bundle, source=source)
        dossier_path = Path(tmp.name) / "dossier.json"
        prepared_path = Path(tmp.name) / "prepared.json"
        verification_root = Path(tmp.name) / "verification"
        dossier_path.write_text(json.dumps(dossier), encoding="utf-8")
        self.assertEqual(
            module.main(
                [
                    "prepare-attestations",
                    "--input",
                    str(dossier_path),
                    "--output",
                    str(prepared_path),
                    "--bundle",
                    bundle,
                    "--source",
                    source,
                    "--producer-context-id",
                    "producer-context-001",
                    "--verification-root",
                    str(verification_root),
                ]
            ),
            0,
        )
        prepared = json.loads(prepared_path.read_text(encoding="utf-8"))

        retargeted = copy.deepcopy(prepared)
        retargeted["network_ref"]["network_id"] = "KN-RETARGETED"
        module._assign_report_set_identity(retargeted)
        with self.assertRaises(module.ContractError):
            module.validate_report_set_v2(retargeted, verification_root=verification_root)

        duplicate_report = copy.deepcopy(prepared)
        duplicate_report["reports"].append(copy.deepcopy(duplicate_report["reports"][0]))
        duplicate_report["completion_matrix"] = module._report_set_completion_matrix(
            duplicate_report["completion_matrix"], duplicate_report["reports"]
        )
        module._assign_report_set_identity(duplicate_report)
        with self.assertRaisesRegex(module.ContractError, "duplicate report_id"):
            module.validate_report_set_v2(duplicate_report, verification_root=verification_root)

        duplicate_claim = copy.deepcopy(prepared)
        cloned = copy.deepcopy(duplicate_claim["reports"][0])
        cloned["report_id"] = "reading-report-v2-0000000000000000"
        duplicate_claim["reports"].append(cloned)
        duplicate_claim["completion_matrix"] = module._report_set_completion_matrix(
            duplicate_claim["completion_matrix"], duplicate_claim["reports"]
        )
        module._assign_report_set_identity(duplicate_claim)
        with self.assertRaisesRegex(module.ContractError, "duplicate claim_id"):
            module.validate_report_set_v2(duplicate_claim, verification_root=verification_root)

        bad_completion = copy.deepcopy(prepared)
        bad_completion["completion_matrix"]["claims"]["total"] += 1
        module._assign_report_set_identity(bad_completion)
        with self.assertRaisesRegex(module.ContractError, "completion_matrix"):
            module.validate_report_set_v2(bad_completion, verification_root=verification_root)

    def test_verification_artifact_alias_and_fifo_are_rejected(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        verification_root = Path(tmp.name)
        request_dir = verification_root / module.VERIFICATION_REQUEST_DIR
        request_dir.mkdir(parents=True)
        fifo_ref = f"{module.VERIFICATION_REQUEST_DIR}/{'0' * 64}.json"
        os.mkfifo(verification_root / fifo_ref)
        with self.assertRaisesRegex(module.ContractError, "regular file"):
            module._read_verification_artifact(
                verification_root,
                fifo_ref,
                label="fifo request",
            )

        payload = {"schema": module.VERIFICATION_REQUEST_SCHEMA}
        payload_bytes = module.canonical_json_bytes(payload) + b"\n"
        digest = hashlib.sha256(payload_bytes).hexdigest()
        alias_ref = f"{module.VERIFICATION_REQUEST_DIR}/alias-{digest}.json"
        (verification_root / alias_ref).write_bytes(payload_bytes)
        with self.assertRaisesRegex(module.ContractError, "canonical content address"):
            module._read_verification_artifact(
                verification_root,
                alias_ref,
                label="alias request",
            )

    def test_draft_verification_rejects_artifact_envelope(self) -> None:
        tmp, manifest, source, bundle = self._make_inputs()
        self.addCleanup(tmp.cleanup)
        draft = _base_draft(manifest, source, bundle, "proves it converges")
        draft["claims"][0]["verification"].update(
            {
                "artifact_ref": f"verification-attestations/{'a' * 64}.json",
                "artifact_sha256": "a" * 64,
                "subject_digest": "b" * 64,
            }
        )
        with self.assertRaisesRegex(module.ContractError, "draft must contain only"):
            module.create_dossier(draft, bundle=bundle, source=source)

    def test_checked_dossier_example_strictly_validates(self) -> None:
        examples = Path(module.__file__).resolve().parent.parent / "examples"
        fixture = examples / "paper_reading_dossier_fixture"
        example = json.loads(
            (examples / "paper_reading_dossier.example.json").read_text(encoding="utf-8")
        )
        validated = module.validate_dossier(
            example,
            bundle=str(fixture / "bundle.json"),
            source=str(fixture / "paper.txt"),
        )
        self.assertEqual(validated, example)
        self.assertEqual(validated["dossier_id"], "reading-dossier-9062dbd8d6834502")


if __name__ == "__main__":
    main()
