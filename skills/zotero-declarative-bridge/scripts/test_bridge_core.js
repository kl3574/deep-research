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

function textNode(value) {
  return {nodeType: 3, nodeValue: value};
}

function elementNode(tag, attributes = {}, children = []) {
  return {
    nodeType: 1,
    tagName: tag.toUpperCase(),
    attributes: Object.entries(attributes).map(([name, value]) => ({name, value})),
    childNodes: children,
  };
}

function storageNoteFixture(options = {}) {
  const displayFormula = options.displayFormula || "$$S=\\sum_{i=1}^{n}x_i$$";
  const inlineFormula = options.inlineFormula || "$\\exp(2)$";
  const firstText = options.firstText || "证据甲。";
  const secondText = options.secondText || "证据乙。";
  const paragraphPrefix = options.paragraphPrefix === undefined ? "结论为 " : options.paragraphPrefix;
  const paragraphSuffix = options.paragraphSuffix || "，并保留边界。";
  const inline = elementNode(options.inlineTag || "span", {class: options.mathClass || "math"}, [textNode(inlineFormula)]);
  const paragraph = elementNode(options.paragraphTag || "p", options.paragraphAttributes || {}, [
    textNode(paragraphPrefix), inline, textNode(paragraphSuffix),
  ]);
  const listItems = [
    elementNode("li", {}, [textNode(options.formatted ? `\n${firstText}\n` : firstText)]),
    elementNode("li", {}, [textNode(options.formatted ? `\n${secondText}\n` : secondText)]),
  ];
  if (options.reverseList) listItems.reverse();
  if (options.removeSecond) listItems.pop();
  const listChildren = options.formatted
    ? [textNode("\n"), ...listItems.flatMap(item => [item, textNode("\n")])]
    : listItems;
  const blocks = [
    elementNode("h1", {}, [textNode("受限采样时：结论保持可审计")]),
    elementNode(options.displayTag || "pre", {class: "math"}, [textNode(displayFormula)]),
    paragraph,
    elementNode("ul", {}, listChildren),
  ];
  const rootChildren = options.formatted
    ? blocks.flatMap((block, index) => index === blocks.length - 1 ? [block] : [block, textNode("\n")])
    : [textNode("\n"), blocks[0], textNode("\n"), blocks[1], blocks[2], blocks[3], textNode("\n")];
  return elementNode("div", options.rootAttributes || {"data-schema-version": "9"}, rootChildren);
}

function runtimeDocument(root, parserError = false) {
  return {
    body: {childNodes: [textNode("\n"), root, textNode("\n")]},
    getElementsByTagName(tag) {
      return tag === "parsererror" && parserError ? [{}] : [];
    },
  };
}

const runtimeParserInputs = [];
class RuntimeDOMParser {
  parseFromString(value, type) {
    runtimeParserInputs.push({value, type});
    if (value === "reviewed") return runtimeDocument(storageNoteFixture());
    if (value === "stored") return runtimeDocument(storageNoteFixture({formatted: true}));
    return runtimeDocument(storageNoteFixture(), true);
  }
}

