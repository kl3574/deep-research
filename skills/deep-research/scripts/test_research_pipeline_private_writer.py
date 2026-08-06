import os
import tempfile
import unittest
from pathlib import Path

from research_pipeline import ContractError, write_json_exclusive


class PrivateWriterTests(unittest.TestCase):
    def test_forces_private_modes_under_permissive_umask(self):
        with tempfile.TemporaryDirectory() as temporary:
            parent = Path(temporary) / "private"
            output = parent / "pipeline.json"
            previous = os.umask(0)
            try:
                write_json_exclusive(str(output), {"status": "bounded"})
            finally:
                os.umask(previous)
            self.assertEqual(output.stat().st_mode & 0o777, 0o600)
            self.assertEqual(parent.stat().st_mode & 0o777, 0o700)

    def test_refuses_existing_file_and_symlink(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            existing = root / "existing.json"
            existing.write_text("original", encoding="utf-8")
            with self.assertRaisesRegex(ContractError, "refusing to overwrite"):
                write_json_exclusive(str(existing), {"changed": True})
            self.assertEqual(existing.read_text(encoding="utf-8"), "original")

            symlink = root / "link.json"
            symlink.symlink_to(existing)
            with self.assertRaisesRegex(ContractError, "refusing to overwrite"):
                write_json_exclusive(str(symlink), {"changed": True})


if __name__ == "__main__":
    unittest.main()
