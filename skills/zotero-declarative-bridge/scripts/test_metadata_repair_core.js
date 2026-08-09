"use strict";

const assert = require("node:assert/strict");
const crypto = require("node:crypto");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");

const core = require("../assets/zotero-plugin/bridge_core.js");
const crossSerializerFixture = JSON.parse(fs.readFileSync(
  path.resolve(__dirname, "fixtures/metadata_cross_serializer_attachment_v1.json"),
  "utf8",
));

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

function serializerState(postCommit = false) {
  const parent = {
    key: "PARENT01", version: postCommit ? 9 : 3, itemType: "journalArticle",
    title: "Synthetic sensitivity study",
    shortTitle: "Synthetic setting: reviewed conclusion",
    abstractNote: "Bound non-profile metadata",
    DOI: postCommit ? "10.0000/synthetic.new" : "10.0000/synthetic.old",
    creators: postCommit
      ? [
        {creatorType: "author", firstName: "Alex", lastName: "Example"},
        {creatorType: "author", firstName: "Blair", lastName: "Sample"},
      ]
      : [],
    publicationTitle: postCommit ? "Synthetic Journal" : "",
    volume: postCommit ? "7" : "", issue: postCommit ? "2" : "",
    pages: postCommit ? "10-20" : "", date: "2026",
    url: "https://example.invalid/parent",
    tags: postCommit ? [{tag: "method"}, {tag: "reviewed"}] : [{tag: "reviewed"}, {tag: "method"}],
    collections: postCommit ? ["OTHER001", "COLL0001"] : ["COLL0001", "OTHER001"],
    dateAdded: "2026-01-01T00:00:00Z",
    dateModified: postCommit ? "2026-01-03T00:00:00Z" : "2026-01-01T00:00:00Z",
    relations: {},
  };
  const note = {
    key: "NOTE0001", version: 2, itemType: "note", parentItem: "PARENT01",
    note: '<div data-schema-version="9"><p>Synthetic note</p></div>', tags: [], relations: {},
  };
  const attachment = {
    key: "PDF00001", version: postCommit ? 9 : 5, itemType: "attachment",
    parentItem: "PARENT01", title: "Synthetic sensitivity study - full text",
    url: "https://example.invalid/paper.pdf", contentType: "application/pdf",
    linkMode: "imported_file", md5: "0123456789abcdef0123456789abcdef",
    mtime: 1700000000000,
    filename: postCommit
      ? "Example and Sample - 2026 - Synthetic sensitivity study.pdf"
      : "2026 - Synthetic sensitivity study.pdf",
    collections: [], tags: [], relations: {}, dateAdded: "2026-01-01T00:00:00Z",
    dateModified: "2026-01-01T00:00:00Z",
  };
  return {
    parent,
    note,
    attachment,
    storagePath: postCommit
      ? "/synthetic/storage/PDF00001/Example and Sample - 2026 - Synthetic sensitivity study.pdf"
      : "/synthetic/storage/PDF00001/2026 - Synthetic sensitivity study.pdf",
    contentHash: childHash,
    sizeBytes: 1234,
  };
}

function serializerGuardFromState(state) {
  const parentProjection = core.metadataSerializerParentProjection(state.parent);
  const noteProjection = core.metadataSerializerNoteProjection(state.note);
  const attachmentProjection = core.metadataSerializerAttachmentProjection(
    state.attachment,
    state.attachment.md5,
  );
  const unsigned = {
    profile: "zotero_managed_storage_equivalence_v2",
    projection_contract: "ZoteroMetadataCanonicalProjection/v1",
    parent: {
      raw_data_sha256: sha(parentProjection),
      stable_nonprofile_sha256: sha(core.metadataSerializerParentStableData(state.parent)),
      tags_raw_sha256: sha(parentProjection.tags),
      tags_set_sha256: sha(core.metadataSerializerSortedValues(parentProjection.tags)),
      collections_raw_sha256: sha(parentProjection.collections),
      collections_set_sha256: sha(core.metadataSerializerSortedValues(parentProjection.collections)),
    },
    children: [
      {
        key: "NOTE0001", item_type: "note", version: 2,
        raw_data_sha256: sha(noteProjection),
        content_sha256: "sha256:" + crypto.createHash("sha256").update(state.note.note).digest("hex"),
      },
      {
        key: "PDF00001", item_type: "attachment", version: state.attachment.version,
        raw_data_sha256: sha(attachmentProjection),
        stable_data_sha256: sha(core.metadataSerializerAttachmentStableData(
          state.attachment,
          state.attachment.md5,
        )),
        filename_sha256: sha(attachmentProjection.filename),
        storage_path_sha256: sha(state.storagePath),
        content_sha256: state.contentHash, size_bytes: state.sizeBytes,
      },
    ],
  };
  return {...unsigned, guard_sha256: sha(unsigned)};
}

