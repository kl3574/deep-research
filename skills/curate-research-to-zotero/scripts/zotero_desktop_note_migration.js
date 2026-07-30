/*
 * Template for Zotero Desktop: Tools -> Developer -> Run JavaScript.
 *
 * Do not paste this template directly. Generate a configured runner with
 * render_zotero_desktop_runner.py. The generated script performs a complete
 * read-only preflight before any Zotero write and emits a JSON report.
 */

const CONFIG = null; // __DEEP_RESEARCH_ZOTERO_CONFIG__

function assertion(condition, message, details = undefined) {
  if (condition) {
    return;
  }
  const error = new Error(message);
  error.details = details;
  throw error;
}

function sha256Bytes(data) {
  const hash = Components.classes["@mozilla.org/security/hash;1"]
    .createInstance(Components.interfaces.nsICryptoHash);
  hash.init(hash.SHA256);
  hash.update(data, data.length);
  const binary = hash.finish(false);
  return Array.from(
    binary,
    (_character, index) => binary.charCodeAt(index).toString(16).padStart(2, "0"),
  ).join("");
}

function sha256Text(text) {
  return sha256Bytes(new TextEncoder().encode(text));
}

function stableJSONStringify(value) {
  if (value === null || typeof value !== "object") {
    assertion(
      value !== undefined
        && (
          typeof value === "string"
          || typeof value === "number"
          || typeof value === "boolean"
          || value === null
        ),
      "parent item snapshot contains a non-JSON value",
    );
    return JSON.stringify(value);
  }
  if (Array.isArray(value)) {
    return `[${value.map(stableJSONStringify).join(",")}]`;
  }
  return `{${
    Object.keys(value)
      .sort()
      .map(key =>
        `${JSON.stringify(key)}:${stableJSONStringify(value[key])}`
      )
      .join(",")
  }}`;
}

function parentDataSnapshotSHA256(parentData) {
  assertion(
    parentData
      && typeof parentData === "object"
      && !Array.isArray(parentData),
    "parent item data is unavailable for snapshot verification",
  );
  const excludedFields = new Set([
    "accessDate",
    "citationKey",
    "collections",
    "createdByUserID",
    "dateAdded",
    "dateModified",
    "deleted",
    "inPublications",
    "key",
    "lastModifiedByUserID",
    "libraryCatalog",
    "relations",
    "synced",
    "tags",
    "version",
  ]);
  const snapshot = Object.fromEntries(
    Object.entries(parentData).filter(
      ([key]) => !excludedFields.has(key),
    ),
  );
  return sha256Text(stableJSONStringify({
    data: snapshot,
    schema: "zotero-item-bibliographic-v1",
  }));
}

const fileVerificationCache = new Map();

async function verifyPDFFile(
  path,
  expectedSHA256,
  noteKey,
  forceRead = false,
) {
  assertion(
    typeof path === "string"
      && path.startsWith("/")
      && /^[0-9a-f]{64}$/.test(expectedSHA256),
    `${noteKey}: PDF path or SHA-256 is invalid`,
  );
  let verified = fileVerificationCache.get(path);
  if (!verified || forceRead) {
    const bytes = await IOUtils.read(path);
    const magic = String.fromCharCode(...bytes.slice(0, 5));
    verified = {
      magic,
      sha256: sha256Bytes(bytes),
    };
    fileVerificationCache.set(path, verified);
  }
  assertion(verified.magic === "%PDF-", `${noteKey}: local file is not a PDF`);
  assertion(
    verified.sha256 === expectedSHA256,
    `${noteKey}: local PDF hash changed`,
    { observed: verified.sha256, expected: expectedSHA256 },
  );
}

function expectedAttachmentLinkMode(linkMode) {
  const expectedLinkModes = {
    imported_file: Zotero.Attachments.LINK_MODE_IMPORTED_FILE,
    imported_url: Zotero.Attachments.LINK_MODE_IMPORTED_URL,
    linked_file: Zotero.Attachments.LINK_MODE_LINKED_FILE,
  };
  assertion(
    Object.hasOwn(expectedLinkModes, linkMode),
    `unsupported PDF attachment link mode: ${linkMode}`,
  );
  return expectedLinkModes[linkMode];
}

async function verifyAttachmentFileBinding(
  attachment,
  expectedPath,
  noteKey,
) {
  const observedPath = await attachment.getFilePathAsync();
  assertion(
    typeof observedPath === "string" && observedPath,
    `${noteKey}: approved PDF attachment has no local file path`,
  );
  const normalizedObserved = PathUtils.normalize(observedPath);
  const normalizedExpected = PathUtils.normalize(expectedPath);
  assertion(
    normalizedObserved === normalizedExpected,
    `${noteKey}: approved PDF attachment file path changed`,
    { observed: normalizedObserved, expected: normalizedExpected },
  );
}

function normalizedNoteHTML(text) {
  const withoutControlCharacters = text.replace(
    /[\u0000-\u0008\u000B\u000C\u000E-\u001F\u007F]/g,
    "",
  );
  assertion(
    withoutControlCharacters === text,
    "staged note contains control characters that Zotero would remove",
  );
  return text.trim();
}

function isCanonicalTableRow(node) {
  return node && node.tag === "tr";
}

function isCanonicalTableSection(node) {
  return (
    node
    && node.tag
    && ["thead", "tbody", "tfoot"].includes(node.tag)
    && node.attributes.length === 0
    && node.children.every(isCanonicalTableRow)
  );
}

function isAttributeFreeBR(node) {
  if (!node || node.nodeType !== 1) {
    return false;
  }
  const tag = node.tagName ? node.tagName.toLowerCase() : "";
  return tag === "br" && node.attributes.length === 0;
}

function canonicalizeTableChildren(children) {
  const normalizedTableChildren = [];
  const directRows = [];
  const flushDirectRows = () => {
    if (!directRows.length) {
      return;
    }
    normalizedTableChildren.push({
      tag: "tbody",
      attributes: [],
      children: [...directRows],
    });
    directRows.length = 0;
  };
  for (const child of children) {
    if (isCanonicalTableRow(child) || isCanonicalTableSection(child)) {
      directRows.push(...(
        isCanonicalTableRow(child)
        ? [child]
        : child.children
      ));
      continue;
    }
    flushDirectRows();
    normalizedTableChildren.push(child);
  }
  flushDirectRows();
  return normalizedTableChildren;
}

