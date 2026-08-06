#!/usr/bin/env python3
"""Offline tests for the Zotero declarative bridge."""

from __future__ import annotations

import contextlib
import hashlib
import hmac
import importlib.util
import io
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


def reviewed_batch_fixture(old_note_html: str = "<h1>Old</h1><p>Baseline</p>") -> dict:
    new_note_html = (
        '<div data-schema-version="9"><h1>高维代理模型分析</h1>'
        "<p>适用场景：先筛选，再校准总效应。局限：仅由摘要支持。</p>"
        '<p>指标 <span class="math">$S_i=V_i/V$</span> 用于排序。</p></div>'
    )
    new_short_title = "高维代理模型分析：应先筛选再校准总效应"
    parent = {
        "key": "PARENT01",
        "version": 7,
        "title": "A generic sensitivity study",
        "doi": "10.1/generic",
        "expected_target_membership": True,
    }
    parent["identity_sha256"] = bridge.sha256_value(parent)
    entry = {
        "parent": parent,
        "operations": [
            {
                "type": "ensure_parent_short_title",
                "parent_key": "PARENT01",
                "expected_parent_version": 7,
                "expected_old_value": "Old",
                "new_short_title": new_short_title,
                "new_short_title_sha256": "sha256:"
                + hashlib.sha256(new_short_title.encode()).hexdigest(),
            },
            {
                "type": "ensure_child_note",
                "note_key": "NOTE0001",
                "expected_note_version": 3,
                "expected_child_note_keys": ["NOTE0001"],
                "expected_old_sha256": "sha256:"
                + hashlib.sha256(old_note_html.encode()).hexdigest(),
                "new_html": new_note_html,
                "new_sha256": "sha256:"
                + hashlib.sha256(new_note_html.encode()).hexdigest(),
            },
        ],
        "draft_entry_sha256": "sha256:" + "d" * 64,
    }
    entry["entry_sha256"] = bridge.sha256_value(entry)
    batch = {
        "schema": bridge.REVIEWED_BATCH_SCHEMA,
        "status": "reviewed_requires_bridge_compile",
        "created_at": "2026-08-06T00:00:00Z",
        "private": True,
        "source": {"kind": "generic-fixture"},
        "target": {
            "group_id": 123,
            "library_type": "group",
            "library_type_id": 123,
            "local_library_id": 2,
            "library_name": "Example Research Library",
            "collection_key": "COLL0001",
            "collection_version": 9,
            "collection_path": ["Research", "Methods"],
            "internal_collection_id": None,
        },
        "entries": [entry],
        "summary": {"entry_count": 1, "operation_count": 2},
        "executable": False,
        "execution_contract": {"compiler": "constrained-bridge"},
    }
    batch["manifest_sha256"] = bridge.sha256_value(batch)
    return batch


