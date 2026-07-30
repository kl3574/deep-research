from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


SCRIPT_PATH = Path(__file__).with_name("check_public_privacy.py")
SPEC = importlib.util.spec_from_file_location("check_public_privacy", SCRIPT_PATH)
assert SPEC and SPEC.loader
module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(module)


class PublicPrivacyCheckTests(unittest.TestCase):
    def test_synthetic_fixture_is_allowed(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            fixture = root / "fixture.py"
            fixture.write_text(
                'group_id = 1234567\nnote_key = "NOTE0001"\n',
                encoding="utf-8",
            )
            self.assertEqual(
                module.scan_tracked_tree(root, [Path("fixture.py")]),
                [],
            )

    def test_private_artifact_and_contextual_identifiers_are_rejected(self) -> None:
        private_key = "Q" + "7W8E9R0"
        camel_key = "Q" + "1W2E3R4"
        yaml_key = "Z" + "9X8C7V6"
        plural_key = "M" + "1N2B3V4"
        private_group = "8" + "765432"
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            fixture = root / "fixture.py"
            fixture.write_text(
                "\n".join(
                    [
                        f'group_id = {private_group}',
                        f'note_key = "{private_key}"',
                        f'parentKey: "{camel_key}"',
                        f"attachment_key: {yaml_key}",
                        f'"noteKeys": ["{plural_key}"]',
                        f'path = "overrides/{private_key}.html"',
                        'home = "/home/" + "private-user/data"',
                        'stage = "zotero-all-notes-" + "2026-01-02"',
                    ]
                ),
                encoding="utf-8",
            )
            findings = module.scan_tracked_tree(root, [Path("fixture.py")])
            self.assertTrue(
                any("non-synthetic Zotero group ID" in value for value in findings)
            )
            self.assertTrue(
                any("non-synthetic Zotero item key" in value for value in findings)
            )
            self.assertGreaterEqual(
                sum(
                    "non-synthetic Zotero item key" in value
                    for value in findings
                ),
                4,
            )
            self.assertTrue(
                any("private-style Zotero note filename" in value for value in findings)
            )

            private_artifact = root / "paper.pdf"
            private_artifact.write_bytes(b"%PDF-fixture")
            findings = module.scan_tracked_tree(root, [Path("paper.pdf")])
            self.assertEqual(
                findings,
                ["paper.pdf: tracked private-artifact extension: .pdf"],
            )

    def test_private_json_is_an_in_memory_denylist(self) -> None:
        private_key = "R" + "8T7Y6U5"
        private_group = int("9" + "876543")
        private_library = "Private " + "Research Library"
        private_collection = "Restricted " + "Topic"
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            private_json = root / "private.json"
            private_json.write_text(
                json.dumps(
                    {
                        "target": {
                            "group_id": private_group,
                            "library_name": private_library,
                            "collection_path": [private_collection],
                        },
                        "entries": [{"note_key": private_key}],
                    }
                ),
                encoding="utf-8",
            )
            tokens = module.private_tokens_from_json([private_json])
            self.assertEqual(
                tokens,
                {
                    str(private_group),
                    private_key,
                    private_library,
                    private_collection,
                },
            )

            fixture = root / "fixture.txt"
            fixture.write_text(
                "\n".join(
                    [
                        f"opaque group: {private_group}",
                        f"opaque key: {private_key}",
                        f"opaque library: {private_library}",
                        f"opaque collection: {private_collection}",
                    ]
                ),
                encoding="utf-8",
            )
            findings = module.scan_tracked_tree(
                root,
                [Path("fixture.txt")],
                tokens,
            )
            self.assertEqual(len(findings), 4)
            self.assertTrue(
                all(
                    "identifier found in private JSON input" in value
                    for value in findings
                )
            )


if __name__ == "__main__":
    unittest.main()
