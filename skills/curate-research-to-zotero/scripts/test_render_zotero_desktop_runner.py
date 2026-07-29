#!/usr/bin/env python3

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path

import render_zotero_desktop_runner as module
from test_verify_note_html import valid_note


NODE = shutil.which("node")
TEMPLATE_PATH = Path(__file__).with_name("zotero_desktop_note_migration.js")


def extract_js_function(start_marker: str, end_marker: str) -> str:
    source = TEMPLATE_PATH.read_text(encoding="utf-8")
    start = source.index(start_marker)
    end = source.index(end_marker, start)
    return source[start:end]


def run_node_json(script: str) -> dict[str, object]:
    assert NODE is not None
    completed = subprocess.run(
        [NODE, "-e", script],
        check=True,
        capture_output=True,
        text=True,
        timeout=5,
    )
    return json.loads(completed.stdout)


class RenderZoteroDesktopRunnerTests(unittest.TestCase):
    def manifest(self, directory: Path) -> Path:
        old_path = directory / "old.html"
        new_path = directory / "new.html"
        pdf_path = directory / "paper.pdf"
        old_path.write_text("<div>old</div>", encoding="utf-8")
        pdf_path.write_bytes(b"%PDF-1.4\nfixture\n%%EOF\n")
        pdf_sha256 = module.sha256_bytes(pdf_path.read_bytes())
        new_path.write_text(
            valid_note().replace("a" * 64, pdf_sha256),
            encoding="utf-8",
        )
        path = directory / "migration.json"
        path.write_text(
            json.dumps(
                {
                    "manifest_version": "2",
                    "write_performed": False,
                    "collection_item_inventory": ["HGFEDCBA"],
                    "target": {
                        "group_id": 1234567,
                        "library_id": 2,
                        "library_name": "PRIVATE_ZOTERO_TARGET",
                        "local_collection_id": 27,
                        "collection_key": "TEST0001",
                        "collection_name": "PRIVATE_ZOTERO_TARGET",
                        "collection_path": [
                            "PRIVATE_ZOTERO_TARGET",
                            "PRIVATE_ZOTERO_TARGET",
                            "PRIVATE_ZOTERO_TARGET",
                        ],
                    },
                    "entries": [
                        {
                            "status": "staged_verified",
                            "note_key": "ABCDEFGH",
                            "parent_key": "HGFEDCBA",
                            "expected_parent_key": "HGFEDCBA",
                            "child_note_inventory": ["ABCDEFGH"],
                            "child_attachment_inventory": ["PDFATT01"],
                            "note_version": 1,
                            "old_path": str(old_path),
                            "old_sha256": module.sha256_bytes(old_path.read_bytes()),
                            "new_path": str(new_path),
                            "new_sha256": module.sha256_bytes(new_path.read_bytes()),
                            "pdf_path": str(pdf_path),
                            "pdf_sha256": pdf_sha256,
                            "pdf_attachment_key": "PDFATT01",
                            "pdf_attachment_link_mode": "imported_file",
                            "validation_errors": [],
                            "validation_summary": {"schema_version": "9"},
                        }
                    ],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        return path

    def test_dry_run_embeds_manifest_hash_and_note_count(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            manifest = self.manifest(Path(temp_dir))
            manifest_sha256 = module.sha256_bytes(manifest.read_bytes())
            rendered = module.render_runner(
                manifest,
                apply=False,
            )

        self.assertNotIn(module.SENTINEL, rendered)
        self.assertIn('"apply": false', rendered)
        self.assertIn('"expectedNoteCount": 1', rendered)
        self.assertIn(manifest_sha256, rendered)
        self.assertIn("const migrationReport = await runMigration();", rendered)

    def test_apply_uses_internal_sync_barrier(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            manifest = self.manifest(Path(temp_dir))
            rendered = module.render_runner(
                manifest,
                apply=True,
                require_auto_sync_enabled=True,
            )

        self.assertIn('"apply": true', rendered)
        self.assertIn('"requireAutoSyncEnabled": true', rendered)
        self.assertIn("await acquireSyncBarrier();", rendered)
        self.assertIn("syncBarrier.release();", rendered)
        self.assertNotIn("clearSyncTimeout()", rendered)
        self.assertIn("{ onCommit }", rendered)
        self.assertIn('"transaction_outcome_unknown"', rendered)
        self.assertIn("resolveAndVerifyTarget(manifestTarget)", rendered)
        self.assertIn("verifyLiveManifestInventory(", rendered)
        self.assertIn("live child-note or attachment inventory changed", rendered)
        self.assertIn("parent left the approved collection", rendered)
        self.assertIn("leaseExpired", rendered)
        self.assertIn("automatic sync is no longer enabled", rendered)
        self.assertIn('"sync_barrier_lease_expired"', rendered)
        self.assertIn('"report_persistence_failed"', rendered)
        self.assertIn('closest("pre, textarea")', rendered)
        self.assertIn('{ mode: "create" }', rendered)
        self.assertIn("approved PDF attachment file path changed", rendered)
        self.assertIn("item.noteKey,\n      true,", rendered)

    def test_rejects_duplicate_note_keys(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            manifest = self.manifest(Path(temp_dir))
            payload = json.loads(manifest.read_text(encoding="utf-8"))
            duplicate = dict(payload["entries"][0])
            duplicate["parent_key"] = "PARENT12"
            duplicate["expected_parent_key"] = "PARENT12"
            payload["entries"].append(duplicate)
            payload["collection_item_inventory"] = ["HGFEDCBA", "PARENT12"]
            manifest.write_text(json.dumps(payload), encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "duplicate note keys"):
                module.load_and_validate_manifest(manifest)

    def test_rejects_inexact_target_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            manifest = self.manifest(Path(temp_dir))
            payload = json.loads(manifest.read_text(encoding="utf-8"))
            del payload["target"]["collection_path"]
            manifest.write_text(json.dumps(payload), encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "collection_path"):
                module.load_and_validate_manifest(manifest)

    def test_rejects_legacy_manifest_version(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            manifest = self.manifest(Path(temp_dir))
            payload = json.loads(manifest.read_text(encoding="utf-8"))
            payload["manifest_version"] = "1"
            manifest.write_text(json.dumps(payload), encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "manifest_version 2"):
                module.load_and_validate_manifest(manifest)

    def test_rejects_parent_key_alias_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            manifest = self.manifest(Path(temp_dir))
            payload = json.loads(manifest.read_text(encoding="utf-8"))
            payload["entries"][0]["expected_parent_key"] = "PARENT12"
            manifest.write_text(json.dumps(payload), encoding="utf-8")

            with self.assertRaisesRegex(
                ValueError,
                "parent_key does not equal expected_parent_key",
            ):
                module.load_and_validate_manifest(manifest)

    def test_rejects_staged_note_outside_child_inventory(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            manifest = self.manifest(Path(temp_dir))
            payload = json.loads(manifest.read_text(encoding="utf-8"))
            payload["entries"][0]["child_note_inventory"] = ["OTHER001"]
            manifest.write_text(json.dumps(payload), encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "child note inventory"):
                module.load_and_validate_manifest(manifest)

    def test_rejects_report_path_that_overwrites_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            manifest = self.manifest(Path(temp_dir))

            with self.assertRaisesRegex(ValueError, "would overwrite"):
                module.render_runner(
                    manifest,
                    apply=False,
                    report_path=manifest,
                )

    def test_rejects_report_path_that_overwrites_staged_input(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            manifest = self.manifest(Path(temp_dir))
            payload = json.loads(manifest.read_text(encoding="utf-8"))
            staged_path = Path(payload["entries"][0]["new_path"])

            with self.assertRaisesRegex(ValueError, "would overwrite"):
                module.render_runner(
                    manifest,
                    apply=True,
                    report_path=staged_path,
                )

    def test_rejects_existing_report_evidence_path(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            directory = Path(temp_dir)
            manifest = self.manifest(directory)
            report_path = directory / "existing-report.json"
            report_path.write_text('{"status":"completed"}', encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "already exists"):
                module.render_runner(
                    manifest,
                    apply=True,
                    report_path=report_path,
                )

    def test_reruns_schema_validator_instead_of_trusting_manifest_summary(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            manifest = self.manifest(Path(temp_dir))
            payload = json.loads(manifest.read_text(encoding="utf-8"))
            entry = payload["entries"][0]
            new_path = Path(entry["new_path"])
            new_path.write_text(
                '<div data-schema-version="9"><h1>truncated</h1></div>',
                encoding="utf-8",
            )
            entry["new_sha256"] = module.sha256_bytes(new_path.read_bytes())
            manifest.write_text(json.dumps(payload), encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "live schema-9 validator"):
                module.load_and_validate_manifest(manifest)

    def test_rejects_staged_note_that_only_adds_outer_whitespace(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            manifest = self.manifest(Path(temp_dir))
            payload = json.loads(manifest.read_text(encoding="utf-8"))
            entry = payload["entries"][0]
            new_path = Path(entry["new_path"])
            normalized_html = new_path.read_text(encoding="utf-8").strip()
            old_path = Path(entry["old_path"])
            old_path.write_text(normalized_html, encoding="utf-8")
            new_path.write_text(f"\n{normalized_html}\n", encoding="utf-8")
            entry["old_sha256"] = module.sha256_bytes(old_path.read_bytes())
            entry["new_sha256"] = module.sha256_bytes(new_path.read_bytes())
            manifest.write_text(json.dumps(payload), encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "normalizes to the existing note"):
                module.load_and_validate_manifest(manifest)

    def test_rejects_blocked_or_invalid_entries(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            manifest = self.manifest(Path(temp_dir))
            payload = json.loads(manifest.read_text(encoding="utf-8"))
            payload["entries"].append(
                {
                    "status": "blocked_multiple_notes",
                    "parent_key": "PARENT12",
                    "child_note_inventory": ["NOTE0001", "NOTE0002"],
                    "child_attachment_inventory": [],
                    "note_count": 2,
                }
            )
            payload["collection_item_inventory"] = ["HGFEDCBA", "PARENT12"]
            manifest.write_text(json.dumps(payload), encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "invalid or ambiguous"):
                module.load_and_validate_manifest(manifest)

    def test_rejects_changed_pdf_even_when_manifest_metadata_is_unchanged(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            manifest = self.manifest(Path(temp_dir))
            payload = json.loads(manifest.read_text(encoding="utf-8"))
            pdf_path = Path(payload["entries"][0]["pdf_path"])
            with pdf_path.open("ab") as stream:
                stream.write(b"changed")

            with self.assertRaisesRegex(ValueError, "pdf_path hash"):
                module.load_and_validate_manifest(manifest)

    def test_rejects_pdf_attachment_not_bound_to_child_inventory(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            manifest = self.manifest(Path(temp_dir))
            payload = json.loads(manifest.read_text(encoding="utf-8"))
            payload["entries"][0]["pdf_attachment_key"] = "OTHER001"
            manifest.write_text(json.dumps(payload), encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "approved live child attachment"):
                module.load_and_validate_manifest(manifest)

    @unittest.skipUnless(NODE, "Node.js is required for runner execution tests")
    def test_report_writer_uses_atomic_create_and_rejects_reuse(self) -> None:
        function_source = extract_js_function(
            "async function writeReport",
            "\nasync function collectionPath",
        )
        result = run_node_json(
            textwrap.dedent(
                f"""
                function assertion(condition, message, details) {{
                  if (!condition) {{
                    const error = new Error(message);
                    error.details = details;
                    throw error;
                  }}
                }}
                const CONFIG = {{ reportPath: "/tmp/evidence.json" }};
                let exists = false;
                let writeOptions = null;
                const IOUtils = {{
                  async exists() {{ return exists; }},
                  async writeUTF8(_path, _data, options) {{
                    if (exists || options.mode !== "create") {{
                      throw new Error("overwrite attempted");
                    }}
                    writeOptions = options;
                    exists = true;
                  }},
                }};
                {function_source}
                (async () => {{
                  await writeReport({{ status: "completed" }});
                  let secondWriteRejected = false;
                  try {{
                    await writeReport({{ status: "replacement" }});
                  }}
                  catch (_error) {{
                    secondWriteRejected = true;
                  }}
                  process.stdout.write(JSON.stringify({{
                    mode: writeOptions.mode,
                    secondWriteRejected,
                  }}));
                }})().catch(error => {{
                  console.error(error);
                  process.exit(1);
                }});
                """
            )
        )

        self.assertEqual(
            result,
            {"mode": "create", "secondWriteRejected": True},
        )

    @unittest.skipUnless(NODE, "Node.js is required for runner execution tests")
    def test_attachment_file_binding_executes_and_rejects_redirect(self) -> None:
        function_source = extract_js_function(
            "async function verifyAttachmentFileBinding",
            "\nfunction normalizedNoteHTML",
        )
        result = run_node_json(
            textwrap.dedent(
                f"""
                function assertion(condition, message, details) {{
                  if (!condition) {{
                    const error = new Error(message);
                    error.details = details;
                    throw error;
                  }}
                }}
                const PathUtils = {{ normalize: value => value }};
                {function_source}
                (async () => {{
                  let redirectedRejected = false;
                  await verifyAttachmentFileBinding(
                    {{ async getFilePathAsync() {{ return "/paper.pdf"; }} }},
                    "/paper.pdf",
                    "NOTE0001",
                  );
                  try {{
                    await verifyAttachmentFileBinding(
                      {{ async getFilePathAsync() {{ return "/other.pdf"; }} }},
                      "/paper.pdf",
                      "NOTE0001",
                    );
                  }}
                  catch (_error) {{
                    redirectedRejected = true;
                  }}
                  process.stdout.write(JSON.stringify({{ redirectedRejected }}));
                }})().catch(error => {{
                  console.error(error);
                  process.exit(1);
                }});
                """
            )
        )

        self.assertEqual(result, {"redirectedRejected": True})

    @unittest.skipUnless(NODE, "Node.js is required for runner execution tests")
    def test_live_inventory_guard_executes_and_detects_new_child_note(self) -> None:
        function_source = extract_js_function(
            "function exactArrayEqual",
            "\nasync function resolveAndVerifyTarget",
        )
        result = run_node_json(
            textwrap.dedent(
                f"""
                function assertion(condition, message, details) {{
                  if (!condition) {{
                    const error = new Error(message);
                    error.details = details;
                    throw error;
                  }}
                }}
                const sha256Text = value => value;
                const noteItems = {{
                  11: {{
                    key: "NOTE0001",
                    parentItemKey: "PARENT01",
                    deleted: false,
                    isNote: () => true,
                  }},
                  12: {{
                    key: "NOTE0002",
                    parentItemKey: "PARENT01",
                    deleted: false,
                    isNote: () => true,
                  }},
                  21: {{
                    key: "PDFATT01",
                    parentItemKey: "PARENT01",
                    deleted: false,
                    isAttachment: () => true,
                  }},
                }};
                let noteIDs = [11];
                const parent = {{
                  key: "PARENT01",
                  deleted: false,
                  isRegularItem: () => true,
                  getCollections: () => [27],
                  async reload() {{}},
                  async loadDataType() {{}},
                  async loadAllData() {{}},
                  getNotes: () => noteIDs,
                  getAttachments: () => [21],
                }};
                const collection = {{
                  id: 27,
                  async reload() {{}},
                  async loadDataType() {{}},
                  getChildItems: () => [parent],
                }};
                const Zotero = {{
                  Items: {{
                    getAsync: async ids => ids.map(id => noteItems[id]),
                    getByLibraryAndKeyAsync: async (_libraryID, key) =>
                      key === "PARENT01" ? parent : null,
                  }},
                }};
                {function_source}
                (async () => {{
                  const manifest = {{
                    collection_item_inventory: ["PARENT01"],
                    entries: [{{
                      status: "staged_verified",
                      parent_key: "PARENT01",
                      expected_parent_key: "PARENT01",
                      note_key: "NOTE0001",
                      child_note_inventory: ["NOTE0001"],
                      child_attachment_inventory: ["PDFATT01"],
                      pdf_attachment_key: "PDFATT01",
                    }}],
                  }};
                  const contract = validateManifestContract(manifest);
                  const target = {{
                    library: {{ libraryID: 2 }},
                    collection,
                  }};
                  const matching = await verifyLiveManifestInventory(
                    contract,
                    target,
                    true,
                  );
                  noteIDs = [11, 12];
                  let changedRejected = false;
                  try {{
                    await verifyLiveManifestInventory(contract, target, true);
                  }}
                  catch (error) {{
                    changedRejected = error.message.includes(
                      "child-note or attachment inventory changed"
                    );
                  }}
                  process.stdout.write(JSON.stringify({{
                    matchingCount: matching.collectionItemCount,
                    changedRejected,
                  }}));
                }})().catch(error => {{
                  console.error(error);
                  process.exit(1);
                }});
                """
            )
        )

        self.assertEqual(
            result,
            {
                "matchingCount": 1,
                "changedRejected": True,
            },
        )

    @unittest.skipUnless(NODE, "Node.js is required for runner execution tests")
    def test_sync_barrier_watchdog_executes_and_releases_once(self) -> None:
        function_source = extract_js_function(
            "async function acquireSyncBarrier",
            "\nasync function readBack",
        )
        result = run_node_json(
            textwrap.dedent(
                f"""
                function assertion(condition, message) {{
                  if (!condition) throw new Error(message);
                }}
                let releaseCount = 0;
                const Zotero = {{
                  Sync: {{
                    Runner: {{
                      syncInProgress: false,
                      delayIndefinite() {{
                        return () => {{ releaseCount += 1; }};
                      }},
                    }},
                  }},
                  Promise: {{ delay: ms => new Promise(resolve => setTimeout(resolve, ms)) }},
                }};
                {function_source}
                (async () => {{
                  const expired = await acquireSyncBarrier(10, 20);
                  await new Promise(resolve => setTimeout(resolve, 40));
                  expired.release();
                  const expiredResult = {{
                    leaseExpired: expired.state.leaseExpired,
                    released: expired.state.released,
                    releaseCount,
                  }};

                  const manual = await acquireSyncBarrier(10, 1000);
                  manual.release();
                  manual.release();
                  const manualResult = {{
                    leaseExpired: manual.state.leaseExpired,
                    released: manual.state.released,
                    releaseCount,
                  }};
                  process.stdout.write(JSON.stringify({{
                    expiredResult,
                    manualResult,
                  }}));
                }})().catch(error => {{
                  console.error(error);
                  process.exit(1);
                }});
                """
            )
        )

        self.assertEqual(
            result["expiredResult"],
            {
                "leaseExpired": True,
                "released": True,
                "releaseCount": 1,
            },
        )
        self.assertEqual(
            result["manualResult"],
            {
                "leaseExpired": False,
                "released": True,
                "releaseCount": 2,
            },
        )

    @unittest.skipUnless(NODE, "Node.js is required for runner execution tests")
    def test_committed_readback_requires_version_advancement(self) -> None:
        function_source = extract_js_function(
            "async function readBack",
            "\nasync function runMigration",
        )
        result = run_node_json(
            textwrap.dedent(
                f"""
                function assertion(condition, message) {{
                  if (!condition) throw new Error(message);
                }}
                const sha256Text = value => value;
                const semanticHTMLSHA256 = value => value;
                {function_source}
                function item(version) {{
                  return {{
                    noteKey: "NOTE0001",
                    parentKey: "PARENT01",
                    oldVersion: 1,
                    oldSHA256: "old",
                    sourceSHA256: "new",
                    expectedStoredSHA256: "new",
                    expectedStoredHTML: "new",
                    storageNormalization: "none",
                    note: {{
                      version,
                      itemType: "note",
                      deleted: false,
                      parentItemKey: "PARENT01",
                      isNote: () => true,
                      async reload() {{}},
                      getNote: () => "new",
                    }},
                    parent: {{
                      deleted: false,
                      async reload() {{}},
                      getCollections: () => [27],
                    }},
                  }};
                }}
                (async () => {{
                  const target = {{ collection: {{ id: 27 }} }};
                  const advanced = await readBack([item(2)], target);
                  let sameVersionRejected = false;
                  try {{
                    await readBack([item(1)], target);
                  }}
                  catch (_error) {{
                    sameVersionRejected = true;
                  }}
                  process.stdout.write(JSON.stringify({{
                    advancedVerified: advanced[0].verified,
                    sameVersionRejected,
                  }}));
                }})().catch(error => {{
                  console.error(error);
                  process.exit(1);
                }});
                """
            )
        )

        self.assertEqual(
            result,
            {
                "advancedVerified": True,
                "sameVersionRejected": True,
            },
        )

    @unittest.skipUnless(NODE, "Node.js is required for runner execution tests")
    def test_transaction_outcome_classifier_executes_all_states(self) -> None:
        function_source = extract_js_function(
            "async function inspectTransactionOutcome",
            "\nasync function acquireSyncBarrier",
        )
        result = run_node_json(
            textwrap.dedent(
                f"""
                const sha256Text = value => value;
                const semanticHTMLSHA256 = value => value;
                const plainError = error => ({{ message: String(error) }});
                {function_source}
                function item(content, version) {{
                  return {{
                    noteKey: "NOTE0001",
                    parentKey: "PARENT01",
                    oldVersion: 1,
                    oldSHA256: "old",
                    expectedStoredSHA256: "new",
                    expectedStoredHTML: "new",
                    note: {{
                      version,
                      parentItemKey: "PARENT01",
                      async reload() {{}},
                      getNote() {{ return content; }},
                    }},
                  }};
                }}
                (async () => {{
                  const committed = await inspectTransactionOutcome([item("new", 2)]);
                  const rolledBack = await inspectTransactionOutcome([item("old", 1)]);
                  const unknown = await inspectTransactionOutcome([item("other", 2)]);
                  const sameVersionNew = await inspectTransactionOutcome([item("new", 1)]);
                  process.stdout.write(JSON.stringify({{
                    committed: committed.outcome,
                    rolledBack: rolledBack.outcome,
                    unknown: unknown.outcome,
                    sameVersionNew: sameVersionNew.outcome,
                  }}));
                }})().catch(error => {{
                  console.error(error);
                  process.exit(1);
                }});
                """
            )
        )

        self.assertEqual(
            result,
            {
                "committed": "committed",
                "rolledBack": "rolled_back",
                "unknown": "unknown",
                "sameVersionNew": "unknown",
            },
        )


if __name__ == "__main__":
    unittest.main()