class BridgeTests(unittest.TestCase):
    def test_manifest_and_bootstrap_expose_zotero_9_diagnostics(self) -> None:
        manifest = json.loads((PLUGIN_ROOT / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["manifest_version"], 2)
        self.assertEqual(manifest["version"], "0.1.8")
        self.assertEqual(
            manifest["applications"]["zotero"]["update_url"],
            (
                "https://raw.githubusercontent.com/kl3574/deep-research/main/skills/"
                "zotero-declarative-bridge/assets/zotero-plugin/updates.json"
            ),
        )
        self.assertEqual(manifest["applications"]["zotero"]["strict_max_version"], "9.0.*")
        bootstrap = (PLUGIN_ROOT / "bootstrap.js").read_text(encoding="utf-8")
        self.assertIn("unsupported Zotero runtime", bootstrap)
        self.assertIn("Zotero.logError(error)", bootstrap)
        self.assertIn('row.live.parent.setField("shortTitle", operation.new_short_title)', bootstrap)
        self.assertIn('"ensure_parent_short_title"', bootstrap)
        self.assertIn("parent_version_precondition", bootstrap)
        self.assertIn("parent_current_synced_version", bootstrap)
        self.assertIn('"locally_modified_pending_sync"', (PLUGIN_ROOT / "bridge_core.js").read_text(encoding="utf-8"))
        self.assertIn('action === "resolve_collection"', bootstrap)
        self.assertIn("getByLibraryAndKeyAsync(", bootstrap)
        self.assertIn("dbCommitConfirmed = true", bootstrap)
        self.assertIn("commitStateAfterFailure", bootstrap)
        self.assertIn('new ProtocolError(error.message, 409, "child_drift")', bootstrap)
        self.assertIn("noteStorageHTMLFingerprint", bootstrap)

    def test_xpi_build_rejects_missing_zotero_update_url(self) -> None:
        builder = load_builder()
        with tempfile.TemporaryDirectory() as directory:
            plugin_root = Path(directory) / "plugin"
            plugin_root.mkdir()
            for name in (*builder.FILES, "updates.json"):
                (plugin_root / name).write_bytes((PLUGIN_ROOT / name).read_bytes())
            manifest_path = plugin_root / "manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            del manifest["applications"]["zotero"]["update_url"]
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "update URL"):
                builder.build(Path(directory) / "missing-update-url.xpi", plugin_root)

    def test_xpi_build_rejects_wrong_zotero_update_url(self) -> None:
        builder = load_builder()
        with tempfile.TemporaryDirectory() as directory:
            plugin_root = Path(directory) / "plugin"
            plugin_root.mkdir()
            for name in (*builder.FILES, "updates.json"):
                (plugin_root / name).write_bytes((PLUGIN_ROOT / name).read_bytes())
            manifest_path = plugin_root / "manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["applications"]["zotero"]["update_url"] = "https://example.invalid/updates.json"
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "update URL"):
                builder.build(Path(directory) / "wrong-update-url.xpi", plugin_root)

    def test_xpi_build_rejects_duplicate_current_version(self) -> None:
        builder = load_builder()
        with tempfile.TemporaryDirectory() as directory:
            plugin_root = Path(directory) / "plugin"
            plugin_root.mkdir()
            for name in (*builder.FILES, "updates.json"):
                (plugin_root / name).write_bytes((PLUGIN_ROOT / name).read_bytes())
            updates_path = plugin_root / "updates.json"
            updates = json.loads(updates_path.read_text(encoding="utf-8"))
            entries = updates["addons"][builder.PLUGIN_ID]["updates"]
            entries.append(json.loads(json.dumps(entries[0])))
            updates_path.write_text(json.dumps(updates), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "one current version"):
                builder.build(Path(directory) / "duplicate-version.xpi", plugin_root)

    def test_xpi_build_rejects_wrong_release_tag(self) -> None:
        builder = load_builder()
        with tempfile.TemporaryDirectory() as directory:
            plugin_root = Path(directory) / "plugin"
            plugin_root.mkdir()
            for name in (*builder.FILES, "updates.json"):
                (plugin_root / name).write_bytes((PLUGIN_ROOT / name).read_bytes())
            updates_path = plugin_root / "updates.json"
            updates = json.loads(updates_path.read_text(encoding="utf-8"))
            entry = updates["addons"][builder.PLUGIN_ID]["updates"][0]
            entry["update_link"] = entry["update_link"].replace(
                f"/{builder.RELEASE_TAG}/", "/v0.0.0/"
            )
            updates_path.write_text(json.dumps(updates), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "release tag and asset"):
                builder.build(Path(directory) / "wrong-release-tag.xpi", plugin_root)

    def test_xpi_build_rejects_wrong_release_asset(self) -> None:
        builder = load_builder()
        with tempfile.TemporaryDirectory() as directory:
            plugin_root = Path(directory) / "plugin"
            plugin_root.mkdir()
            for name in (*builder.FILES, "updates.json"):
                (plugin_root / name).write_bytes((PLUGIN_ROOT / name).read_bytes())
            updates_path = plugin_root / "updates.json"
            updates = json.loads(updates_path.read_text(encoding="utf-8"))
            entry = updates["addons"][builder.PLUGIN_ID]["updates"][0]
            entry["update_link"] = entry["update_link"].replace(
                builder.XPI_FILENAME, "zotero-declarative-bridge-wrong.xpi"
            )
            updates_path.write_text(json.dumps(updates), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "release tag and asset"):
                builder.build(Path(directory) / "wrong-release-asset.xpi", plugin_root)

    def test_xpi_build_rejects_wrong_release_hash(self) -> None:
        builder = load_builder()
        with tempfile.TemporaryDirectory() as directory:
            plugin_root = Path(directory) / "plugin"
            plugin_root.mkdir()
            for name in (*builder.FILES, "updates.json"):
                (plugin_root / name).write_bytes((PLUGIN_ROOT / name).read_bytes())
            updates_path = plugin_root / "updates.json"
            updates = json.loads(updates_path.read_text(encoding="utf-8"))
            updates["addons"][builder.PLUGIN_ID]["updates"][0]["update_hash"] = "sha256:" + "0" * 64
            updates_path.write_text(json.dumps(updates), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "XPI hash"):
                builder.build(Path(directory) / "wrong-release-hash.xpi", plugin_root)

    def test_xpi_build_rejects_missing_updates_json(self) -> None:
        builder = load_builder()
        with tempfile.TemporaryDirectory() as directory:
            plugin_root = Path(directory) / "plugin"
            plugin_root.mkdir()
            for name in builder.FILES:
                (plugin_root / name).write_bytes((PLUGIN_ROOT / name).read_bytes())
            with self.assertRaisesRegex(ValueError, "invalid external update manifest"):
                builder.build(Path(directory) / "missing-updates.xpi", plugin_root)

    def test_xpi_build_rejects_malformed_updates_json(self) -> None:
        builder = load_builder()
        with tempfile.TemporaryDirectory() as directory:
            plugin_root = Path(directory) / "plugin"
            plugin_root.mkdir()
            for name in builder.FILES:
                (plugin_root / name).write_bytes((PLUGIN_ROOT / name).read_bytes())
            (plugin_root / "updates.json").write_text("{not-json", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "invalid external update manifest"):
                builder.build(Path(directory) / "malformed-updates.xpi", plugin_root)

    def test_bootstrap_uses_plugin_sandbox_dom_parser(self) -> None:
        bootstrap = (PLUGIN_ROOT / "bootstrap.js").read_text(encoding="utf-8")
        self.assertIn(
            "noteStorageHTMLFingerprint(noteHTML, DOMParser)",
            bootstrap,
        )
        self.assertNotIn("hiddenDOMWindow.DOMParser", bootstrap)

    def test_stable_skill_excludes_security_sensitive_development_proxy(self) -> None:
        self.assertFalse((HERE / "install_development_proxy.py").exists())
        for path in (
            HERE.parent / "SKILL.md",
            HERE.parent / "references" / "install-uninstall.md",
            HERE.parent / "references" / "protocol.md",
        ):
            self.assertNotIn("install_development_proxy.py", path.read_text(encoding="utf-8"))

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

    def test_pdf_and_database_operations_cannot_share_a_manifest(self) -> None:
        pdf = b"%PDF-1.7\nfixture\n"
        with tempfile.TemporaryDirectory() as directory:
            pdf_path = Path(directory) / "paper.pdf"
            pdf_path.write_bytes(pdf)
            manifest = unsigned_manifest()
            manifest["target"]["require_files_editable"] = True
            manifest["entries"][0]["operations"].append(
                {
                    "type": "ensure_pdf_attachment",
                    "source_path": str(pdf_path),
                    "source_size_bytes": len(pdf),
                    "source_sha256": "sha256:" + hashlib.sha256(pdf).hexdigest(),
                    "source_magic": "%PDF-",
                    "expected_attachments": [],
                }
            )
            with self.assertRaisesRegex(bridge.BridgeError, "cannot share"):
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
                        "request_id": captured["body"]["request_id"],
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

    def test_collection_resolver_cli_binds_exact_input_and_prints_no_secret(self) -> None:
        capability = {
            "endpoint": "http://127.0.0.1:23119" + bridge.ENDPOINT_PATH,
            "key_id": "a" * 16,
            "capability_token": "b" * 64,
        }
        response = {
            "schema": bridge.RESPONSE_SCHEMA,
            "status": "resolved",
            "action": "resolve_collection",
            "request_id": "c" * 32,
            "result": {
                "status": "resolved",
                "library_id": 2,
                "collection_key": "COLL0001",
                "collection_id": 40,
            },
            "error": None,
        }
        args = types.SimpleNamespace(
            command="resolve-collection",
            capability_file=Path("/private/capability.json"),
            library_id=2,
            collection_key="COLL0001",
        )
        stdout = io.StringIO()
        with mock.patch.object(bridge, "parse_args", return_value=args), mock.patch.object(
            bridge, "load_capability", return_value=capability
        ), mock.patch.object(
            bridge, "bridge_request", return_value=response
        ) as request_mock, contextlib.redirect_stdout(stdout):
            self.assertEqual(bridge.main(), 0)
        request_mock.assert_called_once_with(
            capability,
            "resolve_collection",
            {"library_id": 2, "collection_key": "COLL0001"},
        )
        self.assertEqual(json.loads(stdout.getvalue()), response["result"])
        self.assertNotIn(capability["capability_token"], stdout.getvalue())
        unexpected = {**response["result"], "library_name": "private"}
        with self.assertRaisesRegex(bridge.BridgeError, "keys differ"):
            bridge.validate_collection_resolution(unexpected, 2, "COLL0001")
        with self.assertRaisesRegex(bridge.BridgeError, "binding mismatch"):
            bridge.validate_collection_resolution(response["result"], 3, "COLL0001")

    def test_cli_persists_structured_http_errors_without_stderr_leaks(self) -> None:
        capability = {
            "endpoint": "http://127.0.0.1:23119" + bridge.ENDPOINT_PATH,
            "key_id": "a" * 16,
            "capability_token": "b" * 64,
        }
        private_hash = "sha256:" + "c" * 64
        private_source = "/private/library/paper.pdf"
        private_parent_key = "PRIVATE1"
        for commit_state in ("rolled_back", "unknown", "committed_unverified"):
            with self.subTest(commit_state=commit_state), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                manifest_path = root / "private-manifest.json"
                manifest_path.write_text(
                    json.dumps(bridge.seal_manifest(unsigned_manifest())),
                    encoding="utf-8",
                )
                receipt_path = root / f"{commit_state}-receipt.json"
                returned = {}

                class Opener:
                    def open(self, request, timeout):
                        envelope = json.loads(request.data)
                        response = {
                            "schema": bridge.RESPONSE_SCHEMA,
                            "status": "failed",
                            "action": "readback",
                            "request_id": envelope["request_id"],
                            "result": None,
                            "error": {
                                "code": "transaction_failed",
                                "message": f"private source {private_source} hash {private_hash}",
                                "write_attempted": True,
                                "commit_state": commit_state,
                                "inspection": {
                                    "parent_key": private_parent_key,
                                    "source_path": private_source,
                                    "manifest_sha256": private_hash,
                                },
                                "execution_profile": "single_attachment_import",
                                "created_attachment_keys": ["SECRET01"],
                            },
                        }
                        returned["response"] = response
                        raise bridge.urllib.error.HTTPError(
                            request.full_url,
                            500,
                            "bridge failure",
                            {},
                            io.BytesIO(json.dumps(response).encode("utf-8")),
                        )

                args = types.SimpleNamespace(
                    command="readback",
                    manifest=manifest_path,
                    capability_file=root / "private-capability.json",
                    receipt=receipt_path,
                )
                stderr = io.StringIO()
                with mock.patch.object(bridge, "parse_args", return_value=args), mock.patch.object(
                    bridge, "load_capability", return_value=capability
                ), mock.patch.object(
                    bridge.urllib.request, "build_opener", return_value=Opener()
                ), contextlib.redirect_stderr(stderr):
                    return_code = bridge.main()
                self.assertNotEqual(return_code, 0)
                self.assertEqual(json.loads(receipt_path.read_text(encoding="utf-8")), returned["response"])
                self.assertEqual(stat.S_IMODE(receipt_path.stat().st_mode), 0o600)
                stderr_payload = json.loads(stderr.getvalue())
                self.assertEqual(
                    stderr_payload,
                    {
                        "error_code": "transaction_failed",
                        "commit_state": commit_state,
                        "receipt": str(receipt_path.resolve()),
                    },
                )
                for private_value in (
                    private_hash,
                    private_source,
                    private_parent_key,
                    "SECRET01",
                    capability["key_id"],
                    capability["capability_token"],
                    str(manifest_path.resolve()),
                    str(args.capability_file.resolve()),
                ):
                    self.assertNotIn(private_value, stderr.getvalue())

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

    def test_attachment_repair_compiler_requires_one_selected_parent(self) -> None:
        pdf = b"%PDF-1.7\nfixture\n"
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            pdf_path = root / "paper.pdf"
            pdf_path.write_bytes(pdf)
            entries = []
            for key in ("PARENT01", "PARENT02"):
                entries.append(
                    {
                        "action": "attach_missing_pdf",
                        "parent": {
                            "key": key,
                            "version": 7,
                            "item_type": "journalArticle",
                            "title": f"Fixture {key}",
                            "doi": "",
                        },
                        "expected_attachments": [],
                        "source_pdf": {
                            "path": str(pdf_path),
                            "size_bytes": len(pdf),
                            "sha256": "sha256:" + hashlib.sha256(pdf).hexdigest(),
                            "magic": "%PDF-",
                        },
                    }
                )
            repair = {
                "schema": "ZoteroAttachmentRepairManifest/v1",
                "generated_at": "2026-08-06T00:00:00Z",
                "target": {
                    "group_id": 123,
                    "library_id": 2,
                    "library_name": "Fixture",
                    "local_collection_id": 40,
                    "collection_key": "ABCDEFGH",
                    "collection_path": [{"key": "ABCDEFGH", "name": "Target"}],
                },
                "entries": entries,
            }
            repair["manifest_digest_sha256"] = "sha256:" + hashlib.sha256(
                json.dumps(
                    repair,
                    ensure_ascii=True,
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode()
            ).hexdigest()
            source = root / "repair.json"
            source.write_text(json.dumps(repair), encoding="utf-8")
            with self.assertRaisesRegex(bridge.BridgeError, "--parent-key"):
                bridge.compile_attachment_repair(source, "fixture-repair")
            selected = bridge.compile_attachment_repair(
                source,
                "fixture-repair-parent02",
                "PARENT02",
            )
            self.assertEqual([entry["parent"]["key"] for entry in selected["entries"]], ["PARENT02"])
            with self.assertRaisesRegex(bridge.BridgeError, "selector"):
                bridge.compile_attachment_repair(source, "fixture-repair-missing", "PARENT03")

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
                packed_manifest = json.loads(archive.read("manifest.json"))
                source = archive.read("bootstrap.js").decode() + archive.read("bridge_core.js").decode()
            updates = json.loads((PLUGIN_ROOT / "updates.json").read_text(encoding="utf-8"))
            update = updates["addons"][builder.PLUGIN_ID]["updates"][0]
        self.assertEqual(packed_manifest["applications"]["zotero"]["update_url"], builder.PLUGIN_UPDATE_URL)
        self.assertEqual(update["version"], packed_manifest["version"])
        self.assertEqual(update["update_hash"], f"sha256:{digest1}")
        self.assertNotIn("/latest/", update["update_link"])
        self.assertEqual(
            update["applications"]["zotero"],
            {
                "strict_min_version": packed_manifest["applications"]["zotero"][
                    "strict_min_version"
                ],
                "strict_max_version": packed_manifest["applications"]["zotero"][
                    "strict_max_version"
                ],
            },
        )
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
        self.assertIn("storage-equivalence and transaction checks passed", result.stdout)

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

    def test_short_title_compiler_binds_and_refuses_live_drift(self) -> None:
        args = types.SimpleNamespace(
            group_id=123,
            library_id=2,
            library_name="Fixture",
            local_collection_id=40,
            collection_key="ABCDEFGH",
            parent_key="PARENT01",
            expected_parent_version=7,
            expected_old_value="Old title",
            new_short_title="Reviewed title",
            base_url=bridge.BASE_URL,
            transaction_id="short-title-fixture",
        )
        record = {
            "version": 7,
            "data": {
                "key": "PARENT01",
                "version": 7,
                "itemType": "journalArticle",
                "title": "Fixture parent",
                "shortTitle": "Old title",
                "DOI": "10.1/fixture",
                "collections": ["ABCDEFGH"],
            },
        }
        with mock.patch.object(
            bridge,
            "collection_contract",
            return_value=([{"key": "ABCDEFGH", "name": "Target"}], {}),
        ), mock.patch.object(bridge, "live_parent", return_value=record):
            compiled = bridge.compile_short_title(args)
        operation = compiled["entries"][0]["operations"][0]
        self.assertEqual(operation["type"], "ensure_parent_short_title")
        self.assertEqual(operation["library_id"], 2)
        self.assertEqual(operation["parent_key"], "PARENT01")
        self.assertEqual(operation["expected_parent_version"], 7)
        self.assertEqual(operation["expected_old_value"], "Old title")
        self.assertEqual(operation["new_short_title"], "Reviewed title")
        bridge.validate_manifest(compiled)
        drifted = json.loads(json.dumps(record))
        drifted["data"]["shortTitle"] = "Concurrent edit"
        with mock.patch.object(
            bridge,
            "collection_contract",
            return_value=([{"key": "ABCDEFGH", "name": "Target"}], {}),
        ), mock.patch.object(bridge, "live_parent", return_value=drifted):
            with self.assertRaisesRegex(bridge.BridgeError, "old-value drift"):
                bridge.compile_short_title(args)

    def test_reviewed_batch_compiles_combined_atomic_operations(self) -> None:
        old_note_html = "<h1>Old</h1><p>Baseline</p>"
        batch = reviewed_batch_fixture(old_note_html)
        record = {
            "version": 7,
            "data": {
                "key": "PARENT01",
                "version": 7,
                "itemType": "journalArticle",
                "title": "A generic sensitivity study",
                "shortTitle": "Old",
                "DOI": "10.1/generic",
                "collections": ["COLL0001"],
            },
        }
        notes = [{"key": "NOTE0001", "version": 3, "html": old_note_html}]
        keyed_path = [
            {"key": "ROOT0001", "name": "Research"},
            {"key": "COLL0001", "name": "Methods"},
        ]
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "reviewed.json"
            source.write_text(json.dumps(batch), encoding="utf-8")
            with mock.patch.object(
                bridge,
                "collection_contract",
                return_value=(keyed_path, {"version": 9, "data": {"version": 9}}),
            ), mock.patch.object(
                bridge, "live_parent", return_value=record
            ), mock.patch.object(
                bridge, "live_child_notes", return_value=notes
            ):
                compiled = bridge.compile_reviewed_batch(
                    source,
                    transaction_id="reviewed-fixture",
                    local_collection_id=40,
                    source_hash_contract=bridge.REVIEWED_SOURCE_HASH_CONTRACT,
                    short_title_policy=bridge.DECISION_SHORT_TITLE_POLICY,
                    short_title_language="zh-CN",
                    base_url=bridge.BASE_URL,
                )
        self.assertEqual(compiled["target"]["collection_id"], 40)
        self.assertEqual(compiled["target"]["collection_path"], keyed_path)
        operations = compiled["entries"][0]["operations"]
        self.assertEqual(
            [operation["type"] for operation in operations],
            ["ensure_parent_short_title", "ensure_child_note"],
        )
        self.assertNotIn("new_short_title_sha256", operations[0])
        self.assertNotIn("entry_sha256", compiled["entries"][0])
        self.assertNotEqual(
            compiled["entries"][0]["parent"]["identity_sha256"],
            batch["entries"][0]["parent"]["identity_sha256"],
        )
        bridge.validate_manifest(compiled)

    def test_reviewed_batch_rejects_hash_and_live_old_content_drift(self) -> None:
        batch = reviewed_batch_fixture()
        batch["entries"][0]["operations"][0]["new_short_title"] += "x"
        batch["manifest_sha256"] = bridge.sha256_value(
            {key: value for key, value in batch.items() if key != "manifest_sha256"}
        )
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "bad-entry.json"
            source.write_text(json.dumps(batch), encoding="utf-8")
            with self.assertRaisesRegex(bridge.BridgeError, "entry_sha256"):
                bridge.compile_reviewed_batch(
                    source,
                    transaction_id="bad-entry",
                    local_collection_id=40,
                    source_hash_contract=bridge.REVIEWED_SOURCE_HASH_CONTRACT,
                    short_title_policy=None,
                    short_title_language=None,
                    base_url=bridge.BASE_URL,
                )

        batch = reviewed_batch_fixture()
        record = {
            "version": 7,
            "data": {
                "key": "PARENT01",
                "version": 7,
                "itemType": "journalArticle",
                "title": "A generic sensitivity study",
                "shortTitle": "Old",
                "DOI": "10.1/generic",
                "collections": ["COLL0001"],
            },
        }
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "old-drift.json"
            source.write_text(json.dumps(batch), encoding="utf-8")
            with mock.patch.object(
                bridge,
                "collection_contract",
                return_value=(
                    [
                        {"key": "ROOT0001", "name": "Research"},
                        {"key": "COLL0001", "name": "Methods"},
                    ],
                    {"version": 9},
                ),
            ), mock.patch.object(
                bridge, "live_parent", return_value=record
            ), mock.patch.object(
                bridge,
                "live_child_notes",
                return_value=[
                    {"key": "NOTE0001", "version": 3, "html": "concurrent edit"}
                ],
            ):
                with self.assertRaisesRegex(bridge.BridgeError, "old-content hash drift"):
                    bridge.compile_reviewed_batch(
                        source,
                        transaction_id="old-drift",
                        local_collection_id=40,
                        source_hash_contract=bridge.REVIEWED_SOURCE_HASH_CONTRACT,
                        short_title_policy=None,
                        short_title_language=None,
                        base_url=bridge.BASE_URL,
                    )

    def test_decision_short_title_policy_rejects_title_abbreviations(self) -> None:
        bridge.validate_research_short_title(
            "高维代理模型分析：应先筛选再校准总效应",
            "A generic sensitivity study",
            policy=bridge.DECISION_SHORT_TITLE_POLICY,
            language="zh",
        )
        with self.assertRaisesRegex(bridge.BridgeError, "abbreviation"):
            bridge.validate_research_short_title(
                "高维敏感性分析：可用方法综述",
                "高维敏感性分析：可用方法综述与应用",
                policy=bridge.DECISION_SHORT_TITLE_POLICY,
                language="zh-CN",
            )
        with self.assertRaisesRegex(bridge.BridgeError, "requested Chinese"):
            bridge.validate_research_short_title(
                "Surrogate analysis: prefer screening before calibration",
                "A generic sensitivity study",
                policy=bridge.DECISION_SHORT_TITLE_POLICY,
                language="zh",
            )

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
