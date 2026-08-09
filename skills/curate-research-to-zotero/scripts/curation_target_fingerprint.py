#!/usr/bin/env python3
"""Canonical CurationBatch target fingerprints derived from corpus snapshots."""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any


DIGEST_RE = re.compile(r"^(?:sha256:)?([0-9a-f]{64})$")
ITEM_KEY_RE = re.compile(r"^[A-Z0-9]{8}$")
TARGET_KEYS = {
    "group_id",
    "library_id",
    "library_name",
    "collection_key",
    "collection_path",
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


def compute_identity_fingerprint(target: dict[str, Any]) -> str:
    return digest_value(target)


def compute_state_fingerprint(
    identity_sha256: str, collection_version: int, parent_keys: list[str]
) -> str:
    return digest_value(
        {
            "identity_sha256": normalize_digest(identity_sha256)
            or identity_sha256,
            "collection_version": collection_version,
            "top_level_parent_keys": sorted(parent_keys),
        }
    )


def _snapshot_identity(
    group_id: int, collection_key: str, path: list[dict[str, Any]]
) -> str:
    return digest_value(
        {
            "group_id": group_id,
            "collection_key": collection_key,
            "collection_path": [
                {"key": item["key"], "name": item["name"]} for item in path
            ],
        }
    )


def target_and_fingerprint_from_snapshot(
    snapshot: Any,
    *,
    library_id: int,
    library_name: str,
    expected_target: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Verify a snapshot and project its live state into CurationBatch fields."""
    if not isinstance(snapshot, dict) or snapshot.get("schema") != "ZoteroCorpusSnapshot/v1":
        raise ValueError("snapshot must be ZoteroCorpusSnapshot/v1")
    if not isinstance(library_id, int) or isinstance(library_id, bool) or library_id < 0:
        raise ValueError("library_id is invalid")
    if not isinstance(library_name, str) or not library_name.strip():
        raise ValueError("library_name is invalid")

    collection = snapshot.get("collection")
    parents = snapshot.get("parents")
    if not isinstance(collection, dict) or not isinstance(parents, list):
        raise ValueError("snapshot collection or parents are malformed")
    group_id = collection.get("group_id")
    collection_key = collection.get("collection_key")
    collection_version = collection.get("collection_version")
    path = collection.get("collection_path")
    if not isinstance(group_id, int) or isinstance(group_id, bool) or group_id <= 0:
        raise ValueError("snapshot group_id is invalid")
    if not isinstance(collection_key, str) or not ITEM_KEY_RE.fullmatch(collection_key):
        raise ValueError("snapshot collection_key is invalid")
    if (
        not isinstance(collection_version, int)
        or isinstance(collection_version, bool)
        or collection_version < 0
    ):
        raise ValueError("snapshot collection_version is invalid")
    if not isinstance(path, list) or not path:
        raise ValueError("snapshot collection_path is invalid")
    normalized_path: list[dict[str, str]] = []
    for index, item in enumerate(path):
        if not isinstance(item, dict):
            raise ValueError(f"snapshot collection_path[{index}] is invalid")
        key = item.get("key")
        name = item.get("name")
        if not isinstance(key, str) or not ITEM_KEY_RE.fullmatch(key):
            raise ValueError(f"snapshot collection_path[{index}].key is invalid")
        if not isinstance(name, str) or not name.strip():
            raise ValueError(f"snapshot collection_path[{index}].name is invalid")
        normalized_path.append({"key": key, "name": name})
    if normalized_path[-1]["key"] != collection_key:
        raise ValueError("snapshot collection path does not end at collection_key")

    parent_keys: list[str] = []
    for index, parent in enumerate(parents):
        key = parent.get("key") if isinstance(parent, dict) else None
        if not isinstance(key, str) or not ITEM_KEY_RE.fullmatch(key):
            raise ValueError(f"snapshot parents[{index}].key is invalid")
        parent_keys.append(key)
    if parent_keys != sorted(set(parent_keys)):
        raise ValueError("snapshot parent keys must be sorted and unique")

    snapshot_identity = _snapshot_identity(group_id, collection_key, normalized_path)
    if normalize_digest(snapshot.get("identity_sha256")) != snapshot_identity:
        raise ValueError("snapshot identity_sha256 does not match live collection fields")
    snapshot_state = digest_value(
        {
            "identity_sha256": snapshot_identity,
            "collection_version": collection_version,
            "parents": parents,
        }
    )
    if normalize_digest(snapshot.get("state_sha256")) != snapshot_state:
        raise ValueError("snapshot state_sha256 does not match live parent state")

    target = {
        "group_id": group_id,
        "library_id": library_id,
        "library_name": library_name,
        "collection_key": collection_key,
        "collection_path": [item["name"] for item in normalized_path],
    }
    if expected_target is not None and expected_target != target:
        raise ValueError("snapshot projection differs from the expected batch target")
    identity = compute_identity_fingerprint(target)
    fingerprint = {
        "identity_sha256": identity,
        "state_sha256": compute_state_fingerprint(
            identity, collection_version, parent_keys
        ),
        "captured_at": snapshot.get("retrieved_at"),
        "collection_version": collection_version,
        "top_level_parent_keys": parent_keys,
    }
    stored_target = snapshot.get("batch_target")
    stored_fingerprint = snapshot.get("batch_target_fingerprint")
    if stored_target is not None and stored_target != target:
        raise ValueError("snapshot batch_target differs from canonical projection")
    if stored_fingerprint is not None and stored_fingerprint != fingerprint:
        raise ValueError(
            "snapshot batch_target_fingerprint differs from canonical projection"
        )
    return target, fingerprint