function semanticHTMLProjection(html) {
  const document = new DOMParser().parseFromString(html, "text/html");
  const isHTMLASCIIWhitespace = value =>
    !/[^ \t\r\n\f]/u.test(value);
  const collapseHTMLASCIIWhitespace = value =>
    value.replace(/[ \t\r\n\f]+/gu, " ");
  const trimHTMLASCIIWhitespace = value =>
    value.replace(/^[ \t\r\n\f]+|[ \t\r\n\f]+$/gu, "");
  const meaningfulBodyNodes = [...document.body.childNodes].filter(node =>
    node.nodeType === 1
      || (
        node.nodeType === 3
        && !isHTMLASCIIWhitespace(node.nodeValue || "")
      )
  );
  assertion(
    meaningfulBodyNodes.length === 1
      && meaningfulBodyNodes[0].nodeType === 1,
    "note HTML must contain exactly one semantic root",
  );
  const root = meaningfulBodyNodes[0];
  const normalizeText = value =>
    trimHTMLASCIIWhitespace(collapseHTMLASCIIWhitespace(value));
  const blockTags = new Set([
    "address", "article", "aside", "blockquote", "div", "dl", "fieldset",
    "figcaption", "figure", "footer", "form", "h1", "h2", "h3", "h4", "h5",
    "h6", "header", "hr", "li", "main", "nav", "ol", "p", "pre", "section",
    "table", "tbody", "td", "tfoot", "th", "thead", "tr", "ul",
  ]);
  const isBlockNode = node =>
    node
    && node.nodeType === 1
    && blockTags.has(node.tagName.toLowerCase());
  const neighboringSemanticNode = (node, direction) => {
    let current = node[direction];
    while (
      current
      && current.nodeType === 3
      && isHTMLASCIIWhitespace(current.nodeValue || "")
    ) {
      current = current[direction];
    }
    return current;
  };
  const elementPreservesWhitespace = element => {
    if (element.closest("pre, textarea")) {
      return true;
    }
    let current = element;
    while (current) {
      const style = current.getAttribute("style") || "";
      if (
        (
          current.style
          && current.style.getPropertyValue("white-space") !== ""
        )
        || style.includes("/*")
        || style.includes("\\")
        || /(?:^|;)[ \t\r\n\f]*white-space[ \t\r\n\f]*:/iu.test(style)
      ) {
        return true;
      }
      current = current.parentElement;
    }
    return false;
  };
  const canonicalNode = node => {
    if (node.nodeType === 3) {
      const raw = node.nodeValue || "";
      if (
        node.parentElement
        && elementPreservesWhitespace(node.parentElement)
      ) {
        return raw ? { text: raw } : null;
      }
      let value = collapseHTMLASCIIWhitespace(raw);
      if (isHTMLASCIIWhitespace(value)) {
        const previous = neighboringSemanticNode(node, "previousSibling");
        const next = neighboringSemanticNode(node, "nextSibling");
        if (isAttributeFreeBR(previous) || isAttributeFreeBR(next)) {
          return null;
        }
        if (
          !previous
          || !next
          || isBlockNode(previous)
          || isBlockNode(next)
        ) {
          return null;
        }
        return { text: " " };
      }
      const previous = neighboringSemanticNode(node, "previousSibling");
      const next = neighboringSemanticNode(node, "nextSibling");
      if (!previous || isBlockNode(previous)) {
        value = value.replace(/^[ \t\r\n\f]+/u, "");
      }
      if (!next || isBlockNode(next)) {
        value = value.replace(/[ \t\r\n\f]+$/u, "");
      }
      return { text: value };
    }
    if (node.nodeType !== 1) {
      return null;
    }
    const tag = node.tagName.toLowerCase();
    const attributes = [...node.attributes]
      .map(attribute => [attribute.name, attribute.value])
      .sort((left, right) => left[0].localeCompare(right[0]));
    let children = [...node.childNodes]
      .map(canonicalNode)
      .filter(child => child !== null);

    // Zotero wraps otherwise bare table-cell content in a single paragraph.
    // Treat only that exact wrapper as storage normalization. Every other
    // element name, attribute, nesting relation, and ordered text node remains
    // part of the semantic digest.
    if (
      (tag === "th" || tag === "td")
      && children.length === 1
      && children[0].tag === "p"
      && children[0].attributes.length === 0
    ) {
      children = children[0].children;
    }
    if (tag === "table") {
      children = canonicalizeTableChildren(children);
    }
    return { tag, attributes, children };
  };
  const textChunks = [];
  const visit = node => {
    if (node.nodeType === 3) {
      const text = normalizeText(node.nodeValue || "");
      if (text) {
        textChunks.push(text);
      }
      return;
    }
    for (const child of node.childNodes || []) {
      visit(child);
    }
  };
  visit(root);
  const elementText = element => normalizeText(element.textContent || "");
  return {
    root: {
      tag: root.tagName.toLowerCase(),
      schemaVersion: root.getAttribute("data-schema-version"),
    },
    structure: canonicalNode(root),
    textChunks,
    headings: [...root.querySelectorAll("h1, h2")].map(element => ({
      tag: element.tagName.toLowerCase(),
      text: elementText(element),
    })),
    tables: [...root.querySelectorAll("table")].map(table =>
      [...table.querySelectorAll("tr")].map(row =>
        [...row.querySelectorAll(":scope > th, :scope > td")].map(cell => ({
          tag: cell.tagName.toLowerCase(),
          text: elementText(cell),
        })),
      ),
    ),
    math: [...root.querySelectorAll("pre.math")].map(elementText),
    links: [...root.querySelectorAll("a")].map(element => ({
      href: element.getAttribute("href"),
      text: elementText(element),
    })),
    images: [...root.querySelectorAll("img")].map(element => ({
      src: element.getAttribute("src"),
      attachmentKey: element.getAttribute("data-attachment-key"),
      alt: element.getAttribute("alt"),
    })),
  };
}

function semanticHTMLSHA256(html) {
  return sha256Text(JSON.stringify(semanticHTMLProjection(html)));
}

function plainError(error) {
  return {
    name: error && error.name ? String(error.name) : "Error",
    message: error && error.message ? String(error.message) : String(error),
    details: error && error.details !== undefined ? error.details : undefined,
  };
}

async function writeReport(report) {
  await assertFreshReportPath();
  const serialized = JSON.stringify(report, null, 2);
  await IOUtils.writeUTF8(
    CONFIG.reportPath,
    `${serialized}\n`,
    { mode: "create" },
  );
  return serialized;
}

async function assertFreshReportPath() {
  assertion(
    !(await IOUtils.exists(CONFIG.reportPath)),
    "report path already exists; choose a new evidence path",
  );
}

async function collectionPath(collection, forceReload = false) {
  const names = [];
  const seen = new Set();
  let current = collection;
  while (current) {
    if (forceReload) {
      await current.reload(["primaryData"], true);
    }
    assertion(!seen.has(current.id), "collection hierarchy contains a cycle");
    seen.add(current.id);
    assertion(!current.deleted, `collection ${current.key} is deleted`);
    names.unshift(current.name);
    current = current.parentID
      ? await Zotero.Collections.getAsync(current.parentID)
      : null;
  }
  return names;
}

function exactArrayEqual(left, right) {
  return Array.isArray(left)
    && Array.isArray(right)
    && left.length === right.length
    && left.every((value, index) => value === right[index]);
}

function validatedKeyInventory(value, label, { nonempty = false } = {}) {
  assertion(Array.isArray(value), `${label} is not an array`);
  assertion(!nonempty || value.length > 0, `${label} is empty`);
  const keys = value.map(key => String(key || ""));
  assertion(
    keys.every(key => /^[A-Z0-9]{8}$/.test(key)),
    `${label} contains an invalid item key`,
  );
  assertion(
    exactArrayEqual(keys, [...keys].sort())
      && new Set(keys).size === keys.length,
    `${label} must be sorted and duplicate-free`,
  );
  return keys;
}

