"use strict";

const assert = require("node:assert/strict");
const nodeCrypto = require("node:crypto");
const crypto = nodeCrypto.webcrypto;
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const vm = require("node:vm");

const core = require("../assets/zotero-plugin/bridge_core.js");
const bootstrapSource = fs.readFileSync(
  path.resolve(__dirname, "../assets/zotero-plugin/bootstrap.js"),
  "utf8",
);
const STATE_A = "sha256:" + "1".repeat(64);

function loadBootstrap() {
  const callbacks = {commit: [], rollback: []};
  const events = [];
  const zotero = {
    DB: {
      addCurrentCallback(kind, callback) {
        callbacks[kind].push(callback);
      },
      async executeTransaction(callback) {
        return callback();
      },
    },
    Items: {
      unload(id) {
        events.push(["unload", id]);
      },
      async getByLibraryAndKeyAsync() {
        throw new Error("unexpected item lookup");
      },
    },
    Server: {Endpoints: {}, port: 23119},
    Profile: {dir: "/tmp"},
    File: {pathToFile: () => ({exists: () => false})},
    version: "9.0.1",
    initializationPromise: Promise.resolve(),
    debug() {},
    logError() {},
  };
  const ioUtils = {};
  const context = vm.createContext({
    __ZOTERO_DECLARATIVE_BRIDGE_TEST__: true,
    ZoteroDeclarativeBridgeCore: core,
    Zotero: zotero,
    Services: {scriptloader: {loadSubScript() {}}},
    IOUtils: ioUtils,
    PathUtils: {join: (...parts) => parts.join("/")},
    crypto,
    TextEncoder,
    DOMParser: class {},
    Ci: {},
    console,
    Date,
    Map,
    Set,
    Uint8Array,
  });
  vm.runInContext(bootstrapSource, context, {filename: "bootstrap.js"});
  assert.ok(
    context.ZoteroDeclarativeBridge.testing,
    "guarded bootstrap test seam missing",
  );
  return {
    callbacks,
    events,
    testing: context.ZoteroDeclarativeBridge.testing,
    zotero,
    ioUtils,
  };
}

function canonicalSHA(value) {
  return "sha256:" + nodeCrypto.createHash("sha256")
    .update(core.stableStringify(value), "utf8").digest("hex");
}

function rawSHA(value) {
  return "sha256:" + nodeCrypto.createHash("sha256").update(value).digest("hex");
}

function serializerGuardFromRaw(parentData, noteData, attachmentData, storagePath, contentSHA, sizeBytes) {
  const children = [
    {
      key: noteData.key,
      item_type: "note",
      version: noteData.version,
      raw_data_sha256: canonicalSHA(noteData),
      content_sha256: rawSHA(Buffer.from(noteData.note, "utf8")),
    },
    {
      key: attachmentData.key,
      item_type: "attachment",
      version: attachmentData.version,
      raw_data_sha256: canonicalSHA(attachmentData),
      stable_data_sha256: canonicalSHA(
        core.metadataSerializerAttachmentStableData(attachmentData),
      ),
      filename_sha256: canonicalSHA(attachmentData.filename),
      storage_path_sha256: canonicalSHA(storagePath),
      content_sha256: contentSHA,
      size_bytes: sizeBytes,
    },
  ];
  const unsigned = {
    profile: "zotero_managed_storage_equivalence_v1",
    parent: {
      raw_data_sha256: canonicalSHA(parentData),
      stable_nonprofile_sha256: canonicalSHA(
        core.metadataSerializerParentStableData(parentData),
      ),
      tags_raw_sha256: canonicalSHA(parentData.tags),
      tags_set_sha256: canonicalSHA(core.metadataSerializerSortedValues(parentData.tags)),
      collections_raw_sha256: canonicalSHA(parentData.collections),
      collections_set_sha256: canonicalSHA(
        core.metadataSerializerSortedValues(parentData.collections),
      ),
    },
    children,
  };
  return {...unsigned, guard_sha256: canonicalSHA(unsigned)};
}