assert.strictEqual(core.stableStringify({b: 2, a: 1}), '{"a":1,"b":2}');
assert.deepStrictEqual(core.versionEvidence(7, false, 7), {
  observed_version: 7,
  precondition_version: 7,
  current_synced_version: null,
  sync_status: "locally_modified_pending_sync",
});
assert.deepStrictEqual(core.versionEvidence(11, true, 7), {
  observed_version: 11,
  precondition_version: 7,
  current_synced_version: 11,
  sync_status: "synced",
});
assert.throws(() => core.versionEvidence(7, "false", 7), /synced flag/);
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
assert.strictEqual(
  core.classifyNote(noteOperation, [{key: "NOTE0001", version: 2, sha256: noteOperation.new_sha256}]).content_match,
  "exact",
);
const reviewedFingerprint = core.noteStorageDOMFingerprint(storageNoteFixture());
const zoteroFormattedFingerprint = core.noteStorageDOMFingerprint(storageNoteFixture({formatted: true}));
assert.strictEqual(reviewedFingerprint, zoteroFormattedFingerprint);
const reviewedRuntimeFingerprint = core.noteStorageHTMLFingerprint("reviewed", RuntimeDOMParser);
const storedRuntimeFingerprint = core.noteStorageHTMLFingerprint("stored", RuntimeDOMParser);
assert.strictEqual(reviewedRuntimeFingerprint, storedRuntimeFingerprint);
assert.deepStrictEqual(runtimeParserInputs, [
  {value: "reviewed", type: "text/html"},
  {value: "stored", type: "text/html"},
]);
assert.throws(() => core.noteStorageHTMLFingerprint("reviewed", undefined), /DOMParser is unavailable/);
assert.throws(() => core.noteStorageHTMLFingerprint("invalid", RuntimeDOMParser), /note DOM parse failed/);
const semanticNoteOperation = {
  note_key: "NOTE0001",
  expected_child_note_keys: ["NOTE0001"],
  expected_note_version: 2,
  expected_old_sha256: "sha256:" + "1".repeat(64),
  new_sha256: "sha256:" + "2".repeat(64),
  new_storage_fingerprint_sha256: "sha256:" + "3".repeat(64),
};
assert.deepStrictEqual(
  core.classifyNote(semanticNoteOperation, [{
    key: "NOTE0001",
    version: 99,
    sha256: semanticNoteOperation.new_sha256,
    storage_fingerprint_sha256: "sha256:" + "5".repeat(64),
  }]),
  {decision: "satisfied", note_key: "NOTE0001", content_match: "exact"},
);
assert.deepStrictEqual(
  core.classifyNote(semanticNoteOperation, [{
    key: "NOTE0001",
    version: 99,
    sha256: "sha256:" + "4".repeat(64),
    storage_fingerprint_sha256: semanticNoteOperation.new_storage_fingerprint_sha256,
  }]),
  {decision: "satisfied", note_key: "NOTE0001", content_match: "zotero_storage_equivalent"},
);
const replayDecisions = Array.from({length: 62}, (_value, index) => {
  const key = `N${String(index).padStart(7, "0")}`;
  const operation = {
    ...semanticNoteOperation,
    note_key: key,
    expected_child_note_keys: [key],
    expected_note_version: index + 1,
  };
  return core.classifyNote(operation, [{
    key,
    version: 1000 + index,
    sha256: index === 12 ? "sha256:" + "4".repeat(64) : operation.new_sha256,
    storage_fingerprint_sha256: index === 12
      ? operation.new_storage_fingerprint_sha256
      : "sha256:" + "5".repeat(64),
  }]);
});
assert.strictEqual(replayDecisions.every(decision => decision.decision === "satisfied"), true);
assert.strictEqual(replayDecisions.filter(decision => decision.content_match === "exact").length, 61);
assert.strictEqual(replayDecisions.filter(decision => decision.content_match === "zotero_storage_equivalent").length, 1);
for (const changed of [
  storageNoteFixture({firstText: "证据丙。"}),
  storageNoteFixture({firstText: "证据甲！"}),
  storageNoteFixture({paragraphAttributes: {title: "changed"}}),
  storageNoteFixture({removeSecond: true}),
  storageNoteFixture({reverseList: true}),
  storageNoteFixture({paragraphPrefix: "结论为"}),
  storageNoteFixture({paragraphTag: "div"}),
  storageNoteFixture({inlineTag: "pre"}),
  storageNoteFixture({inlineFormula: "$\\exp(3)$"}),
  storageNoteFixture({displayFormula: "$$S=\\sum_{i=1}^{n}y_i$$"}),
]) {
  assert.notStrictEqual(core.noteStorageDOMFingerprint(changed), reviewedFingerprint);
}
assert.throws(
  () => core.noteStorageDOMFingerprint(storageNoteFixture({mathClass: "math changed"})),
  /math node attributes/,
);
assert.throws(
  () => core.noteStorageDOMFingerprint(storageNoteFixture({rootAttributes: {"data-schema-version": "9", private: "x"}})),
  /unsupported attributes/,
);
const unsupportedDOM = storageNoteFixture();
unsupportedDOM.childNodes.push({nodeType: 8, nodeValue: "comment"});
assert.throws(() => core.noteStorageDOMFingerprint(unsupportedDOM), /unsupported node/);
assert.throws(
  () => core.classifyNote(semanticNoteOperation, [{
    key: "NOTE0001",
    version: 99,
    sha256: "sha256:" + "4".repeat(64),
    storage_fingerprint_sha256: "sha256:" + "5".repeat(64),
  }]),
  /child note version drift/,
);
assert.strictEqual(core.commitStateAfterFailure({write_attempted: false}), "not_started");
assert.strictEqual(core.commitStateAfterFailure({
  write_attempted: true,
  execution_profile: "db_atomic",
  db_commit_confirmed: true,
  inspection_available: false,
}), "committed_unverified");
assert.strictEqual(core.commitStateAfterFailure({
  write_attempted: true,
  execution_profile: "db_atomic",
  db_commit_confirmed: false,
  inspection_available: true,
  before_state_sha256: "before",
  inspection_state_sha256: "before",
}), "rolled_back");
assert.strictEqual(core.commitStateAfterFailure({
  write_attempted: true,
  execution_profile: "db_atomic",
  db_commit_confirmed: false,
  inspection_available: false,
}), "unknown");
assert.strictEqual(core.commitStateAfterFailure({
  write_attempted: true,
  execution_profile: "db_atomic",
  db_commit_confirmed: false,
  inspection_available: true,
  before_state_sha256: "before",
  inspection_state_sha256: "after",
  inspection_all_satisfied: true,
}), "committed");
assert.strictEqual(core.commitStateAfterFailure({
  write_attempted: true,
  execution_profile: "db_atomic",
  db_commit_confirmed: false,
  inspection_available: true,
  before_state_sha256: "before",
  inspection_state_sha256: "after",
  inspection_all_satisfied: false,
}), "partial_commit");
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
process.stdout.write("bridge_core: storage-equivalence and transaction checks passed\n");
