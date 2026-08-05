"use strict";

const assert = require("assert");
const core = require("./zotero_attachment_repair_core.js");

let passed = 0;

function test(name, callback) {
  try {
    callback();
    passed += 1;
  }
  catch (error) {
    error.message = `${name}: ${error.message}`;
    throw error;
  }
}

function throwsWith(callback, fragment) {
  assert.throws(callback, error => String(error.message).includes(fragment));
}

const target = {
  group_id: 8,
  library_id: 2,
  library_name: "group",
  local_collection_id: 40,
  collection_key: "COLL0001",
  collection_path: [{key: "ROOT0001", name: "root"}, {key: "COLL0001", name: "target"}],
  require_library_editable: true,
  require_files_editable: true,
};

test("target mismatch", () => {
  throwsWith(
    () => core.verifyTarget(target, {
      ...target,
      library_editable: true,
      files_editable: true,
      local_collection_id: 41,
    }),
    "local_collection_id mismatch",
  );
});

test("parent version drift", () => {
  const expected = {
    key: "PARENT01", version: 3, item_type: "journalArticle", doi: "10/x",
    title: "paper", collection_key: "COLL0001",
  };
  throwsWith(
    () => core.verifyParent(expected, {...expected, version: 4, in_target_collection: true}),
    "version drift",
  );
});

test("file hash mismatch", () => {
  throwsWith(
    () => core.verifyFileBinding(
      {size_bytes: 8, sha256: "sha256:a", magic: "%PDF-", content_type: "application/pdf"},
      {size_bytes: 8, sha256: "sha256:b", magic: "%PDF-", content_type: "application/pdf"},
    ),
    "sha256 mismatch",
  );
});

test("duplicate live key", () => {
  const item = {
    key: "ATTACH01", version: 1, content_type: "application/pdf", link_mode: "imported_file",
    readable_pdf: true, sha256: "sha256:a",
  };
  throwsWith(
    () => core.classifyLiveAttachments("attach_missing_pdf", [], [item, {...item}], "sha256:a"),
    "duplicate live attachment key",
  );
});

test("one same hash is an idempotent no-op", () => {
  const first = {
    key: "ATTACH01", version: 1, content_type: "application/pdf", link_mode: "imported_file",
    readable_pdf: true, sha256: "sha256:a",
  };
  const result = core.classifyLiveAttachments(
    "attach_missing_pdf", [], [first], "sha256:a",
  );
  assert.strictEqual(result.decision, "no_op_same_hash");
  assert.strictEqual(result.duplicateCount, 0);
});

test("multiple same-hash PDFs are a conflict", () => {
  const first = {
    key: "ATTACH01", version: 1, content_type: "application/pdf", link_mode: "imported_file",
    readable_pdf: true, sha256: "sha256:a",
  };
  const second = {...first, key: "ATTACH02"};
  throwsWith(
    () => core.classifyLiveAttachments(
      "attach_missing_pdf", [], [first, second], "sha256:a",
    ),
    "multiple readable PDFs with the source hash",
  );
});

test("single import outcome requires positive evidence to claim commit", () => {
  assert.strictEqual(
    core.classifyImportOutcome(["PARENT01"], {PARENT01: true}, false),
    "committed",
  );
  assert.strictEqual(
    core.classifyImportOutcome(["PARENT01"], {PARENT01: false}, false),
    "unknown",
  );
  assert.strictEqual(
    core.classifyImportOutcome(["PARENT01"], {PARENT01: true}, true),
    "unknown",
  );
  throwsWith(
    () => core.classifyImportOutcome(
      ["PARENT01", "PARENT02"],
      {PARENT01: true, PARENT02: false},
      false,
    ),
    "exactly one planned parent",
  );
});

test("readback verifies parent content hash size and inherited collection", () => {
  assert.strictEqual(
    core.verifyReadback(
      {parent_key: "PARENT01", size_bytes: 8, sha256: "sha256:a"},
      {
        parent_key: "PARENT01",
        content_type: "application/pdf",
        size_bytes: 8,
        sha256: "sha256:a",
        magic: "%PDF-",
        parent_in_target_collection: true,
        direct_collection_count: 0,
      },
    ),
    true,
  );
});

process.stdout.write(JSON.stringify({passed}) + "\n");
