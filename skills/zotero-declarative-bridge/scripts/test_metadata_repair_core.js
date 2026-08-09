"use strict";

const assert = require("node:assert/strict");
const crypto = require("node:crypto");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");

const core = require("../assets/zotero-plugin/bridge_core.js");

const sha = value => "sha256:" + crypto.createHash("sha256").update(core.stableStringify(value)).digest("hex");
const childHash = "sha256:" + "c".repeat(64);

function profile(overrides = {}) {
  return {
    DOI: "10.0000/synthetic.old",
    creators: [],
    publicationTitle: "",
    volume: "",
    issue: "",
    pages: "",
    date: "2026",
    ...overrides,
  };
}

function fixture() {
  const expected = profile();
  const desired = profile({
    DOI: "10.0000/synthetic.new",
    creators: [
      {creatorType: "author", firstName: "Alex", lastName: "Example"},
      {creatorType: "author", firstName: "Blair", lastName: "Sample"},
    ],
    publicationTitle: "Synthetic Journal",
    volume: "7",
    issue: "2",
    pages: "10-20",
  });
  const children = [
    {key: "NOTE0001", version: 2, item_type: "note", content_sha256: "sha256:" + "b".repeat(64)},
    {
      key: "PDF00001", version: 5, item_type: "attachment",
      content_type: "application/pdf", link_mode: "imported_file",
      size_bytes: 1234, content_sha256: childHash, direct_collection_count: 0,
    },
  ];
  const parent = {
    key: "PARENT01", version: 3, item_type: "journalArticle",
    title: "Synthetic sensitivity study",
    short_title: "Synthetic setting: reviewed conclusion",
    expected_target_membership: true,
  };
  const duplicate = {
    scope: "full_library",
    desired_doi_other_parent_keys: [],
    title_year_creator_other_parent_keys: [],
  };
  duplicate.sha256 = sha(duplicate);
  const operation = {
    type: "ensure_parent_journal_metadata_v1",
    expected_parent_version: 3,
    expected_profile: expected,
    expected_profile_sha256: sha(expected),
    desired_profile: desired,
    desired_profile_sha256: sha(desired),
    expected_parent_data_sha256: sha(core.metadataRepairParentData(parent, children, expected)),
    desired_parent_data_sha256: sha(core.metadataRepairParentData(parent, children, desired)),
  };
  const manifest = {
    schema: "ZoteroParentMetadataRepairTransaction/v1",
    transaction_id: "synthetic-metadata-repair",
    generated_at: "2026-01-02T03:04:05Z",
    reviewed_source_sha256: "sha256:" + "a".repeat(64),
    source_evidence_sidecar_ref: {
      schema: "ZoteroParentMetadataRepairLiveSidecar/v1",
      file_sha256: "sha256:" + "f".repeat(64),
      content_sha256: "sha256:" + "1".repeat(64),
    },
    target: {
      library_id: 99, library_type: "group", library_type_id: 9999999,
      library_name: "Synthetic Research Library", collection_id: 40,
      collection_key: "COLL0001",
      collection_path: [
        {key: "ROOT0001", name: "Research"},
        {key: "COLL0001", name: "Methods"},
      ],
      require_editable: true, require_files_editable: false,
    },
    entry: {
      parent,
      children,
      children_sha256: sha(children),
      evidence_pdf_key: "PDF00001",
      duplicate_preconditions: duplicate,
      operation,
    },
  };
  manifest.manifest_sha256 = sha(manifest);
  return manifest;
}

test("isolated metadata schema validates without widening the old allowlist", () => {
  const manifest = fixture();
  assert.equal(core.validateMetadataRepairManifest(manifest), true);
  assert.throws(() => core.validateManifest(manifest), /manifest keys differ/);
});

test("fixed profile rejects title injection and mixed old operations", () => {
  const withTitle = fixture();
  withTitle.entry.operation.desired_profile.title = "Injected";
  withTitle.manifest_sha256 = sha({...withTitle, manifest_sha256: undefined});
  assert.throws(() => core.validateMetadataRepairManifest(withTitle), /profile keys/);

  const mixed = fixture();
  mixed.entry.operations = [{type: "ensure_child_note"}];
  assert.throws(() => core.validateMetadataRepairManifest(mixed), /entry keys/);
});

test("classifier admits only exact expected or exact desired parent data", () => {
  const manifest = fixture();
  const operation = manifest.entry.operation;
  assert.deepEqual(
    core.classifyMetadataRepair(operation, {
      parent_version: 3,
      parent_data_sha256: operation.expected_parent_data_sha256,
    }),
    {decision: "needs_write"},
  );
  assert.deepEqual(
    core.classifyMetadataRepair(operation, {
      parent_version: 4,
      parent_data_sha256: operation.desired_parent_data_sha256,
    }),
    {decision: "satisfied"},
  );
  assert.throws(
    () => core.classifyMetadataRepair(operation, {
      parent_version: 3,
      parent_data_sha256: "sha256:" + "f".repeat(64),
    }),
    /metadata content drift/,
  );
});

