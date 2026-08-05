/* global Zotero, Services, IOUtils, PathUtils, crypto, TextEncoder, Ci */

var ZoteroDeclarativeBridge = (() => {
  "use strict";

  const ENDPOINT = "/deep-research/transaction/v1";
  const CAPABILITY_FILE = "zotero-declarative-bridge-capability.json";
  const MAX_BODY_BYTES = 8 * 1024 * 1024;
  const MAX_PDF_BYTES = 256 * 1024 * 1024;
  const REQUEST_SKEW_MS = 120000;
  const NONCE_TTL_MS = 300000;
  const PREVIEW_TTL_MS = 900000;
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
      || !["probe", "preview", "apply", "readback"].includes(envelope.action)
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
    return {
      size_bytes: bytes.byteLength,
      sha256: await sha256Bytes(bytes),
      magic: String.fromCharCode(...bytes.slice(0, 5)),
    };
  }

  async function attachmentEvidence(item) {
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
    return result;
  }

  async function parentState(entry, target) {
    const parent = await Zotero.Items.getByLibraryAndKeyAsync(target.observed.library_id, entry.parent.key);
    if (!parent || parent.deleted || !parent.isRegularItem()) throw new ProtocolError(`parent unavailable: ${entry.parent.key}`, 409, "parent_drift");
    const observedParent = {
      key: String(parent.key),
      version: Number(parent.version),
      item_type: String(parent.itemType),
      title: String(parent.getField("title") || ""),
      doi: ZoteroDeclarativeBridgeCore.normalizeDOI(String(parent.getField("DOI") || "")),
      target_membership: parent.getCollections().includes(target.collection.id),
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
      noteStates.push({key: String(note.key), version: Number(note.version), sha256: await sha256Text(note.getNote())});
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
      else if (operation.type === "ensure_child_note") {
        if (await sha256Text(operation.new_html) !== operation.new_sha256) throw new ProtocolError("new note hash mismatch", 409, "source_drift");
        decisions.push({...ZoteroDeclarativeBridgeCore.classifyNote(operation, live.noteStates), type: operation.type});
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
    return {
      parent_key: row.entry.parent.key,
      parent_version: row.live.observedParent.version,
      target_membership: row.live.observedParent.target_membership,
      child_notes: row.live.noteStates,
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

  async function preflight(manifest) {
    await validateManifestDigest(manifest);
    const target = await resolveTarget(manifest.target);
    const rows = [];
    for (const entry of manifest.entries) rows.push(await classifyEntry(entry, target));
    const publicState = {target: target.observed, entries: rows.map(publicEntry)};
    return {
      target,
      rows,
      publicState,
      stateSHA256: await sha256Value(publicState),
      allSatisfied: rows.every(row => row.allSatisfied),
    };
  }

  async function applyRows(preflightResult) {
    for (const row of preflightResult.rows) {
      for (let index = 0; index < row.entry.operations.length; index++) {
        const operation = row.entry.operations[index];
        const decision = row.decisions[index];
        if (decision.decision === "satisfied") continue;
        if (operation.type === "ensure_collection_membership") {
          row.live.parent.addToCollection(preflightResult.target.collection.id);
          await row.live.parent.save({skipDateModifiedUpdate: true});
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
        }
      }
    }
  }

  async function dispatch(envelope) {
    const action = envelope.action;
    if (action === "probe") {
      if (Object.keys(envelope.payload).length) throw new ProtocolError("probe payload must be empty");
      return {
        status: "available",
        plugin_version: STATE.pluginVersion,
        zotero_version: Zotero.version,
        endpoint: ENDPOINT,
        operations: ["ensure_collection_membership", "ensure_child_note", "ensure_pdf_attachment"],
        arbitrary_javascript: false,
        sqlite_access: false,
      };
    }
    const allowedPayload = action === "apply"
      ? ["manifest", "preview_id", "preview_token", "state_sha256"]
      : ["manifest"];
    const actualPayload = Object.keys(envelope.payload).sort();
    if (ZoteroDeclarativeBridgeCore.stableStringify(actualPayload) !== ZoteroDeclarativeBridgeCore.stableStringify([...allowedPayload].sort())) {
      throw new ProtocolError("payload keys differ");
    }
    const manifest = envelope.payload.manifest;
    const before = await preflight(manifest);
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
    try {
      writeAttempted = true;
      await Zotero.DB.executeTransaction(async () => {
        const repeated = await preflight(manifest);
        if (repeated.stateSHA256 !== before.stateSHA256) throw new ProtocolError("state changed at transaction start", 409, "transaction_drift");
        await applyRows(repeated);
      });
      const after = await preflight(manifest);
      if (!after.allSatisfied) throw new ProtocolError("committed readback mismatch", 500, "readback_mismatch");
      return {
        status: "completed",
        manifest_sha256: manifest.manifest_sha256,
        state_sha256: after.stateSHA256,
        write_attempted: true,
        commit_state: "committed",
        state: after.publicState,
      };
    }
    catch (error) {
      let inspection = null;
      let commitState = "unknown";
      try {
        inspection = await preflight(manifest);
        const satisfied = inspection.rows.filter(row => row.allSatisfied).length;
        commitState = satisfied === 0 ? "rolled_back" : satisfied === inspection.rows.length ? "committed" : "partial_commit";
      }
      catch (_inspectionError) {}
      const wrapped = new ProtocolError(
        `transaction failed; commit_state=${commitState}`,
        error instanceof ProtocolError ? error.status : 500,
        error instanceof ProtocolError ? error.code : "transaction_failed",
      );
      wrapped.writeAttempted = writeAttempted;
      wrapped.commitState = commitState;
      wrapped.inspection = inspection ? inspection.publicState : null;
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

  return {start, stop};
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
