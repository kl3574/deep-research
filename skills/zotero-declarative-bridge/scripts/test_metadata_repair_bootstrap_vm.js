"use strict";

const assert = require("node:assert/strict");
const crypto = require("node:crypto").webcrypto;
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
  const context = vm.createContext({
    __ZOTERO_DECLARATIVE_BRIDGE_TEST__: true,
    ZoteroDeclarativeBridgeCore: core,
    Zotero: zotero,
    Services: {scriptloader: {loadSubScript() {}}},
    IOUtils: {},
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
  };
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
