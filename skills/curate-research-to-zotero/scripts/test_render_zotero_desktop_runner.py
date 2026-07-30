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
    end = source.find(end_marker, start)
    if end == -1:
        next_function_start = source.find("\nasync function ", start + len(start_marker))
        if next_function_start == -1:
            raise ValueError(
                f"Unable to locate end of JS function block {start_marker!r}"
            )
        end = next_function_start
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
        self.assertIn('"requireAutoSyncEnabled": false', rendered)
        self.assertIn('"expectedInventoryNoteCount": 1', rendered)
        self.assertIn('"expectedMutationCount": 1', rendered)
        self.assertIn('"expectedMutationKeys": ["ABCDEFGH"]', rendered)
        self.assertIn(manifest_sha256, rendered)
        self.assertIn("const migrationReport = await runMigration();", rendered)

    def test_render_runner_respects_require_auto_sync_flag(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            manifest = self.manifest(Path(temp_dir))

            rendered_disabled = module.render_runner(
                manifest,
                apply=False,
                require_auto_sync_enabled=False,
            )
            rendered_enabled = module.render_runner(
                manifest,
                apply=False,
                require_auto_sync_enabled=True,
            )

        self.assertIn('"requireAutoSyncEnabled": false', rendered_disabled)
        self.assertIn('"requireAutoSyncEnabled": true', rendered_enabled)

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

            with self.assertRaisesRegex(
                ValueError,
                "staged note normalizes to the existing note",
            ):
                module.load_and_validate_manifest(manifest)

    def test_accepts_unchanged_verified_without_noop_rejection(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            directory = Path(temp_dir)
            manifest = self.manifest(directory)
            payload = json.loads(manifest.read_text(encoding="utf-8"))
            entry = payload["entries"][0]
            pdf_sha = module.sha256_bytes(Path(payload["entries"][0]["pdf_path"]).read_bytes())
            old_note = valid_note().replace(
                "a" * 64,
                pdf_sha,
            )
            entry["status"] = "unchanged_verified"
            entry["old_path"] = str(directory / "old.html")
            entry["new_path"] = str(directory / "new.html")
            Path(entry["old_path"]).write_text(old_note, encoding="utf-8")
            Path(entry["new_path"]).write_text(old_note, encoding="utf-8")
            entry["old_sha256"] = module.sha256_bytes(
                Path(entry["old_path"]).read_bytes()
            )
            entry["new_sha256"] = module.sha256_bytes(
                Path(entry["new_path"]).read_bytes()
            )
            manifest.write_text(json.dumps(payload), encoding="utf-8")

            raw, data, inventory_count, mutation_count, mutation_keys = (
                module.load_and_validate_manifest(manifest)
            )

            self.assertEqual(raw, manifest.read_bytes())
            self.assertEqual(data["entries"][0]["status"], "unchanged_verified")
            self.assertEqual(inventory_count, 1)
            self.assertEqual(mutation_count, 0)
            self.assertEqual(mutation_keys, [])

    def test_rejects_unchanged_verified_with_hash_divergence(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            directory = Path(temp_dir)
            manifest = self.manifest(directory)
            payload = json.loads(manifest.read_text(encoding="utf-8"))
            entry = payload["entries"][0]
            entry["status"] = "unchanged_verified"
            entry["old_path"] = str(directory / "old.html")
            entry["new_path"] = str(directory / "new.html")
            old_note = valid_note().replace(
                "a" * 64,
                module.sha256_bytes(Path(entry["pdf_path"]).read_bytes()),
            )
            new_note = old_note.replace("</div>", "<span>changed</span></div>")
            Path(entry["old_path"]).write_text(old_note, encoding="utf-8")
            Path(entry["new_path"]).write_text(new_note, encoding="utf-8")
            entry["old_sha256"] = module.sha256_bytes(Path(entry["old_path"]).read_bytes())
            entry["new_sha256"] = module.sha256_bytes(Path(entry["new_path"]).read_bytes())
            manifest.write_text(json.dumps(payload), encoding="utf-8")

            with self.assertRaisesRegex(
                ValueError,
                "unchanged note hashes are inconsistent",
            ):
                module.load_and_validate_manifest(manifest)

    @unittest.skipUnless(NODE, "Node.js is required for runner execution tests")
    def test_run_migration_with_staged_and_unchanged_calls_transaction_for_staged_only(
        self,
    ) -> None:
        function_source = extract_js_function(
            "async function runMigration",
            "\nawait assertFreshReportPath",
        )
        manifest = json.dumps(
            {
                "manifest_version": "2",
                "write_performed": False,
                "target": {
                    "group_id": 1234567,
                    "library_id": 1234567,
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
                "collection_item_inventory": ["HGFEDCBA", "PARENT12"],
                "entries": [
                    {
                        "status": "staged_verified",
                        "note_key": "STAGE001",
                        "parent_key": "HGFEDCBA",
                        "expected_parent_key": "HGFEDCBA",
                        "child_note_inventory": ["STAGE001"],
                        "child_attachment_inventory": ["PDFATTA1"],
                        "note_version": 1,
                        "old_path": "/tmp/stage.old.html",
                        "new_path": "/tmp/stage.new.html",
                        "old_sha256": "a" * 64,
                        "new_sha256": "b" * 64,
                        "pdf_path": "/tmp/stage.pdf",
                        "pdf_sha256": "c" * 64,
                        "pdf_attachment_key": "PDFATTA1",
                        "pdf_attachment_link_mode": "linked_file",
                        "validation_summary": {"schema_version": "9"},
                        "validation_errors": [],
                    },
                    {
                        "status": "unchanged_verified",
                        "note_key": "NOOP0001",
                        "parent_key": "PARENT12",
                        "expected_parent_key": "PARENT12",
                        "child_note_inventory": ["NOOP0001"],
                        "child_attachment_inventory": ["PDFATTB1"],
                        "note_version": 1,
                        "old_path": "/tmp/unchanged.old.html",
                        "new_path": "/tmp/unchanged.new.html",
                        "old_sha256": "d" * 64,
                        "new_sha256": "d" * 64,
                        "pdf_path": "/tmp/unchanged.pdf",
                        "pdf_sha256": "f" * 64,
                        "pdf_attachment_key": "PDFATTB1",
                        "pdf_attachment_link_mode": "linked_file",
                        "validation_summary": {"schema_version": "9"},
                        "validation_errors": [],
                    },
                ],
            },
            ensure_ascii=False,
        )
        result = run_node_json(
            textwrap.dedent(
                f"""
                const manifestText = {manifest!r};
                function assertion(condition, message, details) {{
                  if (!condition) {{
                    const error = new Error(message);
                    error.details = details;
                    throw error;
                  }}
                }}
                function exactArrayEqual(left, right) {{
                  return Array.isArray(left)
                    && Array.isArray(right)
                    && left.length === right.length
                    && left.every((value, index) => value === right[index]);
                }}
                function validatedKeyInventory(value, label, options) {{
                  options = options || {{}};
                  assertion(Array.isArray(value), `${{label}} is not an array`);
                  assertion(
                    !options.nonempty || value.length > 0,
                    `${{label}} is empty`,
                  );
                  const keys = value.map(key => String(key || ""));
                  assertion(
                    keys.every(key => /^[A-Z0-9]{{8}}$/.test(key)),
                    `${{label}} contains an invalid item key`,
                  );
                  assertion(
                    exactArrayEqual(
                      keys,
                      [...keys].sort(),
                    ) && new Set(keys).size === keys.length,
                    `${{label}} must be sorted and duplicate-free`,
                  );
                  return keys;
                }}
                function validateManifestContract(manifest) {{
                  const collectionItemInventory = validatedKeyInventory(
                    manifest.collection_item_inventory,
                    "collection_item_inventory",
                    {{ nonempty: true }},
                  );
                  assertion(Array.isArray(manifest.entries), "manifest entries are missing");
                  assertion(
                    manifest.entries.every(
                      entry => entry && typeof entry === "object",
                    ),
                    "manifest contains a non-object entry",
                  );
                  const parentKeys = manifest.entries.map(entry =>
                    String(entry.parent_key || ""),
                  );
                  assertion(
                    parentKeys.length === collectionItemInventory.length
                      && new Set(parentKeys).size === collectionItemInventory.length,
                    "manifest entries do not exactly cover collection_item_inventory",
                  );
                  const allowedStatuses = new Set([
                    "staged_verified",
                    "unchanged_verified",
                    "staged_invalid",
                    "no_existing_note",
                    "blocked_multiple_notes",
                    "blocked_multiple_pdfs",
                  ]);
                  for (const entry of manifest.entries) {{
                    const parentKey = String(entry.parent_key || "");
                    assertion(
                      allowedStatuses.has(entry.status),
                      `${{parentKey}}: unsupported migration status`,
                    );
                    const childNoteInventory = validatedKeyInventory(
                      entry.child_note_inventory,
                      `${{parentKey}}: child_note_inventory`,
                    );
                    const childAttachmentInventory = validatedKeyInventory(
                      entry.child_attachment_inventory,
                      `${{parentKey}}: child_attachment_inventory`,
                    );
                    if (
                      entry.status === "staged_verified"
                      || entry.status === "unchanged_verified"
                    ) {{
                      const noteKey = String(entry.note_key || "");
                      assertion(
                        entry.expected_parent_key === parentKey,
                        `${{noteKey}}: parent_key and expected_parent_key differ`,
                      );
                      assertion(
                        exactArrayEqual(childNoteInventory, [noteKey]),
                        `${{noteKey}}: staged parent must have exactly the approved child note`,
                      );
                      assertion(
                        childAttachmentInventory.includes(entry.pdf_attachment_key),
                        `${{noteKey}}: approved PDF attachment is absent from child inventory`,
                      );
                    }}
                  }}
                  const blocking = manifest.entries.filter(entry =>
                    ["staged_invalid", "blocked_multiple_notes", "blocked_multiple_pdfs"]
                      .includes(entry.status)
                  );
                  assertion(
                    blocking.length === 0,
                    "manifest contains invalid or ambiguous entries",
                    blocking.map(entry => ({{
                      parentKey: entry.parent_key,
                      status: entry.status,
                    }})),
                  );
                  return {{
                    collectionItemInventory,
                    entries: manifest.entries,
                  }};
                }}
                function sha256Text() {{
                  return "MANIFEST_SHA256";
                }}
                const CONFIG = {{
                  apply: true,
                  reportPath: "/tmp/report.json",
                  manifestPath: "/tmp/manifest.json",
                  manifestSHA256: "MANIFEST_SHA256",
                  requireAutoSyncEnabled: false,
                  expectedInventoryNoteCount: 2,
                  expectedMutationCount: 1,
                  expectedMutationKeys: ["STAGE001"],
                }};
                const migrationText = manifestText;
                const Zotero = {{
                  File: {{
                    getContentsAsync: async () => migrationText,
                  }},
                  Prefs: {{
                    get: () => true,
                  }},
                }};
                let applyMutationKeys = null;
                let verifyLiveStateAgainInput = null;
                let acquireSyncBarrierCalled = false;
                let readBackCalled = false;
                function normalizedNoteHTML(value) {{
                  return value;
                }}
                async function resolveAndVerifyTarget() {{
                  return {{
                    collection: {{ id: 27 }},
                    library: {{ libraryID: 1234567 }},
                    publicTarget: {{
                      group_id: 1234567,
                      collection_key: "TEST0001",
                    }},
                  }};
                }}
                async function verifyLiveManifestInventory() {{
                  return {{ collectionItemCount: 2 }};
                }}
                async function verifyLiveStateAgain(verified) {{
                  verifyLiveStateAgainInput = verified.map(item => item.noteKey).sort();
                }}
                async function verifyEntry(entry) {{
                  return {{
                    status: entry.status,
                    noteKey: entry.note_key,
                    parentKey: entry.parent_key,
                    oldVersion: 1,
                    oldSHA256: "old",
                    sourceSHA256: "new",
                    expectedStoredSHA256: "new",
                    storageNormalization: "none",
                  }};
                }}
                async function acquireSyncBarrier() {{
                  acquireSyncBarrierCalled = true;
                  return {{
                    state: {{
                      leaseExpired: false,
                      released: false,
                      leaseMS: 120000,
                    }},
                    waitedMS: 1,
                    release() {{}},
                  }};
                }}
                async function applyTransaction(verified, mutationVerified) {{
                  verifyLiveStateAgainInput = verified.map(item => item.noteKey).sort();
                  applyMutationKeys = mutationVerified.map(item => item.noteKey);
                }}
                async function inspectTransactionOutcome() {{
                  return {{ outcome: "committed" }};
                }}
                async function readBack() {{
                  readBackCalled = true;
                  return [];
                }}
                {function_source}
                (async () => {{
                  const result = await runMigration();
                  process.stdout.write(
                    JSON.stringify({{
                      status: result.status,
                      mutationCount: result.mutationCount,
                      mutationKeys: result.mutationKeys,
                      applyMutationKeys,
                      verifyLiveStateAgainInput,
                      acquireSyncBarrierCalled,
                      readBackCalled,
                    }}),
                  );
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
                "status": "completed",
                "mutationCount": 1,
                "mutationKeys": ["STAGE001"],
                "applyMutationKeys": ["STAGE001"],
                "verifyLiveStateAgainInput": ["NOOP0001", "STAGE001"],
                "acquireSyncBarrierCalled": True,
                "readBackCalled": True,
            },
        )

    @unittest.skipUnless(NODE, "Node.js is required for runner execution tests")
    def test_run_migration_fails_when_verified_unchanged_entry_drifted(self) -> None:
        function_source = extract_js_function(
            "async function runMigration",
            "\nawait assertFreshReportPath",
        )
        manifest = json.dumps(
            {
                "manifest_version": "2",
                "write_performed": False,
                "target": {
                    "group_id": 1234567,
                    "library_id": 1234567,
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
                "collection_item_inventory": ["HGFEDCBA", "PARENT12"],
                "entries": [
                    {
                        "status": "staged_verified",
                        "note_key": "STAGE001",
                        "parent_key": "HGFEDCBA",
                        "expected_parent_key": "HGFEDCBA",
                        "child_note_inventory": ["STAGE001"],
                        "child_attachment_inventory": ["PDFATTA1"],
                        "note_version": 1,
                        "old_path": "/tmp/stage.old.html",
                        "new_path": "/tmp/stage.new.html",
                        "old_sha256": "a" * 64,
                        "new_sha256": "b" * 64,
                        "pdf_path": "/tmp/stage.pdf",
                        "pdf_sha256": "c" * 64,
                        "pdf_attachment_key": "PDFATTA1",
                        "pdf_attachment_link_mode": "linked_file",
                        "validation_summary": {"schema_version": "9"},
                        "validation_errors": [],
                    },
                    {
                        "status": "unchanged_verified",
                        "note_key": "NOOP0001",
                        "parent_key": "PARENT12",
                        "expected_parent_key": "PARENT12",
                        "child_note_inventory": ["NOOP0001"],
                        "child_attachment_inventory": ["PDFATTB1"],
                        "note_version": 1,
                        "old_path": "/tmp/unchanged.old.html",
                        "new_path": "/tmp/unchanged.new.html",
                        "old_sha256": "d" * 64,
                        "new_sha256": "d" * 64,
                        "pdf_path": "/tmp/unchanged.pdf",
                        "pdf_sha256": "f" * 64,
                        "pdf_attachment_key": "PDFATTB1",
                        "pdf_attachment_link_mode": "linked_file",
                        "validation_summary": {"schema_version": "9"},
                        "validation_errors": [],
                    },
                ],
            },
            ensure_ascii=False,
        )
        result = run_node_json(
            textwrap.dedent(
                f"""
                const manifestText = {manifest!r};
                function assertion(condition, message, details) {{
                  if (!condition) {{
                    const error = new Error(message);
                    error.details = details;
                    throw error;
                  }}
                }}
                function exactArrayEqual(left, right) {{
                  return Array.isArray(left)
                    && Array.isArray(right)
                    && left.length === right.length
                    && left.every((value, index) => value === right[index]);
                }}
                function validatedKeyInventory(value, label, options) {{
                  options = options || {{}};
                  assertion(Array.isArray(value), `${{label}} is not an array`);
                  assertion(
                    !options.nonempty || value.length > 0,
                    `${{label}} is empty`,
                  );
                  const keys = value.map(key => String(key || ""));
                  assertion(
                    keys.every(key => /^[A-Z0-9]{{8}}$/.test(key)),
                    `${{label}} contains an invalid item key`,
                  );
                  assertion(
                    exactArrayEqual(
                      keys,
                      [...keys].sort(),
                    ) && new Set(keys).size === keys.length,
                    `${{label}} must be sorted and duplicate-free`,
                  );
                  return keys;
                }}
                function validateManifestContract(manifest) {{
                  const collectionItemInventory = validatedKeyInventory(
                    manifest.collection_item_inventory,
                    "collection_item_inventory",
                    {{ nonempty: true }},
                  );
                  assertion(Array.isArray(manifest.entries), "manifest entries are missing");
                  assertion(
                    manifest.entries.every(
                      entry => entry && typeof entry === "object",
                    ),
                    "manifest contains a non-object entry",
                  );
                  const parentKeys = manifest.entries.map(entry =>
                    String(entry.parent_key || ""),
                  );
                  assertion(
                    parentKeys.length === collectionItemInventory.length
                      && new Set(parentKeys).size === collectionItemInventory.length,
                    "manifest entries do not exactly cover collection_item_inventory",
                  );
                  const allowedStatuses = new Set([
                    "staged_verified",
                    "unchanged_verified",
                    "staged_invalid",
                    "no_existing_note",
                    "blocked_multiple_notes",
                    "blocked_multiple_pdfs",
                  ]);
                  for (const entry of manifest.entries) {{
                    const parentKey = String(entry.parent_key || "");
                    assertion(
                      allowedStatuses.has(entry.status),
                      `${{parentKey}}: unsupported migration status`,
                    );
                    const childNoteInventory = validatedKeyInventory(
                      entry.child_note_inventory,
                      `${{parentKey}}: child_note_inventory`,
                    );
                    const childAttachmentInventory = validatedKeyInventory(
                      entry.child_attachment_inventory,
                      `${{parentKey}}: child_attachment_inventory`,
                    );
                    if (
                      entry.status === "staged_verified"
                      || entry.status === "unchanged_verified"
                    ) {{
                      const noteKey = String(entry.note_key || "");
                      assertion(
                        entry.expected_parent_key === parentKey,
                        `${{noteKey}}: parent_key and expected_parent_key differ`,
                      );
                      assertion(
                        exactArrayEqual(childNoteInventory, [noteKey]),
                        `${{noteKey}}: staged parent must have exactly the approved child note`,
                      );
                      assertion(
                        childAttachmentInventory.includes(entry.pdf_attachment_key),
                        `${{noteKey}}: approved PDF attachment is absent from child inventory`,
                      );
                    }}
                  }}
                  const blocking = manifest.entries.filter(entry =>
                    ["staged_invalid", "blocked_multiple_notes", "blocked_multiple_pdfs"]
                      .includes(entry.status)
                  );
                  assertion(
                    blocking.length === 0,
                    "manifest contains invalid or ambiguous entries",
                    blocking.map(entry => ({{
                      parentKey: entry.parent_key,
                      status: entry.status,
                    }})),
                  );
                  return {{
                    collectionItemInventory,
                    entries: manifest.entries,
                  }};
                }}
                function sha256Text() {{
                  return "MANIFEST_SHA256";
                }}
                const CONFIG = {{
                  apply: true,
                  reportPath: "/tmp/report.json",
                  manifestPath: "/tmp/manifest.json",
                  manifestSHA256: "MANIFEST_SHA256",
                  requireAutoSyncEnabled: false,
                  expectedInventoryNoteCount: 2,
                  expectedMutationCount: 1,
                  expectedMutationKeys: ["STAGE001"],
                }};
                const migrationText = manifestText;
                const Zotero = {{
                  File: {{
                    getContentsAsync: async () => migrationText,
                  }},
                  Prefs: {{
                    get: () => true,
                  }},
                }};
                let applyTransactionCalled = false;
                let verifyLiveStateAgainInput = null;
                let acquireSyncBarrierCalled = false;
                let readBackCalled = false;
                function plainError(error) {{
                  return {{ message: error.message }};
                }}
                async function resolveAndVerifyTarget() {{
                  return {{
                    collection: {{ id: 27 }},
                    library: {{ libraryID: 1234567 }},
                    publicTarget: {{
                      group_id: 1234567,
                      collection_key: "TEST0001",
                    }},
                  }};
                }}
                async function verifyLiveManifestInventory() {{
                  return {{ collectionItemCount: 2 }};
                }}
                async function verifyLiveStateAgain(verified) {{
                  verifyLiveStateAgainInput = verified.map(item => item.noteKey).sort();
                  for (const item of verified) {{
                    if (item.status === "unchanged_verified") {{
                      throw new Error(`${{item.noteKey}}: unchanged drifted after preflight`);
                    }}
                  }}
                }}
                async function verifyEntry(entry) {{
                  return {{
                    status: entry.status,
                    noteKey: entry.note_key,
                    parentKey: entry.parent_key,
                    oldVersion: 1,
                    oldSHA256: "old",
                    sourceSHA256: "new",
                    expectedStoredSHA256: "new",
                    storageNormalization: "none",
                  }};
                }}
                async function acquireSyncBarrier() {{
                  acquireSyncBarrierCalled = true;
                  return {{
                    state: {{
                      leaseExpired: false,
                      released: false,
                      leaseMS: 120000,
                    }},
                    waitedMS: 1,
                    release() {{}},
                  }};
                }}
                async function applyTransaction(verified, _mutationVerified) {{
                  verifyLiveStateAgainInput = verified.map(item => item.noteKey).sort();
                  for (const item of verified) {{
                    if (item.status === "unchanged_verified") {{
                      throw new Error(`${{item.noteKey}}: unchanged drifted after preflight`);
                    }}
                  }}
                  applyTransactionCalled = true;
                }}
                async function inspectTransactionOutcome() {{
                  return {{ outcome: "rolled_back" }};
                }}
                async function readBack() {{
                  readBackCalled = true;
                  return [];
                }}
                {function_source}
                (async () => {{
                  const result = await runMigration();
                  process.stdout.write(
                    JSON.stringify({{
                      status: result.status,
                      phase: result.phase || null,
                      noteCount: result.noteCount,
                      mutationCount: result.mutationCount,
                      mutationKeys: result.mutationKeys,
                      verifyLiveStateAgainInput,
                      applyTransactionCalled,
                      acquireSyncBarrierCalled,
                      readBackCalled,
                      errorMessage: result.error && result.error.message,
                    }}),
                  );
                }})().catch(error => {{
                  console.error(error);
                  process.exit(1);
                }});
                """
            )
        )

        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["phase"], "transaction")
        self.assertEqual(result["noteCount"], 2)
        self.assertEqual(result["verifyLiveStateAgainInput"], ["NOOP0001", "STAGE001"])
        self.assertIn("unchanged drifted after preflight", result["errorMessage"])
        self.assertFalse(result["applyTransactionCalled"])
        self.assertFalse(result["readBackCalled"])

    @unittest.skipUnless(NODE, "Node.js is required for runner execution tests")
    def test_run_migration_dry_run_succeeds_when_auto_sync_enabled(self) -> None:
        result = self._run_auto_sync_preference_scenario(
            status="staged_verified",
            apply=False,
            require_auto_sync_enabled=True,
            sync_values=[True, True],
            expected_mutation_count=1,
            expected_mutation_keys=["STAGE001"],
        )

        self.assertEqual(result["status"], "preflight_ok")
        self.assertEqual(result["mode"], "dry_run")
        self.assertFalse(result["writePerformed"])
        self.assertTrue(result["autoSyncObserved"])
        self.assertTrue(result["autoSyncAfter"])
        self.assertGreaterEqual(result["syncReads"], 2)
        self.assertFalse(result["preferenceChanged"])
        self.assertFalse(result["syncWritePerformed"])
        self.assertEqual(result["mutationCount"], 1)
        self.assertTrue(result["verifyLiveManifestInventoryCalled"])
        self.assertTrue(result["resolveAndVerifyTargetCalled"])
        self.assertFalse(result["verifyLiveStateAgainCalled"])
        self.assertFalse(result["acquireSyncBarrierCalled"])
        self.assertFalse(result["applyTransactionCalled"])

    @unittest.skipUnless(NODE, "Node.js is required for runner execution tests")
    def test_run_migration_dry_run_fails_when_auto_sync_disabled(self) -> None:
        result = self._run_auto_sync_preference_scenario(
            status="staged_verified",
            apply=False,
            require_auto_sync_enabled=True,
            sync_values=[False],
            expected_mutation_count=1,
            expected_mutation_keys=["STAGE001"],
        )

        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["mode"], "dry_run")
        self.assertEqual(result["phase"], "load_manifest")
        self.assertFalse(result["writePerformed"])
        self.assertFalse(result["autoSyncObserved"])
        self.assertFalse(result["preferenceChanged"])
        self.assertFalse(result["syncWritePerformed"])
        self.assertFalse(result["resolveAndVerifyTargetCalled"])
        self.assertFalse(result["verifyLiveManifestInventoryCalled"])
        self.assertFalse(result["verifyLiveStateAgainCalled"])
        self.assertFalse(result["applyTransactionCalled"])
        self.assertFalse(result["acquireSyncBarrierCalled"])
        self.assertIn("automatic sync is not enabled", result["errorMessage"])

    @unittest.skipUnless(NODE, "Node.js is required for runner execution tests")
    def test_run_migration_no_changes_when_no_staged_mutations(self) -> None:
        result = self._run_auto_sync_preference_scenario(
            status="unchanged_verified",
            apply=True,
            require_auto_sync_enabled=True,
            sync_values=[True, True],
            expected_mutation_count=0,
            expected_mutation_keys=[],
        )

        self.assertEqual(result["status"], "no_changes")
        self.assertEqual(result["mode"], "apply")
        self.assertFalse(result["writePerformed"])
        self.assertTrue(result["autoSyncObserved"])
        self.assertTrue(result["autoSyncAfter"])
        self.assertFalse(result["preferenceChanged"])
        self.assertTrue(result["preferencePreserved"])
        self.assertFalse(result["syncWritePerformed"])
        self.assertEqual(result["mutationCount"], 0)
        self.assertEqual(result["mutationKeys"], [])
        self.assertEqual(result["syncReads"], 2)
        self.assertFalse(result["applyTransactionCalled"])
        self.assertFalse(result["acquireSyncBarrierCalled"])
        self.assertFalse(result["readBackCalled"])

    @unittest.skipUnless(NODE, "Node.js is required for runner execution tests")
    def test_run_migration_no_changes_fails_when_auto_sync_turns_off(self) -> None:
        result = self._run_auto_sync_preference_scenario(
            status="unchanged_verified",
            apply=True,
            require_auto_sync_enabled=True,
            sync_values=[True, False],
            expected_mutation_count=0,
            expected_mutation_keys=[],
        )

        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["mode"], "apply")
        self.assertEqual(result["phase"], "preflight_entries")
        self.assertFalse(result["writePerformed"])
        self.assertTrue(result["autoSyncObserved"])
        self.assertFalse(result["autoSyncAfter"])
        self.assertTrue(result["preferenceChanged"])
        self.assertFalse(result["preferencePreserved"])
        self.assertFalse(result["syncWritePerformed"])
        self.assertEqual(result["syncReads"], 2)
        self.assertIn("no longer enabled", result["errorMessage"])
        self.assertFalse(result["applyTransactionCalled"])
        self.assertFalse(result["acquireSyncBarrierCalled"])
        self.assertFalse(result["readBackCalled"])

    @unittest.skipUnless(NODE, "Node.js is required for runner execution tests")
    def test_run_migration_dry_run_fails_when_auto_sync_turns_off(self) -> None:
        result = self._run_auto_sync_preference_scenario(
            status="staged_verified",
            apply=False,
            require_auto_sync_enabled=True,
            sync_values=[True, False],
            expected_mutation_count=1,
            expected_mutation_keys=["STAGE001"],
        )

        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["mode"], "dry_run")
        self.assertEqual(result["phase"], "preflight_entries")
        self.assertFalse(result["writePerformed"])
        self.assertTrue(result["autoSyncObserved"])
        self.assertFalse(result["autoSyncAfter"])
        self.assertTrue(result["preferenceChanged"])
        self.assertFalse(result["preferencePreserved"])
        self.assertFalse(result["syncWritePerformed"])
        self.assertEqual(result["syncReads"], 2)
        self.assertIn("disabled during dry-run", result["errorMessage"])
        self.assertTrue(result["resolveAndVerifyTargetCalled"])
        self.assertTrue(result["verifyLiveManifestInventoryCalled"])
        self.assertFalse(result["verifyLiveStateAgainCalled"])
        self.assertFalse(result["acquireSyncBarrierCalled"])

    @unittest.skipUnless(NODE, "Node.js is required for runner execution tests")
    def test_run_migration_dry_run_succeeds_when_auto_sync_flag_disabled(self) -> None:
        result = self._run_auto_sync_preference_scenario(
            status="staged_verified",
            apply=False,
            require_auto_sync_enabled=False,
            sync_values=[False, False],
            expected_mutation_count=1,
            expected_mutation_keys=["STAGE001"],
        )

        self.assertEqual(result["status"], "preflight_ok")
        self.assertEqual(result["mode"], "dry_run")
        self.assertFalse(result["writePerformed"])
        self.assertFalse(result["autoSyncObserved"])
        self.assertFalse(result["autoSyncAfter"])
        self.assertFalse(result["preferenceChanged"])
        self.assertTrue(result["preferencePreserved"])
        self.assertFalse(result["syncWritePerformed"])
        self.assertEqual(result["mutationCount"], 1)
        self.assertEqual(result["syncReads"], 2)
        self.assertTrue(result["resolveAndVerifyTargetCalled"])
        self.assertTrue(result["verifyLiveManifestInventoryCalled"])
        self.assertFalse(result["verifyLiveStateAgainCalled"])
        self.assertFalse(result["acquireSyncBarrierCalled"])

    def _build_auto_sync_manifest(
        self,
        *,
        status,
        collection_path_tail="PRIVATE_ZOTERO_TARGET",
    ):
        if status == "unchanged_verified":
            note_key = "NOOP0001"
            old_sha = "d" * 64
            new_sha = "d" * 64
            old_path = "/tmp/unchanged.old.html"
            new_path = "/tmp/unchanged.new.html"
            pdf_path = "/tmp/unchanged.pdf"
            pdf_sha256 = "f" * 64
            child_note_inventory = ["NOOP0001"]
            child_attachment_inventory = ["PDFATTB1"]
            pdf_attachment_key = "PDFATTB1"
        else:
            note_key = "STAGE001"
            old_sha = "a" * 64
            new_sha = "b" * 64
            old_path = "/tmp/stage.old.html"
            new_path = "/tmp/stage.new.html"
            pdf_path = "/tmp/stage.pdf"
            pdf_sha256 = "c" * 64
            child_note_inventory = ["STAGE001"]
            child_attachment_inventory = ["PDFATTA1"]
            pdf_attachment_key = "PDFATTA1"

        return {
            "manifest_version": "2",
            "write_performed": False,
            "target": {
                "group_id": 1234567,
                "library_id": 1234567,
                "library_name": "PRIVATE_ZOTERO_TARGET",
                "local_collection_id": 27,
                "collection_key": "TEST0001",
                "collection_name": "PRIVATE_ZOTERO_TARGET",
                "collection_path": [
                    "PRIVATE_ZOTERO_TARGET",
                    "PRIVATE_ZOTERO_TARGET",
                    collection_path_tail,
                ],
            },
            "collection_item_inventory": ["HGFEDCBA"],
            "entries": [
                {
                    "status": status,
                    "note_key": note_key,
                    "parent_key": "HGFEDCBA",
                    "expected_parent_key": "HGFEDCBA",
                    "child_note_inventory": child_note_inventory,
                    "child_attachment_inventory": child_attachment_inventory,
                    "note_version": 1,
                    "old_path": old_path,
                    "new_path": new_path,
                    "old_sha256": old_sha,
                    "new_sha256": new_sha,
                    "pdf_path": pdf_path,
                    "pdf_sha256": pdf_sha256,
                    "pdf_attachment_key": pdf_attachment_key,
                    "pdf_attachment_link_mode": "linked_file",
                    "validation_summary": {"schema_version": "9"},
                    "validation_errors": [],
                },
            ],
        }

    def _run_auto_sync_preference_scenario(
        self,
        *,
        status,
        apply,
        require_auto_sync_enabled,
        sync_values,
        expected_mutation_count,
        expected_mutation_keys,
        collection_path_tail="PRIVATE_ZOTERO_TARGET",
    ):
        manifest = self._build_auto_sync_manifest(
            status=status,
            collection_path_tail=collection_path_tail,
        )
        manifest_text = json.dumps(manifest, ensure_ascii=False)
        function_source = extract_js_function(
            "async function runMigration",
            "\nawait assertFreshReportPath",
        )
        sync_values_text = json.dumps(sync_values)

        script = textwrap.dedent(
            """
                const manifestText = PLACEHOLDER_MANIFEST_TEXT;
                function assertion(condition, message, details) {
                  if (!condition) {
                    const error = new Error(message);
                    error.details = details;
                    throw error;
                  }
                }
                function exactArrayEqual(left, right) {
                  return Array.isArray(left)
                    && Array.isArray(right)
                    && left.length === right.length
                    && left.every((value, index) => value === right[index]);
                }
                function validatedKeyInventory(value, label, options) {
                  options = options || {};
                  assertion(Array.isArray(value), `${label} is not an array`);
                  assertion(
                    !options.nonempty || value.length > 0,
                    `${label} is empty`,
                  );
                  const keys = value.map(key => String(key || ""));
                  assertion(
                    keys.every(key => /^[A-Z0-9]{8}$/.test(key)),
                    `${label} contains an invalid item key`,
                  );
                  assertion(
                    exactArrayEqual(keys, [...keys].sort())
                      && new Set(keys).size === keys.length,
                    `${label} must be sorted and duplicate-free`,
                  );
                  return keys;
                }
                function validateManifestContract(manifest) {
                  const collectionItemInventory = validatedKeyInventory(
                    manifest.collection_item_inventory,
                    "collection_item_inventory",
                    { nonempty: true },
                  );
                  assertion(Array.isArray(manifest.entries), "manifest entries are missing");
                  assertion(
                    manifest.entries.every(
                      entry => entry && typeof entry === "object",
                    ),
                    "manifest contains a non-object entry",
                  );
                  const parentKeys = manifest.entries.map(entry =>
                    String(entry.parent_key || ""),
                  );
                  assertion(
                    parentKeys.length === collectionItemInventory.length
                      && new Set(parentKeys).size === collectionItemInventory.length,
                    "manifest entries do not exactly cover collection_item_inventory",
                  );
                  const allowedStatuses = new Set([
                    "staged_verified",
                    "unchanged_verified",
                    "staged_invalid",
                    "no_existing_note",
                    "blocked_multiple_notes",
                    "blocked_multiple_pdfs",
                  ]);
                  for (const entry of manifest.entries) {
                    const parentKey = String(entry.parent_key || "");
                    assertion(
                      allowedStatuses.has(entry.status),
                      `${parentKey}: unsupported migration status`,
                    );
                    const childNoteInventory = validatedKeyInventory(
                      entry.child_note_inventory,
                      `${parentKey}: child_note_inventory`,
                    );
                    const childAttachmentInventory = validatedKeyInventory(
                      entry.child_attachment_inventory,
                      `${parentKey}: child_attachment_inventory`,
                    );
                    if (
                      entry.status === "staged_verified"
                      || entry.status === "unchanged_verified"
                    ) {
                      const noteKey = String(entry.note_key || "");
                      assertion(
                        entry.expected_parent_key === parentKey,
                        `${noteKey}: parent_key and expected_parent_key differ`,
                      );
                      assertion(
                        exactArrayEqual(childNoteInventory, [noteKey]),
                        `${noteKey}: staged parent must have exactly the approved child note`,
                      );
                      assertion(
                        childAttachmentInventory.includes(entry.pdf_attachment_key),
                        `${noteKey}: approved PDF attachment is absent from child inventory`,
                      );
                    }
                  }
                  const blocking = manifest.entries.filter(entry =>
                    ["staged_invalid", "blocked_multiple_notes", "blocked_multiple_pdfs"]
                      .includes(entry.status)
                  );
                  assertion(
                    blocking.length === 0,
                    "manifest contains invalid or ambiguous entries",
                    blocking.map(entry => ({
                      parentKey: entry.parent_key,
                      status: entry.status,
                    })),
                  );
                  return {
                    collectionItemInventory,
                    entries: manifest.entries,
                  };
                }
                function sha256Text() {
                  return "MANIFEST_SHA256";
                }
                function plainError(error) {
                  return {
                    name: error && error.name ? error.name : "Error",
                    message: error && error.message ? error.message : String(error),
                    details: error && error.details,
                  };
                }
                const CONFIG = {
                  apply: PLACEHOLDER_APPLY,
                  reportPath: "/tmp/report.json",
                  manifestPath: "/tmp/manifest.json",
                  manifestSHA256: "MANIFEST_SHA256",
                  requireAutoSyncEnabled: PLACEHOLDER_REQUIRE_AUTO_SYNC,
                  expectedInventoryNoteCount: 1,
                  expectedMutationCount: PLACEHOLDER_EXPECTED_MUTATION_COUNT,
                  expectedMutationKeys: PLACEHOLDER_EXPECTED_MUTATION_KEYS,
                };
                const migrationText = manifestText;
                let syncReads = 0;
                const syncValues = PLACEHOLDER_SYNC_VALUES;
                const syncFallback = syncValues.length ? syncValues[syncValues.length - 1] : null;
                const Zotero = {
                  File: {
                    getContentsAsync: async () => migrationText,
                  },
                  Prefs: {
                    get: (key) => {
                      if (key !== "sync.autoSync") {
                        return null;
                      }
                      syncReads += 1;
                      const nextValue = syncValues.shift();
                      return nextValue === undefined ? syncFallback : nextValue;
                    },
                  },
                };
                let resolveAndVerifyTargetCalled = false;
                let verifyLiveManifestInventoryCalled = false;
                let verifyLiveStateAgainCalled = false;
                let applyTransactionCalled = false;
                let acquireSyncBarrierCalled = false;
                let readBackCalled = false;
                function normalizedNoteHTML(value) {
                  return value;
                }
                async function resolveAndVerifyTarget() {
                  resolveAndVerifyTargetCalled = true;
                  return {
                    collection: { id: 27 },
                    library: { libraryID: 1234567 },
                    publicTarget: {
                      group_id: 1234567,
                      collection_key: "TEST0001",
                    },
                  };
                }
                async function verifyLiveManifestInventory() {
                  verifyLiveManifestInventoryCalled = true;
                  return { collectionItemCount: 1 };
                }
                async function verifyLiveStateAgain(verified) {
                  verifyLiveStateAgainCalled = true;
                }
                async function verifyEntry(entry) {
                  return {
                    status: entry.status,
                    noteKey: entry.note_key,
                    parentKey: entry.parent_key,
                    oldVersion: 1,
                    oldSHA256: "old",
                    sourceSHA256: "new",
                    expectedStoredSHA256: "new",
                    storageNormalization: "none",
                  };
                }
                async function acquireSyncBarrier() {
                  acquireSyncBarrierCalled = true;
                  return {
                    state: {
                      leaseExpired: false,
                      released: false,
                      leaseMS: 120000,
                    },
                    waitedMS: 1,
                    release() {},
                  };
                }
                async function applyTransaction() {
                  applyTransactionCalled = true;
                }
                async function inspectTransactionOutcome() {
                  return { outcome: "committed" };
                }
                async function readBack() {
                  readBackCalled = true;
                  return [];
                }
                PLACEHOLDER_FUNCTION_SOURCE
                (async () => {
                  const result = await runMigration();
                  process.stdout.write(
                    JSON.stringify({
                      status: result.status,
                      phase: result.phase || null,
                      mode: result.mode,
                      writePerformed: result.writePerformed,
                      mutationCount: result.mutationCount,
                      mutationKeys: result.mutationKeys,
                      autoSyncObserved: result.syncState && result.syncState.autoSyncObserved,
                      autoSyncAfter: result.syncState && result.syncState.autoSyncAfter,
                      preferenceChanged: result.syncState && result.syncState.preferenceChanged,
                      preferencePreserved: result.syncState && result.syncState.preferencePreserved,
                      syncWritePerformed: result.syncState && result.syncState.writePerformed,
                      errorMessage: result.error && result.error.message,
                      resolveAndVerifyTargetCalled,
                      verifyLiveManifestInventoryCalled,
                      verifyLiveStateAgainCalled,
                      applyTransactionCalled,
                      acquireSyncBarrierCalled,
                      readBackCalled,
                      syncReads,
                    }),
                  );
                })().catch(error => {
                  console.error(error);
                  process.exit(1);
                });
            """
            .replace("PLACEHOLDER_MANIFEST_TEXT", repr(manifest_text))
            .replace("PLACEHOLDER_FUNCTION_SOURCE", function_source)
            .replace("PLACEHOLDER_APPLY", json.dumps(apply))
            .replace("PLACEHOLDER_REQUIRE_AUTO_SYNC", json.dumps(require_auto_sync_enabled))
            .replace("PLACEHOLDER_EXPECTED_MUTATION_COUNT", str(expected_mutation_count))
            .replace(
                "PLACEHOLDER_EXPECTED_MUTATION_KEYS",
                json.dumps(expected_mutation_keys),
            )
            .replace("PLACEHOLDER_SYNC_VALUES", sync_values_text)
        )
        return run_node_json(script)

    @unittest.skipUnless(NODE, "Node.js is required for runner execution tests")
    def test_run_migration_rejects_unsupported_entry_status(self) -> None:
        function_source = extract_js_function(
            "async function runMigration",
            "\nawait assertFreshReportPath",
        )
        manifest = json.dumps(
            {
                "manifest_version": "2",
                "write_performed": False,
                "target": {
                    "group_id": 1234567,
                    "library_id": 1234567,
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
                "collection_item_inventory": ["HGFEDCBA"],
                "entries": [
                    {
                        "status": "weird_status",
                        "note_key": "STAGE001",
                        "parent_key": "HGFEDCBA",
                        "expected_parent_key": "HGFEDCBA",
                        "child_note_inventory": ["STAGE001"],
                        "child_attachment_inventory": ["PDFATTA1"],
                        "note_version": 1,
                        "old_path": "/tmp/stage.old.html",
                        "new_path": "/tmp/stage.new.html",
                        "old_sha256": "a" * 64,
                        "new_sha256": "b" * 64,
                        "pdf_path": "/tmp/stage.pdf",
                        "pdf_sha256": "c" * 64,
                        "pdf_attachment_key": "PDFATTA1",
                        "pdf_attachment_link_mode": "linked_file",
                        "validation_summary": {"schema_version": "9"},
                        "validation_errors": [],
                    },
                ],
            },
            ensure_ascii=False,
        )
        result = run_node_json(
            textwrap.dedent(
                f"""
                const manifestText = {manifest!r};
                function assertion(condition, message, details) {{
                  if (!condition) {{
                    const error = new Error(message);
                    error.details = details;
                    throw error;
                  }}
                }}
                function exactArrayEqual(left, right) {{
                  return Array.isArray(left)
                    && Array.isArray(right)
                    && left.length === right.length
                    && left.every((value, index) => value === right[index]);
                }}
                function validatedKeyInventory(value, label, options) {{
                  options = options || {{}};
                  assertion(Array.isArray(value), `${{label}} is not an array`);
                  assertion(
                    !options.nonempty || value.length > 0,
                    `${{label}} is empty`,
                  );
                  const keys = value.map(key => String(key || ""));
                  assertion(
                    keys.every(key => /^[A-Z0-9]{{8}}$/.test(key)),
                    `${{label}} contains an invalid item key`,
                  );
                  assertion(
                    exactArrayEqual(keys, [...keys].sort())
                      && new Set(keys).size === keys.length,
                    `${{label}} must be sorted and duplicate-free`,
                  );
                  return keys;
                }}
                function validateManifestContract(manifest) {{
                  const collectionItemInventory = validatedKeyInventory(
                    manifest.collection_item_inventory,
                    "collection_item_inventory",
                    {{ nonempty: true }},
                  );
                  assertion(Array.isArray(manifest.entries), "manifest entries are missing");
                  assertion(
                    manifest.entries.every(
                      entry => entry && typeof entry === "object",
                    ),
                    "manifest contains a non-object entry",
                  );
                  const parentKeys = manifest.entries.map(entry =>
                    String(entry.parent_key || ""),
                  );
                  assertion(
                    parentKeys.length === collectionItemInventory.length
                      && new Set(parentKeys).size === collectionItemInventory.length,
                    "manifest entries do not exactly cover collection_item_inventory",
                  );
                  const allowedStatuses = new Set([
                    "staged_verified",
                    "unchanged_verified",
                    "staged_invalid",
                    "no_existing_note",
                    "blocked_multiple_notes",
                    "blocked_multiple_pdfs",
                  ]);
                  for (const entry of manifest.entries) {{
                    const parentKey = String(entry.parent_key || "");
                    assertion(
                      allowedStatuses.has(entry.status),
                      `${{parentKey}}: unsupported migration status`,
                    );
                    const childNoteInventory = validatedKeyInventory(
                      entry.child_note_inventory,
                      `${{parentKey}}: child_note_inventory`,
                    );
                    const childAttachmentInventory = validatedKeyInventory(
                      entry.child_attachment_inventory,
                      `${{parentKey}}: child_attachment_inventory`,
                    );
                    if (
                      entry.status === "staged_verified"
                      || entry.status === "unchanged_verified"
                    ) {{
                      const noteKey = String(entry.note_key || "");
                      assertion(
                        entry.expected_parent_key === parentKey,
                        `${{noteKey}}: parent_key and expected_parent_key differ`,
                      );
                      assertion(
                        exactArrayEqual(childNoteInventory, [noteKey]),
                        `${{noteKey}}: staged parent must have exactly the approved child note`,
                      );
                      assertion(
                        childAttachmentInventory.includes(entry.pdf_attachment_key),
                        `${{noteKey}}: approved PDF attachment is absent from child inventory`,
                      );
                    }}
                  }}
                  const blocking = manifest.entries.filter(entry =>
                    ["staged_invalid", "blocked_multiple_notes", "blocked_multiple_pdfs"]
                      .includes(entry.status)
                  );
                  assertion(
                    blocking.length === 0,
                    "manifest contains invalid or ambiguous entries",
                    blocking.map(entry => ({{
                      parentKey: entry.parent_key,
                      status: entry.status,
                    }})),
                  );
                  return {{
                    collectionItemInventory,
                    entries: manifest.entries,
                  }};
                }}
                function sha256Text() {{
                  return "MANIFEST_SHA256";
                }}
                function plainError(error) {{
                  return {{
                    name: error && error.name ? error.name : "Error",
                    message: error && error.message ? error.message : String(error),
                    details: error && error.details,
                  }};
                }}
                const CONFIG = {{
                  apply: true,
                  reportPath: "/tmp/report.json",
                  manifestPath: "/tmp/manifest.json",
                  manifestSHA256: "MANIFEST_SHA256",
                  requireAutoSyncEnabled: false,
                  expectedInventoryNoteCount: 1,
                  expectedMutationCount: 0,
                  expectedMutationKeys: [],
                }};
                const migrationText = manifestText;
                const Zotero = {{
                  File: {{
                    getContentsAsync: async () => migrationText,
                  }},
                  Prefs: {{
                    get: (key) => key === "sync.autoSync" ? true : null,
                  }},
                }};
                let resolveAndVerifyTargetCalled = false;
                let verifyLiveManifestInventoryCalled = false;
                async function resolveAndVerifyTarget() {{
                  resolveAndVerifyTargetCalled = true;
                  return {{
                    collection: {{ id: 27 }},
                    library: {{ libraryID: 1234567 }},
                    publicTarget: {{
                      group_id: 1234567,
                      collection_key: "TEST0001",
                    }},
                  }};
                }}
                async function verifyLiveManifestInventory() {{
                  verifyLiveManifestInventoryCalled = true;
                  return {{ collectionItemCount: 1 }};
                }}
                async function verifyEntry(entry) {{
                  return {{
                    status: entry.status,
                    noteKey: entry.note_key,
                    parentKey: entry.parent_key,
                    oldVersion: 1,
                    oldSHA256: "old",
                    sourceSHA256: "new",
                    expectedStoredSHA256: "new",
                    storageNormalization: "none",
                  }};
                }}
                async function applyTransaction() {{}}
                async function inspectTransactionOutcome() {{
                  return {{ outcome: "committed" }};
                }}
                async function readBack() {{
                  return [];
                }}
                {function_source}
                (async () => {{
                  const result = await runMigration();
                  process.stdout.write(
                    JSON.stringify({{
                      status: result.status,
                      mode: result.mode,
                      phase: result.phase || null,
                      errorMessage: result.error && result.error.message,
                      writePerformed: result.writePerformed,
                      mutationCount: result.mutationCount,
                      mutationKeys: result.mutationKeys,
                    }}),
                  );
                }})().catch(error => {{
                  console.error(error);
                  process.exit(1);
                }});
                """
            )
        )

        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["mode"], "apply")
        self.assertEqual(result["phase"], "load_manifest")
        self.assertFalse(result["writePerformed"])
        self.assertIsNotNone(result["errorMessage"])
        self.assertIn("unsupported migration status", str(result["errorMessage"]))

    @unittest.skipUnless(NODE, "Node.js is required for runner execution tests")
    def test_validate_manifest_contract_rejects_unchanged_hash_divergence(self) -> None:
        function_source = extract_js_function(
            "function validateManifestContract",
            "\nasync function liveCollectionItemInventory",
        )
        result = run_node_json(
            textwrap.dedent(
                f"""
                const manifest = {{
                  collection_item_inventory: ["HGFEDCBA"],
                  entries: [{{
                    status: "unchanged_verified",
                    note_key: "ABCDEFGH",
                    parent_key: "HGFEDCBA",
                    expected_parent_key: "HGFEDCBA",
                    child_note_inventory: ["ABCDEFGH"],
                    child_attachment_inventory: ["PDFATT01"],
                    note_version: 1,
                    old_sha256: "a".repeat(64),
                    new_sha256: "b".repeat(64),
                    pdf_attachment_key: "PDFATT01",
                    pdf_attachment_link_mode: "imported_file",
                  }}],
                }};
                function assertion(condition, message, details) {{
                  if (!condition) {{
                    const error = new Error(message);
                    error.details = details;
                    throw error;
                  }}
                }}
                function exactArrayEqual(left, right) {{
                  return Array.isArray(left)
                    && Array.isArray(right)
                    && left.length === right.length
                    && left.every((value, index) => value === right[index]);
                }}
                function validatedKeyInventory(value, label, options) {{
                  options = options || {{}};
                  assertion(Array.isArray(value), `${{label}} is not an array`);
                  assertion(
                    !options.nonempty || value.length > 0,
                    `${{label}} is empty`,
                  );
                  const keys = value.map(key => String(key || ""));
                  assertion(
                    keys.every(key => /^[A-Z0-9]{{8}}$/.test(key)),
                    `${{label}} contains an invalid item key`,
                  );
                  assertion(
                    exactArrayEqual(
                      keys,
                      [...keys].sort(),
                    ) && new Set(keys).size === keys.length,
                    `${{label}} must be sorted and duplicate-free`,
                  );
                  return keys;
                }}
                let accepted = false;
                let errorMessage = null;
                {function_source}
                try {{
                  validateManifestContract(manifest);
                  accepted = true;
                }}
                catch (_error) {{
                  errorMessage = String(_error && _error.message || _error);
                }}
                process.stdout.write(
                  JSON.stringify({{ accepted, errorMessage }}),
                );
                """
            )
        )
        self.assertFalse(result["accepted"])
        self.assertIn(
            "unchanged note hashes are inconsistent",
            result["errorMessage"],
        )

    @unittest.skipUnless(NODE, "Node.js is required for runner execution tests")
    def test_verify_entry_rejects_unchanged_hash_divergence(self) -> None:
        function_source = extract_js_function(
            "async function verifyEntry",
            "\nasync function verifyLiveManifestInventory",
        )
        verification_js = textwrap.dedent(
            """
                const crypto = require("crypto");
                const pdfContent = "%PDF-1.4\\nfixture\\n%%EOF\\n";
                const pdfSHA = crypto
                  .createHash("sha256")
                  .update(pdfContent, "utf-8")
                  .digest("hex");
                const oldHTML = '<div data-schema-version="9">'
                  + '<h1>文献笔记｜NOTE0001</h1>'
                  + '<h2>资料与阅读状态</h2>'
                  + '<h2>为什么重要</h2>'
                  + '<h2>一句话结论</h2>'
                  + '<h2>心智模型</h2>'
                  + '<h2>关键主张与证据</h2>'
                  + '<h2>方法或推导</h2>'
                  + '<h2>结果</h2>'
                  + '<h2>假设、失败边界与竞争解释</h2>'
                  + '<h2>知识图谱关系</h2>'
                  + '<h2>复用</h2>'
                  + '<h2>溯源</h2>'
                  + '<p>old</p>'
                  + '</div>';
                const newHTML = '<div data-schema-version="9">'
                  + '<h1>文献笔记｜NOTE0001</h1>'
                  + '<h2>资料与阅读状态</h2>'
                  + '<h2>为什么重要</h2>'
                  + '<h2>一句话结论</h2>'
                  + '<h2>心智模型</h2>'
                  + '<h2>关键主张与证据</h2>'
                  + '<h2>方法或推导</h2>'
                  + '<h2>结果</h2>'
                  + '<h2>假设、失败边界与竞争解释</h2>'
                  + '<h2>知识图谱关系</h2>'
                  + '<h2>复用</h2>'
                  + '<h2>溯源</h2>'
                  + '<p>changed</p>' + pdfSHA
                  + '</div>';
                const files = {
                  "/tmp/old.html": oldHTML,
                  "/tmp/new.html": newHTML,
                  "/tmp/paper.pdf": pdfContent,
                };
                const noteKey = "NOTE0001";
                const parentKey = "PARENT01";
                const attachmentKey = "PDFATT01";
                const fileVerificationCache = new Map();
                const bytes = value => Array.from(Buffer.from(value, "utf-8"));
                function bytesToHex(bytesArray) {
                  return bytesArray
                    .map(item => item.toString(16).padStart(2, "0"))
                    .join("");
                }
                function sha256Text(value) {
                  return crypto
                    .createHash("sha256")
                    .update(value, "utf-8")
                    .digest("hex");
                }
                function sha256Bytes(data) {
                  return bytesToHex(
                    Array.from(
                      crypto
                        .createHash("sha256")
                        .update(Buffer.from(data))
                        .digest(),
                    ),
                  );
                }
                function assertion(condition, message, details) {
                  if (!condition) {
                    const error = new Error(message);
                    error.details = details;
                    throw error;
                  }
                }
                function verifiedBytes(path) {
                  const key = String(path || "");
                  assertion(typeof key === "string" && files[key], `${{key}}`);
                  const cached = fileVerificationCache.get(key);
                  if (cached) {
                    return cached;
                  }
                  const payload = {
                    magic: files[key].slice(0, 5),
                    sha256: sha256Text(files[key]),
                  };
                  fileVerificationCache.set(key, payload);
                  return payload;
                }
                async function verifyPDFFile(path, expectedSHA256, currentNoteKey) {
                  const verified = verifiedBytes(path);
                  assertion(
                    verified.magic === "%PDF-",
                    `${{currentNoteKey}}: local file is not a PDF`,
                  );
                  assertion(
                    verified.sha256 === expectedSHA256,
                    `${{currentNoteKey}}: local PDF hash changed`,
                    {
                      observed: verified.sha256,
                      expected: expectedSHA256,
                    },
                  );
                }
                function expectedAttachmentLinkMode(linkMode) {
                  const expectedLinkModes = {
                    imported_file: 0,
                    imported_url: 1,
                    linked_file: 2,
                  };
                  assertion(
                    Object.hasOwn(expectedLinkModes, linkMode),
                    `unsupported PDF attachment link mode: ${{linkMode}}`,
                  );
                  return expectedLinkModes[linkMode];
                }
                const PathUtils = {{ normalize: value => value }};
                async function verifyAttachmentFileBinding(attachment, expectedPath, noteKey) {{
                  const observedPath = await attachment.getFilePathAsync();
                  assertion(
                    typeof observedPath === "string" && observedPath,
                    `${{noteKey}}: approved PDF attachment has no local file path`,
                  );
                  const normalizedObserved = PathUtils.normalize(observedPath);
                  const normalizedExpected = PathUtils.normalize(expectedPath);
                  assertion(
                    normalizedObserved === normalizedExpected,
                    `${{noteKey}}: approved PDF attachment file path changed`,
                    {{
                      observed: normalizedObserved,
                      expected: normalizedExpected,
                    }},
                  );
                }
                function normalizedNoteHTML(value) {
                  const withoutControlCharacters = String(value).replace(
                    /[\\u0000-\\u0008\\u000B\\u000C\\u000E-\\u001F\\u007F]/g,
                    "",
                  );
                  assertion(
                    withoutControlCharacters === String(value),
                    "staged note contains control characters that Zotero would remove",
                  );
                  return String(value).trim();
                }
                const noteHeading = [
                  "资料与阅读状态",
                  "为什么重要",
                  "一句话结论",
                  "心智模型",
                  "关键主张与证据",
                  "方法或推导",
                  "结果",
                  "假设、失败边界与竞争解释",
                  "知识图谱关系",
                  "复用",
                  "溯源",
                ];
                function semanticHTMLProjection(_html) {
                  const headings = [
                    {{ tag: "h1", text: "文献笔记｜NOTE0001" }},
                    ...noteHeading.map(name => ({ tag: "h2", text: name })),
                  ];
                  return {{
                    root: {{ tag: "div", schemaVersion: "9" }},
                    headings,
                  }};
                }
                __FUNCTION_SOURCE__
                let rejectedMessage = null;
                const oldSHA = sha256Text(oldHTML);
                const newSHA = sha256Text(newHTML);
                const entry = {{
                  status: "unchanged_verified",
                  note_key: noteKey,
                  parent_key: parentKey,
                  expected_parent_key: parentKey,
                  note_version: 1,
                  old_path: "/tmp/old.html",
                  new_path: "/tmp/new.html",
                  old_sha256: oldSHA,
                  new_sha256: newSHA,
                  pdf_path: "/tmp/paper.pdf",
                  pdf_sha256: pdfSHA,
                  pdf_attachment_key: attachmentKey,
                  pdf_attachment_link_mode: "imported_file",
                  validation_summary: {{ schema_version: "9" }},
                  validation_errors: [],
                  child_note_inventory: [noteKey],
                  child_attachment_inventory: [attachmentKey],
                }};
                const targetContext = {{
                  library: {{ libraryID: 1234567 }},
                  collection: {
                    id: 27,
                    hasItem: () => true,
                  },
                }};
                const oldHashHex = sha256Bytes(bytes(oldHTML));
                const note = {{
                  isNote: () => true,
                  deleted: false,
                  parentItemKey: parentKey,
                  libraryID: 1234567,
                  isEditable: () => true,
                  version: 1,
                  async loadAllData() {{}},
                  getNote: () => oldHTML,
                }};
                const parent = {{
                  key: parentKey,
                  isRegularItem: () => true,
                  deleted: false,
                  async reload() {{ }},
                  async loadDataType() {{ }},
                  libraryID: 1234567,
                  getCollections: () => [27],
                  hasItem: () => true,
                }};
                const attachment = {{
                  isAttachment: () => true,
                  deleted: false,
                  parentItemKey: parentKey,
                  attachmentContentType: "application/pdf",
                  attachmentLinkMode: 0,
                  async getFilePathAsync() {{
                    return "/tmp/paper.pdf";
                  }},
                }};
                const Zotero = {{
                  File: {{
                    async getContentsAsync(path) {{
                      assertion(typeof path === "string", "path must be string");
                      return files[path];
                    }},
                  }},
                  Items: {{
                    getByLibraryAndKeyAsync: async (_libraryID, key) => {
                      if (key === noteKey) {{
                        return note;
                      }}
                      if (key === parentKey) {{
                        return parent;
                      }}
                      if (key === attachmentKey) {{
                        return attachment;
                      }}
                      return null;
                    }},
                  }},
                  Attachments: {{
                    LINK_MODE_IMPORTED_FILE: 0,
                    LINK_MODE_IMPORTED_URL: 1,
                    LINK_MODE_LINKED_FILE: 2,
                  },
                }};
                const IOUtils = {{
                  async read(path) {{
                    const entry = pathVerification.get(path);
                    if (!entry) {{
                      throw new Error(`missing file: ${{path}}`);
                    }}
                    return bytes(entry.content);
                  }},
                }};
                const pathVerification = new Map([
                  ["/tmp/paper.pdf", {{ content: pdfContent }}],
                ]);
                (async () => {{
                  let message = null;
                  let called = false;
                  try {{
                    await verifyEntry(entry, targetContext);
                    called = true;
                  }}
                  catch (_error) {{
                    message = String(_error && _error.message || _error);
                  }}
                  process.stdout.write(
                    JSON.stringify({{
                      called,
                      message,
                      oldHashHex,
                    }}),
                  );
                }})().catch(error => {{
                  console.error(error);
                  process.exit(1);
                }});
                """
            .replace("{{", "{")
            .replace("}}", "}")
            .replace("__FUNCTION_SOURCE__", function_source)
        )
        result = run_node_json(verification_js)
        self.assertFalse(result["called"])
        self.assertIn("unchanged note hashes are inconsistent", result["message"])

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
                      old_sha256: "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
                      new_sha256: "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
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
