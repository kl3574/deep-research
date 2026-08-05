#!/usr/bin/env python3

from __future__ import annotations

import hashlib
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).with_name("audit_zotero_bridge_run.py")
SPEC = importlib.util.spec_from_file_location("audit_zotero_bridge_run", SCRIPT)
assert SPEC and SPEC.loader
AUDIT = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(AUDIT)


class AuditZoteroBridgeRunTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.refs: dict[str, dict[str, str]] = {}
        self._write_json("probe", {"status": "available", "action": "probe", "result": {"plugin_version": "0.1.5", "zotero_version": "9.0.6", "execution_profiles": {"db_atomic": [], "single_attachment_import": []}, "mixed_operations": False, "attachment_batch": False}})
        self._write_receipt("canary_apply", "completed", "apply", {"commit_state": "committed", "execution_profile": "single_attachment_import"})
        self._write_receipt("canary_readback", "verified", "readback", {"all_satisfied": True})
        self._write_receipt("metadata_apply", "completed", "apply", {"commit_state": "committed", "execution_profile": "db_atomic"})
        self._write_receipt("metadata_readback", "verified", "readback", {"all_satisfied": True})
        self._write_json("attachment_summary", {"status": "completed", "results": [{"status": "verified"}]})
        self._write_receipt("negative_membership_readback", "not_applied", "readback", {"all_satisfied": False, "state": {"entries": [{"target_membership": False, "operations": [{"decision": "needs_write"}]}]}})
        self._write_json("final_acceptance", {"status": "completed_local_zotero", "operations": {"ensure_pdf_attachment": 2}, "acceptance": {"target_parent_count": 2, "nonempty_short_title_count": 2, "exactly_one_note_parent_count": 2, "nonempty_note_parent_count": 2, "local_readable_pdf_parent_count": 1, "attachment_batch_verified_count": 1}, "delivery_limits": {"local_zotero_verified": True, "pdf_cloud_sync_verified": False}})
        sources = [{"role": "zotero_corpus", "corpus_membership": "current", "title": "Paper A", "doi": "10.1/a"}, {"role": "zotero_corpus", "corpus_membership": "current", "title": "Paper B", "doi": ""}]
        self._write_json("network", {"schema": "KnowledgeNetwork/v1", "snapshot_id": "KN-S1", "corpus_snapshot": {"source": "zotero", "item_count": 2, "item_refs": ["A", "B"]}, "sources": sources})
        self._write_json("research_map", {"schema": "ResearchMap/v1", "network_snapshot_id": "KN-S1"})
        self._write_bytes("html_primary", b"<!doctype html><html><body>ok</body></html>\n", ".html")
        self._write_bytes("html_repeat", b"<!doctype html><html><body>ok</body></html>\n", ".html")

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _write_bytes(self, name: str, raw: bytes, suffix: str = ".json") -> None:
        path = self.root / f"{name}{suffix}"
        path.write_bytes(raw)
        self.refs[name] = {"path": str(path), "sha256": "sha256:" + hashlib.sha256(raw).hexdigest()}

    def _write_json(self, name: str, value: dict) -> None:
        self._write_bytes(name, json.dumps(value, sort_keys=True).encode())

    def _write_receipt(self, name: str, status: str, action: str, result: dict) -> None:
        self._write_json(name, {"status": status, "action": action, "result": result})

    def pack(self) -> dict:
        value = {"schema": AUDIT.SCHEMA, "expected": {"plugin_version": "0.1.5", "zotero_version": "9.0.6", "target_parent_count": 2, "short_title_count": 2, "note_count": 2, "local_readable_pdf_parent_count": 1, "attachment_batch_import_count": 1, "attachment_total_import_count": 2, "current_source_count": 2, "current_source_doi_count": 1}, "artifacts": self.refs}
        value["evidence_pack_sha256"] = "sha256:" + hashlib.sha256(AUDIT.canonical_bytes(value)).hexdigest()
        return value

    def test_passes_complete_run(self) -> None:
        result = AUDIT.audit(self.pack())
        self.assertEqual(result["status"], "passed")
        self.assertTrue(result["html_deterministic"])
        self.assertFalse(result["cloud_sync_claimed"])

    def test_rejects_negative_membership_false_positive(self) -> None:
        self._write_receipt("negative_membership_readback", "not_applied", "readback", {"all_satisfied": True, "state": {"entries": [{"target_membership": False, "operations": [{"decision": "satisfied"}]}]}})
        with self.assertRaisesRegex(AUDIT.AuditFailure, "negative membership"):
            AUDIT.audit(self.pack())

    def test_rejects_noncommitted_apply(self) -> None:
        self._write_receipt("canary_apply", "completed", "apply", {"commit_state": "unknown", "execution_profile": "single_attachment_import"})
        with self.assertRaisesRegex(AUDIT.AuditFailure, "did not commit"):
            AUDIT.audit(self.pack())

    def test_rejects_research_map_binding_drift(self) -> None:
        self._write_json("research_map", {"schema": "ResearchMap/v1", "network_snapshot_id": "KN-S2"})
        with self.assertRaisesRegex(AUDIT.AuditFailure, "snapshot binding"):
            AUDIT.audit(self.pack())

    def test_rejects_corpus_item_count_drift(self) -> None:
        network = json.loads(Path(self.refs["network"]["path"]).read_text())
        network["corpus_snapshot"]["item_count"] = 3
        self._write_json("network", network)
        with self.assertRaisesRegex(AUDIT.AuditFailure, "current corpus source count"):
            AUDIT.audit(self.pack())

    def test_rejects_non_deterministic_html(self) -> None:
        self._write_bytes("html_repeat", b"<!doctype html><html><body>changed</body></html>\n", ".html")
        with self.assertRaisesRegex(AUDIT.AuditFailure, "byte-identical"):
            AUDIT.audit(self.pack())

    def test_rejects_remote_resource(self) -> None:
        raw = b'<!doctype html><html><script src="https://example.test/x.js"></script></html>\n'
        self._write_bytes("html_primary", raw, ".html")
        self._write_bytes("html_repeat", raw, ".html")
        with self.assertRaisesRegex(AUDIT.AuditFailure, "remote executable"):
            AUDIT.audit(self.pack())

    def test_rejects_artifact_hash_drift(self) -> None:
        pack = self.pack()
        Path(pack["artifacts"]["probe"]["path"]).write_text("{}")
        with self.assertRaisesRegex(AUDIT.AuditFailure, "digest mismatch"):
            AUDIT.audit(pack)


if __name__ == "__main__":
    unittest.main()