function validateManifestContract(manifest) {
  const collectionItemInventory = validatedKeyInventory(
    manifest.collection_item_inventory,
    "collection_item_inventory",
    { nonempty: true },
  );
  assertion(Array.isArray(manifest.entries), "manifest entries are missing");
  assertion(
    manifest.entries.every(entry => entry && typeof entry === "object"),
    "manifest contains a non-object entry",
  );
  const parentKeys = manifest.entries.map(entry => String(entry.parent_key || ""));
  assertion(
    exactArrayEqual([...parentKeys].sort(), collectionItemInventory),
    "manifest entries do not exactly cover collection_item_inventory",
  );
  const allowedStatuses = new Set([
    "staged_verified",
    "unchanged_verified",
    "create_verified",
    "staged_invalid",
    "no_existing_note",
    "blocked_multiple_notes",
    "blocked_multiple_pdfs",
  ]);
  for (const entry of manifest.entries) {
    const parentKey = String(entry.parent_key || "");
    const noteKey = String(entry.note_key || "");
    assertion(
      allowedStatuses.has(entry.status),
      `${parentKey}: unsupported migration status`,
    );
    const childNoteInventory = validatedKeyInventory(
      entry.child_note_inventory,
      `${parentKey}: child_note_inventory`,
    );
    const childAttachmentInventory = validatedKeyInventory(
      entry.child_attachment_inventory,
      `${parentKey}: child_attachment_inventory`,
    );
    const childItemInventory = entry.child_item_inventory === undefined
      ? null
      : validatedKeyInventory(
        entry.child_item_inventory,
        `${parentKey}: child_item_inventory`,
      );
    if (childItemInventory !== null) {
      assertion(
        exactArrayEqual(
          childItemInventory,
          [...childNoteInventory, ...childAttachmentInventory].sort(),
        ),
        `${parentKey}: child_item_inventory is inconsistent`,
      );
    }
    if (entry.status === "no_existing_note") {
      assertion(
        childNoteInventory.length === 0,
        `${parentKey}: no_existing_note has live note keys in the manifest`,
      );
    }
    if (
      entry.status === "staged_verified"
      || entry.status === "unchanged_verified"
    ) {
      assertion(
        entry.expected_parent_key === parentKey,
        `${noteKey}: parent_key and expected_parent_key differ`,
      );
      assertion(
        typeof entry.old_sha256 === "string"
          && /^[0-9a-f]{64}$/.test(entry.old_sha256),
        `${noteKey}: old SHA-256 is invalid`,
      );
      assertion(
        typeof entry.new_sha256 === "string"
          && /^[0-9a-f]{64}$/.test(entry.new_sha256),
        `${noteKey}: new SHA-256 is invalid`,
      );
      if (entry.status === "unchanged_verified") {
        assertion(
          entry.old_sha256 === entry.new_sha256,
          `${noteKey}: unchanged note hashes are inconsistent`,
        );
      }
      assertion(
        exactArrayEqual(childNoteInventory, [noteKey]),
        `${noteKey}: staged parent must have exactly the approved child note`,
      );
      assertion(
        childAttachmentInventory.includes(entry.pdf_attachment_key),
        `${noteKey}: approved PDF attachment is absent from child inventory`,
      );
    }
    if (entry.status === "create_verified") {
      assertion(
        entry.expected_parent_key === parentKey,
        `${parentKey}: create expected_parent_key differs`,
      );
      assertion(
        childNoteInventory.length === 0,
        `${parentKey}: create_verified requires zero existing notes`,
      );
      assertion(
        childItemInventory !== null,
        `${parentKey}: create_verified requires a complete child inventory`,
      );
      assertion(
        Number.isInteger(entry.parent_version) && entry.parent_version > 0,
        `${parentKey}: create parent_version is invalid`,
      );
      assertion(
        entry.parent_data_snapshot_schema === "zotero-item-bibliographic-v1"
          && typeof entry.parent_data_snapshot_sha256 === "string"
          && /^[0-9a-f]{64}$/.test(entry.parent_data_snapshot_sha256),
        `${parentKey}: create parent data snapshot is invalid`,
      );
      assertion(
        childAttachmentInventory.includes(entry.pdf_attachment_key),
        `${parentKey}: approved PDF attachment is absent from child inventory`,
      );
    }
  }
  const blocking = manifest.entries.filter(entry =>
    ["staged_invalid", "blocked_multiple_notes", "blocked_multiple_pdfs"]
      .includes(entry.status)
  );
  assertion(
    blocking.length === 0,
    "manifest contains invalid or ambiguous entries",
    blocking.map(entry => ({
      parentKey: entry.parent_key,
      status: entry.status,
    })),
  );
  return {
    collectionItemInventory,
    entries: manifest.entries,
  };
}

async function liveCollectionItemInventory(collection, forceReload = false) {
  if (forceReload) {
    await collection.reload(["childItems"], true);
  }
  await collection.loadDataType("childItems");
  return collection
    .getChildItems(false, false)
    .filter(item => !item.deleted)
    .map(item => item.key)
    .sort();
}

async function liveChildInventory(parent, forceReload = false) {
  if (forceReload) {
    await parent.reload(["primaryData", "childItems"], true);
  }
  await parent.loadDataType("childItems");
  const noteItems = await Zotero.Items.getAsync(parent.getNotes(false));
  const attachmentItems = await Zotero.Items.getAsync(parent.getAttachments(false));
  const validChildren = (items, expectedType) => items
    .filter(item => item && !item.deleted)
    .map(item => {
      assertion(
        item.parentItemKey === parent.key
          && (
            expectedType === "note"
              ? item.isNote()
              : item.isAttachment()
          ),
        `${parent.key}: live ${expectedType} child has a different parent`,
        { childKey: item.key, observedParentKey: item.parentItemKey },
      );
      return item.key;
    })
    .sort();
  const notes = validChildren(noteItems, "note");
  const attachments = validChildren(attachmentItems, "attachment");
  return {
    notes,
    attachments,
    items: [...notes, ...attachments].sort(),
  };
}

async function verifyLiveManifestInventory(
  manifestContract,
  targetContext,
  forceReload = false,
  createdNoteKeysByParent = new Map(),
) {
  const observedCollectionInventory = await liveCollectionItemInventory(
    targetContext.collection,
    forceReload,
  );
  assertion(
    exactArrayEqual(
      observedCollectionInventory,
      manifestContract.collectionItemInventory,
    ),
    "live collection item inventory differs from the staged manifest",
    {
      observed: observedCollectionInventory,
      expected: manifestContract.collectionItemInventory,
    },
  );
  for (const entry of manifestContract.entries) {
    const parentKey = String(entry.parent_key);
    const parent = await Zotero.Items.getByLibraryAndKeyAsync(
      targetContext.library.libraryID,
      parentKey,
    );
    assertion(parent, `${parentKey}: live collection parent is missing`);
    if (forceReload) {
      await parent.reload(["primaryData", "collections", "childItems"], true);
    }
    await parent.loadDataType("collections");
    await parent.loadDataType("childItems");
    assertion(
      parent
        && parent.isRegularItem()
        && !parent.deleted
        && parent.getCollections().includes(targetContext.collection.id),
      `${parentKey}: live collection parent identity or membership changed`,
    );
    const observed = await liveChildInventory(parent, false);
    const createdNoteKey = createdNoteKeysByParent.get(parentKey);
    const expectedNotes = createdNoteKey
      ? [...entry.child_note_inventory, createdNoteKey].sort()
      : entry.child_note_inventory;
    const expectedItems = entry.child_item_inventory === undefined
      ? null
      : (
        createdNoteKey
          ? [...entry.child_item_inventory, createdNoteKey].sort()
          : entry.child_item_inventory
      );
    assertion(
      exactArrayEqual(observed.notes, expectedNotes)
        && exactArrayEqual(
          observed.attachments,
          entry.child_attachment_inventory,
        )
        && (
          expectedItems === null
          || exactArrayEqual(observed.items, expectedItems)
        ),
      `${parentKey}: live child-note or attachment inventory changed`,
      {
        observed,
        expected: {
          notes: expectedNotes,
          attachments: entry.child_attachment_inventory,
          items: expectedItems,
        },
      },
    );
  }
  return {
    collectionItemCount: observedCollectionInventory.length,
    inventorySHA256: sha256Text(JSON.stringify({
      collection: manifestContract.collectionItemInventory,
      children: manifestContract.entries.map(entry => ({
        parentKey: entry.parent_key,
        notes: createdNoteKeysByParent.get(String(entry.parent_key))
          ? [
            ...entry.child_note_inventory,
            createdNoteKeysByParent.get(String(entry.parent_key)),
          ].sort()
          : entry.child_note_inventory,
        attachments: entry.child_attachment_inventory,
      })),
    })),
  };
}