function loadProductionV2Bootstrap(options = {}) {
  const runtime = loadBootstrap();
  const baselineBytes = Buffer.from("%PDF-production-metadata-evidence\n", "utf8");
  const liveBytes = Buffer.from(options.liveBytes || baselineBytes);
  const baselineContentSHA = rawSHA(baselineBytes);
  const noteHTML = '<div data-schema-version="9"><p>Synthetic note</p></div>';
  const expectedProfile = {
    DOI: "10.0000/synthetic.old",
    creators: [],
    publicationTitle: "",
    volume: "",
    issue: "",
    pages: "",
    date: "2026",
  };
  const desiredProfile = {
    DOI: "10.0000/synthetic.new",
    creators: [{creatorType: "author", firstName: "Ada", lastName: "Lovelace"}],
    publicationTitle: "Synthetic Journal",
    volume: "7",
    issue: "2",
    pages: "10-20",
    date: "2026",
  };
  const entryParent = {
    key: "PARENT01",
    version: 3,
    item_type: "journalArticle",
    title: "Synthetic sensitivity study",
    short_title: "Synthetic setting: reviewed conclusion",
    expected_target_membership: true,
  };
  const noteData = {
    key: "NOTE0001",
    version: 2,
    itemType: "note",
    parentItem: "PARENT01",
    note: noteHTML,
    tags: [],
    relations: {},
  };
  const expectedAttachmentData = {
    key: "PDF00001",
    version: 5,
    itemType: "attachment",
    parentItem: "PARENT01",
    title: "Synthetic sensitivity study - full text",
    url: "https://example.invalid/paper.pdf",
    contentType: "application/pdf",
    linkMode: "imported_file",
    md5: "0123456789abcdef0123456789abcdef",
    mtime: 1700000000000,
    filename: "2026 - Synthetic sensitivity study.pdf",
    collections: [],
    tags: [],
    relations: {},
    dateAdded: "2026-01-01T00:00:00Z",
    dateModified: "2026-01-01T00:00:00Z",
  };
  const liveAttachmentData = {
    ...expectedAttachmentData,
    version: options.attachmentVersion ?? 9,
    title: options.attachmentTitle || expectedAttachmentData.title,
    filename: "Lovelace - 2026 - Synthetic sensitivity study.pdf",
  };
  const expectedPath = "/managed/storage/PDF00001/2026 - Synthetic sensitivity study.pdf";
  const livePath = "/managed/storage/PDF00001/Lovelace - 2026 - Synthetic sensitivity study.pdf";
  const parentBase = {
    key: "PARENT01",
    itemType: "journalArticle",
    title: entryParent.title,
    shortTitle: entryParent.short_title,
    abstractNote: "Bound non-profile metadata",
    url: "https://example.invalid/parent",
    dateAdded: "2026-01-01T00:00:00Z",
    relations: {},
  };
  const expectedParentData = {
    ...parentBase,
    version: 3,
    ...expectedProfile,
    tags: [{tag: "reviewed"}, {tag: "method"}],
    collections: ["COLL0001", "OTHER001"],
    dateModified: "2026-01-01T00:00:00Z",
  };
  const liveParentData = {
    ...parentBase,
    version: options.parentVersion ?? 9,
    ...desiredProfile,
    tags: [{tag: "method"}, {tag: "reviewed"}],
    collections: ["OTHER001", "COLL0001"],
    dateModified: "2026-01-03T00:00:00Z",
  };
  const children = [
    {
      key: "NOTE0001", version: 2, item_type: "note",
      content_sha256: rawSHA(Buffer.from(noteHTML, "utf8")),
    },
    {
      key: "PDF00001", version: 5, item_type: "attachment",
      content_type: "application/pdf", link_mode: "imported_file",
      size_bytes: baselineBytes.length, content_sha256: baselineContentSHA,
      direct_collection_count: 0,
    },
  ];
  const serializerGuard = serializerGuardFromRaw(
    expectedParentData,
    noteData,
    expectedAttachmentData,
    expectedPath,
    baselineContentSHA,
    baselineBytes.length,
  );
  const duplicateUnsigned = {
    scope: "full_library",
    desired_doi_other_parent_keys: [],
    title_year_creator_other_parent_keys: [],
  };
  const operation = {
    type: "ensure_parent_journal_metadata_v1",
    expected_parent_version: 3,
    expected_profile: expectedProfile,
    expected_profile_sha256: canonicalSHA(expectedProfile),
    desired_profile: desiredProfile,
    desired_profile_sha256: canonicalSHA(desiredProfile),
    expected_parent_data_sha256: canonicalSHA(
      core.metadataRepairParentData(entryParent, children, expectedProfile),
    ),
    desired_parent_data_sha256: canonicalSHA(
      core.metadataRepairParentData(entryParent, children, desiredProfile),
    ),
  };
  const unsignedManifest = {
    schema: "ZoteroParentMetadataRepairTransaction/v2",
    transaction_id: "production-vm-readback",
    generated_at: "2026-08-09T00:00:00Z",
    reviewed_source_sha256: "sha256:" + "a".repeat(64),
    source_evidence_sidecar_ref: {
      schema: "ZoteroParentMetadataRepairLiveSidecar/v1",
      file_sha256: "sha256:" + "b".repeat(64),
      content_sha256: "sha256:" + "c".repeat(64),
    },
    execution_intent: "readback_only",
    target: {
      library_id: 2,
      library_type: "group",
      library_type_id: 999999,
      library_name: "Synthetic Research Library",
      collection_id: 40,
      collection_key: "COLL0001",
      collection_path: [{key: "COLL0001", name: "Methods"}],
      require_editable: true,
      require_files_editable: false,
    },
    entry: {
      parent: entryParent,
      children,
      children_sha256: canonicalSHA(children),
      evidence_pdf_key: "PDF00001",
      duplicate_preconditions: {
        ...duplicateUnsigned,
        sha256: canonicalSHA(duplicateUnsigned),
      },
      operation,
      serializer_guard: serializerGuard,
    },
  };
  const repairManifest = {
    ...unsignedManifest,
    manifest_sha256: canonicalSHA(unsignedManifest),
  };
  const collection = {
    id: 40, key: "COLL0001", name: "Methods", parentID: null, deleted: false,
  };
  const parentItem = {
    id: 41,
    key: "PARENT01",
    itemType: "journalArticle",
    itemTypeID: 1,
    version: liveParentData.version,
    synced: true,
    deleted: false,
    isRegularItem: () => true,
    hasChanged: () => false,
    getField: field => liveParentData[field] || "",
    getCreators: () => liveParentData.creators,
    getCollections: () => [40, 41],
    getNotes: () => [51],
    getAttachments: () => [61],
    toJSON: () => JSON.parse(JSON.stringify(liveParentData)),
  };
  const noteItem = {
    id: 51, parentItemID: 41, key: "NOTE0001", version: 2,
    getNote: () => noteHTML,
    toJSON: () => JSON.parse(JSON.stringify(noteData)),
  };
  const attachmentItem = {
    id: 61,
    parentItemID: 41,
    key: "PDF00001",
    version: liveAttachmentData.version,
    attachmentContentType: "application/pdf",
    attachmentLinkMode: 1,
    getCollections: () => [],
    getFilePathAsync: async () => livePath,
    toJSON: () => JSON.parse(JSON.stringify(liveAttachmentData)),
  };
  const itemMap = new Map([[51, noteItem], [61, attachmentItem]]);
  runtime.zotero.Libraries = {
    get: () => ({
      libraryID: 2, libraryType: "group", libraryTypeID: 999999,
      name: "Synthetic Research Library", editable: true, filesEditable: false,
    }),
  };
  runtime.zotero.Collections = {
    getByLibraryAndKeyAsync: async () => collection,
    getAsync: async () => null,
  };
  runtime.zotero.Items.getByLibraryAndKeyAsync = async () => parentItem;
  runtime.zotero.Items.getAsync = async ids => ids.map(id => itemMap.get(id));
  runtime.zotero.Items.getAll = async () => [parentItem];
  runtime.zotero.ItemFields = {getID: () => 1, isValidForType: () => true};
  runtime.zotero.CreatorTypes = {getName: () => "author"};
  runtime.zotero.Attachments = {
    LINK_MODE_IMPORTED_FILE: 1,
    LINK_MODE_IMPORTED_URL: 2,
    LINK_MODE_LINKED_FILE: 3,
  };
  runtime.zotero.File.pathToFile = pathValue => ({
    isSymlink: () => false,
    exists: () => pathValue === livePath,
    isFile: () => pathValue === livePath,
  });
  const ioEvents = [];
  runtime.ioUtils.exists = async pathValue => pathValue === livePath;
  runtime.ioUtils.stat = async pathValue => {
    ioEvents.push(["stat", pathValue]);
    return {size: options.reportedSize ?? liveBytes.length};
  };
  runtime.ioUtils.read = async pathValue => {
    ioEvents.push(["read", pathValue]);
    return new Uint8Array(liveBytes);
  };
  return {...runtime, repairManifest, ioEvents, livePath, baselineBytes};
}

