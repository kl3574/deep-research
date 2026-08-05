/* Generated only through zotero_attachment_repair.py. */
/*__ZOTERO_ATTACHMENT_REPAIR_CONFIG__*/

function repairAssertion(condition, message) {
  if (!condition) throw new Error(message);
}

function plainRepairError(error) {
  return {
    name: error && error.name ? String(error.name) : "Error",
    message: error && error.message ? String(error.message) : String(error),
  };
}

async function repairSHA256Bytes(bytes) {
  const view = bytes instanceof Uint8Array ? bytes : new Uint8Array(bytes);
  const digest = await crypto.subtle.digest("SHA-256", view);
  return "sha256:" + [...new Uint8Array(digest)]
    .map(value => value.toString(16).padStart(2, "0"))
    .join("");
}

async function repairFileEvidence(path) {
  repairAssertion(await IOUtils.exists(path), "bound file is missing");
  const bytes = await IOUtils.read(path);
  const magic = String.fromCharCode(...bytes.slice(0, 5));
  return {
    size_bytes: bytes.byteLength,
    sha256: await repairSHA256Bytes(bytes),
    magic,
    content_type: "application/pdf",
  };
}

async function repairTextSHA256(text) {
  return repairSHA256Bytes(new TextEncoder().encode(text));
}

async function repairWriteReport(report) {
  repairAssertion(!(await IOUtils.exists(CONFIG.reportPath)), "report path already exists");
  const serialized = JSON.stringify(report, null, 2);
  await IOUtils.writeUTF8(CONFIG.reportPath, serialized + "\n", {mode: "create"});
  return serialized;
}

async function repairCollectionPath(collection) {
  const path = [];
  const seen = new Set();
  let current = collection;
  while (current) {
    repairAssertion(!seen.has(current.id), "collection path contains a cycle");
    seen.add(current.id);
    repairAssertion(!current.deleted, "selected collection path contains a deleted collection");
    path.unshift({key: String(current.key), name: String(current.name)});
    current = current.parentID ? await Zotero.Collections.getAsync(current.parentID) : null;
  }
  return path;
}

async function repairResolveTarget(expected) {
  const pane = Zotero.getActiveZoteroPane();
  repairAssertion(pane, "active Zotero pane is unavailable");
  const selected = pane.getSelectedCollection();
  repairAssertion(selected, "no Zotero collection is selected");
  const library = Zotero.Libraries.get(expected.library_id);
  repairAssertion(library, "expected Zotero library is unavailable");
  const observed = {
    group_id: Number(library.libraryTypeID),
    library_id: Number(library.libraryID || library.id),
    library_name: String(library.name),
    local_collection_id: Number(selected.id),
    collection_key: String(selected.key),
    collection_path: await repairCollectionPath(selected),
    library_editable: library.editable === true,
    files_editable: library.filesEditable === true,
  };
  AttachmentRepairCore.verifyTarget(expected, observed);
  return {collection: selected, library, observed};
}

function repairLinkModeName(value) {
  const modes = {
    [Zotero.Attachments.LINK_MODE_IMPORTED_FILE]: "imported_file",
    [Zotero.Attachments.LINK_MODE_IMPORTED_URL]: "imported_url",
    [Zotero.Attachments.LINK_MODE_LINKED_FILE]: "linked_file",
  };
  return modes[value] || `unsupported_${value}`;
}

async function repairAttachmentEvidence(item) {
  const live = {
    key: String(item.key),
    version: Number(item.version),
    content_type: String(item.attachmentContentType || ""),
    link_mode: repairLinkModeName(item.attachmentLinkMode),
    readable_pdf: false,
    invalid_local_file: false,
    sha256: null,
    size_bytes: null,
  };
  let path = null;
  try {
    path = await item.getFilePathAsync();
  }
  catch (_error) {
    path = null;
  }
  if (path && await IOUtils.exists(path)) {
    const evidence = await repairFileEvidence(path);
    live.sha256 = evidence.sha256;
    live.size_bytes = evidence.size_bytes;
    live.readable_pdf = live.content_type === "application/pdf" && evidence.magic === "%PDF-";
    live.invalid_local_file = !live.readable_pdf;
  }
  return live;
}

