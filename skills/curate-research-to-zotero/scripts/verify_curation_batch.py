#!/usr/bin/env python3
"""Validate CurationBatch/v1 and CurationExecution/v1 without side effects."""

from __future__ import annotations

import argparse
import hashlib
from html.parser import HTMLParser
import json
from pathlib import Path
import re
import sys
from typing import Any

from verify_note_html import validate_note


DIGEST_RE = re.compile(r"^(?:sha256:)?([0-9a-f]{64})$")
ITEM_KEY_RE = re.compile(r"^[A-Z0-9]{8}$")
DECISION_HANDLER = {
    "create_parent": "import_zotero_bundle",
    "metadata_only_create": "import_zotero_bundle",
    "reuse_existing_parent_add_collection": "desktop_membership_transaction",
    "create_missing_note": "prepare_note_migration",
    "update_existing_note": "prepare_note_migration",
    "attach_missing_pdf": "desktop_attachment_transaction",
    "no_op_verified": "readback_only",
    "blocked_duplicate_conflict": "none",
    "blocked_version_conflict": "none",
    "blocked_access": "none",
    "blocked_unsupported_operation": "none",
}
BLOCKED_DECISIONS = {value for value in DECISION_HANDLER if value.startswith("blocked_")}
EXISTING_DECISIONS = {
    "reuse_existing_parent_add_collection",
    "create_missing_note",
    "update_existing_note",
    "attach_missing_pdf",
    "no_op_verified",
    "blocked_unsupported_operation",
}
MAIN_TEXT_ROLES = {"main_text", "version_of_record", "accepted_manuscript", "preprint"}
SI_ROLES = {"supplement", "supporting_information"}
NOTE_SECTIONS = [
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
]
PAPER_KNOWLEDGE_NOTE_CONTRACT = "PaperKnowledgeNote/v2"
PAPER_KNOWLEDGE_NOTE_SECTIONS = [
    "适用场景与结论",
    "工作流程与 I/O / 数据流",
    "数学原理与推导",
    "算法原理",
    "证据、边界与溯源",
]
SUCCESS_STATES = [
    "mapped",
    "selected",
    "acquisition_ready",
    "golden_bundle_validated",
    "batch_dry_run_passed",
    "write_authorized",
    "imported",
    "readback_verified",
]
FAILURE_STATES = {
    "schema_mismatch",
    "target_drift",
    "blocked_access",
    "blocked_capability",
    "partial_commit",
    "readback_mismatch",
}
FAILURE_FROM = {
    "schema_mismatch": {"mapped"},
    "target_drift": set(SUCCESS_STATES[:-1]),
    "blocked_access": {"selected", "acquisition_ready"},
    "blocked_capability": set(SUCCESS_STATES[:5]),
    "partial_commit": {"write_authorized", "imported"},
    "readback_mismatch": {"imported"},
}
RESULT_STATUSES = {
    "pending",
    "imported",
    "readback_verified",
    "blocked",
    "failed",
    "partial",
    "readback_mismatch",
}


def canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def digest_value(value: Any) -> str:
    return "sha256:" + hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def normalize_digest(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    match = DIGEST_RE.fullmatch(value)
    return "sha256:" + match.group(1) if match else None


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()


def compute_identity_fingerprint(target: dict[str, Any]) -> str:
    return digest_value(target)


def compute_state_fingerprint(
    identity_sha256: str, collection_version: int, parent_keys: list[str]
) -> str:
    return digest_value(
        {
            "identity_sha256": normalize_digest(identity_sha256) or identity_sha256,
            "collection_version": collection_version,
            "top_level_parent_keys": sorted(parent_keys),
        }
    )


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as stream:
        return json.load(stream)


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _exact_keys(
    value: dict[str, Any], allowed: set[str], label: str, errors: list[str]
) -> None:
    unexpected = sorted(set(value) - allowed)
    if unexpected:
        errors.append(f"{label}: unexpected fields {unexpected}")


def validate_target_fingerprint(
    target: Any, fingerprint: Any, label: str, errors: list[str]
) -> None:
    target_keys = {
        "group_id",
        "library_id",
        "library_name",
        "collection_key",
        "collection_path",
    }
    if not isinstance(target, dict):
        errors.append(f"{label}.target: must be an object")
        return
    _exact_keys(target, target_keys, f"{label}.target", errors)
    if set(target) != target_keys:
        errors.append(f"{label}.target: must contain exactly {sorted(target_keys)}")
    if not _is_int(target.get("group_id")) or target.get("group_id", 0) <= 0:
        errors.append(f"{label}.target.group_id: invalid")
    if not _is_int(target.get("library_id")) or target.get("library_id", -1) < 0:
        errors.append(f"{label}.target.library_id: invalid")
    if not isinstance(target.get("library_name"), str) or not target.get(
        "library_name", ""
    ).strip():
        errors.append(f"{label}.target.library_name: invalid")
    if not isinstance(target.get("collection_key"), str) or not ITEM_KEY_RE.fullmatch(
        target.get("collection_key", "")
    ):
        errors.append(f"{label}.target.collection_key: invalid")
    path = target.get("collection_path")
    if (
        not isinstance(path, list)
        or not path
        or any(not isinstance(part, str) or not part.strip() for part in path)
    ):
        errors.append(f"{label}.target.collection_path: invalid")

    fp_keys = {
        "identity_sha256",
        "state_sha256",
        "captured_at",
        "collection_version",
        "top_level_parent_keys",
    }
    if not isinstance(fingerprint, dict):
        errors.append(f"{label}.target_fingerprint: must be an object")
        return
    _exact_keys(fingerprint, fp_keys, f"{label}.target_fingerprint", errors)
    if set(fingerprint) != fp_keys:
        errors.append(
            f"{label}.target_fingerprint: must contain exactly {sorted(fp_keys)}"
        )
        return
    identity = normalize_digest(fingerprint.get("identity_sha256"))
    state = normalize_digest(fingerprint.get("state_sha256"))
    version = fingerprint.get("collection_version")
    keys = fingerprint.get("top_level_parent_keys")
    if identity is None:
        errors.append(f"{label}.target_fingerprint.identity_sha256: invalid")
    if state is None:
        errors.append(f"{label}.target_fingerprint.state_sha256: invalid")
    if not _is_int(version) or version < 0:
        errors.append(f"{label}.target_fingerprint.collection_version: invalid")
    if (
        not isinstance(keys, list)
        or any(not isinstance(key, str) or not ITEM_KEY_RE.fullmatch(key) for key in keys)
        or keys != sorted(set(keys))
    ):
        errors.append(
            f"{label}.target_fingerprint.top_level_parent_keys: must be sorted unique keys"
        )
    if identity is not None and identity != compute_identity_fingerprint(target):
        errors.append(f"{label}: identity fingerprint mismatch")
    if (
        identity is not None
        and state is not None
        and _is_int(version)
        and isinstance(keys, list)
        and state != compute_state_fingerprint(identity, version, keys)
    ):
        errors.append(f"{label}: state fingerprint mismatch")


class _NoteParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.seen_root = False
        self.schema_version: str | None = None
        self.note_contract: str | None = None
        self.access_level: str | None = None
        self.capture = False
        self.parts: list[str] = []
        self.headings: list[str] = []

    def handle_starttag(
        self, tag: str, attrs: list[tuple[str, str | None]]
    ) -> None:
        if not self.seen_root:
            self.seen_root = True
            values = {key: value or "" for key, value in attrs}
            if tag == "div":
                self.schema_version = values.get("data-schema-version")
                self.note_contract = values.get("data-note-contract") or None
                self.access_level = (
                    values.get("data-access-level", "").strip().lower() or None
                )
        if tag == "h2":
            self.capture = True
            self.parts = []

    def handle_data(self, data: str) -> None:
        if self.capture:
            self.parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "h2" and self.capture:
            self.headings.append("".join(self.parts).strip())
            self.capture = False


def verify_file(
    reference: Any, label: str, errors: list[str], *, pdf: bool = False
) -> Path | None:
    if not isinstance(reference, dict):
        errors.append(f"{label}: must be an object")
        return None
    raw_path = reference.get("path")
    expected = normalize_digest(reference.get("sha256"))
    if not isinstance(raw_path, str) or not raw_path:
        errors.append(f"{label}.path: invalid")
        return None
    path = Path(raw_path)
    if not path.is_absolute():
        errors.append(f"{label}.path: must be absolute")
        return None
    if path.is_symlink():
        errors.append(f"{label}.path: symlinks are not accepted")
        return None
    try:
        resolved = path.resolve(strict=True)
    except OSError as exc:
        errors.append(f"{label}.path: unavailable: {exc}")
        return None
    if not resolved.is_file():
        errors.append(f"{label}.path: must be a regular file")
        return None
    if expected is None:
        errors.append(f"{label}.sha256: invalid")
    elif sha256_file(resolved) != expected:
        errors.append(f"{label}: file hash mismatch")
    if pdf:
        with resolved.open("rb") as stream:
            if stream.read(5) != b"%PDF-":
                errors.append(f"{label}: invalid PDF signature")
    return resolved


def identity_key(
    identity: Any, label: str, errors: list[str]
) -> tuple[str, str] | None:
    if not isinstance(identity, dict):
        errors.append(f"{label}: must be an object")
        return None
    _exact_keys(
        identity,
        {"type", "value", "version", "title", "year", "creators"},
        label,
        errors,
    )
    kind = identity.get("type")
    raw = identity.get("value")
    if kind not in {
        "doi",
        "pmid",
        "isbn",
        "arxiv",
        "repository",
        "title_author_year",
    }:
        errors.append(f"{label}.type: unsupported")
        return None
    if not isinstance(raw, str) or not raw.strip():
        errors.append(f"{label}.value: invalid")
        return None
    normalized = raw.strip().lower()
    if kind == "doi":
        for prefix in ("https://doi.org/", "http://doi.org/", "doi:"):
            if normalized.startswith(prefix):
                normalized = normalized[len(prefix) :]
        if "/" not in normalized:
            errors.append(f"{label}.value: invalid DOI")
    if kind == "title_author_year":
        creators = identity.get("creators")
        if (
            not isinstance(identity.get("title"), str)
            or not identity.get("title", "").strip()
            or not _is_int(identity.get("year"))
            or not isinstance(creators, list)
            or not creators
        ):
            errors.append(f"{label}: title_author_year requires title/year/creators")
    return kind, normalized


def validate_effect(
    decision: str, effect: Any, label: str, errors: list[str]
) -> None:
    keys = {
        "new_parent_count",
        "target_membership",
        "note_action",
        "attachment_action",
    }
    if not isinstance(effect, dict) or set(effect) != keys:
        errors.append(f"{label}: must contain exactly {sorted(keys)}")
        return
    if effect["new_parent_count"] not in {0, 1} or isinstance(
        effect["new_parent_count"], bool
    ):
        errors.append(f"{label}.new_parent_count: invalid")
    if not isinstance(effect["target_membership"], bool):
        errors.append(f"{label}.target_membership: invalid")
    if effect["note_action"] not in {"create", "update", "no_op"}:
        errors.append(f"{label}.note_action: invalid")
    if effect["attachment_action"] not in {"create", "no_op"}:
        errors.append(f"{label}.attachment_action: invalid")
    if decision in {"create_parent", "metadata_only_create"}:
        if effect["new_parent_count"] != 1 or effect["target_membership"] is not True:
            errors.append(f"{label}: create requires one new target parent")
    elif effect["new_parent_count"] != 0:
        errors.append(f"{label}: non-create cannot create a parent")
    if (
        decision == "reuse_existing_parent_add_collection"
        and effect["target_membership"] is not True
    ):
        errors.append(f"{label}: reuse must end in membership")
    if decision == "create_missing_note" and effect["note_action"] != "create":
        errors.append(f"{label}: create note effect mismatch")
    if decision == "update_existing_note" and effect["note_action"] != "update":
        errors.append(f"{label}: update note effect mismatch")
    if decision == "attach_missing_pdf" and effect["attachment_action"] != "create":
        errors.append(f"{label}: attach effect mismatch")
    if decision in BLOCKED_DECISIONS | {"no_op_verified"} and (
        effect["note_action"] != "no_op"
        or effect["attachment_action"] != "no_op"
    ):
        errors.append(f"{label}: blocked/no-op cannot mutate children")


def validate_entry(
    entry: Any, index: int, errors: list[str]
) -> tuple[str | None, tuple[str, str] | None]:
    label = f"entries[{index}]"
    if not isinstance(entry, dict):
        errors.append(f"{label}: must be an object")
        return None, None
    allowed = {
        "entry_id",
        "canonical_identity",
        "decision",
        "handler",
        "gate_status",
        "fulltext_status",
        "expected_effect",
        "bundle_path",
        "bundle_sha256",
        "note_artifact",
        "pdf_artifacts",
        "existing_parent",
    }
    required = {
        "entry_id",
        "canonical_identity",
        "decision",
        "handler",
        "gate_status",
        "fulltext_status",
        "expected_effect",
    }
    _exact_keys(entry, allowed, label, errors)
    if not required <= set(entry):
        errors.append(f"{label}: missing fields {sorted(required - set(entry))}")
    entry_id = entry.get("entry_id")
    if not isinstance(entry_id, str) or not entry_id.strip():
        errors.append(f"{label}.entry_id: invalid")
        entry_id = None
    canonical = identity_key(
        entry.get("canonical_identity"), f"{label}.canonical_identity", errors
    )
    decision = entry.get("decision")
    if not isinstance(decision, str) or decision not in DECISION_HANDLER:
        errors.append(f"{label}.decision: unsupported or non-exclusive")
        return entry_id, canonical
    if entry.get("handler") != DECISION_HANDLER[decision]:
        errors.append(f"{label}: handler is incompatible with {decision}")
    blocked = decision in BLOCKED_DECISIONS
    if entry.get("gate_status") != ("blocked" if blocked else "golden"):
        errors.append(f"{label}: gate_status does not match decision")
    fulltext = entry.get("fulltext_status")
    if fulltext not in {"fulltext_verified", "metadata_only", "blocked_access"}:
        errors.append(f"{label}.fulltext_status: invalid")
    if decision == "blocked_access" and fulltext != "blocked_access":
        errors.append(f"{label}: blocked_access status mismatch")
    if decision == "metadata_only_create" and fulltext != "metadata_only":
        errors.append(f"{label}: metadata-only status mismatch")
    validate_effect(
        decision, entry.get("expected_effect"), f"{label}.expected_effect", errors
    )

    existing = entry.get("existing_parent")
    if decision in EXISTING_DECISIONS and not isinstance(existing, dict):
        errors.append(f"{label}: existing_parent is required")
    if isinstance(existing, dict):
        if set(existing) != {"key", "version", "in_target"}:
            errors.append(f"{label}.existing_parent: invalid fields")
        if not isinstance(existing.get("key"), str) or not ITEM_KEY_RE.fullmatch(
            existing.get("key", "")
        ):
            errors.append(f"{label}.existing_parent.key: invalid")
        if not _is_int(existing.get("version")) or existing.get("version", 0) <= 0:
            errors.append(f"{label}.existing_parent.version: invalid")
        if not isinstance(existing.get("in_target"), bool):
            errors.append(f"{label}.existing_parent.in_target: invalid")
        if existing.get("in_target") is False and decision not in {
            "reuse_existing_parent_add_collection",
            "blocked_unsupported_operation",
        }:
            errors.append(
                f"{label}: existing parent outside target must be "
                "reuse_existing_parent_add_collection or blocked_unsupported_operation"
            )
        if decision in {"create_parent", "metadata_only_create"}:
            errors.append(
                f"{label}: existing parent must never be handled by a create decision"
            )

    create = decision in {"create_parent", "metadata_only_create"}
    if create:
        path = verify_file(
            {"path": entry.get("bundle_path"), "sha256": entry.get("bundle_sha256")},
            f"{label}.bundle",
            errors,
        )
        if path is not None:
            try:
                if not isinstance(load_json(path), dict):
                    errors.append(f"{label}.bundle: native bundle must be an object")
            except (OSError, UnicodeError, json.JSONDecodeError) as exc:
                errors.append(f"{label}.bundle: invalid JSON: {exc}")
    elif "bundle_path" in entry or "bundle_sha256" in entry:
        errors.append(f"{label}: only create decisions may reference a bundle")

    effect = entry.get("expected_effect")
    note_action = effect.get("note_action") if isinstance(effect, dict) else None
    note = entry.get("note_artifact")
    if note_action in {"create", "update"} and note is None:
        errors.append(f"{label}: note mutation requires note_artifact")
    if note is not None:
        if not isinstance(note, dict) or note.get("schema_version") != "9":
            errors.append(f"{label}.note_artifact: schema_version must be 9")
        note_path = verify_file(note, f"{label}.note_artifact", errors)
        if note_path is not None:
            parser = _NoteParser()
            try:
                parser.feed(note_path.read_text(encoding="utf-8"))
            except (OSError, UnicodeError) as exc:
                errors.append(f"{label}.note_artifact: unreadable: {exc}")
            else:
                if parser.schema_version != "9":
                    errors.append(f"{label}.note_artifact: root is not schema 9")
                if parser.note_contract == PAPER_KNOWLEDGE_NOTE_CONTRACT:
                    note_errors, _, summary = validate_note(
                        note_path.read_text(encoding="utf-8")
                    )
                    errors.extend(
                        f"{label}.note_artifact: {error}" for error in note_errors
                    )
                    if parser.access_level == "metadata_only":
                        errors.append(
                            f"{label}.note_artifact: PaperKnowledgeNote/v2 "
                            "cannot use the metadata-only marker"
                        )
                    if parser.headings != PAPER_KNOWLEDGE_NOTE_SECTIONS:
                        errors.append(
                            f"{label}.note_artifact: PaperKnowledgeNote/v2 "
                            "section order mismatch"
                        )
                    if isinstance(summary, dict) and summary.get("access_level") != "full_text":
                        errors.append(
                            f"{label}.note_artifact: PaperKnowledgeNote/v2 "
                            "must validate as full_text"
                        )
                    if fulltext != "fulltext_verified":
                        errors.append(
                            f"{label}.note_artifact: PaperKnowledgeNote/v2 "
                            "requires fulltext_verified entry status"
                        )
                elif parser.note_contract is not None:
                    errors.append(
                        f"{label}.note_artifact: unsupported data-note-contract "
                        f"'{parser.note_contract}'"
                    )
                elif parser.access_level == "metadata_only":
                    note_errors, _, summary = validate_note(
                        note_path.read_text(encoding="utf-8")
                    )
                    errors.extend(
                        f"{label}.note_artifact: {error}" for error in note_errors
                    )
                    if parser.headings != NOTE_SECTIONS:
                        errors.append(
                            f"{label}.note_artifact: metadata-only section order mismatch"
                        )
                    if not isinstance(summary, dict) or summary.get(
                        "note_projection"
                    ) != "metadata_only":
                        errors.append(
                            f"{label}.note_artifact: metadata-only marker did not "
                            "validate as metadata_only"
                        )
                    if fulltext != "metadata_only":
                        errors.append(
                            f"{label}.note_artifact: metadata-only marker requires "
                            "metadata_only entry status"
                        )
                elif parser.access_level in (None, "full_text"):
                    if parser.headings != NOTE_SECTIONS:
                        errors.append(
                            f"{label}.note_artifact: legacy section order mismatch"
                        )
                    if fulltext == "metadata_only":
                        errors.append(
                            f"{label}.note_artifact: metadata_only entry requires "
                            "the explicit metadata-only marker"
                        )
                else:
                    errors.append(
                        f"{label}.note_artifact: unsupported data-access-level "
                        f"'{parser.access_level}'"
                    )

    pdfs = entry.get("pdf_artifacts", [])
    if not isinstance(pdfs, list):
        errors.append(f"{label}.pdf_artifacts: must be an array")
        pdfs = []
    has_fulltext = False
    for pdf_index, artifact in enumerate(pdfs):
        artifact_label = f"{label}.pdf_artifacts[{pdf_index}]"
        if not isinstance(artifact, dict):
            errors.append(f"{artifact_label}: must be an object")
            continue
        role = artifact.get("artifact_role")
        counts = artifact.get("counts_as_fulltext")
        if role not in MAIN_TEXT_ROLES | SI_ROLES:
            errors.append(f"{artifact_label}.artifact_role: invalid")
        if not isinstance(counts, bool):
            errors.append(f"{artifact_label}.counts_as_fulltext: invalid")
        if role in SI_ROLES and counts is True:
            errors.append(
                f"{artifact_label}: supporting information cannot count as full text"
            )
        if role in MAIN_TEXT_ROLES and counts is True:
            has_fulltext = True
        verify_file(artifact, artifact_label, errors, pdf=True)
    if fulltext == "fulltext_verified" and not has_fulltext:
        errors.append(
            f"{label}: fulltext_verified requires a verified main-text PDF"
        )
    if fulltext in {"metadata_only", "blocked_access"} and has_fulltext:
        errors.append(f"{label}: non-fulltext status has a fulltext artifact")
    if decision == "attach_missing_pdf" and not pdfs:
        errors.append(f"{label}: attach_missing_pdf requires a PDF")
    return entry_id, canonical


def validate_batch(batch: Any) -> list[str]:
    errors: list[str] = []
    if not isinstance(batch, dict):
        return ["manifest: must be an object"]
    allowed = {
        "schema",
        "batch_id",
        "created_at",
        "target",
        "target_fingerprint",
        "entries",
    }
    _exact_keys(batch, allowed, "manifest", errors)
    if batch.get("schema") != "CurationBatch/v1":
        errors.append("schema_mismatch: expected CurationBatch/v1")
    for field in ("batch_id", "created_at"):
        if not isinstance(batch.get(field), str) or not batch.get(field, "").strip():
            errors.append(f"manifest.{field}: invalid")
    validate_target_fingerprint(
        batch.get("target"), batch.get("target_fingerprint"), "manifest", errors
    )
    entries = batch.get("entries")
    if not isinstance(entries, list) or not entries:
        errors.append("manifest.entries: must be a nonempty array")
        return errors
    seen_ids: set[str] = set()
    seen_identities: set[tuple[str, str]] = set()
    for index, entry in enumerate(entries):
        entry_id, canonical = validate_entry(entry, index, errors)
        if entry_id is not None:
            if entry_id in seen_ids:
                errors.append(f"entries[{index}]: duplicate entry_id {entry_id}")
            seen_ids.add(entry_id)
        if canonical is not None:
            if canonical in seen_identities:
                errors.append(
                    f"entries[{index}]: duplicate canonical identity {canonical}"
                )
            seen_identities.add(canonical)
    return errors


def validate_observed_target(
    observed: Any, batch: dict[str, Any]
) -> list[str]:
    errors: list[str] = []
    if not isinstance(observed, dict) or observed.get("schema") != "ObservedTarget/v1":
        return ["schema_mismatch: observed target must be ObservedTarget/v1"]
    _exact_keys(
        observed,
        {"schema", "target", "target_fingerprint"},
        "observed_target",
        errors,
    )
    validate_target_fingerprint(
        observed.get("target"),
        observed.get("target_fingerprint"),
        "observed_target",
        errors,
    )
    if observed.get("target") != batch.get("target"):
        errors.append("target_drift: target identity fields differ")
    approved = batch.get("target_fingerprint", {})
    actual = observed.get("target_fingerprint", {})
    if normalize_digest(actual.get("identity_sha256")) != normalize_digest(
        approved.get("identity_sha256")
    ):
        errors.append("target_drift: identity fingerprint differs")
    if normalize_digest(actual.get("state_sha256")) != normalize_digest(
        approved.get("state_sha256")
    ):
        errors.append("target_drift: mutable state fingerprint differs")
    return errors


def _strict_json_equal(left: Any, right: Any) -> bool:
    try:
        return canonical_json_bytes(left) == canonical_json_bytes(right)
    except (TypeError, ValueError):
        return False


def _is_blocked_entry(entry: dict[str, Any]) -> bool:
    return entry.get("decision") in BLOCKED_DECISIONS


def _is_no_mutation_effect(effect: Any) -> bool:
    return (
        isinstance(effect, dict)
        and set(effect)
        == {
            "new_parent_count",
            "target_membership",
            "note_action",
            "attachment_action",
        }
        and effect.get("new_parent_count") == 0
        and not isinstance(effect.get("new_parent_count"), bool)
        and isinstance(effect.get("target_membership"), bool)
        and effect.get("note_action") == "no_op"
        and effect.get("attachment_action") == "no_op"
    )


def _validate_blocked_result(
    entry_id: str,
    entry: dict[str, Any],
    result: dict[str, Any] | None,
    errors: list[str],
) -> None:
    expected_effect = entry.get("expected_effect")
    if not _is_no_mutation_effect(expected_effect):
        errors.append(f"execution: blocked entry {entry_id} expects mutation")
    if result is None:
        errors.append(f"execution: blocked entry {entry_id} lacks blocked result")
        return
    if result.get("status") != "blocked":
        errors.append(f"execution: blocked entry {entry_id} status must be blocked")
    observed_effect = result.get("observed_effect")
    if not _strict_json_equal(observed_effect, expected_effect):
        errors.append(f"execution: blocked entry {entry_id} effect mismatch")
    if not _is_no_mutation_effect(observed_effect):
        errors.append(f"execution: blocked entry {entry_id} reports mutation")


def validate_execution(execution: Any, batch: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if not isinstance(execution, dict):
        return ["execution: must be an object"]
    allowed = {
        "schema",
        "batch_digest",
        "target_identity_sha256",
        "initial_state_sha256",
        "events",
        "results",
    }
    _exact_keys(execution, allowed, "execution", errors)
    if execution.get("schema") != "CurationExecution/v1":
        errors.append("schema_mismatch: expected CurationExecution/v1")
    expected_digest = digest_value(batch)
    if normalize_digest(execution.get("batch_digest")) != expected_digest:
        errors.append("execution.batch_digest: mismatch")
    fingerprint = batch.get("target_fingerprint", {})
    if normalize_digest(execution.get("target_identity_sha256")) != normalize_digest(
        fingerprint.get("identity_sha256")
    ):
        errors.append("execution.target_identity_sha256: mismatch")
    if normalize_digest(execution.get("initial_state_sha256")) != normalize_digest(
        fingerprint.get("state_sha256")
    ):
        errors.append("execution.initial_state_sha256: mismatch")

    events = execution.get("events")
    final_state: str | None = None
    if not isinstance(events, list) or not events:
        errors.append("execution.events: must be nonempty")
    else:
        previous: str | None = None
        for index, event in enumerate(events):
            label = f"execution.events[{index}]"
            if not isinstance(event, dict):
                errors.append(f"{label}: must be an object")
                continue
            _exact_keys(
                event,
                {"sequence", "state", "recorded_at", "detail", "evidence"},
                label,
                errors,
            )
            if event.get("sequence") != index + 1:
                errors.append(f"{label}.sequence: invalid")
            state = event.get("state")
            if state not in set(SUCCESS_STATES) | FAILURE_STATES:
                errors.append(f"{label}.state: invalid")
                continue
            if index == 0 and state != "mapped":
                errors.append(f"{label}: execution must start at mapped")
            elif previous in FAILURE_STATES:
                errors.append(f"{label}: failure states are terminal")
            elif index > 0 and state in SUCCESS_STATES:
                expected_next = (
                    SUCCESS_STATES[SUCCESS_STATES.index(previous) + 1]
                    if previous in SUCCESS_STATES[:-1]
                    else None
                )
                if state != expected_next:
                    errors.append(
                        f"{label}: strict transition requires {expected_next}"
                    )
            elif (
                index > 0
                and state in FAILURE_STATES
                and previous not in FAILURE_FROM[state]
            ):
                errors.append(f"{label}: {state} is not allowed from {previous}")
            if state in FAILURE_STATES and (
                not isinstance(event.get("detail"), str)
                or not event.get("detail", "").strip()
            ):
                errors.append(f"{label}: failure requires detail")
            if state == "write_authorized":
                evidence = event.get("evidence")
                if not isinstance(evidence, dict) or normalize_digest(
                    evidence.get("approved_batch_digest")
                ) != expected_digest:
                    errors.append(
                        f"{label}: authorization must bind batch digest"
                    )
            previous = state
        if isinstance(events[-1], dict):
            final_state = events[-1].get("state")

    entries = [
        value
        for value in batch.get("entries", [])
        if isinstance(value, dict) and isinstance(value.get("entry_id"), str)
    ]
    entry_map = {value["entry_id"]: value for value in entries}
    results = execution.get("results")
    if not isinstance(results, list):
        errors.append("execution.results: must be an array")
        results = []
    result_map: dict[str, dict[str, Any]] = {}
    for index, result in enumerate(results):
        label = f"execution.results[{index}]"
        if not isinstance(result, dict):
            errors.append(f"{label}: must be an object")
            continue
        _exact_keys(
            result,
            {"entry_id", "status", "observed_effect", "detail"},
            label,
            errors,
        )
        entry_id = result.get("entry_id")
        if entry_id not in entry_map:
            errors.append(f"{label}.entry_id: unknown")
            continue
        if entry_id in result_map:
            errors.append(f"{label}.entry_id: duplicate")
        result_map[entry_id] = result
        if result.get("status") not in RESULT_STATUSES:
            errors.append(f"{label}.status: invalid")

    blocked_entries = {
        entry_id: entry
        for entry_id, entry in entry_map.items()
        if _is_blocked_entry(entry)
    }
    golden_entries = {
        entry_id: entry
        for entry_id, entry in entry_map.items()
        if not _is_blocked_entry(entry) and entry.get("gate_status") == "golden"
    }
    if final_state in SUCCESS_STATES[3:]:
        for entry_id, entry in blocked_entries.items():
            _validate_blocked_result(
                entry_id, entry, result_map.get(entry_id), errors
            )
        unclassified = sorted(set(entry_map) - set(blocked_entries) - set(golden_entries))
        if unclassified:
            errors.append(
                f"execution: success path contains non-golden actionable entries {unclassified}"
            )
    if final_state == "readback_verified":
        for entry_id, entry in golden_entries.items():
            result = result_map.get(entry_id)
            if result is None or result.get("status") != "readback_verified":
                errors.append(f"execution: {entry_id} lacks readback result")
            elif not _strict_json_equal(
                result.get("observed_effect"), entry.get("expected_effect")
            ):
                errors.append(f"execution: {entry_id} readback effect mismatch")
    if final_state == "partial_commit":
        statuses = {value.get("status") for value in result_map.values()}
        if not statuses & {"imported", "readback_verified", "partial"} or not statuses & {
            "pending",
            "failed",
            "partial",
        }:
            errors.append(
                "execution: partial_commit needs committed and incomplete effects"
            )
    if final_state == "readback_mismatch":
        mismatch = any(
            result.get("status") == "readback_mismatch"
            or result.get("observed_effect")
            != entry_map[result["entry_id"]].get("expected_effect")
            for result in result_map.values()
        )
        if not mismatch:
            errors.append(
                "execution: readback_mismatch requires mismatch evidence"
            )
    return errors


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description=__doc__)
    commands = root.add_subparsers(dest="command", required=True)
    verify = commands.add_parser("verify")
    verify.add_argument("manifest", type=Path)
    verify.add_argument("--execution", type=Path)
    verify.add_argument("--observed-target", type=Path)
    digest = commands.add_parser("digest")
    digest.add_argument("manifest", type=Path)
    return root


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        manifest = load_json(args.manifest)
        manifest_digest = digest_value(manifest)
        if args.command == "digest":
            print(manifest_digest)
            return 0
        errors = validate_batch(manifest)
        if args.observed_target:
            errors.extend(
                validate_observed_target(load_json(args.observed_target), manifest)
            )
        final_state = None
        if args.execution:
            execution = load_json(args.execution)
            errors.extend(validate_execution(execution, manifest))
            if (
                isinstance(execution, dict)
                and isinstance(execution.get("events"), list)
                and execution["events"]
            ):
                final_state = execution["events"][-1].get("state")
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
        print(
            json.dumps({"valid": False, "errors": [str(exc)]}, ensure_ascii=False),
            file=sys.stderr,
        )
        return 2
    print(
        json.dumps(
            {
                "valid": not errors,
                "batch_digest": manifest_digest,
                "entry_count": len(manifest.get("entries", [])),
                "execution_final_state": final_state,
                "errors": errors,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