test("expected state still enforces the exact parent version", () => {
  const operation = fixture().entry.operation;
  assert.throws(
    () => core.classifyMetadataRepair(operation, {
      parent_version: 4,
      parent_data_sha256: operation.expected_parent_data_sha256,
    }),
    /parent-version drift/,
  );
});

test("duplicate preconditions must be empty and sealed", () => {
  const manifest = fixture();
  manifest.entry.duplicate_preconditions.desired_doi_other_parent_keys = ["OTHER001"];
  assert.throws(
    () => core.validateMetadataRepairManifest(manifest),
    /duplicate candidates/,
  );
});

test("title-year duplicate recall tolerates partial, missing, and extra creators", () => {
  const desired = core.metadataDuplicateFingerprint(
    "Synthetic sensitivity study",
    profile({
      creators: [
        {creatorType: "author", firstName: "Alex", lastName: "Example"},
        {creatorType: "author", firstName: "Blair", lastName: "Sample"},
      ],
    }),
  );
  const observed = creators => core.metadataDuplicateFingerprint(
    "Synthetic sensitivity study",
    profile({creators}),
  );
  assert.equal(core.metadataDuplicateTitleMatch(desired, observed([
    {creatorType: "author", firstName: "Alex", lastName: "Example"},
  ])), true);
  assert.equal(core.metadataDuplicateTitleMatch(desired, observed([])), true);
  assert.equal(core.metadataDuplicateTitleMatch(desired, observed([
    {creatorType: "author", firstName: "Alex", lastName: "Example"},
    {creatorType: "author", firstName: "Extra", lastName: "Editor"},
  ])), true);
  assert.equal(core.metadataDuplicateTitleMatch(desired, observed([
    {creatorType: "author", firstName: "Other", lastName: "Unrelated"},
  ])), false);
  const prefix = creators => core.metadataDuplicateFingerprint(
    "Synthetic sensitivity",
    profile({creators}),
  );
  assert.equal(core.metadataDuplicateTitleMatch(desired, prefix([
    {creatorType: "author", firstName: "Alex", lastName: "Example"},
  ])), true);
  assert.equal(core.metadataDuplicateTitleMatch(desired, prefix([])), false);
  assert.equal(core.metadataDuplicateTitleMatch(desired, prefix([
    {creatorType: "author", firstName: "Other", lastName: "Unrelated"},
  ])), false);
  const shortPrefix = core.metadataDuplicateFingerprint(
    "Synthetic",
    profile({creators: [{creatorType: "author", firstName: "Alex", lastName: "Example"}]}),
  );
  assert.equal(core.metadataDuplicateTitleMatch(desired, shortPrefix), false);
});

test("duplicate normalization matches the shared cross-language fixtures", () => {
  const fixturePath = path.resolve(
    __dirname,
    "../../repair-zotero-metadata/references/duplicate-normalization-fixtures.json",
  );
  const normalizationFixture = JSON.parse(fs.readFileSync(fixturePath, "utf8"));
  assert.equal(
    normalizationFixture.schema,
    "MetadataDuplicateNormalizationFixtures/v1",
  );
  for (const item of normalizationFixture.cases) {
    const fingerprint = core.metadataDuplicateFingerprint(item.input, profile());
    assert.equal(fingerprint.title, item.expected, item.id);
  }
});

test("dirty parent states fail closed regardless of the dirty field", () => {
  assert.equal(core.metadataRepairParentIsClean(false), true);
  for (const field of ["abstractNote", "url", "tags"]) {
    assert.equal(core.metadataRepairParentIsClean(Boolean(field)), false);
  }
  assert.throws(() => core.metadataRepairParentIsClean(null), /dirty state is unavailable/);
});

test("metadata atomic failure trusts transaction markers and fresh inspection only", () => {
  const before = "sha256:" + "1".repeat(64);
  const desired = "sha256:" + "2".repeat(64);
  const cachedDesired = {stateSHA256: desired, allSatisfied: true};
  const freshDatabaseOld = {stateSHA256: before, allSatisfied: false};
  assert.equal(cachedDesired.allSatisfied, true);
  assert.equal(core.metadataRepairCommitStateAfterFailure({
    write_attempted: true,
    db_commit_confirmed: false,
    commit_observed: false,
    rollback_observed: true,
    inspection_available: true,
    before_state_sha256: before,
    inspection_state_sha256: freshDatabaseOld.stateSHA256,
    inspection_all_satisfied: freshDatabaseOld.allSatisfied,
  }), "rolled_back");
  assert.equal(core.metadataRepairCommitStateAfterFailure({
    write_attempted: true,
    db_commit_confirmed: false,
    commit_observed: false,
    rollback_observed: true,
    inspection_available: false,
    before_state_sha256: before,
    inspection_state_sha256: null,
    inspection_all_satisfied: false,
  }), "unknown");
  assert.equal(core.metadataRepairCommitStateAfterFailure({
    write_attempted: true,
    db_commit_confirmed: false,
    commit_observed: true,
    rollback_observed: false,
    inspection_available: false,
    before_state_sha256: before,
    inspection_state_sha256: null,
    inspection_all_satisfied: false,
  }), "committed_unverified");
});
