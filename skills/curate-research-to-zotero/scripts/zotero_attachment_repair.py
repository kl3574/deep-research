#!/usr/bin/env python3
"""Build, validate, and render an exact existing-parent PDF repair batch."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import sys
from pathlib import Path
from typing import Any


SCHEMA = "ZoteroAttachmentRepairManifest/v1"
BASELINE_SCHEMA = "ZoteroCorpusSnapshot/v1"
REPAIR_SCHEMA = "ExistingPdfRepairManifest/v1"
CONFIG_SENTINEL = "/*__ZOTERO_ATTACHMENT_REPAIR_CONFIG__*/"
SCRIPT_DIR = Path(__file__).resolve().parent
TEMPLATE_PATH = SCRIPT_DIR / "zotero_desktop_attachment_repair.js"
CORE_PATH = SCRIPT_DIR / "zotero_attachment_repair_core.js"


class ContractError(ValueError):
    """A closed-contract or bound-artifact validation failure."""


def canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def sha256_bytes(raw: bytes) -> str:
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def read_json(path: Path) -> tuple[bytes, dict[str, Any]]:
    raw = path.read_bytes()
    try:
        value = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ContractError(f"invalid JSON: {path}: {error}") from error
    if not isinstance(value, dict):
        raise ContractError(f"JSON root must be an object: {path}")
    return raw, value


def expect_exact_keys(value: Any, expected: set[str], context: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ContractError(f"{context} must be an object")
    actual = set(value)
    if actual != expected:
        missing = sorted(expected - actual)
        extra = sorted(actual - expected)
        raise ContractError(f"{context} keys mismatch; missing={missing}, extra={extra}")
    return value


def require_string(value: Any, context: str, *, allow_empty: bool = False) -> str:
    if not isinstance(value, str) or (not allow_empty and not value.strip()):
        raise ContractError(f"{context} must be a nonempty string")
    return value


def require_int(value: Any, context: str, *, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise ContractError(f"{context} must be an integer >= {minimum}")
    return value


def require_absolute_regular_file(value: Any, context: str) -> Path:
    raw = require_string(value, context)
    path = Path(raw).expanduser()
    if not path.is_absolute():
        raise ContractError(f"{context} must be absolute")
    if path.is_symlink():
        raise ContractError(f"{context} must not be a symlink")
    if not path.is_file():
        raise ContractError(f"{context} must be a readable regular file")
    return path.resolve()


def file_evidence(path: Path) -> dict[str, Any]:
    raw = path.read_bytes()
    return {
        "path": str(path),
        "size_bytes": len(raw),
        "sha256": sha256_bytes(raw),
        "magic": raw[:5].decode("ascii", errors="replace"),
        "content_type": "application/pdf",
    }


def normalized_attachments(parent: dict[str, Any]) -> list[dict[str, Any]]:
    children = parent.get("children")
    if not isinstance(children, list):
        raise ContractError(f"baseline parent {parent.get('key')} children must be a list")
    result: list[dict[str, Any]] = []
    for child in children:
        if not isinstance(child, dict) or child.get("item_type") != "attachment":
            continue
        projection = {
            "key": require_string(child.get("key"), "baseline attachment key"),
            "version": require_int(child.get("version"), "baseline attachment version"),
            "content_type": require_string(
                child.get("content_type"), "baseline attachment content_type"
            ),
            "link_mode": require_string(
                child.get("link_mode"), "baseline attachment link_mode"
            ),
        }
        result.append(projection)
    keys = [item["key"] for item in result]
    if len(keys) != len(set(keys)):
        raise ContractError(f"baseline parent {parent.get('key')} has duplicate attachments")
    return sorted(result, key=lambda item: item["key"])


def parent_projection(parent: dict[str, Any], collection_key: str) -> dict[str, Any]:
    return {
        "key": require_string(parent.get("key"), "baseline parent key"),
        "version": require_int(parent.get("version"), "baseline parent version"),
        "item_type": require_string(parent.get("item_type"), "baseline parent item_type"),
        "doi": require_string(parent.get("DOI", ""), "baseline parent DOI", allow_empty=True),
        "title": require_string(parent.get("title"), "baseline parent title"),
        "collection_key": collection_key,
    }


def seal_manifest(payload: dict[str, Any]) -> dict[str, Any]:
    sealed = copy.deepcopy(payload)
    sealed.pop("manifest_digest_sha256", None)
    sealed["manifest_digest_sha256"] = sha256_bytes(canonical_json_bytes(sealed))
    return sealed


def _unique_map(values: Any, key_field: str, context: str) -> dict[str, dict[str, Any]]:
    if not isinstance(values, list):
        raise ContractError(f"{context} must be a list")
    result: dict[str, dict[str, Any]] = {}
    for index, value in enumerate(values):
        if not isinstance(value, dict):
            raise ContractError(f"{context}[{index}] must be an object")
        key = require_string(value.get(key_field), f"{context}[{index}].{key_field}")
        if key in result:
            raise ContractError(f"duplicate {context} key: {key}")
        result[key] = value
    return result


def build_manifest(
    baseline_path: Path,
    repair_path: Path,
    *,
    group_id: int,
    library_id: int,
    library_name: str,
    local_collection_id: int,
    collection_key: str,
    collection_path: str,
) -> dict[str, Any]:
    baseline_path = require_absolute_regular_file(str(baseline_path), "baseline path")
    repair_path = require_absolute_regular_file(str(repair_path), "repair path")
    baseline_raw, baseline = read_json(baseline_path)
    repair_raw, repair = read_json(repair_path)
    if baseline.get("schema") != BASELINE_SCHEMA:
        raise ContractError("unsupported baseline schema")
    if repair.get("schema") != REPAIR_SCHEMA:
        raise ContractError("unsupported repair schema")

    collection = baseline.get("collection")
    if not isinstance(collection, dict):
        raise ContractError("baseline collection must be an object")
    if collection.get("group_id") != group_id:
        raise ContractError("target group_id does not match baseline")
    if collection.get("collection_key") != collection_key:
        raise ContractError("target collection_key does not match baseline")
    raw_path = collection.get("collection_path")
    if not isinstance(raw_path, list) or not raw_path:
        raise ContractError("baseline collection_path must be a nonempty list")
    target_path: list[dict[str, str]] = []
    for index, part in enumerate(raw_path):
        if not isinstance(part, dict):
            raise ContractError(f"baseline collection_path[{index}] must be an object")
        target_path.append(
            {
                "key": require_string(part.get("key"), "collection path key"),
                "name": require_string(part.get("name"), "collection path name"),
            }
        )
    requested_names = [part for part in collection_path.split("/") if part]
    if requested_names != [part["name"] for part in target_path]:
        raise ContractError("target collection path does not match baseline")
    if target_path[-1]["key"] != collection_key:
        raise ContractError("target collection key is not the baseline path leaf")

    parents = _unique_map(baseline.get("parents"), "key", "baseline parents")
    records = _unique_map(repair.get("records"), "item_key", "repair records")
    entries: list[dict[str, Any]] = []
    for item_key in sorted(records):
        record = records[item_key]
        parent = parents.get(item_key)
        if parent is None:
            raise ContractError(f"repair parent absent from baseline: {item_key}")
        projected_parent = parent_projection(parent, collection_key)
        if record.get("title") != projected_parent["title"]:
            raise ContractError(f"repair title does not match baseline: {item_key}")
        if record.get("DOI", "") != projected_parent["doi"]:
            raise ContractError(f"repair DOI does not match baseline: {item_key}")
        common = {
            "parent": projected_parent,
            "expected_attachments": normalized_attachments(parent),
        }
        status = record.get("status")
        if status == "acquired_validated":
            pdf_path = require_absolute_regular_file(
                record.get("pdf_path"), f"repair PDF {item_key}"
            )
            evidence = file_evidence(pdf_path)
            expected_hash = "sha256:" + require_string(
                record.get("sha256"), f"repair PDF hash {item_key}"
            ).removeprefix("sha256:")
            if evidence["sha256"] != expected_hash:
                raise ContractError(f"repair PDF SHA-256 mismatch: {item_key}")
            if record.get("size_bytes") is not None and record["size_bytes"] != evidence["size_bytes"]:
                raise ContractError(f"repair PDF size mismatch: {item_key}")
            if evidence["magic"] != "%PDF-":
                raise ContractError(f"repair source is not a PDF: {item_key}")
            entries.append(
                {
                    "action": "attach_missing_pdf",
                    **common,
                    "source_pdf": evidence,
                    "source_provenance": {
                        "source_url": require_string(
                            record.get("source_url"), f"source URL {item_key}"
                        ),
                        "access_basis": require_string(
                            record.get("access_basis"), f"access basis {item_key}"
                        ),
                        "result_path": require_string(
                            record.get("result_path"), f"result path {item_key}"
                        ),
                    },
                }
            )
        elif status == "metadata_only":
            entries.append(
                {
                    "action": "metadata_only_skip",
                    **common,
                    "reason": require_string(
                        record.get("reason"), f"metadata-only reason {item_key}"
                    ),
                }
            )
        else:
            raise ContractError(f"unsupported repair status for {item_key}: {status!r}")

    attach_count = sum(entry["action"] == "attach_missing_pdf" for entry in entries)
    skip_count = len(entries) - attach_count
    payload = {
        "schema": SCHEMA,
        "generated_at": require_string(repair.get("generated_at"), "repair generated_at"),
        "target": {
            "group_id": require_int(group_id, "group_id", minimum=1),
            "library_id": require_int(library_id, "library_id", minimum=1),
            "library_name": require_string(library_name, "library_name"),
            "local_collection_id": require_int(
                local_collection_id, "local_collection_id", minimum=1
            ),
            "collection_key": collection_key,
            "collection_path": target_path,
            "require_library_editable": True,
            "require_files_editable": True,
        },
        "baseline": {
            "schema": BASELINE_SCHEMA,
            "path": str(baseline_path),
            "file_sha256": sha256_bytes(baseline_raw),
            "state_sha256": require_string(
                baseline.get("state_sha256"), "baseline state_sha256"
            ),
            "identity_sha256": require_string(
                baseline.get("identity_sha256"), "baseline identity_sha256"
            ),
            "retrieved_at": require_string(baseline.get("retrieved_at"), "baseline retrieved_at"),
            "collection_version": require_int(
                collection.get("collection_version"), "baseline collection_version"
            ),
        },
        "repair_source": {
            "schema": REPAIR_SCHEMA,
            "path": str(repair_path),
            "file_sha256": sha256_bytes(repair_raw),
            "generated_at": require_string(repair.get("generated_at"), "repair generated_at"),
        },
        "entries": entries,
        "summary": {
            "attach_missing_pdf": attach_count,
            "metadata_only_skip": skip_count,
            "total": len(entries),
        },
    }
    return seal_manifest(payload)


def validate_manifest_payload(payload: dict[str, Any], *, verify_files: bool = True) -> dict[str, int]:
    expect_exact_keys(
        payload,
        {
            "schema",
            "generated_at",
            "target",
            "baseline",
            "repair_source",
            "entries",
            "summary",
            "manifest_digest_sha256",
        },
        "manifest",
    )
    if payload["schema"] != SCHEMA:
        raise ContractError("unsupported attachment repair manifest schema")
    require_string(payload["generated_at"], "manifest generated_at")
    supplied_digest = require_string(payload["manifest_digest_sha256"], "manifest digest")
    unsealed = copy.deepcopy(payload)
    unsealed.pop("manifest_digest_sha256")
    if supplied_digest != sha256_bytes(canonical_json_bytes(unsealed)):
        raise ContractError("manifest digest mismatch")

    target = expect_exact_keys(
        payload["target"],
        {
            "group_id",
            "library_id",
            "library_name",
            "local_collection_id",
            "collection_key",
            "collection_path",
            "require_library_editable",
            "require_files_editable",
        },
        "target",
    )
    for field in ("group_id", "library_id", "local_collection_id"):
        require_int(target[field], f"target.{field}", minimum=1)
    require_string(target["library_name"], "target.library_name")
    require_string(target["collection_key"], "target.collection_key")
    if target["require_library_editable"] is not True or target["require_files_editable"] is not True:
        raise ContractError("attachment repair requires editable library and files")
    if not isinstance(target["collection_path"], list) or not target["collection_path"]:
        raise ContractError("target.collection_path must be nonempty")
    for index, part in enumerate(target["collection_path"]):
        expect_exact_keys(part, {"key", "name"}, f"target.collection_path[{index}]")
        require_string(part["key"], "target collection path key")
        require_string(part["name"], "target collection path name")
    if target["collection_path"][-1]["key"] != target["collection_key"]:
        raise ContractError("target collection path leaf mismatch")

    baseline_ref = expect_exact_keys(
        payload["baseline"],
        {
            "schema",
            "path",
            "file_sha256",
            "state_sha256",
            "identity_sha256",
            "retrieved_at",
            "collection_version",
        },
        "baseline",
    )
    repair_ref = expect_exact_keys(
        payload["repair_source"],
        {"schema", "path", "file_sha256", "generated_at"},
        "repair_source",
    )
    if baseline_ref["schema"] != BASELINE_SCHEMA or repair_ref["schema"] != REPAIR_SCHEMA:
        raise ContractError("bound input schema mismatch")
    baseline_path = require_absolute_regular_file(baseline_ref["path"], "baseline.path")
    repair_path = require_absolute_regular_file(repair_ref["path"], "repair_source.path")
    baseline_raw, baseline = read_json(baseline_path)
    repair_raw, repair = read_json(repair_path)
    if verify_files:
        if sha256_bytes(baseline_raw) != baseline_ref["file_sha256"]:
            raise ContractError("bound baseline bytes changed")
        if sha256_bytes(repair_raw) != repair_ref["file_sha256"]:
            raise ContractError("bound repair source bytes changed")
    if baseline.get("schema") != BASELINE_SCHEMA or repair.get("schema") != REPAIR_SCHEMA:
        raise ContractError("live bound input schema mismatch")
    for field in ("state_sha256", "identity_sha256", "retrieved_at"):
        if baseline.get(field) != baseline_ref[field]:
            raise ContractError(f"baseline {field} drift")
    if repair.get("generated_at") != repair_ref["generated_at"]:
        raise ContractError("repair generated_at drift")
    collection = baseline.get("collection")
    if not isinstance(collection, dict):
        raise ContractError("baseline collection missing")
    expected_path = [
        {"key": part.get("key"), "name": part.get("name")}
        for part in collection.get("collection_path", [])
        if isinstance(part, dict)
    ]
    if (
        collection.get("group_id") != target["group_id"]
        or collection.get("collection_key") != target["collection_key"]
        or expected_path != target["collection_path"]
        or collection.get("collection_version") != baseline_ref["collection_version"]
    ):
        raise ContractError("manifest target does not match bound baseline")

    parents = _unique_map(baseline.get("parents"), "key", "baseline parents")
    records = _unique_map(repair.get("records"), "item_key", "repair records")
    entries = payload["entries"]
    if not isinstance(entries, list):
        raise ContractError("entries must be a list")
    entry_map: dict[str, dict[str, Any]] = {}
    attach_count = 0
    skip_count = 0
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict):
            raise ContractError(f"entries[{index}] must be an object")
        action = entry.get("action")
        if action == "attach_missing_pdf":
            expect_exact_keys(
                entry,
                {"action", "parent", "expected_attachments", "source_pdf", "source_provenance"},
                f"entries[{index}]",
            )
            attach_count += 1
        elif action == "metadata_only_skip":
            expect_exact_keys(
                entry,
                {"action", "parent", "expected_attachments", "reason"},
                f"entries[{index}]",
            )
            skip_count += 1
        else:
            raise ContractError(f"entries[{index}] has unsupported action")
        parent_ref = expect_exact_keys(
            entry["parent"],
            {"key", "version", "item_type", "doi", "title", "collection_key"},
            f"entries[{index}].parent",
        )
        key = require_string(parent_ref["key"], "entry parent key")
        if key in entry_map:
            raise ContractError(f"duplicate manifest parent: {key}")
        entry_map[key] = entry
        baseline_parent = parents.get(key)
        record = records.get(key)
        if baseline_parent is None or record is None:
            raise ContractError(f"manifest parent is absent from bound inputs: {key}")
        if parent_ref != parent_projection(baseline_parent, target["collection_key"]):
            raise ContractError(f"parent identity/version drift: {key}")
        expected_attachments = entry["expected_attachments"]
        if expected_attachments != normalized_attachments(baseline_parent):
            raise ContractError(f"baseline attachment inventory drift: {key}")
        for attachment_index, attachment in enumerate(expected_attachments):
            expect_exact_keys(
                attachment,
                {"key", "version", "content_type", "link_mode"},
                f"entries[{index}].expected_attachments[{attachment_index}]",
            )
        if action == "attach_missing_pdf":
            if record.get("status") != "acquired_validated":
                raise ContractError(f"repair action/status mismatch: {key}")
            source_pdf = expect_exact_keys(
                entry["source_pdf"],
                {"path", "size_bytes", "sha256", "magic", "content_type"},
                f"entries[{index}].source_pdf",
            )
            source_path = require_absolute_regular_file(source_pdf["path"], "source PDF path")
            require_int(source_pdf["size_bytes"], "source PDF size", minimum=5)
            if source_pdf["content_type"] != "application/pdf" or source_pdf["magic"] != "%PDF-":
                raise ContractError(f"invalid PDF binding: {key}")
            provenance = expect_exact_keys(
                entry["source_provenance"],
                {"source_url", "access_basis", "result_path"},
                f"entries[{index}].source_provenance",
            )
            for field in provenance:
                require_string(provenance[field], f"source provenance {field}")
            expected_hash = "sha256:" + require_string(record.get("sha256"), "repair hash").removeprefix("sha256:")
            if (
                str(source_path) != record.get("pdf_path")
                or source_pdf["sha256"] != expected_hash
                or source_pdf["size_bytes"] != source_path.stat().st_size
                or provenance["source_url"] != record.get("source_url")
                or provenance["access_basis"] != record.get("access_basis")
                or provenance["result_path"] != record.get("result_path")
            ):
                raise ContractError(f"repair PDF/provenance binding drift: {key}")
            if verify_files:
                observed = file_evidence(source_path)
                if observed != source_pdf:
                    raise ContractError(f"source PDF bytes changed: {key}")
        else:
            if record.get("status") != "metadata_only" or entry["reason"] != record.get("reason"):
                raise ContractError(f"metadata-only binding drift: {key}")
            require_string(entry["reason"], "metadata-only reason")

    if set(entry_map) != set(records):
        raise ContractError("manifest entries do not exactly cover repair records")
    summary = expect_exact_keys(
        payload["summary"],
        {"attach_missing_pdf", "metadata_only_skip", "total"},
        "summary",
    )
    expected_summary = {
        "attach_missing_pdf": attach_count,
        "metadata_only_skip": skip_count,
        "total": len(entries),
    }
    if summary != expected_summary:
        raise ContractError("summary counts do not match entries")
    return expected_summary


def load_and_validate_manifest(path: Path) -> tuple[bytes, dict[str, Any], dict[str, int]]:
    path = require_absolute_regular_file(str(path), "manifest path")
    raw, payload = read_json(path)
    summary = validate_manifest_payload(payload, verify_files=True)
    return raw, payload, summary


def write_json_exclusive(path: Path, payload: dict[str, Any]) -> None:
    path = path.expanduser()
    if not path.is_absolute():
        raise ContractError("output path must be absolute")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8", newline="\n") as handle:
        json.dump(payload, handle, ensure_ascii=False, sort_keys=True, indent=2)
        handle.write("\n")


def render_runner(
    manifest_path: Path,
    *,
    apply: bool = False,
    report_path: Path | None = None,
) -> str:
    manifest_path = require_absolute_regular_file(str(manifest_path), "manifest path")
    raw, payload, summary = load_and_validate_manifest(manifest_path)
    if apply and len(payload["entries"]) != 1:
        raise ContractError("Desktop fallback apply requires exactly one parent entry")
    if report_path is None:
        mode = "apply" if apply else "preview"
        report_path = manifest_path.parent / f"zotero_attachment_repair_{mode}_report.json"
    report_path = report_path.expanduser()
    if not report_path.is_absolute():
        raise ContractError("report path must be absolute")
    report_path = report_path.resolve()
    if not report_path.parent.is_dir():
        raise ContractError("report directory does not exist")
    protected = {
        manifest_path,
        Path(payload["baseline"]["path"]).resolve(),
        Path(payload["repair_source"]["path"]).resolve(),
        TEMPLATE_PATH.resolve(),
        CORE_PATH.resolve(),
    }
    protected.update(
        Path(entry["source_pdf"]["path"]).resolve()
        for entry in payload["entries"]
        if entry["action"] == "attach_missing_pdf"
    )
    if report_path in protected:
        raise ContractError("report path aliases a bound input")
    if report_path.exists():
        raise ContractError("report path already exists; evidence is append-only")
    template = TEMPLATE_PATH.read_text(encoding="utf-8")
    core = CORE_PATH.read_text(encoding="utf-8")
    if template.count(CONFIG_SENTINEL) != 1:
        raise ContractError("attachment repair template sentinel is missing or duplicated")
    config = {
        "apply": bool(apply),
        "expectedAttachCount": summary["attach_missing_pdf"],
        "expectedMetadataSkipCount": summary["metadata_only_skip"],
        "manifestDigestSHA256": payload["manifest_digest_sha256"],
        "manifestPath": str(manifest_path),
        "manifestSHA256": sha256_bytes(raw),
        "reportPath": str(report_path),
    }
    rendered_config = "const CONFIG = " + json.dumps(
        config, ensure_ascii=True, sort_keys=True, separators=(",", ":")
    ) + ";"
    return template.replace(CONFIG_SENTINEL, rendered_config + "\n" + core.rstrip())


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    generate = subparsers.add_parser("generate", help="generate a closed repair manifest")
    generate.add_argument("baseline", type=Path)
    generate.add_argument("repair", type=Path)
    generate.add_argument("output", type=Path)
    generate.add_argument("--group-id", type=int, required=True)
    generate.add_argument("--library-id", type=int, required=True)
    generate.add_argument("--library-name", required=True)
    generate.add_argument("--local-collection-id", type=int, required=True)
    generate.add_argument("--collection-key", required=True)
    generate.add_argument("--collection-path", required=True)
    validate = subparsers.add_parser("validate", help="validate all manifest bindings")
    validate.add_argument("manifest", type=Path)
    render = subparsers.add_parser("render", help="render a Zotero Desktop runner")
    render.add_argument("manifest", type=Path)
    render.add_argument("--apply", action="store_true")
    render.add_argument("--report", type=Path)
    render.add_argument("--output", type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        if args.command == "generate":
            payload = build_manifest(
                args.baseline,
                args.repair,
                group_id=args.group_id,
                library_id=args.library_id,
                library_name=args.library_name,
                local_collection_id=args.local_collection_id,
                collection_key=args.collection_key,
                collection_path=args.collection_path,
            )
            write_json_exclusive(args.output, payload)
            print(json.dumps({"status": "generated", "output": str(args.output), **payload["summary"]}, sort_keys=True))
            return 0
        if args.command == "validate":
            _, payload, summary = load_and_validate_manifest(args.manifest)
            print(json.dumps({"status": "valid", "schema": payload["schema"], **summary}, sort_keys=True))
            return 0
        rendered = render_runner(args.manifest, apply=args.apply, report_path=args.report)
        if args.output is None:
            sys.stdout.write(rendered)
        else:
            output = args.output.expanduser()
            if not output.is_absolute():
                raise ContractError("runner output path must be absolute")
            output.parent.mkdir(parents=True, exist_ok=True)
            with output.open("x", encoding="utf-8", newline="\n") as handle:
                handle.write(rendered)
                if not rendered.endswith("\n"):
                    handle.write("\n")
            print(json.dumps({"status": "rendered", "mode": "apply" if args.apply else "preview", "output": str(output)}, sort_keys=True))
        return 0
    except (ContractError, OSError, UnicodeError, json.JSONDecodeError) as error:
        print(json.dumps({"status": "failed", "error": str(error)}, sort_keys=True), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
