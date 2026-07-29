#!/usr/bin/env python3
"""Dry-run or version-safely PATCH existing Zotero child notes.

The script validates every staged note against live local state before writing.
When the running Zotero exposes the documented per-instance server ID, apply
mode can request a local write key through Zotero's confirmation dialog. It can
otherwise use the official Web API with a dedicated key supplied through an
environment variable. It never prints or stores a key and never edits SQLite.
"""

from __future__ import annotations

import argparse
import hashlib
import re
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from verify_note_html import validate_note


LOCAL_BASE = "http://127.0.0.1:23119"
WEB_BASE = "https://api.zotero.org"

EXIT_OK = 0
EXIT_VALIDATION = 1
EXIT_IO = 2
EXIT_CONFLICT = 4
EXIT_CAPABILITY = 5

ITEM_KEY_PATTERN = re.compile(r"^[A-Z0-9]{8}$")
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
SUPPORTED_PDF_LINK_MODES = {
    "imported_file",
    "imported_url",
    "linked_file",
}


class MutationAcceptedButUnverified(RuntimeError):
    def __init__(self, note_key: str, parent_key: str, reason: str) -> None:
        self.note_key = note_key
        self.parent_key = parent_key
        self.reason = reason
        super().__init__(
            f"{note_key}: mutation accepted but unverified: {reason}"
        )


class MutationOutcomeUnknown(RuntimeError):
    def __init__(self, note_key: str, parent_key: str, reason: str) -> None:
        self.note_key = note_key
        self.parent_key = parent_key
        self.reason = reason
        super().__init__(
            f"{note_key}: mutation outcome unknown: {reason}"
        )


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _normalize_key_list(
    value: object,
    field: str,
    *,
    allow_empty: bool = False,
) -> list[str]:
    if not isinstance(value, list):
        raise ValueError(f"{field} must be a list")
    if not value and not allow_empty:
        raise ValueError(f"{field} must not be empty")
    normalized: list[str] = []
    for item in value:
        if not isinstance(item, str) or not ITEM_KEY_PATTERN.fullmatch(item):
            raise ValueError(f"{field} contains invalid item keys")
        normalized.append(item)
    if normalized != sorted(normalized):
        raise ValueError(f"{field} must be sorted in ascending order")
    if len(normalized) != len(set(normalized)):
        raise ValueError(f"{field} contains duplicate item keys")
    return normalized


def _read_bytes_for_manifest(path_value: object, field: str, note_key: str) -> bytes:
    if not isinstance(path_value, str):
        raise ValueError(f"{note_key}: {field} must be a path string")
    path = Path(path_value).expanduser()
    if not path.is_absolute():
        raise ValueError(f"{note_key}: {field} must be absolute")
    try:
        return path.read_bytes()
    except OSError as exc:
        raise ValueError(f"{note_key}: {field} is unreadable: {exc}") from exc


def verify_local_source_contract(local: dict[str, object]) -> None:
    note_key = str(local.get("note_key") or "")
    group_id = local.get("group_id")
    attachment_key = local.get("pdf_attachment_key")
    if type(group_id) is not int or group_id <= 0:
        raise RuntimeError(f"{note_key}: live PDF contract has an invalid group ID")
    if (
        not isinstance(attachment_key, str)
        or not ITEM_KEY_PATTERN.fullmatch(attachment_key)
    ):
        raise RuntimeError(
            f"{note_key}: live PDF contract has an invalid attachment key"
        )
    pdf_sha256 = local.get("pdf_sha256")
    if not isinstance(pdf_sha256, str) or not SHA256_PATTERN.fullmatch(pdf_sha256):
        raise RuntimeError(f"{note_key}: live PDF contract has an invalid SHA-256")
    pdf_path_value = local.get("pdf_path")
    try:
        pdf_bytes = _read_bytes_for_manifest(
            pdf_path_value,
            "pdf_path",
            note_key,
        )
    except ValueError as exc:
        raise RuntimeError(str(exc)) from exc
    if not pdf_bytes.startswith(b"%PDF-"):
        raise RuntimeError(f"{note_key}: live approved source is no longer a PDF")
    observed_sha256 = sha256_bytes(pdf_bytes)
    if observed_sha256 != pdf_sha256:
        raise RuntimeError(
            f"{note_key}: live approved PDF hash changed "
            f"{observed_sha256} != {pdf_sha256}"
        )
    status, _, body = request(
        f"{LOCAL_BASE}/api/groups/{group_id}/items/"
        f"{urllib.parse.quote(attachment_key)}/file/view/url"
    )
    if status != 200:
        raise RuntimeError(
            f"{note_key}: live attachment path lookup returned HTTP {status}"
        )
    try:
        file_url = body.decode("utf-8").strip()
    except UnicodeDecodeError as exc:
        raise RuntimeError(
            f"{note_key}: live attachment path lookup is not UTF-8"
        ) from exc
    parsed = urllib.parse.urlsplit(file_url)
    if (
        parsed.scheme != "file"
        or parsed.netloc not in {"", "localhost"}
        or not parsed.path
        or parsed.query
        or parsed.fragment
    ):
        raise RuntimeError(
            f"{note_key}: live attachment path lookup did not return a local file URL"
        )
    try:
        observed_path = Path(urllib.parse.unquote(parsed.path)).resolve(strict=True)
        expected_path = Path(str(pdf_path_value)).expanduser().resolve(strict=True)
    except OSError as exc:
        raise RuntimeError(
            f"{note_key}: live attachment path cannot be resolved: {exc}"
        ) from exc
    if observed_path != expected_path:
        raise RuntimeError(
            f"{note_key}: live attachment file path changed "
            f"{observed_path} != {expected_path}"
        )
    parent_key = local.get("parent_key")
    expected_version = local.get("local_version")
    expected_old_sha256 = local.get("old_sha256")
    if (
        not isinstance(parent_key, str)
        or not ITEM_KEY_PATTERN.fullmatch(parent_key)
        or type(expected_version) is not int
        or expected_version <= 0
        or not isinstance(expected_old_sha256, str)
        or not SHA256_PATTERN.fullmatch(expected_old_sha256)
    ):
        raise RuntimeError(
            f"{note_key}: live note source contract is incomplete"
        )
    _, note_obj = get_json(
        f"{LOCAL_BASE}/api/groups/{group_id}/items/{note_key}"
    )
    if not isinstance(note_obj, dict) or not isinstance(note_obj.get("data"), dict):
        raise RuntimeError(f"{note_key}: malformed live note source response")
    note_data = note_obj["data"]
    if (
        note_data.get("itemType") != "note"
        or note_data.get("deleted")
        or note_data.get("parentItem") != parent_key
    ):
        raise RuntimeError(
            f"{note_key}: live note type/deleted/parent state changed"
        )
    observed_version = parse_version(
        note_key,
        source="live local note source",
        json_version=note_obj.get("version"),
        headers=None,
    )
    if note_data.get("version") is not None:
        data_version = parse_version(
            note_key,
            source="live local note source data",
            json_version=note_data.get("version"),
        )
        if data_version != observed_version:
            raise RuntimeError(
                f"{note_key}: live local note version fields disagree"
            )
    if observed_version != expected_version:
        raise RuntimeError(
            f"{note_key}: live local note version changed "
            f"{observed_version} != {expected_version}"
        )
    observed_note_sha256 = sha256_text(str(note_data.get("note") or ""))
    if observed_note_sha256 != expected_old_sha256:
        raise RuntimeError(
            f"{note_key}: live local note content changed "
            f"{observed_note_sha256} != {expected_old_sha256}"
        )


