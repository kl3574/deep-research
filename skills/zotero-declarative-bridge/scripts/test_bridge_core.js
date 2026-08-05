"use strict";

const assert = require("assert");
const path = require("path");
const core = require(path.join(__dirname, "..", "assets", "zotero-plugin", "bridge_core.js"));

function baseManifest() {
  return {
    schema: "ZoteroDeclarativeTransaction/v1",
    transaction_id: "fixture-transaction",
    generated_at: "2026-08-05T00:00:00Z",
    target: {
      library_id: 2,
      library_type: "group",
      library_type_id: 123,
      library_name: "Fixture",
      collection_id: 40,
      collection_key: "ABCDEFGH",
      collection_path: [{key: "ABCDEFGH", name: "Target"}],
      require_editable: true,
      require_files_editable: false,
    },
    entries: [{
      parent: {
        key: "PARENT01",
        version: 7,
        item_type: "journalArticle",
        title: "Fixture parent",
        doi: "10.1/fixture",
        identity_sha256: "sha256:" + "a".repeat(64),
        expected_target_membership: false,
      },
      operations: [{type: "ensure_collection_membership", expected_present: false}],
    }],
    manifest_sha256: "sha256:" + "b".repeat(64),
  };
}

assert.strictEqual(core.stableStringify({b: 2, a: 1}), '{"a":1,"b":2}');
assert.strictEqual(core.validateManifest(baseManifest()), true);
assert.throws(() => {
  const manifest = baseManifest();
  manifest.entries[0].operations[0].arbitrary = "javascript";
  core.validateManifest(manifest);
}, /keys differ/);
assert.deepStrictEqual(
  core.classifyMembership({expected_present: false}, false),
  {decision: "needs_write"},
);
assert.deepStrictEqual(
  core.classifyMembership({expected_present: false}, true),
  {decision: "satisfied"},
);
const noteOperation = {
  note_key: null,
  expected_child_note_keys: [],
  new_sha256: "sha256:" + "c".repeat(64),
};
assert.strictEqual(core.classifyNote(noteOperation, []).decision, "needs_write");
assert.strictEqual(
  core.classifyNote(noteOperation, [{key: "NOTE0001", version: 2, sha256: noteOperation.new_sha256}]).decision,
  "satisfied",
);
const pdfOperation = {
  source_sha256: "sha256:" + "d".repeat(64),
  expected_attachments: [{key: "ATTACH01", version: 1, content_type: "application/pdf", link_mode: "imported_file"}],
};
assert.strictEqual(
  core.classifyAttachment(pdfOperation, [{key: "ATTACH01", version: 1, content_type: "application/pdf", link_mode: "imported_file", readable_pdf: false, sha256: null, direct_collection_count: 0}]).decision,
  "needs_write",
);
assert.strictEqual(
  core.classifyAttachment(pdfOperation, [{key: "NEWPDF01", version: 1, content_type: "application/pdf", link_mode: "imported_file", readable_pdf: true, sha256: pdfOperation.source_sha256, direct_collection_count: 0}]).decision,
  "satisfied",
);
assert.throws(
  () => core.classifyAttachment(pdfOperation, [{key: "OTHERPDF", version: 1, content_type: "application/pdf", link_mode: "imported_file", readable_pdf: true, sha256: "sha256:" + "e".repeat(64), direct_collection_count: 0}]),
  /different readable PDF/,
);
assert.throws(
  () => core.classifyAttachment(pdfOperation, [{key: "NEWPDF01", version: 1, content_type: "application/pdf", link_mode: "imported_file", readable_pdf: true, sha256: pdfOperation.source_sha256, direct_collection_count: 1}]),
  /direct collection membership/,
);
process.stdout.write("bridge_core: 11 checks passed\n");