async function resolveAndVerifyTarget(target) {
  const required = [
    "group_id",
    "library_id",
    "library_name",
    "local_collection_id",
    "collection_key",
    "collection_name",
    "collection_path",
  ];
  for (const field of required) {
    assertion(target[field] !== undefined, `manifest target is missing ${field}`);
  }

  const library = Zotero.Libraries.get(target.library_id);
  assertion(library, `library ${target.library_id} does not exist`);
  assertion(
    library.libraryType === "group"
      && library.groupID === target.group_id
      && library.libraryID === target.library_id
      && library.name === target.library_name,
    "library identity does not match the approved target",
    {
      observed: {
        libraryType: library.libraryType,
        groupID: library.groupID,
        libraryID: library.libraryID,
        name: library.name,
      },
      expected: target,
    },
  );
  assertion(library.editable, `library ${library.name} is not editable`);

  const collection = await Zotero.Collections.getByLibraryAndKeyAsync(
    target.library_id,
    target.collection_key,
  );
  assertion(collection, `collection ${target.collection_key} does not exist`);
  await collection.reload(["primaryData"], true);
  await collection.loadAllData();
  const observedPath = await collectionPath(collection, true);
  assertion(
    collection.id === target.local_collection_id
      && collection.libraryID === target.library_id
      && collection.key === target.collection_key
      && collection.name === target.collection_name
      && exactArrayEqual(observedPath, target.collection_path),
    "collection identity or path does not match the approved target",
    {
      observed: {
        id: collection.id,
        libraryID: collection.libraryID,
        key: collection.key,
        name: collection.name,
        path: observedPath,
      },
      expected: target,
    },
  );
  assertion(collection.isEditable(), `collection ${collection.key} is not editable`);

  const pane = Zotero.getActiveZoteroPane();
  assertion(pane, "no active Zotero library pane is available");
  const selected = pane.getSelectedCollection();
  assertion(selected, "select the approved collection in Zotero before running");
  assertion(
    pane.getSelectedLibraryID() === target.library_id
      && selected.id === collection.id
      && selected.key === collection.key,
    "currently selected Zotero target differs from the approved collection",
    {
      observed: {
        libraryID: pane.getSelectedLibraryID(),
        collectionID: selected.id,
        collectionKey: selected.key,
        collectionName: selected.name,
      },
      expected: {
        libraryID: target.library_id,
        collectionID: target.local_collection_id,
        collectionKey: target.collection_key,
        collectionName: target.collection_name,
      },
    },
  );

  return {
    library,
    collection,
    publicTarget: {
      groupID: library.groupID,
      libraryID: library.libraryID,
      libraryName: library.name,
      collectionID: collection.id,
      collectionKey: collection.key,
      collectionPath: observedPath,
    },
  };
}