function manifest() {
  return {
    schema: "ZoteroParentMetadataRepairTransaction/v1",
    manifest_sha256: "sha256:" + "a".repeat(64),
    target: {library_id: 2},
    entry: {
      parent: {key: "PARENT01"},
      operation: {
        desired_profile: {
          DOI: "10.0000/synthetic.bootstrap",
          creators: [
            {
              creatorType: "author",
              firstName: "Ada",
              lastName: "Lovelace",
            },
          ],
          publicationTitle: "Journal",
          volume: "1",
          issue: "2",
          pages: "3-4",
          date: "2026",
        },
      },
    },
  };
}

function serializerGuard(postCommit = false) {
  const h = character => "sha256:" + character.repeat(64);
  return {
    profile: "zotero_managed_storage_equivalence_v1",
    parent: {
      raw_data_sha256: postCommit ? h("9") : h("1"),
      stable_nonprofile_sha256: h("2"),
      tags_raw_sha256: postCommit ? h("8") : h("3"),
      tags_set_sha256: h("4"),
      collections_raw_sha256: postCommit ? h("7") : h("5"),
      collections_set_sha256: h("6"),
    },
    children: [
      {
        key: "NOTE0001", item_type: "note", version: 2,
        raw_data_sha256: h("a"), content_sha256: h("b"),
      },
      {
        key: "PDF00001", item_type: "attachment", version: postCommit ? 9 : 5,
        raw_data_sha256: postCommit ? h("c") : h("d"),
        stable_data_sha256: h("e"),
        filename_sha256: postCommit ? h("f") : h("0"),
        storage_path_sha256: postCommit ? h("1") : h("2"),
        content_sha256: h("3"), size_bytes: 1234,
      },
    ],
    guard_sha256: postCommit ? h("4") : h("5"),
  };
}

