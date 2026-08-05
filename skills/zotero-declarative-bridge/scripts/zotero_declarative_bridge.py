#!/usr/bin/env python3
"""Compile and call the constrained Zotero Desktop declarative bridge."""

from __future__ import annotations

import argparse
import copy
import datetime as dt
import hashlib
import hmac
import json
import os
import re
import stat
import sys
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path
from typing import Any


MANIFEST_SCHEMA = "ZoteroDeclarativeTransaction/v1"
CAPABILITY_SCHEMA = "ZoteroDeclarativeBridgeCapability/v1"
REQUEST_SCHEMA = "ZoteroDeclarativeBridgeRequest/v1"
RESPONSE_SCHEMA = "ZoteroDeclarativeBridgeResponse/v1"
ENDPOINT_PATH = "/deep-research/transaction/v1"
KEY_RE = re.compile(r"^[A-Z0-9]{8}$")
HEX_RE = re.compile(r"^[0-9a-f]{64}$")
SHA_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
TX_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
BASE_URL = "http://127.0.0.1:23119"
OP_ORDER = {
    "ensure_collection_membership": 0,
    "ensure_parent_short_title": 1,
    "ensure_child_note": 2,
    "ensure_pdf_attachment": 3,
}
RESPONSE_KEYS = {"schema", "status", "action", "request_id", "result", "error"}
ERROR_KEYS = {
    "code",
    "message",
    "write_attempted",
    "commit_state",
    "inspection",
    "execution_profile",
    "created_attachment_keys",
}
COMMIT_STATES = {
    "not_started",
    "rolled_back",
    "committed",
    "committed_unverified",
    "partial_commit",
    "unknown",
}


class BridgeError(RuntimeError):
    pass


class BridgeResponseError(BridgeError):
    """A validated structured error response returned by the bridge."""

    def __init__(self, response: dict[str, Any]) -> None:
        self.response = response
        self.error_code = response["error"]["code"]
        self.commit_state = response["error"]["commit_state"]
        super().__init__("bridge returned a structured error response")


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def sha256_value(value: Any) -> str:
    return "sha256:" + hashlib.sha256(canonical_bytes(value)).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return "sha256:" + digest.hexdigest()