async function verifyEntry(entry, targetContext) {
  const isCreate = entry.status === "create_verified";
  const parentKey = String(entry.expected_parent_key || "");
  const noteKey = isCreate ? null : String(entry.note_key || "");
  const label = noteKey || `create:${parentKey}`;
  if (!isCreate) {
    assertion(/^[A-Z0-9]{8}$/.test(noteKey), "invalid note key", { noteKey });
  }
  assertion(/^[A-Z0-9]{8}$/.test(parentKey), "invalid parent key", {
    noteKey,
    parentKey,
  });
  if (isCreate) {
    assertion(
      Number.isInteger(entry.parent_version) && entry.parent_version > 0,
      `${label}: manifest parent version is invalid`,
    );
    assertion(
      Array.isArray(entry.child_note_inventory)
        && entry.child_note_inventory.length === 0,
      `${label}: create preflight requires zero existing notes`,
    );
  }
  else {
    assertion(
      Number.isInteger(entry.note_version) && entry.note_version > 0,
      `${noteKey}: manifest note version is invalid`,
    );
  }
  assertion(
    Array.isArray(entry.validation_errors) && entry.validation_errors.length === 0,
    `${label}: staged note has validation errors`,
    entry.validation_errors,
  );
  assertion(
    entry.validation_summary
      && String(entry.validation_summary.schema_version) === "9",
    `${label}: staged note is not schema version 9`,
  );

  const stagedHTML = await Zotero.File.getContentsAsync(entry.new_path, "UTF-8");
  const oldHTML = isCreate
    ? null
    : await Zotero.File.getContentsAsync(entry.old_path, "UTF-8");
  if (!isCreate) {
    assertion(
      sha256Text(oldHTML) === entry.old_sha256,
      `${noteKey}: original backup hash changed`,
    );
  }
  assertion(
    sha256Text(stagedHTML) === entry.new_sha256,
    `${label}: staged HTML hash changed`,
  );
  await verifyPDFFile(entry.pdf_path, entry.pdf_sha256, label);
  const stagedProjection = semanticHTMLProjection(stagedHTML);
  assertion(
    stagedProjection.root.tag === "div"
      && stagedProjection.root.schemaVersion === "9",
    `${label}: staged HTML has no schema-9 root`,
  );
  const requiredSections = [
    "资料与阅读状态",
    "为什么重要",
    "一句话结论",
    "心智模型",
    "关键主张与证据",
    "方法或推导",
    "结果",
    "假设、失败边界与竞争解释",
    "知识图谱关系",
    "复用",
    "溯源",
  ];
  const h1 = stagedProjection.headings.filter(heading => heading.tag === "h1");
  const h2 = stagedProjection.headings
    .filter(heading => heading.tag === "h2")
    .map(heading => heading.text);
  let priorSectionIndex = -1;
  for (const section of requiredSections) {
    const sectionIndex = h2.indexOf(section);
    assertion(
      sectionIndex > priorSectionIndex,
      `${label}: staged schema-9 sections are missing or out of order`,
      { section, headings: h2 },
    );
    priorSectionIndex = sectionIndex;
  }
  assertion(
    h1.length === 1 && h1[0].text,
    `${label}: staged schema-9 note must contain one non-empty h1`,
  );
  assertion(
    stagedHTML.includes(entry.pdf_sha256),
    `${label}: staged note does not cite the verified PDF SHA-256`,
  );
  const expectedStoredHTML = normalizedNoteHTML(stagedHTML);
  const expectedStoredSHA256 = sha256Text(expectedStoredHTML);
  if (entry.status === "staged_verified") {
    assertion(
      expectedStoredSHA256 !== entry.old_sha256,
      `${noteKey}: staged note is a no-op`,
    );
  }
  if (entry.status === "unchanged_verified") {
    assertion(
      entry.old_sha256 === entry.new_sha256,
      `${noteKey}: unchanged note hashes are inconsistent`,
    );
    assertion(
      expectedStoredSHA256 === entry.old_sha256,
      `${noteKey}: unchanged note normalization changed the stored digest`,
    );
  }

  const parent = await Zotero.Items.getByLibraryAndKeyAsync(
    targetContext.library.libraryID,
    parentKey,
  );
  assertion(parent, `${label}: parent ${parentKey} does not exist`);
  await parent.loadAllData(true);
  assertion(parent.isRegularItem(), `${label}: parent is not a regular item`);
  assertion(!parent.deleted, `${label}: parent is in the trash`);
  assertion(
    parent.libraryID === targetContext.library.libraryID,
    `${label}: parent is in the wrong library`,
  );
  assertion(
    parent.getCollections().includes(targetContext.collection.id)
      && targetContext.collection.hasItem(parent),
    `${label}: parent is outside the approved collection`,
  );
  let note = null;
  if (isCreate) {
    assertion(
      typeof parent.isEditable === "function" && parent.isEditable(),
      `${label}: parent is not editable for child-note creation`,
    );
    assertion(
      parent.version === entry.parent_version,
      `${label}: parent version changed`,
      { observed: parent.version, expected: entry.parent_version },
    );
    const parentData = parent.toJSON();
    assertion(
      parentData.key === parent.key
        && parentData.version === parent.version,
      `${label}: parent item data identity differs`,
      {
        dataKey: parentData.key,
        itemKey: parent.key,
        dataVersion: parentData.version,
        itemVersion: parent.version,
      },
    );
    const observedParentDataSnapshotSHA256 = parentDataSnapshotSHA256(
      parentData,
    );
    assertion(
      observedParentDataSnapshotSHA256
        === entry.parent_data_snapshot_sha256,
      `${label}: parent item data changed`,
      {
        observed: observedParentDataSnapshotSHA256,
        expected: entry.parent_data_snapshot_sha256,
      },
    );
    const liveChildren = await liveChildInventory(parent, false);
    assertion(
      liveChildren.notes.length === 0
        && exactArrayEqual(
          liveChildren.attachments,
          entry.child_attachment_inventory,
        )
        && exactArrayEqual(
          liveChildren.items,
          entry.child_item_inventory,
        ),
      `${label}: live child inventory changed before creation`,
      {
        observed: liveChildren,
        expected: {
          notes: entry.child_note_inventory,
          attachments: entry.child_attachment_inventory,
          items: entry.child_item_inventory,
        },
      },
    );
  }
  else {
    note = await Zotero.Items.getByLibraryAndKeyAsync(
      targetContext.library.libraryID,
      noteKey,
    );
    assertion(note, `${noteKey}: note does not exist`);
    await note.loadAllData();
    assertion(note.isNote(), `${noteKey}: target item is not a note`);
    assertion(!note.deleted, `${noteKey}: note is in the trash`);
    assertion(note.isEditable(), `${noteKey}: note is not editable`);
    assertion(
      note.libraryID === targetContext.library.libraryID,
      `${noteKey}: note is in the wrong library`,
    );
    assertion(
      note.parentItemKey === parentKey,
      `${noteKey}: parent key changed`,
      { observed: note.parentItemKey, expected: parentKey },
    );
    assertion(
      note.version === entry.note_version,
      `${noteKey}: note version changed`,
      { observed: note.version, expected: entry.note_version },
    );
    assertion(
      sha256Text(note.getNote()) === entry.old_sha256,
      `${noteKey}: live note content conflicts with the approved backup`,
    );
  }
  const attachment = await Zotero.Items.getByLibraryAndKeyAsync(
    targetContext.library.libraryID,
    entry.pdf_attachment_key,
  );
  if (attachment) {
    await attachment.loadAllData();
  }
  assertion(
    attachment
      && attachment.isAttachment()
      && !attachment.deleted
      && attachment.parentItemKey === parentKey
      && attachment.attachmentContentType === "application/pdf",
    `${label}: approved PDF attachment identity changed`,
  );
  assertion(
    attachment.attachmentLinkMode
      === expectedAttachmentLinkMode(entry.pdf_attachment_link_mode),
    `${label}: approved PDF attachment link mode changed`,
  );
  await verifyAttachmentFileBinding(attachment, entry.pdf_path, label);

  return {
    note,
    parent,
    attachment,
    status: entry.status,
    noteKey,
    parentKey,
    operation: isCreate
      ? "create"
      : entry.status === "staged_verified"
        ? "update"
        : "unchanged",
    oldHTML,
    oldSHA256: isCreate ? null : entry.old_sha256,
    sourceSHA256: entry.new_sha256,
    pdfPath: entry.pdf_path,
    pdfSHA256: entry.pdf_sha256,
    pdfAttachmentLinkMode: entry.pdf_attachment_link_mode,
    entryChildAttachmentInventory: entry.child_attachment_inventory,
    entryChildItemInventory: entry.child_item_inventory,
    expectedStoredHTML,
    expectedStoredSHA256,
    storageNormalization:
      stagedHTML === expectedStoredHTML ? "none" : "zotero_trim",
    oldVersion: note ? note.version : null,
    parentVersion: parent.version,
    parentDataSnapshotSHA256: isCreate
      ? entry.parent_data_snapshot_sha256
      : null,
    createdNoteKey: null,
  };
}

async function verifyLiveStateAgain(verified, targetContext) {
  for (const item of verified) {
    const label = item.noteKey || `create:${item.parentKey}`;
    if (item.operation === "create") {
      await verifyPDFFile(
        item.pdfPath,
        item.pdfSHA256,
        label,
        true,
      );
    } else {
      await verifyPDFFile(
        item.pdfPath,
        item.pdfSHA256,
        item.noteKey,
        true,
      );
    }
    if (item.operation !== "create") {
      await item.note.reload(["primaryData", "note"], true);
      assertion(!item.note.deleted, `${item.noteKey}: note was deleted after preflight`);
      assertion(
        item.note.version === item.oldVersion,
        `${item.noteKey}: note version changed after preflight`,
        { observed: item.note.version, expected: item.oldVersion },
      );
      assertion(
        item.note.parentItemKey === item.parentKey,
        `${item.noteKey}: parent changed after preflight`,
      );
      assertion(
        sha256Text(item.note.getNote()) === item.oldSHA256,
        `${item.noteKey}: note content changed after preflight`,
      );
    }
    await item.parent.reload(
      ["primaryData", "collections", "childItems"],
      true,
    );
    assertion(
      item.parent.isRegularItem()
        && !item.parent.deleted
        && item.parent.libraryID === targetContext.library.libraryID,
      `${label}: parent changed or became invalid after preflight`,
    );
    assertion(
      item.parent.getCollections().includes(targetContext.collection.id)
        && targetContext.collection.hasItem(item.parent),
      `${label}: parent left the approved collection after preflight`,
    );
    if (item.operation === "create") {
      await item.parent.loadAllData(true);
      assertion(
        item.parent.version === item.parentVersion,
        `${label}: parent version changed after preflight`,
        { observed: item.parent.version, expected: item.parentVersion },
      );
      const parentData = item.parent.toJSON();
      assertion(
        parentData.key === item.parent.key
          && parentData.version === item.parent.version,
        `${label}: parent item data identity differs after preflight`,
        {
          dataKey: parentData.key,
          itemKey: item.parent.key,
          dataVersion: parentData.version,
          itemVersion: item.parent.version,
        },
      );
      const observedParentDataSnapshotSHA256 = parentDataSnapshotSHA256(
        parentData,
      );
      assertion(
        observedParentDataSnapshotSHA256
          === item.parentDataSnapshotSHA256,
        `${label}: parent item data changed after preflight`,
        {
          observed: observedParentDataSnapshotSHA256,
          expected: item.parentDataSnapshotSHA256,
        },
      );
      const observedChildren = await liveChildInventory(item.parent, false);
      assertion(
        observedChildren.notes.length === 0
          && exactArrayEqual(
            observedChildren.attachments,
            item.entryChildAttachmentInventory,
          )
          && exactArrayEqual(
            observedChildren.items,
            item.entryChildItemInventory,
          ),
        `${label}: a child appeared after create preflight`,
        { observed: observedChildren },
      );
    }
    await item.attachment.reload(["primaryData"], true);
    await item.attachment.loadAllData();
    assertion(
      item.attachment.isAttachment()
        && !item.attachment.deleted
        && item.attachment.parentItemKey === item.parentKey
        && item.attachment.attachmentContentType === "application/pdf"
        && item.attachment.attachmentLinkMode
          === expectedAttachmentLinkMode(item.pdfAttachmentLinkMode),
      `${label}: approved PDF attachment changed after preflight`,
    );
    await verifyAttachmentFileBinding(
      item.attachment,
      item.pdfPath,
      label,
    );
  }
}

