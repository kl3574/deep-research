#!/usr/bin/env python3

from __future__ import annotations

import json
import re
import unittest
from argparse import Namespace
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import prepare_note_migration as module
from test_verify_note_html import valid_note


class PrepareNoteMigrationTests(unittest.TestCase):
    def prepare_parent_note_case(
        self,
        directory: Path,
        *,
        note_count: int,
        parent_version: int = 3,
        parent_data_key: str = "PARENT01",
        parent_data_version: int | None = None,
        pdf_count: int = 1,
        zotero_normalized_note: bool = False,
    ) -> tuple[dict[str, object], str, str]:
        pdf_path = directory / "paper.pdf"
        pdf_path.write_bytes(b"%PDF-1.4\nfixture\n%%EOF\n")
        pdf_sha256 = module.sha256_file(pdf_path)
        requested_html = valid_note().replace("a" * 64, pdf_sha256)
        html_path = directory / "requested-note.html"
        html_path.write_text(requested_html, encoding="utf-8")
        parent_note_map = directory / "parent-note-map.json"
        parent_note_map.write_text(
            '{"PARENT01": ' + json.dumps(str(html_path)) + "}",
            encoding="utf-8",
        )
        args = Namespace(
            group_id=1234567,
            collection_key="COLL",
            expected_collection_name="Collection",
            output_dir=directory,
            override_map=None,
            parent_note_map=parent_note_map,
            pdf_attachment_map=None,
        )
        target = {
            "group_id": 1234567,
            "library_id": 2,
            "library_name": "Example Research Library",
            "local_collection_id": 27,
            "collection_key": "COLL",
            "collection_name": "Collection",
            "collection_path": ["Collection"],
        }
        parents = [
            {
                "key": "PARENT01",
                "version": parent_version,
                "data": {
                    "key": parent_data_key,
                    "version": (
                        parent_version
                        if parent_data_version is None
                        else parent_data_version
                    ),
                    "title": "单元测试标题",
                    "itemType": "journalArticle",
                },
            }
        ]
        live_note_html = requested_html
        if zotero_normalized_note:
            live_note_html = re.sub(
                r"<(th|td)>(.*?)</\1>",
                r"<\1><p>\2</p></\1>",
                live_note_html,
                flags=re.S,
            )
            live_note_html = live_note_html.replace(
                "<table><tr>",
                "<table><tbody><tr>",
            ).replace(
                "</tr></table>",
                "</tr></tbody></table>",
            )
        children = [
            {
                "key": f"NOTE{index:04d}",
                "version": 7,
                "data": {
                    "itemType": "note",
                    "parentItem": "PARENT01",
                    "note": live_note_html,
                },
            }
            for index in range(1, note_count + 1)
        ]
        children.extend(
            {
                "key": f"PDFATT{index:02d}",
                "version": 5,
                "data": {
                    "itemType": "attachment",
                    "parentItem": "PARENT01",
                    "contentType": "application/pdf",
                    "linkMode": "imported_file",
                },
            }
            for index in range(1, pdf_count + 1)
        )
        with (
            patch.object(module, "resolve_target_contract", return_value=target),
            patch.object(module, "get_all_json", side_effect=[parents, children]),
            patch.object(module, "get_text", return_value=pdf_path.as_uri()),
        ):
            manifest = module.prepare(args)
        return manifest, requested_html, pdf_sha256

    def test_get_all_json_paginates_without_truncation(self) -> None:
        first_page = [
            {"key": f"{index:08d}"}
            for index in range(100)
        ]
        final_page = [{"key": "FINAL001"}]
        with patch.object(
            module,
            "get_json",
            side_effect=[first_page, final_page],
        ) as mocked_get:
            result = module.get_all_json("/items?include=data")

        self.assertEqual(len(result), 101)
        self.assertIn("limit=100&start=0", mocked_get.call_args_list[0].args[0])
        self.assertIn("limit=100&start=100", mocked_get.call_args_list[1].args[0])

    def test_get_all_json_rejects_nonadvancing_full_page(self) -> None:
        page = [{"key": f"{index:08d}"} for index in range(100)]
        with patch.object(module, "get_json", side_effect=[page, page]):
            with self.assertRaisesRegex(RuntimeError, "did not advance"):
                module.get_all_json("/items")

    def test_normalize_collection_identifier_strips_numeric_prefix(self) -> None:
        self.assertEqual(module.normalize_collection_identifier("C27"), "27")
        self.assertEqual(
            module.normalize_collection_identifier("L1234567"),
            "L1234567",
        )
        self.assertEqual(module.normalize_collection_identifier(27), "27")
        self.assertEqual(module.normalize_collection_identifier("  "), "")
        self.assertEqual(module.normalize_collection_identifier({}), "")

    def test_parse_positive_int_rejects_invalid_and_bool(self) -> None:
        self.assertEqual(module.parse_positive_int("42", "x"), 42)
        self.assertEqual(module.parse_positive_int("L7", "x"), 7)
        self.assertEqual(module.parse_positive_int("C3", "x"), 3)
        with self.assertRaisesRegex(ValueError, "invalid"):
            module.parse_positive_int(True, "x")
        with self.assertRaisesRegex(ValueError, "invalid"):
            module.parse_positive_int("x3", "x")
        with self.assertRaisesRegex(ValueError, "must be positive"):
            module.parse_positive_int("0", "x")

    def test_staging_destination_rejects_existing_manifest(self) -> None:
        with TemporaryDirectory() as temp_dir:
            output_dir = Path(temp_dir)
            (output_dir / "migration_manifest.json").write_text(
                "{}",
                encoding="utf-8",
            )

            with self.assertRaisesRegex(RuntimeError, "use a new output directory"):
                module.ensure_staging_destination(output_dir)

    def test_staging_destination_rejects_nonempty_artifact_directory(self) -> None:
        with TemporaryDirectory() as temp_dir:
            output_dir = Path(temp_dir)
            originals = output_dir / "originals"
            originals.mkdir()
            (originals / "NOTE.html").write_text("old", encoding="utf-8")

            with self.assertRaisesRegex(RuntimeError, "already reserved"):
                module.ensure_staging_destination(output_dir)

    def test_staging_destination_rejects_group_or_other_writable_root(self) -> None:
        with TemporaryDirectory() as temp_dir:
            output_dir = Path(temp_dir)
            output_dir.chmod(0o777)

            with self.assertRaisesRegex(
                RuntimeError,
                "must not be writable by group or other users",
            ):
                module.ensure_staging_destination(output_dir)

    def test_exclusive_staging_write_never_overwrites(self) -> None:
        with TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "artifact.html"
            module.write_text_exclusive(path, "first")

            with self.assertRaisesRegex(RuntimeError, "refusing to overwrite"):
                module.write_text_exclusive(path, "second")

            self.assertEqual(path.read_text(encoding="utf-8"), "first")

    def test_resolve_selected_path_rejects_cycle(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "contains a cycle"):
            module.resolve_selected_path(
                [
                    {"level": 0, "id": "L2", "name": "Example Research Library"},
                    {"level": 1, "id": "C1", "name": "A"},
                    {"level": 2, "id": "C1", "name": "A"},
                    {"level": 3, "id": "C2", "name": "B"},
                ],
                "C2",
                library_id=2,
            )

    def test_resolve_selected_path_keeps_library_and_collection_ids_distinct(
        self,
    ) -> None:
        self.assertEqual(
            module.resolve_selected_path(
                [
                    {"level": 0, "id": "L2", "name": "Example Research Library"},
                    {"level": 1, "id": "C2", "name": "Collection 2"},
                ],
                "C2",
                library_id=2,
            ),
            ["Collection 2"],
        )

    def test_resolve_selected_path_rejects_ambiguous_path(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "ambiguous"):
            module.resolve_selected_path(
                [
                    {"level": 0, "id": "L2", "name": "Example Research Library"},
                    {"level": 1, "id": "C1", "name": "A"},
                    {"level": 2, "id": "C8", "name": "B"},
                    {"level": 1, "id": "C3", "name": "A-alt"},
                    {"level": 2, "id": "C8", "name": "B2"},
                ],
                "8",
                library_id=2,
            )

    def test_resolve_selected_path_errors_when_path_missing(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "missing"):
            module.resolve_selected_path(
                [
                    {"level": 0, "id": "L2", "name": "Example Research Library"},
                    {"level": 1, "id": "C1", "name": "A"},
                ],
                "C999",
                library_id=2,
            )

    def test_resolve_collection_path_detects_cycle(self) -> None:
        responses = {
            "COL1": {
                "version": 5,
                "library": {
                    "type": "group",
                    "id": 1234567,
                    "name": "Example Research Library",
                },
                "data": {
                    "name": "Leaf",
                    "parentCollection": "COL2",
                },
            },
            "COL2": {
                "version": 5,
                "library": {
                    "type": "group",
                    "id": 1234567,
                    "name": "Example Research Library",
                },
                "data": {
                    "name": "Root",
                    "parentCollection": "COL1",
                },
            },
        }

        def fetch_collection(path: str) -> dict[str, object]:
            key = path.rsplit("/", 1)[-1]
            return responses[key]

        with self.assertRaisesRegex(RuntimeError, "cycle"):
            module.resolve_collection_path(1234567, "COL1", get_collection=fetch_collection)

    def test_resolve_collection_path_rejects_missing_parent(self) -> None:
        responses = {
            "COL1": {
                "version": 5,
                "library": {
                    "type": "group",
                    "id": 1234567,
                    "name": "Example Research Library",
                },
                "data": {
                    "name": "Leaf",
                    "parentCollection": "MISSING",
                },
            },
        }

        def fetch_collection(path: str) -> dict[str, object]:
            key = path.rsplit("/", 1)[-1]
            if key in responses:
                return responses[key]
            raise RuntimeError(f"parent {key} missing")

        with self.assertRaisesRegex(RuntimeError, "missing"):
            module.resolve_collection_path(1234567, "COL1", get_collection=fetch_collection)

    def test_api_collection_key_starting_with_c_is_not_treated_as_local_id(
        self,
    ) -> None:
        requested_paths: list[str] = []

        def fetch_collection(path: str) -> dict[str, object]:
            requested_paths.append(path)
            return {
                "version": 5,
                "library": {
                    "type": "group",
                    "id": 1234567,
                    "name": "Example Research Library",
                },
                "data": {
                    "name": "Collection",
                    "parentCollection": False,
                },
            }

        module.resolve_collection_path(
            1234567,
            "C1234567",
            get_collection=fetch_collection,
        )

        self.assertTrue(requested_paths[0].endswith("/C1234567"))

    def test_selected_target_requires_editable_and_collects_path(self) -> None:
        payload = {
            "libraryID": 2,
            "libraryName": "Example Research Library",
            "id": "C27",
            "name": "示例研究主题",
            "editable": True,
            "filesEditable": True,
            "targets": [
                {"id": "L2", "name": "Example Research Library", "level": 0},
                {"id": "C10", "name": "示例研究域", "level": 1},
                {"id": "C20", "name": "示例研究方向", "level": 2},
                {"id": "C27", "name": "示例研究主题", "level": 3},
            ],
        }
        with patch.object(module, "get_json", return_value=payload):
            selected = module.selected_target()

        self.assertEqual(selected["library_id"], 2)
        self.assertEqual(selected["local_collection_id"], 27)
        self.assertEqual(
            selected["collection_path"],
            ["示例研究域", "示例研究方向", "示例研究主题"],
        )

    def test_resolve_target_contract_rejects_path_mismatch(self) -> None:
        selected = {
            "library_id": 2,
            "library_name": "Example Research Library",
            "local_collection_id": 27,
            "collection_path": ["A", "B"],
            "collection_name": "C",
            "collection_key": "TESTCOL1",
        }

        with (
            patch.object(module, "selected_target", return_value=selected),
            patch.object(
                module,
                "get_json",
                side_effect=[
                    {
                        "version": 12,
                        "library": {
                            "type": "group",
                            "id": 1234567,
                            "name": "Example Research Library",
                        },
                        "data": {
                            "name": "X",
                            "parentCollection": "C10",
                        },
                    },
                    {
                        "version": 11,
                        "library": {
                            "type": "group",
                            "id": 1234567,
                            "name": "Example Research Library",
                        },
                        "data": {
                            "name": "Root",
                        },
                    },
                ],
            ),
        ):
            with self.assertRaisesRegex(RuntimeError, "collection name mismatch"):
                module.resolve_target_contract(1234567, "TESTCOL1")

    def test_resolve_target_contract_outputs_full_manifest_fields(self) -> None:
        selected = {
            "library_id": 2,
            "library_name": "Example Research Library",
            "local_collection_id": 27,
            "collection_path": [
                "示例研究域",
                "示例研究方向",
                "示例研究主题",
            ],
            "collection_name": "示例研究主题",
            "collection_key": "TESTCOL1",
        }

        with (
            patch.object(module, "selected_target", return_value=selected),
            patch.object(
                module,
                "get_json",
                side_effect=[
                    {
                        "version": 2209,
                        "library": {
                            "type": "group",
                            "id": 1234567,
                            "name": "Example Research Library",
                        },
                        "data": {
                            "name": "示例研究主题",
                            "parentCollection": "C20",
                        },
                    },
                    {
                        "version": 2209,
                        "library": {
                            "type": "group",
                            "id": 1234567,
                            "name": "Example Research Library",
                        },
                        "data": {
                            "name": "示例研究方向",
                            "parentCollection": "C10",
                        },
                    },
                    {
                        "version": 2209,
                        "library": {
                            "type": "group",
                            "id": 1234567,
                            "name": "Example Research Library",
                        },
                        "data": {
                            "name": "示例研究域",
                            "parentCollection": False,
                        },
                    },
                ],
            ),
        ):
            target = module.resolve_target_contract(
                1234567,
                "TESTCOL1",
                expected_collection_name="示例研究主题",
            )

        self.assertEqual(target["group_id"], 1234567)
        self.assertEqual(target["library_id"], 2)
        self.assertEqual(target["library_name"], "Example Research Library")
        self.assertEqual(target["local_collection_id"], 27)
        self.assertEqual(target["collection_key"], "TESTCOL1")
        self.assertEqual(target["collection_version"], 2209)
        self.assertEqual(
            target["collection_path"],
            [
                "示例研究域",
                "示例研究方向",
                "示例研究主题",
            ],
        )

    def test_resolve_target_contract_rejects_wrong_selected_library(self) -> None:
        selected = {
            "library_id": 4,
            "library_name": "another-group",
            "local_collection_id": 27,
            "collection_path": ["Collection"],
            "collection_name": "Collection",
        }
        with (
            patch.object(module, "selected_target", return_value=selected),
            patch.object(
                module,
                "get_json",
                return_value={
                    "version": 5,
                    "library": {
                        "type": "group",
                        "id": 1234567,
                        "name": "Example Research Library",
                    },
                    "data": {
                        "name": "Collection",
                        "parentCollection": False,
                    },
                },
            ),
        ):
            with self.assertRaisesRegex(RuntimeError, "library name"):
                module.resolve_target_contract(1234567, "COLL")

    def test_prepare_generates_manifest_with_target_contract(self) -> None:
        selected = {
            "library_id": 2,
            "library_name": "Example Research Library",
            "local_collection_id": 27,
            "collection_path": ["Collection"],
            "collection_name": "Collection",
            "collection_key": "COLL",
        }
        with TemporaryDirectory() as temp_dir:
            pdf_path = Path(temp_dir) / "paper.pdf"
            pdf_path.write_bytes(b"%PDF-1.4\nfixture\n%%EOF\n")
            override_html = Path(temp_dir) / "override.html"
            override_html.write_text(
                '<div data-schema-version="9"><p>override</p></div>',
                encoding="utf-8",
            )
            override_path = Path(temp_dir) / "override_map.json"
            override_path.write_text(
                f'{{"NOTE0001": "{override_html}"}}',
                encoding="utf-8",
            )
            args = Namespace(
                group_id=1234567,
                collection_key="COLL",
                expected_collection_name="Collection",
                output_dir=Path(temp_dir),
                override_map=override_path,
                pdf_attachment_map=None,
            )

            with (
                patch.object(module, "selected_target", return_value=selected),
                patch.object(
                    module,
                    "get_json",
                    side_effect=[
                        {
                            "version": 5,
                            "library": {
                                "type": "group",
                                "id": 1234567,
                                "name": "Example Research Library",
                            },
                            "data": {
                                "name": "Collection",
                                "parentCollection": False,
                            },
                        },
                        [
                            {
                                "key": "PARENT01",
                                "version": 3,
                                "data": {
                                    "title": "单元测试标题",
                                    "itemType": "journalArticle",
                                },
                            }
                        ],
                        [
                            {
                                "key": "NOTE0001",
                                "version": 3,
                                "data": {
                                    "itemType": "note",
                                    "parentItem": "PARENT01",
                                    "note": "<p>旧笔记</p>",
                                },
                            },
                            {
                                "key": "PDFATT01",
                                "version": 3,
                                "data": {
                                    "itemType": "attachment",
                                    "parentItem": "PARENT01",
                                    "contentType": "application/pdf",
                                    "linkMode": "imported_file",
                                },
                            },
                        ],
                    ],
                ),
                patch.object(module, "get_text", return_value=pdf_path.as_uri()),
            ):
                manifest = module.prepare(args)

        self.assertEqual(manifest["target"]["group_id"], 1234567)
        self.assertEqual(manifest["target"]["local_collection_id"], 27)
        self.assertEqual(manifest["target"]["library_name"], "Example Research Library")
        self.assertEqual(manifest["target"]["collection_version"], 5)
        self.assertEqual(manifest["manifest_version"], "2")
        self.assertEqual(manifest["collection_item_inventory"], ["PARENT01"])
        self.assertEqual(len(manifest["entries"]), 1)
        self.assertEqual(manifest["entries"][0]["note_key"], "NOTE0001")
        self.assertEqual(
            manifest["entries"][0]["child_note_inventory"],
            ["NOTE0001"],
        )

    def test_prepare_stages_verified_creation_for_parent_without_note(self) -> None:
        with TemporaryDirectory() as temp_dir:
            manifest, requested_html, pdf_sha256 = self.prepare_parent_note_case(
                Path(temp_dir),
                note_count=0,
            )
            entry = manifest["entries"][0]

            self.assertEqual(entry["status"], "create_verified")
            self.assertEqual(entry["migration_kind"], "parent_note_create")
            self.assertEqual(entry["parent_key"], "PARENT01")
            self.assertEqual(entry["expected_parent_key"], "PARENT01")
            self.assertEqual(entry["parent_version"], 3)
            self.assertEqual(
                entry["parent_data_snapshot_schema"],
                module.PARENT_DATA_SNAPSHOT_SCHEMA,
            )
            self.assertEqual(
                entry["parent_data_snapshot_sha256"],
                module.parent_data_snapshot_sha256(
                    {
                        "title": "单元测试标题",
                        "itemType": "journalArticle",
                    }
                ),
            )
            self.assertEqual(entry["child_item_inventory"], ["PDFATT01"])
            self.assertEqual(entry["child_note_inventory"], [])
            self.assertEqual(entry["child_attachment_inventory"], ["PDFATT01"])
            self.assertEqual(entry["pdf_attachment_key"], "PDFATT01")
            self.assertEqual(entry["pdf_attachment_link_mode"], "imported_file")
            self.assertEqual(entry["pdf_sha256"], pdf_sha256)
            self.assertEqual(entry["validation_errors"], [])
            self.assertEqual(
                str(entry["validation_summary"]["schema_version"]),
                "9",
            )
            new_path = Path(str(entry["new_path"]))
            self.assertTrue(new_path.is_absolute())
            self.assertEqual(new_path.read_text(encoding="utf-8"), requested_html)
            self.assertEqual(entry["new_sha256"], module.sha256_file(new_path))

    def test_creation_rejects_parent_wrapper_data_identity_mismatch(self) -> None:
        with TemporaryDirectory() as temp_dir:
            with self.assertRaisesRegex(
                RuntimeError,
                "wrapper and item data identity differ",
            ):
                self.prepare_parent_note_case(
                    Path(temp_dir),
                    note_count=0,
                    parent_data_key="OTHER001",
                )

        with TemporaryDirectory() as temp_dir:
            with self.assertRaisesRegex(
                RuntimeError,
                "wrapper and item data identity differ",
            ):
                self.prepare_parent_note_case(
                    Path(temp_dir),
                    note_count=0,
                    parent_data_version=2,
                )

    def test_parent_data_snapshot_hash_covers_local_metadata_but_not_identity(
        self,
    ) -> None:
        base = {
            "key": "PARENT01",
            "version": 3,
            "itemType": "journalArticle",
            "title": "A",
            "creators": [
                {
                    "firstName": "Ada",
                    "lastName": "Lovelace",
                    "creatorType": "author",
                },
                {
                    "firstName": "Grace",
                    "lastName": "Hopper",
                    "creatorType": "author",
                }
            ],
            "DOI": "10.1234/example",
            "dateModified": "2026-07-30T00:00:00Z",
        }
        same_bibliography_new_operational_metadata = {
            **base,
            "key": "OTHER001",
            "version": 4,
            "accessDate": "2026-07-31T00:00:00Z",
            "citationKey": "lovelaceChanged",
            "collections": ["OTHER001"],
            "createdByUserID": 1,
            "dateAdded": "2026-07-29T00:00:00Z",
            "dateModified": "2026-07-31T00:00:00Z",
            "deleted": False,
            "inPublications": False,
            "lastModifiedByUserID": 2,
            "libraryCatalog": "Changed catalog",
            "relations": {"dc:relation": ["https://example.org/related"]},
            "synced": False,
            "tags": [{"tag": "new"}],
        }
        changed_title = {**base, "title": "B"}
        changed_creator = {
            **base,
            "creators": [
                {
                    "firstName": "Grace",
                    "lastName": "Hopper",
                    "creatorType": "author",
                }
            ],
        }
        reordered_creators = {
            **base,
            "creators": list(reversed(base["creators"])),
        }
        changed_doi = {**base, "DOI": "10.1234/changed"}

        self.assertEqual(
            module.parent_data_snapshot_sha256(base),
            module.parent_data_snapshot_sha256(
                same_bibliography_new_operational_metadata
            ),
        )
        self.assertNotEqual(
            module.parent_data_snapshot_sha256(base),
            module.parent_data_snapshot_sha256(changed_title),
        )
        self.assertNotEqual(
            module.parent_data_snapshot_sha256(base),
            module.parent_data_snapshot_sha256(changed_creator),
        )
        self.assertNotEqual(
            module.parent_data_snapshot_sha256(base),
            module.parent_data_snapshot_sha256(reordered_creators),
        )
        self.assertNotEqual(
            module.parent_data_snapshot_sha256(base),
            module.parent_data_snapshot_sha256(changed_doi),
        )

    def test_parent_note_map_is_idempotent_after_created_note_exists(self) -> None:
        with TemporaryDirectory() as temp_dir:
            manifest, requested_html, _pdf_sha256 = self.prepare_parent_note_case(
                Path(temp_dir),
                note_count=1,
            )
            entry = manifest["entries"][0]

            self.assertEqual(entry["status"], "unchanged_verified")
            self.assertEqual(entry["migration_kind"], "curated_parent_override")
            self.assertEqual(entry["note_key"], "NOTE0001")
            self.assertEqual(entry["child_note_inventory"], ["NOTE0001"])
            self.assertEqual(
                Path(str(entry["new_path"])).read_text(encoding="utf-8"),
                requested_html,
            )
            self.assertEqual(entry["old_sha256"], entry["new_sha256"])

    def test_parent_note_map_idempotence_accepts_zotero_table_normalization(
        self,
    ) -> None:
        with TemporaryDirectory() as temp_dir:
            manifest, requested_html, _pdf_sha256 = self.prepare_parent_note_case(
                Path(temp_dir),
                note_count=1,
                zotero_normalized_note=True,
            )
            entry = manifest["entries"][0]
            live_html = Path(str(entry["old_path"])).read_text(encoding="utf-8")

        self.assertNotEqual(live_html, requested_html)
        self.assertEqual(entry["status"], "unchanged_verified")
        self.assertEqual(entry["migration_kind"], "curated_parent_override")
        self.assertEqual(entry["old_sha256"], entry["new_sha256"])
        self.assertEqual(
            module.semantic_note_html_for_comparison(live_html),
            module.semantic_note_html_for_comparison(requested_html),
        )

    def test_storage_semantic_comparison_preserves_meaningful_table_wrappers(
        self,
    ) -> None:
        bare = '<div data-schema-version="9"><table><tr><td>x</td></tr></table></div>'
        zotero_normalized = (
            '<div data-schema-version="9"><table><tbody><tr>'
            "<td><p>x</p></td></tr></tbody></table></div>"
        )
        attributed_wrapper = (
            '<div data-schema-version="9"><table><tbody><tr>'
            '<td><p class="meaningful">x</p></td></tr></tbody></table></div>'
        )

        self.assertTrue(
            module.note_html_matches_storage_semantics(
                bare,
                zotero_normalized,
            )
        )
        self.assertFalse(
            module.note_html_matches_storage_semantics(
                bare,
                attributed_wrapper,
            )
        )

    def test_storage_semantic_comparison_flatten_sections_and_preserve_rejections(
        self,
    ) -> None:
        source = (
            "<div data-schema-version=\"9\"><table>"
            "<tr><td>row-1</td></tr><tr><td>row-2</td></tr>"
            "</table></div>"
        )
        flattened = (
            "<div data-schema-version=\"9\"><table>"
            "<thead><tr><td><p>row-1</p></td></tr></thead>"
            "<tfoot><tr><td><p>row-2</p></td></tr></tfoot>"
            "</table></div>"
        )
        mixed = (
            "<div data-schema-version=\"9\"><table>"
            "<tr><td><p>row-1</p></td></tr>"
            "<tbody><tr><td><p>row-2</p></td></tr></tbody>"
            "</table></div>"
        )
        reorder = (
            "<div data-schema-version=\"9\"><table>"
            "<tbody><tr><td><p>row-2</p></td></tr></tbody>"
            "<thead><tr><td><p>row-1</p></td></tr></thead>"
            "</table></div>"
        )
        attributed_section = (
            "<div data-schema-version=\"9\"><table>"
            "<thead class=\"zotero\"><tr><td><p>row-1</p></td></tr></thead>"
            "<tfoot><tr><td><p>row-2</p></td></tr></tfoot>"
            "</table></div>"
        )
        nontr_child_section = (
            "<div data-schema-version=\"9\"><table>"
            "<tbody><tr><td>row-1</td></tr><span>bad</span></tbody>"
            "<tr><td>row-2</td></tr>"
            "</table></div>"
        )
        changed_cell_tag = (
            "<div data-schema-version=\"9\"><table>"
            "<thead><tr><th><p>row-1</p></th></tr></thead>"
            "<tfoot><tr><td><p>row-2</p></td></tr></tfoot>"
            "</table></div>"
        )

        self.assertTrue(
            module.note_html_matches_storage_semantics(source, flattened)
        )
        self.assertTrue(
            module.note_html_matches_storage_semantics(source, mixed)
        )
        self.assertFalse(
            module.note_html_matches_storage_semantics(source, reorder)
        )
        self.assertFalse(
            module.note_html_matches_storage_semantics(source, attributed_section)
        )
        self.assertFalse(
            module.note_html_matches_storage_semantics(source, nontr_child_section)
        )
        self.assertFalse(
            module.note_html_matches_storage_semantics(source, changed_cell_tag)
        )

    def test_storage_semantic_comparison_ignores_ascii_whitespace_around_attribute_free_br(
        self,
    ) -> None:
        source = (
            '<div data-schema-version="9"><p>alpha<br/><span>beta</span></p></div>'
        )
        with_ascii_ws = (
            '<div data-schema-version="9"><p>alpha<br>   <span>beta</span></p></div>'
        )
        with_newlines = (
            '<div data-schema-version="9"><p>alpha<br/>\n\t <span>beta</span></p></div>'
        )
        with_nbsp = (
            '<div data-schema-version="9"><p>alpha<br/>&nbsp;<span>beta</span></p></div>'
        )
        with_attributed_br = (
            '<div data-schema-version="9"><p>alpha<br class="soft-break"> '
            "<span>beta</span></p></div>"
        )

        self.assertTrue(
            module.note_html_matches_storage_semantics(source, with_ascii_ws)
        )
        self.assertTrue(
            module.note_html_matches_storage_semantics(source, with_newlines)
        )
        self.assertFalse(
            module.note_html_matches_storage_semantics(source, with_nbsp)
        )
        self.assertFalse(
            module.note_html_matches_storage_semantics(
                source,
                with_attributed_br,
            )
        )

    def test_storage_semantic_comparison_preserves_nonbreaking_spaces(
        self,
    ) -> None:
        regular_space = '<div data-schema-version="9"><p>a b</p></div>'
        nonbreaking_space = (
            '<div data-schema-version="9"><p>a&nbsp;b</p></div>'
        )

        self.assertFalse(
            module.note_html_matches_storage_semantics(
                regular_space,
                nonbreaking_space,
            )
        )

    def test_storage_semantic_comparison_respects_inline_white_space_style(
        self,
    ) -> None:
        one_space = (
            '<div data-schema-version="9">'
            '<span style="white-space: pre">a b</span></div>'
        )
        two_spaces = (
            '<div data-schema-version="9">'
            '<span style="white-space: pre">a  b</span></div>'
        )
        ordinary_one_space = '<div data-schema-version="9"><span>a b</span></div>'
        ordinary_two_spaces = (
            '<div data-schema-version="9"><span>a  b</span></div>'
        )
        commented_declaration_one_space = (
            '<div data-schema-version="9">'
            '<span style="color:red;/*keep*/white-space:pre">a b</span></div>'
        )
        commented_declaration_two_spaces = (
            '<div data-schema-version="9">'
            '<span style="color:red;/*keep*/white-space:pre">a  b</span></div>'
        )
        comment_inside_property_one_space = (
            '<div data-schema-version="9">'
            '<span style="white-space/**/:pre">a b</span></div>'
        )
        comment_inside_property_two_spaces = (
            '<div data-schema-version="9">'
            '<span style="white-space/**/:pre">a  b</span></div>'
        )

        self.assertFalse(
            module.note_html_matches_storage_semantics(one_space, two_spaces)
        )
        self.assertTrue(
            module.note_html_matches_storage_semantics(
                ordinary_one_space,
                ordinary_two_spaces,
            )
        )
        self.assertFalse(
            module.note_html_matches_storage_semantics(
                commented_declaration_one_space,
                commented_declaration_two_spaces,
            )
        )
        self.assertFalse(
            module.note_html_matches_storage_semantics(
                comment_inside_property_one_space,
                comment_inside_property_two_spaces,
            )
        )

    def test_parent_note_map_does_not_bypass_multiple_note_block(self) -> None:
        with TemporaryDirectory() as temp_dir:
            manifest, _requested_html, _pdf_sha256 = self.prepare_parent_note_case(
                Path(temp_dir),
                note_count=2,
            )
            entry = manifest["entries"][0]

        self.assertEqual(entry["status"], "blocked_multiple_notes")
        self.assertEqual(entry["note_count"], 2)
        self.assertEqual(
            entry["child_item_inventory"],
            ["NOTE0001", "NOTE0002", "PDFATT01"],
        )
        self.assertEqual(entry["pdf_attachment_key"], "PDFATT01")

    def test_parent_note_creation_binds_pdf_before_zero_note_branch(self) -> None:
        with TemporaryDirectory() as temp_dir:
            manifest, _requested_html, _pdf_sha256 = self.prepare_parent_note_case(
                Path(temp_dir),
                note_count=0,
                pdf_count=2,
            )
            entry = manifest["entries"][0]

        self.assertEqual(entry["status"], "blocked_multiple_pdfs")
        self.assertEqual(
            entry["pdf_attachment_candidates"],
            ["PDFATT01", "PDFATT02"],
        )
        self.assertNotIn("new_path", entry)

    def test_parent_note_map_rejects_relative_html_path(self) -> None:
        with TemporaryDirectory() as temp_dir:
            directory = Path(temp_dir)
            parent_note_map = directory / "parent-note-map.json"
            parent_note_map.write_text(
                '{"PARENT01": "relative-note.html"}',
                encoding="utf-8",
            )
            args = Namespace(
                group_id=1234567,
                collection_key="COLL",
                expected_collection_name="Collection",
                output_dir=directory,
                override_map=None,
                parent_note_map=parent_note_map,
                pdf_attachment_map=None,
            )
            target = {
                "group_id": 1234567,
                "library_id": 2,
                "library_name": "Example Research Library",
                "local_collection_id": 27,
                "collection_key": "COLL",
                "collection_name": "Collection",
                "collection_path": ["Collection"],
            }
            parents = [
                {
                    "key": "PARENT01",
                    "version": 3,
                    "data": {
                        "title": "单元测试标题",
                        "itemType": "journalArticle",
                    },
                }
            ]
            with (
                patch.object(
                    module,
                    "resolve_target_contract",
                    return_value=target,
                ),
                patch.object(module, "get_all_json", return_value=parents),
                self.assertRaisesRegex(ValueError, "must be absolute"),
            ):
                module.prepare(args)

    def test_prepare_marks_schema9_note_as_unchanged(self) -> None:
        selected = {
            "library_id": 2,
            "library_name": "Example Research Library",
            "local_collection_id": 27,
            "collection_path": ["Collection"],
            "collection_name": "Collection",
            "collection_key": "COLL",
        }
        with TemporaryDirectory() as temp_dir:
            pdf_path = Path(temp_dir) / "paper.pdf"
            pdf_path.write_bytes(b"%PDF-1.4\nfixture\n%%EOF\n")
            args = Namespace(
                group_id=1234567,
                collection_key="COLL",
                expected_collection_name="Collection",
                output_dir=Path(temp_dir),
                override_map=None,
                pdf_attachment_map=None,
            )
            raw = valid_note()
            with (
                patch.object(module, "selected_target", return_value=selected),
                patch.object(
                    module,
                    "get_json",
                    side_effect=[
                        {
                            "version": 5,
                            "library": {
                                "type": "group",
                                "id": 1234567,
                                "name": "Example Research Library",
                            },
                            "data": {
                                "name": "Collection",
                                "parentCollection": False,
                            },
                        },
                        [
                            {
                                "key": "PARENT01",
                                "version": 3,
                                "data": {
                                    "title": "单元测试标题",
                                    "itemType": "journalArticle",
                                },
                            }
                        ],
                        [
                            {
                                "key": "NOTE0001",
                                "version": 3,
                                "data": {
                                    "itemType": "note",
                                    "parentItem": "PARENT01",
                                    "note": raw,
                                },
                            },
                            {
                                "key": "PDFATT01",
                                "version": 3,
                                "data": {
                                    "itemType": "attachment",
                                    "parentItem": "PARENT01",
                                    "contentType": "application/pdf",
                                    "linkMode": "imported_file",
                                },
                            },
                        ],
                    ],
                ),
                patch.object(module, "get_text", return_value=pdf_path.as_uri()),
            ):
                manifest = module.prepare(args)

            entry = manifest["entries"][0]
            self.assertEqual(entry["status"], "unchanged_verified")
            self.assertEqual(entry["migration_kind"], "existing_schema9")
            self.assertEqual(
                Path(entry["new_path"]).read_text(encoding="utf-8"),
                raw,
            )
            self.assertEqual(entry["old_sha256"], entry["new_sha256"])

    def test_prepare_marks_matching_override_as_unchanged(self) -> None:
        selected = {
            "library_id": 2,
            "library_name": "Example Research Library",
            "local_collection_id": 27,
            "collection_path": ["Collection"],
            "collection_name": "Collection",
            "collection_key": "COLL",
        }
        raw = valid_note()
        with TemporaryDirectory() as temp_dir:
            pdf_path = Path(temp_dir) / "paper.pdf"
            pdf_path.write_bytes(b"%PDF-1.4\nfixture\n%%EOF\n")
            override_html = Path(temp_dir) / "override.html"
            override_html.write_text(raw, encoding="utf-8")
            override_path = Path(temp_dir) / "override_map.json"
            override_path.write_text(
                f'{{"NOTE0001": "{override_html}"}}',
                encoding="utf-8",
            )
            args = Namespace(
                group_id=1234567,
                collection_key="COLL",
                expected_collection_name="Collection",
                output_dir=Path(temp_dir),
                override_map=override_path,
                pdf_attachment_map=None,
            )
            with (
                patch.object(module, "selected_target", return_value=selected),
                patch.object(
                    module,
                    "get_json",
                    side_effect=[
                        {
                            "version": 5,
                            "library": {
                                "type": "group",
                                "id": 1234567,
                                "name": "Example Research Library",
                            },
                            "data": {
                                "name": "Collection",
                                "parentCollection": False,
                            },
                        },
                        [
                            {
                                "key": "PARENT01",
                                "version": 3,
                                "data": {
                                    "title": "单元测试标题",
                                    "itemType": "journalArticle",
                                },
                            }
                        ],
                        [
                            {
                                "key": "NOTE0001",
                                "version": 3,
                                "data": {
                                    "itemType": "note",
                                    "parentItem": "PARENT01",
                                    "note": raw,
                                },
                            },
                            {
                                "key": "PDFATT01",
                                "version": 3,
                                "data": {
                                    "itemType": "attachment",
                                    "parentItem": "PARENT01",
                                    "contentType": "application/pdf",
                                    "linkMode": "imported_file",
                                },
                            },
                        ],
                    ],
                ),
                patch.object(module, "get_text", return_value=pdf_path.as_uri()),
            ):
                manifest = module.prepare(args)

            entry = manifest["entries"][0]
            staged_html = Path(entry["new_path"]).read_text(encoding="utf-8")
            self.assertEqual(staged_html, raw)
            self.assertEqual(entry["new_sha256"], entry["old_sha256"])

        self.assertEqual(entry["status"], "unchanged_verified")
        self.assertEqual(entry["migration_kind"], "curated_override")

    def test_prepare_marks_trimmed_override_as_unchanged(self) -> None:
        selected = {
            "library_id": 2,
            "library_name": "Example Research Library",
            "local_collection_id": 27,
            "collection_path": ["Collection"],
            "collection_name": "Collection",
            "collection_key": "COLL",
        }
        raw = valid_note()
        with TemporaryDirectory() as temp_dir:
            pdf_path = Path(temp_dir) / "paper.pdf"
            pdf_path.write_bytes(b"%PDF-1.4\nfixture\n%%EOF\n")
            override_html = Path(temp_dir) / "override.html"
            override_html.write_text(f"{raw}\n   \n", encoding="utf-8")
            override_path = Path(temp_dir) / "override_map.json"
            override_path.write_text(
                f'{{"NOTE0001": "{override_html}"}}',
                encoding="utf-8",
            )
            args = Namespace(
                group_id=1234567,
                collection_key="COLL",
                expected_collection_name="Collection",
                output_dir=Path(temp_dir),
                override_map=override_path,
                pdf_attachment_map=None,
            )
            with (
                patch.object(module, "selected_target", return_value=selected),
                patch.object(
                    module,
                    "get_json",
                    side_effect=[
                        {
                            "version": 5,
                            "library": {
                                "type": "group",
                                "id": 1234567,
                                "name": "Example Research Library",
                            },
                            "data": {
                                "name": "Collection",
                                "parentCollection": False,
                            },
                        },
                        [
                            {
                                "key": "PARENT01",
                                "version": 3,
                                "data": {
                                    "title": "单元测试标题",
                                    "itemType": "journalArticle",
                                },
                            }
                        ],
                        [
                            {
                                "key": "NOTE0001",
                                "version": 3,
                                "data": {
                                    "itemType": "note",
                                    "parentItem": "PARENT01",
                                    "note": raw,
                                },
                            },
                            {
                                "key": "PDFATT01",
                                "version": 3,
                                "data": {
                                    "itemType": "attachment",
                                    "parentItem": "PARENT01",
                                    "contentType": "application/pdf",
                                    "linkMode": "imported_file",
                                },
                            },
                        ],
                    ],
                ),
                patch.object(module, "get_text", return_value=pdf_path.as_uri()),
            ):
                manifest = module.prepare(args)

            entry = manifest["entries"][0]
            staged_html = Path(entry["new_path"]).read_text(encoding="utf-8")
            self.assertEqual(staged_html, raw)
            self.assertEqual(entry["new_sha256"], entry["old_sha256"])

        self.assertEqual(entry["status"], "unchanged_verified")
        self.assertEqual(entry["migration_kind"], "curated_override")

    def test_prepare_marks_real_change_override_as_staged(self) -> None:
        selected = {
            "library_id": 2,
            "library_name": "Example Research Library",
            "local_collection_id": 27,
            "collection_path": ["Collection"],
            "collection_name": "Collection",
            "collection_key": "COLL",
        }
        raw = valid_note()
        with TemporaryDirectory() as temp_dir:
            pdf_path = Path(temp_dir) / "paper.pdf"
            pdf_path.write_bytes(b"%PDF-1.4\nfixture\n%%EOF\n")
            override_html = Path(temp_dir) / "override.html"
            override_html.write_text(
                raw.replace("</div>", "<p>新增注释</p>\n</div>", 1),
                encoding="utf-8",
            )
            override_path = Path(temp_dir) / "override_map.json"
            override_path.write_text(
                f'{{"NOTE0001": "{override_html}"}}',
                encoding="utf-8",
            )
            args = Namespace(
                group_id=1234567,
                collection_key="COLL",
                expected_collection_name="Collection",
                output_dir=Path(temp_dir),
                override_map=override_path,
                pdf_attachment_map=None,
            )
            with (
                patch.object(module, "selected_target", return_value=selected),
                patch.object(
                    module,
                    "get_json",
                    side_effect=[
                        {
                            "version": 5,
                            "library": {
                                "type": "group",
                                "id": 1234567,
                                "name": "Example Research Library",
                            },
                            "data": {
                                "name": "Collection",
                                "parentCollection": False,
                            },
                        },
                        [
                            {
                                "key": "PARENT01",
                                "version": 3,
                                "data": {
                                    "title": "单元测试标题",
                                    "itemType": "journalArticle",
                                },
                            }
                        ],
                        [
                            {
                                "key": "NOTE0001",
                                "version": 3,
                                "data": {
                                    "itemType": "note",
                                    "parentItem": "PARENT01",
                                    "note": raw,
                                },
                            },
                            {
                                "key": "PDFATT01",
                                "version": 3,
                                "data": {
                                    "itemType": "attachment",
                                    "parentItem": "PARENT01",
                                    "contentType": "application/pdf",
                                    "linkMode": "imported_file",
                                },
                            },
                        ],
                    ],
                ),
                patch.object(module, "get_text", return_value=pdf_path.as_uri()),
            ):
                manifest = module.prepare(args)

        entry = manifest["entries"][0]
        self.assertEqual(entry["status"], "staged_verified")
        self.assertEqual(entry["migration_kind"], "curated_override")

    def test_prepare_rejects_unknown_override_note_key(self) -> None:
        with TemporaryDirectory() as temp_dir:
            output_dir = Path(temp_dir)
            pdf_path = output_dir / "paper.pdf"
            pdf_path.write_bytes(b"%PDF-1.4\nfixture\n%%EOF\n")
            override_html = output_dir / "override.html"
            override_html.write_text(
                '<div data-schema-version="9"><p>override</p></div>',
                encoding="utf-8",
            )
            override_map = output_dir / "override_map.json"
            override_map.write_text(
                f'{{"TYPO0001": "{override_html}"}}',
                encoding="utf-8",
            )
            args = Namespace(
                group_id=1234567,
                collection_key="COLL",
                expected_collection_name="Collection",
                output_dir=output_dir,
                override_map=override_map,
                pdf_attachment_map=None,
            )
            target = {
                "group_id": 1234567,
                "library_id": 2,
                "library_name": "Example Research Library",
                "local_collection_id": 27,
                "collection_key": "COLL",
                "collection_name": "Collection",
                "collection_path": ["Collection"],
            }
            parents = [
                {
                    "key": "PARENT01",
                    "version": 3,
                    "data": {
                        "title": "单元测试标题",
                        "itemType": "journalArticle",
                    },
                }
            ]
            children = [
                {
                    "key": "NOTE0001",
                    "version": 3,
                    "data": {
                        "itemType": "note",
                        "parentItem": "PARENT01",
                        "note": "<p>旧笔记</p>",
                    },
                },
                {
                    "key": "PDFATT01",
                    "version": 3,
                    "data": {
                        "itemType": "attachment",
                        "parentItem": "PARENT01",
                        "contentType": "application/pdf",
                        "linkMode": "imported_file",
                    },
                },
            ]
            with (
                patch.object(
                    module,
                    "resolve_target_contract",
                    return_value=target,
                ),
                patch.object(
                    module,
                    "get_all_json",
                    side_effect=[parents, children],
                ),
                patch.object(module, "get_text", return_value=pdf_path.as_uri()),
            ):
                with self.assertRaisesRegex(
                    ValueError,
                    "override map entries were not used",
                ):
                    module.prepare(args)

    def test_prepare_rejects_deleted_parent_and_child(self) -> None:
        target = {
            "group_id": 1234567,
            "library_id": 2,
            "library_name": "Example Research Library",
            "local_collection_id": 27,
            "collection_key": "COLL",
            "collection_name": "Collection",
            "collection_path": ["Collection"],
        }
        with TemporaryDirectory() as temp_dir:
            args = Namespace(
                group_id=1234567,
                collection_key="COLL",
                expected_collection_name="Collection",
                output_dir=Path(temp_dir),
                override_map=None,
                pdf_attachment_map=None,
            )
            deleted_parent = [
                {
                    "key": "PARENT01",
                    "data": {
                        "title": "已删除父项",
                        "itemType": "journalArticle",
                        "deleted": True,
                    },
                }
            ]
            with (
                patch.object(
                    module,
                    "resolve_target_contract",
                    return_value=target,
                ),
                patch.object(
                    module,
                    "get_all_json",
                    return_value=deleted_parent,
                ),
            ):
                with self.assertRaisesRegex(RuntimeError, "parent PARENT01 is deleted"):
                    module.prepare(args)

        with TemporaryDirectory() as temp_dir:
            args.output_dir = Path(temp_dir)
            live_parent = [
                {
                    "key": "PARENT01",
                    "data": {
                        "title": "父项",
                        "itemType": "journalArticle",
                    },
                }
            ]
            deleted_child = [
                {
                    "key": "NOTE0001",
                    "data": {
                        "itemType": "note",
                        "parentItem": "PARENT01",
                        "deleted": True,
                        "note": "<p>旧笔记</p>",
                    },
                }
            ]
            with (
                patch.object(
                    module,
                    "resolve_target_contract",
                    return_value=target,
                ),
                patch.object(
                    module,
                    "get_all_json",
                    side_effect=[live_parent, deleted_child],
                ),
            ):
                with self.assertRaisesRegex(RuntimeError, "child NOTE0001 is deleted"):
                    module.prepare(args)

    def test_resolve_pdf_blocks_ambiguous_candidates_without_map(self) -> None:
        children = [
            {
                "key": "PDFATT01",
                "data": {
                    "itemType": "attachment",
                    "contentType": "application/pdf",
                    "parentItem": "PARENT01",
                    "linkMode": "imported_file",
                },
            },
            {
                "key": "PDFATT02",
                "data": {
                    "itemType": "attachment",
                    "contentType": "application/pdf",
                    "parentItem": "PARENT01",
                    "linkMode": "imported_file",
                },
            },
        ]

        with self.assertRaises(module.AmbiguousPDFAttachments) as context:
            module.resolve_pdf(1234567, "PARENT01", children)

        self.assertEqual(context.exception.keys, ["PDFATT01", "PDFATT02"])

    def test_resolve_pdf_rejects_missing_live_pdf(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "no live PDF attachment"):
            module.resolve_pdf(1234567, "PARENT01", [])

    def test_resolve_pdf_honors_explicit_attachment_map_and_hashes_file(self) -> None:
        with TemporaryDirectory() as temp_dir:
            pdf_path = Path(temp_dir) / "paper.pdf"
            pdf_path.write_bytes(b"%PDF-1.4\nfixture\n%%EOF\n")
            expected_sha256 = module.sha256_file(pdf_path)
            children = [
                {
                    "key": "PDFATT01",
                    "data": {
                        "itemType": "attachment",
                        "contentType": "application/pdf",
                        "parentItem": "PARENT01",
                        "linkMode": "imported_file",
                    },
                },
                {
                    "key": "PDFATT02",
                    "data": {
                        "itemType": "attachment",
                        "contentType": "application/pdf",
                        "parentItem": "PARENT01",
                        "linkMode": "imported_file",
                    },
                },
            ]
            with patch.object(module, "get_text", return_value=pdf_path.as_uri()):
                resolved = module.resolve_pdf(
                    1234567,
                    "PARENT01",
                    children,
                    selected_attachment_key="PDFATT02",
                )

        self.assertEqual(resolved[0], str(pdf_path))
        self.assertEqual(resolved[1], expected_sha256)
        self.assertEqual(resolved[2:], ("PDFATT02", "imported_file"))

    def test_resolve_pdf_rejects_invalid_magic_bytes(self) -> None:
        with TemporaryDirectory() as temp_dir:
            pdf_path = Path(temp_dir) / "paper.pdf"
            pdf_path.write_bytes(b"not really a PDF")
            children = [
                {
                    "key": "PDFATT01",
                    "data": {
                        "itemType": "attachment",
                        "contentType": "application/pdf",
                        "parentItem": "PARENT01",
                        "linkMode": "imported_file",
                    },
                },
            ]
            with (
                patch.object(module, "get_text", return_value=pdf_path.as_uri()),
                self.assertRaisesRegex(RuntimeError, "invalid magic bytes"),
            ):
                module.resolve_pdf(1234567, "PARENT01", children)

    def test_main_returns_nonzero_for_ambiguous_multiple_notes(self) -> None:
        with TemporaryDirectory() as temp_dir:
            manifest = {
                "manifest_version": "1",
                "write_performed": False,
                "target": {},
                "entries": [
                    {
                        "status": "blocked_multiple_notes",
                        "parent_key": "PARENT12",
                        "note_count": 2,
                    }
                ],
            }
            with (
                patch.object(module, "prepare", return_value=manifest),
                patch.object(
                    module.sys,
                    "argv",
                    [
                        "prepare_note_migration.py",
                        "--group-id",
                        "1234567",
                        "--collection-key",
                        "COLL",
                        "--output-dir",
                        temp_dir,
                    ],
                ),
                redirect_stdout(StringIO()),
            ):
                result = module.main()

        self.assertEqual(result, 1)


if __name__ == "__main__":
    unittest.main()
