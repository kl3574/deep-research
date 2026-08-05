#!/usr/bin/env python3
"""Offline tests for the Zotero declarative bridge."""

from __future__ import annotations

import hashlib
import hmac
import importlib.util
import json
import stat
import subprocess
import tempfile
import types
import unittest
import zipfile
from pathlib import Path
from unittest import mock

import zotero_declarative_bridge as bridge


HERE = Path(__file__).resolve().parent
PLUGIN_ROOT = HERE.parent / "assets" / "zotero-plugin"


def load_builder():
    spec = importlib.util.spec_from_file_location("bridge_build_xpi", HERE / "build_xpi.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader
    spec.loader.exec_module(module)
    return module


def load_packed_installer():
    spec = importlib.util.spec_from_file_location(
        "bridge_install_packed_xpi", HERE / "install_packed_xpi.py"
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader
    spec.loader.exec_module(module)
    return module


def unsigned_manifest() -> dict:
    identity = {
        "doi": "10.1/fixture",
        "item_type": "journalArticle",
        "key": "PARENT01",
        "library_id": 2,
        "title": "Fixture parent",
    }
    return {
        "schema": bridge.MANIFEST_SCHEMA,
        "transaction_id": "fixture-transaction",
        "generated_at": "2026-08-05T00:00:00Z",
        "target": {
            "library_id": 2,
            "library_type": "group",
            "library_type_id": 123,
            "library_name": "Fixture",
            "collection_id": 40,
            "collection_key": "ABCDEFGH",
            "collection_path": [{"key": "ABCDEFGH", "name": "Target"}],
            "require_editable": True,
            "require_files_editable": False,
        },
        "entries": [
            {
                "parent": {
                    "key": "PARENT01",
                    "version": 7,
                    "item_type": "journalArticle",
                    "title": "Fixture parent",
                    "doi": "10.1/fixture",
                    "identity_sha256": bridge.sha256_value(identity),
                    "expected_target_membership": False,
                },
                "operations": [
                    {"type": "ensure_collection_membership", "expected_present": False}
                ],
            }
        ],
    }


class BridgeTests(unittest.TestCase):
    def test_zotero_9_runtime_contract_and_packed_profile_shape(self) -> None:
        builder = load_builder()
        installer = load_packed_installer()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            zotero_root = root / "zotero"
            profile = zotero_root / "fixture.default"
            profile.mkdir(parents=True)
            (zotero_root / "profiles.ini").write_text(
                "[Profile0]\nName=default\nIsRelative=1\nPath=fixture.default\nDefault=1\n",
                encoding="utf-8",
            )
            (profile / "compatibility.ini").write_text(
                "[Compatibility]\nLastVersion=9.0.6_fixture/build\n",
                encoding="utf-8",
            )
            xpi = root / "bridge.xpi"
            builder.build(xpi, PLUGIN_ROOT)
            receipt = root / "install-receipt.json"
            with mock.patch.object(installer, "zotero_is_running", return_value=False):
                result = installer.install_packed_xpi(xpi, profile, receipt)
            destination = profile / "extensions" / f"{installer.PLUGIN_ID}.xpi"
            self.assertEqual(destination.read_bytes(), xpi.read_bytes())
            self.assertEqual(result["destination"], str(destination))
            self.assertEqual(stat.S_IMODE(receipt.stat().st_mode), 0o600)
            self.assertFalse((profile / "extensions.json").exists())
            self.assertFalse(any(profile.glob("*.sqlite")))

    def test_manifest_and_bootstrap_expose_zotero_9_diagnostics(self) -> None:
        manifest = json.loads((PLUGIN_ROOT / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["manifest_version"], 2)
        self.assertEqual(manifest["version"], "0.1.1")
        self.assertEqual(manifest["applications"]["zotero"]["strict_max_version"], "9.0.*")
        bootstrap = (PLUGIN_ROOT / "bootstrap.js").read_text(encoding="utf-8")
        self.assertIn("unsupported Zotero runtime", bootstrap)
        self.assertIn("Zotero.logError(error)", bootstrap)

    def test_manifest_seal_validate_and_unknown_field_rejection(self) -> None:
        sealed = bridge.seal_manifest(unsigned_manifest())
        self.assertEqual(bridge.validate_manifest(sealed), sealed)
        sealed["entries"][0]["operations"][0]["javascript"] = "1+1"
        with self.assertRaisesRegex(bridge.BridgeError, "unknown"):
            bridge.validate_manifest(sealed)

    def test_note_requires_hash_h1_and_non_executable_html(self) -> None:
        manifest = unsigned_manifest()
        html = "<h1>检索标题</h1><p>内容</p>"
        manifest["entries"][0]["parent"]["expected_target_membership"] = True
        manifest["entries"][0]["operations"] = [
            {
                "type": "ensure_child_note",
                "note_key": None,
                "expected_note_version": None,
                "expected_old_sha256": None,
                "expected_child_note_keys": [],
                "new_html": html,
                "new_sha256": "sha256:" + hashlib.sha256(html.encode()).hexdigest(),
            }
        ]
        bridge.seal_manifest(manifest)
        manifest["entries"][0]["operations"][0]["new_html"] = "<h1>x</h1><script>bad()</script>"
        with self.assertRaisesRegex(bridge.BridgeError, "executable"):
            bridge.seal_manifest(manifest)

    def test_capability_requires_private_regular_literal_loopback_file(self) -> None:
        capability = {
            "schema": bridge.CAPABILITY_SCHEMA,
            "endpoint": "http://127.0.0.1:23119" + bridge.ENDPOINT_PATH,
            "key_id": "a" * 16,
            "capability_token": "b" * 64,
            "created_at": "2026-08-05T00:00:00Z",
            "zotero_version": "9.0.6",
            "plugin_version": "0.1.0",
            "expires_on_shutdown": True,
        }
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "capability.json"
            path.write_text(json.dumps(capability), encoding="utf-8")
            path.chmod(0o600)
            self.assertEqual(bridge.load_capability(path)["key_id"], "a" * 16)
            path.chmod(0o644)
            with self.assertRaisesRegex(bridge.BridgeError, "group/other"):
                bridge.load_capability(path)
            path.chmod(0o600)
            capability["endpoint"] = "http://localhost:23119" + bridge.ENDPOINT_PATH
            path.write_text(json.dumps(capability), encoding="utf-8")
            with self.assertRaisesRegex(bridge.BridgeError, "literal-loopback"):
                bridge.load_capability(path)

    def test_request_hmac_is_over_canonical_unsigned_envelope(self) -> None:
        capability = {
            "endpoint": "http://127.0.0.1:23119" + bridge.ENDPOINT_PATH,
            "key_id": "a" * 16,
            "capability_token": "b" * 64,
        }
        captured = {}

        class Response:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def read(self):
                return json.dumps(
                    {
                        "schema": bridge.RESPONSE_SCHEMA,
                        "status": "available",
                        "action": "probe",
                        "request_id": "x",
                        "result": {"status": "available"},
                        "error": None,
                    }
                ).encode()

        class Opener:
            def open(self, request, timeout):
                captured["content_type"] = request.headers["Content-type"]
                captured["body"] = json.loads(request.data)
                captured["timeout"] = timeout
                return Response()

        with mock.patch.object(bridge.urllib.request, "build_opener", return_value=Opener()):
            bridge.bridge_request(capability, "probe", {})
        envelope = captured["body"]
        mac = envelope.pop("mac")
        expected = hmac.new(bytes.fromhex("b" * 64), bridge.canonical_bytes(envelope), hashlib.sha256).hexdigest()
        self.assertEqual(mac, expected)
        self.assertEqual(captured["content_type"], "application/octet-stream")
        self.assertNotIn("capability_token", captured["body"])

    def test_attachment_repair_compiler_preserves_exact_bindings(self) -> None:
        pdf = b"%PDF-1.7\nfixture\n"
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            pdf_path = root / "paper.pdf"
            pdf_path.write_bytes(pdf)
            repair = {
                "schema": "ZoteroAttachmentRepairManifest/v1",
                "generated_at": "2026-08-05T00:00:00Z",
                "target": {
                    "group_id": 123,
                    "library_id": 2,
                    "library_name": "Fixture",
                    "local_collection_id": 40,
                    "collection_key": "ABCDEFGH",
                    "collection_path": [{"key": "ABCDEFGH", "name": "Target"}],
                    "require_library_editable": True,
                    "require_files_editable": True,
                },
                "baseline": {},
                "repair_source": {},
                "entries": [
                    {
                        "action": "attach_missing_pdf",
                        "parent": {
                            "key": "PARENT01",
                            "version": 7,
                            "item_type": "journalArticle",
                            "title": "Fixture parent",
                            "doi": "10.1/fixture",
                        },
                        "expected_attachments": [
                            {
                                "key": "ATTACH01",
                                "version": 2,
                                "content_type": "application/pdf",
                                "link_mode": "imported_file",
                            }
                        ],
                        "source_pdf": {
                            "path": str(pdf_path),
                            "size_bytes": len(pdf),
                            "sha256": "sha256:" + hashlib.sha256(pdf).hexdigest(),
                            "magic": "%PDF-",
                            "content_type": "application/pdf",
                        },
                        "source_provenance": {},
                    }
                ],
                "summary": {"total": 1, "attach_missing_pdf": 1, "metadata_only_skip": 0},
            }
            repair_bytes = json.dumps(
                repair,
                ensure_ascii=True,
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
            repair["manifest_digest_sha256"] = (
                "sha256:" + hashlib.sha256(repair_bytes).hexdigest()
            )
            source = root / "repair.json"
            source.write_text(json.dumps(repair), encoding="utf-8")
            compiled = bridge.compile_attachment_repair(source, "fixture-repair")
        self.assertEqual(compiled["entries"][0]["operations"][0]["source_size_bytes"], len(pdf))
        self.assertTrue(compiled["target"]["require_files_editable"])
        bridge.validate_manifest(compiled)

    def test_deterministic_xpi_has_only_fixed_files_and_no_dynamic_code(self) -> None:
        builder = load_builder()
        with tempfile.TemporaryDirectory() as directory:
            first = Path(directory) / "first.xpi"
            second = Path(directory) / "second.xpi"
            digest1 = builder.build(first, PLUGIN_ROOT)
            digest2 = builder.build(second, PLUGIN_ROOT)
            self.assertEqual(digest1, digest2)
            with zipfile.ZipFile(first) as archive:
                self.assertEqual(tuple(archive.namelist()), builder.FILES)
                source = archive.read("bootstrap.js").decode() + archive.read("bridge_core.js").decode()
        self.assertNotIn("eval(", source)
        self.assertNotIn("new Function", source)
        self.assertNotIn("executeSQL", source)
        self.assertNotIn("Zotero.DB.query", source)
        self.assertIn("application/octet-stream", source)
        self.assertIn("logFilter", source)

    def test_node_core_contract(self) -> None:
        result = subprocess.run(
            ["node", str(HERE / "test_bridge_core.js")],
            check=False,
            capture_output=True,
            text=True,
            timeout=15,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("11 checks passed", result.stdout)

    def test_membership_compiler_binds_live_parent_and_keyed_path(self) -> None:
        args = types.SimpleNamespace(
            group_id=123,
            library_id=2,
            library_name="Fixture",
            local_collection_id=40,
            collection_key="ABCDEFGH",
            parent_key=["PARENT01"],
            base_url=bridge.BASE_URL,
            transaction_id="membership-fixture",
        )
        record = {
            "version": 7,
            "data": {
                "key": "PARENT01",
                "version": 7,
                "itemType": "journalArticle",
                "title": "Fixture parent",
                "DOI": "10.1/fixture",
                "collections": [],
            },
        }
        with mock.patch.object(
            bridge,
            "collection_contract",
            return_value=([{"key": "ABCDEFGH", "name": "Target"}], {}),
        ), mock.patch.object(bridge, "live_parent", return_value=record):
            compiled = bridge.compile_membership(args)
        self.assertFalse(compiled["target"]["require_files_editable"])
        self.assertEqual(
            compiled["entries"][0]["operations"][0]["type"],
            "ensure_collection_membership",
        )
        bridge.validate_manifest(compiled)

    def test_note_migration_compiler_binds_live_parent_and_note_bytes(self) -> None:
        note_html = "<h1>检索标题</h1><p>经审核内容</p>"
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            note_path = root / "note.html"
            note_path.write_text(note_html, encoding="utf-8")
            migration = {
                "manifest_version": "2",
                "target": {
                    "group_id": 123,
                    "library_id": 2,
                    "library_name": "Fixture",
                    "local_collection_id": 40,
                    "collection_key": "ABCDEFGH",
                    "collection_path": ["Target"],
                },
                "entries": [
                    {
                        "status": "create_verified",
                        "parent_key": "PARENT01",
                        "parent_version": 7,
                        "child_note_inventory": [],
                        "new_path": str(note_path),
                        "new_sha256": hashlib.sha256(note_html.encode()).hexdigest(),
                    }
                ],
            }
            source = root / "migration.json"
            source.write_text(json.dumps(migration), encoding="utf-8")
            record = {
                "version": 7,
                "data": {
                    "key": "PARENT01",
                    "version": 7,
                    "itemType": "journalArticle",
                    "title": "Fixture parent",
                    "DOI": "10.1/fixture",
                    "collections": ["ABCDEFGH"],
                },
            }
            with mock.patch.object(
                bridge,
                "collection_contract",
                return_value=([{"key": "ABCDEFGH", "name": "Target"}], {}),
            ), mock.patch.object(bridge, "live_parent", return_value=record):
                compiled = bridge.compile_note_migration(
                    source,
                    "note-fixture",
                    bridge.BASE_URL,
                )
        operation = compiled["entries"][0]["operations"][0]
        self.assertEqual(operation["type"], "ensure_child_note")
        self.assertEqual(operation["new_html"], note_html)
        self.assertIsNone(operation["note_key"])
        bridge.validate_manifest(compiled)

    def test_private_writer_is_exclusive_and_mode_600(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "receipt.json"
            bridge.write_private_json(path, {"ok": True})
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
            with self.assertRaisesRegex(bridge.BridgeError, "overwrite"):
                bridge.write_private_json(path, {"ok": False})


if __name__ == "__main__":
    unittest.main()