function serializerGuard(postCommit = false) {
  return serializerGuardFromState(serializerState(postCommit));
}

test("shared anonymous fixture identifies md5 and mtime and canonicalizes both serializers", () => {
  assert.deepEqual(
    core.metadataSerializerProjectionContract(),
    {
      schema: "ZoteroMetadataCanonicalProjection/v1",
      defaults: {text: "", list: [], object: {}, boolean: false, scalar: null},
      parent: {
        item_type: "journalArticle",
        text_fields: [
          "title", "abstractNote", "publicationTitle", "volume", "issue", "pages", "date",
          "series", "seriesTitle", "seriesText", "journalAbbreviation", "language", "DOI",
          "ISSN", "PMID", "PMCID", "shortTitle", "url", "accessDate", "archive",
          "archiveLocation", "libraryCatalog", "callNumber", "rights", "extra", "citationKey",
          "partNumber", "partTitle", "place", "publisher", "section",
        ],
        list_fields: ["creators", "tags", "collections"],
        object_fields: ["relations"],
        boolean_fields: ["deleted", "inPublications"],
        stable_excluded: [
          "version", "dateModified", "tags", "collections", "DOI", "creators",
          "publicationTitle", "volume", "issue", "pages", "date",
        ],
      },
      note: {
        item_type: "note",
        text_fields: ["parentItem", "note", "dateAdded", "dateModified"],
        list_fields: ["tags", "collections"],
        object_fields: ["relations"],
        boolean_fields: ["deleted"],
        exact: true,
      },
      attachment: {
        item_type: "attachment",
        text_fields: [
          "parentItem", "title", "url", "accessDate", "linkMode", "contentType", "charset",
          "path", "filename", "note", "dateAdded", "dateModified",
        ],
        scalar_fields: ["lastRead"],
        list_fields: ["tags", "collections"],
        object_fields: ["relations"],
        boolean_fields: ["deleted"],
        supplemental_fields: ["content_md5"],
        serializer_only_fields: ["md5", "mtime"],
        stable_excluded: ["version", "filename"],
      },
    },
  );
  assert.deepEqual(crossSerializerFixture.diagnosis.local_api_only_fields, ["md5", "mtime"]);
  const stable = {};
  for (const phase of ["pre", "post"]) {
    const local = crossSerializerFixture[phase].local_api;
    const runtime = crossSerializerFixture[phase].item_to_json;
    assert.deepEqual(
      Object.keys(local).filter(field => !(field in runtime)).sort(),
      crossSerializerFixture.diagnosis.local_api_only_fields,
    );
    const localProjection = core.metadataSerializerAttachmentProjection(
      local,
      crossSerializerFixture.content_md5,
    );
    const runtimeProjection = core.metadataSerializerAttachmentProjection(
      runtime,
      crossSerializerFixture.content_md5,
    );
    assert.deepEqual(localProjection, crossSerializerFixture[phase].expected_projection);
    assert.deepEqual(runtimeProjection, crossSerializerFixture[phase].expected_projection);
    stable[phase] = core.metadataSerializerAttachmentStableData(
      runtime,
      crossSerializerFixture.content_md5,
    );
  }
  assert.deepEqual(stable.pre, stable.post);
});

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