async function applyTransaction(
  verified,
  mutationVerified,
  manifestTarget,
  manifestContract,
  onCommit,
  createVerified = [],
) {
  await Zotero.DB.executeTransaction(async function () {
    assertion(
      !CONFIG.requireAutoSyncEnabled
        || Zotero.Prefs.get("sync.autoSync") === true,
      "automatic sync was disabled at transaction start",
    );
    const transactionTargetContext = await resolveAndVerifyTarget(manifestTarget);
    await verifyLiveManifestInventory(
      manifestContract,
      transactionTargetContext,
      true,
    );
    await verifyLiveStateAgain(verified, transactionTargetContext);
    for (const item of mutationVerified) {
      item.note.setNote(item.expectedStoredHTML);
      await item.note.save();
      assertion(
        sha256Text(item.note.getNote()) === item.expectedStoredSHA256,
        `${item.noteKey}: in-transaction note hash mismatch`,
      );
    }
    for (const item of createVerified) {
      const note = new Zotero.Item("note");
      note.libraryID = transactionTargetContext.library.libraryID;
      note.parentKey = item.parentKey;
      note.setNote(item.expectedStoredHTML);
      await note.save();
      assertion(
        /^[A-Z0-9]{8}$/.test(String(note.key || "")),
        `create:${item.parentKey}: Zotero did not assign a valid note key`,
      );
      assertion(
        note.libraryID === transactionTargetContext.library.libraryID
          && note.parentItemKey === item.parentKey
          && sha256Text(note.getNote()) === item.expectedStoredSHA256,
        `create:${item.parentKey}: in-transaction created note verification failed`,
      );
      item.note = note;
      item.noteKey = note.key;
      item.createdNoteKey = note.key;
    }
  }, { onCommit });
}

async function inspectTransactionOutcome(verified) {
  let oldStateCount = 0;
  let newStateCount = 0;
  const observations = [];
  for (const item of verified) {
    try {
      if (item.operation === "create") {
        await item.parent.reload(["primaryData", "childItems"], true);
        await item.parent.loadDataType("childItems");
        const notes = (await Zotero.Items.getAsync(item.parent.getNotes(false)))
          .filter(note =>
            note
              && !note.deleted
              && note.isNote()
              && note.parentItemKey === item.parentKey
          );
        const matches = notes.filter(note => {
          const html = note.getNote();
          return sha256Text(html) === item.expectedStoredSHA256
            || semanticHTMLSHA256(html)
              === semanticHTMLSHA256(item.expectedStoredHTML);
        });
        const isOld = notes.length === 0;
        const isNew = notes.length === 1 && matches.length === 1;
        if (isOld) {
          oldStateCount += 1;
        }
        if (isNew) {
          newStateCount += 1;
          item.note = matches[0];
          item.noteKey = matches[0].key;
          item.createdNoteKey = matches[0].key;
        }
        observations.push({
          operation: "create",
          parentKey: item.parentKey,
          noteKeys: notes.map(note => note.key).sort(),
          matchingNoteKeys: matches.map(note => note.key).sort(),
          state: isOld ? "old" : isNew ? "new" : "neither",
        });
        continue;
      }
      await item.note.reload(["primaryData", "note"], true);
      const html = item.note.getNote();
      const sha256 = sha256Text(html);
      const parentMatches = item.note.parentItemKey === item.parentKey;
      const isOld =
        parentMatches
        && item.note.version === item.oldVersion
        && sha256 === item.oldSHA256;
      const isNew =
        parentMatches
        && item.note.version >= item.oldVersion
        && (
          sha256 === item.expectedStoredSHA256
          || semanticHTMLSHA256(html)
            === semanticHTMLSHA256(item.expectedStoredHTML)
        );
      if (isOld) {
        oldStateCount += 1;
      }
      if (isNew) {
        newStateCount += 1;
      }
      observations.push({
        operation: "update",
        noteKey: item.noteKey,
        version: item.note.version,
        sha256,
        parentMatches,
        state: isOld ? "old" : isNew ? "new" : "neither",
      });
    }
    catch (error) {
      observations.push({
        operation: item.operation,
        noteKey: item.noteKey,
        parentKey: item.parentKey,
        state: "unreadable",
        error: plainError(error),
      });
    }
  }
  let outcome = "unknown";
  if (oldStateCount === verified.length) {
    outcome = "rolled_back";
  }
  else if (newStateCount === verified.length) {
    outcome = "committed";
  }
  return { outcome, oldStateCount, newStateCount, observations };
}

async function acquireSyncBarrier(timeoutMS = 60000, leaseMS = 120000) {
  const runner = Zotero.Sync && Zotero.Sync.Runner;
  assertion(
    runner
      && typeof runner.delayIndefinite === "function",
    "this Zotero build does not expose the required temporary sync barrier",
  );
  const startedAt = Date.now();
  while (runner.syncInProgress) {
    assertion(
      Date.now() - startedAt < timeoutMS,
      "an active sync did not finish within 60 seconds; no notes were changed",
    );
    await Zotero.Promise.delay(100);
  }

  // No await is allowed between the final idle check and acquiring the barrier.
  // JavaScript therefore cannot start another task in this interval.
  const releaseBarrier = runner.delayIndefinite();
  const state = {
    leaseMS,
    leaseExpired: false,
    released: false,
  };
  let watchdog = setTimeout(() => {
    state.leaseExpired = true;
    if (!state.released) {
      state.released = true;
      releaseBarrier();
    }
  }, leaseMS);
  const release = () => {
    if (state.released) {
      return;
    }
    state.released = true;
    clearTimeout(watchdog);
    watchdog = null;
    releaseBarrier();
  };
  return {
    release,
    waitedMS: Date.now() - startedAt,
    state,
  };
}