def exact_keys(value: Any, expected: set[str], label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise BridgeError(f"{label} must be an object")
    actual = set(value)
    if actual != expected:
        raise BridgeError(
            f"{label} keys differ: missing={sorted(expected-actual)} "
            f"unknown={sorted(actual-expected)}"
        )
    return value


def text(value: Any, label: str, *, nonempty: bool = True, limit: int = 1_048_576) -> str:
    if not isinstance(value, str) or (nonempty and not value):
        raise BridgeError(f"{label} must be a{' non-empty' if nonempty else ''} string")
    if len(value.encode("utf-8")) > limit:
        raise BridgeError(f"{label} is too large")
    return value


def positive_int(value: Any, label: str, *, maximum: int | None = None) -> int:
    if type(value) is not int or value <= 0 or (maximum is not None and value > maximum):
        raise BridgeError(f"{label} must be a positive integer")
    return value


def item_key(value: Any, label: str) -> str:
    value = text(value, label, limit=8)
    if not KEY_RE.fullmatch(value):
        raise BridgeError(f"{label} must be an 8-character Zotero key")
    return value


def sha(value: Any, label: str) -> str:
    value = text(value, label, limit=71)
    if not SHA_RE.fullmatch(value):
        raise BridgeError(f"{label} must be sha256:<64 lowercase hex>")
    return value


def normalize_doi(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    return re.sub(r"^https?://(?:dx\.)?doi\.org/", "", value.strip().lower())


def short_title(value: Any, label: str, *, nonempty: bool) -> str:
    value = text(value, label, nonempty=nonempty, limit=4096)
    if re.search(r"[\x00-\x1f\x7f]", value):
        raise BridgeError(f"{label} contains control characters")
    return value


def identity_for_parent(parent: dict[str, Any], library_id: int) -> dict[str, Any]:
    return {
        "doi": normalize_doi(parent.get("doi", parent.get("DOI", ""))),
        "item_type": str(parent.get("item_type", parent.get("itemType", ""))),
        "key": str(parent.get("key", "")),
        "library_id": library_id,
        "title": str(parent.get("title", "")),
    }


def validate_target(value: Any) -> None:
    target = exact_keys(
        value,
        {
            "library_id",
            "library_type",
            "library_type_id",
            "library_name",
            "collection_id",
            "collection_key",
            "collection_path",
            "require_editable",
            "require_files_editable",
        },
        "target",
    )
    positive_int(target["library_id"], "target.library_id")
    if target["library_type"] not in {"group", "user"}:
        raise BridgeError("target.library_type must be group or user")
    positive_int(target["library_type_id"], "target.library_type_id")
    text(target["library_name"], "target.library_name", limit=256)
    positive_int(target["collection_id"], "target.collection_id")
    item_key(target["collection_key"], "target.collection_key")
    if target["require_editable"] is not True:
        raise BridgeError("target.require_editable must be true")
    if type(target["require_files_editable"]) is not bool:
        raise BridgeError("target.require_files_editable must be boolean")
    path = target["collection_path"]
    if not isinstance(path, list) or not path or len(path) > 32:
        raise BridgeError("target.collection_path must be a non-empty bounded array")
    keys: list[str] = []
    for index, part in enumerate(path):
        part = exact_keys(part, {"key", "name"}, f"target.collection_path[{index}]")
        keys.append(item_key(part["key"], f"target.collection_path[{index}].key"))
        text(part["name"], f"target.collection_path[{index}].name", limit=512)
    if len(keys) != len(set(keys)):
        raise BridgeError("target.collection_path contains duplicate keys")
    if keys[-1] != target["collection_key"]:
        raise BridgeError("target.collection_path does not end at collection_key")


def validate_parent(value: Any, target: dict[str, Any]) -> None:
    parent = exact_keys(
        value,
        {
            "key",
            "version",
            "item_type",
            "title",
            "doi",
            "identity_sha256",
            "expected_target_membership",
        },
        "parent",
    )
    item_key(parent["key"], "parent.key")
    positive_int(parent["version"], "parent.version")
    text(parent["item_type"], "parent.item_type", limit=128)
    text(parent["title"], "parent.title", limit=16_384)
    text(parent["doi"], "parent.doi", nonempty=False, limit=2048)
    sha(parent["identity_sha256"], "parent.identity_sha256")
    if type(parent["expected_target_membership"]) is not bool:
        raise BridgeError("parent.expected_target_membership must be boolean")
    expected = identity_for_parent(parent, target["library_id"])
    if sha256_value(expected) != parent["identity_sha256"]:
        raise BridgeError(f"parent {parent['key']} identity_sha256 is inconsistent")


def validate_operation(
    value: Any,
    parent: dict[str, Any],
    target: dict[str, Any],
    label: str,
) -> str:
    if not isinstance(value, dict) or "type" not in value:
        raise BridgeError(f"{label} must contain type")
    operation_type = value["type"]
    if operation_type == "ensure_collection_membership":
        exact_keys(value, {"type", "expected_present"}, label)
        if value["expected_present"] is not False:
            raise BridgeError(f"{label}.expected_present must be false")
        if parent["expected_target_membership"] is not False:
            raise BridgeError(f"{label} disagrees with parent membership baseline")
    elif operation_type == "ensure_parent_short_title":
        exact_keys(
            value,
            {
                "type",
                "library_id",
                "parent_key",
                "expected_parent_version",
                "expected_old_value",
                "new_short_title",
            },
            label,
        )
        positive_int(value["library_id"], f"{label}.library_id")
        item_key(value["parent_key"], f"{label}.parent_key")
        positive_int(value["expected_parent_version"], f"{label}.expected_parent_version")
        short_title(value["expected_old_value"], f"{label}.expected_old_value", nonempty=False)
        new_value = short_title(value["new_short_title"], f"{label}.new_short_title", nonempty=True)
        if new_value != new_value.strip():
            raise BridgeError(f"{label}.new_short_title must be trimmed")
        if value["library_id"] != target["library_id"]:
            raise BridgeError(f"{label}.library_id disagrees with target")
        if value["parent_key"] != parent["key"]:
            raise BridgeError(f"{label}.parent_key disagrees with parent")
        if value["expected_parent_version"] != parent["version"]:
            raise BridgeError(f"{label}.expected_parent_version disagrees with parent")
    elif operation_type == "ensure_child_note":
        exact_keys(
            value,
            {
                "type",
                "note_key",
                "expected_note_version",
                "expected_old_sha256",
                "expected_child_note_keys",
                "new_html",
                "new_sha256",
            },
            label,
        )
        new_html = text(value["new_html"], f"{label}.new_html")
        if new_html != new_html.strip():
            raise BridgeError(f"{label}.new_html must already match Zotero storage trimming")
        if re.search(r"<script\b|javascript:|\son[a-z]+\s*=", new_html, re.I):
            raise BridgeError(f"{label}.new_html contains executable markup")
        if not re.search(r"<h1(?:\s[^>]*)?>\s*[^<\s]", new_html, re.I):
            raise BridgeError(f"{label}.new_html requires a non-empty h1")
        sha(value["new_sha256"], f"{label}.new_sha256")
        actual_new = "sha256:" + hashlib.sha256(new_html.encode("utf-8")).hexdigest()
        if actual_new != value["new_sha256"]:
            raise BridgeError(f"{label}.new_sha256 is inconsistent")
        keys = value["expected_child_note_keys"]
        if not isinstance(keys, list) or keys != sorted(keys) or len(keys) != len(set(keys)):
            raise BridgeError(f"{label}.expected_child_note_keys must be sorted and unique")
        for index, key in enumerate(keys):
            item_key(key, f"{label}.expected_child_note_keys[{index}]")
        if value["note_key"] is None:
            if value["expected_note_version"] is not None or value["expected_old_sha256"] is not None:
                raise BridgeError(f"{label} create fields are inconsistent")
            if keys:
                raise BridgeError(f"{label} creation requires an empty note inventory")
        else:
            key = item_key(value["note_key"], f"{label}.note_key")
            positive_int(value["expected_note_version"], f"{label}.expected_note_version")
            sha(value["expected_old_sha256"], f"{label}.expected_old_sha256")
            if keys != [key]:
                raise BridgeError(f"{label} update requires the exact single note inventory")
    elif operation_type == "ensure_pdf_attachment":
        exact_keys(
            value,
            {
                "type",
                "source_path",
                "source_size_bytes",
                "source_sha256",
                "source_magic",
                "expected_attachments",
            },
            label,
        )
        source_path = Path(text(value["source_path"], f"{label}.source_path", limit=16_384))
        if not source_path.is_absolute():
            raise BridgeError(f"{label}.source_path must be absolute")
        positive_int(value["source_size_bytes"], f"{label}.source_size_bytes", maximum=268_435_456)
        sha(value["source_sha256"], f"{label}.source_sha256")
        if value["source_magic"] != "%PDF-":
            raise BridgeError(f"{label}.source_magic must be %PDF-")
        attachments = value["expected_attachments"]
        if not isinstance(attachments, list) or len(attachments) > 100:
            raise BridgeError(f"{label}.expected_attachments must be a bounded array")
        keys: list[str] = []
        for index, attachment in enumerate(attachments):
            attachment = exact_keys(
                attachment,
                {"key", "version", "content_type", "link_mode"},
                f"{label}.expected_attachments[{index}]",
            )
            keys.append(item_key(attachment["key"], f"{label}.expected_attachments[{index}].key"))
            positive_int(attachment["version"], f"{label}.expected_attachments[{index}].version")
            text(attachment["content_type"], f"{label}.expected_attachments[{index}].content_type", nonempty=False, limit=256)
            text(attachment["link_mode"], f"{label}.expected_attachments[{index}].link_mode", limit=128)
        if keys != sorted(keys) or len(keys) != len(set(keys)):
            raise BridgeError(f"{label}.expected_attachments must be key-sorted and unique")
    else:
        raise BridgeError(f"{label}.type is unsupported")
    return operation_type


def validate_manifest(manifest: Any, *, require_digest: bool = True) -> dict[str, Any]:
    expected = {"schema", "transaction_id", "generated_at", "target", "entries"}
    if require_digest:
        expected.add("manifest_sha256")
    manifest = exact_keys(manifest, expected, "manifest")
    if manifest["schema"] != MANIFEST_SCHEMA:
        raise BridgeError("manifest schema mismatch")
    if not isinstance(manifest["transaction_id"], str) or not TX_RE.fullmatch(manifest["transaction_id"]):
        raise BridgeError("transaction_id is invalid")
    text(manifest["generated_at"], "generated_at", limit=64)
    validate_target(manifest["target"])
    entries = manifest["entries"]
    if not isinstance(entries, list) or not entries or len(entries) > 100:
        raise BridgeError("entries must be a non-empty bounded array")
    parent_keys: list[str] = []
    needs_files = False
    operation_types: list[str] = []
    for index, entry in enumerate(entries):
        entry = exact_keys(entry, {"parent", "operations"}, f"entries[{index}]")
        validate_parent(entry["parent"], manifest["target"])
        parent_keys.append(entry["parent"]["key"])
        operations = entry["operations"]
        if not isinstance(operations, list) or not operations or len(operations) > 4:
            raise BridgeError(f"entries[{index}].operations must be non-empty and bounded")
        types = [
            validate_operation(
                operation,
                entry["parent"],
                manifest["target"],
                f"entries[{index}].operations[{op_index}]",
            )
            for op_index, operation in enumerate(operations)
        ]
        if len(types) != len(set(types)) or types != sorted(types, key=OP_ORDER.get):
            raise BridgeError(f"entries[{index}].operations must be unique and canonically ordered")
        operation_types.extend(types)
        needs_files = needs_files or "ensure_pdf_attachment" in types
    if parent_keys != sorted(parent_keys) or len(parent_keys) != len(set(parent_keys)):
        raise BridgeError("entries must be parent-key-sorted and unique")
    if needs_files and manifest["target"]["require_files_editable"] is not True:
        raise BridgeError("PDF operations require target.require_files_editable=true")
    if needs_files and any(value != "ensure_pdf_attachment" for value in operation_types):
        raise BridgeError("PDF and database operations cannot share one transaction manifest")
    if require_digest:
        sha(manifest["manifest_sha256"], "manifest.manifest_sha256")
        unsigned = {key: value for key, value in manifest.items() if key != "manifest_sha256"}
        if sha256_value(unsigned) != manifest["manifest_sha256"]:
            raise BridgeError("manifest_sha256 is inconsistent")
    return manifest


def seal_manifest(unsigned: dict[str, Any]) -> dict[str, Any]:
    validate_manifest(unsigned, require_digest=False)
    sealed = copy.deepcopy(unsigned)
    sealed["manifest_sha256"] = sha256_value(unsigned)
    return validate_manifest(sealed)


def read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise BridgeError(f"cannot read JSON {path}: {exc}") from exc


def write_private_json(path: Path, value: Any) -> None:
    path = path.expanduser().resolve()
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    data = json.dumps(value, ensure_ascii=False, indent=2) + "\n"
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except OSError as exc:
        raise BridgeError(f"refusing to overwrite {path}: {exc}") from exc
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write(data)


def validate_bridge_response(value: Any, action: str, request_id: str) -> dict[str, Any]:
    response = exact_keys(value, RESPONSE_KEYS, "bridge response")
    if response["schema"] != RESPONSE_SCHEMA:
        raise BridgeError("bridge response schema mismatch")
    error = response["error"]
    if error is None:
        if response["action"] != action or response["request_id"] != request_id:
            raise BridgeError("bridge response request binding mismatch")
        if response["status"] == "failed" or not isinstance(response["result"], dict):
            raise BridgeError("bridge success response shape mismatch")
        text(response["status"], "bridge response status", limit=128)
        return response
    if response["status"] != "failed" or response["result"] is not None:
        raise BridgeError("bridge error response shape mismatch")
    if response["action"] is not None and response["action"] != action:
        raise BridgeError("bridge error response action mismatch")
    if response["request_id"] is not None and response["request_id"] != request_id:
        raise BridgeError("bridge error response request mismatch")
    error = exact_keys(error, ERROR_KEYS, "bridge response error")
    code = text(error["code"], "bridge response error code", limit=128)
    if not re.fullmatch(r"[a-z][a-z0-9_]{0,127}", code):
        raise BridgeError("bridge response error code is invalid")
    text(error["message"], "bridge response error message", limit=4096)
    if not isinstance(error["write_attempted"], bool):
        raise BridgeError("bridge response write_attempted is invalid")
    if error["commit_state"] not in COMMIT_STATES:
        raise BridgeError("bridge response commit_state is invalid")
    if error["inspection"] is not None and not isinstance(error["inspection"], dict):
        raise BridgeError("bridge response inspection is invalid")
    if error["execution_profile"] not in {None, "none", "db_atomic", "single_attachment_import"}:
        raise BridgeError("bridge response execution_profile is invalid")
    if not isinstance(error["created_attachment_keys"], list):
        raise BridgeError("bridge response created_attachment_keys is invalid")
    for index, key_value in enumerate(error["created_attachment_keys"]):
        item_key(key_value, f"bridge response created_attachment_keys[{index}]")
    return response


def api_get(path: str, base_url: str = BASE_URL) -> Any:
    parsed = urllib.parse.urlsplit(base_url)
    if parsed.scheme != "http" or parsed.hostname != "127.0.0.1" or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise BridgeError("base URL must be a credential-free literal 127.0.0.1 HTTP origin")
    request = urllib.request.Request(
        base_url.rstrip("/") + path,
        headers={"Zotero-API-Version": "3", "User-Agent": "deep-research-zotero-bridge/0.1"},
    )
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(request, timeout=10.0) as response:
            return json.loads(response.read().decode("utf-8"))
    except (OSError, ValueError, json.JSONDecodeError, urllib.error.HTTPError) as exc:
        raise BridgeError(f"Local API GET failed for {path}: {exc}") from exc


def collection_contract(group_id: int, collection_key: str, base_url: str = BASE_URL) -> tuple[list[dict[str, str]], dict[str, Any]]:
    path: list[dict[str, str]] = []
    seen: set[str] = set()
    current: str | bool = collection_key
    leaf: dict[str, Any] | None = None
    while current:
        key = item_key(str(current), "collection key")
        if key in seen:
            raise BridgeError("collection ancestry contains a cycle")
        seen.add(key)
        record = api_get(f"/api/groups/{group_id}/collections/{key}?format=json", base_url)
        data = record.get("data") if isinstance(record, dict) else None
        if not isinstance(data, dict) or data.get("key") != key or not data.get("name"):
            raise BridgeError(f"collection record is malformed for {key}")
        if leaf is None:
            leaf = record
        path.insert(0, {"key": key, "name": str(data["name"])})
        current = data.get("parentCollection") or False
    if leaf is None:
        raise BridgeError("collection contract is empty")
    return path, leaf


def live_parent(group_id: int, parent_key: str, base_url: str = BASE_URL) -> dict[str, Any]:
    record = api_get(f"/api/groups/{group_id}/items/{item_key(parent_key, 'parent key')}?format=json", base_url)
    if not isinstance(record, dict) or not isinstance(record.get("data"), dict):
        raise BridgeError(f"parent record is malformed: {parent_key}")
    return record


def target_from_parts(
    *,
    group_id: int,
    library_id: int,
    library_name: str,
    collection_id: int,
    collection_key: str,
    collection_path: list[dict[str, str]],
    files: bool,
) -> dict[str, Any]:
    return {
        "library_id": library_id,
        "library_type": "group",
        "library_type_id": group_id,
        "library_name": library_name,
        "collection_id": collection_id,
        "collection_key": collection_key,
        "collection_path": collection_path,
        "require_editable": True,
        "require_files_editable": files,
    }


def parent_from_data(data: dict[str, Any], library_id: int, expected_membership: bool) -> dict[str, Any]:
    identity = identity_for_parent(data, library_id)
    parent = {
        "key": item_key(str(data.get("key", "")), "parent.key"),
        "version": positive_int(data.get("version"), "parent.version"),
        "item_type": text(str(data.get("itemType", "")), "parent.item_type", limit=128),
        "title": text(str(data.get("title", "")), "parent.title", limit=16_384),
        "doi": normalize_doi(data.get("DOI", "")),
        "identity_sha256": sha256_value(identity),
        "expected_target_membership": expected_membership,
    }
    return parent


def now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def compile_attachment_repair(
    source: Path,
    transaction_id: str,
    parent_key: str | None = None,
) -> dict[str, Any]:
    repair = read_json(source)
    if not isinstance(repair, dict) or repair.get("schema") != "ZoteroAttachmentRepairManifest/v1":
        raise BridgeError("attachment repair schema mismatch")
    declared = repair.get("manifest_digest_sha256")
    unsigned_repair = {
        key: value for key, value in repair.items() if key != "manifest_digest_sha256"
    }
    repair_bytes = json.dumps(
        unsigned_repair,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    expected_digest = "sha256:" + hashlib.sha256(repair_bytes).hexdigest()
    if (
        not isinstance(declared, str)
        or not SHA_RE.fullmatch(declared)
        or expected_digest != declared
    ):
        raise BridgeError("attachment repair manifest digest mismatch")
    source_target = repair.get("target")
    if not isinstance(source_target, dict):
        raise BridgeError("attachment repair target is missing")
    target = target_from_parts(
        group_id=positive_int(source_target.get("group_id"), "target.group_id"),
        library_id=positive_int(source_target.get("library_id"), "target.library_id"),
        library_name=text(source_target.get("library_name"), "target.library_name", limit=256),
        collection_id=positive_int(source_target.get("local_collection_id"), "target.local_collection_id"),
        collection_key=item_key(source_target.get("collection_key"), "target.collection_key"),
        collection_path=source_target.get("collection_path"),
        files=True,
    )
    entries: list[dict[str, Any]] = []
    selected_parent_key = item_key(parent_key, "parent_key") if parent_key else None
    for row in repair.get("entries", []):
        if not isinstance(row, dict) or row.get("action") != "attach_missing_pdf":
            continue
        raw_parent = row.get("parent")
        source_pdf = row.get("source_pdf")
        if not isinstance(raw_parent, dict) or not isinstance(source_pdf, dict):
            raise BridgeError("attachment repair entry is malformed")
        if selected_parent_key and raw_parent.get("key") != selected_parent_key:
            continue
        parent = {
            "key": raw_parent.get("key"),
            "version": raw_parent.get("version"),
            "item_type": raw_parent.get("item_type"),
            "title": raw_parent.get("title"),
            "doi": normalize_doi(raw_parent.get("doi", "")),
            "identity_sha256": sha256_value(identity_for_parent(raw_parent, target["library_id"])),
            "expected_target_membership": True,
        }
        attachments = sorted(row.get("expected_attachments", []), key=lambda item: item.get("key", ""))
        operation = {
            "type": "ensure_pdf_attachment",
            "source_path": str(source_pdf.get("path", "")),
            "source_size_bytes": source_pdf.get("size_bytes"),
            "source_sha256": source_pdf.get("sha256"),
            "source_magic": source_pdf.get("magic"),
            "expected_attachments": attachments,
        }
        entries.append({"parent": parent, "operations": [operation]})
    if not entries:
        if selected_parent_key:
            raise BridgeError("attachment repair parent-key selector did not match exactly one entry")
        raise BridgeError("attachment repair has no attach_missing_pdf operations")
    if len(entries) != 1:
        if selected_parent_key:
            raise BridgeError("attachment repair parent-key selector did not match exactly one entry")
        raise BridgeError("multi-entry attachment repair requires --parent-key")
    unsigned = {
        "schema": MANIFEST_SCHEMA,
        "transaction_id": transaction_id,
        "generated_at": now_iso(),
        "target": target,
        "entries": sorted(entries, key=lambda entry: entry["parent"]["key"]),
    }
    return seal_manifest(unsigned)


def compile_membership(args: argparse.Namespace) -> dict[str, Any]:
    path, _ = collection_contract(args.group_id, args.collection_key, args.base_url)
    target = target_from_parts(
        group_id=args.group_id,
        library_id=args.library_id,
        library_name=args.library_name,
        collection_id=args.local_collection_id,
        collection_key=args.collection_key,
        collection_path=path,
        files=False,
    )
    entries: list[dict[str, Any]] = []
    for key in sorted(set(args.parent_key)):
        record = live_parent(args.group_id, key, args.base_url)
        data = record["data"]
        if args.collection_key in data.get("collections", []):
            raise BridgeError(f"parent {key} is already in the target; no membership write needed")
        parent = parent_from_data(data, args.library_id, False)
        entries.append(
            {
                "parent": parent,
                "operations": [{"type": "ensure_collection_membership", "expected_present": False}],
            }
        )
    return seal_manifest(
        {
            "schema": MANIFEST_SCHEMA,
            "transaction_id": args.transaction_id,
            "generated_at": now_iso(),
            "target": target,
            "entries": entries,
        }
    )


def compile_note_migration(source: Path, transaction_id: str, base_url: str) -> dict[str, Any]:
    migration = read_json(source)
    if not isinstance(migration, dict) or str(migration.get("manifest_version")) != "2":
        raise BridgeError("note migration manifest version mismatch")
    raw_target = migration.get("target")
    if not isinstance(raw_target, dict):
        raise BridgeError("note migration target is missing")
    group_id = positive_int(raw_target.get("group_id"), "target.group_id")
    library_id = positive_int(raw_target.get("library_id"), "target.library_id")
    collection_key = item_key(raw_target.get("collection_key"), "target.collection_key")
    path, _ = collection_contract(group_id, collection_key, base_url)
    if [part["name"] for part in path] != raw_target.get("collection_path"):
        raise BridgeError("note migration collection path drift")
    target = target_from_parts(
        group_id=group_id,
        library_id=library_id,
        library_name=text(raw_target.get("library_name"), "target.library_name", limit=256),
        collection_id=positive_int(raw_target.get("local_collection_id"), "target.local_collection_id"),
        collection_key=collection_key,
        collection_path=path,
        files=False,
    )
    entries: list[dict[str, Any]] = []
    for row in migration.get("entries", []):
        if not isinstance(row, dict) or row.get("status") not in {"staged_verified", "create_verified"}:
            continue
        parent_key = item_key(row.get("parent_key"), "entry.parent_key")
        record = live_parent(group_id, parent_key, base_url)
        data = record["data"]
        if collection_key not in data.get("collections", []):
            raise BridgeError(f"note parent {parent_key} is outside the target")
        parent = parent_from_data(data, library_id, True)
        if row.get("status") == "create_verified" and parent["version"] != row.get("parent_version"):
            raise BridgeError(f"note parent {parent_key} version drift")
        new_path = Path(text(row.get("new_path"), "entry.new_path", limit=16_384)).expanduser().resolve()
        if not new_path.is_file() or new_path.is_symlink():
            raise BridgeError(f"note source is not a regular non-symlink file: {new_path}")
        new_html = new_path.read_text(encoding="utf-8")
        new_hash = "sha256:" + hashlib.sha256(new_html.encode("utf-8")).hexdigest()
        declared_new = str(row.get("new_sha256", ""))
        if declared_new not in {new_hash, new_hash.removeprefix("sha256:")}:
            raise BridgeError(f"note source hash drift for {parent_key}")
        note_key_value = row.get("note_key") if row.get("status") == "staged_verified" else None
        expected_old = row.get("old_sha256") if note_key_value else None
        if isinstance(expected_old, str) and not expected_old.startswith("sha256:"):
            expected_old = "sha256:" + expected_old
        operation = {
            "type": "ensure_child_note",
            "note_key": note_key_value,
            "expected_note_version": row.get("note_version") if note_key_value else None,
            "expected_old_sha256": expected_old,
            "expected_child_note_keys": row.get("child_note_inventory", []),
            "new_html": new_html,
            "new_sha256": new_hash,
        }
        entries.append({"parent": parent, "operations": [operation]})
    if not entries:
        raise BridgeError("note migration has no staged_verified or create_verified writes")
    return seal_manifest(
        {
            "schema": MANIFEST_SCHEMA,
            "transaction_id": transaction_id,
            "generated_at": now_iso(),
            "target": target,
            "entries": sorted(entries, key=lambda entry: entry["parent"]["key"]),
        }
    )


def compile_short_title(args: argparse.Namespace) -> dict[str, Any]:
    path, _ = collection_contract(args.group_id, args.collection_key, args.base_url)
    target = target_from_parts(
        group_id=args.group_id,
        library_id=args.library_id,
        library_name=args.library_name,
        collection_id=args.local_collection_id,
        collection_key=args.collection_key,
        collection_path=path,
        files=False,
    )
    record = live_parent(args.group_id, args.parent_key, args.base_url)
    data = record["data"]
    if args.collection_key not in data.get("collections", []):
        raise BridgeError(f"shortTitle parent {args.parent_key} is outside the target")
    parent = parent_from_data(data, args.library_id, True)
    expected_version = positive_int(
        args.expected_parent_version,
        "expected_parent_version",
    )
    expected_old = short_title(
        args.expected_old_value,
        "expected_old_value",
        nonempty=False,
    )
    reviewed_new = short_title(
        args.new_short_title,
        "new_short_title",
        nonempty=True,
    )
    if reviewed_new != reviewed_new.strip():
        raise BridgeError("new_short_title must be trimmed")
    if parent["version"] != expected_version:
        raise BridgeError(f"shortTitle parent {args.parent_key} version drift")
    if str(data.get("shortTitle", "")) != expected_old:
        raise BridgeError(f"shortTitle parent {args.parent_key} old-value drift")
    if expected_old == reviewed_new:
        raise BridgeError(f"shortTitle parent {args.parent_key} already has the reviewed value")
    operation = {
        "type": "ensure_parent_short_title",
        "library_id": args.library_id,
        "parent_key": parent["key"],
        "expected_parent_version": expected_version,
        "expected_old_value": expected_old,
        "new_short_title": reviewed_new,
    }
    return seal_manifest(
        {
            "schema": MANIFEST_SCHEMA,
            "transaction_id": args.transaction_id,
            "generated_at": now_iso(),
            "target": target,
            "entries": [{"parent": parent, "operations": [operation]}],
        }
    )


def load_capability(path: Path) -> dict[str, Any]:
    path = path.expanduser().resolve()
    try:
        metadata = path.lstat()
    except OSError as exc:
        raise BridgeError(f"cannot stat capability file: {exc}") from exc
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
        raise BridgeError("capability path must be a regular non-symlink file")
    if hasattr(os, "getuid") and metadata.st_uid != os.getuid():
        raise BridgeError("capability file is not owned by the current user")
    if metadata.st_mode & 0o077:
        raise BridgeError("capability file permits group/other access")
    capability = exact_keys(
        read_json(path),
        {
            "schema",
            "endpoint",
            "key_id",
            "capability_token",
            "created_at",
            "zotero_version",
            "plugin_version",
            "expires_on_shutdown",
        },
        "capability",
    )
    if capability["schema"] != CAPABILITY_SCHEMA:
        raise BridgeError("capability schema mismatch")
    parsed = urllib.parse.urlsplit(capability["endpoint"])
    if (
        parsed.scheme != "http"
        or parsed.hostname != "127.0.0.1"
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
        or parsed.path != ENDPOINT_PATH
        or parsed.port is None
    ):
        raise BridgeError("capability endpoint is not the fixed literal-loopback endpoint")
    if not isinstance(capability["key_id"], str) or not re.fullmatch(r"[0-9a-f]{16}", capability["key_id"]):
        raise BridgeError("capability key_id is invalid")
    if not isinstance(capability["capability_token"], str) or not HEX_RE.fullmatch(capability["capability_token"]):
        raise BridgeError("capability token is invalid")
    if capability["expires_on_shutdown"] is not True:
        raise BridgeError("capability must expire on shutdown")
    return capability


def bridge_request(capability: dict[str, Any], action: str, payload: dict[str, Any]) -> dict[str, Any]:
    base = {
        "schema": REQUEST_SCHEMA,
        "request_id": uuid.uuid4().hex,
        "issued_at": now_iso(),
        "nonce": os.urandom(16).hex(),
        "key_id": capability["key_id"],
        "action": action,
        "payload": payload,
    }
    mac = hmac.new(
        bytes.fromhex(capability["capability_token"]),
        canonical_bytes(base),
        hashlib.sha256,
    ).hexdigest()
    envelope = {**base, "mac": mac}
    request = urllib.request.Request(
        capability["endpoint"],
        data=canonical_bytes(envelope),
        method="POST",
        headers={
            "Content-Type": "application/octet-stream",
            "Accept": "application/json",
            "User-Agent": "deep-research-zotero-bridge/0.1",
        },
    )
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(request, timeout=60.0) as response:
            result = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        try:
            result = validate_bridge_response(json.loads(body), action, base["request_id"])
        except (BridgeError, json.JSONDecodeError) as contract_error:
            raise BridgeError(f"bridge HTTP {exc.code} returned an invalid error response") from contract_error
        if result["error"] is None:
            raise BridgeError(f"bridge HTTP {exc.code} returned a non-error response") from exc
        raise BridgeResponseError(result) from exc
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        raise BridgeError(f"bridge request failed: {exc}") from exc
    result = validate_bridge_response(result, action, base["request_id"])
    if result["error"] is not None:
        raise BridgeResponseError(result)
    return result


def load_preview_receipt(path: Path, manifest: dict[str, Any]) -> dict[str, Any]:
    receipt = read_json(path)
    if not isinstance(receipt, dict) or receipt.get("schema") != RESPONSE_SCHEMA or receipt.get("action") != "preview":
        raise BridgeError("preview receipt contract mismatch")
    result = receipt.get("result")
    if not isinstance(result, dict) or result.get("manifest_sha256") != manifest["manifest_sha256"]:
        raise BridgeError("preview receipt is not bound to this manifest")
    for field in ("preview_id", "preview_token", "state_sha256"):
        if not isinstance(result.get(field), str) or not result[field]:
            raise BridgeError(f"preview receipt is missing {field}")
    return result


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    validate = sub.add_parser("validate")
    validate.add_argument("manifest", type=Path)

    repair = sub.add_parser("compile-attachment-repair")
    repair.add_argument("source", type=Path)
    repair.add_argument("output", type=Path)
    repair.add_argument("--transaction-id", required=True)
    repair.add_argument("--parent-key")

    notes = sub.add_parser("compile-note-migration")
    notes.add_argument("source", type=Path)
    notes.add_argument("output", type=Path)
    notes.add_argument("--transaction-id", required=True)
    notes.add_argument("--base-url", default=BASE_URL)

    membership = sub.add_parser("compile-membership")
    membership.add_argument("output", type=Path)
    membership.add_argument("--transaction-id", required=True)
    membership.add_argument("--group-id", type=int, required=True)
    membership.add_argument("--library-id", type=int, required=True)
    membership.add_argument("--library-name", required=True)
    membership.add_argument("--local-collection-id", type=int, required=True)
    membership.add_argument("--collection-key", required=True)
    membership.add_argument("--parent-key", action="append", required=True)
    membership.add_argument("--base-url", default=BASE_URL)

    short_title_parser = sub.add_parser("compile-short-title")
    short_title_parser.add_argument("output", type=Path)
    short_title_parser.add_argument("--transaction-id", required=True)
    short_title_parser.add_argument("--group-id", type=int, required=True)
    short_title_parser.add_argument("--library-id", type=int, required=True)
    short_title_parser.add_argument("--library-name", required=True)
    short_title_parser.add_argument("--local-collection-id", type=int, required=True)
    short_title_parser.add_argument("--collection-key", required=True)
    short_title_parser.add_argument("--parent-key", required=True)
    short_title_parser.add_argument("--expected-parent-version", type=int, required=True)
    short_title_parser.add_argument("--expected-old-value", required=True)
    short_title_parser.add_argument("--new-short-title", required=True)
    short_title_parser.add_argument("--base-url", default=BASE_URL)

    probe = sub.add_parser("probe")
    probe.add_argument("--capability-file", type=Path, required=True)

    for command in ("preview", "readback"):
        child = sub.add_parser(command)
        child.add_argument("manifest", type=Path)
        child.add_argument("--capability-file", type=Path, required=True)
        child.add_argument("--receipt", type=Path, required=True)

    apply = sub.add_parser("apply")
    apply.add_argument("manifest", type=Path)
    apply.add_argument("--capability-file", type=Path, required=True)
    apply.add_argument("--preview-receipt", type=Path, required=True)
    apply.add_argument("--receipt", type=Path, required=True)
    apply.add_argument("--yes", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        if args.command == "validate":
            manifest = validate_manifest(read_json(args.manifest))
            print(json.dumps({"status": "valid", "manifest_sha256": manifest["manifest_sha256"]}))
            return 0
        if args.command == "compile-attachment-repair":
            result = compile_attachment_repair(args.source, args.transaction_id, args.parent_key)
            write_private_json(args.output, result)
            print(json.dumps({"status": "compiled", "entries": len(result["entries"]), "manifest_sha256": result["manifest_sha256"]}))
            return 0
        if args.command == "compile-note-migration":
            result = compile_note_migration(args.source, args.transaction_id, args.base_url)
            write_private_json(args.output, result)
            print(json.dumps({"status": "compiled", "entries": len(result["entries"]), "manifest_sha256": result["manifest_sha256"]}))
            return 0
        if args.command == "compile-membership":
            result = compile_membership(args)
            write_private_json(args.output, result)
            print(json.dumps({"status": "compiled", "entries": len(result["entries"]), "manifest_sha256": result["manifest_sha256"]}))
            return 0
        if args.command == "compile-short-title":
            result = compile_short_title(args)
            write_private_json(args.output, result)
            print(json.dumps({"status": "compiled", "entries": len(result["entries"]), "manifest_sha256": result["manifest_sha256"]}))
            return 0

        capability = load_capability(args.capability_file)
        if args.command == "probe":
            response = bridge_request(capability, "probe", {})
            public = copy.deepcopy(response)
            if isinstance(public.get("result"), dict):
                public["result"].pop("preview_token", None)
            print(json.dumps(public, ensure_ascii=False, indent=2))
            return 0

        manifest = validate_manifest(read_json(args.manifest))
        if args.command == "preview":
            response = bridge_request(capability, "preview", {"manifest": manifest})
        elif args.command == "readback":
            response = bridge_request(capability, "readback", {"manifest": manifest})
        else:
            if not args.yes:
                raise BridgeError("apply is disabled without --yes")
            preview = load_preview_receipt(args.preview_receipt, manifest)
            response = bridge_request(
                capability,
                "apply",
                {
                    "manifest": manifest,
                    "preview_id": preview["preview_id"],
                    "preview_token": preview["preview_token"],
                    "state_sha256": preview["state_sha256"],
                },
            )
        write_private_json(args.receipt, response)
        summary = {
            "status": response.get("status"),
            "action": response.get("action"),
            "receipt": str(args.receipt.expanduser().resolve()),
        }
        print(json.dumps(summary, ensure_ascii=False))
        return 0
    except BridgeResponseError as exc:
        receipt_arg = getattr(args, "receipt", None)
        if receipt_arg is None:
            print(
                json.dumps(
                    {"error_code": exc.error_code, "commit_state": exc.commit_state},
                    ensure_ascii=False,
                ),
                file=sys.stderr,
            )
            return 3
        receipt_path = receipt_arg.expanduser().resolve()
        try:
            write_private_json(receipt_path, exc.response)
        except BridgeError:
            print(
                json.dumps(
                    {
                        "error_code": "receipt_write_failed",
                        "commit_state": exc.commit_state,
                        "receipt": str(receipt_path),
                    },
                    ensure_ascii=False,
                ),
                file=sys.stderr,
            )
            return 2
        print(
            json.dumps(
                {
                    "error_code": exc.error_code,
                    "commit_state": exc.commit_state,
                    "receipt": str(receipt_path),
                },
                ensure_ascii=False,
            ),
            file=sys.stderr,
        )
        return 3
    except BridgeError as exc:
        print(f"bridge error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
