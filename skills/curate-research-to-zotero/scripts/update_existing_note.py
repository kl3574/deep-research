#!/usr/bin/env python3
"""Dry-run or version-safely PATCH existing Zotero child notes.

Current stable Zotero releases may expose only a read-only local API. This
script always validates against that local state first. It can then use the
official Zotero Web API when a dedicated key is supplied through an environment
variable. It never prints the key and never edits Zotero SQLite.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

from verify_note_html import validate_note


LOCAL_BASE = "http://127.0.0.1:23119"
WEB_BASE = "https://api.zotero.org"

EXIT_OK = 0
EXIT_VALIDATION = 1
EXIT_IO = 2
EXIT_CONFLICT = 4
EXIT_CAPABILITY = 5


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


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


def probe_local_write() -> dict[str, object]:
    status, headers, _ = request(f"{LOCAL_BASE}/api/")
    server_id = headers.get("Zotero-Server-ID") or headers.get("zotero-server-id")
    authorize_status, _, _ = request(
        f"{LOCAL_BASE}/api/local/authorize",
        method="OPTIONS",
    )
    return {
        "api_status": status,
        "server_id_present": bool(server_id),
        "authorize_route_status": authorize_status,
        "supported": bool(server_id) and authorize_status not in {404, 405},
    }


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
    return {
        "libraryID": payload.get("libraryID"),
        "libraryName": payload.get("libraryName"),
        "name": payload.get("name"),
        "editable": payload.get("editable"),
        "filesEditable": payload.get("filesEditable"),
        "id": payload.get("id"),
    }


def load_entries(manifest_path: Path, requested_keys: set[str]) -> tuple[dict[str, object], list[dict[str, object]]]:
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or not isinstance(payload.get("entries"), list):
        raise ValueError("migration manifest is missing entries")
    target = payload.get("target")
    if not isinstance(target, dict):
        raise ValueError("migration manifest target is missing")
    entries = [
        entry
        for entry in payload["entries"]
        if isinstance(entry, dict)
        and entry.get("status") == "staged_verified"
        and (not requested_keys or str(entry.get("note_key")) in requested_keys)
    ]
    if requested_keys:
        found = {str(entry.get("note_key")) for entry in entries}
        missing = requested_keys - found
        if missing:
            raise ValueError(f"requested note keys are not staged_verified: {sorted(missing)}")
    if not entries:
        raise ValueError("no staged_verified notes selected")
    return target, entries


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
    if note_data.get("parentItem") != parent_key:
        raise RuntimeError(
            f"{note_key}: parent changed {note_data.get('parentItem')!r} != {parent_key!r}"
        )
    if observed_sha != entry.get("old_sha256"):
        raise RuntimeError(
            f"{note_key}: old content conflict {observed_sha} != {entry.get('old_sha256')}"
        )
    if note_obj.get("version") != entry.get("note_version"):
        raise RuntimeError(
            f"{note_key}: local version changed {note_obj.get('version')} != {entry.get('note_version')}"
        )

    _, parent_obj = get_json(f"{LOCAL_BASE}/api/groups/{group_id}/items/{parent_key}")
    if not isinstance(parent_obj, dict) or not isinstance(parent_obj.get("data"), dict):
        raise RuntimeError(f"{parent_key}: malformed local parent response")
    collections = parent_obj["data"].get("collections")
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
    return {
        "note_key": note_key,
        "parent_key": parent_key,
        "local_version": note_obj.get("version"),
        "old_sha256": observed_sha,
        "new_sha256": new_sha,
        "new_path": str(new_path),
        "new_html": new_html,
        "validation_warnings": warnings,
        "validation_summary": summary,
        "old_html": observed_note,
    }


def web_headers(api_key: str) -> dict[str, str]:
    return {
        "Zotero-API-Key": api_key,
        "Zotero-API-Version": "3",
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
    collections = parent_obj["data"].get("collections")
    if not isinstance(collections, list) or collection_key not in collections:
        raise RuntimeError(f"{note_key}: remote parent is outside approved collection")

    version = note_obj.get("version")
    if not isinstance(version, int):
        version_header = headers.get("Last-Modified-Version")
        version = int(version_header) if version_header and version_header.isdigit() else None
    if not isinstance(version, int):
        raise RuntimeError(f"{note_key}: remote version is unavailable")
    return {
        "version": version,
        "old_html": str(note_data.get("note") or ""),
        "old_sha256": remote_sha,
    }


def patch_remote_note(
    group_id: int,
    local: dict[str, object],
    remote: dict[str, object],
    api_key: str,
) -> dict[str, object]:
    note_key = str(local["note_key"])
    headers = web_headers(api_key)
    headers["If-Unmodified-Since-Version"] = str(remote["version"])
    status, _, body = request(
        f"{WEB_BASE}/groups/{group_id}/items/{note_key}",
        method="PATCH",
        headers=headers,
        payload={"note": local["new_html"]},
    )
    if status == 412:
        raise RuntimeError(f"{note_key}: HTTP 412 concurrent modification; stopped")
    if status != 204:
        detail = body.decode("utf-8", errors="replace")[:300]
        raise RuntimeError(f"{note_key}: PATCH returned HTTP {status}: {detail}")
    _, readback = get_json(
        f"{WEB_BASE}/groups/{group_id}/items/{note_key}",
        headers=web_headers(api_key),
    )
    if not isinstance(readback, dict) or not isinstance(readback.get("data"), dict):
        raise RuntimeError(f"{note_key}: malformed remote readback")
    readback_note = str(readback["data"].get("note") or "")
    readback_sha = sha256_text(readback_note)
    if readback_sha != local["new_sha256"]:
        raise RuntimeError(
            f"{note_key}: remote readback hash mismatch {readback_sha} != {local['new_sha256']}"
        )
    return {
        "remote_version": readback.get("version"),
        "remote_readback_sha256": readback_sha,
        "remote_verified": True,
    }


def backup_remote(
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
    parser.add_argument("--route", choices=("auto", "web"), default="auto")
    parser.add_argument("--api-key-env", default="ZOTERO_API_KEY")
    parser.add_argument("--backup-dir", type=Path)
    parser.add_argument("--yes", action="store_true")
    parser.add_argument("--json", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    manifest_path = args.manifest.expanduser().resolve()
    try:
        target, entries = load_entries(manifest_path, set(args.note_key))
        group_id = int(target["group_id"])
        collection_key = str(target["collection_key"])
        collection_name = str(target["collection_name"])
        selected = selected_target()
        if (
            selected.get("libraryName") != "PRIVATE_ZOTERO_TARGET"
            or selected.get("name") != collection_name
            or not selected.get("editable")
        ):
            raise RuntimeError(f"selected target mismatch or not editable: {selected}")
        locals_verified = [
            verify_local_entry(group_id, collection_key, entry) for entry in entries
        ]
        capability = probe_local_write()
    except Exception as exc:
        print(f"preflight failed: {exc}", file=sys.stderr)
        return EXIT_CONFLICT

    api_key = os.environ.get(args.api_key_env, "")
    route = "web" if api_key else None
    if args.route == "web" and not api_key:
        route = None
    preview = {
        "mode": "apply" if args.yes else "dry_run",
        "target": {
            "group_id": group_id,
            "collection_key": collection_key,
            "collection_name": collection_name,
        },
        "selected_target": selected,
        "local_write_capability": capability,
        "selected_route": route,
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
        print(
            f"no supported write route: local PATCH unavailable and {args.api_key_env} is unset",
            file=sys.stderr,
        )
        return EXIT_CAPABILITY

    backup_dir = (
        args.backup_dir.expanduser().resolve()
        if args.backup_dir
        else manifest_path.parent / "web_api_backups"
    )
    results: list[dict[str, object]] = []
    try:
        for local in locals_verified:
            remote = verify_remote_entry(group_id, collection_key, local, api_key)
            backup = backup_remote(
                backup_dir,
                str(local["note_key"]),
                int(remote["version"]),
                str(remote["old_html"]),
            )
            result = patch_remote_note(group_id, local, remote, api_key)
            results.append(
                {
                    "note_key": local["note_key"],
                    "parent_key": local["parent_key"],
                    "backup": backup,
                    **result,
                }
            )
    except Exception as exc:
        print(
            json.dumps(
                {
                    "status": "partial_failure" if results else "failed",
                    "completed": results,
                    "error": str(exc),
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
