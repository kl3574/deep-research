import json
import os
import stat
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import scholar_discovery as discovery


class PrivateOutputTests(unittest.TestCase):
    def test_forces_private_file_and_new_directory_modes_under_open_umask(self):
        with tempfile.TemporaryDirectory() as root_name:
            root = Path(root_name)
            os.chmod(root, 0o700)
            target = root / "private" / "result-set.json"
            previous_umask = os.umask(0)
            try:
                discovery.write_json(
                    target, {"schema": "ScholarDiscoveryResultSet/v1"}
                )
            finally:
                os.umask(previous_umask)

            self.assertEqual(stat.S_IMODE(target.parent.stat().st_mode), 0o700)
            self.assertEqual(stat.S_IMODE(target.stat().st_mode), 0o600)
            self.assertEqual(
                json.loads(target.read_text(encoding="utf-8")),
                {"schema": "ScholarDiscoveryResultSet/v1"},
            )

    def test_replace_failure_preserves_target_and_removes_private_temporary(self):
        with tempfile.TemporaryDirectory() as root_name:
            root = Path(root_name)
            os.chmod(root, 0o700)
            target = root / "result-set.json"
            target.write_text("old\n", encoding="utf-8")
            os.chmod(target, 0o600)

            with mock.patch.object(
                discovery.os, "replace", side_effect=OSError("injected replace failure")
            ):
                with self.assertRaisesRegex(OSError, "injected replace failure"):
                    discovery.write_json(target, {"new": True})

            self.assertEqual(target.read_text(encoding="utf-8"), "old\n")
            self.assertEqual(stat.S_IMODE(target.stat().st_mode), 0o600)
            self.assertEqual(list(root.glob(".result-set.json.*.tmp")), [])

    def test_base_exception_preserves_target_and_removes_private_temporary(self):
        with tempfile.TemporaryDirectory() as root_name:
            root = Path(root_name)
            os.chmod(root, 0o700)
            target = root / "result-set.json"
            target.write_text("old\n", encoding="utf-8")
            os.chmod(target, 0o600)

            with mock.patch.object(
                discovery.os,
                "replace",
                side_effect=KeyboardInterrupt("injected interruption"),
            ):
                with self.assertRaises(KeyboardInterrupt):
                    discovery.write_json(target, {"new": True})

            self.assertEqual(target.read_text(encoding="utf-8"), "old\n")
            self.assertEqual(list(root.glob(".result-set.json.*.tmp")), [])

    def test_rejects_existing_non_private_output_directory(self):
        with tempfile.TemporaryDirectory() as root_name:
            root = Path(root_name)
            public = root / "public"
            public.mkdir(mode=0o755)
            os.chmod(public, 0o755)
            target = public / "result-set.json"

            with self.assertRaisesRegex(
                discovery.ContractError, "must not grant group or other access"
            ):
                discovery.write_json(target, {"private": True})
            self.assertFalse(target.exists())


if __name__ == "__main__":
    unittest.main()