async function readBack(verified, targetContext) {
  const refreshItemFromKey = async (key, label) => {
    if (
      Zotero.Items
      && typeof Zotero.Items.getByLibraryAndKeyAsync === "function"
    ) {
      const item = await Zotero.Items.getByLibraryAndKeyAsync(
        targetContext.library.libraryID,
        key,
      );
      assertion(
        item,
        `${label}: committed lookup did not return item ${key}`,
      );
      return item;
    }
    assertion(
      false,
      `${label}: committed lookup did not expose a way to refresh item state`,
    );
  };
  const results = [];
  for (const item of verified) {
    assertion(
      /^[A-Z0-9]{8}$/.test(String(item.noteKey || "")),
      `create:${item.parentKey}: committed note key is missing or invalid`,
    );
    const note = await refreshItemFromKey(
      item.noteKey,
      `${item.noteKey}: failed to refresh committed note`,
    );
    const parent = await refreshItemFromKey(
      item.parentKey,
      `${item.noteKey}: failed to refresh committed note parent`,
    );
    await note.reload(["primaryData", "note"], true);
    await parent.reload(["primaryData", "collections"], true);
    const observedSHA256 = sha256Text(note.getNote());
    const observedSemanticSHA256 = semanticHTMLSHA256(note.getNote());
    const expectedSemanticSHA256 = semanticHTMLSHA256(item.expectedStoredHTML);
    const byteExact = observedSHA256 === item.expectedStoredSHA256;
    const semanticEquivalent =
      observedSemanticSHA256 === expectedSemanticSHA256;
    const noteTypeMatches = typeof note.isNote === "function"
      ? note.isNote()
      : note.itemType === "note";
    const localVersionValid =
      Number.isInteger(note.version) && note.version >= 0;
    const serverVersionAdvanced = item.operation === "create"
      ? note.version > 0
      : note.version > item.oldVersion;
    const versionMatches = item.operation === "create"
      ? localVersionValid
      : note.version >= item.oldVersion;
    assertion(
      noteTypeMatches
        && !note.deleted
        && note.parentItemKey === item.parentKey
        && versionMatches
        && (byteExact || semanticEquivalent),
      `${item.noteKey}: committed readback verification failed`,
      {
        itemType: note.itemType,
        deleted: note.deleted,
        parentItemKey: note.parentItemKey,
        oldVersion: item.oldVersion,
        localVersionValid,
        serverVersionAdvanced,
        readbackVersion: note.version,
        observedSHA256,
        expectedSHA256: item.expectedStoredSHA256,
        observedSemanticSHA256,
        expectedSemanticSHA256,
      },
    );
    assertion(
      !parent.deleted
        && parent.isRegularItem()
        && parent.getCollections().includes(targetContext.collection.id),
      `${item.noteKey}: parent collection membership changed after commit`,
    );
    results.push({
      operation: item.operation,
      noteKey: item.noteKey,
      parentKey: item.parentKey,
      createdNoteKey: item.operation === "create" ? item.noteKey : null,
      parentVersion: item.parentVersion,
      oldVersion: item.oldVersion,
      readbackVersion: note.version,
      serverVersionAdvanced,
      oldSHA256: item.oldSHA256,
      stagedSourceSHA256: item.sourceSHA256,
      readbackSHA256: observedSHA256,
      expectedStoredSHA256: item.expectedStoredSHA256,
      semanticSHA256: observedSemanticSHA256,
      readbackMode: byteExact ? "byte_exact" : "semantic_equivalent",
      storageNormalization: byteExact
        ? item.storageNormalization
        : "zotero_dom_normalization",
      verified: true,
    });
  }
  return results;
}