async function repairParentAndAttachments(entry, targetContext) {
  const expected = entry.parent;
  const parent = await Zotero.Items.getByLibraryAndKeyAsync(
    targetContext.observed.library_id,
    expected.key,
  );
  repairAssertion(parent && !parent.deleted, `parent unavailable: ${expected.key}`);
  const collections = parent.getCollections();
  const observedParent = {
    key: String(parent.key),
    version: Number(parent.version),
    item_type: String(parent.itemType),
    doi: String(parent.getField("DOI") || ""),
    title: String(parent.getField("title") || ""),
    collection_key: targetContext.observed.collection_key,
    in_target_collection: collections.includes(targetContext.collection.id),
  };
  AttachmentRepairCore.verifyParent(expected, observedParent);
  const attachmentIDs = parent.getAttachments();
  let attachmentItems = attachmentIDs.length
    ? await Zotero.Items.getAsync(attachmentIDs)
    : [];
  if (!Array.isArray(attachmentItems)) attachmentItems = [attachmentItems];
  const attachments = [];
  for (const item of attachmentItems.filter(Boolean)) {
    repairAssertion(item.parentItemID === parent.id, "attachment parent drift");
    attachments.push(await repairAttachmentEvidence(item));
  }
  attachments.sort((left, right) => left.key.localeCompare(right.key));
  return {parent, attachments};
}

async function repairVerifyBoundInputs(manifest) {
  const baselineText = await Zotero.File.getContentsAsync(manifest.baseline.path, "UTF-8");
  repairAssertion(
    await repairTextSHA256(baselineText) === manifest.baseline.file_sha256,
    "bound baseline bytes changed",
  );
  const repairText = await Zotero.File.getContentsAsync(manifest.repair_source.path, "UTF-8");
  repairAssertion(
    await repairTextSHA256(repairText) === manifest.repair_source.file_sha256,
    "bound repair source bytes changed",
  );
}

async function repairPreflightEntry(entry, targetContext) {
  const live = await repairParentAndAttachments(entry, targetContext);
  if (entry.action === "metadata_only_skip") {
    const classification = AttachmentRepairCore.classifyLiveAttachments(
      entry.action,
      entry.expected_attachments,
      live.attachments,
      null,
    );
    return {entry, parentID: live.parent.id, classification};
  }
  const observedSource = await repairFileEvidence(entry.source_pdf.path);
  AttachmentRepairCore.verifyFileBinding(entry.source_pdf, observedSource);
  const classification = AttachmentRepairCore.classifyLiveAttachments(
    entry.action,
    entry.expected_attachments,
    live.attachments,
    entry.source_pdf.sha256,
  );
  return {entry, parentID: live.parent.id, classification};
}

async function repairPreflightAll(manifest, targetContext) {
  const results = [];
  for (const entry of manifest.entries) {
    results.push(await repairPreflightEntry(entry, targetContext));
  }
  return results;
}

function repairPublicPreflight(row) {
  return {
    parentKey: row.entry.parent.key,
    action: row.entry.action,
    decision: row.classification.decision,
    sameHashAttachmentKeys: row.classification.sameHashKeys,
    duplicateSameHashCount: row.classification.duplicateCount,
    invalidLocalAttachmentKeys: row.classification.invalidLocalKeys,
  };
}