test("v2 classifier limits post-commit equivalence to Zotero-managed rename and set order", () => {
  const operation = fixture().entry.operation;
  const expected = serializerGuard(false);
  const observed = serializerGuard(true);
  const decision = core.classifyMetadataRepairV2(
    operation,
    expected,
    {
      parent_version: 9,
      parent_data_sha256: "sha256:" + "9".repeat(64),
      profile_sha256: operation.desired_profile_sha256,
      serializer_guard: observed,
    },
    true,
  );
  assert.equal(decision.decision, "satisfied");
  assert.equal(
    decision.content_match,
    "zotero_managed_attachment_rename_and_set_order_equivalent",
  );
  assert.equal(decision.raw_hashes.expected_guard_sha256, expected.guard_sha256);
  assert.equal(decision.raw_hashes.observed_guard_sha256, observed.guard_sha256);
  assert.throws(
    () => core.classifyMetadataRepairV2(
      operation,
      expected,
      {
        parent_version: 9,
        parent_data_sha256: "sha256:" + "9".repeat(64),
        profile_sha256: operation.desired_profile_sha256,
        serializer_guard: observed,
      },
      false,
    ),
    /metadata content drift|serializer content drift/,
  );
});

test("v2 equivalence rejects stable attachment, note, byte, and tag-member drift", () => {
  const expected = serializerGuard(false);
  const operation = fixture().entry.operation;
  const classify = observed => core.classifyMetadataRepairV2(
    operation,
    expected,
    {
      parent_version: 9,
      parent_data_sha256: "sha256:" + "9".repeat(64),
      profile_sha256: operation.desired_profile_sha256,
      serializer_guard: observed,
    },
    true,
  );

  const changedValues = {
    title: "Changed attachment title",
    url: "https://example.invalid/other.pdf",
    linkMode: "imported_url",
    contentType: "text/html",
    md5: "f".repeat(32),
  };
  for (const [field, value] of Object.entries(changedValues)) {
    const state = serializerState(true);
    state.attachment[field] = value;
    const observed = serializerGuardFromState(state);
    assert.throws(() => classify(observed), new RegExp(`stable_data_sha256 drift`), field);
  }

  for (const field of ["tags", "collections"]) {
    const state = serializerState(true);
    state.attachment[field].push(field === "tags" ? {tag: "new-member"} : "EXTRA001");
    assert.throws(
      () => classify(serializerGuardFromState(state)),
      /stable_data_sha256 drift/,
      field,
    );
  }

  const bytesState = serializerState(true);
  bytesState.contentHash = "sha256:" + "a".repeat(64);
  const bytes = serializerGuardFromState(bytesState);
  assert.throws(() => classify(bytes), /content_sha256 drift/);

  const noteState = serializerState(true);
  noteState.note.note = "Changed note";
  const note = serializerGuardFromState(noteState);
  assert.throws(() => classify(note), /note content or metadata drift/);

  const tagsState = serializerState(true);
  tagsState.parent.tags.push({tag: "new-member"});
  const tags = serializerGuardFromState(tagsState);
  assert.throws(() => classify(tags), /tags member drift/);
});

test("v2 manifest is isolated while v1 remains exact and unchanged", () => {
  const manifest = fixture();
  manifest.schema = "ZoteroParentMetadataRepairTransaction/v2";
  manifest.execution_intent = "repair";
  const guard = serializerGuard(false);
  guard.children[0].content_sha256 = manifest.entry.children[0].content_sha256;
  guard.guard_sha256 = sha({...guard, guard_sha256: undefined});
  manifest.entry.serializer_guard = guard;
  manifest.manifest_sha256 = sha({...manifest, manifest_sha256: undefined});
  assert.equal(core.validateMetadataRepairManifest(manifest), true);

  const legacy = fixture();
  assert.equal(core.validateMetadataRepairManifest(legacy), true);
  legacy.entry.serializer_guard = guard;
  assert.throws(() => core.validateMetadataRepairManifest(legacy), /entry keys differ/);
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

test("v2 post and readback states reject a regressed parent version", () => {
  const operation = fixture().entry.operation;
  const expected = serializerGuard(false);
  assert.throws(
    () => core.classifyMetadataRepairV2(
      operation,
      expected,
      {
        parent_version: operation.expected_parent_version - 1,
        parent_data_sha256: operation.desired_parent_data_sha256,
        profile_sha256: operation.desired_profile_sha256,
        serializer_guard: expected,
      },
      true,
    ),
    /parent-version regressed/,
  );
  assert.throws(
    () => core.classifyMetadataRepairV2(
      operation,
      expected,
      {
        parent_version: operation.expected_parent_version - 1,
        parent_data_sha256: "sha256:" + "9".repeat(64),
        profile_sha256: operation.desired_profile_sha256,
        serializer_guard: serializerGuard(true),
      },
      true,
    ),
    /parent-version regressed/,
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