function v2ReadbackManifest() {
  const value = manifest();
  value.schema = "ZoteroParentMetadataRepairTransaction/v2";
  value.execution_intent = "readback_only";
  value.entry.operation.expected_parent_version = 3;
  value.entry.operation.expected_parent_data_sha256 = "sha256:" + "6".repeat(64);
  value.entry.operation.desired_parent_data_sha256 = "sha256:" + "7".repeat(64);
  value.entry.operation.desired_profile_sha256 = "sha256:" + "8".repeat(64);
  value.entry.serializer_guard = serializerGuard(false);
  return value;
}

function parent(overrides = {}) {
  return {
    id: 41,
    hasChanged: () => false,
    setCreators() {},
    setField() {},
    async save() {},
    async reload() {},
    ...overrides,
  };
}

function before(parentItem) {
  return {
    stateSHA256: STATE_A,
    allSatisfied: false,
    parent: parentItem,
    publicState: {execution_profile: "db_atomic", marker: "before"},
  };
}

async function preview(testing, repairManifest, preflightForManifest) {
  return testing.dispatch(
    {action: "preview", payload: {manifest: repairManifest}},
    {preflightForManifest},
  );
}

async function apply(testing, repairManifest, previewReceipt, hooks) {
  return testing.dispatch(
    {
      action: "apply",
      payload: {
        manifest: repairManifest,
        preview_id: previewReceipt.preview_id,
        preview_token: previewReceipt.preview_token,
        state_sha256: previewReceipt.state_sha256,
      },
    },
    hooks,
  );
}

