/* global Zotero, Services, IOUtils, PathUtils, crypto, TextEncoder, DOMParser, Ci */

var ZoteroDeclarativeBridge = (() => {
  "use strict";

  const ENDPOINT = "/deep-research/transaction/v1";
  const CAPABILITY_FILE = "zotero-declarative-bridge-capability.json";
  const MAX_BODY_BYTES = 8 * 1024 * 1024;
  const MAX_PDF_BYTES = 256 * 1024 * 1024;
  const REQUEST_SKEW_MS = 120000;
  const NONCE_TTL_MS = 300000;
  const PREVIEW_TTL_MS = 900000;
  const METADATA_REPAIR_SCHEMA = "ZoteroParentMetadataRepairTransaction/v1";
  const METADATA_REPAIR_SCHEMA_V2 = "ZoteroParentMetadataRepairTransaction/v2";
  const METADATA_WRITABLE_FIELDS = ["DOI", "publicationTitle", "volume", "issue", "pages", "date"];
  const STATE = {
    endpointConstructor: null,
    capabilityPath: null,
    capabilityToken: null,
    keyID: null,
    pluginVersion: null,
    nonces: new Map(),
    previews: new Map(),
  };

  class ProtocolError extends Error {
    constructor(message, status = 400, code = "invalid_request") {
      super(message);
      this.status = status;
      this.code = code;
    }
  }

  function randomHex(byteLength) {
    const bytes = new Uint8Array(byteLength);
    crypto.getRandomValues(bytes);
    return [...bytes].map(value => value.toString(16).padStart(2, "0")).join("");
  }

  function bytesToHex(bytes) {
    return [...new Uint8Array(bytes)].map(value => value.toString(16).padStart(2, "0")).join("");
  }

  function hexToBytes(value) {
    const result = new Uint8Array(value.length / 2);
    for (let index = 0; index < result.length; index++) result[index] = parseInt(value.slice(index * 2, index * 2 + 2), 16);
    return result;
  }

  async function sha256Bytes(bytes) {
    return "sha256:" + bytesToHex(await crypto.subtle.digest("SHA-256", bytes));
  }

  async function sha256Text(value) {
    return sha256Bytes(new TextEncoder().encode(value));
  }

  async function sha256Value(value) {
    return sha256Text(ZoteroDeclarativeBridgeCore.stableStringify(value));
  }

  async function noteStorageFingerprint(noteHTML) {
    try {
      const fingerprint = ZoteroDeclarativeBridgeCore.noteStorageHTMLFingerprint(noteHTML, DOMParser);
      return sha256Text(fingerprint);
    }
    catch (_error) {
      return null;
    }
  }

  async function hmacHex(secretHex, value) {
    const key = await crypto.subtle.importKey(
      "raw",
      hexToBytes(secretHex),
      {name: "HMAC", hash: "SHA-256"},
      false,
      ["sign"],
    );
    return bytesToHex(await crypto.subtle.sign("HMAC", key, new TextEncoder().encode(value)));
  }

  function safeEqual(left, right) {
    if (typeof left !== "string" || typeof right !== "string") return false;
    let mismatch = left.length ^ right.length;
    const length = Math.max(left.length, right.length);
    for (let index = 0; index < length; index++) mismatch |= (left.charCodeAt(index) || 0) ^ (right.charCodeAt(index) || 0);
    return mismatch === 0;
  }

  function response(status, action, requestID, result, error = null) {
    const body = {
      schema: "ZoteroDeclarativeBridgeResponse/v1",
      status: error ? "failed" : result.status,
      action,
      request_id: requestID || null,
      result: error ? null : result,
      error,
    };
    return [
      status,
      {"Content-Type": "application/json", "Cache-Control": "no-store"},
      JSON.stringify(body),
      {logFilter: () => "Zotero Declarative Bridge response [redacted]"},
    ];
  }

  function cleanCaches() {
    const now = Date.now();
    for (const [nonce, expires] of STATE.nonces) if (expires <= now) STATE.nonces.delete(nonce);
    for (const [id, preview] of STATE.previews) if (preview.expiresAt <= now || preview.used) STATE.previews.delete(id);
  }

  async function authenticate(envelope) {
    const expectedKeys = ["schema", "request_id", "issued_at", "nonce", "key_id", "action", "payload", "mac"].sort();
    const actualKeys = envelope && typeof envelope === "object" && !Array.isArray(envelope) ? Object.keys(envelope).sort() : [];
    if (ZoteroDeclarativeBridgeCore.stableStringify(actualKeys) !== ZoteroDeclarativeBridgeCore.stableStringify(expectedKeys)) {
      throw new ProtocolError("authentication failed", 403, "authentication_failed");
    }
    if (
      envelope.schema !== "ZoteroDeclarativeBridgeRequest/v1"
      || !/^[0-9a-f]{32}$/.test(envelope.request_id)
      || !/^[0-9a-f]{32}$/.test(envelope.nonce)
      || envelope.key_id !== STATE.keyID
      || !["probe", "resolve_collection", "preview", "apply", "readback"].includes(envelope.action)
      || !envelope.payload || typeof envelope.payload !== "object" || Array.isArray(envelope.payload)
      || !/^[0-9a-f]{64}$/.test(envelope.mac)
    ) throw new ProtocolError("authentication failed", 403, "authentication_failed");
    const issued = Date.parse(envelope.issued_at);
    if (!Number.isFinite(issued) || Math.abs(Date.now() - issued) > REQUEST_SKEW_MS) {
      throw new ProtocolError("authentication failed", 403, "authentication_failed");
    }
    cleanCaches();
    if (STATE.nonces.has(envelope.nonce)) throw new ProtocolError("authentication failed", 403, "replay_rejected");
    const unsigned = {...envelope};
    delete unsigned.mac;
    const expectedMAC = await hmacHex(STATE.capabilityToken, ZoteroDeclarativeBridgeCore.stableStringify(unsigned));
    if (!safeEqual(expectedMAC, envelope.mac)) throw new ProtocolError("authentication failed", 403, "authentication_failed");
    STATE.nonces.set(envelope.nonce, Date.now() + NONCE_TTL_MS);
  }

  async function parseRequest(request) {
    const rawLength = request.headers["content-length"];
    if (!/^[0-9]+$/.test(rawLength || "")) throw new ProtocolError("Content-Length is required");
    const length = Number(rawLength);
    if (length <= 0 || length > MAX_BODY_BYTES) throw new ProtocolError("request body is outside the allowed size");
    const raw = Zotero.Server.networkStreamToString(request.data, length);
    let envelope;
    try { envelope = JSON.parse(raw); }
    catch (_error) { throw new ProtocolError("invalid JSON envelope"); }
    await authenticate(envelope);
    return envelope;
  }

  async function collectionPath(collection) {
    const result = [];
    const seen = new Set();
    let current = collection;
    while (current) {
      if (seen.has(current.id)) throw new ProtocolError("collection path cycle", 409, "target_drift");
      seen.add(current.id);
      if (current.deleted) throw new ProtocolError("collection path contains a deleted collection", 409, "target_drift");
      result.unshift({key: String(current.key), name: String(current.name)});
      current = current.parentID ? await Zotero.Collections.getAsync(current.parentID) : null;
    }
    return result;
  }

  async function resolveTarget(expected) {
    const library = Zotero.Libraries.get(expected.library_id);
    if (!library) throw new ProtocolError("target library is unavailable", 409, "target_drift");
    const collection = await Zotero.Collections.getByLibraryAndKeyAsync(expected.library_id, expected.collection_key);
    if (!collection || collection.deleted) throw new ProtocolError("target collection is unavailable", 409, "target_drift");
    const observed = {
      library_id: Number(library.libraryID || library.id),
      library_type: String(library.libraryType),
      library_type_id: Number(library.libraryTypeID),
      library_name: String(library.name),
      collection_id: Number(collection.id),
      collection_key: String(collection.key),
      collection_path: await collectionPath(collection),
      editable: library.editable === true,
      files_editable: library.filesEditable === true,
    };
    const comparisons = [
      [observed.library_id, expected.library_id],
      [observed.library_type, expected.library_type],
      [observed.library_type_id, expected.library_type_id],
      [observed.library_name, expected.library_name],
      [observed.collection_id, expected.collection_id],
      [observed.collection_key, expected.collection_key],
      [ZoteroDeclarativeBridgeCore.stableStringify(observed.collection_path), ZoteroDeclarativeBridgeCore.stableStringify(expected.collection_path)],
      [observed.editable, expected.require_editable],
    ];
    if (
      comparisons.some(([left, right]) => left !== right)
      || (expected.require_files_editable && !observed.files_editable)
    ) throw new ProtocolError("exact target contract drift", 409, "target_drift");
    return {library, collection, observed};
  }

  function linkModeName(value) {
    const modes = {
      [Zotero.Attachments.LINK_MODE_IMPORTED_FILE]: "imported_file",
      [Zotero.Attachments.LINK_MODE_IMPORTED_URL]: "imported_url",
      [Zotero.Attachments.LINK_MODE_LINKED_FILE]: "linked_file",
    };
    return modes[value] || `unsupported_${value}`;
  }

  async function fileEvidence(path) {
    const file = Zotero.File.pathToFile(path);
    let isSymlink = false;
    try { isSymlink = file.isSymlink(); }
    catch (_error) { isSymlink = true; }
    if (isSymlink || !file.exists() || !file.isFile()) throw new ProtocolError("bound PDF is not a regular non-symlink file", 409, "source_drift");
    const stat = await IOUtils.stat(path);
    if (stat.size <= 0 || stat.size > MAX_PDF_BYTES) throw new ProtocolError("bound PDF size is outside the allowed range", 409, "source_drift");
    const bytes = await IOUtils.read(path);
    if (bytes.byteLength !== stat.size) throw new ProtocolError("bound PDF size changed during read", 409, "source_drift");
    return {
      size_bytes: bytes.byteLength,
      sha256: await sha256Bytes(bytes),
      magic: String.fromCharCode(...bytes.slice(0, 5)),
    };
  }

  async function attachmentEvidence(item, includeStoragePath = false) {
    const result = {
      key: String(item.key),
      version: Number(item.version),
      content_type: String(item.attachmentContentType || ""),
      link_mode: linkModeName(item.attachmentLinkMode),
      readable_pdf: false,
      sha256: null,
      size_bytes: null,
      direct_collection_count: item.getCollections().length,
    };
    let path = null;
    try { path = await item.getFilePathAsync(); }
    catch (_error) { path = null; }
    if (path && await IOUtils.exists(path)) {
      try {
        const evidence = await fileEvidence(path);
        result.sha256 = evidence.sha256;
        result.size_bytes = evidence.size_bytes;
        result.readable_pdf = result.content_type === "application/pdf" && evidence.magic === "%PDF-";
      }
      catch (_error) {
        result.readable_pdf = false;
      }
    }
    if (includeStoragePath) result.storage_path = String(path || "");
    return result;
  }

  function metadataCreator(creator) {
    let creatorType = creator.creatorType;
    if (!creatorType && creator.creatorTypeID) creatorType = Zotero.CreatorTypes.getName(creator.creatorTypeID);
    return {
      creatorType: String(creatorType || ""),
      firstName: String(creator.firstName || ""),
      lastName: String(creator.lastName || ""),
    };
  }

  function metadataProfile(parent) {
    return {
      DOI: ZoteroDeclarativeBridgeCore.normalizeDOI(String(parent.getField("DOI") || "")),
      creators: parent.getCreators().map(metadataCreator),
      publicationTitle: String(parent.getField("publicationTitle") || ""),
      volume: String(parent.getField("volume") || ""),
      issue: String(parent.getField("issue") || ""),
      pages: String(parent.getField("pages") || ""),
      date: String(parent.getField("date") || ""),
    };
  }

  function metadataRawData(item, label) {
    let data;
    try { data = item.toJSON(); }
    catch (_error) { data = null; }
    if (!data || typeof data !== "object" || Array.isArray(data)) {
      throw new ProtocolError(`${label} raw data is unavailable`, 409, "metadata_drift");
    }
    return JSON.parse(JSON.stringify(data));
  }

  async function metadataChildState(parent, includeSerializerRecords = false) {
    let notes = parent.getNotes().length ? await Zotero.Items.getAsync(parent.getNotes()) : [];
    if (!Array.isArray(notes)) notes = [notes];
    let attachments = parent.getAttachments().length ? await Zotero.Items.getAsync(parent.getAttachments()) : [];
    if (!Array.isArray(attachments)) attachments = [attachments];
    const children = [];
    const serializerRecords = [];
    for (const note of notes.filter(Boolean)) {
      if (note.parentItemID !== parent.id) throw new ProtocolError("metadata note parent drift", 409, "child_drift");
      children.push({
        key: String(note.key),
        version: Number(note.version),
        item_type: "note",
        content_sha256: await sha256Text(note.getNote()),
      });
      if (includeSerializerRecords) {
        serializerRecords.push({
          data: metadataRawData(note, `metadata note ${note.key}`),
          content_sha256: children.at(-1).content_sha256,
        });
      }
    }
    for (const attachment of attachments.filter(Boolean)) {
      if (attachment.parentItemID !== parent.id) throw new ProtocolError("metadata attachment parent drift", 409, "child_drift");
      const evidence = await attachmentEvidence(attachment, includeSerializerRecords);
      if (!evidence.sha256 || !evidence.size_bytes) throw new ProtocolError("metadata attachment bytes are unreadable", 409, "child_drift");
      children.push({
        key: evidence.key,
        version: evidence.version,
        item_type: "attachment",
        content_type: evidence.content_type,
        link_mode: evidence.link_mode,
        size_bytes: evidence.size_bytes,
        content_sha256: evidence.sha256,
        direct_collection_count: evidence.direct_collection_count,
      });
      if (includeSerializerRecords) {
        serializerRecords.push({
          data: metadataRawData(attachment, `metadata attachment ${attachment.key}`),
          storage_path: evidence.storage_path,
          content_sha256: evidence.sha256,
          size_bytes: evidence.size_bytes,
        });
      }
    }
    children.sort((left, right) => left.key.localeCompare(right.key));
    serializerRecords.sort((left, right) => String(left.data.key).localeCompare(String(right.data.key)));
    return {children, serializerRecords};
  }

  async function metadataSerializerGuard(parent, childState) {
    const parentData = metadataRawData(parent, "metadata parent");
    if (String(parentData.itemType || "") !== "journalArticle") {
      throw new ProtocolError("metadata serializer parent type drift", 409, "metadata_drift");
    }
    const tags = Array.isArray(parentData.tags) ? parentData.tags : null;
    const collections = Array.isArray(parentData.collections) ? parentData.collections : null;
    if (!tags || !collections) {
      throw new ProtocolError("metadata serializer parent sets are unavailable", 409, "metadata_drift");
    }
    const guardChildren = [];
    for (const wrapper of childState.serializerRecords) {
      const data = wrapper.data;
      const itemType = String(data.itemType || "");
      const common = {
        key: String(data.key || ""),
        item_type: itemType,
        version: Number(data.version),
        raw_data_sha256: await sha256Value(data),
      };
      if (itemType === "note") {
        guardChildren.push({...common, content_sha256: wrapper.content_sha256});
      }
      else if (itemType === "attachment") {
        guardChildren.push({
          ...common,
          stable_data_sha256: await sha256Value(
            ZoteroDeclarativeBridgeCore.metadataSerializerAttachmentStableData(data),
          ),
          filename_sha256: await sha256Value(String(data.filename || "")),
          storage_path_sha256: await sha256Value(String(wrapper.storage_path || "")),
          content_sha256: wrapper.content_sha256,
          size_bytes: wrapper.size_bytes,
        });
      }
      else throw new ProtocolError("metadata serializer child type drift", 409, "metadata_drift");
    }
    guardChildren.sort((left, right) => left.key.localeCompare(right.key));
    const unsigned = {
      profile: "zotero_managed_storage_equivalence_v1",
      parent: {
        raw_data_sha256: await sha256Value(parentData),
        stable_nonprofile_sha256: await sha256Value(
          ZoteroDeclarativeBridgeCore.metadataSerializerParentStableData(parentData),
        ),
        tags_raw_sha256: await sha256Value(tags),
        tags_set_sha256: await sha256Value(
          ZoteroDeclarativeBridgeCore.metadataSerializerSortedValues(tags),
        ),
        collections_raw_sha256: await sha256Value(collections),
        collections_set_sha256: await sha256Value(
          ZoteroDeclarativeBridgeCore.metadataSerializerSortedValues(collections),
        ),
      },
      children: guardChildren,
    };
    return {...unsigned, guard_sha256: await sha256Value(unsigned)};
  }

  async function metadataDuplicateCandidates(manifest, desiredProfile) {
    let items = await Zotero.Items.getAll(manifest.target.library_id, true);
    if (!Array.isArray(items)) items = [];
    if (items.length && typeof items[0] === "number") items = await Zotero.Items.getAsync(items);
    const desiredDOI = ZoteroDeclarativeBridgeCore.normalizeDOI(desiredProfile.DOI);
    const desiredFingerprint = ZoteroDeclarativeBridgeCore.metadataDuplicateFingerprint(
      manifest.entry.parent.title,
      desiredProfile,
    );
    const doiMatches = [];
    const titleMatches = [];
    for (const item of items.filter(Boolean)) {
      if (
        item.deleted || !item.isRegularItem || !item.isRegularItem()
        || String(item.key) === manifest.entry.parent.key
      ) continue;
      const observedDOI = ZoteroDeclarativeBridgeCore.normalizeDOI(String(item.getField("DOI") || ""));
      if (desiredDOI && observedDOI === desiredDOI) doiMatches.push(String(item.key));
      const observedProfile = metadataProfile(item);
      const observedFingerprint = ZoteroDeclarativeBridgeCore.metadataDuplicateFingerprint(
        String(item.getField("title") || ""),
        observedProfile,
      );
      if (ZoteroDeclarativeBridgeCore.metadataDuplicateTitleMatch(desiredFingerprint, observedFingerprint)) {
        titleMatches.push(String(item.key));
      }
    }
    return {
      desired_doi_other_parent_keys: [...new Set(doiMatches)].sort(),
      title_year_creator_other_parent_keys: [...new Set(titleMatches)].sort(),
    };
  }

  async function parentState(entry, target) {
    const parent = await Zotero.Items.getByLibraryAndKeyAsync(target.observed.library_id, entry.parent.key);
    if (!parent || parent.deleted || !parent.isRegularItem()) throw new ProtocolError(`parent unavailable: ${entry.parent.key}`, 409, "parent_drift");
    const observedParent = {
      key: String(parent.key),
      version: Number(parent.version),
      item_type: String(parent.itemType),
      title: String(parent.getField("title") || ""),
      short_title: String(parent.getField("shortTitle") || ""),
      doi: ZoteroDeclarativeBridgeCore.normalizeDOI(String(parent.getField("DOI") || "")),
      target_membership: parent.getCollections().includes(target.collection.id),
      synced: parent.synced === true,
    };
    const identity = ZoteroDeclarativeBridgeCore.parentIdentity(observedParent, target.observed.library_id);
    observedParent.identity_sha256 = await sha256Value(identity);
    for (const field of ["key", "item_type", "title", "doi", "identity_sha256"]) {
      if (observedParent[field] !== entry.parent[field]) throw new ProtocolError(`parent ${entry.parent.key} ${field} drift`, 409, "parent_drift");
    }
    let notes = parent.getNotes().length ? await Zotero.Items.getAsync(parent.getNotes()) : [];
    if (!Array.isArray(notes)) notes = [notes];
    const noteStates = [];
    for (const note of notes.filter(Boolean)) {
      if (note.parentItemID !== parent.id) throw new ProtocolError("child note parent drift", 409, "child_drift");
      const noteHTML = note.getNote();
      noteStates.push({
        key: String(note.key),
        version: Number(note.version),
        synced: note.synced === true,
        sha256: await sha256Text(noteHTML),
        storage_fingerprint_sha256: await noteStorageFingerprint(noteHTML),
      });
    }
    noteStates.sort((left, right) => left.key.localeCompare(right.key));
    let attachments = parent.getAttachments().length ? await Zotero.Items.getAsync(parent.getAttachments()) : [];
    if (!Array.isArray(attachments)) attachments = [attachments];
    const attachmentStates = [];
    for (const attachment of attachments.filter(Boolean)) {
      if (attachment.parentItemID !== parent.id) throw new ProtocolError("attachment parent drift", 409, "child_drift");
      attachmentStates.push(await attachmentEvidence(attachment));
    }
    attachmentStates.sort((left, right) => left.key.localeCompare(right.key));
    return {parent, observedParent, noteStates, attachmentStates};
  }

  async function classifyEntry(entry, target) {
    const live = await parentState(entry, target);
    const decisions = [];
    for (const operation of entry.operations) {
      if (operation.type === "ensure_collection_membership") {
        decisions.push({...ZoteroDeclarativeBridgeCore.classifyMembership(operation, live.observedParent.target_membership), type: operation.type});
      }
      else if (operation.type === "ensure_parent_short_title") {
        const fieldID = Zotero.ItemFields.getID("shortTitle");
        if (!fieldID || !Zotero.ItemFields.isValidForType(fieldID, live.parent.itemTypeID)) {
          throw new ProtocolError("shortTitle is invalid for the parent item type", 409, "parent_drift");
        }
        try {
          decisions.push({
            ...ZoteroDeclarativeBridgeCore.classifyShortTitle(operation, {
              library_id: target.observed.library_id,
              parent_key: live.observedParent.key,
              item_version: live.observedParent.version,
              value: live.observedParent.short_title,
            }),
            type: operation.type,
          });
        }
        catch (error) {
          throw new ProtocolError(error.message, 409, "parent_drift");
        }
      }
      else if (operation.type === "ensure_child_note") {
        if (await sha256Text(operation.new_html) !== operation.new_sha256) throw new ProtocolError("new note hash mismatch", 409, "source_drift");
        const runtimeOperation = {
          ...operation,
          new_storage_fingerprint_sha256: await noteStorageFingerprint(operation.new_html),
        };
        try {
          decisions.push({...ZoteroDeclarativeBridgeCore.classifyNote(runtimeOperation, live.noteStates), type: operation.type});
        }
        catch (error) {
          throw new ProtocolError(error.message, 409, "child_drift");
        }
      }
      else {
        const source = await fileEvidence(operation.source_path);
        if (source.size_bytes !== operation.source_size_bytes || source.sha256 !== operation.source_sha256 || source.magic !== operation.source_magic) {
          throw new ProtocolError("bound PDF drift", 409, "source_drift");
        }
        decisions.push({...ZoteroDeclarativeBridgeCore.classifyAttachment(operation, live.attachmentStates), type: operation.type});
      }
    }
    const allSatisfied = decisions.every(item => item.decision === "satisfied");
    if (!allSatisfied) {
      if (live.observedParent.version !== entry.parent.version) throw new ProtocolError(`parent ${entry.parent.key} version drift`, 409, "parent_drift");
      if (live.observedParent.target_membership !== entry.parent.expected_target_membership) throw new ProtocolError(`parent ${entry.parent.key} membership drift`, 409, "parent_drift");
    }
    return {entry, live, decisions, allSatisfied};
  }

  function publicEntry(row) {
    const parentVersion = ZoteroDeclarativeBridgeCore.versionEvidence(
      row.live.observedParent.version,
      row.live.observedParent.synced,
      row.entry.parent.version,
    );
    const noteOperation = row.entry.operations.find(operation => operation.type === "ensure_child_note");
    const childNotes = row.live.noteStates.map(note => {
      const precondition = noteOperation && noteOperation.note_key === note.key
        ? noteOperation.expected_note_version
        : null;
      const version = ZoteroDeclarativeBridgeCore.versionEvidence(
        note.version,
        note.synced,
        precondition,
      );
      return {
        key: note.key,
        version: version.observed_version,
        version_precondition: version.precondition_version,
        current_synced_version: version.current_synced_version,
        version_sync_status: version.sync_status,
        sha256: note.sha256,
      };
    });
    return {
      parent_key: row.entry.parent.key,
      parent_version: parentVersion.observed_version,
      parent_version_precondition: parentVersion.precondition_version,
      parent_current_synced_version: parentVersion.current_synced_version,
      parent_version_sync_status: parentVersion.sync_status,
      target_membership: row.live.observedParent.target_membership,
      short_title: row.live.observedParent.short_title,
      child_notes: childNotes,
      attachments: row.live.attachmentStates,
      operations: row.decisions,
      all_satisfied: row.allSatisfied,
    };
  }

  async function validateManifestDigest(manifest) {
    ZoteroDeclarativeBridgeCore.validateManifest(manifest);
    const unsigned = {...manifest};
    delete unsigned.manifest_sha256;
    if (await sha256Value(unsigned) !== manifest.manifest_sha256) throw new ProtocolError("manifest digest mismatch");
    for (const entry of manifest.entries) {
      const expectedIdentity = ZoteroDeclarativeBridgeCore.parentIdentity(entry.parent, manifest.target.library_id);
      if (await sha256Value(expectedIdentity) !== entry.parent.identity_sha256) throw new ProtocolError(`parent ${entry.parent.key} identity digest mismatch`);
    }
  }

  async function preflight(manifest, enforceReadbackMembership = false) {
    await validateManifestDigest(manifest);
    const target = await resolveTarget(manifest.target);
    const rows = [];
    for (const entry of manifest.entries) rows.push(await classifyEntry(entry, target));
    const rowSatisfied = row => row.allSatisfied && (
      !enforceReadbackMembership
      || ZoteroDeclarativeBridgeCore.readbackMembershipSatisfied(
        row.entry,
        row.live.observedParent.target_membership,
        row.decisions,
      )
    );
    let writePlan;
    try { writePlan = ZoteroDeclarativeBridgeCore.planWrites(rows); }
    catch (error) { throw new ProtocolError(error.message, 409, "unsafe_write_plan"); }
    const publicState = {
      target: target.observed,
      execution_profile: writePlan.mode,
      write_plan: writePlan,
      entries: rows.map(row => ({...publicEntry(row), all_satisfied: rowSatisfied(row)})),
    };
    return {
      target,
      rows,
      publicState,
      stateSHA256: await sha256Value(publicState),
      allSatisfied: rows.every(rowSatisfied),
    };
  }

  async function validateMetadataRepairDigest(manifest) {
    try { ZoteroDeclarativeBridgeCore.validateMetadataRepairManifest(manifest); }
    catch (error) { throw new ProtocolError(error.message); }
    const unsigned = {...manifest};
    delete unsigned.manifest_sha256;
    if (await sha256Value(unsigned) !== manifest.manifest_sha256) throw new ProtocolError("metadata repair manifest digest mismatch");
    const entry = manifest.entry;
    const operation = entry.operation;
    if (await sha256Value(entry.children) !== entry.children_sha256) throw new ProtocolError("metadata repair children digest mismatch");
    const duplicateUnsigned = {...entry.duplicate_preconditions};
    delete duplicateUnsigned.sha256;
    if (await sha256Value(duplicateUnsigned) !== entry.duplicate_preconditions.sha256) throw new ProtocolError("metadata repair duplicate digest mismatch");
    if (await sha256Value(operation.expected_profile) !== operation.expected_profile_sha256) throw new ProtocolError("metadata repair expected profile digest mismatch");
    if (await sha256Value(operation.desired_profile) !== operation.desired_profile_sha256) throw new ProtocolError("metadata repair desired profile digest mismatch");
    const expectedData = ZoteroDeclarativeBridgeCore.metadataRepairParentData(entry.parent, entry.children, operation.expected_profile);
    const desiredData = ZoteroDeclarativeBridgeCore.metadataRepairParentData(entry.parent, entry.children, operation.desired_profile);
    if (await sha256Value(expectedData) !== operation.expected_parent_data_sha256) throw new ProtocolError("metadata repair expected parent-data digest mismatch");
    if (await sha256Value(desiredData) !== operation.desired_parent_data_sha256) throw new ProtocolError("metadata repair desired parent-data digest mismatch");
    if (manifest.schema === METADATA_REPAIR_SCHEMA_V2) {
      const unsignedGuard = {...entry.serializer_guard};
      delete unsignedGuard.guard_sha256;
      if (await sha256Value(unsignedGuard) !== entry.serializer_guard.guard_sha256) {
        throw new ProtocolError("metadata repair serializer guard digest mismatch");
      }
    }
  }

  function assertMetadataRepairParentClean(parent) {
    let hasChanged;
    try {
      hasChanged = typeof parent.hasChanged === "function" ? parent.hasChanged() : null;
    }
    catch (_error) {
      hasChanged = null;
    }
    if (!ZoteroDeclarativeBridgeCore.metadataRepairParentIsClean(hasChanged)) {
      throw new ProtocolError("metadata repair parent has unsaved changes", 409, "parent_dirty");
    }
  }

  async function preflightMetadataRepair(
    manifest,
    suppliedParent = null,
    allowSerializerEquivalence = false,
  ) {
    await validateMetadataRepairDigest(manifest);
    const target = await resolveTarget(manifest.target);
    const entry = manifest.entry;
    const parent = suppliedParent || await Zotero.Items.getByLibraryAndKeyAsync(target.observed.library_id, entry.parent.key);
    if (!parent || parent.deleted || !parent.isRegularItem()) throw new ProtocolError("metadata repair parent unavailable", 409, "parent_drift");
    assertMetadataRepairParentClean(parent);
    const observedParent = {
      key: String(parent.key),
      version: Number(parent.version),
      item_type: String(parent.itemType),
      title: String(parent.getField("title") || ""),
      short_title: String(parent.getField("shortTitle") || ""),
      expected_target_membership: parent.getCollections().includes(target.collection.id),
      synced: parent.synced === true,
    };
    for (const field of ["key", "item_type", "title", "short_title", "expected_target_membership"]) {
      if (observedParent[field] !== entry.parent[field]) throw new ProtocolError(`metadata repair protected ${field} drift`, 409, "parent_drift");
    }
    for (const field of METADATA_WRITABLE_FIELDS) {
      const fieldID = Zotero.ItemFields.getID(field);
      if (!fieldID || !Zotero.ItemFields.isValidForType(fieldID, parent.itemTypeID)) {
        throw new ProtocolError(`metadata repair field is invalid for journalArticle: ${field}`, 409, "parent_drift");
      }
    }
    const isV2 = manifest.schema === METADATA_REPAIR_SCHEMA_V2;
    const childState = await metadataChildState(parent, isV2);
    const children = childState.children;
    const evidencePDF = children.find(child => child.key === entry.evidence_pdf_key);
    if (!evidencePDF || evidencePDF.item_type !== "attachment" || evidencePDF.content_type !== "application/pdf") {
      throw new ProtocolError("metadata repair evidence PDF drift", 409, "child_drift");
    }
    const profile = metadataProfile(parent);
    const profileSHA256 = await sha256Value(profile);
    const observedData = ZoteroDeclarativeBridgeCore.metadataRepairParentData(observedParent, children, profile);
    const parentDataSHA256 = await sha256Value(observedData);
    const duplicateCandidates = await metadataDuplicateCandidates(manifest, entry.operation.desired_profile);
    if (
      duplicateCandidates.desired_doi_other_parent_keys.length
      || duplicateCandidates.title_year_creator_other_parent_keys.length
    ) throw new ProtocolError("metadata repair duplicate conflict", 409, "duplicate_conflict");
    const boundDuplicate = entry.duplicate_preconditions;
    if (
      ZoteroDeclarativeBridgeCore.stableStringify(duplicateCandidates.desired_doi_other_parent_keys)
        !== ZoteroDeclarativeBridgeCore.stableStringify(boundDuplicate.desired_doi_other_parent_keys)
      || ZoteroDeclarativeBridgeCore.stableStringify(duplicateCandidates.title_year_creator_other_parent_keys)
        !== ZoteroDeclarativeBridgeCore.stableStringify(boundDuplicate.title_year_creator_other_parent_keys)
    ) throw new ProtocolError("metadata repair duplicate precondition drift", 409, "duplicate_conflict");
    let decision;
    try {
      if (isV2) {
        decision = ZoteroDeclarativeBridgeCore.classifyMetadataRepairV2(
          entry.operation,
          entry.serializer_guard,
          {
            parent_version: observedParent.version,
            parent_data_sha256: parentDataSHA256,
            profile_sha256: profileSHA256,
            serializer_guard: await metadataSerializerGuard(parent, childState),
          },
          allowSerializerEquivalence,
        );
      }
      else {
        decision = ZoteroDeclarativeBridgeCore.classifyMetadataRepair(entry.operation, {
          parent_version: observedParent.version,
          parent_data_sha256: parentDataSHA256,
        });
      }
    }
    catch (error) {
      throw new ProtocolError(error.message, 409, "metadata_drift");
    }
    const allSatisfied = decision.decision === "satisfied";
    const parentVersion = ZoteroDeclarativeBridgeCore.versionEvidence(
      observedParent.version,
      observedParent.synced,
      entry.parent.version,
    );
    const publicState = {
      target: target.observed,
      execution_profile: "db_atomic",
      write_plan: {
        mode: allSatisfied ? "none" : "db_atomic",
        operation_count: allSatisfied ? 0 : 1,
        attachment_operation_count: 0,
        database_operation_count: allSatisfied ? 0 : 1,
      },
      entry: {
        parent_key: entry.parent.key,
        parent_version: parentVersion.observed_version,
        parent_version_precondition: parentVersion.precondition_version,
        parent_current_synced_version: parentVersion.current_synced_version,
        parent_version_sync_status: parentVersion.sync_status,
        target_membership: observedParent.expected_target_membership,
        profile_sha256: profileSHA256,
        parent_data_sha256: parentDataSHA256,
        children_sha256: await sha256Value(children),
        duplicate_candidates: duplicateCandidates,
        operation: {...decision, type: entry.operation.type},
        all_satisfied: allSatisfied,
      },
    };
    return {
      target,
      parent,
      publicState,
      stateSHA256: await sha256Value(publicState),
      allSatisfied,
    };
  }

  async function preflightForManifest(manifest, enforceReadbackMembership = false) {
    return manifest && [METADATA_REPAIR_SCHEMA, METADATA_REPAIR_SCHEMA_V2].includes(manifest.schema)
      ? preflightMetadataRepair(manifest, null, enforceReadbackMembership)
      : preflight(manifest, enforceReadbackMembership);
  }

  async function applyMetadataRepair(manifest, preflightResult) {
    const desired = manifest.entry.operation.desired_profile;
    assertMetadataRepairParentClean(preflightResult.parent);
    preflightResult.parent.setCreators(desired.creators.map(creator => ({...creator})));
    for (const field of METADATA_WRITABLE_FIELDS) preflightResult.parent.setField(field, desired[field]);
    await preflightResult.parent.save();
    return [];
  }

  async function freshMetadataRepairFailureInspection(
    manifest,
    parent,
    inspectPreflight = preflightMetadataRepair,
  ) {
    if (!parent || !Number.isInteger(parent.id) || parent.id <= 0) {
      throw new ProtocolError("metadata repair failure parent is unavailable", 500, "readback_unavailable");
    }
    const itemID = parent.id;
    try {
      await parent.reload(null, true);
    }
    catch (error) {
      try { Zotero.Items.unload(itemID); }
      catch (_unloadError) {}
      throw error;
    }
    Zotero.Items.unload(itemID);
    const fresh = await Zotero.Items.getByLibraryAndKeyAsync(
      manifest.target.library_id,
      manifest.entry.parent.key,
    );
    if (!fresh || fresh === parent || fresh.id !== itemID) {
      throw new ProtocolError("metadata repair fresh readback failed", 500, "readback_unavailable");
    }
    return inspectPreflight(manifest, fresh, true);
  }

  async function applyRows(preflightResult) {
    const createdAttachmentKeys = [];
    for (const row of preflightResult.rows) {
      for (let index = 0; index < row.entry.operations.length; index++) {
        const operation = row.entry.operations[index];
        const decision = row.decisions[index];
        if (decision.decision === "satisfied") continue;
        if (operation.type === "ensure_collection_membership") {
          row.live.parent.addToCollection(preflightResult.target.collection.id);
          await row.live.parent.save({skipDateModifiedUpdate: true});
        }
        else if (operation.type === "ensure_parent_short_title") {
          const fieldID = Zotero.ItemFields.getID("shortTitle");
          if (!fieldID || !Zotero.ItemFields.isValidForType(fieldID, row.live.parent.itemTypeID)) {
            throw new ProtocolError("shortTitle is invalid for the parent item type", 409, "parent_drift");
          }
          row.live.parent.setField("shortTitle", operation.new_short_title);
          await row.live.parent.save();
        }
        else if (operation.type === "ensure_child_note") {
          if (operation.note_key) {
            const note = await Zotero.Items.getByLibraryAndKeyAsync(preflightResult.target.observed.library_id, operation.note_key);
            if (!note || note.parentItemID !== row.live.parent.id) throw new ProtocolError("approved note disappeared during transaction", 409, "transaction_drift");
            note.setNote(operation.new_html);
            await note.save();
          }
          else {
            const note = new Zotero.Item("note");
            note.libraryID = preflightResult.target.observed.library_id;
            note.parentKey = row.entry.parent.key;
            note.setNote(operation.new_html);
            await note.save();
          }
        }
        else {
          const attachment = await Zotero.Attachments.importFromFile({
            file: operation.source_path,
            libraryID: preflightResult.target.observed.library_id,
            parentItemID: row.live.parent.id,
            contentType: "application/pdf",
          });
          if (!attachment || !attachment.key) throw new Error("attachment import returned no item key");
          createdAttachmentKeys.push(attachment.key);
        }
      }
    }
    return createdAttachmentKeys;
  }

  async function dispatch(envelope, testHooks = null) {
    if (testHooks && globalThis.__ZOTERO_DECLARATIVE_BRIDGE_TEST__ !== true) {
      throw new ProtocolError("bootstrap test hooks are unavailable");
    }
    const runPreflightForManifest = testHooks && testHooks.preflightForManifest
      ? testHooks.preflightForManifest
      : preflightForManifest;
    const runApplyMetadataRepair = testHooks && testHooks.applyMetadataRepair
      ? testHooks.applyMetadataRepair
      : applyMetadataRepair;
    const runFreshMetadataRepairFailureInspection = (
      testHooks && testHooks.freshMetadataRepairFailureInspection
        ? testHooks.freshMetadataRepairFailureInspection
        : freshMetadataRepairFailureInspection
    );
    const action = envelope.action;
    if (action === "probe") {
      if (Object.keys(envelope.payload).length) throw new ProtocolError("probe payload must be empty");
      return {
        status: "available",
        plugin_version: STATE.pluginVersion,
        zotero_version: Zotero.version,
        endpoint: ENDPOINT,
        read_only_actions: ["resolve_collection"],
        operations: ["ensure_collection_membership", "ensure_parent_short_title", "ensure_child_note", "ensure_pdf_attachment"],
        metadata_repair_schemas: [METADATA_REPAIR_SCHEMA, METADATA_REPAIR_SCHEMA_V2],
        metadata_repair_operations: ["ensure_parent_journal_metadata_v1"],
        execution_profiles: {
          db_atomic: ["ensure_collection_membership", "ensure_parent_short_title", "ensure_child_note"],
          single_attachment_import: ["ensure_pdf_attachment"],
        },
        mixed_operations: false,
        attachment_batch: false,
        arbitrary_javascript: false,
        sqlite_access: false,
      };
    }
    if (action === "resolve_collection") {
      let payload;
      try {
        payload = ZoteroDeclarativeBridgeCore.validateCollectionResolutionRequest(envelope.payload);
      }
      catch (error) {
        throw new ProtocolError(error.message);
      }
      const library = Zotero.Libraries.get(payload.library_id);
      const collection = await Zotero.Collections.getByLibraryAndKeyAsync(
        payload.library_id,
        payload.collection_key,
      );
      try {
        return ZoteroDeclarativeBridgeCore.resolveCollectionID(payload, library, collection);
      }
      catch (error) {
        const resolutionCodes = new Set([
          "library_not_found", "library_mismatch", "library_not_group",
          "collection_not_found", "collection_ambiguous", "collection_mismatch",
        ]);
        if (!resolutionCodes.has(error.code)) throw error;
        const status = ["library_not_found", "collection_not_found"].includes(error.code) ? 404 : 409;
        throw new ProtocolError("exact collection resolution failed", status, error.code);
      }
    }
    const allowedPayload = action === "apply"
      ? ["manifest", "preview_id", "preview_token", "state_sha256"]
      : ["manifest"];
    const actualPayload = Object.keys(envelope.payload).sort();
    if (ZoteroDeclarativeBridgeCore.stableStringify(actualPayload) !== ZoteroDeclarativeBridgeCore.stableStringify([...allowedPayload].sort())) {
      throw new ProtocolError("payload keys differ");
    }
    const manifest = envelope.payload.manifest;
    if (
      manifest && manifest.schema === METADATA_REPAIR_SCHEMA_V2
      && manifest.execution_intent === "readback_only" && action !== "readback"
    ) throw new ProtocolError("readback-only metadata transaction forbids preview and apply", 409, "readback_only");
    const before = await runPreflightForManifest(manifest, action === "readback");
    if (action === "readback") {
      return {
        status: before.allSatisfied ? "verified" : "not_applied",
        manifest_sha256: manifest.manifest_sha256,
        state_sha256: before.stateSHA256,
        all_satisfied: before.allSatisfied,
        state: before.publicState,
      };
    }
    if (action === "preview") {
      const previewID = randomHex(16);
      const previewToken = randomHex(32);
      const expiresAt = Date.now() + PREVIEW_TTL_MS;
      STATE.previews.set(previewID, {
        token: previewToken,
        manifestSHA256: manifest.manifest_sha256,
        stateSHA256: before.stateSHA256,
        expiresAt,
        used: false,
      });
      return {
        status: before.allSatisfied ? "no_changes" : "preview_ready",
        manifest_sha256: manifest.manifest_sha256,
        state_sha256: before.stateSHA256,
        preview_id: previewID,
        preview_token: previewToken,
        expires_at: new Date(expiresAt).toISOString(),
        state: before.publicState,
      };
    }
    cleanCaches();
    const preview = STATE.previews.get(envelope.payload.preview_id);
    if (
      !preview
      || preview.used
      || !safeEqual(preview.token, envelope.payload.preview_token)
      || preview.manifestSHA256 !== manifest.manifest_sha256
      || preview.stateSHA256 !== envelope.payload.state_sha256
      || preview.stateSHA256 !== before.stateSHA256
    ) throw new ProtocolError("preview is missing, expired, used, or stale", 412, "preview_invalid");
    preview.used = true;
    if (before.allSatisfied) {
      return {
        status: "no_changes",
        manifest_sha256: manifest.manifest_sha256,
        state_sha256: before.stateSHA256,
        write_attempted: false,
        commit_state: "not_started",
        state: before.publicState,
      };
    }
    let writeAttempted = false;
    let createdAttachmentKeys = [];
    let dbCommitConfirmed = false;
    let metadataCommitObserved = false;
    let metadataRollbackObserved = false;
    let metadataRepairParent = null;
    const executionProfile = before.publicState.execution_profile;
    try {
      const repeatAndApply = async () => {
        if ([METADATA_REPAIR_SCHEMA, METADATA_REPAIR_SCHEMA_V2].includes(manifest.schema)) {
          Zotero.DB.addCurrentCallback("commit", () => { metadataCommitObserved = true; });
          Zotero.DB.addCurrentCallback("rollback", () => { metadataRollbackObserved = true; });
        }
        const repeated = await runPreflightForManifest(manifest);
        if (repeated.stateSHA256 !== before.stateSHA256) throw new ProtocolError("state changed at transaction start", 409, "transaction_drift");
        if ([METADATA_REPAIR_SCHEMA, METADATA_REPAIR_SCHEMA_V2].includes(manifest.schema)) metadataRepairParent = repeated.parent;
        writeAttempted = true;
        createdAttachmentKeys = [METADATA_REPAIR_SCHEMA, METADATA_REPAIR_SCHEMA_V2].includes(manifest.schema)
          ? await runApplyMetadataRepair(manifest, repeated)
          : await applyRows(repeated);
      };
      if (executionProfile === "single_attachment_import") await repeatAndApply();
      else {
        await Zotero.DB.executeTransaction(repeatAndApply);
        dbCommitConfirmed = true;
      }
      const after = await runPreflightForManifest(
        manifest,
        manifest.schema === METADATA_REPAIR_SCHEMA_V2,
      );
      if (!after.allSatisfied) throw new ProtocolError("committed readback mismatch", 500, "readback_mismatch");
      return {
        status: "completed",
        manifest_sha256: manifest.manifest_sha256,
        state_sha256: after.stateSHA256,
        write_attempted: true,
        commit_state: "committed",
        execution_profile: executionProfile,
        created_attachment_keys: createdAttachmentKeys,
        state: after.publicState,
      };
    }
    catch (error) {
      let inspection = null;
      let commitState = "unknown";
      if ([METADATA_REPAIR_SCHEMA, METADATA_REPAIR_SCHEMA_V2].includes(manifest.schema)) {
        if (writeAttempted && (metadataCommitObserved || metadataRollbackObserved)) {
          try {
            inspection = await runFreshMetadataRepairFailureInspection(
              manifest,
              metadataRepairParent,
            );
          }
          catch (_inspectionError) {}
        }
        commitState = ZoteroDeclarativeBridgeCore.metadataRepairCommitStateAfterFailure({
          write_attempted: writeAttempted,
          db_commit_confirmed: dbCommitConfirmed,
          commit_observed: metadataCommitObserved,
          rollback_observed: metadataRollbackObserved,
          inspection_available: inspection !== null,
          before_state_sha256: before.stateSHA256,
          inspection_state_sha256: inspection ? inspection.stateSHA256 : null,
          inspection_all_satisfied: inspection ? inspection.allSatisfied : false,
        });
      }
      else {
        try {
          inspection = await runPreflightForManifest(manifest);
        }
        catch (_inspectionError) {}
        commitState = ZoteroDeclarativeBridgeCore.commitStateAfterFailure({
          write_attempted: writeAttempted,
          execution_profile: executionProfile,
          db_commit_confirmed: dbCommitConfirmed,
          inspection_available: inspection !== null,
          before_state_sha256: before.stateSHA256,
          inspection_state_sha256: inspection ? inspection.stateSHA256 : null,
          inspection_all_satisfied: inspection ? inspection.allSatisfied : false,
          created_attachment_count: createdAttachmentKeys.length,
        });
      }
      const wrapped = new ProtocolError(
        `transaction failed; commit_state=${commitState}`,
        error instanceof ProtocolError ? error.status : 500,
        error instanceof ProtocolError ? error.code : "transaction_failed",
      );
      wrapped.writeAttempted = writeAttempted;
      wrapped.commitState = commitState;
      wrapped.inspection = inspection ? inspection.publicState : null;
      wrapped.executionProfile = executionProfile;
      wrapped.createdAttachmentKeys = createdAttachmentKeys;
      throw wrapped;
    }
  }

  async function endpointInit(request) {
    let envelope = null;
    try {
      envelope = await parseRequest(request);
      const result = await dispatch(envelope);
      return response(200, envelope.action, envelope.request_id, result);
    }
    catch (error) {
      if (!(error instanceof ProtocolError)) Zotero.logError(error);
      const protocol = error instanceof ProtocolError
        ? error
        : new ProtocolError("internal bridge failure", 500, "internal_error");
      return response(
        protocol.status,
        envelope && envelope.action ? envelope.action : null,
        envelope && envelope.request_id ? envelope.request_id : null,
        null,
        {
          code: protocol.code,
          message: protocol.message,
          write_attempted: protocol.writeAttempted === true,
          commit_state: protocol.commitState || "not_started",
          inspection: protocol.inspection || null,
          execution_profile: protocol.executionProfile || null,
          created_attachment_keys: protocol.createdAttachmentKeys || [],
        },
      );
    }
  }

  async function writeCapability() {
    STATE.capabilityPath = PathUtils.join(Zotero.Profile.dir, CAPABILITY_FILE);
    const file = Zotero.File.pathToFile(STATE.capabilityPath);
    if (file.exists()) {
      if (file.isSymlink() || !file.isFile()) throw new Error("unsafe existing capability path");
    }
    STATE.capabilityToken = randomHex(32);
    STATE.keyID = randomHex(8);
    const descriptor = {
      schema: "ZoteroDeclarativeBridgeCapability/v1",
      endpoint: `http://127.0.0.1:${Zotero.Server.port}${ENDPOINT}`,
      key_id: STATE.keyID,
      capability_token: STATE.capabilityToken,
      created_at: new Date().toISOString(),
      zotero_version: Zotero.version,
      plugin_version: STATE.pluginVersion,
      expires_on_shutdown: true,
    };
    await IOUtils.writeUTF8(STATE.capabilityPath, JSON.stringify(descriptor, null, 2) + "\n");
    await IOUtils.setPermissions(STATE.capabilityPath, 0o600);
  }

  async function removeCapability() {
    if (!STATE.capabilityPath || !(await IOUtils.exists(STATE.capabilityPath))) return;
    try {
      const raw = await IOUtils.readUTF8(STATE.capabilityPath);
      const descriptor = JSON.parse(raw);
      if (descriptor.key_id === STATE.keyID) await IOUtils.remove(STATE.capabilityPath);
    }
    catch (error) { Zotero.logError(error); }
  }

  async function start(pluginVersion) {
    STATE.pluginVersion = pluginVersion;
    if (Zotero.Server.Endpoints[ENDPOINT]) throw new Error(`endpoint already registered: ${ENDPOINT}`);
    function BridgeEndpoint() {}
    BridgeEndpoint.prototype = {
      supportedMethods: ["POST"],
      supportedDataTypes: ["application/octet-stream"],
      init: endpointInit,
    };
    STATE.endpointConstructor = BridgeEndpoint;
    Zotero.Server.Endpoints[ENDPOINT] = BridgeEndpoint;
    try { await writeCapability(); }
    catch (error) {
      delete Zotero.Server.Endpoints[ENDPOINT];
      STATE.endpointConstructor = null;
      throw error;
    }
  }

  async function stop() {
    if (Zotero.Server.Endpoints[ENDPOINT] === STATE.endpointConstructor) delete Zotero.Server.Endpoints[ENDPOINT];
    await removeCapability();
    STATE.capabilityToken = null;
    STATE.nonces.clear();
    STATE.previews.clear();
  }

  const testing = globalThis.__ZOTERO_DECLARATIVE_BRIDGE_TEST__ === true
    ? Object.freeze({
      applyMetadataRepair,
      assertMetadataRepairParentClean,
      dispatch,
      freshMetadataRepairFailureInspection,
      metadataSerializerGuard,
      preflightMetadataRepair,
      resetState() {
        STATE.nonces.clear();
        STATE.previews.clear();
      },
    })
    : null;
  return testing ? {start, stop, testing} : {start, stop};
})();

async function startup({version, rootURI}) {
  Zotero.debug(`Zotero Declarative Bridge: startup ${version} on Zotero ${Zotero.version}`);
  try {
    if (!/^9\.0\./.test(String(Zotero.version))) {
      throw new Error(`unsupported Zotero runtime: ${Zotero.version}; expected 9.0.*`);
    }
    await Zotero.initializationPromise;
    Services.scriptloader.loadSubScript(rootURI + "bridge_core.js");
    await ZoteroDeclarativeBridge.start(version);
    Zotero.debug("Zotero Declarative Bridge: endpoint ready");
  }
  catch (error) {
    Zotero.logError(error);
    throw error;
  }
}

async function shutdown() {
  Zotero.debug("Zotero Declarative Bridge: shutdown");
  if (typeof ZoteroDeclarativeBridge !== "undefined") await ZoteroDeclarativeBridge.stop();
}

function install() {}
function uninstall() {}
