from __future__ import annotations

import importlib.util
import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).with_name("zotero_attachment_repair.py")
SPEC = importlib.util.spec_from_file_location("zotero_attachment_repair", MODULE_PATH)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class ZoteroAttachmentRepairTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.directory = Path(self.temp.name).resolve()
        self.pdf = self.directory / "paper.pdf"
        self.pdf.write_bytes(b"%PDF-1.7\nfixture\n%%EOF\n")
        pdf_hash = MODULE.sha256_bytes(self.pdf.read_bytes()).removeprefix("sha256:")
        self.baseline = self.directory / "baseline.json"
        self.repair = self.directory / "repair.json"
        baseline_payload = {
            "schema": "ZoteroCorpusSnapshot/v1",
            "state_sha256": "sha256:" + "1" * 64,
            "identity_sha256": "sha256:" + "2" * 64,
            "retrieved_at": "2026-08-05T00:00:00Z",
            "collection": {
                "group_id": 8,
                "collection_key": "TARGET01",
                "collection_version": 9,
                "collection_path": [
                    {"key": "ROOT0001", "name": "root", "version": 1},
                    {"key": "TARGET01", "name": "target", "version": 9},
                ],
            },
            "parents": [
                {
                    "key": "PARENT01",
                    "version": 3,
                    "item_type": "journalArticle",
                    "DOI": "10/example",
                    "title": "Example",
                    "children": [
                        {
                            "key": "REMOTE01",
                            "version": 2,
                            "item_type": "attachment",
                            "content_type": "application/pdf",
                            "link_mode": "imported_url",
                        }
                    ],
                },
                {
                    "key": "PARENT02",
                    "version": 4,
                    "item_type": "journalArticle",
                    "DOI": "10/closed",
                    "title": "Closed",
                    "children": [],
                },
            ],
        }
        repair_payload = {
            "schema": "ExistingPdfRepairManifest/v1",
            "generated_at": "2026-08-05T00:01:00Z",
            "records": [
                {
                    "item_key": "PARENT01",
                    "title": "Example",
                    "DOI": "10/example",
                    "status": "acquired_validated",
                    "pdf_path": str(self.pdf),
                    "sha256": pdf_hash,
                    "size_bytes": self.pdf.stat().st_size,
                    "source_url": "https://example.test/paper.pdf",
                    "access_basis": "declared_open_access",
                    "result_path": str(self.directory / "acquisition.json"),
                },
                {
                    "item_key": "PARENT02",
                    "title": "Closed",
                    "DOI": "10/closed",
                    "status": "metadata_only",
                    "reason": "no lawful public exact-version PDF",
                },
            ],
        }
        self.baseline.write_text(json.dumps(baseline_payload), encoding="utf-8")
        self.repair.write_text(json.dumps(repair_payload), encoding="utf-8")

    def tearDown(self) -> None:
        self.temp.cleanup()

    def build(self):
        return MODULE.build_manifest(
            self.baseline,
            self.repair,
            group_id=8,
            library_id=2,
            library_name="group",
            local_collection_id=40,
            collection_key="TARGET01",
            collection_path="root/target",
        )

    def write_manifest(self, payload=None) -> Path:
        path = self.directory / "manifest.json"
        MODULE.write_json_exclusive(path, payload or self.build())
        return path

    def test_generate_validate_and_preview_render_are_deterministic(self) -> None:
        manifest = self.write_manifest()
        _, payload, summary = MODULE.load_and_validate_manifest(manifest)
        self.assertEqual(summary, {"attach_missing_pdf": 1, "metadata_only_skip": 1, "total": 2})
        report = self.directory / "preview-report.json"
        first = MODULE.render_runner(manifest, report_path=report)
        second = MODULE.render_runner(manifest, report_path=report)
        self.assertEqual(first, second)
        self.assertIn('"apply":false', first)
        self.assertEqual(payload["schema"], "ZoteroAttachmentRepairManifest/v1")

    def test_target_mismatch_is_rejected(self) -> None:
        with self.assertRaisesRegex(MODULE.ContractError, "group_id"):
            MODULE.build_manifest(
                self.baseline,
                self.repair,
                group_id=9,
                library_id=2,
                library_name="group",
                local_collection_id=40,
                collection_key="TARGET01",
                collection_path="root/target",
            )

    def test_parent_version_drift_is_rejected_even_with_resealed_digest(self) -> None:
        payload = self.build()
        payload["entries"][0]["parent"]["version"] += 1
        payload = MODULE.seal_manifest(payload)
        with self.assertRaisesRegex(MODULE.ContractError, "identity/version drift"):
            MODULE.validate_manifest_payload(payload)

    def test_pdf_hash_mismatch_is_rejected(self) -> None:
        payload = self.build()
        self.pdf.write_bytes(b"%PDF-1.7\nchanged\n%%EOF\n")
        with self.assertRaisesRegex(MODULE.ContractError, "source PDF bytes changed"):
            MODULE.validate_manifest_payload(payload)

    def test_duplicate_repair_parent_is_rejected(self) -> None:
        payload = json.loads(self.repair.read_text(encoding="utf-8"))
        payload["records"].append(dict(payload["records"][0]))
        duplicate = self.directory / "duplicate.json"
        duplicate.write_text(json.dumps(payload), encoding="utf-8")
        with self.assertRaisesRegex(MODULE.ContractError, "duplicate repair records"):
            MODULE.build_manifest(
                self.baseline,
                duplicate,
                group_id=8,
                library_id=2,
                library_name="group",
                local_collection_id=40,
                collection_key="TARGET01",
                collection_path="root/target",
            )

    def test_apply_render_is_explicit_and_report_is_append_only(self) -> None:
        manifest = self.write_manifest()
        report = self.directory / "apply-report.json"
        rendered = MODULE.render_runner(manifest, apply=True, report_path=report)
        self.assertIn('"apply":true', rendered)
        report.write_text("{}", encoding="utf-8")
        with self.assertRaisesRegex(MODULE.ContractError, "append-only"):
            MODULE.render_runner(manifest, apply=True, report_path=report)

    def test_javascript_core_mock_scenarios(self) -> None:
        node = shutil.which("node")
        self.assertIsNotNone(node, "Node.js is required for deterministic JS mock tests")
        test_path = Path(__file__).with_name("test_zotero_attachment_repair_core.js")
        completed = subprocess.run(
            [str(node), str(test_path)],
            check=False,
            capture_output=True,
            text=True,
            timeout=30,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(json.loads(completed.stdout), {"passed": 7})


if __name__ == "__main__":
    unittest.main()