def request(
    url: str,
    *,
    method: str = "GET",
    headers: dict[str, str] | None = None,
    payload: object | None = None,
    timeout: int = 30,
) -> tuple[int, dict[str, str], bytes]:
    data = None
    final_headers = dict(headers or {})
    if payload is not None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        final_headers.setdefault("Content-Type", "application/json")
    req = urllib.request.Request(
        url,
        data=data,
        headers=final_headers,
        method=method,
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            return response.status, dict(response.headers.items()), response.read()
    except urllib.error.HTTPError as exc:
        return exc.code, dict(exc.headers.items()), exc.read()


def get_json(url: str, headers: dict[str, str] | None = None) -> tuple[dict[str, str], object]:
    status, response_headers, body = request(url, headers=headers)
    if status != 200:
        raise RuntimeError(f"GET {url} returned HTTP {status}")
    return response_headers, json.loads(body.decode("utf-8"))


def verify_item_readback(
    note_key: str,
    *,
    get_item: Callable[[], tuple[dict[str, str], dict[str, object]]],
    get_parent: Callable[[str], tuple[dict[str, str], dict[str, object]]],
    expected_parent_key: str,
    expected_collection_key: str,
    expected_new_sha256: str,
    previous_version: int,
    source: str,
) -> tuple[int, str]:
    readback_headers, readback = get_item()
    if not isinstance(readback, dict) or not isinstance(readback.get("data"), dict):
        raise RuntimeError(f"{note_key}: malformed {source} readback")
    readback_data = readback["data"]
    if readback_data.get("itemType") != "note":
        raise RuntimeError(f"{note_key}: {source} readback type is not a note")
    if readback_data.get("deleted"):
        raise RuntimeError(f"{note_key}: {source} readback is deleted")

    readback_parent_key = readback_data.get("parentItem")
    if not isinstance(readback_parent_key, str):
        raise RuntimeError(f"{note_key}: {source} readback parent is malformed")
    if readback_parent_key != expected_parent_key:
        raise RuntimeError(
            f"{note_key}: {source} readback parent changed to {readback_parent_key!r}"
        )

    _, parent_obj = get_parent(readback_parent_key)
    if not isinstance(parent_obj, dict) or not isinstance(parent_obj.get("data"), dict):
        raise RuntimeError(f"{note_key}: malformed {source} parent readback")
    parent_data = parent_obj["data"]
    if parent_data.get("deleted"):
        raise RuntimeError(f"{note_key}: {source} parent is deleted")
    collections = parent_data.get("collections")
    if not isinstance(collections, list) or expected_collection_key not in collections:
        raise RuntimeError(
            f"{note_key}: {source} parent is outside approved collection "
            f"{expected_collection_key}"
        )

    item_version = parse_version(
        note_key,
        source=f"{source} readback",
        json_version=readback.get("version"),
        headers=readback_headers,
        previous_version=previous_version,
    )
    if readback_data.get("version") is not None:
        readback_data_version = parse_version(
            note_key,
            source=f"{source} readback data",
            json_version=readback_data.get("version"),
        )
        if readback_data_version != item_version:
            raise RuntimeError(
                f"{note_key}: {source} readback version mismatch: "
                f"top={item_version}, data={readback_data_version}"
            )

    readback_sha = sha256_text(str(readback_data.get("note") or ""))
    if readback_sha != expected_new_sha256:
        raise RuntimeError(
            f"{note_key}: {source} readback hash mismatch "
            f"{readback_sha} != {expected_new_sha256}"
        )

    return item_version, readback_sha


def _run_contract_guard(
    action: str,
    target_contract: dict[str, Any] | None,
    callback: Callable[[dict[str, Any]], object] | None,
) -> None:
    if callback is None:
        return
    if target_contract is None:
        raise RuntimeError(f"{action} contract check requires target_contract")
    callback(target_contract)


def header_value(headers: dict[str, str], name: str) -> str | None:
    wanted = name.casefold()
    return next(
        (value for key, value in headers.items() if key.casefold() == wanted),
        None,
    )


def probe_local_write() -> dict[str, object]:
    status, headers, _ = request(f"{LOCAL_BASE}/api/")
    server_id = header_value(headers, "Zotero-Server-ID")
    return {
        "api_status": status,
        "server_id_present": bool(server_id),
        "server_id": server_id,
        "authorization_probe": "deferred_until_apply",
        "supported": status == 200 and bool(server_id),
    }


def authorize_local(server_id: str, app_name: str) -> dict[str, object]:
    status, response_headers, body = request(
        f"{LOCAL_BASE}/api/local/authorize",
        method="POST",
        headers={
            "Zotero-API-Version": "3",
            "Zotero-Server-ID": server_id,
        },
        payload={"appName": app_name},
        timeout=55,
    )
    if status == 403:
        raise RuntimeError("local write authorization was denied")
    if status == 404:
        raise RuntimeError("running Zotero does not expose /api/local/authorize")
    if status == 429:
        retry_after = header_value(response_headers, "Retry-After")
        suffix = f"; retry after {retry_after} seconds" if retry_after else ""
        raise RuntimeError(f"local write authorization was rate-limited{suffix}")
    if status != 200:
        raise RuntimeError(f"local write authorization returned HTTP {status}")
    try:
        payload = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeError("local write authorization returned malformed JSON") from exc
    key = payload.get("key") if isinstance(payload, dict) else None
    if not isinstance(key, str) or not key:
        raise RuntimeError("local write authorization returned no key")
    return {
        "api_key": key,
        "remember": bool(payload.get("remember")),
    }


def local_headers(api_key: str, server_id: str) -> dict[str, str]:
    return {
        "Zotero-API-Key": api_key,
        "Zotero-API-Version": "3",
        "Zotero-Server-ID": server_id,
    }


def choose_route(
    requested: str,
    *,
    local_supported: bool,
    web_key_present: bool,
) -> str | None:
    if requested == "local":
        return "local" if local_supported else None
    if requested == "web":
        return "web" if web_key_present else None
    if local_supported:
        return "local"
    return "web" if web_key_present else None


def unavailable_route_message(requested: str, api_key_env: str) -> str:
    if requested == "local":
        return (
            "local write route unavailable: running Zotero exposes no "
            "per-instance local write authorization"
        )
    if requested == "web":
        return f"Web API write route unavailable: {api_key_env} is unset"
    return (
        "no supported write route: running Zotero exposes no per-instance "
        f"local write authorization and {api_key_env} is unset"
    )


def selected_target() -> dict[str, object]:
    status, _, body = request(
        f"{LOCAL_BASE}/connector/getSelectedCollection",
        method="POST",
        headers={"Content-Type": "application/json"},
        payload={},
    )
    if status != 200:
        raise RuntimeError(f"selected-target probe returned HTTP {status}")
    payload = json.loads(body.decode("utf-8"))
    selected_id = normalize_collection_identifier(payload.get("id"))
    selected_path: list[str] | None = None
    targets = payload.get("targets")
    if isinstance(targets, list):
        stack: list[dict[str, object]] = []
        for candidate in targets:
            if not isinstance(candidate, dict):
                continue
            level = candidate.get("level")
            if type(level) is not int or level < 0:
                continue
            stack = stack[:level]
            if len(stack) != level:
                stack = []
                if level != 0:
                    continue
            stack.append(candidate)
            if (
                level > 0
                and normalize_collection_identifier(candidate.get("id"))
                == selected_id
            ):
                root_id = str(stack[0].get("id") or "")
                expected_root_id = f"L{payload.get('libraryID')}"
                if root_id == expected_root_id:
                    selected_path = [
                        str(part.get("name") or "") for part in stack[1:]
                    ]
                break
    return {
        "libraryID": payload.get("libraryID"),
        "libraryName": payload.get("libraryName"),
        "name": payload.get("name"),
        "editable": payload.get("editable"),
        "filesEditable": payload.get("filesEditable"),
        "id": payload.get("id"),
        "collectionPath": selected_path,
    }


def normalize_collection_identifier(value: object) -> str:
    if isinstance(value, bool) or value is None:
        return ""
    if isinstance(value, int):
        return str(value)
    if not isinstance(value, str):
        return ""
    text = value.strip()
    if text.upper().startswith("C") and text[1:].isdigit():
        return text[1:]
    return text


def parse_version(
    note_key: str,
    *,
    source: str,
    json_version: object,
    headers: dict[str, str] | None = None,
    previous_version: int | None = None,
) -> int:
    header_value_raw = header_value(headers or {}, "Last-Modified-Version")
    header_text = header_value_raw.strip() if isinstance(header_value_raw, str) else None
    header_version: int | None = None
    if header_text is not None:
        if not header_text.isdigit():
            raise RuntimeError(
                f"{note_key}: {source} Last-Modified-Version is not numeric: {header_text!r}"
            )
        header_version = int(header_text)

    if type(json_version) is bool:
        raise RuntimeError(f"{note_key}: {source} version has invalid type bool")
    if type(json_version) is int:
        version = json_version
    elif isinstance(json_version, str) and json_version.isdigit():
        version = int(json_version)
    elif header_version is not None:
        version = header_version
    else:
        raise RuntimeError(f"{note_key}: {source} version is unavailable")

    if header_version is not None and version != header_version:
        raise RuntimeError(
            f"{note_key}: {source} version mismatch: body={version}, header={header_version}"
        )

    if previous_version is not None and version <= previous_version:
        raise RuntimeError(
            f"{note_key}: {source} version did not advance ({version} <= {previous_version})"
        )
    if version <= 0:
        raise RuntimeError(f"{note_key}: {source} version must be positive")
    return version


def get_all_item_pages(
    url: str,
    *,
    headers: dict[str, str] | None = None,
    page_size: int = 100,
) -> list[dict[str, object]]:
    if type(page_size) is not int or page_size <= 0:
        raise ValueError("page_size must be a positive integer")
    collected: list[dict[str, object]] = []
    observed_full_pages: set[tuple[str, ...]] = set()
    start = 0
    while True:
        separator = "&" if "?" in url else "?"
        _, page = get_json(
            f"{url}{separator}limit={page_size}&start={start}",
            headers=headers,
        )
        if not isinstance(page, list):
            raise RuntimeError(
                f"paginated item response at start={start} is malformed"
            )
        if any(not isinstance(item, dict) for item in page):
            raise RuntimeError(
                f"paginated item response at start={start} contains a non-object"
            )
        if len(page) > page_size:
            raise RuntimeError(
                f"paginated item response at start={start} exceeds its limit"
            )
        collected.extend(page)
        if len(page) < page_size:
            return collected
        page_keys = tuple(str(item.get("key") or "") for item in page)
        if page_keys in observed_full_pages:
            raise RuntimeError("item pagination did not advance")
        observed_full_pages.add(page_keys)
        start += page_size


def enumerate_collection_inventory(
    base_api: str,
    group_id: int,
    collection_key: str,
    headers: dict[str, str] | None = None,
    *,
    group_route: str = "/api/groups",
) -> list[str]:
    parents = get_all_item_pages(
        f"{base_api}{group_route}/{group_id}/collections/"
        f"{urllib.parse.quote(collection_key)}/items/top?include=data",
        headers=headers,
    )
    parent_keys: list[str] = []
    for index, parent in enumerate(parents):
        if not isinstance(parent, dict):
            raise RuntimeError(
                f"collection inventory entry {index} is not an object"
            )
        parent_key = parent.get("key")
        if not isinstance(parent_key, str) or not ITEM_KEY_PATTERN.fullmatch(parent_key):
            raise RuntimeError(
                f"collection inventory entry {index} has no valid parent key"
            )
        data = parent.get("data")
        if not isinstance(data, dict):
            raise RuntimeError(
                f"collection inventory entry {index} has malformed payload"
            )
        if (
            data.get("itemType") in {"note", "attachment", "annotation"}
            or data.get("parentItem")
            or data.get("deleted")
        ):
            raise RuntimeError(
                f"collection inventory entry {parent_key} is not a live regular item"
            )
        parent_keys.append(parent_key)
    if len(parent_keys) != len(set(parent_keys)):
        raise RuntimeError("collection inventory contains duplicate keys")
    return sorted(parent_keys)


def enumerate_parent_children(
    base_api: str,
    group_id: int,
    parent_key: str,
    headers: dict[str, str] | None = None,
    *,
    group_route: str = "/api/groups",
    expected_pdf_attachment_key: str | None = None,
    expected_pdf_link_mode: str | None = None,
) -> tuple[list[str], list[str]]:
    children = get_all_item_pages(
        f"{base_api}{group_route}/{group_id}/items/"
        f"{urllib.parse.quote(parent_key)}/children?include=data",
        headers=headers,
    )
    child_notes: list[str] = []
    child_attachments: list[str] = []
    approved_pdf_observed = False
    for index, child in enumerate(children):
        if not isinstance(child, dict):
            raise RuntimeError(f"{parent_key}: child {index} is not an object")
        key = child.get("key")
        data = child.get("data")
        if not isinstance(key, str) or not ITEM_KEY_PATTERN.fullmatch(key):
            raise RuntimeError(
                f"{parent_key}: child {index} has no valid key"
            )
        if not isinstance(data, dict):
            raise RuntimeError(
                f"{parent_key}: child {index} has malformed payload"
            )
        if data.get("parentItem") != parent_key or data.get("deleted"):
            raise RuntimeError(
                f"{parent_key}: child {key} parent/deleted state changed"
            )
        item_type = str(data.get("itemType") or "").lower()
        if item_type == "note":
            child_notes.append(key)
        elif item_type == "attachment":
            child_attachments.append(key)
            if key == expected_pdf_attachment_key:
                if (
                    data.get("contentType") != "application/pdf"
                    or data.get("linkMode") != expected_pdf_link_mode
                ):
                    raise RuntimeError(
                        f"{parent_key}: approved PDF attachment metadata changed"
                    )
                approved_pdf_observed = True
    if len(child_notes) != len(set(child_notes)):
        raise RuntimeError(f"{parent_key}: duplicate child note keys in live inventory")
    if len(child_attachments) != len(set(child_attachments)):
        raise RuntimeError(
            f"{parent_key}: duplicate child attachment keys in live inventory"
        )
    if expected_pdf_attachment_key and not approved_pdf_observed:
        raise RuntimeError(
            f"{parent_key}: approved PDF attachment is missing from live children"
        )
    return sorted(child_notes), sorted(child_attachments)


def verify_inventory_contract(
    *,
    base_api: str,
    group_id: int,
    collection_key: str,
    entries: list[dict[str, object]],
    headers: dict[str, str] | None = None,
    group_route: str = "/api/groups",
) -> None:
    expected_parent_keys = _normalize_key_list(
        sorted(str(entry.get("parent_key") or "") for entry in entries),
        "manifest parent keys",
    )
    live_parent_keys = enumerate_collection_inventory(
        base_api,
        group_id,
        collection_key,
        headers=headers,
        group_route=group_route,
    )
    if live_parent_keys != expected_parent_keys:
        raise RuntimeError("live collection inventory does not match manifest snapshot")
    for entry in entries:
        parent_key = str(entry["parent_key"])
        live_child_notes, live_child_attachments = enumerate_parent_children(
            base_api,
            group_id,
            parent_key,
            headers=headers,
            group_route=group_route,
            expected_pdf_attachment_key=(
                str(entry["pdf_attachment_key"])
                if entry.get("status") == "staged_verified"
                else None
            ),
            expected_pdf_link_mode=(
                str(entry["pdf_attachment_link_mode"])
                if entry.get("status") == "staged_verified"
                else None
            ),
        )
        expected_child_notes = _normalize_key_list(
            entry.get("child_note_inventory"),
            "manifest child_note_inventory",
            allow_empty=True,
        )
        expected_child_attachments = _normalize_key_list(
            entry.get("child_attachment_inventory"),
            "manifest child_attachment_inventory",
            allow_empty=True,
        )
        if live_child_notes != expected_child_notes:
            raise RuntimeError(
                f"{parent_key}: live child note inventory does not match manifest"
            )
        if live_child_attachments != expected_child_attachments:
            raise RuntimeError(
                f"{parent_key}: live child attachment inventory does not match manifest"
            )


def resolve_target_contract(target: dict[str, Any]) -> dict[str, Any]:
    required_fields = (
        "library_id",
        "library_name",
        "local_collection_id",
        "collection_path",
        "collection_key",
        "group_id",
    )
    missing = [field for field in required_fields if field not in target]
    if missing:
        raise ValueError(
            "manifest target is missing required exact contract fields: "
            f"{', '.join(sorted(missing))}"
        )

    try:
        collection_path_raw = target["collection_path"]
        if not isinstance(collection_path_raw, list):
            raise TypeError("collection_path must be a list")
        collection_path = [str(part).strip() for part in collection_path_raw]
        if not collection_path or any(not part for part in collection_path):
            raise ValueError("collection_path is empty")
        collection_name = collection_path[-1]
        if (
            "collection_name" in target
            and str(target["collection_name"]) != collection_name
        ):
            raise ValueError("collection_name does not match collection_path")
        if type(target["library_id"]) is not int or target["library_id"] <= 0:
            raise ValueError("library_id is invalid")
        if type(target["group_id"]) is not int or target["group_id"] <= 0:
            raise ValueError("group_id is invalid")
        library_name = str(target["library_name"]).strip()
        if not library_name:
            raise ValueError("library_name is empty")
        local_collection_id = normalize_collection_identifier(
            target["local_collection_id"]
        )
        if not local_collection_id.isdigit() or int(local_collection_id) <= 0:
            raise ValueError("local_collection_id is invalid")
        collection_key = str(target["collection_key"])
        if not collection_key:
            raise ValueError("collection_key is empty")
        return {
            "strict": True,
            "group_id": target["group_id"],
            "library_id": target["library_id"],
            "library_name": library_name,
            "collection_key": collection_key,
            "collection_name": collection_name,
            "collection_path": collection_path,
            "local_collection_id": local_collection_id,
        }
    except (TypeError, ValueError) as exc:
        raise ValueError(f"manifest target is invalid: {exc}") from exc


def verify_explicit_api_collection_contract(
    target: dict[str, Any],
    *,
    base_api: str = LOCAL_BASE,
    collection_route: str = "/api/groups",
    headers: dict[str, str] | None = None,
) -> dict[str, object]:
    group_id = int(target["group_id"])
    current_key = str(target["collection_key"])
    expected_path = list(target["collection_path"])
    seen: set[str] = set()
    names: list[str] = []
    observed_library_name: str | None = None
    while current_key:
        if current_key in seen:
            raise RuntimeError("explicit API collection hierarchy contains a cycle")
        seen.add(current_key)
        _, collection = get_json(
            f"{base_api}{collection_route}/{group_id}/collections/"
            f"{urllib.parse.quote(current_key)}",
            headers=headers,
        )
        if not isinstance(collection, dict) or not isinstance(
            collection.get("data"),
            dict,
        ):
            raise RuntimeError("explicit API collection response is malformed")
        data = collection["data"]
        library = collection.get("library")
        if not isinstance(library, dict):
            raise RuntimeError("explicit API collection has no library identity")
        library_group_id = library.get("id")
        if (
            type(library_group_id) is not int
            or library_group_id != group_id
            or library.get("type") != "group"
        ):
            raise RuntimeError("explicit API collection group identity changed")
        library_name = str(library.get("name") or "").strip()
        if not library_name:
            raise RuntimeError("explicit API collection library name is missing")
        if observed_library_name is None:
            observed_library_name = library_name
        elif observed_library_name != library_name:
            raise RuntimeError("explicit API collection hierarchy crosses libraries")
        observed_key = str(collection.get("key") or data.get("key") or "")
        if observed_key != current_key:
            raise RuntimeError("explicit API collection key changed")
        name = str(data.get("name") or "").strip()
        if not name:
            raise RuntimeError("explicit API collection name is missing")
        names.append(name)
        parent = data.get("parentCollection")
        if parent is False or parent is None:
            break
        if not isinstance(parent, str) or not parent:
            raise RuntimeError("explicit API parent collection key is invalid")
        current_key = parent

    observed_path = list(reversed(names))
    if (
        observed_library_name != target["library_name"]
        or observed_path != expected_path
    ):
        raise RuntimeError(
            "explicit API group/key does not match the approved library/path"
        )
    return {
        "group_id": group_id,
        "library_name": observed_library_name,
        "collection_key": target["collection_key"],
        "collection_path": observed_path,
        "verified": True,
    }


def verify_target_match(selected: dict[str, object], target: dict[str, Any]) -> None:
    if not selected.get("editable") or not selected.get("filesEditable"):
        raise RuntimeError("selected target is not editable or files are not writable")

    if not target.get("strict"):
        raise RuntimeError("legacy target contract is no longer supported")

    selected_library_id = normalize_collection_identifier(selected.get("libraryID"))
    expected_library_id = str(target["library_id"])
    if selected_library_id != expected_library_id:
        raise RuntimeError(
            "selected target mismatch: library id does not match exact contract"
        )
    if str(selected.get("libraryName")) != str(target["library_name"]):
        raise RuntimeError(
            "selected target mismatch: library name does not match exact contract"
        )
    selected_collection_id = normalize_collection_identifier(selected.get("id"))
    if selected_collection_id != target["local_collection_id"]:
        raise RuntimeError(
            "selected target mismatch: collection id does not match exact contract"
        )
    if str(selected.get("name")) != str(target["collection_name"]):
        raise RuntimeError(
            "selected target mismatch: collection name does not match exact contract"
        )
    if selected.get("collectionPath") != target["collection_path"]:
        raise RuntimeError(
            "selected target mismatch: collection path does not match exact contract"
        )


def load_entries(manifest_path: Path, requested_keys: set[str]) -> tuple[dict[str, object], list[dict[str, object]]]:
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or not isinstance(payload.get("entries"), list):
        raise ValueError("migration manifest is missing entries")
    if payload.get("manifest_version") != "2":
        raise ValueError("migration manifest version must be '2'")
    if payload.get("write_performed") is not False:
        raise ValueError("migration manifest must have write_performed set to False")
    inventory = _normalize_key_list(
        payload.get("collection_item_inventory"),
        "collection_item_inventory",
    )
    allowed_statuses = {
        "staged_verified",
        "staged_invalid",
        "no_existing_note",
        "blocked_multiple_notes",
        "blocked_multiple_pdfs",
    }
    if any(not isinstance(entry, dict) for entry in payload["entries"]):
        raise ValueError("migration manifest contains a non-object entry")
    observed_statuses = {entry.get("status") for entry in payload["entries"]}
    unknown_statuses = observed_statuses - allowed_statuses
    if unknown_statuses:
        raise ValueError(
            "migration manifest has unsupported entry statuses: "
            f"{sorted(str(status) for status in unknown_statuses)}"
        )
    if observed_statuses & {
        "staged_invalid",
        "blocked_multiple_notes",
        "blocked_multiple_pdfs",
    }:
        raise ValueError(
            "migration manifest contains invalid or ambiguous note entries"
        )
    target = payload.get("target")
    if not isinstance(target, dict):
        raise ValueError("migration manifest target is missing")
    target = dict(target)
    all_entries = list(payload["entries"])
    staged_entries = [
        entry
        for entry in all_entries
        if entry.get("status") == "staged_verified"
    ]
    entry_parent_keys = _normalize_key_list(
        sorted(str(entry.get("parent_key") or "") for entry in all_entries),
        "entry parent keys",
    )
    if entry_parent_keys != inventory:
        raise ValueError(
            "migration manifest entries do not exactly cover collection inventory"
        )
    deduped: list[dict[str, object]] = []
    seen_keys: set[str] = set()
    selected_keys: set[str] = set()
    for entry in all_entries:
        status = entry.get("status")
        parent_key = str(entry.get("parent_key"))
        if not ITEM_KEY_PATTERN.fullmatch(parent_key):
            raise ValueError(f"{parent_key}: parent_key is invalid")
        child_notes = _normalize_key_list(
            entry.get("child_note_inventory"),
            "manifest child_note_inventory",
            allow_empty=True,
        )
        child_attachments = _normalize_key_list(
            entry.get("child_attachment_inventory"),
            "manifest child_attachment_inventory",
            allow_empty=True,
        )
        if status == "no_existing_note" and child_notes:
            raise ValueError(
                f"{parent_key}: no_existing_note has a nonempty child note inventory"
            )
        if status != "staged_verified":
            continue
        expected_parent_key = entry.get("expected_parent_key")
        if not ITEM_KEY_PATTERN.fullmatch(str(expected_parent_key)):
            raise ValueError(f"{parent_key}: expected_parent_key is invalid")
        if str(expected_parent_key) != parent_key:
            raise ValueError(
                f"{parent_key}: expected_parent_key does not match parent_key"
            )
        note_key = str(entry.get("note_key"))
        if not ITEM_KEY_PATTERN.fullmatch(note_key):
            raise ValueError(f"{parent_key}: note_key is invalid")
        if child_notes != [note_key]:
            raise ValueError(
                f"{parent_key}: staged child_note_inventory must be exactly the note key"
            )
        old_path = entry.get("old_path")
        new_path = entry.get("new_path")
        old_sha = entry.get("old_sha256")
        new_sha = entry.get("new_sha256")
        if not isinstance(old_sha, str) or not SHA256_PATTERN.fullmatch(old_sha):
            raise ValueError(f"{parent_key}: old_sha256 is invalid")
        if not isinstance(new_sha, str) or not SHA256_PATTERN.fullmatch(new_sha):
            raise ValueError(f"{parent_key}: new_sha256 is invalid")
        if old_sha == new_sha:
            raise ValueError(f"{parent_key}: staged note is a no-op")
        if not isinstance(entry.get("note_version"), int) or entry["note_version"] <= 0:
            raise ValueError(f"{parent_key}: note_version is invalid")
        if not isinstance(entry.get("old_path"), str) or not isinstance(
            entry.get("new_path"), str
        ):
            raise ValueError(f"{parent_key}: old_path and new_path must be paths")

        old_bytes = _read_bytes_for_manifest(old_path, "old_path", note_key)
        if sha256_bytes(old_bytes) != old_sha:
            raise ValueError(
                f"{note_key}: old_path hash does not match manifest old_sha256"
            )
        new_bytes = _read_bytes_for_manifest(new_path, "new_path", note_key)
        if sha256_bytes(new_bytes) != new_sha:
            raise ValueError(
                f"{note_key}: new_path hash does not match manifest new_sha256"
            )
        pdf_sha = entry.get("pdf_sha256")
        if not isinstance(pdf_sha, str) or not SHA256_PATTERN.fullmatch(pdf_sha):
            raise ValueError(f"{note_key}: pdf_sha256 is invalid")
        pdf_bytes = _read_bytes_for_manifest(entry.get("pdf_path"), "pdf_path", note_key)
        if not pdf_bytes.startswith(b"%PDF-"):
            raise ValueError(f"{note_key}: pdf_path does not point to a PDF file")
        if sha256_bytes(pdf_bytes) != pdf_sha:
            raise ValueError(f"{note_key}: pdf_path hash does not match manifest")
        pdf_attachment_key = entry.get("pdf_attachment_key")
        if (
            not isinstance(pdf_attachment_key, str)
            or not ITEM_KEY_PATTERN.fullmatch(pdf_attachment_key)
            or pdf_attachment_key not in child_attachments
        ):
            raise ValueError(
                f"{note_key}: pdf_attachment_key is not in child attachment inventory"
            )
        if entry.get("pdf_attachment_link_mode") not in SUPPORTED_PDF_LINK_MODES:
            raise ValueError(f"{note_key}: pdf_attachment_link_mode is invalid")
        summary = entry.get("validation_summary")
        errors = entry.get("validation_errors")
        if not isinstance(summary, dict):
            raise ValueError(f"{note_key}: validation_summary is missing")
        if str(summary.get("schema_version")) != "9":
            raise ValueError(f"{note_key}: validation_summary schema_version is not 9")
        full_text = summary.get("full_text_sha256")
        if not isinstance(errors, list) or errors:
            raise ValueError(f"{note_key}: validation_errors must be an empty list")
        if not isinstance(full_text, str) or not SHA256_PATTERN.fullmatch(full_text):
            raise ValueError(f"{note_key}: validation_summary.full_text_sha256 invalid")
        if full_text != pdf_sha:
            raise ValueError(
                f"{note_key}: validation_summary full_text_sha256 does not match pdf_sha256"
            )
        try:
            new_html = new_bytes.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ValueError(f"{note_key}: new_path is not UTF-8 HTML") from exc
        if sha256_text(new_html.strip()) == old_sha:
            raise ValueError(
                f"{note_key}: staged note normalizes to the existing note"
            )
        live_errors, _live_warnings, live_summary = validate_note(new_html)
        if live_errors:
            raise ValueError(
                f"{note_key}: staged note fails the live schema-9 validator: "
                f"{live_errors}"
            )
        if (
            str(live_summary.get("schema_version")) != "9"
            or live_summary.get("full_text_sha256") != pdf_sha
        ):
            raise ValueError(
                f"{note_key}: live validator did not bind schema 9 to the PDF hash"
            )
        if note_key in seen_keys:
            raise ValueError(f"duplicate note_key in staged entries: {note_key}")
        seen_keys.add(note_key)
        if requested_keys and note_key not in requested_keys:
            continue
        selected_keys.add(note_key)
        deduped.append(entry)

    if requested_keys:
        missing = requested_keys - selected_keys
        if missing:
            raise ValueError(
                f"requested note keys are not staged_verified: {sorted(missing)}"
            )
    if not staged_entries:
        raise ValueError("no staged_verified notes selected")
    target["_entries_for_inventory"] = all_entries
    return target, deduped


def verify_local_entry(
    group_id: int,
    collection_key: str,
    entry: dict[str, object],
) -> dict[str, object]:
    note_key = str(entry["note_key"])
    parent_key = str(entry["expected_parent_key"])
    _, note_obj = get_json(f"{LOCAL_BASE}/api/groups/{group_id}/items/{note_key}")
    if not isinstance(note_obj, dict) or not isinstance(note_obj.get("data"), dict):
        raise RuntimeError(f"{note_key}: malformed local note response")
    note_data = note_obj["data"]
    observed_note = str(note_data.get("note") or "")
    observed_sha = sha256_text(observed_note)
    if note_data.get("itemType") != "note":
        raise RuntimeError(f"{note_key}: target is not a note")
    if note_data.get("deleted"):
        raise RuntimeError(f"{note_key}: target note is deleted")
    if note_data.get("parentItem") != parent_key:
        raise RuntimeError(
            f"{note_key}: parent changed {note_data.get('parentItem')!r} != {parent_key!r}"
        )
    if observed_sha != entry.get("old_sha256"):
        raise RuntimeError(
            f"{note_key}: old content conflict {observed_sha} != {entry.get('old_sha256')}"
        )
    expected_version = entry.get("note_version")
    if type(expected_version) is not int:
        raise RuntimeError(
            f"{note_key}: manifest note version must be an integer"
        )
    local_version = parse_version(
        note_key,
        source="local note",
        json_version=note_obj.get("version"),
        headers=None,
    )
    if note_data.get("version") is not None:
        data_version = parse_version(
            note_key,
            source="local note data",
            json_version=note_data.get("version"),
        )
        if data_version != local_version:
            raise RuntimeError(
                f"{note_key}: local version mismatch: top={local_version}, "
                f"data={data_version}"
            )
    if local_version != expected_version:
        raise RuntimeError(
            f"{note_key}: local version changed {local_version} != {expected_version}"
        )

    _, parent_obj = get_json(f"{LOCAL_BASE}/api/groups/{group_id}/items/{parent_key}")
    if not isinstance(parent_obj, dict) or not isinstance(parent_obj.get("data"), dict):
        raise RuntimeError(f"{parent_key}: malformed local parent response")
    parent_data = parent_obj["data"]
    if parent_data.get("deleted"):
        raise RuntimeError(f"{note_key}: parent {parent_key} is deleted")
    collections = parent_data.get("collections")
    if not isinstance(collections, list) or collection_key not in collections:
        raise RuntimeError(
            f"{note_key}: parent {parent_key} is not in collection {collection_key}"
        )

    new_path = Path(str(entry["new_path"])).expanduser().resolve()
    new_html = new_path.read_text(encoding="utf-8")
    new_sha = sha256_text(new_html)
    if new_sha != entry.get("new_sha256"):
        raise RuntimeError(
            f"{note_key}: staged note hash changed {new_sha} != {entry.get('new_sha256')}"
        )
    errors, warnings, summary = validate_note(new_html)
    if errors:
        raise RuntimeError(f"{note_key}: staged note validation failed: {errors}")
    local = {
        "note_key": note_key,
        "parent_key": parent_key,
        "group_id": group_id,
        "local_version": local_version,
        "old_sha256": observed_sha,
        "new_sha256": new_sha,
        "new_path": str(new_path),
        "new_html": new_html,
        "validation_warnings": warnings,
        "validation_summary": summary,
        "old_html": observed_note,
        "pdf_path": str(entry["pdf_path"]),
        "pdf_sha256": str(entry["pdf_sha256"]),
        "pdf_attachment_key": str(entry["pdf_attachment_key"]),
    }
    verify_local_source_contract(local)
    return local


def web_headers(api_key: str) -> dict[str, str]:
    return {
        "Zotero-API-Key": api_key,
        "Zotero-API-Version": "3",
    }


def verify_web_key_access(api_key: str, group_id: int) -> dict[str, object]:
    _, key_obj = get_json(
        f"{WEB_BASE}/keys/current",
        headers=web_headers(api_key),
    )
    if not isinstance(key_obj, dict):
        raise RuntimeError("Web API key access response is malformed")
    access = key_obj.get("access")
    groups = access.get("groups") if isinstance(access, dict) else None
    if not isinstance(groups, dict):
        raise RuntimeError("Web API key has no group access")
    exact_access = groups.get(str(group_id))
    group_access = exact_access if isinstance(exact_access, dict) else groups.get("all")
    if not isinstance(group_access, dict):
        raise RuntimeError(f"Web API key has no access to group {group_id}")
    if group_access.get("library") is not True:
        raise RuntimeError(f"Web API key cannot read group {group_id}")
    if group_access.get("write") is not True:
        raise RuntimeError(f"Web API key cannot write group {group_id}")
    return {
        "group_id": group_id,
        "library": True,
        "write": True,
    }


def verify_remote_entry(
    group_id: int,
    collection_key: str,
    local: dict[str, object],
    api_key: str,
) -> dict[str, object]:
    note_key = str(local["note_key"])
    headers, note_obj = get_json(
        f"{WEB_BASE}/groups/{group_id}/items/{note_key}",
        headers=web_headers(api_key),
    )
    if not isinstance(note_obj, dict) or not isinstance(note_obj.get("data"), dict):
        raise RuntimeError(f"{note_key}: malformed remote note response")
    note_data = note_obj["data"]
    if note_data.get("itemType") != "note":
        raise RuntimeError(f"{note_key}: remote target is not a note")
    if note_data.get("deleted"):
        raise RuntimeError(f"{note_key}: remote target note is deleted")
    if note_data.get("parentItem") != local["parent_key"]:
        raise RuntimeError(f"{note_key}: remote parent differs from approved parent")
    remote_sha = sha256_text(str(note_data.get("note") or ""))
    if remote_sha != local["old_sha256"]:
        raise RuntimeError(
            f"{note_key}: remote/local old note conflict {remote_sha} != {local['old_sha256']}"
        )

    _, parent_obj = get_json(
        f"{WEB_BASE}/groups/{group_id}/items/{local['parent_key']}",
        headers=web_headers(api_key),
    )
    if not isinstance(parent_obj, dict) or not isinstance(parent_obj.get("data"), dict):
        raise RuntimeError(f"{note_key}: malformed remote parent response")
    parent_data = parent_obj["data"]
    if parent_data.get("deleted"):
        raise RuntimeError(f"{note_key}: remote parent is deleted")
    collections = parent_data.get("collections")
    if not isinstance(collections, list) or collection_key not in collections:
        raise RuntimeError(f"{note_key}: remote parent is outside approved collection")

    remote_version = parse_version(
        note_key,
        source="remote note",
        json_version=note_obj.get("version"),
        headers=headers,
    )
    if note_data.get("version") is not None:
        data_version = parse_version(
            note_key,
            source="remote note data",
            json_version=note_data.get("version"),
        )
        if data_version != remote_version:
            raise RuntimeError(
                f"{note_key}: remote version mismatch: "
                f"top={remote_version}, data={data_version}"
            )
    return {
        "version": remote_version,
        "old_html": str(note_data.get("note") or ""),
        "old_sha256": remote_sha,
    }


def preflight_web_route(
    group_id: int,
    collection_key: str,
    locals_verified: list[dict[str, object]],
    api_key: str,
) -> tuple[dict[str, object], dict[str, dict[str, object]]]:
    key_access = verify_web_key_access(api_key, group_id)
    remote_entries: dict[str, dict[str, object]] = {}
    for local in locals_verified:
        note_key = str(local["note_key"])
        remote_entries[note_key] = verify_remote_entry(
            group_id,
            collection_key,
            local,
            api_key,
        )
    return key_access, remote_entries


def patch_remote_note(
    group_id: int,
    local: dict[str, object],
    remote: dict[str, object],
    api_key: str,
    collection_key: str,
    *,
    target_contract: dict[str, Any] | None = None,
    pre_patch_contract_check: Callable[[dict[str, Any]], object] | None = None,
    post_patch_contract_check: Callable[[dict[str, Any]], object] | None = None,
    source_contract_check: Callable[[], object] | None = None,
) -> dict[str, object]:
    note_key = str(local["note_key"])
    headers = web_headers(api_key)
    headers["If-Unmodified-Since-Version"] = str(remote["version"])
    _run_contract_guard(
        "pre_patch",
        target_contract,
        pre_patch_contract_check,
    )
    if source_contract_check is not None:
        source_contract_check()
    try:
        status, _, body = request(
            f"{WEB_BASE}/groups/{group_id}/items/{note_key}",
            method="PATCH",
            headers=headers,
            payload={"note": local["new_html"]},
        )
    except Exception as exc:
        try:
            remote_version, remote_readback_sha = verify_item_readback(
                note_key,
                get_item=lambda: get_json(
                    f"{WEB_BASE}/groups/{group_id}/items/{note_key}",
                    headers=web_headers(api_key),
                ),
                get_parent=lambda parent_key: get_json(
                    f"{WEB_BASE}/groups/{group_id}/items/{parent_key}",
                    headers=web_headers(api_key),
                ),
                expected_parent_key=str(local["parent_key"]),
                expected_collection_key=collection_key,
                expected_new_sha256=str(local["new_sha256"]),
                previous_version=int(remote["version"]),
                source="remote",
            )
        except Exception as readback_exc:
            raise MutationOutcomeUnknown(
                note_key=note_key,
                parent_key=str(local["parent_key"]),
                reason=(
                    f"patch request failed with transport error: {exc}; "
                    f"readback check failed: {readback_exc}"
                ),
            ) from exc

        try:
            _run_contract_guard(
                "post_patch",
                target_contract,
                post_patch_contract_check,
            )
        except Exception as contract_exc:
            raise MutationAcceptedButUnverified(
                note_key=note_key,
                parent_key=str(local["parent_key"]),
                reason=f"post-patch contract changed: {contract_exc}",
            ) from exc

        return {
            "remote_version": remote_version,
            "remote_readback_sha256": remote_readback_sha,
            "remote_verified": True,
        }
    if status == 412:
        raise RuntimeError(f"{note_key}: HTTP 412 concurrent modification; stopped")
    if status != 204:
        detail = body.decode("utf-8", errors="replace")[:300]
        if 400 <= status < 500:
            raise RuntimeError(f"{note_key}: PATCH returned HTTP {status}: {detail}")
        try:
            remote_version, remote_readback_sha = verify_item_readback(
                note_key,
                get_item=lambda: get_json(
                    f"{WEB_BASE}/groups/{group_id}/items/{note_key}",
                    headers=web_headers(api_key),
                ),
                get_parent=lambda parent_key: get_json(
                    f"{WEB_BASE}/groups/{group_id}/items/{parent_key}",
                    headers=web_headers(api_key),
                ),
                expected_parent_key=str(local["parent_key"]),
                expected_collection_key=collection_key,
                expected_new_sha256=str(local["new_sha256"]),
                previous_version=int(remote["version"]),
                source="remote",
            )
        except Exception as readback_exc:
            raise MutationOutcomeUnknown(
                note_key=note_key,
                parent_key=str(local["parent_key"]),
                reason=(
                    f"PATCH returned uncertain HTTP {status}: {detail}; "
                    f"readback check failed: {readback_exc}"
                ),
            ) from readback_exc
        try:
            _run_contract_guard(
                "post_patch",
                target_contract,
                post_patch_contract_check,
            )
        except Exception as contract_exc:
            raise MutationAcceptedButUnverified(
                note_key=note_key,
                parent_key=str(local["parent_key"]),
                reason=f"post-patch contract changed: {contract_exc}",
            ) from contract_exc
        return {
            "remote_version": remote_version,
            "remote_readback_sha256": remote_readback_sha,
            "remote_verified": True,
        }
    try:
        remote_version, remote_readback_sha = verify_item_readback(
            note_key,
            get_item=lambda: get_json(
                f"{WEB_BASE}/groups/{group_id}/items/{note_key}",
                headers=web_headers(api_key),
            ),
            get_parent=lambda parent_key: get_json(
                f"{WEB_BASE}/groups/{group_id}/items/{parent_key}",
                headers=web_headers(api_key),
            ),
            expected_parent_key=str(local["parent_key"]),
            expected_collection_key=collection_key,
            expected_new_sha256=str(local["new_sha256"]),
            previous_version=int(remote["version"]),
            source="remote",
        )
    except MutationAcceptedButUnverified:
        raise
    except Exception as exc:
        raise MutationAcceptedButUnverified(
            note_key=note_key,
            parent_key=str(local["parent_key"]),
            reason=str(exc),
        ) from exc
    try:
        _run_contract_guard(
            "post_patch",
            target_contract,
            post_patch_contract_check,
        )
    except Exception as exc:
        raise MutationAcceptedButUnverified(
            note_key=note_key,
            parent_key=str(local["parent_key"]),
            reason=f"post-patch contract changed: {exc}",
        ) from exc
    return {
        "remote_version": remote_version,
        "remote_readback_sha256": remote_readback_sha,
        "remote_verified": True,
    }


def patch_local_note(
    group_id: int,
    local: dict[str, object],
    api_key: str,
    server_id: str,
    collection_key: str,
    *,
    target_contract: dict[str, Any] | None = None,
    pre_patch_contract_check: Callable[[dict[str, Any]], object] | None = None,
    post_patch_contract_check: Callable[[dict[str, Any]], object] | None = None,
    source_contract_check: Callable[[], object] | None = None,
) -> dict[str, object]:
    note_key = str(local["note_key"])
    _run_contract_guard(
        "pre_patch",
        target_contract,
        pre_patch_contract_check,
    )
    if source_contract_check is not None:
        source_contract_check()
    headers = local_headers(api_key, server_id)
    headers["If-Unmodified-Since-Version"] = str(local["local_version"])
    try:
        status, _, body = request(
            f"{LOCAL_BASE}/api/groups/{group_id}/items/{note_key}",
            method="PATCH",
            headers=headers,
            payload={"note": local["new_html"]},
        )
    except Exception as exc:
        try:
            local_version, local_readback_sha = verify_item_readback(
                note_key,
                get_item=lambda: get_json(
                    f"{LOCAL_BASE}/api/groups/{group_id}/items/{note_key}"
                ),
                get_parent=lambda parent_key: get_json(
                    f"{LOCAL_BASE}/api/groups/{group_id}/items/{parent_key}"
                ),
                expected_parent_key=str(local["parent_key"]),
                expected_collection_key=collection_key,
                expected_new_sha256=str(local["new_sha256"]),
                previous_version=int(local["local_version"]),
                source="local",
            )
        except Exception as readback_exc:
            raise MutationOutcomeUnknown(
                note_key=note_key,
                parent_key=str(local["parent_key"]),
                reason=(
                    f"patch request failed with transport error: {exc}; "
                    f"readback check failed: {readback_exc}"
                ),
            ) from exc

        try:
            _run_contract_guard(
                "post_patch",
                target_contract,
                post_patch_contract_check,
            )
        except Exception as contract_exc:
            raise MutationAcceptedButUnverified(
                note_key=note_key,
                parent_key=str(local["parent_key"]),
                reason=f"post-patch contract changed: {contract_exc}",
            ) from exc

        return {
            "local_version": local_version,
            "local_readback_sha256": local_readback_sha,
            "local_verified": True,
        }
    if status == 412:
        raise RuntimeError(f"{note_key}: HTTP 412 concurrent modification; stopped")
    if status == 401:
        raise RuntimeError(
            f"{note_key}: local key was rejected or already consumed; stopped"
        )
    if status != 204:
        detail = body.decode("utf-8", errors="replace")[:300]
        if 400 <= status < 500:
            raise RuntimeError(
                f"{note_key}: local PATCH returned HTTP {status}: {detail}"
            )
        try:
            local_version, local_readback_sha = verify_item_readback(
                note_key,
                get_item=lambda: get_json(
                    f"{LOCAL_BASE}/api/groups/{group_id}/items/{note_key}"
                ),
                get_parent=lambda parent_key: get_json(
                    f"{LOCAL_BASE}/api/groups/{group_id}/items/{parent_key}"
                ),
                expected_parent_key=str(local["parent_key"]),
                expected_collection_key=collection_key,
                expected_new_sha256=str(local["new_sha256"]),
                previous_version=int(local["local_version"]),
                source="local",
            )
        except Exception as readback_exc:
            raise MutationOutcomeUnknown(
                note_key=note_key,
                parent_key=str(local["parent_key"]),
                reason=(
                    f"local PATCH returned uncertain HTTP {status}: {detail}; "
                    f"readback check failed: {readback_exc}"
                ),
            ) from readback_exc
        try:
            _run_contract_guard(
                "post_patch",
                target_contract,
                post_patch_contract_check,
            )
        except Exception as contract_exc:
            raise MutationAcceptedButUnverified(
                note_key=note_key,
                parent_key=str(local["parent_key"]),
                reason=f"post-patch contract changed: {contract_exc}",
            ) from contract_exc
        return {
            "local_version": local_version,
            "local_readback_sha256": local_readback_sha,
            "local_verified": True,
        }

    try:
        local_version, local_readback_sha = verify_item_readback(
            note_key,
            get_item=lambda: get_json(
                f"{LOCAL_BASE}/api/groups/{group_id}/items/{note_key}"
            ),
            get_parent=lambda parent_key: get_json(
                f"{LOCAL_BASE}/api/groups/{group_id}/items/{parent_key}"
            ),
            expected_parent_key=str(local["parent_key"]),
            expected_collection_key=collection_key,
            expected_new_sha256=str(local["new_sha256"]),
            previous_version=int(local["local_version"]),
            source="local",
        )
    except MutationAcceptedButUnverified:
        raise
    except Exception as exc:
        raise MutationAcceptedButUnverified(
            note_key=note_key,
            parent_key=str(local["parent_key"]),
            reason=str(exc),
        ) from exc
    try:
        _run_contract_guard(
            "post_patch",
            target_contract,
            post_patch_contract_check,
        )
    except Exception as exc:
        raise MutationAcceptedButUnverified(
            note_key=note_key,
            parent_key=str(local["parent_key"]),
            reason=f"post-patch contract changed: {exc}",
        ) from exc
    return {
        "local_version": local_version,
        "local_readback_sha256": local_readback_sha,
        "local_verified": True,
    }


def backup_note(
    backup_dir: Path,
    note_key: str,
    version: int,
    old_html: str,
) -> str:
    backup_dir.mkdir(parents=True, exist_ok=True)
    digest = sha256_text(old_html)
    path = backup_dir / f"{note_key}.v{version}.{digest[:12]}.html"
    if path.exists():
        if sha256_text(path.read_text(encoding="utf-8")) != digest:
            raise RuntimeError(f"backup collision: {path}")
    else:
        path.write_text(old_html, encoding="utf-8")
    return str(path)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--note-key", action="append", default=[])
    parser.add_argument(
        "--route",
        choices=("auto", "local", "web"),
        default="auto",
    )
    parser.add_argument("--api-key-env", default="ZOTERO_API_KEY")
    parser.add_argument("--backup-dir", type=Path)
    parser.add_argument("--yes", action="store_true")
    parser.add_argument(
        "--confirm-explicit-api-target",
        action="store_true",
        help=(
            "confirm that manifest group_id/collection_key, not the Desktop "
            "local collection ID, is the authoritative HTTP/Web write target"
        ),
    )
    parser.add_argument("--json", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    manifest_path = args.manifest.expanduser().resolve()
    try:
        target, entries = load_entries(manifest_path, set(args.note_key))
        contract_entries = list(target.get("_entries_for_inventory", entries))
        target_contract = resolve_target_contract(target)
        group_id = int(target_contract["group_id"])
        collection_key = str(target_contract["collection_key"])
        collection_name = str(target_contract["collection_name"])
        selected = selected_target()
        verify_target_match(selected, target_contract)
        api_collection_contract = verify_explicit_api_collection_contract(
            target_contract,
        )
        locals_verified = [
            verify_local_entry(group_id, collection_key, entry) for entry in entries
        ]
        capability = probe_local_write()
    except Exception as exc:
        print(f"preflight failed: {exc}", file=sys.stderr)
        return EXIT_CONFLICT

    web_api_key = os.environ.get(args.api_key_env, "")
    route = choose_route(
        args.route,
        local_supported=bool(capability["supported"]),
        web_key_present=bool(web_api_key),
    )

    def _make_invariant_contract_checker(
        *,
        base_api: str,
        collection_route: str = "/api/groups",
        headers: dict[str, str] | None = None,
    ) -> Callable[[dict[str, Any]], None]:
        def _checker(_: dict[str, Any]) -> None:
            verify_explicit_api_collection_contract(
                target_contract,
                base_api=base_api,
                collection_route=collection_route,
                headers=headers,
            )
            verify_inventory_contract(
                base_api=base_api,
                group_id=group_id,
                collection_key=collection_key,
                entries=contract_entries,
                headers=headers,
                group_route=collection_route,
            )

        return _checker

    local_contract_checker = _make_invariant_contract_checker(
        base_api=LOCAL_BASE,
    )
    web_contract_checker = _make_invariant_contract_checker(
        base_api=WEB_BASE,
        collection_route="/groups",
        headers=(web_headers(web_api_key) if web_api_key else None),
    )

    def web_and_local_contract_checker(contract: dict[str, Any]) -> None:
        local_contract_checker(contract)
        web_contract_checker(contract)

    web_key_access: dict[str, object] | None = None
    web_remote_entries: dict[str, dict[str, object]] = {}
    if route == "local":
        try:
            local_contract_checker(target_contract)
        except Exception as exc:
            print(
                json.dumps(
                    {
                        "status": "preflight_failed",
                        "selected_route": "local",
                        "error": str(exc),
                        "write_performed": False,
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                file=sys.stderr,
            )
            return EXIT_CONFLICT
    if route == "web":
        try:
            local_contract_checker(target_contract)
            web_key_access, web_remote_entries = preflight_web_route(
                group_id,
                collection_key,
                locals_verified,
                web_api_key,
            )
            web_contract_checker(target_contract)
        except Exception as exc:
            print(
                json.dumps(
                    {
                        "status": "preflight_failed",
                        "selected_route": "web",
                        "error": str(exc),
                        "write_performed": False,
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                file=sys.stderr,
            )
            return EXIT_CONFLICT
    public_capability = {
        key: value
        for key, value in capability.items()
        if key != "server_id"
    }
    preview = {
        "mode": "apply" if args.yes else "dry_run",
        "target": {
            "group_id": group_id,
            "collection_key": collection_key,
            "collection_name": collection_name,
        },
        "selected_target": selected,
        "explicit_api_target": {
            **api_collection_contract,
            "connector_local_id_to_collection_key_binding": "not_exposed",
            "apply_confirmation_required": True,
        },
        "local_write_capability": public_capability,
        "selected_route": route,
        "web_write_preflight": {
            "performed": route == "web",
            "key_access": web_key_access,
            "entries_verified": len(web_remote_entries),
        },
        "note_count": len(locals_verified),
        "notes": [
            {
                key: value
                for key, value in item.items()
                if key not in {"new_html", "old_html"}
            }
            for item in locals_verified
        ],
        "write_performed": False,
    }
    if not args.yes:
        if args.json:
            print(json.dumps(preview, ensure_ascii=False, indent=2))
        else:
            print(json.dumps(preview, ensure_ascii=False, indent=2))
        return EXIT_OK if route else EXIT_CAPABILITY

    if not route:
        print(unavailable_route_message(args.route, args.api_key_env), file=sys.stderr)
        return EXIT_CAPABILITY
    if not args.confirm_explicit_api_target:
        print(
            json.dumps(
                {
                    "status": "capability_blocked",
                    "reason": (
                        "Zotero Connector does not expose a verifiable mapping "
                        "from the selected local collection ID to the API "
                        "collection key; approve the manifest group_id and "
                        "collection_key explicitly, then rerun with "
                        "--confirm-explicit-api-target"
                    ),
                    "explicit_api_target": api_collection_contract,
                    "write_performed": False,
                },
                ensure_ascii=False,
                indent=2,
            ),
            file=sys.stderr,
        )
        return EXIT_CAPABILITY

    if args.yes:
        try:
            if route == "local":
                local_contract_checker(target_contract)
            elif route == "web":
                web_and_local_contract_checker(target_contract)
        except Exception as exc:
            print(
                json.dumps(
                    {
                        "status": "preflight_failed",
                        "selected_route": route,
                        "error": str(exc),
                        "write_performed": False,
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                file=sys.stderr,
            )
            return EXIT_CONFLICT

    results: list[dict[str, object]] = []
    current_backup: str | None = None
    try:
        backup_dir = (
            args.backup_dir.expanduser().resolve()
            if args.backup_dir
            else manifest_path.parent / f"{route}_api_backups"
        )
        planned_updates: list[tuple[dict[str, object], str, dict[str, object] | None]] = []
        if route == "local":
            for local in locals_verified:
                current_backup = backup_note(
                    backup_dir,
                    str(local["note_key"]),
                    int(local["local_version"]),
                    str(local["old_html"]),
                )
                planned_updates.append(
                    (
                        local,
                        current_backup,
                        None,
                    )
                )
        else:
            for local in locals_verified:
                remote = web_remote_entries[str(local["note_key"])]
                planned_updates.append(
                    (
                        local,
                        backup_note(
                            backup_dir,
                            str(local["note_key"]),
                            int(remote["version"]),
                            str(remote["old_html"]),
                        ),
                        remote,
                    )
                )
        if route == "local":
            server_id = capability.get("server_id")
            if not isinstance(server_id, str) or not server_id:
                raise RuntimeError("local route selected without a server ID")
            authorization = authorize_local(
                server_id,
                "deep-research Zotero note migrator",
            )
            local_api_key = str(authorization["api_key"])
            if len(locals_verified) > 1 and not authorization["remember"]:
                raise RuntimeError(
                    "batch update requires choosing 'Always Allow' in Zotero; "
                    "no notes were changed"
                )
            for local, backup, _ in planned_updates:
                current_backup = backup
                result = patch_local_note(
                    group_id,
                    local,
                    local_api_key,
                    server_id,
                    collection_key,
                    target_contract=target_contract,
                    pre_patch_contract_check=local_contract_checker,
                    post_patch_contract_check=local_contract_checker,
                    source_contract_check=lambda local=local: (
                        verify_local_source_contract(local)
                    ),
                )
                results.append(
                    {
                        "note_key": local["note_key"],
                        "parent_key": local["parent_key"],
                        "backup": backup,
                        **result,
                    }
                )
        else:
            for local, backup, remote in planned_updates:
                current_backup = backup
                result = patch_remote_note(
                    group_id,
                    local,
                    remote,
                    web_api_key,
                    collection_key,
                    target_contract=target_contract,
                    pre_patch_contract_check=web_and_local_contract_checker,
                    post_patch_contract_check=web_and_local_contract_checker,
                    source_contract_check=lambda local=local: (
                        verify_local_source_contract(local)
                    ),
                )
                results.append(
                    {
                        "note_key": local["note_key"],
                        "parent_key": local["parent_key"],
                        "backup": backup,
                        **result,
                    }
                )
    except MutationAcceptedButUnverified as exc:
        print(
            json.dumps(
                {
                    "status": "partial_failure",
                    "completed": results,
                    "accepted_but_unverified": {
                        "note_key": exc.note_key,
                        "parent_key": exc.parent_key,
                        "backup": current_backup,
                    },
                    "error": str(exc),
                    "write_performed": True,
                    "stopped": True,
                },
                ensure_ascii=False,
                indent=2,
            ),
            file=sys.stderr,
        )
        return EXIT_CONFLICT
    except MutationOutcomeUnknown as exc:
        print(
            json.dumps(
                {
                    "status": "partial_failure",
                    "completed": results,
                    "outcome_unknown": {
                        "note_key": exc.note_key,
                        "parent_key": exc.parent_key,
                        "backup": current_backup,
                    },
                    "error": str(exc),
                    "write_performed": None,
                    "stopped": True,
                },
                ensure_ascii=False,
                indent=2,
            ),
            file=sys.stderr,
        )
        return EXIT_CONFLICT
    except Exception as exc:
        print(
            json.dumps(
                {
                    "status": "partial_failure" if results else "failed",
                    "completed": results,
                    "error": str(exc),
                    "write_performed": bool(results),
                    "stopped": True,
                },
                ensure_ascii=False,
                indent=2,
            ),
            file=sys.stderr,
        )
        return EXIT_CONFLICT

    report = {
        **preview,
        "write_performed": True,
        "completed_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "results": results,
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
