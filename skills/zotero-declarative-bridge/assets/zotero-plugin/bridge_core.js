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
  const METADATA_REPAIR_SCHEMA = "ZoteroParentMetadataRepairTransaction/v1";
  const METADATA_REPAIR_SCHEMA_V2 = "ZoteroParentMetadataRepairTransaction/v2";
  const METADATA_REPAIR_OPERATION = "ensure_parent_journal_metadata_v1";
  const METADATA_DUPLICATE_TITLE_PREFIX_MIN_CHARS = 20;
  const METADATA_PROFILE_FIELDS = [
    "DOI", "creators", "publicationTitle", "volume", "issue", "pages", "date",
  ];
  const METADATA_SERIALIZER_GUARD_PROFILE = "zotero_managed_storage_equivalence_v1";
  const METADATA_SERIALIZER_PARENT_EXCLUDED_FIELDS = new Set([
    "DOI", "collections", "creators", "date", "dateModified", "issue", "pages",
    "publicationTitle", "tags", "version", "volume",
  ]);
  const METADATA_SERIALIZER_ATTACHMENT_ALLOWED_FIELDS = new Set(["filename", "version"]);
  const STORAGE_BLOCK_TAGS = new Set([
    "blockquote", "div", "h1", "h2", "h3", "h4", "h5", "h6", "li",
    "ol", "p", "pre", "table", "tbody", "td", "th", "thead", "tr", "ul",
  ]);
  const STORAGE_ROOT_ATTRIBUTES = new Set(["data-citation-items", "data-schema-version"]);

  function assertion(condition, message) {
    if (!condition) throw new Error(message);
  }

  function stableStringify(value) {
    if (value === null || typeof value !== "object") return JSON.stringify(value);
    if (Array.isArray(value)) return `[${value.map(stableStringify).join(",")}]`;
    return `{${Object.keys(value).sort().map(key => `${JSON.stringify(key)}:${stableStringify(value[key])}`).join(",")}}`;
  }

  function domAttributes(node) {
    const attributes = Array.from(node.attributes || []).map(attribute => {
      assertion(attribute && typeof attribute.name === "string", "note DOM attribute is invalid");
      return [attribute.name.toLowerCase(), String(attribute.value)];
    });
    attributes.sort((left, right) => left[0].localeCompare(right[0]) || left[1].localeCompare(right[1]));
    for (let index = 1; index < attributes.length; index++) {
      assertion(attributes[index - 1][0] !== attributes[index][0], "note DOM has duplicate attributes");
    }
    return attributes;
  }

  function elementTag(node) {
    assertion(node && node.nodeType === 1 && typeof node.tagName === "string", "note DOM element is invalid");
    return node.tagName.toLowerCase();
  }

  function hasFormattingLineBreak(value) {
    return /[\r\n]/.test(value);
  }

  function blockElement(node) {
    return node && node.nodeType === 1 && STORAGE_BLOCK_TAGS.has(elementTag(node));
  }

  function normalizedStorageText(value, parentTag, siblings, index, insideMath) {
    if (insideMath || !hasFormattingLineBreak(value) || !STORAGE_BLOCK_TAGS.has(parentTag)) return value;
    if (/^[\t\r\n ]+$/.test(value)) {
      const previous = index > 0 ? siblings[index - 1] : null;
      const next = index + 1 < siblings.length ? siblings[index + 1] : null;
      if (index === 0 || index === siblings.length - 1 || blockElement(previous) || blockElement(next)) return null;
      return value;
    }
    let normalized = value;
    if (index === 0) normalized = normalized.replace(/^(?:[\t ]*\r?\n)+[\t\r\n ]*/, "");
    if (index === siblings.length - 1) normalized = normalized.replace(/[\t ]*(?:\r?\n[\t ]*)+$/, "");
    return normalized;
  }

  function noteStorageDOMFingerprint(root) {
    const rootTag = elementTag(root);
    const rootAttributes = domAttributes(root);
    assertion(rootTag === "div", "note DOM root must be div");
    assertion(
      rootAttributes.some(([name, value]) => name === "data-schema-version" && value === "9"),
      "note DOM root must use data-schema-version=9",
    );
    assertion(
      rootAttributes.every(([name]) => STORAGE_ROOT_ATTRIBUTES.has(name)),
      "note DOM root has unsupported attributes",
    );
    const tokens = [];
    const visit = (node, insideMath = false) => {
      if (node.nodeType === 3) {
        assertion(typeof node.nodeValue === "string", "note DOM text is invalid");
        tokens.push(["text", node.nodeValue]);
        return;
      }
      const tag = elementTag(node);
      const attributes = domAttributes(node);
      const classValue = (attributes.find(([name]) => name === "class") || [null, ""])[1];
      const hasMathClass = classValue.split(/\s+/).filter(Boolean).includes("math");
      if (hasMathClass) {
        assertion(tag === "pre" || tag === "span", "math class is allowed only on pre or span");
        assertion(
          attributes.length === 1 && attributes[0][0] === "class" && attributes[0][1] === "math",
          "math node attributes are invalid",
        );
      }
      assertion(!insideMath || node.nodeType === 3, "math nodes must contain text only");
      tokens.push(["start", tag, attributes]);
      const children = Array.from(node.childNodes || []);
      for (let index = 0; index < children.length; index++) {
        const child = children[index];
        if (child.nodeType === 3) {
          assertion(typeof child.nodeValue === "string", "note DOM text is invalid");
          const value = normalizedStorageText(child.nodeValue, tag, children, index, hasMathClass || insideMath);
          if (value !== null) tokens.push(["text", value]);
        }
        else {
          assertion(child.nodeType === 1, "note DOM contains an unsupported node");
          assertion(!hasMathClass && !insideMath, "math nodes must contain text only");
          visit(child, false);
        }
      }
      tokens.push(["end", tag]);
    };
    visit(root);
    return stableStringify(tokens);
  }

  function noteStorageHTMLFingerprint(noteHTML, DOMParserConstructor) {
    assertion(typeof noteHTML === "string", "note HTML is invalid");
    assertion(typeof DOMParserConstructor === "function", "DOMParser is unavailable");
    const document = new DOMParserConstructor().parseFromString(noteHTML, "text/html");
    assertion(document && document.body, "note DOM document is invalid");
    const parserErrors = document.getElementsByTagName("parsererror");
    assertion(
      parserErrors && typeof parserErrors.length === "number" && parserErrors.length === 0,
      "note DOM parse failed",
    );
    const bodyNodes = Array.from(document.body.childNodes || []);
    const roots = bodyNodes.filter(node => node && node.nodeType === 1);
    assertion(roots.length === 1, "note DOM must have exactly one root element");
    assertion(
      bodyNodes.every(node => node === roots[0] || (
        node && node.nodeType === 3 && typeof node.nodeValue === "string" && !node.nodeValue.trim()
      )),
      "note DOM contains content outside its root",
    );
    return noteStorageDOMFingerprint(roots[0]);
  }

  function commitStateAfterFailure(context) {
    assertion(context && typeof context === "object", "commit-state context is invalid");
    if (context.write_attempted !== true) return "not_started";
    if (context.execution_profile === "db_atomic") {
      if (context.db_commit_confirmed === true) return "committed_unverified";
      if (context.inspection_available !== true) return "unknown";
      if (context.inspection_state_sha256 === context.before_state_sha256) return "rolled_back";
      if (context.inspection_all_satisfied === true) return "committed";
      return "partial_commit";
    }
    if (context.execution_profile === "single_attachment_import") {
      if (context.inspection_available === true && context.inspection_all_satisfied === true) return "committed";
      if (context.created_attachment_count > 0) return "committed_unverified";
    }
    return "unknown";
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

  function versionEvidence(observedVersion, synced, preconditionVersion = null) {
    positiveInt(observedVersion, "observed version");
    assertion(typeof synced === "boolean", "version synced flag must be boolean");
    if (preconditionVersion !== null) positiveInt(preconditionVersion, "precondition version");
    return {
      observed_version: observedVersion,
      precondition_version: preconditionVersion,
      current_synced_version: synced ? observedVersion : null,
      sync_status: synced ? "synced" : "locally_modified_pending_sync",
    };
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

  function validateMetadataProfile(profile, label) {
    exactKeys(profile, METADATA_PROFILE_FIELDS, label);
    text(profile.DOI, `${label}.DOI`, true, 2048);
    assertion(
      !profile.DOI || (
        profile.DOI === normalizeDOI(profile.DOI)
        && /^10\.\d{4,9}\/\S+$/.test(profile.DOI)
      ),
      `${label}.DOI is not canonical`,
    );
    assertion(Array.isArray(profile.creators) && profile.creators.length <= 64, `${label}.creators is invalid`);
    const creatorFingerprints = [];
    profile.creators.forEach((creator, index) => {
      exactKeys(creator, ["creatorType", "firstName", "lastName"], `${label}.creators[${index}]`);
      assertion(creator.creatorType === "author", `${label}.creators[${index}].creatorType must be author`);
      text(creator.firstName, `${label}.creators[${index}].firstName`, false, 4096);
      text(creator.lastName, `${label}.creators[${index}].lastName`, false, 4096);
      creatorFingerprints.push(stableStringify(creator));
    });
    assertion(new Set(creatorFingerprints).size === creatorFingerprints.length, `${label}.creators contains duplicates`);
    for (const field of ["publicationTitle", "volume", "issue", "pages", "date"]) {
      text(profile[field], `${label}.${field}`, true, 4096);
      assertion(!profile[field] || profile[field] === profile[field].trim(), `${label}.${field} must be trimmed`);
    }
    return profile;
  }

  function validateMetadataChildren(children, label) {
    assertion(Array.isArray(children) && children.length > 0 && children.length <= 100, `${label} is invalid`);
    const keys = [];
    children.forEach((child, index) => {
      const childLabel = `${label}[${index}]`;
      assertion(child && typeof child === "object", `${childLabel} is invalid`);
      if (child.item_type === "note") {
        exactKeys(child, ["key", "version", "item_type", "content_sha256"], childLabel);
      }
      else if (child.item_type === "attachment") {
        exactKeys(child, [
          "key", "version", "item_type", "content_type", "link_mode", "size_bytes",
          "content_sha256", "direct_collection_count",
        ], childLabel);
        text(child.content_type, `${childLabel}.content_type`, false, 256);
        assertion(["imported_file", "imported_url", "linked_file"].includes(child.link_mode), `${childLabel}.link_mode is unsupported`);
        positiveInt(child.size_bytes, `${childLabel}.size_bytes`, 268435456);
        assertion(Number.isInteger(child.direct_collection_count) && child.direct_collection_count >= 0, `${childLabel}.direct_collection_count is invalid`);
      }
      else assertion(false, `${childLabel}.item_type is unsupported`);
      keys.push(key(child.key, `${childLabel}.key`));
      positiveInt(child.version, `${childLabel}.version`);
      sha(child.content_sha256, `${childLabel}.content_sha256`);
    });
    assertion(stableStringify(keys) === stableStringify([...keys].sort()) && new Set(keys).size === keys.length, `${label} is not key-sorted and unique`);
    return children;
  }

  function metadataRepairParentData(parent, children, profile) {
    return {
      key: parent.key,
      item_type: parent.item_type,
      title: parent.title,
      short_title: parent.short_title,
      target_membership: parent.expected_target_membership,
      profile,
      children,
    };
  }

  function metadataSerializerSortedValues(values) {
    assertion(Array.isArray(values), "metadata serializer set input must be an array");
    return values.map(value => JSON.parse(JSON.stringify(value))).sort((left, right) => {
      const leftBytes = new TextEncoder().encode(stableStringify(left));
      const rightBytes = new TextEncoder().encode(stableStringify(right));
      const length = Math.min(leftBytes.length, rightBytes.length);
      for (let index = 0; index < length; index++) {
        if (leftBytes[index] !== rightBytes[index]) return leftBytes[index] - rightBytes[index];
      }
      return leftBytes.length - rightBytes.length;
    });
  }

  function metadataSerializerParentStableData(data) {
    assertion(data && typeof data === "object" && !Array.isArray(data), "metadata serializer parent data is invalid");
    return Object.fromEntries(
      Object.entries(data)
        .filter(([field]) => !METADATA_SERIALIZER_PARENT_EXCLUDED_FIELDS.has(field))
        .map(([field, value]) => [field, JSON.parse(JSON.stringify(value))]),
    );
  }

  function metadataSerializerAttachmentStableData(data) {
    assertion(data && typeof data === "object" && !Array.isArray(data), "metadata serializer attachment data is invalid");
    return Object.fromEntries(
      Object.entries(data)
        .filter(([field]) => !METADATA_SERIALIZER_ATTACHMENT_ALLOWED_FIELDS.has(field))
        .map(([field, value]) => [field, JSON.parse(JSON.stringify(value))]),
    );
  }

  function validateMetadataSerializerGuard(guard, label) {
    exactKeys(guard, ["profile", "parent", "children", "guard_sha256"], label);
    assertion(guard.profile === METADATA_SERIALIZER_GUARD_PROFILE, `${label}.profile is unsupported`);
    exactKeys(guard.parent, [
      "raw_data_sha256", "stable_nonprofile_sha256", "tags_raw_sha256",
      "tags_set_sha256", "collections_raw_sha256", "collections_set_sha256",
    ], `${label}.parent`);
    for (const [field, value] of Object.entries(guard.parent)) sha(value, `${label}.parent.${field}`);
    assertion(Array.isArray(guard.children) && guard.children.length > 0 && guard.children.length <= 100, `${label}.children is invalid`);
    const keys = [];
    guard.children.forEach((child, index) => {
      const childLabel = `${label}.children[${index}]`;
      assertion(child && typeof child === "object" && !Array.isArray(child), `${childLabel} is invalid`);
      if (child.item_type === "note") {
        exactKeys(child, ["key", "item_type", "version", "raw_data_sha256", "content_sha256"], childLabel);
        sha(child.content_sha256, `${childLabel}.content_sha256`);
      }
      else if (child.item_type === "attachment") {
        exactKeys(child, [
          "key", "item_type", "version", "raw_data_sha256", "stable_data_sha256",
          "filename_sha256", "storage_path_sha256", "content_sha256", "size_bytes",
        ], childLabel);
        positiveInt(child.size_bytes, `${childLabel}.size_bytes`, 268435456);
        for (const field of [
          "stable_data_sha256", "filename_sha256", "storage_path_sha256", "content_sha256",
        ]) sha(child[field], `${childLabel}.${field}`);
      }
      else assertion(false, `${childLabel}.item_type is unsupported`);
      keys.push(key(child.key, `${childLabel}.key`));
      positiveInt(child.version, `${childLabel}.version`);
      sha(child.raw_data_sha256, `${childLabel}.raw_data_sha256`);
    });
    assertion(stableStringify(keys) === stableStringify([...keys].sort()) && new Set(keys).size === keys.length, `${label}.children is not key-sorted and unique`);
    sha(guard.guard_sha256, `${label}.guard_sha256`);
    return guard;
  }

  function metadataSerializerRawHashes(expected, observed) {
    return {
      expected_guard_sha256: expected.guard_sha256,
      observed_guard_sha256: observed.guard_sha256,
      parent: {
        expected_raw_data_sha256: expected.parent.raw_data_sha256,
        observed_raw_data_sha256: observed.parent.raw_data_sha256,
        expected_tags_raw_sha256: expected.parent.tags_raw_sha256,
        observed_tags_raw_sha256: observed.parent.tags_raw_sha256,
        expected_collections_raw_sha256: expected.parent.collections_raw_sha256,
        observed_collections_raw_sha256: observed.parent.collections_raw_sha256,
      },
      children: expected.children.map((baseline, index) => {
        const current = observed.children[index];
        const result = {
          key: baseline.key,
          expected_raw_data_sha256: baseline.raw_data_sha256,
          observed_raw_data_sha256: current.raw_data_sha256,
        };
        if (baseline.item_type === "attachment") {
          result.expected_filename_sha256 = baseline.filename_sha256;
          result.observed_filename_sha256 = current.filename_sha256;
          result.expected_storage_path_sha256 = baseline.storage_path_sha256;
          result.observed_storage_path_sha256 = current.storage_path_sha256;
        }
        return result;
      }),
    };
  }

  function classifyMetadataSerializerGuard(expected, observed, allowEquivalent) {
    validateMetadataSerializerGuard(expected, "expected metadata serializer guard");
    validateMetadataSerializerGuard(observed, "observed metadata serializer guard");
    assertion(typeof allowEquivalent === "boolean", "metadata serializer equivalence flag is invalid");
    assertion(
      expected.parent.stable_nonprofile_sha256 === observed.parent.stable_nonprofile_sha256,
      "metadata parent non-profile drift",
    );
    let parentRawSetsExact = true;
    for (const field of ["tags", "collections"]) {
      assertion(
        expected.parent[`${field}_set_sha256`] === observed.parent[`${field}_set_sha256`],
        `metadata parent ${field} member drift`,
      );
      parentRawSetsExact = parentRawSetsExact
        && expected.parent[`${field}_raw_sha256`] === observed.parent[`${field}_raw_sha256`];
    }
    assertion(expected.children.length === observed.children.length, "metadata child topology drift");
    let childrenRawExact = true;
    expected.children.forEach((baseline, index) => {
      const current = observed.children[index];
      assertion(
        baseline.key === current.key && baseline.item_type === current.item_type,
        "metadata child key or type drift",
      );
      if (baseline.item_type === "note") {
        assertion(stableStringify(baseline) === stableStringify(current), "metadata note content or metadata drift");
        return;
      }
      for (const field of ["stable_data_sha256", "content_sha256", "size_bytes"]) {
        assertion(baseline[field] === current[field], `metadata attachment ${baseline.key} ${field} drift`);
      }
      assertion(current.version >= baseline.version, `metadata attachment ${baseline.key} version regressed`);
      const rawExact = [
        "version", "raw_data_sha256", "filename_sha256", "storage_path_sha256",
      ].every(field => baseline[field] === current[field]);
      childrenRawExact = childrenRawExact && rawExact;
    });
    const exact = parentRawSetsExact && childrenRawExact;
    assertion(exact || allowEquivalent, "metadata serializer content drift");
    return {
      content_match: exact
        ? "exact"
        : "zotero_managed_attachment_rename_and_set_order_equivalent",
      raw_hashes: metadataSerializerRawHashes(expected, observed),
    };
  }

  function validateMetadataTransition(expected, desired) {
    const changed = METADATA_PROFILE_FIELDS.filter(field => stableStringify(expected[field]) !== stableStringify(desired[field]));
    assertion(changed.length > 0, "metadata repair profiles are unchanged");
    for (const field of changed) {
      if (field === "creators") {
        assertion(expected.creators.length === 0 && desired.creators.length > 0, "creators may only be filled from empty in v1");
      }
      else {
        assertion(Boolean(desired[field]), `${field} cannot be cleared`);
        if (["publicationTitle", "volume", "issue", "pages"].includes(field)) {
          assertion(!expected[field], `${field} may only be filled from empty in v1`);
        }
      }
    }
  }

  function validateMetadataRepairManifest(manifest) {
    const isV2 = manifest && manifest.schema === METADATA_REPAIR_SCHEMA_V2;
    exactKeys(manifest, [
      "schema", "transaction_id", "generated_at", "reviewed_source_sha256",
      "source_evidence_sidecar_ref", "target", "entry", "manifest_sha256",
      ...(isV2 ? ["execution_intent"] : []),
    ], "metadata repair manifest");
    assertion([METADATA_REPAIR_SCHEMA, METADATA_REPAIR_SCHEMA_V2].includes(manifest.schema), "metadata repair manifest schema mismatch");
    if (isV2) assertion(["repair", "readback_only"].includes(manifest.execution_intent), "metadata repair execution_intent is invalid");
    assertion(typeof manifest.transaction_id === "string" && TX_RE.test(manifest.transaction_id), "metadata repair transaction_id is invalid");
    text(manifest.generated_at, "metadata repair generated_at", false, 64);
    sha(manifest.reviewed_source_sha256, "metadata repair reviewed_source_sha256");
    const sidecarRef = exactKeys(manifest.source_evidence_sidecar_ref, [
      "schema", "file_sha256", "content_sha256",
    ], "metadata repair source_evidence_sidecar_ref");
    assertion(
      sidecarRef.schema === "ZoteroParentMetadataRepairLiveSidecar/v1",
      "metadata repair source evidence sidecar schema is unsupported",
    );
    sha(sidecarRef.file_sha256, "metadata repair source evidence sidecar file_sha256");
    sha(sidecarRef.content_sha256, "metadata repair source evidence sidecar content_sha256");
    validateTarget(manifest.target);
    const entry = exactKeys(manifest.entry, [
      "parent", "children", "children_sha256", "evidence_pdf_key",
      "duplicate_preconditions", "operation", ...(isV2 ? ["serializer_guard"] : []),
    ], "metadata repair entry");
    const parent = exactKeys(entry.parent, [
      "key", "version", "item_type", "title", "short_title", "expected_target_membership",
    ], "metadata repair parent");
    key(parent.key, "metadata repair parent.key");
    positiveInt(parent.version, "metadata repair parent.version");
    assertion(parent.item_type === "journalArticle", "metadata repair parent must be journalArticle");
    text(parent.title, "metadata repair parent.title", false, 16384);
    text(parent.short_title, "metadata repair parent.short_title", true, 4096);
    assertion(parent.expected_target_membership === true, "metadata repair parent membership must be true");
    const children = validateMetadataChildren(entry.children, "metadata repair children");
    if (isV2) {
      const guard = validateMetadataSerializerGuard(entry.serializer_guard, "metadata repair serializer_guard");
      assertion(
        stableStringify(guard.children.map(child => [child.key, child.item_type, child.version]))
          === stableStringify(children.map(child => [child.key, child.item_type, child.version])),
        "metadata repair serializer guard child baseline mismatch",
      );
      children.forEach((child, index) => {
        assertion(
          child.content_sha256 === guard.children[index].content_sha256,
          "metadata repair serializer guard child content mismatch",
        );
        if (child.item_type === "attachment") {
          assertion(
            child.size_bytes === guard.children[index].size_bytes,
            "metadata repair serializer guard attachment size mismatch",
          );
        }
      });
    }
    sha(entry.children_sha256, "metadata repair children_sha256");
    const evidencePDFKey = key(entry.evidence_pdf_key, "metadata repair evidence_pdf_key");
    assertion(children.filter(child => child.key === evidencePDFKey && child.item_type === "attachment" && child.content_type === "application/pdf").length === 1, "metadata repair evidence PDF binding is invalid");
    const duplicate = exactKeys(entry.duplicate_preconditions, [
      "scope", "desired_doi_other_parent_keys", "title_year_creator_other_parent_keys", "sha256",
    ], "metadata repair duplicate_preconditions");
    assertion(duplicate.scope === "full_library", "metadata repair duplicate scope is invalid");
    for (const field of ["desired_doi_other_parent_keys", "title_year_creator_other_parent_keys"]) {
      assertion(Array.isArray(duplicate[field]), `metadata repair ${field} is invalid`);
      duplicate[field].forEach((value, index) => key(value, `metadata repair ${field}[${index}]`));
      assertion(duplicate[field].length === 0, "metadata repair contains duplicate candidates");
    }
    sha(duplicate.sha256, "metadata repair duplicate_preconditions.sha256");
    const operation = exactKeys(entry.operation, [
      "type", "expected_parent_version", "expected_profile", "expected_profile_sha256",
      "desired_profile", "desired_profile_sha256", "expected_parent_data_sha256",
      "desired_parent_data_sha256",
    ], "metadata repair operation");
    assertion(operation.type === METADATA_REPAIR_OPERATION, "metadata repair operation type is invalid");
    positiveInt(operation.expected_parent_version, "metadata repair expected_parent_version");
    assertion(operation.expected_parent_version === parent.version, "metadata repair parent-version binding is invalid");
    validateMetadataProfile(operation.expected_profile, "metadata repair expected profile");
    validateMetadataProfile(operation.desired_profile, "metadata repair desired profile");
    validateMetadataTransition(operation.expected_profile, operation.desired_profile);
    for (const field of [
      "expected_profile_sha256", "desired_profile_sha256", "expected_parent_data_sha256",
      "desired_parent_data_sha256",
    ]) sha(operation[field], `metadata repair operation.${field}`);
    sha(manifest.manifest_sha256, "metadata repair manifest_sha256");
    return true;
  }

  function classifyMetadataRepair(operation, observed) {
    if (observed.parent_data_sha256 === operation.desired_parent_data_sha256) return {decision: "satisfied"};
    assertion(observed.parent_data_sha256 === operation.expected_parent_data_sha256, "metadata content drift");
    assertion(observed.parent_version === operation.expected_parent_version, "metadata parent-version drift");
    return {decision: "needs_write"};
  }

  function classifyMetadataRepairV2(operation, expectedGuard, observed, allowEquivalent) {
    const desired = observed.parent_data_sha256 === operation.desired_parent_data_sha256;
    const expected = observed.parent_data_sha256 === operation.expected_parent_data_sha256;
    if (desired) {
      assertion(observed.parent_version >= operation.expected_parent_version, "metadata parent-version regressed");
      const match = classifyMetadataSerializerGuard(expectedGuard, observed.serializer_guard, allowEquivalent);
      return {decision: "satisfied", ...match};
    }
    if (expected) {
      classifyMetadataSerializerGuard(expectedGuard, observed.serializer_guard, false);
      assertion(observed.parent_version === operation.expected_parent_version, "metadata parent-version drift");
      return {decision: "needs_write"};
    }
    assertion(
      allowEquivalent && observed.profile_sha256 === operation.desired_profile_sha256,
      "metadata content drift",
    );
    assertion(observed.parent_version >= operation.expected_parent_version, "metadata parent-version regressed");
    const match = classifyMetadataSerializerGuard(expectedGuard, observed.serializer_guard, true);
    assertion(match.content_match !== "exact", "metadata content drift");
    return {decision: "satisfied", ...match};
  }

  function normalizeMetadataDuplicateText(value) {
    return String(value || "").normalize("NFKD").toLowerCase()
      .replace(/\p{M}/gu, "").replace(/[^\p{L}\p{N}]+/gu, "");
  }

  function metadataDuplicateFingerprint(title, profile) {
    const yearMatch = String(profile.date || "").match(/(?:^|\D)(\d{4})(?:\D|$)/);
    return {
      title: normalizeMetadataDuplicateText(title),
      year: yearMatch ? yearMatch[1] : "",
      creators: profile.creators.map(creator => normalizeMetadataDuplicateText(creator.lastName)).sort(),
    };
  }

  function metadataDuplicateTitleMatch(desired, observed) {
    const desiredCreators = new Set(desired.creators.filter(Boolean));
    const observedCreators = new Set(observed.creators.filter(Boolean));
    const creatorOverlap = desiredCreators.size > 0 && observedCreators.size > 0
      && [...desiredCreators].some(creator => observedCreators.has(creator));
    const titleExact = Boolean(desired.title) && desired.title === observed.title;
    const shorterTitleLength = Math.min(
      Array.from(desired.title || "").length,
      Array.from(observed.title || "").length,
    );
    const titlePrefixRelated = Boolean(desired.title) && Boolean(observed.title)
      && !titleExact
      && shorterTitleLength >= METADATA_DUPLICATE_TITLE_PREFIX_MIN_CHARS
      && (desired.title.startsWith(observed.title) || observed.title.startsWith(desired.title));
    const titleCreatorRelated = (
      titleExact && (desiredCreators.size === 0 || observedCreators.size === 0 || creatorOverlap)
    ) || (titlePrefixRelated && creatorOverlap);
    return titleCreatorRelated && Boolean(desired.year) && desired.year === observed.year;
  }

  function metadataRepairParentIsClean(hasChanged) {
    assertion(typeof hasChanged === "boolean", "metadata repair dirty state is unavailable");
    return hasChanged === false;
  }

  function metadataRepairCommitStateAfterFailure(context) {
    assertion(context && typeof context === "object", "metadata repair commit-state context is invalid");
    if (context.write_attempted !== true) return "not_started";
    if (context.commit_observed === true || context.db_commit_confirmed === true) {
      return context.inspection_available === true && context.inspection_all_satisfied === true
        ? "committed"
        : "committed_unverified";
    }
    if (context.rollback_observed === true) {
      return context.inspection_available === true
        && context.inspection_state_sha256 === context.before_state_sha256
        ? "rolled_back"
        : "unknown";
    }
    return "unknown";
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
    const contentMatch = note => {
      if (note.sha256 === operation.new_sha256) return "exact";
      if (
        typeof operation.new_storage_fingerprint_sha256 === "string"
        && typeof note.storage_fingerprint_sha256 === "string"
        && note.storage_fingerprint_sha256 === operation.new_storage_fingerprint_sha256
      ) return "zotero_storage_equivalent";
      return null;
    };
    if (operation.note_key === null) {
      const matches = notes.map(note => ({note, content_match: contentMatch(note)})).filter(item => item.content_match);
      assertion(matches.length <= 1, "multiple child notes already match the requested content");
      if (matches.length === 1) {
        assertion(notes.length === 1, "matching child note exists beside unapproved notes");
        return {decision: "satisfied", note_key: matches[0].note.key, content_match: matches[0].content_match};
      }
      assertion(stableStringify(keys) === stableStringify(operation.expected_child_note_keys), "child note inventory drift");
      return {decision: "needs_write", note_key: null};
    }
    const note = notes.find(item => item.key === operation.note_key);
    assertion(note, "approved child note disappeared");
    const match = contentMatch(note);
    if (match) {
      assertion(notes.length === 1, "updated child note exists beside unapproved notes");
      return {decision: "satisfied", note_key: note.key, content_match: match};
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
    commitStateAfterFailure,
    classifyMembership,
    classifyMetadataRepair,
    classifyMetadataRepairV2,
    classifyMetadataSerializerGuard,
    classifyNote,
    classifyShortTitle,
    normalizeDOI,
    metadataDuplicateFingerprint,
    metadataDuplicateTitleMatch,
    metadataRepairCommitStateAfterFailure,
    metadataRepairParentIsClean,
    metadataRepairParentData,
    metadataSerializerAttachmentStableData,
    metadataSerializerParentStableData,
    metadataSerializerSortedValues,
    noteStorageDOMFingerprint,
    noteStorageHTMLFingerprint,
    parentIdentity,
    planWrites,
    readbackMembershipSatisfied,
    resolveCollectionID,
    stableStringify,
    validateCollectionResolutionRequest,
    validateManifest,
    validateMetadataRepairManifest,
    versionEvidence,
  };
})();

if (typeof module !== "undefined" && module.exports) {
  module.exports = ZoteroDeclarativeBridgeCore;
}