async function repairReadbackCreated(created, entry, targetContext) {
  const attachment = await Zotero.Items.getByLibraryAndKeyAsync(
    targetContext.observed.library_id,
    created.attachmentKey,
  );
  repairAssertion(attachment && !attachment.deleted, "created attachment missing at readback");
  const parent = await Zotero.Items.getByLibraryAndKeyAsync(
    targetContext.observed.library_id,
    entry.parent.key,
  );
  repairAssertion(parent && attachment.parentItemID === parent.id, "created attachment parent mismatch");
  const path = await attachment.getFilePathAsync();
  const evidence = await repairFileEvidence(path);
  const directCollections = attachment.getCollections();
  const observed = {
    parent_key: String(parent.key),
    content_type: String(attachment.attachmentContentType || ""),
    size_bytes: evidence.size_bytes,
    sha256: evidence.sha256,
    magic: evidence.magic,
    parent_in_target_collection: parent.getCollections().includes(targetContext.collection.id),
    direct_collection_count: directCollections.length,
  };
  AttachmentRepairCore.verifyReadback(
    {
      parent_key: entry.parent.key,
      size_bytes: entry.source_pdf.size_bytes,
      sha256: entry.source_pdf.sha256,
    },
    observed,
  );
  const live = await repairParentAndAttachments(entry, targetContext);
  const classification = AttachmentRepairCore.classifyLiveAttachments(
    entry.action,
    entry.expected_attachments,
    live.attachments,
    entry.source_pdf.sha256,
  );
  repairAssertion(
    classification.decision === "no_op_same_hash"
      && classification.sameHashKeys.length === 1
      && classification.sameHashKeys[0] === String(attachment.key),
    "immediate readback did not confirm exactly one bound PDF attachment",
  );
  return {
    parentKey: entry.parent.key,
    attachmentKey: String(attachment.key),
    contentType: observed.content_type,
    sizeBytes: observed.size_bytes,
    sha256: observed.sha256,
    collectionInheritance: {
      parentInTargetCollection: true,
      exactParent: true,
      directChildCollectionCount: observed.direct_collection_count,
    },
  };
}

async function repairInspectImportOutcome(rows, manifest) {
  const presentByParent = {};
  let inspectionFailed = false;
  for (const row of rows) {
    const entry = row.entry;
    try {
      const targetContext = await repairResolveTarget(manifest.target);
      const live = await repairParentAndAttachments(entry, targetContext);
      const classification = AttachmentRepairCore.classifyLiveAttachments(
        entry.action,
        entry.expected_attachments,
        live.attachments,
        entry.source_pdf.sha256,
      );
      presentByParent[entry.parent.key] = classification.decision === "no_op_same_hash"
        && classification.sameHashKeys.length === 1;
    }
    catch (_error) {
      inspectionFailed = true;
      presentByParent[entry.parent.key] = false;
    }
  }
  const planned = rows.map(row => row.entry.parent.key);
  return {
    outcome: AttachmentRepairCore.classifyImportOutcome(
      planned,
      presentByParent,
      inspectionFailed,
    ),
    presentByParent,
  };
}