async function runMigration() {
  const startedAt = new Date().toISOString();
  let phase = "load_manifest";
  let writePerformed = false;
  let rolledBack = false;
  let transactionOutcome = "not_started";
  let transactionInspection;
  let verified = [];
  let mutationVerified = [];
  let createVerified = [];
  let publicTarget;
  const autoSyncBefore = Zotero.Prefs.get("sync.autoSync");
  let syncState = {
    guardUsed: false,
    autoSyncBefore,
    autoSyncObserved: autoSyncBefore === true,
    preferenceChanged: false,
    writePerformed: false,
  };
  const sampleSyncPreferenceState = () => {
    syncState.autoSyncAfter = Zotero.Prefs.get("sync.autoSync");
    syncState.preferenceChanged =
      syncState.autoSyncAfter !== syncState.autoSyncBefore;
    syncState.preferencePreserved =
      syncState.autoSyncAfter === syncState.autoSyncBefore;
    syncState.writePerformed = writePerformed;
  };
  try {
    assertion(CONFIG && typeof CONFIG === "object", "runner is not configured");
    assertion(
      typeof CONFIG.manifestPath === "string"
        && typeof CONFIG.reportPath === "string"
        && typeof CONFIG.manifestSHA256 === "string",
      "runner configuration is incomplete",
    );
    assertion(
      !CONFIG.requireAutoSyncEnabled
        || syncState.autoSyncObserved,
      "automatic sync is not enabled; no notes were changed",
    );
    const manifestText = await Zotero.File.getContentsAsync(
      CONFIG.manifestPath,
      "UTF-8",
    );
    assertion(
      sha256Text(manifestText) === CONFIG.manifestSHA256,
      "migration manifest changed after the runner was generated",
    );
    const manifest = JSON.parse(manifestText);
    assertion(
      manifest.manifest_version === "2",
      "unsupported migration manifest version",
    );
    assertion(
      manifest.write_performed === false,
      "migration manifest is already marked as written",
    );

    const manifestContract = validateManifestContract(manifest);

    phase = "verify_target";
    const targetContext = await resolveAndVerifyTarget(manifest.target || {});
    publicTarget = targetContext.publicTarget;
    const inventoryEvidence = await verifyLiveManifestInventory(
      manifestContract,
      targetContext,
      true,
    );

    phase = "preflight_entries";
    const entries = (manifest.entries || []).filter(
      entry => entry && (
        entry.status === "staged_verified"
        || entry.status === "unchanged_verified"
        || entry.status === "create_verified"
      ),
    );
    const mutationEntries = (manifest.entries || []).filter(
      entry => entry && entry.status === "staged_verified",
    );
    const createEntries = (manifest.entries || []).filter(
      entry => entry && entry.status === "create_verified",
    );
    assertion(entries.length > 0, "manifest contains no staged notes");
    assertion(
      entries.length === CONFIG.expectedInventoryNoteCount,
      "inventory note count differs from the generated runner",
      { observed: entries.length, expected: CONFIG.expectedInventoryNoteCount },
    );
    assertion(
      mutationEntries.length === CONFIG.expectedMutationCount,
      "mutation note count differs from the generated runner",
      {
        observed: mutationEntries.length,
        expected: CONFIG.expectedMutationCount,
      },
    );
    assertion(
      createEntries.length === (CONFIG.expectedCreateCount || 0),
      "create note count differs from the generated runner",
      {
        observed: createEntries.length,
        expected: CONFIG.expectedCreateCount || 0,
      },
    );
    const observedMutationKeys = mutationEntries
      .map(entry => String(entry.note_key || ""))
      .sort();
    assertion(
      exactArrayEqual(
        observedMutationKeys,
        (CONFIG.expectedMutationKeys || []).slice().sort(),
      ),
      "mutation note keys differ from the generated runner",
      {
        observed: observedMutationKeys,
        expected: CONFIG.expectedMutationKeys,
      },
    );
    const observedCreateParentKeys = createEntries
      .map(entry => String(entry.parent_key || ""))
      .sort();
    assertion(
      exactArrayEqual(
        observedCreateParentKeys,
        (CONFIG.expectedCreateParentKeys || []).slice().sort(),
      ),
      "create parent keys differ from the generated runner",
      {
        observed: observedCreateParentKeys,
        expected: CONFIG.expectedCreateParentKeys || [],
      },
    );
    const noteKeys = entries
      .filter(entry => entry.status !== "create_verified")
      .map(entry => String(entry.note_key || ""));
    assertion(
      new Set(noteKeys).size === noteKeys.length,
      "manifest contains duplicate note keys",
    );
    for (const entry of entries) {
      verified.push(await verifyEntry(entry, targetContext));
    }
    mutationVerified = verified.filter(item => item.status === "staged_verified");
    createVerified = verified.filter(item => item.status === "create_verified");

    const publicNotes = verified.map(item => ({
      operation: item.operation,
      noteKey: item.noteKey,
      parentKey: item.parentKey,
      parentVersion: item.parentVersion,
      parentDataSnapshotSHA256: item.parentDataSnapshotSHA256,
      oldVersion: item.oldVersion,
      oldSHA256: item.oldSHA256,
      stagedSourceSHA256: item.sourceSHA256,
      expectedStoredSHA256: item.expectedStoredSHA256,
      storageNormalization: item.storageNormalization,
      backupVerified: item.operation !== "create",
      sourceVerified: true,
    }));

    if (!CONFIG.apply) {
      sampleSyncPreferenceState();
      assertion(
        !CONFIG.requireAutoSyncEnabled
          || syncState.autoSyncAfter === true,
        "automatic sync was disabled during dry-run; no notes were changed",
      );
      return {
        status: "preflight_ok",
        mode: "dry_run",
        startedAt,
        completedAt: new Date().toISOString(),
        target: publicTarget,
        inventoryEvidence,
        noteCount: verified.length,
        mutationCount: mutationVerified.length,
        mutationKeys: observedMutationKeys,
        updateCount: mutationVerified.length,
        updateNoteKeys: observedMutationKeys,
        createCount: createVerified.length,
        createParentKeys: observedCreateParentKeys,
        newNoteKeys: [],
        totalWriteCount: mutationVerified.length + createVerified.length,
        notes: publicNotes,
        syncState,
        writePerformed: false,
      };
    }

    if (mutationVerified.length === 0 && createVerified.length === 0) {
      sampleSyncPreferenceState();
      assertion(
        !CONFIG.requireAutoSyncEnabled
          || syncState.autoSyncAfter === true,
        "automatic sync is no longer enabled after the migration",
      );
      return {
        status: "no_changes",
        mode: "apply",
        startedAt,
        completedAt: new Date().toISOString(),
        target: publicTarget,
        inventoryEvidence,
        noteCount: verified.length,
        mutationCount: mutationVerified.length,
        mutationKeys: observedMutationKeys,
        updateCount: 0,
        updateNoteKeys: [],
        createCount: 0,
        createParentKeys: [],
        newNoteKeys: [],
        totalWriteCount: 0,
        notes: publicNotes,
        syncState,
        writePerformed: false,
      };
    }

    phase = "quiesce_sync";
    let syncBarrier;
    try {
      assertion(
        !CONFIG.requireAutoSyncEnabled
          || Zotero.Prefs.get("sync.autoSync") === true,
        "automatic sync was disabled after preflight; no notes were changed",
      );
      syncBarrier = await acquireSyncBarrier();
      syncState = {
        ...syncState,
        guardUsed: true,
        activeSyncWaitMS: syncBarrier.waitedMS,
        barrierLeaseMS: syncBarrier.state.leaseMS,
        barrierLeaseExpired: syncBarrier.state.leaseExpired,
      };

      phase = "transaction";
      let commitObserved = false;
      try {
        assertion(
          !CONFIG.requireAutoSyncEnabled
            || Zotero.Prefs.get("sync.autoSync") === true,
          "automatic sync was disabled before the transaction; no notes were changed",
        );
        await applyTransaction(
          verified,
          mutationVerified,
          manifest.target,
          manifestContract,
          () => {
            commitObserved = true;
          },
          createVerified,
        );
        writePerformed = true;
        transactionOutcome = "committed";
      }
      catch (error) {
        transactionInspection = await inspectTransactionOutcome([
          ...mutationVerified,
          ...createVerified,
        ]);
        transactionOutcome = transactionInspection.outcome;
        if (commitObserved || transactionOutcome === "committed") {
          writePerformed = true;
          rolledBack = false;
        }
        else if (transactionOutcome === "rolled_back") {
          writePerformed = false;
          rolledBack = true;
        }
        else {
          writePerformed = null;
          rolledBack = false;
        }
        throw error;
      }

      phase = "readback";
      const writeVerified = [...mutationVerified, ...createVerified];
      const results = await readBack(writeVerified, targetContext);
      const createdNoteKeysByParent = new Map(
        createVerified.map(item => [item.parentKey, item.noteKey]),
      );
      await verifyLiveManifestInventory(
        manifestContract,
        targetContext,
        true,
        createdNoteKeysByParent,
      );
      const newNoteKeys = createVerified.map(item => item.noteKey).sort();
      syncState.writePerformed = writePerformed;
      return {
        status: "completed",
        mode: "apply",
        startedAt,
        completedAt: new Date().toISOString(),
        target: publicTarget,
        inventoryEvidence,
        noteCount: verified.length,
        mutationCount: mutationVerified.length,
        mutationKeys: observedMutationKeys,
        updateCount: mutationVerified.length,
        updateNoteKeys: observedMutationKeys,
        createCount: createVerified.length,
        createParentKeys: observedCreateParentKeys,
        newNoteKeys,
        totalWriteCount: mutationVerified.length + createVerified.length,
        notes: publicNotes,
        results,
        syncState,
        writePerformed: true,
        rolledBack: false,
        transactionOutcome,
      };
    }
    finally {
      if (syncBarrier) {
        syncBarrier.release();
        syncState.barrierLeaseExpired = syncBarrier.state.leaseExpired;
        syncState.barrierReleased = syncBarrier.state.released;
      }
      sampleSyncPreferenceState();
      if (
        CONFIG.requireAutoSyncEnabled
        && syncState.autoSyncAfter !== true
      ) {
        phase = "sync_invariant";
        throw new Error(
          "automatic sync is no longer enabled after the migration",
        );
      }
      if (syncBarrier && syncBarrier.state.leaseExpired) {
        phase = "sync_barrier_lease";
        throw new Error(
          "the temporary sync-barrier lease expired before migration completion",
        );
      }
    }
  }
  catch (error) {
    try {
      sampleSyncPreferenceState();
    }
    catch (sampleError) {
      syncState.syncPreferenceSampleError = plainError(sampleError);
      syncState.autoSyncAfter = null;
      syncState.preferenceChanged = null;
      syncState.preferencePreserved = null;
      syncState.writePerformed = writePerformed;
    }
    return {
      status:
        phase === "sync_barrier_lease"
          ? "sync_barrier_lease_expired"
          : writePerformed === true
          ? "readback_failed"
          : writePerformed === null
            ? "transaction_outcome_unknown"
            : "failed",
      mode: CONFIG && CONFIG.apply ? "apply" : "dry_run",
      phase,
      startedAt,
      completedAt: new Date().toISOString(),
      target: publicTarget,
      noteCount: verified.length,
      updateCount: mutationVerified.length,
      updateNoteKeys: mutationVerified
        .map(item => item.noteKey)
        .filter(Boolean)
        .sort(),
      createCount: createVerified.length,
      createParentKeys: createVerified.map(item => item.parentKey).sort(),
      newNoteKeys: createVerified
        .map(item => item.noteKey)
        .filter(Boolean)
        .sort(),
      totalWriteCount: mutationVerified.length + createVerified.length,
      syncState,
      writePerformed,
      rolledBack,
      transactionOutcome,
      transactionInspection,
      error: plainError(error),
    };
  }
}

await assertFreshReportPath();
const migrationReport = await runMigration();
try {
  return await writeReport(migrationReport);
}
catch (error) {
  return JSON.stringify({
    status: "report_persistence_failed",
    reportPath: CONFIG.reportPath,
    migrationReport,
    persistenceError: plainError(error),
  }, null, 2);
}
