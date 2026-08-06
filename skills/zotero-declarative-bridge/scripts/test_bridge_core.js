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
const baselineMembershipEntry = {
  parent: {expected_target_membership: true},
  operations: [{type: "ensure_parent_short_title"}],
};
assert.strictEqual(
  core.readbackMembershipSatisfied(baselineMembershipEntry, true, [{decision: "satisfied"}]),
  true,
);
assert.strictEqual(
  core.readbackMembershipSatisfied(baselineMembershipEntry, false, [{decision: "satisfied"}]),
  false,
);
const ensuredMembershipEntry = baseManifest().entries[0];
assert.strictEqual(
  core.readbackMembershipSatisfied(ensuredMembershipEntry, true, [{decision: "satisfied"}]),
  true,
);
assert.strictEqual(
  core.readbackMembershipSatisfied(ensuredMembershipEntry, false, [{decision: "satisfied"}]),
  false,
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
assert.throws(
  () => core.classifyAttachment(pdfOperation, [
    {key: "NEWPDF01", version: 1, content_type: "application/pdf", link_mode: "imported_file", readable_pdf: true, sha256: pdfOperation.source_sha256, direct_collection_count: 0},
    {key: "NEWPDF02", version: 1, content_type: "application/pdf", link_mode: "imported_file", readable_pdf: true, sha256: pdfOperation.source_sha256, direct_collection_count: 0},
  ]),
  /multiple matching PDF attachments/,
);
const shortTitleOperation = {
  type: "ensure_parent_short_title",
  library_id: 2,
  parent_key: "PARENT01",
  expected_parent_version: 7,
  expected_old_value: "Old title",
  new_short_title: "Reviewed title",
};
assert.deepStrictEqual(
  core.classifyShortTitle(shortTitleOperation, {library_id: 2, parent_key: "PARENT01", item_version: 7, value: "Old title"}),
  {decision: "needs_write"},
);
assert.deepStrictEqual(
  core.classifyShortTitle(shortTitleOperation, {library_id: 2, parent_key: "PARENT01", item_version: 99, value: "Reviewed title"}),
  {decision: "satisfied"},
);
assert.throws(
  () => core.classifyShortTitle(shortTitleOperation, {library_id: 2, parent_key: "PARENT01", item_version: 8, value: "Old title"}),
  /parent-version drift/,
);
assert.throws(
  () => core.classifyShortTitle(shortTitleOperation, {library_id: 2, parent_key: "PARENT01", item_version: 7, value: "Concurrent edit"}),
  /old-value drift/,
);
const shortTitleManifest = baseManifest();
shortTitleManifest.entries[0].parent.expected_target_membership = true;
shortTitleManifest.entries[0].operations = [shortTitleOperation];
assert.strictEqual(core.validateManifest(shortTitleManifest), true);
shortTitleManifest.entries[0].operations[0].library_id = 3;
assert.throws(() => core.validateManifest(shortTitleManifest), /disagrees with target/);
const fullPDFOperation = {
  type: "ensure_pdf_attachment",
  source_path: "/tmp/fixture.pdf",
  source_size_bytes: 17,
  source_sha256: "sha256:" + "d".repeat(64),
  source_magic: "%PDF-",
  expected_attachments: [],
};
const attachmentManifest = baseManifest();
attachmentManifest.target.require_files_editable = true;
attachmentManifest.entries[0].parent.expected_target_membership = true;
attachmentManifest.entries[0].operations = [fullPDFOperation];
assert.strictEqual(core.validateManifest(attachmentManifest), true);
const mixedManifest = baseManifest();
mixedManifest.target.require_files_editable = true;
mixedManifest.entries[0].operations.push(fullPDFOperation);
assert.throws(() => core.validateManifest(mixedManifest), /cannot share/);
assert.deepStrictEqual(core.planWrites([]), {
  mode: "none",
  operation_count: 0,
  attachment_operation_count: 0,
  database_operation_count: 0,
});
assert.strictEqual(core.planWrites([{
  entry: {operations: [fullPDFOperation]},
  decisions: [{decision: "needs_write"}],
}]).mode, "single_attachment_import");
assert.strictEqual(core.planWrites([{
  entry: {operations: [{type: "ensure_parent_short_title"}]},
  decisions: [{decision: "needs_write"}],
}]).mode, "db_atomic");
assert.throws(() => core.planWrites([
  {entry: {operations: [fullPDFOperation]}, decisions: [{decision: "needs_write"}]},
  {entry: {operations: [fullPDFOperation]}, decisions: [{decision: "needs_write"}]},
]), /multiple PDF attachment mutations/);
const collectionRequest = {library_id: 2, collection_key: "COLL0001"};
const groupLibrary = {libraryID: 2, libraryType: "group"};
const exactCollection = {id: 40, libraryID: 2, key: "COLL0001", deleted: false};
assert.strictEqual(core.validateCollectionResolutionRequest(collectionRequest), collectionRequest);
assert.throws(
  () => core.validateCollectionResolutionRequest({...collectionRequest, name: "guess"}),
  /keys differ/,
);
assert.deepStrictEqual(
  core.resolveCollectionID(collectionRequest, groupLibrary, exactCollection),
  {status: "resolved", library_id: 2, collection_key: "COLL0001", collection_id: 40},
);
assert.throws(
  () => core.resolveCollectionID(collectionRequest, null, exactCollection),
  error => error.code === "library_not_found",
);
assert.throws(
  () => core.resolveCollectionID(collectionRequest, {libraryID: 2, libraryType: "user"}, exactCollection),
  error => error.code === "library_not_group",
);
assert.throws(
  () => core.resolveCollectionID(collectionRequest, groupLibrary, null),
  error => error.code === "collection_not_found",
);
assert.throws(
  () => core.resolveCollectionID(collectionRequest, groupLibrary, [exactCollection, {...exactCollection, id: 41}]),
  error => error.code === "collection_ambiguous",
);
assert.throws(
  () => core.resolveCollectionID(collectionRequest, groupLibrary, {...exactCollection, libraryID: 3}),
  error => error.code === "collection_mismatch",
);
assert.throws(
  () => core.resolveCollectionID(collectionRequest, groupLibrary, {...exactCollection, key: "OTHER001"}),
  error => error.code === "collection_mismatch",
);
assert.throws(
  () => core.resolveCollectionID(collectionRequest, groupLibrary, {...exactCollection, deleted: true}),
  error => error.code === "collection_not_found",
);
process.stdout.write("bridge_core: 38 checks passed\n");