async function runAttachmentRepair() {
  const startedAt = new Date().toISOString();
  let phase = "load_manifest";
  let target = null;
  let preflight = [];
  let readyRows = [];
  let writeAttempted = false;
  let created = [];
  try {
    repairAssertion(CONFIG && typeof CONFIG === "object", "runner configuration missing");
    const manifestText = await Zotero.File.getContentsAsync(CONFIG.manifestPath, "UTF-8");
    repairAssertion(
      await repairTextSHA256(manifestText) === CONFIG.manifestSHA256,
      "manifest bytes changed after rendering",
    );
    const manifest = JSON.parse(manifestText);
    repairAssertion(manifest.schema === "ZoteroAttachmentRepairManifest/v1", "manifest schema mismatch");
    repairAssertion(
      manifest.manifest_digest_sha256 === CONFIG.manifestDigestSHA256,
      "manifest digest binding mismatch",
    );
    repairAssertion(
      manifest.summary.attach_missing_pdf === CONFIG.expectedAttachCount
        && manifest.summary.metadata_only_skip === CONFIG.expectedMetadataSkipCount,
      "manifest summary binding mismatch",
    );
    if (CONFIG.apply) {
      repairAssertion(
        Array.isArray(manifest.entries) && manifest.entries.length === 1,
        "Desktop fallback apply requires exactly one parent entry",
      );
    }
    phase = "verify_bound_inputs";
    await repairVerifyBoundInputs(manifest);
    phase = "verify_target";
    let targetContext = await repairResolveTarget(manifest.target);
    target = targetContext.observed;
    phase = "preflight_all";
    preflight = await repairPreflightAll(manifest, targetContext);
    readyRows = preflight.filter(row => row.classification.decision === "ready_to_attach");
    if (!CONFIG.apply) {
      return {
        schema: "ZoteroAttachmentRepairReport/v1",
        status: readyRows.length ? "preview_ready" : "no_changes",
        mode: "preview",
        startedAt,
        completedAt: new Date().toISOString(),
        target,
        counts: {
          total: preflight.length,
          readyToAttach: readyRows.length,
          noOpSameHash: preflight.filter(row => row.classification.decision === "no_op_same_hash").length,
          metadataOnlySkip: preflight.filter(row => row.classification.decision === "metadata_only_skip").length,
        },
        preflight: preflight.map(repairPublicPreflight),
        writeAttempted: false,
        writePerformed: false,
        commitState: "not_started",
      };
    }
    if (!readyRows.length) {
      return {
        schema: "ZoteroAttachmentRepairReport/v1",
        status: "no_changes",
        mode: "apply",
        startedAt,
        completedAt: new Date().toISOString(),
        target,
        counts: {total: preflight.length, readyToAttach: 0},
        preflight: preflight.map(repairPublicPreflight),
        writeAttempted: false,
        writePerformed: false,
        commitState: "not_started",
        readback: [],
      };
    }
    repairAssertion(readyRows.length === 1, "Desktop fallback apply supports one attachment import");
    phase = "write_repreflight";
    targetContext = await repairResolveTarget(manifest.target);
    const repeated = await repairPreflightAll(manifest, targetContext);
    const firstDecisions = preflight.map(row => [row.entry.parent.key, row.classification.decision]);
    const repeatedDecisions = repeated.map(row => [row.entry.parent.key, row.classification.decision]);
    repairAssertion(
      JSON.stringify(firstDecisions) === JSON.stringify(repeatedDecisions),
      "preflight decisions changed immediately before import",
    );
    const repeatedReady = repeated.filter(
      row => row.classification.decision === "ready_to_attach",
    );
    repairAssertion(repeatedReady.length === 1, "exactly one attachment must remain ready to import");
    const row = repeatedReady[0];
    phase = "import_attachment";
    writeAttempted = true;
    const attachment = await Zotero.Attachments.importFromFile({
      file: row.entry.source_pdf.path,
      libraryID: manifest.target.library_id,
      parentItemID: row.parentID,
    });
    repairAssertion(attachment && attachment.key, "attachment import returned no item key");
    const createdItem = {
      parentKey: row.entry.parent.key,
      attachmentKey: String(attachment.key),
    };
    created = [createdItem];
    phase = "immediate_readback";
    const readbackItem = await repairReadbackCreated(createdItem, row.entry, targetContext);
    const readback = [readbackItem];
    return {
      schema: "ZoteroAttachmentRepairReport/v1",
      status: "completed",
      mode: "apply",
      startedAt,
      completedAt: new Date().toISOString(),
      target,
      counts: {
        total: preflight.length,
        attached: readback.length,
        noOpSameHash: preflight.filter(row => row.classification.decision === "no_op_same_hash").length,
        metadataOnlySkip: preflight.filter(row => row.classification.decision === "metadata_only_skip").length,
      },
      preflight: preflight.map(repairPublicPreflight),
      writeAttempted: true,
      writePerformed: true,
      commitState: "committed",
      readback,
    };
  }
  catch (error) {
    let inspection = null;
    if (writeAttempted && readyRows.length) {
      try {
        const manifestText = await Zotero.File.getContentsAsync(CONFIG.manifestPath, "UTF-8");
        inspection = await repairInspectImportOutcome(readyRows, JSON.parse(manifestText));
      }
      catch (_inspectionError) {
        inspection = {outcome: "unknown", presentByParent: {}};
      }
    }
    const commitState = inspection ? inspection.outcome : "not_started";
    return {
      schema: "ZoteroAttachmentRepairReport/v1",
      status: commitState === "committed" ? "readback_failed" : "failed",
      mode: CONFIG && CONFIG.apply ? "apply" : "preview",
      phase,
      startedAt,
      completedAt: new Date().toISOString(),
      target,
      preflight: preflight.map(repairPublicPreflight),
      writeAttempted,
      writePerformed: commitState === "committed",
      commitState,
      writeInspection: inspection,
      createdItemKeysObservedBeforeFailure: created.map(item => item.attachmentKey),
      error: plainRepairError(error),
    };
  }
}

await (async () => {
  try {
    repairAssertion(!(await IOUtils.exists(CONFIG.reportPath)), "report path already exists");
    const report = await runAttachmentRepair();
    return await repairWriteReport(report);
  }
  catch (error) {
    return JSON.stringify({
      status: "report_persistence_failed",
      reportPath: CONFIG.reportPath,
      error: plainRepairError(error),
    }, null, 2);
  }
})();