test("dirty parent fails closed at preview, transaction repeat, and immediate apply", async () => {
  const {testing} = loadBootstrap();
  const repairManifest = manifest();
  const dirty = parent({hasChanged: () => true});
  await assert.rejects(
    preview(testing, repairManifest, async () => {
      testing.assertMetadataRepairParentClean(dirty);
    }),
    /unsaved changes/,
  );

  testing.resetState();
  const clean = parent();
  const cleanBefore = before(clean);
  const previewReceipt = await preview(
    testing,
    repairManifest,
    async () => cleanBefore,
  );
  let calls = 0;
  await assert.rejects(
    apply(testing, repairManifest, previewReceipt, {
      preflightForManifest: async () => {
        calls += 1;
        if (calls === 2) testing.assertMetadataRepairParentClean(dirty);
        return cleanBefore;
      },
    }),
    error => error.commitState === "not_started",
  );

  let mutated = false;
  await assert.rejects(
    testing.applyMetadataRepair(repairManifest, {
      parent: parent({
        hasChanged: () => true,
        setCreators() {
          mutated = true;
        },
      }),
    }),
    /unsaved changes/,
  );
  assert.equal(mutated, false);
});

test("rollback uses reload, unload, and a distinct fresh cache identity", async () => {
  const {callbacks, events, testing, zotero} = loadBootstrap();
  const repairManifest = manifest();
  const cached = parent({
    async reload() {
      events.push(["reload", this.id]);
    },
  });
  const fresh = parent();
  zotero.Items.getByLibraryAndKeyAsync = async (libraryID, key) => {
    events.push(["get", libraryID, key]);
    return fresh;
  };
  zotero.DB.executeTransaction = async callback => {
    try {
      await callback();
      assert.fail("write failure was not raised");
    }
    catch (error) {
      for (const onRollback of callbacks.rollback) onRollback();
      throw error;
    }
  };
  const initial = before(cached);
  const receipt = await preview(testing, repairManifest, async () => initial);
  await assert.rejects(
    apply(testing, repairManifest, receipt, {
      preflightForManifest: async () => initial,
      applyMetadataRepair: async () => {
        throw new Error("write failed");
      },
      freshMetadataRepairFailureInspection: (item, cachedParent) => (
        testing.freshMetadataRepairFailureInspection(
          item,
          cachedParent,
          async (_manifest, freshParent) => {
            assert.equal(freshParent, fresh);
            return before(freshParent);
          },
        )
      ),
    }),
    error => error.commitState === "rolled_back",
  );
  assert.deepEqual(events, [
    ["reload", 41],
    ["unload", 41],
    ["get", 2, "PARENT01"],
  ]);
});

