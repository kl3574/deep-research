#!/usr/bin/env python3

from __future__ import annotations

import copy
from pathlib import Path
import tempfile
import unittest

import verify_curation_batch as verify


class CurationBatchTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.bundle = self.root / "bundle.json"
        self.bundle.write_text('{"native_bundle":true}\n', encoding="utf-8")
        self.pdf = self.root / "paper.pdf"
        self.pdf.write_bytes(b"%PDF-1.4\nfixture\n")
        self.note = self.root / "note.html"
        headings = "".join(
            f"<h2>{heading}</h2><p>x</p>" for heading in verify.NOTE_SECTIONS
        )
        self.note.write_text(
            f'<div data-schema-version="9">{headings}</div>',
            encoding="utf-8",
        )
        self.target = {
            "group_id": 1234567,
            "library_id": 2,
            "library_name": "Example Research Library",
            "collection_key": "COLL0001",
            "collection_path": ["Research", "Inverse Problems", "Calibration"],
        }
        identity = verify.compute_identity_fingerprint(self.target)
        self.fingerprint = {
            "identity_sha256": identity,
            "state_sha256": verify.compute_state_fingerprint(
                identity, 12, ["ABCDEFGH"]
            ),
            "captured_at": "2026-08-04T00:00:00+08:00",
            "collection_version": 12,
            "top_level_parent_keys": ["ABCDEFGH"],
        }

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def entry(self, entry_id: str = "paper-1") -> dict[str, object]:
        return {
            "entry_id": entry_id,
            "canonical_identity": {
                "type": "doi",
                "value": "10.1000/example",
            },
            "decision": "create_parent",
            "handler": "import_zotero_bundle",
            "gate_status": "golden",
            "fulltext_status": "fulltext_verified",
            "expected_effect": {
                "new_parent_count": 1,
                "target_membership": True,
                "note_action": "create",
                "attachment_action": "create",
            },
            "bundle_path": str(self.bundle),
            "bundle_sha256": verify.sha256_file(self.bundle),
            "note_artifact": {
                "path": str(self.note),
                "sha256": verify.sha256_file(self.note),
                "schema_version": "9",
            },
            "pdf_artifacts": [
                {
                    "path": str(self.pdf),
                    "sha256": verify.sha256_file(self.pdf),
                    "artifact_role": "version_of_record",
                    "counts_as_fulltext": True,
                }
            ],
        }

    def batch(self) -> dict[str, object]:
        return {
            "schema": "CurationBatch/v1",
            "batch_id": "test-batch",
            "created_at": "2026-08-04T00:00:00+08:00",
            "target": copy.deepcopy(self.target),
            "target_fingerprint": copy.deepcopy(self.fingerprint),
            "entries": [self.entry()],
        }

    def success_execution(
        self, batch: dict[str, object]
    ) -> dict[str, object]:
        events = []
        digest = verify.digest_value(batch)
        for index, state in enumerate(verify.SUCCESS_STATES):
            event: dict[str, object] = {
                "sequence": index + 1,
                "state": state,
                "recorded_at": "2026-08-04T00:00:00+08:00",
            }
            if state == "write_authorized":
                event["evidence"] = {"approved_batch_digest": digest}
            events.append(event)
        entry = batch["entries"][0]
        return {
            "schema": "CurationExecution/v1",
            "batch_digest": digest,
            "target_identity_sha256": batch["target_fingerprint"][
                "identity_sha256"
            ],
            "initial_state_sha256": batch["target_fingerprint"][
                "state_sha256"
            ],
            "events": events,
            "results": [
                {
                    "entry_id": entry["entry_id"],
                    "status": "readback_verified",
                    "observed_effect": copy.deepcopy(entry["expected_effect"]),
                }
            ],
        }

    def test_golden_happy_path(self) -> None:
        batch = self.batch()
        self.assertEqual([], verify.validate_batch(batch))
        observed = {
            "schema": "ObservedTarget/v1",
            "target": copy.deepcopy(batch["target"]),
            "target_fingerprint": copy.deepcopy(
                batch["target_fingerprint"]
            ),
        }
        self.assertEqual(
            [], verify.validate_observed_target(observed, batch)
        )
        self.assertEqual(
            [], verify.validate_execution(self.success_execution(batch), batch)
        )

    def test_target_drift_and_schema_mismatch(self) -> None:
        batch = self.batch()
        invalid = copy.deepcopy(batch)
        invalid["schema"] = "CurationBatch/v2"
        self.assertTrue(
            any("schema_mismatch" in value for value in verify.validate_batch(invalid))
        )
        observed = {
            "schema": "ObservedTarget/v1",
            "target": copy.deepcopy(batch["target"]),
            "target_fingerprint": copy.deepcopy(
                batch["target_fingerprint"]
            ),
        }
        observed["target_fingerprint"]["collection_version"] = 13
        observed["target_fingerprint"][
            "state_sha256"
        ] = verify.compute_state_fingerprint(
            observed["target_fingerprint"]["identity_sha256"],
            13,
            ["ABCDEFGH"],
        )
        self.assertTrue(
            any(
                "target_drift" in value
                for value in verify.validate_observed_target(observed, batch)
            )
        )

    def test_si_only_and_duplicate_identity_are_rejected(self) -> None:
        batch = self.batch()
        batch["entries"][0]["pdf_artifacts"][0][
            "artifact_role"
        ] = "supporting_information"
        errors = verify.validate_batch(batch)
        self.assertTrue(
            any("cannot count as full text" in value for value in errors)
        )
        self.assertTrue(
            any("requires a verified main-text" in value for value in errors)
        )
        batch = self.batch()
        duplicate = self.entry("paper-2")
        batch["entries"].append(duplicate)
        self.assertTrue(
            any(
                "duplicate canonical identity" in value
                for value in verify.validate_batch(batch)
            )
        )

    def test_existing_outside_target_is_blocked_not_duplicated(self) -> None:
        batch = self.batch()
        batch["entries"][0]["existing_parent"] = {
            "key": "ZXCVBNMA",
            "version": 4,
            "in_target": False,
        }
        errors = verify.validate_batch(batch)
        self.assertTrue(
            any("must never be handled by a create" in value for value in errors)
        )
        blocked = self.entry()
        for key in ("bundle_path", "bundle_sha256", "note_artifact"):
            blocked.pop(key)
        blocked["pdf_artifacts"] = []
        blocked.update(
            {
                "decision": "blocked_unsupported_operation",
                "handler": "none",
                "gate_status": "blocked",
                "fulltext_status": "metadata_only",
                "existing_parent": {
                    "key": "ZXCVBNMA",
                    "version": 4,
                    "in_target": False,
                },
                "expected_effect": {
                    "new_parent_count": 0,
                    "target_membership": False,
                    "note_action": "no_op",
                    "attachment_action": "no_op",
                },
            }
        )
        batch["entries"] = [blocked]
        self.assertEqual([], verify.validate_batch(batch))

    def test_partial_commit_and_readback_mismatch(self) -> None:
        batch = self.batch()
        second = self.entry("paper-2")
        second["canonical_identity"] = {
            "type": "doi",
            "value": "10.1000/example-2",
        }
        batch["entries"].append(second)
        digest = verify.digest_value(batch)
        events = []
        for index, state in enumerate(verify.SUCCESS_STATES[:6]):
            event: dict[str, object] = {
                "sequence": index + 1,
                "state": state,
                "recorded_at": "2026-08-04T00:00:00+08:00",
            }
            if state == "write_authorized":
                event["evidence"] = {"approved_batch_digest": digest}
            events.append(event)
        base = {
            "schema": "CurationExecution/v1",
            "batch_digest": digest,
            "target_identity_sha256": batch["target_fingerprint"][
                "identity_sha256"
            ],
            "initial_state_sha256": batch["target_fingerprint"][
                "state_sha256"
            ],
        }
        partial = {
            **base,
            "events": events
            + [
                {
                    "sequence": 7,
                    "state": "partial_commit",
                    "recorded_at": "2026-08-04T00:00:00+08:00",
                    "detail": "one committed",
                }
            ],
            "results": [
                {"entry_id": "paper-1", "status": "imported"},
                {"entry_id": "paper-2", "status": "pending"},
            ],
        }
        self.assertEqual([], verify.validate_execution(partial, batch))
        mismatch = {
            **base,
            "events": events
            + [
                {
                    "sequence": 7,
                    "state": "imported",
                    "recorded_at": "2026-08-04T00:00:00+08:00",
                },
                {
                    "sequence": 8,
                    "state": "readback_mismatch",
                    "recorded_at": "2026-08-04T00:00:00+08:00",
                    "detail": "hash differs",
                },
            ],
            "results": [
                {
                    "entry_id": "paper-1",
                    "status": "readback_mismatch",
                    "observed_effect": {"new_parent_count": 0},
                },
                {"entry_id": "paper-2", "status": "pending"},
            ],
        }
        self.assertEqual([], verify.validate_execution(mismatch, batch))


if __name__ == "__main__":
    unittest.main()
