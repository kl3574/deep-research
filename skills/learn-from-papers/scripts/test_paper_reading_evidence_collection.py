#!/usr/bin/env python3
"""Focused tests for PaperReadingEvidenceCollection/v1."""

from __future__ import annotations

import copy
import importlib.util
import tempfile
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest import TestCase, main, mock


SCRIPT_DIR = Path(__file__).resolve().parent


def _load(name: str, filename: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, SCRIPT_DIR / filename)
    assert spec and spec.loader
    loaded = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(loaded)
    return loaded


module = _load(
    "paper_reading_evidence_collection_under_test",
    "paper_reading_evidence_collection.py",
)
dossier_module = _load(
    "paper_reading_evidence_collection_test_dossier",
    "paper_reading_dossier.py",
)
source_bundle_module = _load(
    "paper_reading_evidence_collection_test_source_bundle",
    "paper_source_bundle.py",
)


NETWORK_REF = {
    "network_id": "KN-collection",
    "snapshot_id": "KN-collection-S001",
    "sha256": "a" * 64,
}
REQUEST_SET_REF = {
    "review_request_set_id": "RFS-collection",
    "review_request_set_digest": "b" * 64,
}


def _write_json(path: Path, payload: Any) -> None:
    path.write_bytes(dossier_module.canonical_json_bytes(payload) + b"\n")


def _draft(
    *,
    manifest: dict[str, Any],
    source_path: Path,
    bundle_path: Path,
    source_id: str,
    verifier_id: str,
    network_ref: dict[str, str],
    request_set_ref: dict[str, str],
) -> dict[str, Any]:
    phrase = "proves the scoped claim"
    source_text = source_path.read_text(encoding="utf-8")
    start = source_text.index(phrase)
    end = start + len(phrase)
    located = dossier_module.locate_span(
        bundle=str(bundle_path), page=1, start_char=start, end_char=end
    )
    scope = {
        "assumptions": ["bounded input"],
        "conditions": ["declared regime"],
        "units": ["population parameter"],
        "exclusions": ["unstated regimes"],
    }
    return {
        "schema": dossier_module.SCHEMA,
        "schema_version": dossier_module.SCHEMA_VERSION,
        "producer": dossier_module.PRODUCER,
        "protocol_version": dossier_module.PROTOCOL_VERSION,
        "generated_at": "2026-08-11T00:00:00Z",
        "request_question_plan": {
            "request_text": "Check one scoped claim.",
            "subquestions": [
                {
                    "subquestion_id": f"sq-{source_id}",
                    "text": "Is the scoped claim supported?",
                    "required": True,
                }
            ],
            "abstention_conditions": [],
        },
        "source_bundle": {
            "bundle_id": manifest["bundle_id"],
            "bundle_digest": manifest["bundle_digest"],
            "source_ref": source_path.name,
            "source_artifact_sha256": manifest["source"]["source_sha256"],
        },
        "review_source": {
            "source_id": source_id,
            "source_digest": manifest["source"]["source_sha256"],
            "acquisition_locator": f"local:{source_id}",
        },
        "network_ref": copy.deepcopy(network_ref),
        "review_request_set_id": request_set_ref["review_request_set_id"],
        "review_request_set_digest": request_set_ref["review_request_set_digest"],
        "review_request_id": f"RR-{source_id}",
        "review_request_digest": "c" * 64,
        "access_level": "full_text",
        "inspection_depth": "evidence",
        "reconstruction_status": "planned",
        "embedded_documents": [
            {"document_id": f"doc-{source_id}", "instruction": "Source only."}
        ],
        "component_manifest": [
            {
                "component_id": f"component-{source_id}",
                "name": "main",
                "artifact": source_path.name,
                "status": "covered",
                "inspected_units": 1,
                "covered_units": 1,
                "terminal_units": 0,
                "document_id": f"doc-{source_id}",
            }
        ],
        "claims": [
            {
                "claim_id": f"claim-{source_id}",
                "hypothesis_id": "KGH-collection",
                "target_id": "target-collection",
                "statement": "The source proves the scoped claim.",
                "relation": "supports",
                "origin": "source",
                "scope": scope,
                "verifier_status": "passed",
                "confidence": "medium",
                "evidence_ids": [f"evidence-{source_id}"],
                "subquestion_id": f"sq-{source_id}",
                "verification": {
                    "mode": "independent_source_check",
                    "verifier_id": verifier_id,
                },
                "reconstruction_task_ids": [],
                "citation_chain": [],
            }
        ],
        "evidence_records": [
            {
                "evidence_id": f"evidence-{source_id}",
                "claim_id": f"claim-{source_id}",
                "hypothesis_id": "KGH-collection",
                "target_id": "target-collection",
                "page": 1,
                "start_char": start,
                "end_char": end,
                "relation": "supports",
                "verifier_status": "passed",
                "exact_locator": located["exact_locator"],
                "card_type": "page",
                "origin": "source",
                "scope": scope,
                "document_id": f"doc-{source_id}",
                "span_hash": located["span_hash"],
                "span_id": located["span_id"],
                "card": {},
                "reconstruction_task_ids": [],
                "citation_chain": [],
            }
        ],
        "reconstruction_tasks": [],
        "correction_log": [],
        "unresolved_terminal_states": [],
    }


