var ZoteroDeclarativeBridgeCore = (() => {
  "use strict";

  const KEY_RE = /^[A-Z0-9]{8}$/;
  const SHA_RE = /^sha256:[0-9a-f]{64}$/;
  const TX_RE = /^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$/;
  const OP_ORDER = new Map([
    ["ensure_collection_membership", 0],
    ["ensure_parent_short_title", 1],
    ["ensure_child_note", 2],
    ["ensure_pdf_attachment", 3],
  ]);

  function assertion(condition, message) {
    if (!condition) throw new Error(message);
  }

  function stableStringify(value) {
    if (value === null || typeof value !== "object") return JSON.stringify(value);
    if (Array.isArray(value)) return `[${value.map(stableStringify).join(",")}]`;
    return `{${Object.keys(value).sort().map(key => `${JSON.stringify(key)}:${stableStringify(value[key])}`).join(",")}}`;
  }

  function exactKeys(value, expected, label) {
    assertion(value && typeof value === "object" && !Array.isArray(value), `${label} must be an object`);
    const actual = Object.keys(value).sort();
    const wanted = [...expected].sort();
    assertion(stableStringify(actual) === stableStringify(wanted), `${label} keys differ`);
    return value;
  }

  function positiveInt(value, label, maximum = null) {
    assertion(Number.isInteger(value) && value > 0, `${label} must be a positive integer`);
    if (maximum !== null) assertion(value <= maximum, `${label} exceeds maximum`);
    return value;
  }

  function text(value, label, allowEmpty = false, maxBytes = 1048576) {
    assertion(typeof value === "string" && (allowEmpty || value.length > 0), `${label} must be a string`);
    assertion(new TextEncoder().encode(value).byteLength <= maxBytes, `${label} is too large`);
    return value;
  }

  function key(value, label) {
    assertion(typeof value === "string" && KEY_RE.test(value), `${label} is not a Zotero key`);
    return value;
  }

  function resolutionFailure(code) {
    const error = new Error("exact collection resolution failed");
    error.code = code;
    throw error;
  }

  function validateCollectionResolutionRequest(value) {
    exactKeys(value, ["library_id", "collection_key"], "collection resolution request");
    positiveInt(value.library_id, "collection resolution request.library_id");
    key(value.collection_key, "collection resolution request.collection_key");
    return value;
  }

  function resolveCollectionID(request, library, lookupResult) {
    validateCollectionResolutionRequest(request);
    if (!library || typeof library !== "object" || Array.isArray(library)) {
      resolutionFailure("library_not_found");
    }
    const observedLibraryID = Number(library.libraryID || library.id);
    if (observedLibraryID !== request.library_id) resolutionFailure("library_mismatch");
    if (String(library.libraryType) !== "group") resolutionFailure("library_not_group");
    const matches = lookupResult == null
      ? []
      : Array.isArray(lookupResult)
        ? lookupResult
        : [lookupResult];
    if (matches.length === 0) resolutionFailure("collection_not_found");
    if (matches.length !== 1) resolutionFailure("collection_ambiguous");
    const collection = matches[0];
    if (!collection || typeof collection !== "object" || collection.deleted) {
      resolutionFailure("collection_not_found");
    }
    const collectionID = Number(collection.id);
    if (
      !Number.isInteger(collectionID)
      || collectionID <= 0
      || Number(collection.libraryID) !== request.library_id
      || String(collection.key) !== request.collection_key
    ) resolutionFailure("collection_mismatch");
    return {
      status: "resolved",
      library_id: request.library_id,
      collection_key: request.collection_key,
      collection_id: collectionID,
    };
  }

  function sha(value, label) {
    assertion(typeof value === "string" && SHA_RE.test(value), `${label} is not a SHA-256 value`);
    return value;
  }

  function normalizeDOI(value) {
    return typeof value === "string"
      ? value.trim().toLowerCase().replace(/^https?:\/\/(?:dx\.)?doi\.org\//, "")
      : "";
  }

  function parentIdentity(parent, libraryID) {
    return {
      doi: normalizeDOI(parent.doi),
      item_type: parent.item_type,
      key: parent.key,
      library_id: libraryID,
      title: parent.title,
    };
  }

  function validateTarget(target) {
    exactKeys(target, [
      "library_id", "library_type", "library_type_id", "library_name",
      "collection_id", "collection_key", "collection_path", "require_editable",
      "require_files_editable",
    ], "target");
    positiveInt(target.library_id, "target.library_id");
    assertion(["group", "user"].includes(target.library_type), "target.library_type is invalid");
    positiveInt(target.library_type_id, "target.library_type_id");
    text(target.library_name, "target.library_name", false, 256);
    positiveInt(target.collection_id, "target.collection_id");
    key(target.collection_key, "target.collection_key");
    assertion(target.require_editable === true, "target.require_editable must be true");
    assertion(typeof target.require_files_editable === "boolean", "target.require_files_editable must be boolean");
    assertion(Array.isArray(target.collection_path) && target.collection_path.length > 0 && target.collection_path.length <= 32, "target.collection_path is invalid");
    const keys = [];
    target.collection_path.forEach((part, index) => {
      exactKeys(part, ["key", "name"], `target.collection_path[${index}]`);
      keys.push(key(part.key, `target.collection_path[${index}].key`));
      text(part.name, `target.collection_path[${index}].name`, false, 512);
    });
    assertion(new Set(keys).size === keys.length, "target.collection_path has duplicate keys");
    assertion(keys.at(-1) === target.collection_key, "target.collection_path leaf mismatch");
  }

  function validateParent(parent) {
    exactKeys(parent, [
      "key", "version", "item_type", "title", "doi", "identity_sha256",
      "expected_target_membership",
    ], "parent");
    key(parent.key, "parent.key");
    positiveInt(parent.version, "parent.version");
    text(parent.item_type, "parent.item_type", false, 128);
    text(parent.title, "parent.title", false, 16384);
    text(parent.doi, "parent.doi", true, 2048);
    sha(parent.identity_sha256, "parent.identity_sha256");
    assertion(typeof parent.expected_target_membership === "boolean", "parent membership baseline must be boolean");
  }

  function validateOperation(operation, parent, target, label) {
    assertion(operation && typeof operation === "object" && typeof operation.type === "string", `${label} is invalid`);
    if (operation.type === "ensure_collection_membership") {
      exactKeys(operation, ["type", "expected_present"], label);
      assertion(operation.expected_present === false && parent.expected_target_membership === false, `${label} membership baseline is invalid`);
    }
    else if (operation.type === "ensure_parent_short_title") {
      exactKeys(operation, [
        "type", "library_id", "parent_key", "expected_parent_version",
        "expected_old_value", "new_short_title",
      ], label);
      positiveInt(operation.library_id, `${label}.library_id`);
      key(operation.parent_key, `${label}.parent_key`);
      positiveInt(operation.expected_parent_version, `${label}.expected_parent_version`);
      text(operation.expected_old_value, `${label}.expected_old_value`, true, 4096);
      text(operation.new_short_title, `${label}.new_short_title`, false, 4096);
      assertion(!/[\x00-\x1f\x7f]/.test(operation.expected_old_value), `${label}.expected_old_value contains control characters`);
      assertion(!/[\x00-\x1f\x7f]/.test(operation.new_short_title), `${label}.new_short_title contains control characters`);
      assertion(operation.new_short_title === operation.new_short_title.trim(), `${label}.new_short_title must be trimmed`);
      assertion(operation.library_id === target.library_id, `${label}.library_id disagrees with target`);
      assertion(operation.parent_key === parent.key, `${label}.parent_key disagrees with parent`);
      assertion(operation.expected_parent_version === parent.version, `${label}.expected_parent_version disagrees with parent`);
    }
    else if (operation.type === "ensure_child_note") {
      exactKeys(operation, [
        "type", "note_key", "expected_note_version", "expected_old_sha256",
        "expected_child_note_keys", "new_html", "new_sha256",
      ], label);
      text(operation.new_html, `${label}.new_html`);
      assertion(operation.new_html === operation.new_html.trim(), `${label}.new_html is not storage-trimmed`);
      assertion(!/<script\b|javascript:|\son[a-z]+\s*=/i.test(operation.new_html), `${label}.new_html contains executable markup`);
      assertion(/<h1(?:\s[^>]*)?>\s*[^<\s]/i.test(operation.new_html), `${label}.new_html has no non-empty h1`);
      sha(operation.new_sha256, `${label}.new_sha256`);
      assertion(Array.isArray(operation.expected_child_note_keys), `${label}.expected_child_note_keys is not an array`);
      const noteKeys = operation.expected_child_note_keys.map((value, index) => key(value, `${label}.expected_child_note_keys[${index}]`));
      assertion(stableStringify(noteKeys) === stableStringify([...noteKeys].sort()) && new Set(noteKeys).size === noteKeys.length, `${label} note keys are not sorted and unique`);
      if (operation.note_key === null) {
        assertion(operation.expected_note_version === null && operation.expected_old_sha256 === null && noteKeys.length === 0, `${label} create baseline is invalid`);
      }
      else {
        key(operation.note_key, `${label}.note_key`);
        positiveInt(operation.expected_note_version, `${label}.expected_note_version`);
        sha(operation.expected_old_sha256, `${label}.expected_old_sha256`);
        assertion(stableStringify(noteKeys) === stableStringify([operation.note_key]), `${label} update inventory must contain one exact note`);
      }
    }
    else if (operation.type === "ensure_pdf_attachment") {
      exactKeys(operation, [
        "type", "source_path", "source_size_bytes", "source_sha256", "source_magic",
        "expected_attachments",
      ], label);
      text(operation.source_path, `${label}.source_path`, false, 16384);
      positiveInt(operation.source_size_bytes, `${label}.source_size_bytes`, 268435456);
      sha(operation.source_sha256, `${label}.source_sha256`);
      assertion(operation.source_magic === "%PDF-", `${label}.source_magic is invalid`);
      assertion(Array.isArray(operation.expected_attachments) && operation.expected_attachments.length <= 100, `${label}.expected_attachments is invalid`);
      const attachmentKeys = [];
      operation.expected_attachments.forEach((item, index) => {
        exactKeys(item, ["key", "version", "content_type", "link_mode"], `${label}.expected_attachments[${index}]`);
        attachmentKeys.push(key(item.key, `${label}.expected_attachments[${index}].key`));
        positiveInt(item.version, `${label}.expected_attachments[${index}].version`);
        text(item.content_type, `${label}.expected_attachments[${index}].content_type`, true, 256);
        text(item.link_mode, `${label}.expected_attachments[${index}].link_mode`, false, 128);
      });
      assertion(stableStringify(attachmentKeys) === stableStringify([...attachmentKeys].sort()) && new Set(attachmentKeys).size === attachmentKeys.length, `${label} attachment keys are not sorted and unique`);
    }
    else {
      throw new Error(`${label}.type is unsupported`);
    }
    return operation.type;
  }

  function validateManifest(manifest) {
    exactKeys(manifest, ["schema", "transaction_id", "generated_at", "target", "entries", "manifest_sha256"], "manifest");
    assertion(manifest.schema === "ZoteroDeclarativeTransaction/v1", "manifest schema mismatch");
    assertion(typeof manifest.transaction_id === "string" && TX_RE.test(manifest.transaction_id), "transaction_id is invalid");
    text(manifest.generated_at, "generated_at", false, 64);
    validateTarget(manifest.target);
    assertion(Array.isArray(manifest.entries) && manifest.entries.length > 0 && manifest.entries.length <= 100, "entries are invalid");
    const parentKeys = [];
    let attachmentOperations = 0;
    let databaseOperations = 0;
    manifest.entries.forEach((entry, index) => {
      exactKeys(entry, ["parent", "operations"], `entries[${index}]`);
      validateParent(entry.parent);
      parentKeys.push(entry.parent.key);
      assertion(Array.isArray(entry.operations) && entry.operations.length > 0 && entry.operations.length <= 4, `entries[${index}].operations are invalid`);
      const types = entry.operations.map((operation, opIndex) => validateOperation(operation, entry.parent, manifest.target, `entries[${index}].operations[${opIndex}]`));
      assertion(new Set(types).size === types.length, `entries[${index}] has duplicate operations`);
      assertion(stableStringify(types) === stableStringify([...types].sort((a, b) => OP_ORDER.get(a) - OP_ORDER.get(b))), `entries[${index}] operation order is not canonical`);
      attachmentOperations += types.filter(type => type === "ensure_pdf_attachment").length;
      databaseOperations += types.filter(type => type !== "ensure_pdf_attachment").length;
    });
    assertion(stableStringify(parentKeys) === stableStringify([...parentKeys].sort()) && new Set(parentKeys).size === parentKeys.length, "entries are not parent-key-sorted and unique");
    assertion(!attachmentOperations || manifest.target.require_files_editable === true, "PDF operations require files editability");
    assertion(!(attachmentOperations && databaseOperations), "PDF and database operations cannot share one transaction manifest");
    sha(manifest.manifest_sha256, "manifest.manifest_sha256");
    return true;
  }

  function planWrites(rows) {
    const pendingTypes = [];
    for (const row of rows) {
      row.decisions.forEach((decision, index) => {
        if (decision.decision === "needs_write") pendingTypes.push(row.entry.operations[index].type);
      });
    }
    const attachmentCount = pendingTypes.filter(type => type === "ensure_pdf_attachment").length;
    const databaseCount = pendingTypes.length - attachmentCount;
    assertion(!(attachmentCount && databaseCount), "live write plan mixes PDF and database operations");
    assertion(attachmentCount <= 1, "live write plan contains multiple PDF attachment mutations");
    return {
      mode: pendingTypes.length === 0 ? "none" : attachmentCount ? "single_attachment_import" : "db_atomic",
      operation_count: pendingTypes.length,
      attachment_operation_count: attachmentCount,
      database_operation_count: databaseCount,
    };
  }

  function liveKeys(items) {
    return items.map(item => item.key).sort();
  }

  function classifyMembership(operation, present) {
    assertion(operation.expected_present === false, "membership operation baseline is invalid");
    return {decision: present ? "satisfied" : "needs_write"};
  }

  function readbackMembershipSatisfied(entry, present, decisions) {
    assertion(typeof present === "boolean", "readback membership must be boolean");
    assertion(Array.isArray(entry.operations) && Array.isArray(decisions), "readback membership inputs are invalid");
    assertion(entry.operations.length === decisions.length, "readback decisions do not align with operations");
    const membershipIndex = entry.operations.findIndex(operation => operation.type === "ensure_collection_membership");
    if (membershipIndex === -1) return present === entry.parent.expected_target_membership;
    return present === true && decisions[membershipIndex].decision === "satisfied";
  }

  function classifyShortTitle(operation, observed) {
    assertion(observed.library_id === operation.library_id, "shortTitle library drift");
    assertion(observed.parent_key === operation.parent_key, "shortTitle parent-key drift");
    if (observed.value === operation.new_short_title) return {decision: "satisfied"};
    assertion(observed.item_version === operation.expected_parent_version, "shortTitle parent-version drift");
    assertion(observed.value === operation.expected_old_value, "shortTitle old-value drift");
    return {decision: "needs_write"};
  }

  function classifyNote(operation, notes) {
    const keys = liveKeys(notes);
    if (operation.note_key === null) {
      const matches = notes.filter(note => note.sha256 === operation.new_sha256);
      assertion(matches.length <= 1, "multiple child notes already match the requested content");
      if (matches.length === 1) {
        assertion(notes.length === 1, "matching child note exists beside unapproved notes");
        return {decision: "satisfied", note_key: matches[0].key};
      }
      assertion(stableStringify(keys) === stableStringify(operation.expected_child_note_keys), "child note inventory drift");
      return {decision: "needs_write", note_key: null};
    }
    const note = notes.find(item => item.key === operation.note_key);
    assertion(note, "approved child note disappeared");
    if (note.sha256 === operation.new_sha256) {
      assertion(notes.length === 1, "updated child note exists beside unapproved notes");
      return {decision: "satisfied", note_key: note.key};
    }
    assertion(stableStringify(keys) === stableStringify(operation.expected_child_note_keys), "child note inventory drift");
    assertion(note.version === operation.expected_note_version, "child note version drift");
    assertion(note.sha256 === operation.expected_old_sha256, "child note content drift");
    return {decision: "needs_write", note_key: note.key};
  }

  function classifyAttachment(operation, attachments) {
    const readable = attachments.filter(item => item.readable_pdf === true);
    const same = readable.filter(
      item => item.sha256 === operation.source_sha256 && item.direct_collection_count === 0,
    );
    const misfiledSame = readable.filter(
      item => item.sha256 === operation.source_sha256 && item.direct_collection_count !== 0,
    );
    const different = readable.filter(item => item.sha256 !== operation.source_sha256);
    assertion(misfiledSame.length === 0, "a matching PDF has direct collection membership");
    assertion(different.length === 0, "a different readable PDF already exists");
    assertion(same.length <= 1, "multiple matching PDF attachments already exist");
    if (same.length) {
      return {decision: "satisfied", attachment_keys: same.map(item => item.key).sort(), duplicate_count: Math.max(0, same.length - 1)};
    }
    const expected = new Map(operation.expected_attachments.map(item => [item.key, item]));
    assertion(attachments.length === expected.size, "attachment inventory drift");
    for (const item of attachments) {
      const baseline = expected.get(item.key);
      assertion(baseline, `unexpected attachment: ${item.key}`);
      for (const field of ["version", "content_type", "link_mode"]) {
        assertion(item[field] === baseline[field], `attachment ${item.key} ${field} drift`);
      }
    }
    return {decision: "needs_write", attachment_keys: [], duplicate_count: 0};
  }

  return {
    assertion,
    classifyAttachment,
    classifyMembership,
    classifyNote,
    classifyShortTitle,
    normalizeDOI,
    parentIdentity,
    planWrites,
    readbackMembershipSatisfied,
    resolveCollectionID,
    stableStringify,
    validateCollectionResolutionRequest,
    validateManifest,
  };
})();

if (typeof module !== "undefined" && module.exports) {
  module.exports = ZoteroDeclarativeBridgeCore;
}
