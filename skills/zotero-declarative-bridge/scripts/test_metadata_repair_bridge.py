#!/usr/bin/env python3
"""Focused compiler/schema tests for the isolated metadata-repair transaction."""

from __future__ import annotations

import copy
import contextlib
import hashlib
import importlib.util
import io
import json
import subprocess
import sys
import tempfile
import unittest
import urllib.error
import urllib.parse
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


def v2_live_records(*, post_commit: bool) -> tuple[dict, list[dict]]:
    parent_data, wrappers = fixture_module.synthetic_v2_state(post_commit=post_commit)
    parent_record = {"version": parent_data["version"], "data": parent_data}
    records = []
    for wrapper in wrappers:
        record = {"data": wrapper["data"]}
        if wrapper["data"]["itemType"] == "attachment":
            record["links"] = {
                "enclosure": {
                    "href": "file://" + urllib.parse.quote(wrapper["storage_path"]),
                }
            }
        records.append(record)
    return parent_record, records


def compile_v2_source(
    source: dict,
    *,
    post_commit: bool = False,
    readback_only: bool = False,
    parent_version: int | None = None,
    attachment_evidence: dict | None = None,
) -> dict:
    keyed_path = [
        {"key": "ROOT0001", "name": "Research"},
        {"key": "COLL0001", "name": "Methods"},
    ]
    parent_record, child_records = v2_live_records(post_commit=post_commit)
    if parent_version is not None:
        parent_record["version"] = parent_version
        parent_record["data"]["version"] = parent_version
    attachment_record = next(
        record
        for record in child_records
        if record["data"]["itemType"] == "attachment"
    )
    storage_path = bridge._storage_path_from_child_record(attachment_record)

    def observed_attachment(*_args, **kwargs):
        return attachment_evidence or {
            "storage_path": storage_path,
            "content_sha256": kwargs["expected_content_sha256"],
            "size_bytes": kwargs["expected_size_bytes"],
            "content_md5": attachment_record["data"]["md5"],
        }

    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "source-v2.json"
        path.write_text(json.dumps(source), encoding="utf-8")
        with mock.patch.object(
            bridge,
            "collection_contract",
            return_value=(keyed_path, {"version": 7, "data": {"version": 7}}),
        ), mock.patch.object(
            bridge, "live_parent", return_value=parent_record
        ), mock.patch.object(
            bridge, "live_all_child_records", return_value=child_records
        ), mock.patch.object(
            bridge,
            "local_api_attachment_file_evidence",
            side_effect=observed_attachment,
        ), mock.patch.object(
            bridge, "live_library_top_items", return_value=[parent_record]
        ):
            return bridge.compile_reviewed_metadata_repair(
                path,
                transaction_id="synthetic-metadata-repair-v2",
                local_collection_id=40,
                source_hash_contract="canonical-json-v1",
                base_url=bridge.BASE_URL,
                readback_only=readback_only,
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

    def test_v2_compiler_binds_guard_and_preserves_v1_operation_write_domain(self) -> None:
        source = fixture_module.build_reviewed(fixture_module.synthetic_v2_draft())
        manifest = compile_v2_source(source)
        self.assertEqual(manifest["schema"], bridge.METADATA_REPAIR_MANIFEST_SCHEMA_V2)
        self.assertEqual(manifest["execution_intent"], "repair")
        self.assertEqual(
            manifest["entry"]["operation"]["type"],
            "ensure_parent_journal_metadata_v1",
        )
        self.assertEqual(
            manifest["entry"]["serializer_guard"],
            source["entry"]["serializer_guard"],
        )
        bridge.validate_any_manifest(manifest)

    def test_v2_readback_only_compiles_post_commit_managed_equivalence_without_apply(self) -> None:
        source = fixture_module.build_reviewed(fixture_module.synthetic_v2_draft())
        manifest = compile_v2_source(
            source,
            post_commit=True,
            readback_only=True,
        )
        self.assertEqual(manifest["execution_intent"], "readback_only")
        self.assertEqual(
            manifest["entry"]["parent"]["version"],
            source["entry"]["parent"]["version"],
        )
        bridge.validate_any_manifest(manifest)

    def test_local_api_attachment_redirect_reads_bytes_and_rejects_drift_or_escape(self) -> None:
        payload = b"%PDF-synthetic-local-api-evidence\n"
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "Zotero" / "storage"
            attachment_dir = root / "PDF00001"
            attachment_dir.mkdir(parents=True)
            pdf_path = attachment_dir / "paper.pdf"
            pdf_path.write_bytes(payload)
            expected_sha = "sha256:" + hashlib.sha256(payload).hexdigest()

            class RedirectingOpener:
                location = pdf_path.as_uri()

                def open(self, request, timeout):
                    self.request_url = request.full_url
                    raise urllib.error.HTTPError(
                        request.full_url,
                        302,
                        "Found",
                        {"Location": self.location},
                        None,
                    )

            opener = RedirectingOpener()
            with mock.patch.object(bridge, "ZOTERO_STORAGE_ROOT", root), mock.patch.object(
                bridge.urllib.request,
                "build_opener",
                return_value=opener,
            ):
                real_open = bridge.os.open
                real_read = bridge.os.read
                real_sha256 = bridge.hashlib.sha256
                real_md5 = bridge.hashlib.md5
                open_descriptors = []
                read_descriptors = []
                read_blocks = []
                digest_updates = {"sha256": [], "md5": []}
                digest_constructors = {"sha256": 0, "md5": 0}

                def counted_open(*args, **kwargs):
                    descriptor = real_open(*args, **kwargs)
                    open_descriptors.append(descriptor)
                    return descriptor

                def counted_read(descriptor, size):
                    read_descriptors.append(descriptor)
                    block = real_read(descriptor, size)
                    read_blocks.append(block)
                    return block

                class DigestSpy:
                    def __init__(self, algorithm, digest):
                        self.algorithm = algorithm
                        self.digest = digest

                    def update(self, block):
                        digest_updates[self.algorithm].append(block)
                        return self.digest.update(block)

                    def hexdigest(self):
                        return self.digest.hexdigest()

                def sha256_spy(*args, **kwargs):
                    digest_constructors["sha256"] += 1
                    return DigestSpy("sha256", real_sha256(*args, **kwargs))

                def md5_spy(*args, **kwargs):
                    digest_constructors["md5"] += 1
                    return DigestSpy("md5", real_md5(*args, **kwargs))

                with mock.patch.object(
                    bridge.os,
                    "open",
                    side_effect=counted_open,
                ), mock.patch.object(
                    bridge.os,
                    "read",
                    side_effect=counted_read,
                ), mock.patch.object(
                    bridge.hashlib,
                    "sha256",
                    side_effect=sha256_spy,
                ), mock.patch.object(
                    bridge.hashlib,
                    "md5",
                    side_effect=md5_spy,
                ):
                    evidence = bridge.local_api_attachment_file_evidence(
                        999999,
                        "PDF00001",
                        expected_size_bytes=len(payload),
                        expected_content_sha256=expected_sha,
                    )
                self.assertEqual(evidence["content_sha256"], expected_sha)
                self.assertEqual(evidence["size_bytes"], len(payload))
                self.assertEqual(
                    evidence["content_md5"],
                    hashlib.md5(payload, usedforsecurity=False).hexdigest(),
                )
                self.assertEqual(len(open_descriptors), 1)
                self.assertEqual(read_descriptors, open_descriptors * 2)
                self.assertEqual(read_blocks, [payload, b""])
                self.assertEqual(digest_constructors, {"sha256": 1, "md5": 1})
                self.assertEqual(digest_updates, {"sha256": [payload], "md5": [payload]})
                self.assertIs(digest_updates["sha256"][0], read_blocks[0])
                self.assertIs(digest_updates["md5"][0], read_blocks[0])
                self.assertTrue(opener.request_url.endswith("/items/PDF00001/file"))

                with self.assertRaisesRegex(bridge.BridgeError, "size drift"):
                    bridge.local_api_attachment_file_evidence(
                        999999,
                        "PDF00001",
                        expected_size_bytes=len(payload) + 1,
                        expected_content_sha256=expected_sha,
                    )
                with self.assertRaisesRegex(bridge.BridgeError, "content hash drift"):
                    bridge.local_api_attachment_file_evidence(
                        999999,
                        "PDF00001",
                        expected_size_bytes=len(payload),
                        expected_content_sha256="sha256:" + "a" * 64,
                    )

                escaped = Path(directory) / "private-path-must-not-leak.pdf"
                escaped.write_bytes(payload)
                opener.location = escaped.as_uri()
                with self.assertRaises(bridge.BridgeError) as caught:
                    bridge.local_api_attachment_file_evidence(
                        999999,
                        "PDF00001",
                        expected_size_bytes=len(payload),
                        expected_content_sha256=expected_sha,
                    )
                self.assertNotIn(str(escaped), str(caught.exception))

    def test_v2_compiler_never_backfills_observed_attachment_evidence(self) -> None:
        source = fixture_module.build_reviewed(fixture_module.synthetic_v2_draft())
        with self.assertRaisesRegex(bridge.BridgeError, "observed file evidence drift"):
            compile_v2_source(
                source,
                attachment_evidence={
                    "storage_path": "/synthetic/storage/PDF00001/paper.pdf",
                    "content_sha256": "sha256:" + "a" * 64,
                    "size_bytes": 1234,
                },
            )

    def test_v2_readback_only_rejects_regressed_parent_version(self) -> None:
        source = fixture_module.build_reviewed(fixture_module.synthetic_v2_draft())
        with self.assertRaisesRegex(bridge.BridgeError, "version regressed"):
            compile_v2_source(
                source,
                post_commit=True,
                readback_only=True,
                parent_version=2,
            )

    def test_readback_only_rejects_v1_reviewed_source(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "source-v1.json"
            path.write_text(json.dumps(self.source), encoding="utf-8")
            with self.assertRaisesRegex(bridge.BridgeError, "requires reviewed source v2"):
                bridge.compile_reviewed_metadata_repair(
                    path,
                    transaction_id="synthetic-readback-only-v1",
                    local_collection_id=40,
                    source_hash_contract="canonical-json-v1",
                    base_url=bridge.BASE_URL,
                    readback_only=True,
                )

    def test_v2_readback_only_rejects_attachment_title_drift(self) -> None:
        source = fixture_module.build_reviewed(fixture_module.synthetic_v2_draft())
        parent_record, child_records = v2_live_records(post_commit=True)
        child_records[1]["data"]["title"] = "Changed attachment title"
        keyed_path = [
            {"key": "ROOT0001", "name": "Research"},
            {"key": "COLL0001", "name": "Methods"},
        ]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "source-v2.json"
            path.write_text(json.dumps(source), encoding="utf-8")
            with mock.patch.object(
                bridge,
                "collection_contract",
                return_value=(keyed_path, {"version": 7, "data": {"version": 7}}),
            ), mock.patch.object(
                bridge, "live_parent", return_value=parent_record
            ), mock.patch.object(
                bridge, "live_all_child_records", return_value=child_records
            ), mock.patch.object(
                bridge,
                "local_api_attachment_file_evidence",
                return_value={
                    "storage_path": bridge._storage_path_from_child_record(
                        child_records[1]
                    ),
                    "content_sha256": source["entry"]["children"][1][
                        "content_sha256"
                    ],
                    "size_bytes": source["entry"]["children"][1]["size_bytes"],
                    "content_md5": child_records[1]["data"]["md5"],
                },
            ), mock.patch.object(
                bridge, "live_library_top_items", return_value=[parent_record]
            ):
                with self.assertRaisesRegex(bridge.BridgeError, "stable_data_sha256"):
                    bridge.compile_reviewed_metadata_repair(
                        path,
                        transaction_id="synthetic-drift-v2",
                        local_collection_id=40,
                        source_hash_contract="canonical-json-v1",
                        base_url=bridge.BASE_URL,
                        readback_only=True,
                    )

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
        self.assertIn("--readback-only", result.stdout)

    def test_cli_readback_only_rejects_preview_and_apply_before_request(self) -> None:
        source = fixture_module.build_reviewed(fixture_module.synthetic_v2_draft())
        manifest = compile_v2_source(source, post_commit=True, readback_only=True)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest_path = root / "manifest.json"
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            capability_path = root / "capability.json"
            for action in ("preview", "apply"):
                with self.subTest(action=action):
                    argv = [
                        "zotero_declarative_bridge.py",
                        action,
                        str(manifest_path),
                        "--capability-file",
                        str(capability_path),
                        "--receipt",
                        str(root / f"{action}-receipt.json"),
                    ]
                    if action == "apply":
                        argv.extend(
                            [
                                "--preview-receipt",
                                str(root / "preview.json"),
                                "--yes",
                            ]
                        )
                    stderr = io.StringIO()
                    with mock.patch.object(sys, "argv", argv), mock.patch.object(
                        bridge, "load_capability", return_value={}
                    ), mock.patch.object(
                        bridge, "bridge_request"
                    ) as request, contextlib.redirect_stderr(stderr):
                        self.assertEqual(bridge.main(), 2)
                    request.assert_not_called()
                    self.assertIn("forbids preview and apply", stderr.getvalue())

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
