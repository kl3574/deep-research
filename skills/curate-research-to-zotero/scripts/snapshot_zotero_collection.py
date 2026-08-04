#!/usr/bin/env python3
"""Export private, read-only ZoteroCorpusSnapshot/v1 metadata."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import sys
from typing import Any
import urllib.error
import urllib.parse
import urllib.request


MAX_RESPONSE_BYTES = 16 * 1024 * 1024
NOTE_SCHEMA_RE = re.compile(r"""data-schema-version=["']([^"']+)["']""")


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


def validate_base_url(value: str) -> str:
    parsed = urllib.parse.urlsplit(value)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("base URL must be HTTP(S)")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("base URL must not contain credentials, query, or fragment")
    if parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
        raise ValueError("only a loopback Zotero API is accepted")
    if parsed.path not in {"", "/", "/api", "/api/"}:
        raise ValueError("base URL path must be empty or /api")
    return urllib.parse.urlunsplit(
        (parsed.scheme, parsed.netloc, "", "", "")
    )


def api_get(
    base_url: str, path: str, params: dict[str, Any] | None = None
) -> Any:
    query = urllib.parse.urlencode(params or {})
    url = base_url + path + ("?" + query if query else "")
    request = urllib.request.Request(
        url, headers={"Accept": "application/json"}, method="GET"
    )
    with urllib.request.urlopen(request, timeout=10) as response:
        payload = response.read(MAX_RESPONSE_BYTES + 1)
    if len(payload) > MAX_RESPONSE_BYTES:
        raise ValueError("Zotero response exceeds size limit")
    return json.loads(payload.decode("utf-8"))


def get_all(base_url: str, path: str) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    start = 0
    while True:
        page = api_get(
            base_url,
            path,
            {"include": "data", "limit": 100, "start": start},
        )
        if not isinstance(page, list):
            raise ValueError(f"{path}: expected array")
        output.extend(item for item in page if isinstance(item, dict))
        if len(page) < 100:
            return output
        start += len(page)


def data_of(item: dict[str, Any]) -> dict[str, Any]:
    data = item.get("data")
    if not isinstance(data, dict):
        raise ValueError("Zotero object lacks data")
    return data


def get_collection_path(
    base_url: str, group_id: int, collection: dict[str, Any]
) -> list[dict[str, Any]]:
    chain: list[dict[str, Any]] = []
    current = collection
    seen: set[str] = set()
    while True:
        data = data_of(current)
        key = str(current.get("key") or data.get("key") or "")
        if not key or key in seen:
            raise ValueError("collection ancestry is missing or cyclic")
        seen.add(key)
        chain.append(
            {
                "key": key,
                "name": str(data.get("name") or ""),
                "version": int(
                    current.get("version") or data.get("version") or 0
                ),
            }
        )
        parent = data.get("parentCollection")
        if not parent:
            return list(reversed(chain))
        current = api_get(
            base_url,
            f"/api/groups/{group_id}/collections/{urllib.parse.quote(str(parent), safe='')}",
            {"include": "data"},
        )
        if not isinstance(current, dict):
            raise ValueError("collection parent is malformed")


def creators_of(value: Any) -> list[dict[str, str]]:
    output: list[dict[str, str]] = []
    for creator in value if isinstance(value, list) else []:
        if not isinstance(creator, dict):
            continue
        item = {
            key: str(creator[key])
            for key in ("creatorType", "firstName", "lastName", "name")
            if creator.get(key)
        }
        if item:
            output.append(item)
    return output


def artifact_role(data: dict[str, Any]) -> str:
    text = " ".join(
        str(data.get(field) or "") for field in ("title", "filename")
    ).lower()
    if (
        "supporting information" in text
        or "supplement" in text
        or re.search(r"\bsi\b", text)
    ):
        return "supporting_information"
    if "accepted manuscript" in text or "author manuscript" in text:
        return "accepted_manuscript"
    if any(term in text for term in ("preprint", "arxiv", "chemrxiv", "biorxiv")):
        return "preprint"
    if str(data.get("contentType") or "").lower() == "application/pdf":
        return "main_text_candidate"
    return "unknown"


def child_record(child: dict[str, Any]) -> dict[str, Any]:
    data = data_of(child)
    item_type = str(data.get("itemType") or "")
    output: dict[str, Any] = {
        "key": str(child.get("key") or data.get("key") or ""),
        "version": int(child.get("version") or data.get("version") or 0),
        "item_type": item_type,
    }
    if item_type == "note":
        match = NOTE_SCHEMA_RE.search(str(data.get("note") or ""))
        output.update(
            {
                "availability": "present",
                "schema_version": match.group(1) if match else None,
            }
        )
    elif item_type == "attachment":
        availability = (
            "local_reference"
            if data.get("path")
            else "remote_reference"
            if data.get("url")
            else "metadata_only"
        )
        output.update(
            {
                "availability": availability,
                "content_type": str(data.get("contentType") or ""),
                "link_mode": data.get("linkMode"),
                "artifact_role": artifact_role(data),
            }
        )
    else:
        output["availability"] = "metadata_only"
    return output


def parent_record(
    parent: dict[str, Any], children: list[dict[str, Any]]
) -> dict[str, Any]:
    data = data_of(parent)
    return {
        "key": str(parent.get("key") or data.get("key") or ""),
        "version": int(parent.get("version") or data.get("version") or 0),
        "item_type": str(data.get("itemType") or ""),
        "title": str(data.get("title") or ""),
        "date": str(data.get("date") or ""),
        "DOI": str(data.get("DOI") or ""),
        "ISBN": str(data.get("ISBN") or ""),
        "creators": creators_of(data.get("creators")),
        "children": sorted(
            (child_record(child) for child in children),
            key=lambda item: item["key"],
        ),
    }


def build_snapshot(
    base_url: str, group_id: int, collection_key: str
) -> dict[str, Any]:
    base_url = validate_base_url(base_url)
    if group_id <= 0:
        raise ValueError("group_id must be positive")
    if not re.fullmatch(r"[A-Z0-9]{8}", collection_key):
        raise ValueError("collection_key is invalid")
    collection = api_get(
        base_url,
        f"/api/groups/{group_id}/collections/{collection_key}",
        {"include": "data"},
    )
    if not isinstance(collection, dict):
        raise ValueError("collection is malformed")
    path = get_collection_path(base_url, group_id, collection)
    parents: list[dict[str, Any]] = []
    top = get_all(
        base_url,
        f"/api/groups/{group_id}/collections/{collection_key}/items/top",
    )
    for parent in top:
        data = data_of(parent)
        if data.get("itemType") in {"note", "attachment", "annotation"}:
            continue
        key = str(parent.get("key") or data.get("key") or "")
        if not re.fullmatch(r"[A-Z0-9]{8}", key):
            raise ValueError("parent key is invalid")
        children = get_all(
            base_url, f"/api/groups/{group_id}/items/{key}/children"
        )
        parents.append(parent_record(parent, children))
    parents.sort(key=lambda item: item["key"])
    version = int(
        collection.get("version") or data_of(collection).get("version") or 0
    )
    collection_record = {
        "group_id": group_id,
        "collection_key": collection_key,
        "collection_version": version,
        "collection_path": path,
    }
    identity = digest_value(
        {
            "group_id": group_id,
            "collection_key": collection_key,
            "collection_path": [
                {"key": item["key"], "name": item["name"]} for item in path
            ],
        }
    )
    return {
        "schema": "ZoteroCorpusSnapshot/v1",
        "retrieved_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "collection": collection_record,
        "parents": parents,
        "identity_sha256": identity,
        "state_sha256": digest_value(
            {
                "identity_sha256": identity,
                "collection_version": version,
                "parents": parents,
            }
        ),
    }


def write_private_snapshot(path: Path, snapshot: dict[str, Any]) -> None:
    path = path.expanduser()
    if not path.is_absolute():
        raise ValueError("output must be absolute")
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(snapshot, stream, ensure_ascii=False, sort_keys=True, indent=2)
            stream.write("\n")
    except Exception:
        path.unlink(missing_ok=True)
        raise


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--base-url",
        required=True,
        help=(
            "loopback Zotero origin or API root, for example "
            "http://127.0.0.1:23119 or http://127.0.0.1:23119/api; "
            "both normalize to the origin"
        ),
    )
    parser.add_argument("--group-id", type=int, required=True)
    parser.add_argument("--collection-key", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        value = build_snapshot(
            args.base_url, args.group_id, args.collection_key
        )
        write_private_snapshot(args.output, value)
    except (
        OSError,
        ValueError,
        UnicodeError,
        json.JSONDecodeError,
        urllib.error.URLError,
    ) as exc:
        print(f"snapshot failed: {exc}", file=sys.stderr)
        return 2
    print(
        json.dumps(
            {
                "output": str(args.output),
                "parents": len(value["parents"]),
                "state_sha256": value["state_sha256"],
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
