from __future__ import annotations

import hashlib
import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).with_name("verify_manifest.py")
MODULE_SPEC = importlib.util.spec_from_file_location("verify_manifest", MODULE_PATH)
assert MODULE_SPEC is not None and MODULE_SPEC.loader is not None
verify_manifest = importlib.util.module_from_spec(MODULE_SPEC)
MODULE_SPEC.loader.exec_module(verify_manifest)


class VerifyManifestTests(unittest.TestCase):
    def make_valid_case(self, root: Path) -> tuple[dict, Path, Path]:
        pdf_path = root / "paper.pdf"
        pdf_path.write_bytes(b"%PDF-1.7\nminimal forward-test fixture\n%%EOF\n")
        note_path = root / "note.md"
        note_path.write_text("# Verified note\n\nEvidence-linked content.\n", encoding="utf-8")
        manifest = {
            "manifest_version": "1",
            "entries": [
                {
                    "id": "SRC-0001",
                    "title": "Fixture Paper",
                    "year": 2024,
                    "source": {
                        "doi": "10.1000/fixture",
                        "access_level": "full_text",
                    },
                    "pdf": {
                        "status": "verified",
                        "local_path": str(pdf_path),
                        "declared_mime": "application/pdf",
                        "size_bytes": pdf_path.stat().st_size,
                        "sha256": hashlib.sha256(pdf_path.read_bytes()).hexdigest(),
                    },
                    "note": {
                        "status": "verified",
                        "local_path": str(note_path),
                        "sha256": hashlib.sha256(note_path.read_bytes()).hexdigest(),
                    },
                    "ingestion": {"decision": "add"},
                }
            ],
        }
        return manifest, pdf_path, note_path

    def test_valid_pdf_and_note(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest, _, _ = self.make_valid_case(root)
            status, errors, _, ids = verify_manifest.validate_manifest(
                manifest, root, require_pdf=True
            )
            self.assertEqual(status, verify_manifest.EXIT_SUCCESS)
            self.assertEqual(errors, [])
            self.assertEqual(ids, {"SRC-0001"})

    def test_duplicate_and_hash_mismatch_fail(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest, _, _ = self.make_valid_case(root)
            duplicate = json.loads(json.dumps(manifest["entries"][0]))
            duplicate["pdf"]["sha256"] = "0" * 64
            manifest["entries"].append(duplicate)
            status, errors, _, _ = verify_manifest.validate_manifest(
                manifest, root, require_pdf=True
            )
            self.assertEqual(status, verify_manifest.EXIT_VALIDATION)
            self.assertTrue(any("duplicate id" in error for error in errors))
            self.assertTrue(any("sha256 mismatch" in error for error in errors))

    def test_bib_alignment_failure_has_exit_three(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest, _, _ = self.make_valid_case(root)
            manifest_path = root / "ingestion_manifest.json"
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            bib_path = root / "references.bib"
            bib_path.write_text(
                "@article{OTHER,\n title={Other},\n year={2024}\n}\n",
                encoding="utf-8",
            )
            result = subprocess.run(
                [
                    sys.executable,
                    str(Path(__file__).with_name("verify_manifest.py")),
                    str(manifest_path),
                    "--root",
                    str(root),
                    "--references-bib",
                    str(bib_path),
                ],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, verify_manifest.EXIT_ALIGNMENT)
            self.assertIn("SRC-0001", result.stderr)


if __name__ == "__main__":
    unittest.main()
