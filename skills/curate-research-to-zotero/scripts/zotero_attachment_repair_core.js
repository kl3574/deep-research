var AttachmentRepairCore = (() => {
  "use strict";

  function assertion(condition, message) {
    if (!condition) throw new Error(message);
  }

  function sameJSON(left, right) {
    return JSON.stringify(left) === JSON.stringify(right);
  }

  function uniqueByKey(items, context) {
    const result = new Map();
    for (const item of items) {
      assertion(item && typeof item === "object", `${context} item must be an object`);
      assertion(typeof item.key === "string" && item.key, `${context} key is missing`);
      assertion(!result.has(item.key), `duplicate ${context} key: ${item.key}`);
      result.set(item.key, item);
    }
    return result;
  }

  function verifyTarget(expected, observed) {
    const scalarFields = [
      "group_id", "library_id", "library_name", "local_collection_id", "collection_key",
    ];
    for (const field of scalarFields) {
      assertion(observed[field] === expected[field], `selected target ${field} mismatch`);
    }
    assertion(sameJSON(observed.collection_path, expected.collection_path), "selected target path mismatch");
    assertion(
      observed.library_editable === expected.require_library_editable,
      "library editability mismatch",
    );
    assertion(
      observed.files_editable === expected.require_files_editable,
      "library files editability mismatch",
    );
    return true;
  }

  function verifyParent(expected, observed) {
    const fields = ["key", "version", "item_type", "doi", "title", "collection_key"];
    for (const field of fields) {
      assertion(observed[field] === expected[field], `parent ${expected.key} ${field} drift`);
    }
    assertion(observed.in_target_collection === true, `parent ${expected.key} left target collection`);
    return true;
  }

  function verifyFileBinding(expected, observed) {
    for (const field of ["size_bytes", "sha256", "magic", "content_type"]) {
      assertion(observed[field] === expected[field], `source PDF ${field} mismatch`);
    }
    return true;
  }

  function classifyLiveAttachments(action, expectedItems, liveItems, sourceSHA256) {
    const expected = uniqueByKey(expectedItems, "expected attachment");
    const live = uniqueByKey(liveItems, "live attachment");
    for (const [key, expectedItem] of expected) {
      const liveItem = live.get(key);
      assertion(liveItem, `baseline attachment disappeared: ${key}`);
      for (const field of ["version", "content_type", "link_mode"]) {
        assertion(liveItem[field] === expectedItem[field], `attachment ${key} ${field} drift`);
      }
    }
    const extras = liveItems.filter(item => !expected.has(item.key));
    if (action === "metadata_only_skip") {
      assertion(extras.length === 0, "metadata-only attachment inventory drift");
      return {decision: "metadata_only_skip", sameHashKeys: [], duplicateCount: 0, invalidLocalKeys: []};
    }
    assertion(action === "attach_missing_pdf", "unsupported attachment repair action");
    const validReadable = liveItems.filter(
      item => item.content_type === "application/pdf" && item.readable_pdf === true,
    );
    const sameHash = validReadable.filter(item => item.sha256 === sourceSHA256);
    const differentHash = validReadable.filter(item => item.sha256 !== sourceSHA256);
    assertion(differentHash.length === 0, "a different readable PDF already exists");
    for (const item of extras) {
      assertion(
        item.readable_pdf === true && item.sha256 === sourceSHA256,
        `unexpected attachment inventory drift: ${item.key}`,
      );
    }
    const invalidLocalKeys = liveItems
      .filter(item => item.invalid_local_file === true)
      .map(item => item.key)
      .sort();
    assertion(sameHash.length <= 1, "multiple readable PDFs with the source hash already exist");
    if (sameHash.length === 1) {
      return {
        decision: "no_op_same_hash",
        sameHashKeys: sameHash.map(item => item.key).sort(),
        duplicateCount: 0,
        invalidLocalKeys,
      };
    }
    return {
      decision: "ready_to_attach",
      sameHashKeys: [],
      duplicateCount: 0,
      invalidLocalKeys,
    };
  }

  function classifyImportOutcome(plannedParentKeys, presentByParent, inspectionFailed) {
    assertion(plannedParentKeys.length === 1, "import outcome requires exactly one planned parent");
    if (inspectionFailed) return "unknown";
    return presentByParent[plannedParentKeys[0]] === true ? "committed" : "unknown";
  }

  function verifyReadback(expected, observed) {
    assertion(observed.parent_key === expected.parent_key, "readback parent mismatch");
    assertion(observed.content_type === "application/pdf", "readback content type mismatch");
    assertion(observed.size_bytes === expected.size_bytes, "readback size mismatch");
    assertion(observed.sha256 === expected.sha256, "readback SHA-256 mismatch");
    assertion(observed.magic === "%PDF-", "readback PDF magic mismatch");
    assertion(observed.parent_in_target_collection === true, "readback parent collection mismatch");
    assertion(observed.direct_collection_count === 0, "child attachment has direct collection membership");
    return true;
  }

  return {
    classifyLiveAttachments,
    classifyImportOutcome,
    verifyFileBinding,
    verifyParent,
    verifyReadback,
    verifyTarget,
  };
})();

if (typeof module !== "undefined" && module.exports) {
  module.exports = AttachmentRepairCore;
}
