#!/usr/bin/env python3
"""Import one verified parent/PDF/note bundle through Zotero Connector.

The command is dry-run unless --yes is supplied. It refuses target mismatches
and library-wide duplicates, then reads the created parent and children back.

Exit codes:
  0 dry-run or fully verified import
  1 invalid bundle or local artifact
  2 Zotero/API connectivity or parse failure
  3 selected-target mismatch
  4 duplicate/conflict
  5 write succeeded partially or readback failed
"""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

from verify_note_html import validate_note


EXIT_OK = 0
EXIT_VALIDATION = 1
EXIT_IO = 2
EXIT_TARGET = 3
EXIT_DUPLICATE = 4
EXIT_PARTIAL = 5
BASE_URL = os.environ.get("ZOTERO_LOCAL_BASE_URL", "http://127.0.0.1:23119").rstrip("/")


class BundleError(RuntimeError):
    def __init__(self, message: str, code: int = EXIT_VALIDATION):
        super().__init__(message)
        self.code = code


def sha256sum(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def request_json(
    path: str,
    *,
    method: str = "GET",
    payload: Any = None,
    headers: dict[str, str] | None = None,
    raw_body: bytes | None = None,
    timeout: float = 15.0,
) -> tuple[int, Any]:
    request_headers = dict(headers or {})
    if path.startswith("/api/"):
        request_headers.setdefault("Zotero-API-Version", "3")
    if path.startswith("/connector/"):
        request_headers.setdefault("X-Zotero-Connector-API-Version", "3")

    body = raw_body
    if payload is not None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        request_headers.setdefault("Content-Type", "application/json")

    req = urllib.request.Request(
        BASE_URL + path,
        data=body,
        method=method,
        headers=request_headers,
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            raw = response.read()
            content_type = response.headers.get("Content-Type", "")
            if "json" in content_type and raw:
                return response.status, json.loads(raw.decode("utf-8"))
            return response.status, raw.decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise BundleError(
            f"{method} {path} failed: HTTP {exc.code}: {detail[:500]}",
            EXIT_IO,
        ) from exc
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        raise BundleError(f"{method} {path} failed: {exc}", EXIT_IO) from exc


def api_get(path: str) -> Any:
    status, payload = request_json(path)
    if status != 200:
        raise BundleError(f"GET {path} returned {status}", EXIT_IO)
    return payload


def collection_path(group_id: int, key: str) -> list[str]:
    names: list[str] = []
    seen: set[str] = set()
    current: str | bool = key
    while current:
        current_key = str(current)
        if current_key in seen:
            raise BundleError("collection parent cycle detected", EXIT_IO)
        seen.add(current_key)
        encoded = urllib.parse.quote(current_key)
        record = api_get(f"/api/groups/{group_id}/collections/{encoded}?format=json")
        data = record.get("data") if isinstance(record, dict) else None
        if not isinstance(data, dict) or not data.get("name"):
            raise BundleError(f"invalid collection record for {current_key}", EXIT_IO)
        names.append(str(data["name"]))
        current = data.get("parentCollection") or False
    return list(reversed(names))


def selected_target() -> dict[str, Any]:
    status, payload = request_json(
        "/connector/getSelectedCollection",
        method="POST",
        payload={},
    )
    if status != 200 or not isinstance(payload, dict):
        raise BundleError("could not read selected Zotero target", EXIT_IO)
    return payload


def normalize_doi(value: object) -> str:
    if not isinstance(value, str):
        return ""
    value = value.strip().lower()
    value = re.sub(r"^https?://(?:dx\.)?doi\.org/", "", value)
    return value


def normalize_title(value: object) -> str:
    if not isinstance(value, str):
        return ""
    return re.sub(r"\W+", "", value, flags=re.UNICODE).casefold()


def query_top_items(group_id: int, query_text: str) -> list[dict[str, Any]]:
    query = urllib.parse.urlencode(
        {
            "q": query_text,
            "qmode": "titleCreatorYear",
            "limit": "100",
            "format": "json",
        }
    )
    payload = api_get(f"/api/groups/{group_id}/items/top?{query}")
    return payload if isinstance(payload, list) else []


def exact_matches(group_id: int, item: dict[str, Any]) -> list[dict[str, Any]]:
    doi = normalize_doi(item.get("DOI"))
    title = normalize_title(item.get("title"))
    date = str(item.get("date") or "")
    year_match = re.search(r"\b(?:19|20)\d{2}\b", date)
    year = year_match.group(0) if year_match else ""

    candidates: dict[str, dict[str, Any]] = {}
    for query_text in [doi, str(item.get("title") or "")]:
        if not query_text:
            continue
        for candidate in query_top_items(group_id, query_text):
            if isinstance(candidate, dict) and candidate.get("key"):
                candidates[str(candidate["key"])] = candidate

    matches: list[dict[str, Any]] = []
    for candidate in candidates.values():
        data = candidate.get("data", {})
        candidate_doi = normalize_doi(data.get("DOI"))
        if doi and candidate_doi == doi:
            matches.append(candidate)
            continue
        candidate_title = normalize_title(data.get("title"))
        candidate_year_match = re.search(r"\b(?:19|20)\d{2}\b", str(data.get("date") or ""))
        candidate_year = candidate_year_match.group(0) if candidate_year_match else ""
        if title and candidate_title == title and (not year or not candidate_year or year == candidate_year):
            matches.append(candidate)
    return matches


def require_hash(path: Path, declared: object, label: str) -> str:
    if not path.is_file():
        raise BundleError(f"{label} is not a file: {path}")
    actual = sha256sum(path)
    if not isinstance(declared, str) or not re.fullmatch(r"[0-9a-fA-F]{64}", declared):
        raise BundleError(f"{label} requires a 64-hex sha256")
    if actual.lower() != declared.lower():
        raise BundleError(f"{label} sha256 mismatch: declared={declared} actual={actual}")
    return actual


def normalize_note(value: str) -> str:
    value = html.unescape(value)
    value = re.sub(r"\s+data-schema-version=[\"'][^\"']+[\"']", "", value)
    value = re.sub(r">\s+<", "><", value)
    return re.sub(r"\s+", " ", value).strip()


class _RootAccessLevelParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.seen_root = False
        self.access_level: str | None = None

    def handle_starttag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        if self.seen_root:
            return
        self.seen_root = True
        values = {key.lower(): value or "" for key, value in attrs}
        if tag.lower() == "div":
            self.access_level = values.get("data-access-level", "").strip().lower() or None


def note_root_access_level(note_html: str) -> str | None:
    parser = _RootAccessLevelParser()
    parser.feed(note_html)
    parser.close()
    return parser.access_level


def load_and_validate(
    bundle_path: Path,
) -> tuple[dict[str, Any], Path | None, Path, str | None]:
    try:
        bundle = json.loads(bundle_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise BundleError(f"cannot read bundle: {exc}", EXIT_VALIDATION) from exc
    if not isinstance(bundle, dict):
        raise BundleError("bundle root must be an object")

    source_id = bundle.get("source_id")
    target = bundle.get("target")
    item = bundle.get("item")
    pdf = bundle.get("pdf")
    note = bundle.get("note")
    if not isinstance(source_id, str) or not source_id.strip():
        raise BundleError("source_id must be a non-empty string")
    if not all(isinstance(value, dict) for value in (target, item, note)):
        raise BundleError("target, item, and note must be objects")
    if not item.get("title") or not (item.get("DOI") or item.get("url")):
        raise BundleError("item requires title and DOI or URL")

    access_level = bundle.get("access_level", "full_text")
    if access_level not in {"full_text", "metadata_only"}:
        raise BundleError("access_level must be full_text or metadata_only")
    pdf_path: Path | None = None
    pdf_hash: str | None = None
    if access_level == "full_text":
        if not isinstance(pdf, dict):
            raise BundleError("full_text bundle requires pdf object")
        pdf_path = Path(str(pdf.get("local_path") or "")).expanduser().resolve()
        pdf_hash = require_hash(pdf_path, pdf.get("sha256"), "pdf")
        with pdf_path.open("rb") as handle:
            if b"%PDF-" not in handle.read(1024):
                raise BundleError("pdf has no %PDF- signature in its first 1024 bytes")
    else:
        if pdf not in (None, {}):
            raise BundleError("metadata_only bundle must not declare a PDF")
        reason = bundle.get("metadata_only_reason")
        if not isinstance(reason, str) or not reason.strip():
            raise BundleError("metadata_only bundle requires metadata_only_reason")

    note_path = Path(str(note.get("html_path") or "")).expanduser().resolve()
    require_hash(note_path, note.get("sha256"), "note")
    try:
        note_html = note_path.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        raise BundleError("note must be UTF-8") from exc
    if not note_html.strip():
        raise BundleError("note is empty")
    note_errors, _, note_summary = validate_note(note_html)
    if note_errors:
        raise BundleError(f"note HTML contract failed: {note_errors}")
    if not isinstance(note_summary, dict):
        raise BundleError("note HTML validator returned no access-level summary")
    root_access_level = note_root_access_level(note_html)
    summary_access_level = note_summary.get("access_level")
    summary_projection = note_summary.get("note_projection")
    if access_level == "metadata_only":
        if (
            root_access_level != "metadata_only"
            or summary_access_level != "metadata_only"
            or summary_projection != "metadata_only"
        ):
            raise BundleError(
                "bundle access_level=metadata_only does not match the note's "
                "root data-access-level and validated projection"
            )
    elif root_access_level not in (None, "full_text") or summary_access_level not in (
        None,
        "full_text",
    ):
        raise BundleError(
            "bundle access_level=full_text conflicts with the note's "
            "root data-access-level or validated projection"
        )

    return bundle, pdf_path, note_path, pdf_hash


def verify_target(target: dict[str, Any]) -> tuple[int, str, list[str], dict[str, Any]]:
    try:
        group_id = int(target["group_id"])
        expected_library_id = int(target["library_id"])
        collection_key = str(target["collection_key"])
        expected_library = str(target["library_name"])
        expected_path = [str(part) for part in target["collection_path"]]
    except (KeyError, TypeError, ValueError) as exc:
        raise BundleError(f"invalid target contract: {exc}") from exc

    actual_path = collection_path(group_id, collection_key)
    if actual_path != expected_path:
        raise BundleError(
            f"collection path mismatch: expected={expected_path} actual={actual_path}",
            EXIT_TARGET,
        )

    selected = selected_target()
    if (
        selected.get("libraryName") != expected_library
        or selected.get("libraryID") != expected_library_id
        or selected.get("name") != expected_path[-1]
        or not selected.get("editable")
        or not selected.get("filesEditable")
    ):
        raise BundleError(
            "selected target mismatch or not editable: "
            f"expected={expected_library}/{expected_path[-1]} "
            f"actual={selected.get('libraryName')}/{selected.get('name')} "
            f"editable={selected.get('editable')} filesEditable={selected.get('filesEditable')}",
            EXIT_TARGET,
        )
    return group_id, collection_key, actual_path, selected


def poll_new_parent(group_id: int, item: dict[str, Any], timeout: float = 10.0) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        matches = exact_matches(group_id, item)
        if len(matches) == 1:
            return matches[0]
        time.sleep(0.25)
    raise BundleError("parent item was not uniquely found during readback", EXIT_PARTIAL)


def import_bundle(
    bundle: dict[str, Any],
    pdf_path: Path | None,
    pdf_hash: str | None,
    *,
    group_id: int,
    collection_key: str,
    storage_root: Path | None,
) -> dict[str, Any]:
    source_id = str(bundle["source_id"])
    item = dict(bundle["item"])
    note_record = bundle["note"]
    note_html = Path(str(note_record["html_path"])).expanduser().resolve().read_text(
        encoding="utf-8"
    )
    item["id"] = source_id
    item["notes"] = [{"note": note_html}]
    item["attachments"] = []

    session_id = f"deep-research-{uuid.uuid4().hex}"
    save_payload = {
        "sessionID": session_id,
        "uri": item.get("url") or f"https://doi.org/{normalize_doi(item.get('DOI'))}",
        "items": [item],
    }
    status, _ = request_json(
        "/connector/saveItems",
        method="POST",
        payload=save_payload,
        timeout=30.0,
    )
    if status != 201:
        raise BundleError(f"saveItems returned {status}", EXIT_PARTIAL)

    if pdf_path is not None:
        if pdf_hash is None:
            raise BundleError("full-text import is missing its validated PDF hash")
        pdf_record = bundle["pdf"]
        attachment_metadata = {
            "sessionID": session_id,
            "parentItemID": source_id,
            "title": pdf_record.get("title") or "Full Text PDF",
            "url": pdf_record.get("source_url") or item.get("url") or "",
        }
        metadata_header = json.dumps(attachment_metadata, ensure_ascii=False)
        status, _ = request_json(
            "/connector/saveAttachment",
            method="POST",
            raw_body=pdf_path.read_bytes(),
            headers={
                "Content-Type": "application/pdf",
                "X-Metadata": metadata_header,
            },
            timeout=60.0,
        )
        if status != 201:
            raise BundleError(
                f"parent was created but saveAttachment returned {status}",
                EXIT_PARTIAL,
            )

    parent = poll_new_parent(group_id, item)
    parent_data = parent.get("data", {})
    if collection_key not in parent_data.get("collections", []):
        raise BundleError(
            f"parent created outside approved collection: {parent_data.get('collections')}",
            EXIT_PARTIAL,
        )

    parent_key = str(parent["key"])
    encoded_key = urllib.parse.quote(parent_key)
    children = api_get(
        f"/api/groups/{group_id}/items/{encoded_key}/children?limit=100&format=json"
    )
    if not isinstance(children, list):
        raise BundleError("children readback was not a list", EXIT_PARTIAL)

    note_matches = [
        child
        for child in children
        if child.get("data", {}).get("itemType") == "note"
        and normalize_note(str(child.get("data", {}).get("note") or ""))
        == normalize_note(note_html)
    ]
    attachment_matches = [
        child
        for child in children
        if child.get("data", {}).get("itemType") == "attachment"
        and child.get("data", {}).get("contentType") == "application/pdf"
    ]
    if len(note_matches) != 1:
        raise BundleError(
            f"expected one matching child note, found {len(note_matches)}",
            EXIT_PARTIAL,
        )
    expected_attachments = 1 if pdf_path is not None else 0
    if len(attachment_matches) != expected_attachments:
        raise BundleError(
            f"expected {expected_attachments} PDF attachment(s), "
            f"found {len(attachment_matches)}",
            EXIT_PARTIAL,
        )

    attachment = attachment_matches[0] if attachment_matches else None
    stored_hash: str | None = None
    stored_path: str | None = None
    if storage_root is not None and attachment is not None:
        if pdf_hash is None:
            raise BundleError("stored-file verification is missing source PDF hash")
        attachment_key = str(attachment["key"])
        filename = str(attachment.get("data", {}).get("filename") or "")
        candidate = storage_root / attachment_key / filename
        if not candidate.is_file():
            raise BundleError(f"stored PDF not found at {candidate}", EXIT_PARTIAL)
        stored_hash = sha256sum(candidate)
        stored_path = str(candidate)
        if stored_hash != pdf_hash:
            raise BundleError(
                f"stored PDF hash mismatch: source={pdf_hash} stored={stored_hash}",
                EXIT_PARTIAL,
            )

    return {
        "status": "verified",
        "session_id": session_id,
        "parent_item_key": parent_key,
        "collection_key": collection_key,
        "note_key": note_matches[0]["key"],
        "attachment_key": attachment["key"] if attachment is not None else None,
        "access_level": "full_text" if attachment is not None else "metadata_only",
        "source_pdf_sha256": pdf_hash,
        "stored_pdf_sha256": stored_hash,
        "stored_pdf_path": stored_path,
        "note_comparison": "normalized_html_exact",
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("bundle", type=Path, help="Verified one-item bundle JSON.")
    parser.add_argument(
        "--yes",
        action="store_true",
        help="Perform the Zotero write. Without this flag only validate and preview.",
    )
    parser.add_argument(
        "--storage-root",
        type=Path,
        default=None,
        help="Optional Zotero storage root for stored-file hash readback.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        bundle, pdf_path, note_path, pdf_hash = load_and_validate(
            args.bundle.expanduser().resolve()
        )
        group_id, collection_key, actual_path, selected = verify_target(bundle["target"])
        duplicates = exact_matches(group_id, bundle["item"])
        if duplicates:
            summary = [
                {
                    "key": duplicate.get("key"),
                    "title": duplicate.get("data", {}).get("title"),
                    "DOI": duplicate.get("data", {}).get("DOI"),
                }
                for duplicate in duplicates
            ]
            raise BundleError(f"existing exact match(es): {summary}", EXIT_DUPLICATE)

        preview = {
            "status": "dry_run",
            "source_id": bundle["source_id"],
            "target": {
                "library": selected.get("libraryName"),
                "group_id": group_id,
                "collection_key": collection_key,
                "collection_path": actual_path,
            },
            "item_title": bundle["item"].get("title"),
            "access_level": bundle.get("access_level", "full_text"),
            "pdf_path": str(pdf_path) if pdf_path is not None else None,
            "pdf_sha256": pdf_hash,
            "note_path": str(note_path),
            "side_effects": {
                "parents": 1,
                "pdf_attachments": 1 if pdf_path is not None else 0,
                "child_notes": 1,
            },
        }
        if not args.yes:
            print(json.dumps(preview, ensure_ascii=False, indent=2))
            return EXIT_OK

        storage_root = (
            args.storage_root.expanduser().resolve() if args.storage_root else None
        )
        result = import_bundle(
            bundle,
            pdf_path,
            pdf_hash,
            group_id=group_id,
            collection_key=collection_key,
            storage_root=storage_root,
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return EXIT_OK
    except BundleError as exc:
        print(
            json.dumps(
                {
                    "status": "error",
                    "exit_code": exc.code,
                    "error": str(exc),
                },
                ensure_ascii=False,
                indent=2,
            ),
            file=sys.stderr,
        )
        return exc.code


if __name__ == "__main__":
    raise SystemExit(main())
