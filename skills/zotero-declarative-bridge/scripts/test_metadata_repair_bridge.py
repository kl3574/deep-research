#!/usr/bin/env python3
"""Focused compiler/schema tests for the isolated metadata-repair transaction."""

from __future__ import annotations

import copy
import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import zotero_declarative_bridge as bridge


HERE = Path(__file__).resolve().parent
CONTRACT_PATH = (
    HERE.parents[1]
    / "repair-zotero-metadata"
    / "scripts"
    / "metadata_repair_contract.py"
)
TEST_PATH = (
    HERE.parents[1]
    / "repair-zotero-metadata"
    / "scripts"
    / "test_metadata_repair_contract.py"
)
BOOTSTRAP_PATH = HERE.parent / "assets" / "zotero-plugin" / "bootstrap.js"


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


contract = load_module(CONTRACT_PATH, "metadata_repair_contract_for_bridge_test")
sys.path.insert(0, str(TEST_PATH.parent))
fixture_module = load_module(TEST_PATH, "metadata_repair_fixture_for_bridge_test")


def live_parent_record(source: dict) -> dict:
    parent = source["entry"]["parent"]
    profile = source["entry"]["repair"]["expected_profile"]
    return {
        "version": parent["version"],
        "data": {
            "key": parent["key"],
            "version": parent["version"],
            "itemType": parent["item_type"],
            "title": parent["title"],
            "shortTitle": parent["short_title"],
            "DOI": profile["DOI"],
            "creators": profile["creators"],
            "publicationTitle": profile["publicationTitle"],
            "volume": profile["volume"],
            "issue": profile["issue"],
            "pages": profile["pages"],
            "date": profile["date"],
            "collections": ["COLL0001"],
        },
    }


def compile_source(source: dict, *, library_items: list[dict] | None = None) -> dict:
    keyed_path = [
        {"key": "ROOT0001", "name": "Research"},
        {"key": "COLL0001", "name": "Methods"},
    ]
    parent_record = live_parent_record(source)
    if library_items is None:
        library_items = [parent_record]
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "source.json"
        path.write_text(json.dumps(source), encoding="utf-8")
        with mock.patch.object(
            bridge,
            "collection_contract",
            return_value=(keyed_path, {"version": 7, "data": {"version": 7}}),
        ), mock.patch.object(
            bridge, "live_parent", return_value=parent_record
        ), mock.patch.object(
            bridge,
            "live_all_children",
            return_value=source["entry"]["children"],
        ), mock.patch.object(
            bridge, "live_library_top_items", return_value=library_items
        ):
            return bridge.compile_reviewed_metadata_repair(
                path,
                transaction_id="synthetic-metadata-repair",
                local_collection_id=40,
                source_hash_contract="canonical-json-v1",
                base_url=bridge.BASE_URL,
            )


class MetadataRepairBridgeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.source = fixture_module.build_reviewed()

    def test_compiles_one_isolated_fixed_profile_transaction(self) -> None:
        manifest = compile_source(self.source)
        self.assertEqual(manifest["schema"], bridge.METADATA_REPAIR_MANIFEST_SCHEMA)
        self.assertEqual(
            manifest["entry"]["operation"]["type"],
            "ensure_parent_journal_metadata_v1",
        )
        self.assertNotIn("operations", manifest["entry"])
        self.assertEqual(
            manifest["source_evidence_sidecar_ref"],
            self.source["source_evidence_sidecar_ref"],
        )
        bridge.validate_any_manifest(manifest)
        with self.assertRaisesRegex(bridge.BridgeError, "manifest keys differ"):
            bridge.validate_manifest(manifest)

    def test_rejects_live_short_title_content_drift(self) -> None:
        record = live_parent_record(self.source)
        record["data"]["shortTitle"] = "Drifted conclusion"
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "source.json"
            path.write_text(json.dumps(self.source), encoding="utf-8")
            with mock.patch.object(
                bridge,
                "collection_contract",
                return_value=(
                    [
                        {"key": "ROOT0001", "name": "Research"},
                        {"key": "COLL0001", "name": "Methods"},
                    ],
                    {"version": 7, "data": {"version": 7}},
                ),
            ), mock.patch.object(
                bridge, "live_parent", return_value=record
            ), mock.patch.object(
                bridge,
                "live_all_children",
                return_value=self.source["entry"]["children"],
            ), mock.patch.object(
                bridge, "live_library_top_items", return_value=[record]
            ):
                with self.assertRaisesRegex(bridge.BridgeError, "shortTitle drift"):
                    bridge.compile_reviewed_metadata_repair(
                        path,
                        transaction_id="synthetic-metadata-repair",
                        local_collection_id=40,
                        source_hash_contract="canonical-json-v1",
                        base_url=bridge.BASE_URL,
                    )

    def test_rejects_full_library_desired_doi_duplicate(self) -> None:
        duplicate = copy.deepcopy(live_parent_record(self.source))
        duplicate["data"]["key"] = "OTHER001"
        duplicate["data"]["DOI"] = self.source["entry"]["repair"][
            "desired_profile"
        ]["DOI"]
        with self.assertRaisesRegex(bridge.BridgeError, "duplicate conflict"):
            compile_source(self.source, library_items=[live_parent_record(self.source), duplicate])

    def test_new_schema_rejects_unknown_or_mixed_operation_shapes(self) -> None:
        manifest = compile_source(self.source)
        manifest["entry"]["operations"] = [
            {"type": "ensure_parent_short_title"}
        ]
        manifest["manifest_sha256"] = bridge.sha256_value(
            {key: value for key, value in manifest.items() if key != "manifest_sha256"}
        )
        with self.assertRaisesRegex(bridge.BridgeError, "entry keys differ"):
            bridge.validate_metadata_repair_manifest(manifest)

    def test_cli_exposes_separate_compile_command(self) -> None:
        result = subprocess.run(
            [
                sys.executable,
                str(HERE / "zotero_declarative_bridge.py"),
                "compile-reviewed-metadata-repair",
                "--help",
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        self.assertIn("--source-hash-contract", result.stdout)

    def test_bootstrap_fail_closes_dirty_parent_and_uses_fresh_failure_readback(self) -> None:
        source = BOOTSTRAP_PATH.read_text(encoding="utf-8")
        self.assertIn("assertMetadataRepairParentClean(parent);", source)
        self.assertIn("assertMetadataRepairParentClean(preflightResult.parent);", source)
        self.assertIn("await parent.reload(null, true);", source)
        self.assertIn("Zotero.Items.unload(itemID);", source)
        self.assertIn("freshMetadataRepairFailureInspection", source)
        self.assertIn('Zotero.DB.addCurrentCallback("commit"', source)
        self.assertIn('Zotero.DB.addCurrentCallback("rollback"', source)
        apply_start = source.index("async function applyMetadataRepair")
        apply_end = source.index("async function freshMetadataRepairFailureInspection")
        apply_source = source[apply_start:apply_end]
        before_save = apply_source.split("await preflightResult.parent.save()", 1)[0]
        self.assertNotIn("await ", before_save)
        self.assertNotIn("abstractNote", apply_source)
        self.assertNotIn('setField("url"', apply_source)
        self.assertNotIn("setTags", apply_source)

    def test_compiled_transaction_does_not_copy_private_evidence_locators(self) -> None:
        manifest = compile_source(self.source)
        serialized = json.dumps(manifest)
        self.assertNotIn("artifact:synthetic-pdf", serialized)
        self.assertNotIn("example.invalid", serialized)
        self.assertNotIn("sidecar.json", serialized)

    def test_transaction_manifest_digest_binds_sidecar_reference(self) -> None:
        manifest = compile_source(self.source)
        manifest["source_evidence_sidecar_ref"]["content_sha256"] = (
            "sha256:" + "f" * 64
        )
        with self.assertRaisesRegex(bridge.BridgeError, "manifest_sha256"):
            bridge.validate_metadata_repair_manifest(manifest)


if __name__ == "__main__":
    unittest.main()