test("reload failure unloads stale cache and leaves rollback state unknown", async () => {
  const {callbacks, events, testing, zotero} = loadBootstrap();
  const repairManifest = manifest();
  const cached = parent({
    async reload() {
      throw new Error("reload failed");
    },
  });
  let getCalls = 0;
  zotero.Items.getByLibraryAndKeyAsync = async () => {
    getCalls += 1;
    return parent();
  };
  zotero.DB.executeTransaction = async callback => {
    try {
      await callback();
    }
    catch (error) {
      for (const onRollback of callbacks.rollback) onRollback();
      throw error;
    }
  };
  const initial = before(cached);
  const receipt = await preview(testing, repairManifest, async () => initial);
  await assert.rejects(
    apply(testing, repairManifest, receipt, {
      preflightForManifest: async () => initial,
      applyMetadataRepair: async () => {
        throw new Error("write failed");
      },
    }),
    error => error.commitState === "unknown",
  );
  assert.deepEqual(events, [["unload", 41]]);
  assert.equal(getCalls, 0);
});

test("commit callback failure is reported as committed_unverified", async () => {
  const {callbacks, testing, zotero} = loadBootstrap();
  const repairManifest = manifest();
  const cached = parent();
  const fresh = parent();
  zotero.Items.getByLibraryAndKeyAsync = async () => fresh;
  zotero.DB.executeTransaction = async callback => {
    await callback();
    for (const onCommit of callbacks.commit) onCommit();
    throw new Error("commit callback failed");
  };
  const initial = before(cached);
  const receipt = await preview(testing, repairManifest, async () => initial);
  await assert.rejects(
    apply(testing, repairManifest, receipt, {
      preflightForManifest: async () => initial,
      applyMetadataRepair: async () => [],
      freshMetadataRepairFailureInspection: (item, cachedParent) => (
        testing.freshMetadataRepairFailureInspection(
          item,
          cachedParent,
          async () => before(fresh),
        )
      ),
    }),
    error => error.commitState === "committed_unverified",
  );
});

test("v2 production readback hashes attachment bytes and accepts only bounded rename/set-order equivalence", async () => {
  const {testing, repairManifest, ioEvents, livePath} = loadProductionV2Bootstrap();
  const result = await testing.dispatch(
    {action: "readback", payload: {manifest: repairManifest}},
  );
  assert.equal(result.status, "verified");
  assert.equal(
    result.state.entry.operation.content_match,
    "zotero_managed_attachment_rename_and_set_order_equivalent",
  );
  assert.ok(result.state.entry.operation.raw_hashes.expected_guard_sha256);
  assert.ok(result.state.entry.operation.raw_hashes.observed_guard_sha256);
  assert.deepEqual(ioEvents, [["stat", livePath], ["read", livePath]]);
});

test("v2 production readback rejects byte, size, title, and version drift", async () => {
  const cases = [
    ["bytes", {liveBytes: Buffer.from("%PDF-different-metadata-evidence!\n")}, /content_sha256 drift/],
    ["size", {reportedSize: 999}, /bytes are unreadable/],
    ["title", {attachmentTitle: "Changed attachment title"}, /stable_data_sha256 drift/],
    ["parent version", {parentVersion: 2}, /parent-version regressed/],
    ["attachment version", {attachmentVersion: 4}, /version regressed/],
  ];
  for (const [label, options, pattern] of cases) {
    const {testing, repairManifest} = loadProductionV2Bootstrap(options);
    await assert.rejects(
      testing.dispatch({action: "readback", payload: {manifest: repairManifest}}),
      pattern,
      label,
    );
  }
});

test("v2 readback-only transaction rejects preview and apply before any preflight", async () => {
  const {testing} = loadBootstrap();
  for (const action of ["preview", "apply"]) {
    let preflightCalls = 0;
    const payload = action === "apply"
      ? {
        manifest: v2ReadbackManifest(),
        preview_id: "unused",
        preview_token: "unused",
        state_sha256: STATE_A,
      }
      : {manifest: v2ReadbackManifest()};
    await assert.rejects(
      testing.dispatch(
        {action, payload},
        {preflightForManifest: async () => { preflightCalls += 1; }},
      ),
      error => error.code === "readback_only",
    );
    assert.equal(preflightCalls, 0, action);
  }
});