def _make_group(
    root: Path,
    *,
    source_id: str,
    verifier_id: str,
    source_text: str,
    network_ref: dict[str, str] | None = None,
    request_set_ref: dict[str, str] | None = None,
) -> dict[str, Any]:
    root.mkdir()
    source_path = root / "paper.txt"
    source_path.write_text(source_text, encoding="utf-8")
    bundle_path = root / "source-bundle.json"
    manifest = source_bundle_module.build_bundle(
        source=str(source_path),
        output=str(bundle_path),
        generated_at="2026-08-11T00:00:00Z",
    )
    draft = _draft(
        manifest=manifest,
        source_path=source_path,
        bundle_path=bundle_path,
        source_id=source_id,
        verifier_id=verifier_id,
        network_ref=network_ref or NETWORK_REF,
        request_set_ref=request_set_ref or REQUEST_SET_REF,
    )
    dossier = dossier_module.create_dossier(
        draft, bundle=str(bundle_path), source=str(source_path)
    )
    dossier_path = root / "dossier.json"
    _write_json(dossier_path, dossier)
    verification_root = root / "verification"
    prepared_path = root / "report-set.prepared.json"
    attested_path = root / "report-set.attested.json"
    finalized_path = root / "report-set.finalized.json"
    assert (
        dossier_module.main(
            [
                "prepare-attestations",
                "--input",
                str(dossier_path),
                "--output",
                str(prepared_path),
                "--bundle",
                str(bundle_path),
                "--source",
                str(source_path),
                "--producer-context-id",
                f"producer-{source_id}",
                "--verification-root",
                str(verification_root),
                "--generated-at",
                "2026-08-11T00:00:00Z",
            ]
        )
        == 0
    )
    assert (
        dossier_module.main(
            [
                "attest",
                "--input",
                str(prepared_path),
                "--output",
                str(attested_path),
                "--verification-root",
                str(verification_root),
                "--mode",
                "independent_source_check",
                "--verifier-id",
                verifier_id,
                "--verdict",
                "passed",
                "--basis",
                "independent fixture review",
                "--verifier-context-id",
                f"verifier-context-{source_id}",
            ]
        )
        == 0
    )
    assert (
        dossier_module.main(
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
        == 0
    )
    return {
        "spec": {
            "reading_reports": str(finalized_path.resolve()),
            "dossier": str(dossier_path.resolve()),
            "source_bundle": str(bundle_path.resolve()),
            "source_artifact": str(source_path.resolve()),
            "verification_root": str(verification_root.resolve()),
        },
        "prepared_path": prepared_path,
        "finalized_path": finalized_path,
        "verification_root": verification_root,
    }


class PaperReadingEvidenceCollectionTests(TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()

    def _two_groups(self) -> tuple[dict[str, Any], dict[str, Any]]:
        first = _make_group(
            self.root / "group-a",
            source_id="SRC-A",
            verifier_id="verifier-a",
            source_text="Source A proves the scoped claim with context.",
        )
        second = _make_group(
            self.root / "group-b",
            source_id="SRC-B",
            verifier_id="verifier-b",
            source_text="Source B independently proves the scoped claim.",
        )
        return first, second

    def test_build_and_validate_roundtrip(self) -> None:
        first, second = self._two_groups()
        collection = module.build_collection([second["spec"], first["spec"]])
        validated = module.validate_collection(collection)

        self.assertEqual(validated, collection)
        self.assertEqual(validated["schema"], module.SCHEMA)
        self.assertEqual(validated["schema_version"], module.SCHEMA_VERSION)
        self.assertEqual(len(validated["reading_groups"]), 2)
        self.assertEqual(validated["network_ref"], NETWORK_REF)
        self.assertEqual(validated["review_request_set_ref"], REQUEST_SET_REF)
        self.assertEqual(
            [group["source_ref"]["source_id"] for group in validated["reading_groups"]],
            ["SRC-A", "SRC-B"],
        )
        for group in validated["reading_groups"]:
            self.assertEqual(
                group["reading_group_digest"],
                module.canonical_group_digest(group),
            )
            for ref in group["refs"].values():
                self.assertTrue(Path(ref["path"]).is_absolute())

    def test_missing_second_group_fails(self) -> None:
        first = _make_group(
            self.root / "group-a",
            source_id="SRC-A",
            verifier_id="verifier-a",
            source_text="Source A proves the scoped claim.",
        )
        with self.assertRaisesRegex(module.ContractError, "at least two"):
            module.build_collection([first["spec"]])

    def test_duplicate_source_id_fails_even_with_different_verifiers(self) -> None:
        first = _make_group(
            self.root / "group-a",
            source_id="SRC-SAME",
            verifier_id="verifier-a",
            source_text="Source A proves the scoped claim.",
        )
        second = _make_group(
            self.root / "group-b",
            source_id="SRC-SAME",
            verifier_id="verifier-b",
            source_text="Different bytes prove and proves the scoped claim.",
        )
        with self.assertRaisesRegex(module.ContractError, "source_id"):
            module.build_collection([first["spec"], second["spec"]])

    def test_two_verifiers_over_same_source_bytes_fail(self) -> None:
        text = "The same source proves the scoped claim."
        first = _make_group(
            self.root / "group-a",
            source_id="SRC-A",
            verifier_id="verifier-a",
            source_text=text,
        )
        second = _make_group(
            self.root / "group-b",
            source_id="SRC-B",
            verifier_id="verifier-b",
            source_text=text,
        )
        with self.assertRaisesRegex(module.ContractError, "source_digest"):
            module.build_collection([first["spec"], second["spec"]])

    def test_symlink_reference_fails(self) -> None:
        first, second = self._two_groups()
        alias = self.root / "report-set-alias.json"
        alias.symlink_to(first["finalized_path"])
        first_spec = copy.deepcopy(first["spec"])
        first_spec["reading_reports"] = str(alias)
        with self.assertRaisesRegex(module.ContractError, "symlink"):
            module.build_collection([first_spec, second["spec"]])

    def test_file_hash_drift_fails_validation(self) -> None:
        first, second = self._two_groups()
        collection = module.build_collection([first["spec"], second["spec"]])
        with first["finalized_path"].open("ab") as stream:
            stream.write(b" ")
        with self.assertRaisesRegex(module.ContractError, "sha256"):
            module.validate_collection(collection)

    def test_stable_read_rejects_ctime_drift_even_if_size_and_mtime_match(
        self,
    ) -> None:
        path = self.root / "stable-read.txt"
        path.write_bytes(b"same-size-payload")
        before = path.stat()
        changed = SimpleNamespace(
            st_dev=before.st_dev,
            st_ino=before.st_ino,
            st_mode=before.st_mode,
            st_size=before.st_size,
            st_mtime_ns=before.st_mtime_ns,
            st_ctime_ns=before.st_ctime_ns + 1,
        )
        with mock.patch.object(module.os, "stat", side_effect=[before, changed]):
            with self.assertRaisesRegex(module.ContractError, "changed while"):
                module._read_regular_file(path, "stable read fixture")

    def test_verification_tree_drift_fails_validation(self) -> None:
        first, second = self._two_groups()
        collection = module.build_collection([first["spec"], second["spec"]])
        (first["verification_root"] / "unexpected.txt").write_text(
            "drift", encoding="utf-8"
        )
        with self.assertRaisesRegex(module.ContractError, "tree_digest"):
            module.validate_collection(collection)

    def test_mixed_network_fails(self) -> None:
        first = _make_group(
            self.root / "group-a",
            source_id="SRC-A",
            verifier_id="verifier-a",
            source_text="Source A proves the scoped claim.",
        )
        other_network = {**NETWORK_REF, "snapshot_id": "KN-collection-S002"}
        second = _make_group(
            self.root / "group-b",
            source_id="SRC-B",
            verifier_id="verifier-b",
            source_text="Source B proves the scoped claim.",
            network_ref=other_network,
        )
        with self.assertRaisesRegex(module.ContractError, "mixed network_ref"):
            module.build_collection([first["spec"], second["spec"]])

    def test_mixed_review_request_set_fails(self) -> None:
        first = _make_group(
            self.root / "group-a",
            source_id="SRC-A",
            verifier_id="verifier-a",
            source_text="Source A proves the scoped claim.",
        )
        other_request = {
            **REQUEST_SET_REF,
            "review_request_set_id": "RFS-other",
        }
        second = _make_group(
            self.root / "group-b",
            source_id="SRC-B",
            verifier_id="verifier-b",
            source_text="Source B proves the scoped claim.",
            request_set_ref=other_request,
        )
        with self.assertRaisesRegex(
            module.ContractError, "mixed review_request_set_ref"
        ):
            module.build_collection([first["spec"], second["spec"]])

    def test_nonfinalized_report_set_fails(self) -> None:
        first, second = self._two_groups()
        first_spec = copy.deepcopy(first["spec"])
        first_spec["reading_reports"] = str(first["prepared_path"].resolve())
        with self.assertRaisesRegex(module.ContractError, "finalized|attestation"):
            module.build_collection([first_spec, second["spec"]])

    def test_noncanonical_group_order_fails_even_with_recomputed_collection_id(
        self,
    ) -> None:
        first, second = self._two_groups()
        collection = module.build_collection([first["spec"], second["spec"]])
        tampered = copy.deepcopy(collection)
        tampered["reading_groups"].reverse()
        tampered["collection_digest"] = module.canonical_collection_digest(tampered)
        tampered["collection_id"] = (
            "paper-reading-evidence-collection-" + tampered["collection_digest"][:16]
        )
        with self.assertRaisesRegex(module.ContractError, "canonical order"):
            module.validate_collection(tampered)

    def test_duplicate_report_set_fails(self) -> None:
        first = _make_group(
            self.root / "group-a",
            source_id="SRC-A",
            verifier_id="verifier-a",
            source_text="Source A proves the scoped claim.",
        )
        with self.assertRaisesRegex(
            module.ContractError, "reading_group_id|report_set_id"
        ):
            module.build_collection([first["spec"], copy.deepcopy(first["spec"])])


if __name__ == "__main__":
    main()
