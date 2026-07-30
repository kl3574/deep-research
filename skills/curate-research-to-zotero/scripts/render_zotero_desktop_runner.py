#!/usr/bin/env python3
"""Render a manifest-bound script for Zotero Desktop's Run JavaScript tool."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

from verify_note_html import validate_note


SENTINEL = "const CONFIG = null; // __DEEP_RESEARCH_ZOTERO_CONFIG__"
REQUIRED_TARGET_FIELDS = {
    "group_id": int,
    "library_id": int,
    "library_name": str,
    "local_collection_id": int,
    "collection_key": str,
    "collection_name": str,
    "collection_path": list,
}
ITEM_KEY_PATTERN = re.compile(r"^[A-Z0-9]{8}$")
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
_STORAGE_NORMALIZATION_CONTROL_PATTERN = re.compile(r"[\x00-\x08\x0B\x0C\x0E-\x1F\x7F]")
SUPPORTED_PDF_LINK_MODES = {
    "imported_file",
    "imported_url",
    "linked_file",
}
PARENT_DATA_SNAPSHOT_SCHEMA = "zotero-item-bibliographic-v1"


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def normalize_staged_html_for_storage(text: str) -> str:
    return _STORAGE_NORMALIZATION_CONTROL_PATTERN.sub("", text).strip()


def load_and_validate_manifest(
    path: Path,
) -> tuple[bytes, dict[str, object], int, int, list[str]]:
    raw = path.read_bytes()
    payload = json.loads(raw.decode("utf-8"))
    if not isinstance(payload, dict) or payload.get("manifest_version") != "2":
        raise ValueError("expected migration manifest_version 2")
    if payload.get("write_performed") is not False:
        raise ValueError("migration manifest must have write_performed=false")
    target = payload.get("target")
    if not isinstance(target, dict):
        raise ValueError("migration manifest target is missing")
    for field, expected_type in REQUIRED_TARGET_FIELDS.items():
        value = target.get(field)
        if expected_type is int:
            valid = type(value) is int and value > 0
        elif expected_type is list:
            valid = (
                isinstance(value, list)
                and bool(value)
                and all(isinstance(part, str) and part for part in value)
            )
        else:
            valid = isinstance(value, expected_type) and bool(value)
        if not valid:
            raise ValueError(f"invalid manifest target field: {field}")
    if target["collection_path"][-1] != target["collection_name"]:
        raise ValueError("collection_path must end with collection_name")

    entries = payload.get("entries")
    if not isinstance(entries, list):
        raise ValueError("migration manifest entries are missing")
    if any(not isinstance(entry, dict) for entry in entries):
        raise ValueError("migration manifest contains a non-object entry")
    inventory = payload.get("collection_item_inventory")
    if (
        not isinstance(inventory, list)
        or not inventory
        or any(
            not isinstance(key, str) or not ITEM_KEY_PATTERN.fullmatch(key)
            for key in inventory
        )
        or inventory != sorted(inventory)
        or len(inventory) != len(set(inventory))
    ):
        raise ValueError(
            "migration manifest collection_item_inventory is invalid"
        )
    entry_parent_keys = [entry.get("parent_key") for entry in entries]
    if (
        any(
            not isinstance(key, str) or not ITEM_KEY_PATTERN.fullmatch(key)
            for key in entry_parent_keys
        )
        or sorted(entry_parent_keys) != inventory
    ):
        raise ValueError(
            "migration manifest entries do not exactly cover the collection inventory"
        )
    allowed_statuses = {
        "staged_verified",
        "unchanged_verified",
        "create_verified",
        "staged_invalid",
        "no_existing_note",
        "blocked_multiple_notes",
        "blocked_multiple_pdfs",
    }
    observed_statuses = {
        entry.get("status")
        for entry in entries
        if isinstance(entry, dict)
    }
    unknown_statuses = observed_statuses - allowed_statuses
    if unknown_statuses:
        raise ValueError(
            f"migration manifest has unsupported entry statuses: "
            f"{sorted(str(status) for status in unknown_statuses)}"
        )
    blocking = [
        entry
        for entry in entries
        if isinstance(entry, dict)
        and entry.get("status")
        in {"staged_invalid", "blocked_multiple_notes", "blocked_multiple_pdfs"}
    ]
    if blocking:
        raise ValueError(
            "migration manifest contains invalid or ambiguous note entries; "
            "resolve them before generating a runner"
        )
    for entry in entries:
        parent_key = entry.get("parent_key")
        child_item_inventory = entry.get("child_item_inventory")
        child_note_inventory = entry.get("child_note_inventory")
        child_attachment_inventory = entry.get("child_attachment_inventory")
        for label, child_inventory in (
            ("child_note_inventory", child_note_inventory),
            ("child_attachment_inventory", child_attachment_inventory),
        ):
            if (
                not isinstance(child_inventory, list)
                or any(
                    not isinstance(key, str)
                    or not ITEM_KEY_PATTERN.fullmatch(key)
                    for key in child_inventory
                )
                or child_inventory != sorted(child_inventory)
                or len(child_inventory) != len(set(child_inventory))
            ):
                raise ValueError(f"{parent_key}: {label} is invalid")
        status = entry.get("status")
        if child_item_inventory is not None:
            if (
                not isinstance(child_item_inventory, list)
                or any(
                    not isinstance(key, str)
                    or not ITEM_KEY_PATTERN.fullmatch(key)
                    for key in child_item_inventory
                )
                or child_item_inventory != sorted(child_item_inventory)
                or len(child_item_inventory) != len(set(child_item_inventory))
            ):
                raise ValueError(f"{parent_key}: child_item_inventory is invalid")
            if child_item_inventory != sorted(
                child_note_inventory + child_attachment_inventory
            ):
                raise ValueError(
                    f"{parent_key}: child_item_inventory is inconsistent"
                )
        if status == "no_existing_note" and child_note_inventory:
            raise ValueError(
                f"{parent_key}: no_existing_note has a nonempty child note inventory"
            )
        if status == "blocked_multiple_notes":
            if (
                len(child_note_inventory) < 2
                or entry.get("note_count") != len(child_note_inventory)
            ):
                raise ValueError(
                    f"{parent_key}: blocked_multiple_notes inventory is inconsistent"
                )
        if status == "blocked_multiple_pdfs":
            candidates = entry.get("pdf_attachment_candidates")
            if (
                not isinstance(candidates, list)
                or len(candidates) < 2
                or candidates != sorted(candidates)
                or any(key not in child_attachment_inventory for key in candidates)
            ):
                raise ValueError(
                    f"{parent_key}: blocked_multiple_pdfs inventory is inconsistent"
                )
        if status == "create_verified":
            if child_note_inventory:
                raise ValueError(
                    f"{parent_key}: create_verified requires zero existing notes"
                )
            if child_item_inventory is None:
                raise ValueError(
                    f"{parent_key}: create_verified requires a complete child inventory"
                )
            if entry.get("expected_parent_key") != parent_key:
                raise ValueError(
                    f"{parent_key}: create expected_parent_key is inconsistent"
                )
            parent_version = entry.get("parent_version")
            if type(parent_version) is not int or parent_version <= 0:
                raise ValueError(
                    f"{parent_key}: create parent_version is invalid"
                )
            if (
                entry.get("parent_data_snapshot_schema")
                != PARENT_DATA_SNAPSHOT_SCHEMA
                or not isinstance(
                    entry.get("parent_data_snapshot_sha256"),
                    str,
                )
                or not SHA256_PATTERN.fullmatch(
                    str(entry.get("parent_data_snapshot_sha256"))
                )
            ):
                raise ValueError(
                    f"{parent_key}: create parent data snapshot is invalid"
                )

    staged = [
        entry
        for entry in entries
        if isinstance(entry, dict) and entry.get("status") in {
            "staged_verified",
            "unchanged_verified",
            "create_verified",
        }
    ]
    mutation = [
        entry for entry in staged if str(entry.get("status")) == "staged_verified"
    ]
    if not staged:
        raise ValueError("migration manifest has no staged entries")
    existing_staged = [
        entry for entry in staged if entry.get("status") != "create_verified"
    ]
    create_staged = [
        entry for entry in staged if entry.get("status") == "create_verified"
    ]
    note_keys = [entry.get("note_key") for entry in existing_staged]
    mutation_keys = [str(entry.get("note_key")) for entry in mutation]
    if any(
        not isinstance(key, str) or not ITEM_KEY_PATTERN.fullmatch(key)
        for key in note_keys
    ):
        raise ValueError("a staged entry has an invalid note_key")
    if any(
        not isinstance(key, str) or not ITEM_KEY_PATTERN.fullmatch(key)
        for key in mutation_keys
    ):
        raise ValueError("a staged entry has an invalid note key")
    if len(note_keys) != len(set(note_keys)):
        raise ValueError("migration manifest contains duplicate note keys")
    if len(mutation_keys) != len(set(mutation_keys)):
        raise ValueError("migration manifest contains duplicate staged note keys")
    create_parent_keys = [str(entry.get("parent_key")) for entry in create_staged]
    if len(create_parent_keys) != len(set(create_parent_keys)):
        raise ValueError("migration manifest contains duplicate create parents")
    for entry in staged:
        status = str(entry.get("status"))
        is_create = status == "create_verified"
        note_key = (
            f"create:{entry.get('parent_key')}"
            if is_create
            else str(entry["note_key"])
        )
        parent_key = entry.get("expected_parent_key")
        if not isinstance(parent_key, str) or not ITEM_KEY_PATTERN.fullmatch(parent_key):
            raise ValueError(f"{note_key}: expected_parent_key is invalid")
        if entry.get("parent_key") != parent_key:
            raise ValueError(
                f"{note_key}: parent_key does not equal expected_parent_key"
            )
        expected_note_inventory = [] if is_create else [note_key]
        if entry.get("child_note_inventory") != expected_note_inventory:
            raise ValueError(
                f"{note_key}: staged child note inventory is inconsistent"
            )
        if not is_create:
            note_version = entry.get("note_version")
            if type(note_version) is not int or note_version <= 0:
                raise ValueError(f"{note_key}: note_version is invalid")
        path_fields = ("new_path",) if is_create else ("old_path", "new_path")
        for field in path_fields:
            value = entry.get(field)
            if not isinstance(value, str) or not Path(value).expanduser().is_absolute():
                raise ValueError(f"{note_key}: {field} must be an absolute path")
        hash_fields = ("new_sha256",) if is_create else ("old_sha256", "new_sha256")
        for field in hash_fields:
            value = entry.get(field)
            if not isinstance(value, str) or not SHA256_PATTERN.fullmatch(value):
                raise ValueError(f"{note_key}: {field} is invalid")
        pdf_path_value = entry.get("pdf_path")
        pdf_sha256 = entry.get("pdf_sha256")
        pdf_attachment_key = entry.get("pdf_attachment_key")
        pdf_attachment_link_mode = entry.get("pdf_attachment_link_mode")
        if (
            not isinstance(pdf_path_value, str)
            or not Path(pdf_path_value).expanduser().is_absolute()
            or not isinstance(pdf_sha256, str)
            or not SHA256_PATTERN.fullmatch(pdf_sha256)
            or not isinstance(pdf_attachment_key, str)
            or not ITEM_KEY_PATTERN.fullmatch(pdf_attachment_key)
            or pdf_attachment_key not in entry["child_attachment_inventory"]
            or pdf_attachment_link_mode not in SUPPORTED_PDF_LINK_MODES
        ):
            raise ValueError(
                f"{note_key}: PDF fields must identify one approved live child attachment"
            )
        errors = entry.get("validation_errors")
        if not isinstance(errors, list) or errors:
            raise ValueError(f"{note_key}: validation_errors must be an empty list")
        summary = entry.get("validation_summary")
        if not isinstance(summary, dict) or str(summary.get("schema_version")) != "9":
            raise ValueError(f"{note_key}: validation_summary is not schema version 9")
        new_path = Path(str(entry["new_path"])).expanduser().resolve()
        pdf_path = Path(pdf_path_value).expanduser().resolve()
        try:
            new_bytes = new_path.read_bytes()
            new_html = new_bytes.decode("utf-8")
            pdf_bytes = pdf_path.read_bytes()
            if is_create:
                old_bytes = None
            else:
                old_path = Path(str(entry["old_path"])).expanduser().resolve()
                old_bytes = old_path.read_bytes()
                old_bytes.decode("utf-8")
        except (OSError, UnicodeError) as exc:
            raise ValueError(f"{note_key}: staged input cannot be read: {exc}") from exc
        if old_bytes is not None and sha256_bytes(old_bytes) != entry["old_sha256"]:
            raise ValueError(f"{note_key}: old_path hash does not match manifest")
        if sha256_bytes(new_bytes) != entry["new_sha256"]:
            raise ValueError(f"{note_key}: new_path hash does not match manifest")
        if status == "staged_verified":
            storage_sha256 = sha256_bytes(
                normalize_staged_html_for_storage(new_html).encode("utf-8")
            )
            if storage_sha256 == entry["old_sha256"]:
                raise ValueError(
                    f"{note_key}: staged note normalizes to the existing note"
                )
        elif status == "unchanged_verified":
            if entry["old_sha256"] != entry["new_sha256"]:
                raise ValueError(
                    f"{note_key}: unchanged note hashes are inconsistent"
                )
            if old_bytes != new_bytes:
                raise ValueError(
                    f"{note_key}: unchanged note content changed"
                )
            if sha256_bytes(new_bytes) != entry["old_sha256"]:
                raise ValueError(
                    f"{note_key}: unchanged note normalization changed the stored digest"
                )
        if not pdf_bytes.startswith(b"%PDF-"):
            raise ValueError(f"{note_key}: pdf_path does not have PDF magic bytes")
        if sha256_bytes(pdf_bytes) != pdf_sha256:
            raise ValueError(f"{note_key}: pdf_path hash does not match manifest")
        validation_errors, _warnings, observed_summary = validate_note(new_html)
        if validation_errors:
            raise ValueError(
                f"{note_key}: staged note fails the live schema-9 validator: "
                f"{validation_errors}"
            )
        if str(observed_summary.get("schema_version")) != "9":
            raise ValueError(
                f"{note_key}: live validator did not confirm schema version 9"
            )
        if observed_summary.get("full_text_sha256") != pdf_sha256:
            raise ValueError(
                f"{note_key}: note full-text SHA-256 does not match pdf_sha256"
            )
    return raw, payload, len(staged), len(mutation), mutation_keys


def protected_manifest_paths(
    manifest_path: Path,
    payload: dict[str, object],
) -> set[Path]:
    protected = {manifest_path.resolve()}
    entries = payload.get("entries")
    if not isinstance(entries, list):
        return protected
    for entry in entries:
        if (
            not isinstance(entry, dict)
            or entry.get("status") not in {
                "staged_verified",
                "unchanged_verified",
                "create_verified",
            }
        ):
            continue
        for field in ("old_path", "new_path", "pdf_path"):
            value = entry.get(field)
            if not isinstance(value, str) or not value or value == "unresolved":
                continue
            candidate = Path(value).expanduser()
            if candidate.is_absolute():
                protected.add(candidate.resolve())
    return protected


def render_runner(
    manifest_path: Path,
    *,
    apply: bool,
    require_auto_sync_enabled: bool = False,
    report_path: Path | None = None,
    template_path: Path | None = None,
) -> str:
    manifest_path = manifest_path.expanduser().resolve()
    raw, payload, inventory_count, mutation_count, mutation_keys = (
        load_and_validate_manifest(manifest_path)
    )
    create_entries = [
        entry
        for entry in payload["entries"]
        if isinstance(entry, dict) and entry.get("status") == "create_verified"
    ]
    create_parent_keys = sorted(str(entry["parent_key"]) for entry in create_entries)
    mode = "apply" if apply else "dry_run"
    if report_path is None:
        report_path = manifest_path.parent / f"zotero_desktop_{mode}_report.json"
    report_path = report_path.expanduser().resolve()
    if not report_path.parent.is_dir():
        raise ValueError(f"report directory does not exist: {report_path.parent}")

    if template_path is None:
        template_path = Path(__file__).with_name(
            "zotero_desktop_note_migration.js"
        )
    template_path = template_path.expanduser().resolve()
    protected_paths = protected_manifest_paths(manifest_path, payload)
    protected_paths.add(template_path)
    if report_path in protected_paths:
        raise ValueError(
            "report path would overwrite the manifest, a staged input, "
            "a source PDF, or the runner template"
        )
    if report_path.is_dir():
        raise ValueError(f"report path is a directory: {report_path}")
    if report_path.exists():
        raise ValueError(
            f"report path already exists; choose a new evidence path: {report_path}"
        )
    template = template_path.read_text(encoding="utf-8")
    if template.count(SENTINEL) != 1:
        raise ValueError("Zotero Desktop runner template sentinel is missing or duplicated")
    config = {
        "apply": apply,
        "expectedInventoryNoteCount": inventory_count,
        "expectedMutationCount": mutation_count,
        "expectedMutationKeys": mutation_keys,
        "expectedCreateCount": len(create_entries),
        "expectedCreateParentKeys": create_parent_keys,
        "manifestPath": str(manifest_path),
        "manifestSHA256": sha256_bytes(raw),
        "requireAutoSyncEnabled": require_auto_sync_enabled,
        "reportPath": str(report_path),
    }
    rendered_config = "const CONFIG = " + json.dumps(
        config,
        ensure_ascii=True,
        sort_keys=True,
    ) + ";"
    return template.replace(SENTINEL, rendered_config)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--require-auto-sync-enabled", action="store_true")
    parser.add_argument("--report", type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        rendered = render_runner(
            args.manifest,
            apply=args.apply,
            require_auto_sync_enabled=args.require_auto_sync_enabled,
            report_path=args.report,
        )
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as error:
        print(f"runner generation failed: {error}", file=sys.stderr)
        return 1
    sys.stdout.write(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
