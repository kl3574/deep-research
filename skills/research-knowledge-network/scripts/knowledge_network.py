#!/usr/bin/env python3
"""Traceable research knowledge-network ledger for local evidence networks."""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import re
import stat
import sys
import tempfile
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

SCHEMA_VERSION = "1"
NETWORK_ROOT = "networks"
LEDGER_NAMES = (
    "sources",
    "entities",
    "claims",
    "evidence",
    "relations",
    "gaps",
    "events",
)

ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{1,62}")
GAP_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{1,254}")
SNAPSHOT_DIGEST_RE = re.compile(r"sha256:[0-9a-f]{64}")
ZOTERO_SNAPSHOT_SCHEMA = "ZoteroCorpusSnapshot/v1"

READ_DEPTHS = {"full", "partial", "metadata", "abstract"}
EVIDENCE_POLARITY = {"supports", "contradicts", "qualifies", "not_tested"}
DECISIVE_COVERAGE_POLARITIES = frozenset({"supports"})
GAP_TYPES = {"explicit", "deterministic_structural", "implicit_candidate"}
IMPACTS = {"high", "medium", "low"}
GAP_PRIORITIES = {"P0", "P1", "P2", "P3"}
GAP_STATUSES = {"open", "resolved", "blocked"}
GAP_STATUS_TRANSITIONS = {
    "open": {"resolved", "blocked"},
    "resolved": {"open"},
    "blocked": {"open", "resolved"},
}
RELATION_TYPES = {"supports", "contradicts", "grounds", "refines", "depends", "enables"}
EVENT_TYPES = {
    "init",
    "derive_gaps",
    "snapshot_refreshed",
    "status_snapshot",
    "patch_decision",
}


def _utcnow() -> str:
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return f"sha256:{digest.hexdigest()}"


def _snapshot_file_fingerprint(metadata: os.stat_result) -> tuple[int, ...]:
    return (
        metadata.st_dev,
        metadata.st_ino,
        metadata.st_mode,
        metadata.st_size,
        metadata.st_mtime_ns,
        metadata.st_ctime_ns,
    )


def _open_stable_snapshot(path: Path) -> tuple[int, os.stat_result, os.stat_result]:
    if not path.is_absolute():
        raise ValueError("snapshot path must be absolute")
    try:
        path_before = path.lstat()
    except OSError as exc:
        raise ValueError(f"snapshot path unavailable: {path}") from exc
    if not stat.S_ISREG(path_before.st_mode):
        raise ValueError("snapshot path must be a regular non-symlink file")

    flags = os.O_RDONLY | os.O_CLOEXEC | os.O_NONBLOCK
    nofollow = getattr(os, "O_NOFOLLOW", None)
    if nofollow is None:
        raise ValueError("platform lacks O_NOFOLLOW for safe snapshot reads")
    flags |= nofollow
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise ValueError("snapshot open-no-follow failed") from exc
    try:
        descriptor_before = os.fstat(descriptor)
        if not stat.S_ISREG(descriptor_before.st_mode):
            raise ValueError("snapshot descriptor is not a regular file")
        if (
            descriptor_before.st_dev != path_before.st_dev
            or descriptor_before.st_ino != path_before.st_ino
        ):
            raise ValueError("snapshot changed before read")
    except Exception:
        os.close(descriptor)
        raise
    return descriptor, path_before, descriptor_before


def _read_snapshot_descriptor(
    descriptor: int,
) -> tuple[bytes, str, os.stat_result]:
    digest = hashlib.sha256()
    chunks: list[bytes] = []
    while True:
        chunk = os.read(descriptor, 1024 * 1024)
        if not chunk:
            break
        chunks.append(chunk)
        digest.update(chunk)
    descriptor_after = os.fstat(descriptor)
    return b"".join(chunks), f"sha256:{digest.hexdigest()}", descriptor_after


def _verify_snapshot_unchanged(
    path: Path,
    path_before: os.stat_result,
    descriptor_before: os.stat_result,
    descriptor_after: os.stat_result,
) -> None:
    try:
        path_after = path.lstat()
    except OSError as exc:
        raise ValueError("snapshot disappeared during read") from exc
    stable_fingerprint = _snapshot_file_fingerprint(path_before)
    observed = (
        _snapshot_file_fingerprint(descriptor_before),
        _snapshot_file_fingerprint(descriptor_after),
        _snapshot_file_fingerprint(path_after),
    )
    if any(fingerprint != stable_fingerprint for fingerprint in observed):
        raise ValueError("snapshot changed during read")


def _decode_snapshot_json(raw: bytes) -> dict[str, Any]:
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("snapshot is not valid UTF-8 JSON") from exc
    if not isinstance(payload, dict):
        raise ValueError("snapshot JSON must be an object")
    return payload


def _read_stable_snapshot(path: Path) -> tuple[dict[str, Any], str]:
    """Read one absolute regular file without following its final symlink."""
    descriptor, path_before, descriptor_before = _open_stable_snapshot(path)
    try:
        raw, digest, descriptor_after = _read_snapshot_descriptor(descriptor)
    finally:
        os.close(descriptor)
    _verify_snapshot_unchanged(
        path,
        path_before,
        descriptor_before,
        descriptor_after,
    )
    if len(raw) != descriptor_after.st_size:
        raise ValueError("snapshot size changed during read")
    return _decode_snapshot_json(raw), digest


def _canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _sha256_json(value: Any) -> str:
    return f"sha256:{hashlib.sha256(_canonical_json_bytes(value)).hexdigest()}"


def _normalized_text(value: str) -> str:
    return " ".join(value.strip().split())


def _normalized_doi(value: str) -> str:
    doi = _normalized_text(value).lower()
    for prefix in ("https://doi.org/", "http://doi.org/", "doi:"):
        if doi.startswith(prefix):
            doi = doi[len(prefix) :].strip()
            break
    return doi


def _snapshot_parent_identity_hash(parent: dict[str, Any]) -> str:
    payload = {
        "key": str(parent.get("key") or ""),
        "version": int(parent.get("version") or 0),
        "item_type": str(parent.get("item_type") or ""),
        "title": _normalized_text(str(parent.get("title") or "")),
        "date": _normalized_text(str(parent.get("date") or "")),
        "DOI": _normalized_doi(str(parent.get("DOI") or "")),
        "ISBN": _normalized_text(str(parent.get("ISBN") or "")),
        "creators": parent.get("creators") or [],
    }
    return _sha256_json(payload)


def _zotero_snapshot_identity_digest(snapshot: dict[str, Any]) -> str | None:
    collection = snapshot.get("collection")
    if not isinstance(collection, dict):
        return None
    group_id = collection.get("group_id")
    collection_key = collection.get("collection_key")
    collection_path = collection.get("collection_path")
    if (
        not isinstance(group_id, int)
        or isinstance(group_id, bool)
        or not isinstance(collection_key, str)
        or not isinstance(collection_path, list)
    ):
        return None
    identity_path: list[dict[str, str]] = []
    for item in collection_path:
        if not isinstance(item, dict):
            return None
        key = item.get("key")
        name = item.get("name")
        if not isinstance(key, str) or not isinstance(name, str):
            return None
        identity_path.append({"key": key, "name": name})
    return _sha256_json(
        {
            "group_id": group_id,
            "collection_key": collection_key,
            "collection_path": identity_path,
        }
    )


def _zotero_snapshot_state_digest(snapshot: dict[str, Any]) -> str | None:
    collection = snapshot.get("collection")
    parents = snapshot.get("parents")
    if not isinstance(collection, dict) or not isinstance(parents, list):
        return None
    identity = _zotero_snapshot_identity_digest(snapshot)
    collection_version = collection.get("collection_version")
    if identity is None or not isinstance(collection_version, int):
        return None
    return _sha256_json(
        {
            "identity_sha256": identity,
            "collection_version": collection_version,
            "parents": parents,
        }
    )


def _snapshot_parent_identity(parent: dict[str, Any]) -> str:
    doi = _normalized_doi(str(parent.get("DOI") or ""))
    if doi:
        return f"doi:{doi}"
    title = _normalized_text(str(parent.get("title") or "")).casefold()
    date = _normalized_text(str(parent.get("date") or "")).casefold()
    return f"title-date:{_sha256_json({'title': title, 'date': date}).split(':', 1)[1]}"


def _safe_slug(value: str) -> str:
    value = value.strip().lower()
    if not value:
        return ""
    value = re.sub(r"[^a-z0-9._-]+", "-", value)
    value = re.sub(r"-{2,}", "-", value)
    value = value.strip("-._")
    if not value:
        return ""
    if not (value[0].isalnum()):
        value = f"p-{value}"
    if len(value) > 50:
        value = value[:50]
    return value


def _parent_source_id(parent: dict[str, Any], identity_digest: str) -> str:
    canonical_identity = _snapshot_parent_identity(parent)
    canonical_digest = _sha256_json(
        {"canonical_identity": canonical_identity}
    ).split(":", 1)[1]
    version_digest = identity_digest.split(":", 1)[1]
    return f"zotero-{canonical_digest[:16]}-{version_digest[:16]}"


def _source_row_signature(row: dict[str, Any]) -> dict[str, Any]:
    signature = dict(row)
    signature.pop("sequence", None)
    signature.pop("recorded_at", None)
    signature.pop("schema_version", None)
    signature.pop("network_id", None)
    signature.pop("record_id", None)
    signature.pop("snapshot_state", None)
    signature.pop("supersedes", None)
    return signature


def _corpus_snapshot_current_source_ids(state: dict[str, Any]) -> list[str]:
    value = state.get("corpus_snapshot_current_source_ids")
    if not isinstance(value, list):
        return []
    normalized: list[str] = []
    seen: set[str] = set()
    for item in value:
        if not isinstance(item, str):
            continue
        sid = item.strip()
        if sid and sid not in seen and ID_RE.fullmatch(sid):
            seen.add(sid)
            normalized.append(sid)
    return normalized


def _snapshot_parents_sorted(parents: list[dict[str, Any]]) -> list[dict[str, Any]]:
    enriched = []
    for parent in parents:
        if not isinstance(parent, dict):
            raise ValueError("parent must be an object")
        identity = _snapshot_parent_identity(parent)
        identity_hash = _snapshot_parent_identity_hash(parent)
        source_id = _parent_source_id(parent, identity_hash)
        enriched.append((identity, identity_hash, source_id, parent))
    enriched.sort(key=lambda item: (item[0], item[1], item[2], item[3].get("key", "")))
    return [item[3] for item in enriched]


def _require_snapshot_string(
    payload: dict[str, Any], field: str, *, allow_empty: bool = True
) -> str:
    value = payload.get(field)
    if not isinstance(value, str):
        raise ValueError(f"snapshot {field} must be a string")
    if not allow_empty and not value.strip():
        raise ValueError(f"snapshot {field} cannot be empty")
    return value


def _validate_snapshot_parent(parent: dict[str, Any], position: int) -> None:
    prefix = f"snapshot parent[{position}]"
    key = parent.get("key")
    if not isinstance(key, str) or not key.strip():
        raise ValueError(f"{prefix} key missing or invalid")
    version = parent.get("version")
    if not isinstance(version, int) or isinstance(version, bool) or version < 0:
        raise ValueError(f"{prefix} version missing or invalid")
    for field in ("item_type", "title", "date", "DOI", "ISBN"):
        if not isinstance(parent.get(field), str):
            raise ValueError(f"{prefix} {field} must be a string")
    if not parent["item_type"].strip():
        raise ValueError(f"{prefix} item_type cannot be empty")
    if not parent["title"].strip() and not parent["date"].strip():
        raise ValueError(f"{prefix} requires title or date")
    creators = parent.get("creators")
    if not isinstance(creators, list) or not all(
        isinstance(creator, dict) for creator in creators
    ):
        raise ValueError(f"{prefix} creators must be a list of objects")
    children = parent.get("children", [])
    if not isinstance(children, list):
        raise ValueError(f"{prefix} children must be a list")
    for child_position, child in enumerate(children):
        _validate_snapshot_child(child, prefix, child_position)


def _validate_snapshot_child(child: Any, parent_prefix: str, position: int) -> None:
    prefix = f"{parent_prefix} child[{position}]"
    if not isinstance(child, dict):
        raise ValueError(f"{prefix} must be an object")
    child_key = child.get("key")
    child_type = child.get("item_type")
    child_version = child.get("version")
    if not isinstance(child_key, str) or not child_key.strip():
        raise ValueError(f"{prefix} key invalid")
    if not isinstance(child_type, str) or not child_type.strip():
        raise ValueError(f"{prefix} item_type invalid")
    if (
        not isinstance(child_version, int)
        or isinstance(child_version, bool)
        or child_version < 0
    ):
        raise ValueError(f"{prefix} version invalid")


def _validate_snapshot_collection(collection: Any) -> None:
    if not isinstance(collection, dict):
        raise ValueError("snapshot collection must be an object")
    group_id = collection.get("group_id")
    if not isinstance(group_id, int) or isinstance(group_id, bool) or group_id <= 0:
        raise ValueError("snapshot collection group_id missing or invalid")
    _require_snapshot_string(collection, "collection_key", allow_empty=False)
    collection_version = collection.get("collection_version")
    if (
        not isinstance(collection_version, int)
        or isinstance(collection_version, bool)
        or collection_version < 0
    ):
        raise ValueError("snapshot collection_version missing or invalid")
    collection_path = collection.get("collection_path")
    if not isinstance(collection_path, list) or not collection_path:
        raise ValueError("snapshot collection_path must be a non-empty list")
    for position, node in enumerate(collection_path):
        if not isinstance(node, dict):
            raise ValueError(f"snapshot collection_path[{position}] must be an object")
        _require_snapshot_string(node, "key", allow_empty=False)
        _require_snapshot_string(node, "name", allow_empty=False)


def _validate_snapshot_parents(parents: Any) -> None:
    if not isinstance(parents, list):
        raise ValueError("snapshot parents must be a list")
    seen_keys: set[str] = set()
    seen_identities: set[str] = set()
    for position, parent in enumerate(parents):
        if not isinstance(parent, dict):
            raise ValueError(f"snapshot parent[{position}] must be an object")
        _validate_snapshot_parent(parent, position)
        parent_key = str(parent["key"])
        identity = _snapshot_parent_identity(parent)
        if parent_key in seen_keys:
            raise ValueError(f"duplicate snapshot parent key: {parent_key}")
        if identity in seen_identities:
            raise ValueError(f"duplicate snapshot parent identity: {identity}")
        seen_keys.add(parent_key)
        seen_identities.add(identity)


def _validate_snapshot_declared_digests(snapshot: dict[str, Any]) -> None:
    declared_identity = snapshot.get("identity_sha256")
    computed_identity = _zotero_snapshot_identity_digest(snapshot)
    if not SNAPSHOT_DIGEST_RE.fullmatch(str(declared_identity or "")):
        raise ValueError("snapshot identity_sha256 missing or invalid")
    if declared_identity != computed_identity:
        raise ValueError("snapshot identity_sha256 mismatch")
    declared_state = snapshot.get("state_sha256")
    computed_state = _zotero_snapshot_state_digest(snapshot)
    if not SNAPSHOT_DIGEST_RE.fullmatch(str(declared_state or "")):
        raise ValueError("snapshot state_sha256 missing or invalid")
    if declared_state != computed_state:
        raise ValueError("snapshot state_sha256 mismatch")


def _validate_zotero_snapshot(snapshot: dict[str, Any]) -> None:
    if snapshot.get("schema") != ZOTERO_SNAPSHOT_SCHEMA:
        raise ValueError("snapshot schema must be ZoteroCorpusSnapshot/v1")
    _require_snapshot_string(snapshot, "retrieved_at", allow_empty=False)
    _validate_snapshot_collection(snapshot.get("collection"))
    _validate_snapshot_parents(snapshot.get("parents"))
    _validate_snapshot_declared_digests(snapshot)


def _read_zotero_snapshot(snapshot_path: Path) -> dict[str, Any]:
    snapshot, _ = _read_stable_snapshot(snapshot_path)
    _validate_zotero_snapshot(snapshot)
    return snapshot


def _read_zotero_snapshot_with_digest(
    snapshot_path: Path,
) -> tuple[dict[str, Any], str]:
    snapshot, digest = _read_stable_snapshot(snapshot_path)
    _validate_zotero_snapshot(snapshot)
    return snapshot, digest


def _ensure_value(value: str | None, field: str) -> str:
    if value is None:
        raise ValueError(f"{field} must be provided")
    value = value.strip()
    if not value:
        raise ValueError(f"{field} cannot be empty")
    return value


def _validate_id(value: str, field: str) -> str:
    value = _ensure_value(value, field)
    if not ID_RE.fullmatch(value):
        raise ValueError(f"{field} invalid format: {value}")
    return value


def _validate_gap_id(value: str, field: str) -> str:
    value = _ensure_value(value, field)
    if not GAP_ID_RE.fullmatch(value):
        raise ValueError(f"{field} invalid format: {value}")
    return value


def _ensure_root(root: Path) -> Path:
    if root.is_symlink():
        raise ValueError(f"root is symlink: {root}")
    return root.expanduser().resolve()


def _safe_relative_path(root: Path, raw: str, label: str) -> Path:
    path = (root / Path(raw)).expanduser().resolve()
    if root != path and root not in path.parents:
        raise ValueError(f"{label} escapes root: {path}")
    return path


def _ensure_file(path: Path, label: str) -> Path:
    if path.is_symlink():
        raise ValueError(f"{label} is a symbolic link: {path}")
    if not path.is_file():
        raise ValueError(f"{label} is not a file: {path}")
    return path


def _ensure_dir(path: Path, label: str) -> Path:
    if path.is_symlink():
        raise ValueError(f"{label} is a symbolic link: {path}")
    return path


def _normalize_record(row: dict[str, Any]) -> dict[str, Any]:
    copy = dict(row)
    copy.pop("sequence", None)
    copy.pop("recorded_at", None)
    copy.pop("schema_version", None)
    copy.pop("network_id", None)
    return copy


def _record_id(*segments: str) -> str:
    return ":".join(segments)


def _gap_record_digest(gap_id: str) -> str:
    return hashlib.sha256(gap_id.encode("utf-8")).hexdigest()[:32]


def _gap_initial_record_id(gap_id: str) -> str:
    return f"gap-{_gap_record_digest(gap_id)}-initial"


def _gap_transition_record_id(gap_id: str, sequence: int) -> str:
    return f"gap-{_gap_record_digest(gap_id)}-t{sequence}"


def _record_id_suffix_matches(
    record_type: str, row: dict[str, Any], payload_id: str
) -> bool:
    record_id = row.get("record_id")
    if not isinstance(record_id, str):
        return False
    prefix = f"{record_type}:"
    if not record_id.startswith(prefix):
        return False
    return record_id[len(prefix) :].strip(":") == payload_id


def _sort_items(values: Iterable[Any]) -> list[Any]:
    return sorted(
        values, key=lambda item: json.dumps(item, sort_keys=True, ensure_ascii=False)
    )


@dataclass(frozen=True)
class Paths:
    root: Path
    network_id: str

    @property
    def network_dir(self) -> Path:
        candidate = self.root / NETWORK_ROOT / self.network_id
        _ensure_dir(candidate, "network dir")
        candidate_resolved = candidate.resolve()
        if (
            self.root != candidate_resolved
            and self.root not in candidate_resolved.parents
        ):
            raise ValueError(f"network path escapes root: {candidate_resolved}")
        return candidate

    @property
    def state(self) -> Path:
        return self.network_dir / "network.json"

    def ledger(self, name: str) -> Path:
        if name not in LEDGER_NAMES:
            raise ValueError(f"unknown ledger: {name}")
        return self.network_dir / f"{name}.jsonl"

    @property
    def lock(self) -> Path:
        return self.network_dir / ".lock"

    @property
    def transaction_journal(self) -> Path:
        return self.network_dir / ".transaction.json"


def _safe_paths(root: str, network_id: str) -> Paths:
    root_path = _ensure_root(Path(root))
    network_id = _validate_id(network_id, "network_id")
    paths = Paths(root_path, network_id)
    return paths


def _network_exists(paths: Paths) -> bool:
    return paths.network_dir.exists()


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            "w",
            dir=path.parent,
            prefix=f".{path.name}.",
            encoding="utf-8",
            delete=False,
        ) as handle:
            temp_path = Path(handle.name)
            json.dump(payload, handle, ensure_ascii=False, sort_keys=True, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        temp_path.replace(path)
    finally:
        if temp_path is not None and temp_path.exists():
            try:
                temp_path.unlink()
            except OSError:
                pass


def _json_text(payload: dict[str, Any]) -> str:
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        indent=2,
        allow_nan=False,
    ) + "\n"


def _jsonl_text(rows: list[dict[str, Any]]) -> str:
    return "".join(
        json.dumps(
            row,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        + "\n"
        for row in rows
    )


def _restore_file(path: Path, content: bytes) -> None:
    temp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            "wb", dir=path.parent, prefix=f".{path.name}.restore.", delete=False
        ) as handle:
            temp_path = Path(handle.name)
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, path)
    finally:
        if temp_path is not None and temp_path.exists():
            temp_path.unlink(missing_ok=True)


def _rollback_replaced_files(
    replaced: list[Path], originals: dict[Path, bytes]
) -> bool:
    rollback_failed = False
    for path in reversed(replaced):
        try:
            _restore_file(path, originals[path])
        except OSError:
            rollback_failed = True
    return rollback_failed


def _fsync_directory(path: Path) -> None:
    directory_fd = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)


def _replace_files_transactionally(contents: dict[Path, str]) -> None:
    """Stage files and roll back handled failures under the caller's lock."""
    staged: dict[Path, Path] = {}
    originals: dict[Path, bytes] = {}
    replaced: list[Path] = []
    first_path = next(iter(contents))
    journal_path = first_path.parent / ".transaction.json"
    if journal_path.exists() or journal_path.is_symlink():
        raise ValueError("incomplete transaction journal requires recovery")
    try:
        for path, content in contents.items():
            if path.is_symlink():
                raise ValueError(f"transaction target is symbolic link: {path}")
            if not path.is_file():
                raise ValueError(f"transaction target is not a file: {path}")
            originals[path] = path.read_bytes()
            with tempfile.NamedTemporaryFile(
                "w",
                dir=path.parent,
                prefix=f".{path.name}.stage.",
                encoding="utf-8",
                delete=False,
            ) as handle:
                staged[path] = Path(handle.name)
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())

        _write_json_atomic(
            journal_path,
            {
                "schema": "KnowledgeNetworkTransaction/v1",
                "status": "prepared",
                "targets": [
                    {
                        "name": path.name,
                        "before_sha256": hashlib.sha256(originals[path]).hexdigest(),
                        "after_sha256": hashlib.sha256(
                            contents[path].encode("utf-8")
                        ).hexdigest(),
                    }
                    for path in contents
                ],
            },
        )
        _fsync_directory(first_path.parent)

        for path in contents:
            os.replace(staged[path], path)
            replaced.append(path)
        _fsync_directory(first_path.parent)
        journal_path.unlink()
        _fsync_directory(first_path.parent)
    except Exception:
        rollback_failed = _rollback_replaced_files(replaced, originals)
        if not rollback_failed:
            _fsync_directory(first_path.parent)
            journal_path.unlink(missing_ok=True)
            _fsync_directory(first_path.parent)
        raise
    finally:
        for temp_path in staged.values():
            temp_path.unlink(missing_ok=True)


def _append_jsonl(path: Path, payload: dict[str, Any]) -> None:
    line = json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n"
    with path.open("a", encoding="utf-8") as handle:
        handle.write(line)
        handle.flush()
        os.fsync(handle.fileno())


def _read_json(path: Path) -> dict[str, Any]:
    if path.is_symlink():
        raise ValueError(f"json path is symlink: {path}")
    with path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise ValueError(f"{path.name} must be an object")
    return data


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if path.is_symlink():
        raise ValueError(f"ledger is symlink: {path}")
    records: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            content = line.strip()
            if not content:
                continue
            try:
                row = json.loads(content)
            except json.JSONDecodeError as exc:
                raise ValueError(
                    f"{path.name}: invalid JSON at line {line_number}"
                ) from exc
            if not isinstance(row, dict):
                raise ValueError(f"{path.name}: line {line_number} is not an object")
            records.append(row)
    return records


def _load_state(paths: Paths) -> tuple[dict[str, Any], dict[str, list[dict[str, Any]]]]:
    if not paths.network_dir.exists():
        raise FileNotFoundError(f"network missing: {paths.network_id}")
    if paths.network_dir.is_symlink():
        raise ValueError(f"network dir is symlink: {paths.network_dir}")
    if paths.transaction_journal.exists() or paths.transaction_journal.is_symlink():
        raise ValueError(
            "incomplete transaction journal detected; validation is blocked"
        )

    _ensure_dir(paths.network_dir, "network dir")
    state = _read_json(paths.state)
    if not isinstance(state, dict):
        raise ValueError("network.json invalid payload")
    ledgers = {}
    for name in LEDGER_NAMES:
        ledgers[name] = _read_jsonl(paths.ledger(name))
    return state, ledgers


def _next_sequence(records: dict[str, list[dict[str, Any]]]) -> int:
    sequence = 0
    for rows in records.values():
        for row in rows:
            current = row.get("sequence")
            if isinstance(current, int) and current > sequence:
                sequence = current
    return sequence + 1


def _find_records(
    records: list[dict[str, Any]], record_id: str
) -> list[dict[str, Any]]:
    return [row for row in records if row.get("record_id") == record_id]


def _check_idempotent_or_fail(
    rows: list[dict[str, Any]], candidate: dict[str, Any], record_id: str
) -> str:
    candidates = _find_records(rows, record_id)
    if not candidates:
        return "append"
    if all(
        _normalize_record(candidate) != _normalize_record(row) for row in candidates
    ):
        return "conflict"
    return "noop"


def _append_candidate(
    paths: Paths,
    records: dict[str, list[dict[str, Any]]],
    ledger: str,
    record_id: str,
    payload: dict[str, Any],
) -> bool:
    _ensure_dir(paths.network_dir, "network dir")
    target = paths.ledger(ledger)
    state = _check_idempotent_or_fail(
        records[ledger], {"record_id": record_id, **payload}, record_id
    )
    if state == "conflict":
        print(
            f"{ledger} record {record_id!r} already exists with different payload",
            file=sys.stderr,
        )
        return False
    if state == "noop":
        return True

    next_sequence = _next_sequence(records)
    row = {
        "schema_version": SCHEMA_VERSION,
        "network_id": paths.network_id,
        "record_id": record_id,
        "sequence": next_sequence,
        "recorded_at": _utcnow(),
        **payload,
    }
    _append_jsonl(target, row)
    records[ledger].append(row)
    return True


def _append_event(
    paths: Paths,
    records: dict[str, list[dict[str, Any]]],
    event_type: str,
    payload: dict[str, Any],
) -> None:
    next_sequence = _next_sequence(records)
    timestamp = _utcnow()
    event = {
        "schema_version": SCHEMA_VERSION,
        "network_id": paths.network_id,
        "record_id": _record_id("event", event_type, str(next_sequence)),
        "sequence": next_sequence,
        "recorded_at": timestamp,
        "event_type": event_type,
        **payload,
    }
    _append_jsonl(paths.ledger("events"), event)
    records["events"].append(event)


def _append_source_row(
    paths: Paths, records: dict[str, list[dict[str, Any]]], payload: dict[str, Any]
) -> bool:
    next_sequence = _next_sequence(records)
    source_id = payload.get("source_id")
    if not isinstance(source_id, str):
        return False
    row = {
        "schema_version": SCHEMA_VERSION,
        "network_id": paths.network_id,
        "record_id": _record_id("source", source_id),
        "sequence": next_sequence,
        "recorded_at": _utcnow(),
        **payload,
    }
    _append_jsonl(paths.ledger("sources"), row)
    records["sources"].append(row)
    return True


@contextmanager
def _exclusive_lock(paths: Paths):
    path = paths.lock
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_symlink():
        raise ValueError(f"lock file is symlink: {path}")
    with path.open("a+", encoding="utf-8") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _collect_known_record_ids(
    records: dict[str, list[dict[str, Any]]],
) -> dict[str, set[str]]:
    return {
        "sources": {
            row.get("source_id")
            for row in records["sources"]
            if isinstance(row.get("source_id"), str)
        },
        "entities": {
            row.get("entity_id")
            for row in records["entities"]
            if isinstance(row.get("entity_id"), str)
        },
        "claims": {
            row.get("claim_id")
            for row in records["claims"]
            if isinstance(row.get("claim_id"), str)
        },
        "evidence": {
            row.get("evidence_id")
            for row in records["evidence"]
            if isinstance(row.get("evidence_id"), str)
        },
        "relations": {
            row.get("relation_id")
            for row in records["relations"]
            if isinstance(row.get("relation_id"), str)
        },
        "gaps": {
            row.get("gap_id")
            for row in records["gaps"]
            if isinstance(row.get("gap_id"), str)
        },
    }


def _validate_snapshot_state(  # noqa: C901
    paths: Paths,
    state: dict[str, Any],
    source_rows: list[dict[str, Any]],
    errors: list[str],
) -> None:
    if state.get("schema_version") != SCHEMA_VERSION:
        errors.append("network.json schema_version mismatch")
    if state.get("network_id") != paths.network_id:
        errors.append("state network_id mismatch")

    snapshot_path = state.get("corpus_snapshot_path")
    if not isinstance(snapshot_path, str):
        errors.append("corpus_snapshot_path missing")
        return

    snapshot_file = Path(snapshot_path)
    try:
        snapshot, file_digest = _read_stable_snapshot(snapshot_file)
        if snapshot.get("schema") == ZOTERO_SNAPSHOT_SCHEMA:
            _validate_zotero_snapshot(snapshot)
            state_digest = _zotero_snapshot_state_digest(snapshot)
            if state.get("corpus_snapshot_digest") != state_digest:
                errors.append("corpus snapshot state digest mismatch")
        elif state.get("corpus_snapshot_digest") != file_digest:
            errors.append("legacy corpus snapshot digest mismatch")
        if state.get("corpus_snapshot_file_sha256") != file_digest:
            errors.append("corpus snapshot file digest mismatch")
        identity = state.get("corpus_snapshot_identity_sha256")
        if identity is not None:
            snapshot_identity = snapshot.get("identity_sha256")
            if snapshot_identity != identity:
                errors.append("corpus snapshot identity digest mismatch")
        state_snapshot_sha = state.get("corpus_snapshot_state_sha256")
        if state_snapshot_sha is not None:
            snapshot_state_sha = _zotero_snapshot_state_digest(snapshot)
            if snapshot_state_sha is None or snapshot_state_sha != state_snapshot_sha:
                errors.append("corpus snapshot state digest mismatch")
        current_sources = state.get("corpus_snapshot_current_source_ids")
        if current_sources is not None and not isinstance(current_sources, list):
            errors.append("corpus snapshot current sources must be a list")
        elif isinstance(current_sources, list):
            if len(current_sources) != len(set(current_sources)):
                errors.append("corpus snapshot current sources contain duplicates")
            if not all(
                isinstance(source_id, str) and ID_RE.fullmatch(source_id)
                for source_id in current_sources
            ):
                errors.append("corpus snapshot current sources contain invalid IDs")
        if snapshot.get("schema") == ZOTERO_SNAPSHOT_SCHEMA:
            _validate_snapshot_membership(snapshot, state, source_rows, errors)
    except (OSError, ValueError):
        errors.append("snapshot unavailable or invalid for digest check")


def _validate_snapshot_membership(
    snapshot: dict[str, Any],
    state: dict[str, Any],
    source_rows: list[dict[str, Any]],
    errors: list[str],
) -> None:
    if "corpus_snapshot_current_source_ids" not in state:
        return
    snapshot_state = _zotero_snapshot_state_digest(snapshot) or ""
    expected: list[tuple[str, dict[str, Any]]] = []
    for parent in _snapshot_parents_sorted(snapshot.get("parents", [])):
        expected.append(
            _source_payload_from_parent(parent, snapshot, snapshot_state)
        )
    expected_ids = [source_id for source_id, _ in expected]
    current_ids = _corpus_snapshot_current_source_ids(state)
    if current_ids != expected_ids:
        errors.append("corpus snapshot current membership mismatch")

    latest_by_id: dict[str, dict[str, Any]] = {}
    for row in sorted(source_rows, key=lambda item: int(item.get("sequence") or 0)):
        source_id = row.get("source_id")
        if isinstance(source_id, str):
            latest_by_id[source_id] = row
    for source_id, expected_payload in expected:
        actual = latest_by_id.get(source_id)
        if actual is None:
            errors.append(f"current snapshot source row missing: {source_id}")
        elif _source_row_signature(actual) != _source_row_signature(
            expected_payload
        ):
            errors.append(f"current snapshot source payload mismatch: {source_id}")


def _validate_zotero_source_record(
    row: dict[str, Any], known_sources: set[str], errors: list[str]
) -> None:
    source_id = row.get("source_id")
    if row.get("read_depth") != "metadata":
        errors.append(f"Zotero source {source_id} must remain metadata-only")
    if not isinstance(row.get("zotero_parent_key"), str):
        errors.append(f"Zotero source {source_id} missing parent key")
    snapshot_state = row.get("snapshot_state")
    if not isinstance(snapshot_state, dict) or not SNAPSHOT_DIGEST_RE.fullmatch(
        str(snapshot_state.get("state_sha256", ""))
    ):
        errors.append(f"Zotero source {source_id} snapshot state invalid")
    supersedes = row.get("supersedes")
    if supersedes is not None and supersedes not in known_sources:
        errors.append(
            f"Zotero source {source_id} supersedes unknown source {supersedes}"
        )


def _validate_source_record(
    row: dict[str, Any], network_id: str, errors: list[str]
) -> None:
    source_id = row.get("source_id")
    if row.get("schema_version") != SCHEMA_VERSION:
        errors.append("source record schema_version mismatch")
    if row.get("network_id") != network_id:
        errors.append(f"source {row.get('record_id')} network mismatch")
    if not ID_RE.fullmatch(str(source_id or "")):
        errors.append(f"invalid source_id: {source_id!r}")
    if row.get("record_id") != _record_id("source", str(source_id or "")):
        errors.append(f"source record_id mismatch: {row.get('record_id')}")
    if not isinstance(row.get("canonical_version"), str) or not row[
        "canonical_version"
    ].strip():
        errors.append(f"source {source_id} missing canonical_version")
    if row.get("read_depth") not in READ_DEPTHS:
        errors.append(f"invalid read_depth for source {source_id}")
    if not SNAPSHOT_DIGEST_RE.fullmatch(str(row.get("version_hash", ""))):
        errors.append(f"invalid version_hash for source {source_id}")


def _validate_source_records(
    rows: list[dict[str, Any]], network_id: str, errors: list[str]
) -> None:
    known_sources = {
        row.get("source_id")
        for row in rows
        if isinstance(row.get("source_id"), str)
    }
    for row in rows:
        _validate_source_record(row, network_id, errors)
        if row.get("role") == "zotero_corpus":
            _validate_zotero_source_record(row, known_sources, errors)


def _validate_entity_records(
    rows: list[dict[str, Any]],
    known_entities: set[str],
    network_id: str,
    errors: list[str],
) -> None:
    for row in rows:
        if row.get("schema_version") != SCHEMA_VERSION:
            errors.append("entity record schema_version mismatch")
        if row.get("network_id") != network_id:
            errors.append(f"entity {row.get('record_id')} network mismatch")
        entity_id = row.get("entity_id")
        if not ID_RE.fullmatch(str(entity_id or "")):
            errors.append(f"invalid entity_id: {entity_id!r}")
        if row.get("record_id") != _record_id("entity", str(entity_id or "")):
            errors.append(f"entity record_id mismatch: {row.get('record_id')}")
        if not isinstance(row.get("name"), str) or not row["name"].strip():
            errors.append(f"entity {entity_id} missing name")
        if row.get("is_factual", False) is True:
            errors.append(f"entity {entity_id} cannot be factual")
        supersedes = row.get("supersedes")
        if supersedes is not None and supersedes not in known_entities:
            errors.append(f"entity {entity_id} supersedes unknown entity {supersedes}")


def _validate_claim_records(
    rows: list[dict[str, Any]], known_entities: set[str], errors: list[str]
) -> None:
    for row in rows:
        _validate_claim_record(row, known_entities, errors)


def _validate_claim_record(
    row: dict[str, Any], known_entities: set[str], errors: list[str]
) -> None:
    if row.get("schema_version") != SCHEMA_VERSION:
        errors.append("claim record schema_version mismatch")
    claim_id = row.get("claim_id")
    if not ID_RE.fullmatch(str(claim_id or "")):
        errors.append(f"invalid claim_id: {claim_id!r}")
    if row.get("record_id") != _record_id("claim", str(claim_id or "")):
        errors.append(f"claim record_id mismatch: {row.get('record_id')}")
    if row.get("is_factual", False) is True:
        errors.append(f"claim {claim_id} cannot be factual")
    if row.get("impact") not in IMPACTS:
        errors.append(f"claim {claim_id} invalid impact")
    if _value_missing_text(row.get("claim_text")):
        errors.append(f"claim {claim_id} missing claim_text")
    entity_id = row.get("entity_id")
    if entity_id is not None and entity_id not in known_entities:
        errors.append(f"claim {claim_id} references unknown entity {entity_id}")
    scope_statement = row.get("scope_statement", "")
    if not isinstance(scope_statement, str):
        errors.append(f"claim {claim_id} scope_statement must be string")
    for field in (
        "assumptions",
        "conditions",
        "units",
        "exclusions",
        "defeaters",
        "coverage_dimensions",
        "benchmark_profiles",
    ):
        values = row.get(field, [])
        if not isinstance(values, list):
            errors.append(f"claim {claim_id} {field} must be list")
            continue
        valid_items = all(isinstance(item, str) and item for item in values)
        if not valid_items:
            errors.append(f"claim {claim_id} {field} contains invalid item")
        elif len(values) != len(set(values)):
            errors.append(f"claim {claim_id} {field} contains duplicates")


def _validate_evidence_records(
    rows: list[dict[str, Any]],
    known_claims: set[str],
    known_sources: set[str],
    known_evidence: set[str],
    errors: list[str],
) -> None:
    for row in rows:
        _validate_evidence_record(
            row,
            known_claims,
            known_sources,
            known_evidence,
            errors,
        )


def _validate_evidence_record(
    row: dict[str, Any],
    known_claims: set[str],
    known_sources: set[str],
    known_evidence: set[str],
    errors: list[str],
) -> None:
    if row.get("schema_version") != SCHEMA_VERSION:
        errors.append("evidence record schema_version mismatch")
    evidence_id = row.get("evidence_id")
    if not ID_RE.fullmatch(str(evidence_id or "")):
        errors.append(f"invalid evidence_id: {evidence_id!r}")
    if row.get("record_id") != _record_id("evidence", str(evidence_id or "")):
        errors.append(f"evidence record_id mismatch: {row.get('record_id')}")
    claim_id = row.get("claim_id")
    source_id = row.get("source_id")
    if claim_id not in known_claims:
        errors.append(f"evidence {evidence_id} references unknown claim {claim_id}")
    if source_id not in known_sources:
        errors.append(f"evidence {evidence_id} references unknown source {source_id}")
    if row.get("polarity") not in EVIDENCE_POLARITY:
        errors.append(f"evidence {evidence_id} invalid polarity")
    if _value_missing_text(row.get("exact_locator")):
        errors.append(f"evidence {evidence_id} missing exact_locator")
    if _value_missing_text(row.get("independence_group")):
        errors.append(f"evidence {evidence_id} missing independence_group")
    if _references_unknown_supersede(row.get("supersedes"), known_evidence):
        errors.append(
            f"evidence {evidence_id} supersedes unknown evidence "
            f"{row['supersedes']}"
        )


def _validate_relation_records(
    rows: list[dict[str, Any]],
    known_claims: set[str],
    known_evidence: set[str],
    known_relations: set[str],
    errors: list[str],
) -> None:
    for row in rows:
        relation_id = row.get("relation_id")
        if not ID_RE.fullmatch(str(relation_id or "")):
            errors.append(f"invalid relation_id: {relation_id!r}")
        if row.get("record_id") != _record_id("relation", str(relation_id or "")):
            errors.append(f"relation record_id mismatch: {row.get('record_id')}")
        if row.get("relation_type") not in RELATION_TYPES:
            errors.append(f"relation {relation_id} invalid relation_type")
        from_ref = row.get("from")
        to_ref = row.get("to")
        if not _valid_ref(from_ref) or not _valid_ref(to_ref):
            errors.append(f"relation {relation_id} has invalid from/to refs")
        else:
            if from_ref and not _ref_exists(from_ref, known_claims, known_evidence):
                errors.append(
                    f"relation {relation_id} references missing from ref {from_ref}"
                )
            if to_ref and not _ref_exists(to_ref, known_claims, known_evidence):
                errors.append(
                    f"relation {relation_id} references missing to ref {to_ref}"
                )
        if not _is_claim_or_evidence_ref(from_ref) or not _is_claim_or_evidence_ref(
            to_ref
        ):
            errors.append(f"relation {relation_id} must reference claim/evidence")
        if (
            row.get("supersedes") is not None
            and row["supersedes"] not in known_relations
        ):
            errors.append(
                f"relation {relation_id} supersedes unknown relation "
                f"{row['supersedes']}"
            )


def _validate_gap_records(
    rows: list[dict[str, Any]],
    known_claims: set[str],
    evidence_rows: list[dict[str, Any]],
    errors: list[str],
) -> None:
    evidence_by_id = {
        str(row["evidence_id"]): row
        for row in evidence_rows
        if isinstance(row.get("evidence_id"), str)
    }
    latest_by_gap: dict[str, dict[str, Any]] = {}
    ordered = sorted(rows, key=lambda row: int(row.get("sequence") or 0))
    for row in ordered:
        _validate_gap_record(row, known_claims, errors)
        gap_id = row.get("gap_id")
        record_id = row.get("record_id")
        if not isinstance(gap_id, str) or not isinstance(record_id, str):
            continue
        transition_from = row.get("transition_from_record_id")
        if transition_from is None:
            if record_id != _gap_initial_record_id(gap_id):
                errors.append(f"gap {gap_id} initial record_id invalid")
            if gap_id in latest_by_gap:
                errors.append(f"gap {gap_id} has a second initial record")
            _validate_gap_resolution(
                row,
                "resolution_evidence_refs",
                evidence_by_id,
                errors,
            )
        else:
            prior = latest_by_gap.get(gap_id)
            if prior is None:
                errors.append(f"gap {gap_id} transition has no prior record")
                continue
            _validate_gap_transition(row, prior, gap_id, evidence_by_id, errors)
        latest_by_gap[gap_id] = row


def _validate_gap_transition(
    row: dict[str, Any],
    prior: dict[str, Any],
    gap_id: str,
    evidence_by_id: dict[str, dict[str, Any]],
    errors: list[str],
) -> None:
    prior_record_id = prior.get("record_id")
    if row.get("transition_from_record_id") != prior_record_id:
        errors.append(
            f"gap {gap_id} transition does not reference latest record"
        )
    if row.get("supersedes") != prior_record_id:
        errors.append(f"gap {gap_id} transition supersedes mismatch")
    sequence = row.get("sequence")
    expected_record_id = (
        _gap_transition_record_id(gap_id, sequence)
        if isinstance(sequence, int)
        else None
    )
    if row.get("record_id") != expected_record_id:
        errors.append(f"gap {gap_id} transition record_id invalid")
    prior_status = prior.get("status")
    next_status = row.get("status")
    if next_status not in GAP_STATUS_TRANSITIONS.get(str(prior_status), set()):
        errors.append(
            f"gap {gap_id} invalid transition {prior_status!r}->{next_status!r}"
        )
    if _value_missing_text(row.get("transition_reason")):
        errors.append(f"gap {gap_id} transition reason missing")
    _validate_gap_resolution(
        row,
        "transition_evidence_refs",
        evidence_by_id,
        errors,
    )


def _resolution_evidence_error(
    claim_id: Any,
    evidence_refs: Any,
    resolution_source: Any,
    evidence_by_id: dict[str, dict[str, Any]],
) -> str | None:
    if not isinstance(evidence_refs, list) or not evidence_refs:
        return "resolution requires evidence references"
    if not all(isinstance(ref, str) and ref in evidence_by_id for ref in evidence_refs):
        return "resolution references unknown evidence"
    if isinstance(claim_id, str):
        if not all(
            evidence_by_id[ref].get("claim_id") == claim_id for ref in evidence_refs
        ):
            return "resolution evidence must reference the gap claim"
    elif not isinstance(resolution_source, str) or not resolution_source.strip():
        return "claimless resolution requires an explicit resolution source"
    return None


def _validate_gap_resolution(
    row: dict[str, Any],
    evidence_field: str,
    evidence_by_id: dict[str, dict[str, Any]],
    errors: list[str],
) -> None:
    if row.get("status") != "resolved":
        return
    message = _resolution_evidence_error(
        row.get("claim_id"),
        row.get(evidence_field),
        row.get("resolution_source"),
        evidence_by_id,
    )
    if message:
        errors.append(f"gap {row.get('gap_id')} {message}")


def _record_gap_resolution_error(
    payload: dict[str, Any],
    claim_id: str | None,
    evidence_rows: list[dict[str, Any]],
) -> str | None:
    if payload.get("status") != "resolved":
        return None
    evidence_by_id = {
        str(row["evidence_id"]): row
        for row in evidence_rows
        if isinstance(row.get("evidence_id"), str)
    }
    return _resolution_evidence_error(
        claim_id,
        payload.get("resolution_evidence_refs"),
        payload.get("resolution_source"),
        evidence_by_id,
    )


def _validate_gap_record(
    row: dict[str, Any], known_claims: set[str], errors: list[str]
) -> None:
    gap_id = row.get("gap_id")
    if row.get("schema_version") != SCHEMA_VERSION:
        errors.append(f"gap {gap_id} schema_version mismatch")
    if not GAP_ID_RE.fullmatch(str(gap_id or "")):
        errors.append(f"invalid gap_id: {gap_id!r}")
    if not ID_RE.fullmatch(str(row.get("record_id") or "")):
        errors.append(f"gap record_id mismatch: {row.get('record_id')}")
    if row.get("gap_type") not in GAP_TYPES:
        errors.append(f"gap {gap_id} invalid gap_type")
    if row.get("status") not in GAP_STATUSES:
        errors.append(f"gap {gap_id} invalid status")
    priority = row.get("priority")
    if priority is not None and priority not in GAP_PRIORITIES:
        errors.append(f"gap {gap_id} invalid priority")
    decision_impact = row.get("decision_impact")
    if decision_impact is not None and decision_impact not in IMPACTS:
        errors.append(f"gap {gap_id} invalid decision_impact")
    if row.get("gap_type") == "implicit_candidate":
        _validate_implicit_gap_record(row, gap_id, known_claims, errors)


def _validate_implicit_gap_record(
    row: dict[str, Any],
    gap_id: str | None,
    known_claims: set[str],
    errors: list[str],
) -> None:
    for key in (
        "grounds",
        "warrant",
        "backing",
        "qualifier",
        "defeaters",
        "search_test",
    ):
        if _value_missing_text(row.get(key)):
            errors.append(f"gap {gap_id} missing {key}")
    if row.get("novelty_claimed") is True:
        errors.append(f"gap {gap_id} sets novelty_claimed in implicit_candidate")
    claim_id = row.get("claim_id")
    if claim_id is not None and claim_id not in known_claims:
        errors.append(f"gap {gap_id} references unknown claim {claim_id}")


def _value_missing_text(value: Any) -> bool:
    return not isinstance(value, str) or not value.strip()


def _value_is_nonlist(value: Any) -> bool:
    return value is not None and not isinstance(value, list)


def _references_unknown_supersede(value: Any, known: set[str]) -> bool:
    return value is not None and value not in known


def _validate_event_records(
    rows: list[dict[str, Any]], errors: list[str], expected_network_id: str
) -> None:
    for row in rows:
        if row.get("schema_version") != SCHEMA_VERSION:
            errors.append("event record schema_version mismatch")
        event_type = row.get("event_type")
        if event_type not in EVENT_TYPES:
            errors.append(f"event {row.get('record_id')} invalid event_type")
        if event_type == "patch_decision":
            _validate_patch_decision_event(row, errors, expected_network_id)


def _validate_patch_decision_event(
    row: dict[str, Any], errors: list[str], expected_network_id: str
) -> None:
    record_id = row.get("record_id")
    label = f"event {record_id}"
    expected_fields = {
        "schema_version",
        "network_id",
        "record_id",
        "sequence",
        "recorded_at",
        "event_type",
        "event_digest",
        "proposal_id",
        "proposal_digest",
        "plan_id",
        "plan_digest",
        "acceptance_id",
        "acceptance_digest",
        "decided_at",
        "operator",
        "decisions",
    }
    if set(row) != expected_fields:
        errors.append(f"{label} patch_decision fields invalid")
        return
    if row.get("network_id") != expected_network_id:
        errors.append(f"{label} network_id mismatch")
    digest_fields = (
        ("proposal", "proposal_id", "proposal_digest", "network-patch-proposal-"),
        ("plan", "plan_id", "plan_digest", "network-patch-plan-"),
        (
            "acceptance",
            "acceptance_id",
            "acceptance_digest",
            "network-patch-acceptance-",
        ),
    )
    for name, id_field, digest_field, prefix in digest_fields:
        digest = row.get(digest_field)
        if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
            errors.append(f"{label} {name} digest invalid")
        elif row.get(id_field) != prefix + digest[:16]:
            errors.append(f"{label} {name} ID/digest mismatch")
    event_digest = row.get("event_digest")
    if not isinstance(event_digest, str) or not re.fullmatch(
        r"[0-9a-f]{64}", event_digest
    ):
        errors.append(f"{label} event_digest invalid")
    else:
        subject = {
            key: value
            for key, value in row.items()
            if key
            not in {
                "schema_version",
                "record_id",
                "sequence",
                "recorded_at",
                "event_digest",
            }
        }
        expected_digest = _sha256_json(subject).split(":", 1)[1]
        if event_digest != expected_digest:
            errors.append(f"{label} event_digest mismatch")
        expected_record_id = _record_id("event", "patch", event_digest[:16])
        if record_id != expected_record_id:
            errors.append(f"{label} record ID/digest mismatch")
    try:
        datetime.strptime(str(row.get("decided_at")), "%Y-%m-%dT%H:%M:%SZ")
    except ValueError:
        errors.append(f"{label} decided_at invalid")
    try:
        datetime.strptime(str(row.get("recorded_at")), "%Y-%m-%dT%H:%M:%SZ")
    except ValueError:
        errors.append(f"{label} recorded_at invalid")
    operator = row.get("operator")
    if not isinstance(operator, dict) or set(operator) != {
        "operator_id",
        "operator_role",
        "authority_basis",
    }:
        errors.append(f"{label} operator fields invalid")
        return
    if _value_missing_text(operator.get("operator_id")) or _value_missing_text(
        operator.get("operator_role")
    ):
        errors.append(f"{label} operator identity invalid")
    authority = operator.get("authority_basis")
    if not isinstance(authority, list) or not authority:
        errors.append(f"{label} authority basis missing")
        return
    authority_ids: set[str] = set()
    for index, basis in enumerate(authority):
        if not isinstance(basis, dict) or set(basis) != {
            "basis_id",
            "basis_type",
            "source_ref",
            "locator",
            "artifact_sha256",
        }:
            errors.append(f"{label} authority basis[{index}] fields invalid")
            continue
        artifact_digest = basis.get("artifact_sha256")
        if not isinstance(artifact_digest, str) or not re.fullmatch(
            r"[0-9a-f]{64}", artifact_digest
        ):
            errors.append(f"{label} authority basis[{index}] digest invalid")
        if basis.get("basis_type") not in {
            "expert_review",
            "curation_policy",
            "user_authorization",
        }:
            errors.append(f"{label} authority basis[{index}] type invalid")
        if _value_missing_text(basis.get("source_ref")) or _value_missing_text(
            basis.get("locator")
        ):
            errors.append(f"{label} authority basis[{index}] locator invalid")
        subject = {key: value for key, value in basis.items() if key != "basis_id"}
        expected_id = (
            "patch-authority-basis-"
            + _sha256_json(subject).split(":", 1)[1][:16]
        )
        if basis.get("basis_id") != expected_id:
            errors.append(f"{label} authority basis[{index}] ID mismatch")
        else:
            if expected_id in authority_ids:
                errors.append(f"{label} duplicate authority basis")
            authority_ids.add(expected_id)
    decisions = row.get("decisions")
    if not isinstance(decisions, list) or not decisions:
        errors.append(f"{label} decisions missing")
        return
    seen_actions: set[tuple[str, str]] = set()
    seen_operations: set[tuple[str, str]] = set()
    for index, decision in enumerate(decisions):
        decision_label = f"{label} decision[{index}]"
        if not isinstance(decision, dict) or set(decision) != {
            "action_id",
            "action_digest",
            "decision",
            "rationale",
            "authority_basis_ids",
            "operations",
        }:
            errors.append(f"{decision_label} fields invalid")
            continue
        action_digest = decision.get("action_digest")
        action_id = decision.get("action_id")
        if not isinstance(action_digest, str) or not re.fullmatch(
            r"[0-9a-f]{64}", action_digest
        ) or action_id != "network-patch-action-" + str(action_digest)[:16]:
            errors.append(f"{decision_label} action ID/digest mismatch")
        action_identity = (str(action_id), str(action_digest))
        if action_identity in seen_actions:
            errors.append(f"{decision_label} duplicate action")
        seen_actions.add(action_identity)
        decision_value = decision.get("decision")
        if decision_value not in {"accept", "reject", "defer"}:
            errors.append(f"{decision_label} decision invalid")
        if _value_missing_text(decision.get("rationale")):
            errors.append(f"{decision_label} rationale missing")
        cited = decision.get("authority_basis_ids")
        if (
            not isinstance(cited, list)
            or not cited
            or len(cited) != len(set(cited))
            or not set(cited).issubset(authority_ids)
        ):
            errors.append(f"{decision_label} authority binding invalid")
        operations = decision.get("operations")
        if not isinstance(operations, list):
            errors.append(f"{decision_label} operations invalid")
            continue
        if decision_value == "accept" and not operations:
            errors.append(f"{decision_label} accepted action lacks operations")
        if decision_value in {"reject", "defer"} and operations:
            errors.append(f"{decision_label} non-accepted action has operations")
        for op_index, operation in enumerate(operations):
            if not isinstance(operation, dict) or set(operation) != {
                "operation_id",
                "operation_digest",
            }:
                errors.append(
                    f"{decision_label} operation[{op_index}] fields invalid"
                )
                continue
            operation_digest = operation.get("operation_digest")
            operation_id = operation.get("operation_id")
            if not isinstance(operation_digest, str) or not re.fullmatch(
                r"[0-9a-f]{64}", operation_digest
            ) or operation_id != "network-operation-" + str(operation_digest)[:16]:
                errors.append(
                    f"{decision_label} operation[{op_index}] ID/digest mismatch"
                )
            operation_identity = (str(operation_id), str(operation_digest))
            if operation_identity in seen_operations:
                errors.append(f"{decision_label} duplicate operation")
            seen_operations.add(operation_identity)


def _validate_sequence_continuity(
    rows_by_ledger: dict[str, list[dict[str, Any]]], errors: list[str]
) -> None:
    sequence_expected = 1
    for row in _ordered_records(rows_by_ledger):
        if row.get("sequence") != sequence_expected:
            errors.append("sequence must be continuous starting at 1")
            break
        sequence_expected += 1


def _validate_record_id_collisions(
    rows_by_ledger: dict[str, list[dict[str, Any]]], errors: list[str]
) -> None:
    for ledger_name in LEDGER_NAMES:
        seen: dict[str, dict[str, Any]] = {}
        for row in rows_by_ledger[ledger_name]:
            rid = row.get("record_id")
            if not isinstance(rid, str):
                errors.append(f"{ledger_name} has non-string record_id")
                continue
            normalized = _normalize_record(row)
            if rid in seen and _normalize_record(seen[rid]) != normalized:
                errors.append(
                    f"{ledger_name} id collision with different payload: {rid}"
                )
            seen[rid] = row


def _validate_record_shapes(
    paths: Paths, state: dict[str, Any], records: dict[str, list[dict[str, Any]]]
) -> list[str]:
    errors: list[str] = []

    _validate_snapshot_state(paths, state, records["sources"], errors)

    known = _collect_known_record_ids(records)
    _validate_source_records(records["sources"], paths.network_id, errors)
    _validate_entity_records(
        records["entities"], known["entities"], paths.network_id, errors
    )
    _validate_claim_records(records["claims"], known["entities"], errors)
    _validate_evidence_records(
        records["evidence"],
        known["claims"],
        known["sources"],
        known["evidence"],
        errors,
    )
    _validate_relation_records(
        records["relations"],
        known["claims"],
        known["evidence"],
        known["relations"],
        errors,
    )
    _validate_gap_records(
        records["gaps"], known["claims"], records["evidence"], errors
    )
    _validate_event_records(records["events"], errors, paths.network_id)
    _validate_sequence_continuity(records, errors)
    _validate_record_id_collisions(records, errors)

    return errors


def _ordered_records(records: dict[str, list[dict[str, Any]]]) -> list[dict[str, Any]]:
    all_rows: list[tuple[int, dict[str, Any]]] = []
    for _, rows in records.items():
        for row in rows:
            sequence = row.get("sequence")
            if not isinstance(sequence, int):
                all_rows.append((-1, row))
            else:
                all_rows.append((sequence, row))
    all_rows.sort(key=lambda item: item[0])
    return [row for _, row in all_rows]


def _valid_ref(ref: Any) -> bool:
    if not isinstance(ref, str):
        return False
    head, _, tail = ref.partition(":")
    if head not in {"claim", "evidence"}:
        return False
    return bool(tail) and ID_RE.fullmatch(tail)


def _is_claim_or_evidence_ref(ref: Any) -> bool:
    return _valid_ref(ref)


def _ref_exists(ref: str, known_claims: set[str], known_evidence: set[str]) -> bool:
    namespace, _, value = ref.partition(":")
    if namespace == "claim":
        return value in known_claims
    if namespace == "evidence":
        return value in known_evidence
    return False


def _derive_topology(records: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    claim_ids = {
        row["claim_id"]
        for row in records["claims"]
        if isinstance(row.get("claim_id"), str)
    }
    incident_claims: set[str] = set()
    for row in records["relations"]:
        for key in ("from", "to"):
            ref = row.get(key)
            if not isinstance(ref, str):
                continue
            namespace, _, value = ref.partition(":")
            if namespace == "claim":
                incident_claims.add(value)
    for row in records["evidence"]:
        claim_id = row.get("claim_id")
        if isinstance(claim_id, str):
            incident_claims.add(claim_id)
    return {
        "claim_ids": sorted(claim_ids),
        "isolated_claims": sorted(claim_ids - incident_claims),
    }


def _make_gap_id(prefix: str, claim_id: str, extra: str | None = None) -> str:
    kind = prefix.removeprefix("derived_").replace("_", "-")
    if extra:
        return f"derived:{kind}:{claim_id}:{_gap_id_component(extra)}"
    return f"derived:{kind}:{claim_id}"


def _gap_id_component(value: str) -> str:
    value = value.strip()
    if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,119}", value):
        return value
    slug = re.sub(r"[^A-Za-z0-9._-]+", "-", value).strip(".-")[:96]
    digest = hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]
    return f"{slug or 'value'}-{digest}"


def _aggregate_gap_id(kind: str, value: str) -> str:
    return f"derived:{kind}:{_gap_id_component(value)}"


def _derive_conflicts(records: dict[str, list[dict[str, Any]]]) -> list[str]:
    by_claim: dict[str, list[dict[str, Any]]] = {}
    for row in records["evidence"]:
        claim_id = row.get("claim_id")
        if not isinstance(claim_id, str):
            continue
        by_claim.setdefault(claim_id, []).append(row)

    conflicts: list[str] = []
    for claim_id, evidences in by_claim.items():
        support_groups = {
            row.get("independence_group")
            for row in evidences
            if isinstance(row.get("independence_group"), str)
            and row.get("polarity") == "supports"
        }
        contradict_groups = {
            row.get("independence_group")
            for row in evidences
            if isinstance(row.get("independence_group"), str)
            and row.get("polarity") == "contradicts"
        }
        if support_groups and contradict_groups:
            conflicts.append(claim_id)
    return sorted(set(conflicts))


def _derive_status_summary(
    paths: Paths, state: dict[str, Any], records: dict[str, list[dict[str, Any]]]
) -> dict[str, Any]:
    required_dimensions = sorted(_sort_items(state.get("required_dimensions", [])))
    required_profiles = sorted(
        _sort_items(state.get("required_benchmark_profiles", []))
    )
    active_claims = _active_records(records["claims"], "claim_id")
    active_evidence = _active_records(records["evidence"], "evidence_id")
    claim_map = _collect_claim_map(active_claims)
    by_claim = _group_evidence_by_claim(active_evidence)
    open_conflicts = _derive_conflicts(records)
    high_impact_open = _count_high_impact_open_claims(claim_map, by_claim)
    open_gaps = _collect_open_gaps(records["gaps"])
    blocking_explicit_gaps = _collect_blocking_open_explicit_gaps(records["gaps"])
    coverage = _collect_aggregate_coverage(
        records["claims"],
        records["evidence"],
        required_dimensions,
        required_profiles,
    )
    blockers = _collect_completion_blockers(
        high_impact_open,
        open_conflicts,
        coverage["missing_dimensions"],
        coverage["missing_benchmark_profiles"],
        blocking_explicit_gaps,
    )
    has_current_membership = "corpus_snapshot_current_source_ids" in state
    current_sources = _corpus_snapshot_current_source_ids(state)
    if not has_current_membership:
        current_sources = sorted(
            {
                str(row.get("source_id"))
                for row in records["sources"]
                if isinstance(row.get("source_id"), str)
            }
        )

    return {
        "network_id": paths.network_id,
        "schema_version": SCHEMA_VERSION,
        "counts": {name: len(records[name]) for name in LEDGER_NAMES},
        "open_conflicts": open_conflicts,
        "open_gaps": sorted(set(open_gaps)),
        "open_high_priority_explicit_gap_ids": blocking_explicit_gaps,
        "high_impact_claims_with_no_decisive_evidence": high_impact_open,
        "coverage": {
            "required_dimensions": required_dimensions,
            "required_benchmark_profiles": required_profiles,
            **coverage,
        },
        "completion": {
            "can_complete": not blockers,
            "blockers": blockers,
        },
        "snapshot": {
            "path": state.get("corpus_snapshot_path"),
            "digest": state.get("corpus_snapshot_digest"),
            "current_count": len(current_sources),
            "current_sources": current_sources,
            "identity_sha256": state.get("corpus_snapshot_identity_sha256"),
            "state_sha256": state.get("corpus_snapshot_state_sha256"),
        },
    }


def _collect_claim_map(
    claim_records: list[dict[str, Any]],
) -> dict[str | None, dict[str, Any]]:
    return {
        row.get("claim_id"): row
        for row in claim_records
        if isinstance(row.get("claim_id"), str)
    }


def _group_evidence_by_claim(
    evidence_records: list[dict[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    by_claim: dict[str, list[dict[str, Any]]] = {}
    for row in evidence_records:
        claim_id = row.get("claim_id")
        if isinstance(claim_id, str):
            by_claim.setdefault(claim_id, []).append(row)
    return by_claim


def _count_high_impact_open_claims(
    claim_map: dict[str | None, dict[str, Any]],
    by_claim: dict[str, list[dict[str, Any]]],
) -> int:
    count = 0
    for claim_id, claim in claim_map.items():
        if claim.get("impact") != "high":
            continue
        evidences = by_claim.get(claim_id, [])
        if not evidences:
            count += 1
            continue
        decisive = {
            row.get("polarity")
            for row in evidences
            if row.get("polarity") in DECISIVE_COVERAGE_POLARITIES
        }
        if not decisive:
            count += 1
    return count


def _collect_open_gaps(gaps: list[dict[str, Any]]) -> list[str]:
    latest = _latest_gaps_by_id(gaps)
    return sorted(
        gap_id for gap_id, row in latest.items() if row.get("status") == "open"
    )


def _collect_blocking_open_explicit_gaps(
    gaps: list[dict[str, Any]],
) -> list[str]:
    blocking: list[str] = []
    for gap_id, row in _latest_gaps_by_id(gaps).items():
        if (
            row.get("status") != "open"
            or row.get("gap_type") != "explicit"
            or row.get("claim_id") is not None
        ):
            continue
        priority = row.get("priority")
        decision_impact = row.get("decision_impact")
        explicitly_blocking = priority in {"P0", "P1"} or decision_impact == "high"
        legacy_blocking = (
            priority is None
            and decision_impact is None
            and row.get("impact") in {"high", "medium"}
        )
        if explicitly_blocking or legacy_blocking:
            blocking.append(gap_id)
    return sorted(blocking)


def _active_records(
    rows: list[dict[str, Any]], identity_field: str
) -> list[dict[str, Any]]:
    superseded = {
        row["supersedes"]
        for row in rows
        if isinstance(row.get("supersedes"), str)
    }
    return [
        row
        for row in rows
        if isinstance(row.get(identity_field), str)
        and row[identity_field] not in superseded
    ]


def _collect_aggregate_coverage(
    claims: list[dict[str, Any]],
    evidence: list[dict[str, Any]],
    required_dimensions: list[str],
    required_profiles: list[str],
) -> dict[str, list[str]]:
    required_dimension_set = set(_sort_items(required_dimensions))
    required_profile_set = set(_sort_items(required_profiles))
    active_claims = _active_records(claims, "claim_id")
    active_evidence = _active_records(evidence, "evidence_id")
    evidence_backed_claim_ids = {
        row["claim_id"]
        for row in active_evidence
        if isinstance(row.get("claim_id"), str)
        and row.get("polarity") in DECISIVE_COVERAGE_POLARITIES
    }
    covered_dimensions: set[str] = set()
    covered_profiles: set[str] = set()
    backed_active_claim_ids: list[str] = []
    for claim in active_claims:
        claim_id = str(claim["claim_id"])
        if claim_id not in evidence_backed_claim_ids:
            continue
        backed_active_claim_ids.append(claim_id)
        covered_dimensions.update(_sort_items(claim.get("coverage_dimensions", [])))
        covered_profiles.update(_sort_items(claim.get("benchmark_profiles", [])))
    return {
        "decisive_evidence_polarities": sorted(DECISIVE_COVERAGE_POLARITIES),
        "evidence_backed_active_claim_ids": sorted(backed_active_claim_ids),
        "covered_dimensions": sorted(covered_dimensions),
        "covered_benchmark_profiles": sorted(covered_profiles),
        "missing_dimensions": sorted(required_dimension_set - covered_dimensions),
        "missing_benchmark_profiles": sorted(
            required_profile_set - covered_profiles
        ),
    }


def _collect_completion_blockers(
    high_impact_open: int,
    open_conflicts: list[str],
    missing_dimensions: list[str],
    missing_profiles: list[str],
    blocking_explicit_gaps: list[str],
) -> list[str]:
    blockers: list[str] = []
    if high_impact_open:
        blockers.append("open_high_impact_claim")
    if open_conflicts:
        blockers.append("open_conflict")
    if missing_dimensions or missing_profiles:
        blockers.append("unmet_coverage")
    if blocking_explicit_gaps:
        blockers.append("open_high_priority_explicit_gap")
    return blockers


def _derive_gaps_payload_for_claim(
    claim_id: str,
    claim: dict[str, Any],
    evidences: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    payloads: list[dict[str, Any]] = []
    decisive = {
        row.get("polarity")
        for row in evidences
        if row.get("polarity") in DECISIVE_COVERAGE_POLARITIES
    }
    groups = {
        row.get("independence_group")
        for row in evidences
        if isinstance(row.get("independence_group"), str)
        and row.get("polarity") in DECISIVE_COVERAGE_POLARITIES
    }

    if claim.get("impact") == "high" and not decisive:
        payloads.append(
            {
                "gap_id": _make_gap_id("derived_unsupported_high_impact", claim_id),
                "gap_type": "explicit",
                "claim_id": claim_id,
                "impact": "high",
                "status": "open",
                "description": (
                    f"No decisive evidence for high-impact claim {claim_id}."
                ),
                "derivation_source": "derive-gaps",
                "derivation_rule": "unsupported_high_impact",
            }
        )

    if len(groups) == 1:
        payloads.append(
            {
                "gap_id": _make_gap_id("derived_single_source", claim_id),
                "gap_type": "deterministic_structural",
                "claim_id": claim_id,
                "impact": "medium" if claim.get("impact") != "high" else "high",
                "status": "open",
                "description": (
                    f"Claim {claim_id} currently has one independent "
                    "source stream."
                ),
                "derivation_source": "derive-gaps",
                "derivation_rule": "single_independent_source",
            }
        )

    support_groups = {
        row.get("independence_group")
        for row in evidences
        if row.get("polarity") == "supports"
        and isinstance(row.get("independence_group"), str)
    }
    contradict_groups = {
        row.get("independence_group")
        for row in evidences
        if row.get("polarity") == "contradicts"
        and isinstance(row.get("independence_group"), str)
    }
    if support_groups and contradict_groups:
        groups = sorted(_sort_items(support_groups | contradict_groups))
        payloads.append(
            {
                "gap_id": _make_gap_id("derived_open_conflict", claim_id),
                "gap_type": "explicit",
                "claim_id": claim_id,
                "impact": "high",
                "status": "open",
                "conflict_independence": "multi_stream"
                if len(groups) > 1
                else "single_stream",
                "group_count": len(groups),
                "severity": "high" if len(groups) > 1 else "medium",
                "independence_groups": groups,
                "description": f"Open conflict for claim {claim_id}.",
                "derivation_source": "derive-gaps",
                "derivation_rule": "open_conflict",
            }
        )

    return payloads


def command_init(args: argparse.Namespace) -> int:  # noqa: C901
    paths = _safe_paths(args.root, args.network_id)
    if paths.network_dir.exists():
        print(f"network already exists: {args.network_id}", file=sys.stderr)
        return 1

    snapshot_path = Path(args.snapshot_path).expanduser()
    if not snapshot_path.is_absolute():
        print("snapshot path must be absolute", file=sys.stderr)
        return 1
    snapshot_path = Path(os.path.abspath(snapshot_path))
    try:
        snapshot_file, file_digest = _read_stable_snapshot(snapshot_path)
    except ValueError as exc:
        print(f"snapshot path invalid: {exc}", file=sys.stderr)
        return 1
    if not SNAPSHOT_DIGEST_RE.fullmatch(args.snapshot_digest):
        print("snapshot_digest must be sha256:<64 hex>", file=sys.stderr)
        return 1

    snapshot_state_identity: str | None = None
    snapshot_state_sha: str | None = None
    contract_digest = file_digest
    if snapshot_file.get("schema") == ZOTERO_SNAPSHOT_SCHEMA:
        try:
            _validate_zotero_snapshot(snapshot_file)
        except ValueError as exc:
            print(f"Zotero snapshot invalid: {exc}", file=sys.stderr)
            return 1
        snapshot_state_identity = _zotero_snapshot_identity_digest(snapshot_file)
        snapshot_state_sha = _zotero_snapshot_state_digest(snapshot_file)
        if snapshot_state_sha is None:
            print("Zotero snapshot state digest unavailable", file=sys.stderr)
            return 1
        contract_digest = snapshot_state_sha

    if contract_digest != args.snapshot_digest:
        print(
            "snapshot digest mismatch",
            file=sys.stderr,
        )
        return 1

    paths.network_dir.mkdir(parents=True)
    for name in LEDGER_NAMES:
        with paths.ledger(name).open("w", encoding="utf-8"):
            pass

    state = {
        "schema_version": SCHEMA_VERSION,
        "network_id": paths.network_id,
        "created_at": _utcnow(),
        "question": _ensure_value(args.question, "question"),
        "scope": _ensure_value(args.scope, "scope"),
        "corpus_snapshot_path": str(snapshot_path),
        "corpus_snapshot_digest": contract_digest,
        "corpus_snapshot_file_sha256": file_digest,
        "required_dimensions": sorted(_sort_items(args.required_dimension)),
        "required_benchmark_profiles": sorted(
            _sort_items(args.required_benchmark_profile)
        ),
    }
    if snapshot_state_identity is not None:
        state["corpus_snapshot_identity_sha256"] = snapshot_state_identity
    if snapshot_state_sha is not None:
        state["corpus_snapshot_state_sha256"] = snapshot_state_sha
    _write_json_atomic(paths.state, state)
    records = {name: [] for name in LEDGER_NAMES}
    ok = _append_candidate(
        paths,
        records,
        "events",
        _record_id("event", "init"),
        {"event_type": "init", "status": "initialized"},
    )
    if not ok:
        return 1
    return 0


def command_add_source(args: argparse.Namespace) -> int:
    with _exclusive_lock(_safe_paths(args.root, args.network_id)):
        paths = _safe_paths(args.root, args.network_id)
        state, records = _load_state(paths)
        if _ensure_value(args.source_id, "source_id") is None:
            return 1
        if args.version_hash and not SNAPSHOT_DIGEST_RE.fullmatch(args.version_hash):
            print("version_hash must be sha256:<64 hex>", file=sys.stderr)
            return 1
        source_id = _validate_id(args.source_id, "source_id")
        if args.supersedes:
            if args.supersedes == source_id:
                print("supersedes cannot point to itself", file=sys.stderr)
                return 1
            if _validate_id(args.supersedes, "supersedes") not in {
                row.get("source_id") for row in records["sources"]
            }:
                print("supersedes target is unknown", file=sys.stderr)
                return 1
        payload = {
            "source_id": source_id,
            "canonical_identity": _ensure_value(
                args.canonical_identity, "canonical_identity"
            ),
            "canonical_version": _ensure_value(
                args.canonical_version, "canonical_version"
            ),
            "read_version": _ensure_value(args.read_version, "read_version"),
            "read_depth": _ensure_value(args.read_depth, "read_depth"),
            "version_hash": _ensure_value(args.version_hash, "version_hash"),
            "notes": (args.notes or "").strip(),
            "role": (args.role or "").strip(),
            "supersedes": args.supersedes,
            "source": args.source_id,
        }
        if payload["supersedes"] is not None:
            payload["supersedes"] = _validate_id(payload["supersedes"], "supersedes")
        if payload["read_depth"] not in READ_DEPTHS:
            print(f"invalid read_depth {payload['read_depth']}", file=sys.stderr)
            return 1
        if not SNAPSHOT_DIGEST_RE.fullmatch(payload["version_hash"]):
            print("version_hash must be sha256:<64 hex>", file=sys.stderr)
            return 1
        if payload["role"] not in {"", "source", "method", "dataset", "theory"}:
            print("invalid source role", file=sys.stderr)
            return 1
        return (
            0
            if _append_candidate(
                paths,
                records,
                "sources",
                _record_id("source", source_id),
                payload,
            )
            else 1
        )


def command_add_entity(args: argparse.Namespace) -> int:
    with _exclusive_lock(_safe_paths(args.root, args.network_id)):
        paths = _safe_paths(args.root, args.network_id)
        state, records = _load_state(paths)
        entity_id = _validate_id(args.entity_id, "entity_id")
        if args.supersedes:
            if _validate_id(args.supersedes, "supersedes") == entity_id:
                print("supersedes cannot point to itself", file=sys.stderr)
                return 1
            if _validate_id(args.supersedes, "supersedes") not in {
                row.get("entity_id") for row in records["entities"]
            }:
                print("supersedes target is unknown", file=sys.stderr)
                return 1
        payload = {
            "entity_id": entity_id,
            "entity_type": _ensure_value(args.entity_type, "entity_type"),
            "name": _ensure_value(args.name, "name"),
            "description": _ensure_value(args.description, "description"),
            "is_factual": False,
            "supersedes": args.supersedes,
        }
        return (
            0
            if _append_candidate(
                paths,
                records,
                "entities",
                _record_id("entity", entity_id),
                payload,
            )
            else 1
        )


def command_add_claim(args: argparse.Namespace) -> int:
    with _exclusive_lock(_safe_paths(args.root, args.network_id)):
        paths = _safe_paths(args.root, args.network_id)
        state, records = _load_state(paths)
        claim_id = _validate_id(args.claim_id, "claim_id")
        entity_ids = {
            row.get("entity_id")
            for row in records["entities"]
            if isinstance(row.get("entity_id"), str)
        }
        entity_id = args.entity_id
        if entity_id is not None:
            entity_id = _validate_id(entity_id, "entity_id")
            if entity_id not in entity_ids:
                print("entity_id not found", file=sys.stderr)
                return 1
        if args.supersedes:
            if _validate_id(args.supersedes, "supersedes") == claim_id:
                print("supersedes cannot point to itself", file=sys.stderr)
                return 1
            if _validate_id(args.supersedes, "supersedes") not in {
                row.get("claim_id") for row in records["claims"]
            }:
                print("supersedes target is unknown", file=sys.stderr)
                return 1
        typed_lists = {
            "assumptions": list(args.assumption),
            "conditions": list(args.condition),
            "units": list(args.unit),
            "exclusions": list(args.exclusion),
            "defeaters": list(args.defeater),
            "coverage_dimensions": list(args.coverage_dimension),
            "benchmark_profiles": list(args.benchmark_profile),
        }
        for field, values in typed_lists.items():
            if any(not isinstance(item, str) or not item for item in values):
                print(f"{field} contains an empty item", file=sys.stderr)
                return 1
            if len(values) != len(set(values)):
                print(f"{field} contains duplicates", file=sys.stderr)
                return 1
        payload = {
            "claim_id": claim_id,
            "claim_text": _ensure_value(args.claim_text, "claim_text"),
            "entity_id": entity_id,
            "impact": _ensure_value(args.impact, "impact"),
            "is_factual": False,
            "scope_statement": args.scope_statement,
            **typed_lists,
            "supersedes": args.supersedes,
        }
        if payload["impact"] not in IMPACTS:
            print("invalid impact", file=sys.stderr)
            return 1
        return (
            0
            if _append_candidate(
                paths,
                records,
                "claims",
                _record_id("claim", claim_id),
                payload,
            )
            else 1
        )


def command_add_evidence(args: argparse.Namespace) -> int:
    with _exclusive_lock(_safe_paths(args.root, args.network_id)):
        paths = _safe_paths(args.root, args.network_id)
        state, records = _load_state(paths)
        claim_id = _validate_id(args.claim_id, "claim_id")
        source_id = _validate_id(args.source_id, "source_id")
        if claim_id not in {row.get("claim_id") for row in records["claims"]}:
            print("claim_id unknown", file=sys.stderr)
            return 1
        if source_id not in {row.get("source_id") for row in records["sources"]}:
            print("source_id unknown", file=sys.stderr)
            return 1
        if args.supersedes:
            if _validate_id(args.supersedes, "supersedes") not in {
                row.get("evidence_id") for row in records["evidence"]
            }:
                print("supersedes target is unknown", file=sys.stderr)
                return 1
        if args.supersedes and args.evidence_id == args.supersedes:
            print("supersedes cannot point to itself", file=sys.stderr)
            return 1
        evidence_id = _validate_id(args.evidence_id, "evidence_id")
        payload = {
            "evidence_id": evidence_id,
            "claim_id": claim_id,
            "source_id": source_id,
            "polarity": args.polarity,
            "exact_locator": args.exact_locator,
            "independence_group": _ensure_value(
                args.independence_group, "independence_group"
            ),
            "summary": _ensure_value(args.summary, "summary"),
            "notes": (args.notes or "").strip(),
            "supersedes": args.supersedes,
        }
        if payload["polarity"] not in EVIDENCE_POLARITY:
            print("invalid polarity", file=sys.stderr)
            return 1
        if args.exact_locator is None or not args.exact_locator.strip():
            print("exact_locator missing", file=sys.stderr)
            return 1
        if payload["exact_locator"] == "N/A":
            print("exact_locator must be exact", file=sys.stderr)
            return 1
        return (
            0
            if _append_candidate(
                paths,
                records,
                "evidence",
                _record_id("evidence", evidence_id),
                payload,
            )
            else 1
        )


def command_add_relation(args: argparse.Namespace) -> int:
    with _exclusive_lock(_safe_paths(args.root, args.network_id)):
        paths = _safe_paths(args.root, args.network_id)
        state, records = _load_state(paths)
        relation_id = _validate_id(args.relation_id, "relation_id")
        if args.supersedes:
            if _validate_id(args.supersedes, "supersedes") not in {
                row.get("relation_id") for row in records["relations"]
            }:
                print("supersedes target is unknown", file=sys.stderr)
                return 1
        claims = {
            row.get("claim_id")
            for row in records["claims"]
            if isinstance(row.get("claim_id"), str)
        }
        evidence = {
            row.get("evidence_id")
            for row in records["evidence"]
            if isinstance(row.get("evidence_id"), str)
        }
        if not _valid_ref(args.from_ref) or not _valid_ref(args.to_ref):
            print("relation refs must be claim:ID or evidence:ID", file=sys.stderr)
            return 1
        if not _is_claim_or_evidence_ref(
            args.from_ref
        ) or not _is_claim_or_evidence_ref(args.to_ref):
            print("relation must reference claim or evidence", file=sys.stderr)
            return 1
        if not _ref_exists(args.from_ref, claims, evidence) or not _ref_exists(
            args.to_ref, claims, evidence
        ):
            print("relation references unknown node", file=sys.stderr)
            return 1
        payload = {
            "relation_id": relation_id,
            "relation_type": _ensure_value(args.relation_type, "relation_type"),
            "from": args.from_ref,
            "to": args.to_ref,
            "notes": (args.notes or "").strip(),
            "supersedes": args.supersedes,
        }
        if payload["relation_type"] not in RELATION_TYPES:
            print("invalid relation_type", file=sys.stderr)
            return 1
        return (
            0
            if _append_candidate(
                paths,
                records,
                "relations",
                _record_id("relation", relation_id),
                payload,
            )
            else 1
        )


def command_record_gap(args: argparse.Namespace) -> int:
    with _exclusive_lock(_safe_paths(args.root, args.network_id)):
        paths = _safe_paths(args.root, args.network_id)
        state, records = _load_state(paths)
        gap_id = _validate_gap_id(args.gap_id, "gap_id")
        if args.gap_type == "implicit_candidate" and args.novelty_claimed:
            print("implicit_candidate cannot claim novelty", file=sys.stderr)
            return 1
        claim_id = args.claim_id
        if claim_id is not None:
            claim_id = _validate_id(claim_id, "claim_id")
            if claim_id not in {row.get("claim_id") for row in records["claims"]}:
                print("claim_id unknown", file=sys.stderr)
                return 1
        payload = {
            "gap_id": gap_id,
            "gap_type": _ensure_value(args.gap_type, "gap_type"),
            "claim_id": claim_id,
            "impact": _ensure_value(args.impact, "impact"),
            "status": _ensure_value(args.status, "status"),
            "description": _ensure_value(args.description, "description"),
            "grounds": (args.grounds or "").strip(),
            "warrant": (args.warrant or "").strip(),
            "backing": (args.backing or "").strip(),
            "qualifier": (args.qualifier or "").strip(),
            "defeaters": (args.defeaters or "").strip(),
            "search_test": (args.search_test or "").strip(),
            "novelty_claimed": bool(args.novelty_claimed),
            "resolution_evidence_refs": sorted(
                set(args.resolution_evidence_ref or [])
            ),
            "resolution_source": (args.resolution_source or "").strip(),
        }
        if args.priority is not None:
            payload["priority"] = args.priority
        if args.decision_impact is not None:
            payload["decision_impact"] = args.decision_impact
        source = (args.source or "").strip()
        if payload["gap_type"] == "implicit_candidate":
            required_implicit = (
                "grounds",
                "warrant",
                "backing",
                "qualifier",
                "defeaters",
                "search_test",
            )
            for key in required_implicit:
                if not payload[key]:
                    print(f"{key} required for implicit_candidate", file=sys.stderr)
                    return 1
            payload["source"] = "derive-gap"
        else:
            payload["source"] = _ensure_value(source, "source")
        if payload["impact"] not in IMPACTS:
            print("invalid impact", file=sys.stderr)
            return 1
        if payload["status"] not in GAP_STATUSES:
            print("invalid status", file=sys.stderr)
            return 1
        resolution_error = _record_gap_resolution_error(
            payload, claim_id, records["evidence"]
        )
        if resolution_error:
            print(resolution_error, file=sys.stderr)
            return 1
        return (
            0
            if _append_candidate(
                paths,
                records,
                "gaps",
                _gap_initial_record_id(gap_id),
                payload,
            )
            else 1
        )


def command_transition_gap(args: argparse.Namespace) -> int:
    with _exclusive_lock(_safe_paths(args.root, args.network_id)):
        paths = _safe_paths(args.root, args.network_id)
        _, records = _load_state(paths)
        gap_id = _validate_gap_id(args.gap_id, "gap_id")
        from_record_id = _ensure_value(args.from_record_id, "from_record_id")
        reason = _ensure_value(args.reason, "reason")
        next_status = _ensure_value(args.status, "status")
        gap_rows = sorted(
            [row for row in records["gaps"] if row.get("gap_id") == gap_id],
            key=lambda row: int(row.get("sequence") or 0),
        )
        if not gap_rows:
            print(f"gap not found: {gap_id}", file=sys.stderr)
            return 1
        latest = gap_rows[-1]
        if latest.get("record_id") != from_record_id:
            print("from_record_id is not the latest gap record", file=sys.stderr)
            return 1
        prior_status = str(latest.get("status") or "")
        if next_status not in GAP_STATUS_TRANSITIONS.get(prior_status, set()):
            print(
                f"invalid gap transition: {prior_status}->{next_status}",
                file=sys.stderr,
            )
            return 1

        evidence_refs = sorted(set(args.evidence_ref or []))
        evidence_by_id = {
            str(row["evidence_id"]): row
            for row in records["evidence"]
            if isinstance(row.get("evidence_id"), str)
        }
        for evidence_ref in evidence_refs:
            _validate_id(evidence_ref, "evidence_ref")
            if evidence_ref not in evidence_by_id:
                print(f"unknown evidence_ref: {evidence_ref}", file=sys.stderr)
                return 1
        resolution_source = (args.resolution_source or "").strip()
        if next_status == "resolved":
            resolution_error = _resolution_evidence_error(
                latest.get("claim_id"),
                evidence_refs,
                resolution_source,
                evidence_by_id,
            )
            if resolution_error:
                print(resolution_error, file=sys.stderr)
                return 1

        semantic_fields = (
            "gap_id",
            "gap_type",
            "claim_id",
            "impact",
            "description",
            "grounds",
            "warrant",
            "backing",
            "qualifier",
            "defeaters",
            "search_test",
            "novelty_claimed",
            "source",
            "derivation_source",
            "derivation_rule",
            "missing_dimension",
            "missing_profile",
            "conflict_independence",
            "group_count",
            "severity",
            "independence_groups",
            "priority",
            "decision_impact",
        )
        payload = {key: latest.get(key) for key in semantic_fields if key in latest}
        payload.update(
            {
                "status": next_status,
                "transition_from_record_id": from_record_id,
                "transition_reason": reason,
                "transition_evidence_refs": evidence_refs,
                "resolution_source": resolution_source,
                "supersedes": from_record_id,
            }
        )
        sequence = _next_sequence(records)
        record_id = _gap_transition_record_id(gap_id, sequence)
        if not _append_candidate(paths, records, "gaps", record_id, payload):
            return 1
        print(
            json.dumps(
                {
                    "from_record_id": from_record_id,
                    "gap_id": gap_id,
                    "record_id": record_id,
                    "status": next_status,
                },
                ensure_ascii=False,
                sort_keys=True,
            )
        )
        return 0


def _source_payload_from_parent(
    parent: dict[str, Any],
    snapshot: dict[str, Any],
    snapshot_state: str,
) -> tuple[str, dict[str, Any]]:
    source_identity = _snapshot_parent_identity(parent)
    parent_hash = _snapshot_parent_identity_hash(parent)
    source_id = _parent_source_id(parent, parent_hash)
    parent_version = str(parent["version"])
    payload = {
        "source_id": source_id,
        "canonical_identity": source_identity,
        "canonical_version": parent_version,
        "read_version": parent_version,
        "read_depth": "metadata",
        "version_hash": parent_hash,
        "notes": "ingested from ZoteroCorpusSnapshot/v1",
        "role": "zotero_corpus",
        "supersedes": None,
        "source": source_id,
        "zotero_parent_key": str(parent["key"]),
        "zotero_item_type": str(parent["item_type"]),
        "snapshot_state": {
            "identity_sha256": _zotero_snapshot_identity_digest(snapshot),
            "state_sha256": snapshot_state,
        },
    }
    return source_id, payload


def _latest_sources_by_identity_and_key(
    source_rows: list[dict[str, Any]],
) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    by_identity: dict[str, dict[str, Any]] = {}
    by_key: dict[str, dict[str, Any]] = {}
    ordered = sorted(source_rows, key=lambda row: int(row.get("sequence") or 0))
    for row in ordered:
        identity = row.get("canonical_identity")
        parent_key = row.get("zotero_parent_key")
        if isinstance(identity, str):
            by_identity[identity] = row
        if isinstance(parent_key, str):
            by_key[parent_key] = row
    return by_identity, by_key


def _stage_source_rows(
    paths: Paths,
    records: dict[str, list[dict[str, Any]]],
    pending_payloads: list[dict[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    staged = {name: list(rows) for name, rows in records.items()}
    next_sequence = _next_sequence(staged)
    recorded_at = _utcnow()
    for payload in pending_payloads:
        source_id = str(payload["source_id"])
        staged["sources"].append(
            {
                "schema_version": SCHEMA_VERSION,
                "network_id": paths.network_id,
                "record_id": _record_id("source", source_id),
                "sequence": next_sequence,
                "recorded_at": recorded_at,
                **payload,
            }
        )
        next_sequence += 1
    return staged


def _stage_refresh_event(
    paths: Paths,
    records: dict[str, list[dict[str, Any]]],
    payload: dict[str, Any],
) -> None:
    sequence = _next_sequence(records)
    records["events"].append(
        {
            "schema_version": SCHEMA_VERSION,
            "network_id": paths.network_id,
            "record_id": _record_id("event", "snapshot_refreshed", str(sequence)),
            "sequence": sequence,
            "recorded_at": _utcnow(),
            "event_type": "snapshot_refreshed",
            **payload,
        }
    )


def command_ingest_zotero_snapshot(args: argparse.Namespace) -> int:  # noqa: C901
    with _exclusive_lock(_safe_paths(args.root, args.network_id)):
        paths = _safe_paths(args.root, args.network_id)
        state, records = _load_state(paths)
        snapshot_path = Path(args.snapshot)
        allow_refresh = bool(args.allow_refresh)
        if not snapshot_path.is_absolute():
            print("snapshot must be an absolute path", file=sys.stderr)
            return 1
        snapshot_path = Path(os.path.abspath(snapshot_path))

        bound_value = state.get("corpus_snapshot_path")
        if not isinstance(bound_value, str) or not Path(bound_value).is_absolute():
            print("invalid bound snapshot path", file=sys.stderr)
            return 1
        bound_snapshot_path = Path(bound_value)
        try:
            bound_snapshot_path = bound_snapshot_path.resolve()
        except OSError:
            print("invalid bound snapshot path", file=sys.stderr)
            return 1
        try:
            candidate_snapshot_path = snapshot_path.resolve()
        except OSError:
            print("snapshot path cannot be resolved", file=sys.stderr)
            return 1
        if candidate_snapshot_path != bound_snapshot_path and not allow_refresh:
            print("snapshot path does not match network binding", file=sys.stderr)
            return 1

        try:
            snapshot, file_digest = _read_zotero_snapshot_with_digest(snapshot_path)
        except (ValueError, OSError, json.JSONDecodeError) as exc:
            print(f"snapshot invalid: {exc}", file=sys.stderr)
            return 1
        bound_identity = state.get("corpus_snapshot_identity_sha256")
        snapshot_identity = _zotero_snapshot_identity_digest(snapshot)
        if not SNAPSHOT_DIGEST_RE.fullmatch(str(bound_identity or "")):
            print("bound snapshot identity missing", file=sys.stderr)
            return 1
        if snapshot_identity != bound_identity:
            print("snapshot identity mismatch", file=sys.stderr)
            return 1

        bound_state_sha = state.get("corpus_snapshot_state_sha256")
        snapshot_state_sha = _zotero_snapshot_state_digest(snapshot) or ""
        if not SNAPSHOT_DIGEST_RE.fullmatch(snapshot_state_sha):
            print("snapshot state digest invalid", file=sys.stderr)
            return 1

        if not allow_refresh:
            if file_digest != state.get("corpus_snapshot_file_sha256"):
                print("snapshot file digest mismatch", file=sys.stderr)
                return 1
            if bound_state_sha is not None:
                if not SNAPSHOT_DIGEST_RE.fullmatch(bound_state_sha):
                    print("bound snapshot state digest invalid", file=sys.stderr)
                    return 1
                if snapshot_state_sha != bound_state_sha:
                    print("snapshot state mismatch", file=sys.stderr)
                    return 1
        else:
            if "corpus_snapshot_current_source_ids" not in state:
                print(
                    "initial snapshot must be ingested before refresh",
                    file=sys.stderr,
                )
                return 1
            if bound_state_sha is None:
                print("bound snapshot state digest missing", file=sys.stderr)
                return 1
            if not SNAPSHOT_DIGEST_RE.fullmatch(bound_state_sha):
                print("bound snapshot state digest invalid", file=sys.stderr)
                return 1
            if snapshot_state_sha == bound_state_sha:
                print("snapshot state unchanged", file=sys.stderr)
                return 1

        parents = snapshot.get("parents", [])
        sorted_parents = _snapshot_parents_sorted(parents)
        latest_by_identity, latest_by_key = _latest_sources_by_identity_and_key(
            records["sources"]
        )
        existing_by_id = {
            str(row.get("source_id")): row
            for row in records["sources"]
            if isinstance(row.get("source_id"), str)
        }
        pending_rows: list[dict[str, Any]] = []
        added_count = 0
        changed_count = 0
        existing_count = 0
        current_source_ids: list[str] = []
        seen_source_ids: set[str] = set()
        matched_prior_source_ids: set[str] = set()
        for parent in sorted_parents:
            source_id, payload = _source_payload_from_parent(
                parent,
                snapshot,
                snapshot_state_sha,
            )
            source_id = _validate_id(source_id, "source_id")
            if source_id in seen_source_ids:
                print(f"duplicate derived source ID: {source_id}", file=sys.stderr)
                return 1
            seen_source_ids.add(source_id)
            current_source_ids.append(source_id)

            canonical_identity = str(payload["canonical_identity"])
            parent_key = str(payload["zotero_parent_key"])
            prior = latest_by_key.get(parent_key) or latest_by_identity.get(
                canonical_identity
            )
            if prior is not None and isinstance(prior.get("source_id"), str):
                matched_prior_source_ids.add(str(prior["source_id"]))
            prior_same = (
                prior is not None
                and _source_row_signature(prior) == _source_row_signature(payload)
            )
            if prior_same:
                if prior.get("source_id") != source_id:
                    print(
                        f"source identity/version conflict for {canonical_identity!r}",
                        file=sys.stderr,
                    )
                    return 1
                existing_count += 1
                continue
            if prior is not None and not allow_refresh:
                print(
                    f"source identity/version drift for {canonical_identity!r}; "
                    "use --allow-refresh",
                    file=sys.stderr,
                )
                return 1
            if prior is not None:
                payload["supersedes"] = prior.get("source_id")

            existing = existing_by_id.get(source_id)
            if existing is not None:
                if _source_row_signature(existing) == _source_row_signature(payload):
                    existing_count += 1
                    continue
                print(
                    f"source {source_id!r} already exists with different payload",
                    file=sys.stderr,
                )
                return 1
            pending_rows.append(payload)
            if prior is None:
                added_count += 1
            else:
                changed_count += 1
            existing_by_id[source_id] = payload
            latest_by_identity[canonical_identity] = payload
            latest_by_key[parent_key] = payload

        prior_current = set(_corpus_snapshot_current_source_ids(state))
        removed_count = len(prior_current - matched_prior_source_ids)
        staged_records = _stage_source_rows(paths, records, pending_rows)
        staged_state = dict(state)
        staged_state["corpus_snapshot_path"] = str(candidate_snapshot_path)
        staged_state["corpus_snapshot_digest"] = snapshot_state_sha
        staged_state["corpus_snapshot_file_sha256"] = file_digest
        staged_state["corpus_snapshot_identity_sha256"] = snapshot_identity
        staged_state["corpus_snapshot_state_sha256"] = snapshot_state_sha
        staged_state["corpus_snapshot_current_source_ids"] = current_source_ids

        if allow_refresh:
            _stage_refresh_event(
                paths,
                staged_records,
                {
                    "status": "ok",
                    "previous_snapshot_path": str(bound_snapshot_path),
                    "previous_snapshot_state_sha256": bound_state_sha,
                    "previous_snapshot_file_sha256": state.get(
                        "corpus_snapshot_file_sha256"
                    ),
                    "snapshot_path": str(candidate_snapshot_path),
                    "snapshot_digest": snapshot_state_sha,
                    "snapshot_file_sha256": file_digest,
                    "snapshot_state_sha256": snapshot_state_sha,
                    "snapshot_identity_sha256": snapshot_identity,
                    "added": added_count,
                    "changed": changed_count,
                    "existing": existing_count,
                    "removed": removed_count,
                    "current": len(current_source_ids),
                },
            )

        transaction_files = {
            paths.ledger("sources"): _jsonl_text(staged_records["sources"]),
            paths.state: _json_text(staged_state),
        }
        if allow_refresh:
            transaction_files[paths.ledger("events")] = _jsonl_text(
                staged_records["events"]
            )
        try:
            _replace_files_transactionally(transaction_files)
        except (OSError, ValueError) as exc:
            print(f"snapshot ingest transaction failed: {exc}", file=sys.stderr)
            return 1

        output = {
            "added": added_count,
            "changed": changed_count,
            "existing": existing_count,
            "removed": removed_count,
            "total": len(current_source_ids),
            "ledger_total": len(staged_records["sources"]),
            "snapshot_state": {
                "path": str(candidate_snapshot_path),
                "digest": snapshot_state_sha,
                "file_sha256": file_digest,
                "state_sha256": snapshot_state_sha,
                "identity_sha256": snapshot_identity,
            },
            "status": _derive_status_summary(paths, staged_state, staged_records),
        }
        print(json.dumps(output, ensure_ascii=False, sort_keys=True, indent=2))
        return 0


def _required_list(state: dict[str, Any], key: str) -> list[str]:
    value = state.get(key)
    return value if isinstance(value, list) else []


def _build_implicit_isolated_gap_payload(claim_id: str) -> dict[str, Any]:
    return {
        "gap_id": _make_gap_id("derived_isolated", claim_id),
        "gap_type": "implicit_candidate",
        "claim_id": claim_id,
        "impact": "medium",
        "status": "open",
        "description": f"Claim {claim_id} is topologically isolated.",
        "source": "derive-gaps",
        "grounds": f"No inbound/outbound claim/evidence relation for {claim_id}.",
        "warrant": "Insufficient chain of support for graph integration.",
        "backing": "Topological isolation in current relation/evidence network.",
        "qualifier": "Candidate only; does not imply novelty.",
        "defeaters": "Future evidence chain connections or explicit relation rows.",
        "search_test": "Search for explicit relation edges under independent sources.",
        "novelty_claimed": False,
    }


def _build_aggregate_coverage_gap_payloads(
    coverage: dict[str, list[str]],
) -> list[dict[str, Any]]:
    payloads: list[dict[str, Any]] = []
    for dimension in coverage["missing_dimensions"]:
        payloads.append(
            {
                "gap_id": _aggregate_gap_id("missing-dimension", dimension),
                "gap_type": "deterministic_structural",
                "claim_id": None,
                "impact": "medium",
                "status": "open",
                "description": f"Network coverage is missing dimension {dimension}.",
                "derivation_source": "derive-gaps",
                "derivation_rule": "missing_dimension",
                "missing_dimension": dimension,
            }
        )
    for profile in coverage["missing_benchmark_profiles"]:
        payloads.append(
            {
                "gap_id": _aggregate_gap_id("missing-profile", profile),
                "gap_type": "deterministic_structural",
                "claim_id": None,
                "impact": "medium",
                "status": "open",
                "description": f"Network coverage is missing profile {profile}.",
                "derivation_source": "derive-gaps",
                "derivation_rule": "missing_benchmark_profile",
                "missing_profile": profile,
            }
        )
    return payloads


def _build_derived_gap_payloads(
    state: dict[str, Any], records: dict[str, list[dict[str, Any]]]
) -> list[dict[str, Any]]:
    active_claims = _active_records(records["claims"], "claim_id")
    active_evidence = _active_records(records["evidence"], "evidence_id")
    claim_evidence = _group_evidence_by_claim(active_evidence)
    payloads: list[dict[str, Any]] = []
    for claim in sorted(active_claims, key=lambda row: str(row.get("claim_id"))):
        claim_id = claim.get("claim_id")
        if not isinstance(claim_id, str):
            continue
        payloads.extend(
            _derive_gaps_payload_for_claim(
                claim_id,
                claim,
                claim_evidence.get(claim_id, []),
            )
        )
    topology_records = dict(records)
    topology_records["claims"] = active_claims
    topology_records["evidence"] = active_evidence
    topology = _derive_topology(topology_records)
    payloads.extend(
        _build_implicit_isolated_gap_payload(claim_id)
        for claim_id in topology["isolated_claims"]
    )
    coverage = _collect_aggregate_coverage(
        records["claims"],
        records["evidence"],
        _required_list(state, "required_dimensions"),
        _required_list(state, "required_benchmark_profiles"),
    )
    payloads.extend(_build_aggregate_coverage_gap_payloads(coverage))
    return sorted(payloads, key=lambda payload: str(payload.get("gap_id")))


def _validate_derive_gap_candidates(
    paths: Paths,
    records: dict[str, list[dict[str, Any]]],
    payloads: list[dict[str, Any]],
) -> list[str]:
    rows = [
        {
            "schema_version": SCHEMA_VERSION,
            "network_id": paths.network_id,
            "record_id": _gap_initial_record_id(str(payload.get("gap_id") or "")),
            "sequence": index,
            "recorded_at": "derive-validation",
            **payload,
        }
        for index, payload in enumerate(payloads, start=1)
    ]
    errors: list[str] = []
    known_claims = {
        str(row["claim_id"])
        for row in records["claims"]
        if isinstance(row.get("claim_id"), str)
    }
    _validate_gap_records(rows, known_claims, records["evidence"], errors)
    return errors


def _latest_gaps_by_id(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    latest: dict[str, dict[str, Any]] = {}
    for row in sorted(rows, key=lambda item: int(item.get("sequence") or 0)):
        if isinstance(row.get("gap_id"), str):
            latest[row["gap_id"]] = row
    return latest


def command_derive_gaps(args: argparse.Namespace) -> int:
    with _exclusive_lock(_safe_paths(args.root, args.network_id)):
        paths = _safe_paths(args.root, args.network_id)
        state, records = _load_state(paths)
        payloads = _build_derived_gap_payloads(state, records)
        candidate_errors = _validate_derive_gap_candidates(paths, records, payloads)
        if candidate_errors:
            for error in candidate_errors:
                print(f"derive candidate invalid: {error}", file=sys.stderr)
            return 1

        latest = _latest_gaps_by_id(records["gaps"])
        new_payloads = [
            payload for payload in payloads if payload.get("gap_id") not in latest
        ]
        reopen_required = sorted(
            str(payload["gap_id"])
            for payload in payloads
            if payload.get("gap_id") in latest
            and latest[str(payload["gap_id"])].get("status") != "open"
        )
        desired_status = {
            str(payload["gap_id"]): (
                latest[str(payload["gap_id"])].get("status")
                if str(payload["gap_id"]) in latest
                else "open"
            )
            for payload in payloads
        }
        event_payload = {
            "event_type": "derive_gaps",
            "source": "derive-gaps",
            "status": "ok",
            "derived_count": len(payloads),
            "derived_gap_ids": [str(payload["gap_id"]) for payload in payloads],
            "reopen_required_gap_ids": reopen_required,
        }
        event_digest = hashlib.sha256(
            json.dumps(
                {"payloads": payloads, "desired_status": desired_status},
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()[:32]
        event_record_id = f"event-derive-gaps-{event_digest}"
        event_state = _check_idempotent_or_fail(
            records["events"],
            {"record_id": event_record_id, **event_payload},
            event_record_id,
        )
        if event_state == "conflict":
            print("derive event id collision", file=sys.stderr)
            return 1

        staged_records = {name: list(rows) for name, rows in records.items()}
        sequence = _next_sequence(staged_records)
        recorded_at = _utcnow()
        for payload in new_payloads:
            gap_id = str(payload["gap_id"])
            staged_records["gaps"].append(
                {
                    "schema_version": SCHEMA_VERSION,
                    "network_id": paths.network_id,
                    "record_id": _gap_initial_record_id(gap_id),
                    "sequence": sequence,
                    "recorded_at": recorded_at,
                    **payload,
                }
            )
            sequence += 1
        if event_state == "append":
            staged_records["events"].append(
                {
                    "schema_version": SCHEMA_VERSION,
                    "network_id": paths.network_id,
                    "record_id": event_record_id,
                    "sequence": sequence,
                    "recorded_at": recorded_at,
                    **event_payload,
                }
            )

        staged_errors = _validate_record_shapes(paths, state, staged_records)
        if staged_errors:
            for error in staged_errors:
                print(f"derive staged state invalid: {error}", file=sys.stderr)
            return 1
        contents: dict[Path, str] = {}
        if new_payloads:
            contents[paths.ledger("gaps")] = _jsonl_text(staged_records["gaps"])
        if event_state == "append":
            contents[paths.ledger("events")] = _jsonl_text(staged_records["events"])
        if contents:
            _replace_files_transactionally(contents)
        print(
            json.dumps(
                {
                    "appended_gap_ids": [
                        str(payload["gap_id"]) for payload in new_payloads
                    ],
                    "derived_gap_ids": [
                        str(payload["gap_id"]) for payload in payloads
                    ],
                    "reopen_required_gap_ids": reopen_required,
                },
                ensure_ascii=False,
                sort_keys=True,
            )
        )
        return 0


def command_status(args: argparse.Namespace) -> int:
    paths = _safe_paths(args.root, args.network_id)
    state, records = _load_state(paths)
    payload = _derive_status_summary(paths, state, records)
    payload["validation_errors"] = _validate_record_shapes(paths, state, records)
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    return 1 if payload["validation_errors"] else 0


def command_validate(args: argparse.Namespace) -> int:
    return command_status(args)


def _snapshot_payload(
    paths: Paths, state: dict[str, Any], records: dict[str, list[dict[str, Any]]]
) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "network": paths.network_id,
        "state": state,
        "records": {
            name: sorted(records[name], key=lambda row: row.get("sequence", 0))
            for name in LEDGER_NAMES
        },
        "derived": _derive_status_summary(paths, state, records),
    }


def command_snapshot(args: argparse.Namespace) -> int:
    paths = _safe_paths(args.root, args.network_id)
    state, records = _load_state(paths)
    errors = _validate_record_shapes(paths, state, records)
    if errors:
        print("validation errors:\n" + "\n".join(errors), file=sys.stderr)
        return 1
    payload = _snapshot_payload(paths, state, records)
    output = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
    if args.output is not None:
        output_path = _safe_relative_path(paths.root, args.output, "output")
        if output_path.is_symlink():
            print("output is symlink", file=sys.stderr)
            return 1
        _write_json_atomic(output_path, json.loads(output))
        return 0
    print(output)
    return 0


def _latest_gap_records(gaps: list[dict[str, Any]]) -> list[dict[str, Any]]:
    latest: dict[str, dict[str, Any]] = {}
    for row in sorted(gaps, key=lambda item: int(item.get("sequence") or 0)):
        gap_id = row.get("gap_id")
        if isinstance(gap_id, str):
            latest[gap_id] = row
    return [latest[gap_id] for gap_id in sorted(latest)]


def _export_creator_metadata(creator: dict[str, Any]) -> dict[str, str] | None:
    role = _normalized_text(str(creator.get("creatorType") or ""))
    given = _normalized_text(str(creator.get("firstName") or ""))
    family = _normalized_text(str(creator.get("lastName") or ""))
    literal = _normalized_text(str(creator.get("name") or ""))
    name = literal or " ".join(part for part in (given, family) if part)
    if not any((role, given, family, name)):
        return None
    output: dict[str, str] = {}
    if role:
        output["role"] = role
    if given:
        output["given"] = given
    if family:
        output["family"] = family
    if name:
        output["name"] = name
    return output


def _export_parent_bibliography(parent: dict[str, Any]) -> dict[str, Any]:
    date = _normalized_text(str(parent.get("date") or ""))
    year_match = re.search(r"(?<!\d)([12]\d{3})(?!\d)", date)
    creators: list[dict[str, str]] = []
    authors: list[str] = []
    for raw_creator in parent.get("creators", []):
        if not isinstance(raw_creator, dict):
            continue
        creator = _export_creator_metadata(raw_creator)
        if creator is None:
            continue
        creators.append(creator)
        if creator.get("role", "").casefold() == "author" and creator.get("name"):
            authors.append(str(creator["name"]))
    return {
        "title": _normalized_text(str(parent.get("title") or "")),
        "doi": _normalized_doi(str(parent.get("DOI") or "")),
        "date": date,
        "year": year_match.group(1) if year_match else "",
        "creators": creators,
        "authors": authors,
    }


def _verified_export_zotero_metadata(
    state: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    snapshot_path = state.get("corpus_snapshot_path")
    if not isinstance(snapshot_path, str) or not snapshot_path.strip():
        raise ValueError("bound Zotero snapshot path missing")
    snapshot, file_digest = _read_zotero_snapshot_with_digest(Path(snapshot_path))

    identity_digest = _zotero_snapshot_identity_digest(snapshot)
    state_digest = _zotero_snapshot_state_digest(snapshot)
    bindings = (
        (
            "file digest",
            state.get("corpus_snapshot_file_sha256"),
            file_digest,
        ),
        (
            "identity digest",
            state.get("corpus_snapshot_identity_sha256"),
            identity_digest,
        ),
        (
            "state digest",
            state.get("corpus_snapshot_state_sha256"),
            state_digest,
        ),
        (
            "contract digest",
            state.get("corpus_snapshot_digest"),
            state_digest,
        ),
    )
    for label, bound, observed in bindings:
        if bound != observed:
            raise ValueError(f"bound Zotero snapshot {label} mismatch during export")

    metadata: dict[str, dict[str, Any]] = {}
    expected_current_ids: list[str] = []
    for parent in _snapshot_parents_sorted(snapshot["parents"]):
        parent_hash = _snapshot_parent_identity_hash(parent)
        source_id = _parent_source_id(parent, parent_hash)
        expected_current_ids.append(source_id)
        metadata[source_id] = _export_parent_bibliography(parent)
    if expected_current_ids != _corpus_snapshot_current_source_ids(state):
        raise ValueError("bound Zotero snapshot membership mismatch during export")
    return metadata


def _export_sources(
    state: dict[str, Any], sources: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    has_current_membership = "corpus_snapshot_current_source_ids" in state
    current_ids = set(_corpus_snapshot_current_source_ids(state))
    zotero_bound = any(row.get("role") == "zotero_corpus" for row in sources)
    zotero_metadata = _verified_export_zotero_metadata(state) if zotero_bound else {}

    exported: list[dict[str, Any]] = []
    for source in sorted(sources, key=lambda row: str(row.get("record_id") or "")):
        source_id = str(source.get("source_id") or "")
        is_current = source_id in current_ids if has_current_membership else True
        output = dict(source)
        output["corpus_membership"] = "current" if is_current else "historical"
        if is_current and source.get("role") == "zotero_corpus":
            bibliography = zotero_metadata.get(source_id)
            if bibliography is None:
                raise ValueError(
                    f"current Zotero source missing verified bibliography: {source_id}"
                )
            output.update(bibliography)
        exported.append(output)
    return exported


def _export_current_sources(
    state: dict[str, Any], sources: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    if "corpus_snapshot_current_source_ids" not in state:
        return sorted(sources, key=lambda row: str(row.get("source_id") or ""))
    current_ids = set(_corpus_snapshot_current_source_ids(state))
    return sorted(
        [row for row in sources if row.get("source_id") in current_ids],
        key=lambda row: str(row.get("source_id") or ""),
    )


def _export_source_provenance(source: dict[str, Any]) -> list[dict[str, str]]:
    source_id = str(source.get("source_id") or "")
    locator = (
        f"read_version={source.get('read_version')}; "
        f"version_hash={source.get('version_hash')}"
    )
    return [{"source_id": f"source:{source_id}", "locator": locator}]


def _partition_evidence_backed_records(
    records: dict[str, list[dict[str, Any]]],
) -> tuple[
    list[tuple[dict[str, Any], dict[str, Any]]],
    dict[str, dict[str, Any]],
    list[str],
]:
    evidence_by_claim: dict[str, list[dict[str, Any]]] = {}
    for evidence in records["evidence"]:
        claim_id = evidence.get("claim_id")
        if isinstance(claim_id, str):
            evidence_by_claim.setdefault(claim_id, []).append(evidence)
    evidence_by_entity: dict[str, dict[str, Any]] = {}
    omissions: list[str] = []
    backed_claims: list[tuple[dict[str, Any], dict[str, Any]]] = []
    ordered_claims = sorted(
        records["claims"], key=lambda row: str(row.get("claim_id") or "")
    )
    for claim in ordered_claims:
        claim_id = str(claim["claim_id"])
        claim_evidence = evidence_by_claim.get(claim_id, [])
        if not claim_evidence:
            omissions.append(f"claim:{claim_id}:missing-evidence")
            continue
        evidence = sorted(
            claim_evidence, key=lambda row: str(row.get("evidence_id") or "")
        )[0]
        backed_claims.append((claim, evidence))
        entity_id = claim.get("entity_id")
        if isinstance(entity_id, str):
            evidence_by_entity.setdefault(entity_id, evidence)
    return backed_claims, evidence_by_entity, omissions


def _export_nodes(
    paths: Paths,
    sources: list[dict[str, Any]],
    current_sources: list[dict[str, Any]],
    records: dict[str, list[dict[str, Any]]],
) -> tuple[list[dict[str, Any]], str, list[str]]:
    if not current_sources:
        raise ValueError("KnowledgeNetwork/v1 export requires a current source")
    current_ids = {str(row.get("source_id")) for row in current_sources}
    first_source_id = str(current_sources[0]["source_id"])
    corpus_node_id = f"entity:corpus-{paths.network_id}"
    nodes: list[dict[str, Any]] = [
        {
            "node_id": corpus_node_id,
            "kind": "entity",
            "label": f"Corpus bound to {paths.network_id}",
            "status": "active",
            "confidence": "high",
            "provenance": [
                {
                    "source_id": f"source:{first_source_id}",
                    "locator": "verified corpus snapshot membership",
                }
            ],
        }
    ]
    for source in sorted(sources, key=lambda row: str(row.get("source_id") or "")):
        source_id = str(source["source_id"])
        nodes.append(
            {
                "node_id": f"source:{source_id}",
                "kind": "source",
                "label": str(
                    source.get("title")
                    or source.get("canonical_identity")
                    or source_id
                ),
                "status": "active" if source_id in current_ids else "deprecated",
                "confidence": (
                    "unknown" if source.get("read_depth") == "metadata" else "high"
                ),
                "provenance": _export_source_provenance(source),
            }
        )
    backed_claims, evidence_by_entity, projection_omissions = (
        _partition_evidence_backed_records(records)
    )

    for entity in sorted(
        records["entities"], key=lambda row: str(row.get("entity_id") or "")
    ):
        entity_id = str(entity["entity_id"])
        evidence = evidence_by_entity.get(entity_id)
        if evidence is None:
            projection_omissions.append(f"entity:{entity_id}:missing-evidence")
            continue
        nodes.append(
            {
                "node_id": f"entity:{entity_id}",
                "kind": "entity",
                "label": str(entity.get("name") or entity_id),
                "status": "active",
                "confidence": "medium",
                "provenance": [
                    {
                        "source_id": f"source:{evidence['source_id']}",
                        "locator": str(evidence["exact_locator"]),
                    }
                ],
            }
        )
    for claim, evidence in backed_claims:
        claim_id = str(claim["claim_id"])
        nodes.append(
            {
                "node_id": f"claim:{claim_id}",
                "kind": "claim",
                "label": str(claim.get("claim_text") or claim_id),
                "status": "active",
                "confidence": "medium",
                "provenance": [
                    {
                        "source_id": f"source:{evidence['source_id']}",
                        "locator": str(evidence["exact_locator"]),
                    }
                ],
            }
        )
    return nodes, corpus_node_id, sorted(projection_omissions)


def _projection_provenance_complete(
    nodes: list[dict[str, Any]], relations: list[dict[str, Any]]
) -> bool:
    records = [*nodes, *relations]
    for record in records:
        provenance = record.get("provenance")
        if not isinstance(provenance, list) or not provenance:
            return False
        for entry in provenance:
            if (
                not isinstance(entry, dict)
                or not str(entry.get("source_id") or "").strip()
                or not str(entry.get("locator") or "").strip()
            ):
                return False
    return True


def _export_relations(
    current_sources: list[dict[str, Any]],
    records: dict[str, list[dict[str, Any]]],
    corpus_node_id: str,
    node_ids: set[str],
) -> list[dict[str, Any]]:
    relations: list[dict[str, Any]] = []
    for source in current_sources:
        source_id = str(source["source_id"])
        relations.append(
            {
                "relation_id": f"corpus-membership:{source_id}",
                "from_id": corpus_node_id,
                "to_id": f"source:{source_id}",
                "predicate": "contains",
                "status": "supported",
                "confidence": "high",
                "provenance": _export_source_provenance(source),
            }
        )
    status_map = {
        "supports": "supported",
        "contradicts": "contradicted",
        "qualifies": "qualified",
        "not_tested": "unresolved",
    }
    for row in sorted(
        records["evidence"], key=lambda item: str(item.get("evidence_id") or "")
    ):
        relations.append(
            {
                "relation_id": f"evidence:{row['evidence_id']}",
                "from_id": f"claim:{row['claim_id']}",
                "to_id": f"source:{row['source_id']}",
                "predicate": str(row["polarity"]),
                "status": status_map[str(row["polarity"])],
                "confidence": "high",
                "provenance": [
                    {
                        "source_id": f"source:{row['source_id']}",
                        "locator": str(row["exact_locator"]),
                    }
                ],
            }
        )
    backed_claims, _, _ = _partition_evidence_backed_records(records)
    for claim, row in backed_claims:
        claim_id = str(claim["claim_id"])
        entity_id = str(claim["entity_id"])
        if (
            f"claim:{claim_id}" not in node_ids
            or f"entity:{entity_id}" not in node_ids
        ):
            continue
        relations.append(
            {
                "relation_id": f"claim-entity:{claim_id}",
                "from_id": f"claim:{claim_id}",
                "to_id": f"entity:{entity_id}",
                "predicate": "about",
                "status": "supported",
                "confidence": "high",
                "provenance": [
                    {
                        "source_id": f"source:{row['source_id']}",
                        "locator": str(row["exact_locator"]),
                    }
                ],
            }
        )
    return relations


def _export_gaps(
    gaps: list[dict[str, Any]], node_ids: set[str], corpus_node_id: str
) -> list[dict[str, Any]]:
    exported: list[dict[str, Any]] = []
    for row in _latest_gap_records(gaps):
        claim_ref = f"claim:{row.get('claim_id')}"
        derived_from = claim_ref if claim_ref in node_ids else corpus_node_id
        derivation_rule = str(row.get("derivation_rule") or "")
        reason = "missing"
        if "conflict" in derivation_rule:
            reason = "conflict"
        elif row.get("gap_type") == "implicit_candidate":
            reason = "low_confidence"
        status = str(row.get("status") or "open")
        gap_type = str(row.get("gap_type") or "deterministic_structural")
        output = {
            "gap_id": str(row["gap_id"]),
            "derived_from": [derived_from],
            "reason": reason,
            "priority": {
                "high": "decision_critical",
                "medium": "medium",
                "low": "low",
            }.get(str(row.get("impact")), "medium"),
            "impact": str(row.get("impact") or "medium"),
            "gap_type": gap_type,
            "status": "unresolved" if status == "blocked" else status,
            "next_action": str(
                row.get("transition_reason")
                or row.get("search_test")
                or row.get("description")
                or "review gap"
            ),
            "description": str(row.get("description") or "review gap"),
            "novelty_claimed": False,
        }
        if row.get("priority") in GAP_PRIORITIES:
            output["declared_priority"] = str(row["priority"])
        if row.get("decision_impact") in IMPACTS:
            output["decision_impact"] = str(row["decision_impact"])
        if str(row.get("derivation_rule") or ""):
            output["derivation_rule"] = str(row["derivation_rule"])
        if isinstance(row.get("claim_id"), str):
            output["claim_id"] = str(row["claim_id"])
        if gap_type == "implicit_candidate":
            defeaters = row.get("defeaters")
            output.update(
                {
                    "grounds": str(row.get("grounds") or ""),
                    "warrant": str(row.get("warrant") or ""),
                    "backing": str(row.get("backing") or ""),
                    "qualifier": str(row.get("qualifier") or ""),
                    "defeaters": (
                        defeaters
                        if isinstance(defeaters, list)
                        else [str(defeaters)]
                        if str(defeaters or "").strip()
                        else []
                    ),
                    "search_test": str(row.get("search_test") or ""),
                }
            )
        exported.append(output)
    return exported


def _export_change_history(
    paths: Paths,
    state: dict[str, Any],
    records: dict[str, list[dict[str, Any]]],
    first_source_id: str,
) -> list[dict[str, Any]]:
    history: list[dict[str, Any]] = []
    ordered_events = sorted(
        records["events"], key=lambda item: int(item.get("sequence") or 0)
    )
    for row in ordered_events:
        if row.get("event_type") == "patch_decision":
            operator = row.get("operator")
            authority = (
                operator.get("authority_basis", [])
                if isinstance(operator, dict)
                else []
            )
            basis_refs = sorted(
                {
                    "authority:sha256:" + str(item.get("artifact_sha256"))
                    for item in authority
                    if isinstance(item, dict)
                    and isinstance(item.get("artifact_sha256"), str)
                }
            )
            object_ids = sorted(
                {
                    str(identifier)
                    for decision in row.get("decisions", [])
                    if isinstance(decision, dict)
                    for identifier in [
                        decision.get("action_id"),
                        *[
                            operation.get("operation_id")
                            for operation in decision.get("operations", [])
                            if isinstance(operation, dict)
                        ],
                    ]
                    if isinstance(identifier, str) and identifier
                }
            )
            if not basis_refs or not object_ids:
                continue
            history.append(
                {
                    "change_id": str(row["record_id"]),
                    "action": "patch-decision",
                    "object_ids": object_ids,
                    "basis_refs": basis_refs,
                    "recorded_at": str(
                        row.get("recorded_at") or state["created_at"]
                    ),
                }
            )
            continue
        history.append(
            {
                "change_id": str(row["record_id"]),
                "action": str(row.get("event_type") or "event"),
                "object_ids": [paths.network_id],
                "basis_refs": [f"source:{first_source_id}"],
                "recorded_at": str(row.get("recorded_at") or state["created_at"]),
            }
        )
    for row in _latest_gap_records(records["gaps"]):
        if row.get("transition_from_record_id") is None:
            continue
        history.append(
            {
                "change_id": f"change:{row['record_id']}",
                "action": "transition-gap",
                "object_ids": [str(row["gap_id"])],
                "basis_refs": [f"source:{first_source_id}"],
                "recorded_at": str(row.get("recorded_at") or state["created_at"]),
            }
        )
    if not history:
        history.append(
            {
                "change_id": f"change:export:{paths.network_id}",
                "action": "export",
                "object_ids": [paths.network_id],
                "basis_refs": [f"source:{first_source_id}"],
                "recorded_at": str(state["created_at"]),
            }
        )
    return history


def _knowledge_network_export(
    paths: Paths, state: dict[str, Any], records: dict[str, list[dict[str, Any]]]
) -> dict[str, Any]:
    ledger_sources = sorted(
        records["sources"], key=lambda row: str(row.get("record_id"))
    )
    export_sources = _export_sources(state, ledger_sources)
    current_sources = _export_current_sources(state, export_sources)
    nodes, corpus_node_id, projection_omissions = _export_nodes(
        paths, export_sources, current_sources, records
    )
    node_ids = {str(node["node_id"]) for node in nodes}
    relations = _export_relations(
        current_sources, records, corpus_node_id, node_ids
    )
    gaps = _export_gaps(records["gaps"], node_ids, corpus_node_id)
    status = _derive_status_summary(paths, state, records)
    open_gap_ids = sorted(
        str(gap["gap_id"]) for gap in gaps if gap.get("status") == "open"
    )
    conflicts_terminal = not status["open_conflicts"]
    low_confidence_terminal = not any(
        relation.get("status") == "unresolved" for relation in relations
    )
    gate_checks = {
        "corpus_snapshotted": bool(current_sources),
        "provenance_complete": (
            not projection_omissions
            and _projection_provenance_complete(nodes, relations)
        ),
        "conflicts_terminal": conflicts_terminal,
        "low_confidence_edges_terminal": low_confidence_terminal,
        "high_priority_explicit_gaps_terminal": not status[
            "open_high_priority_explicit_gap_ids"
        ],
        "change_history_recorded": True,
    }
    completion_status = "partial"
    if status["completion"]["can_complete"] and not open_gap_ids and all(
        gate_checks.values()
    ):
        completion_status = "passed"
    elif any(gap.get("status") == "unresolved" for gap in gaps):
        completion_status = "blocked"

    snapshot_digest = str(
        state.get("corpus_snapshot_state_sha256")
        or state.get("corpus_snapshot_digest")
        or ""
    ).removeprefix("sha256:")
    internal_digest = _sha256_json(
        {
            "state": state,
            "records": {
                name: sorted(rows, key=lambda row: int(row.get("sequence") or 0))
                for name, rows in records.items()
            },
        }
    ).split(":", 1)[1]
    first_source_id = str(current_sources[0]["source_id"])
    zotero_bound = any(row.get("role") == "zotero_corpus" for row in ledger_sources)
    payload: dict[str, Any] = {
        "schema": "KnowledgeNetwork/v1",
        "network_id": paths.network_id,
        "snapshot_id": f"{paths.network_id}-S{internal_digest[:16]}",
        "corpus_snapshot": {
            "source": "zotero" if zotero_bound else "local",
            "target_ref": (
                f"private:zotero-corpus:{snapshot_digest[:16]}"
                if zotero_bound
                else "private:local-corpus"
            ),
            "captured_at": str(state["created_at"]),
            "inventory_digest": snapshot_digest,
            "item_count": len(current_sources),
            "item_refs": [
                f"private:item:{row['source_id']}" for row in current_sources
            ],
        },
        "nodes": nodes,
        "relations": relations,
        "gap_derivation": {
            "rules": ["missing", "conflict", "low_confidence"],
            "derived_gap_ids": [str(gap["gap_id"]) for gap in gaps],
        },
        "gaps": gaps,
        "change_history": _export_change_history(
            paths, state, records, first_source_id
        ),
        "completion": {
            "status": completion_status,
            "open_gap_ids": open_gap_ids,
            "blocking_gap_ids": status["open_high_priority_explicit_gap_ids"],
            "gate_checks": gate_checks,
        },
        "sources": export_sources,
        "claims": sorted(
            records["claims"], key=lambda row: str(row.get("record_id"))
        ),
        "evidence": sorted(
            records["evidence"], key=lambda row: str(row.get("record_id"))
        ),
        "events": sorted(
            records["events"], key=lambda row: str(row.get("record_id"))
        ),
        "projection_omissions": projection_omissions,
        "ledger_digest": internal_digest,
    }
    payload["content_sha256"] = _sha256_json(payload).split(":", 1)[1]
    return payload


def command_export(args: argparse.Namespace) -> int:
    paths = _safe_paths(args.root, args.network_id)
    state, records = _load_state(paths)
    errors = _validate_record_shapes(paths, state, records)
    if errors:
        print("validation errors:\n" + "\n".join(errors), file=sys.stderr)
        return 1
    try:
        payload = _knowledge_network_export(paths, state, records)
    except ValueError as exc:
        print(f"KnowledgeNetwork/v1 export failed: {exc}", file=sys.stderr)
        return 1
    output = json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2)
    if args.output is not None:
        output_path = _safe_relative_path(paths.root, args.output, "output")
        if output_path.is_symlink():
            print("output is symlink", file=sys.stderr)
            return 1
        _write_json_atomic(output_path, payload)
        return 0
    print(output)
    return 0


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Operate a local auditable research knowledge network",
        exit_on_error=False,
    )
    parser.add_argument("--root", required=True)
    parser.add_argument("--network-id", required=True)
    commands = parser.add_subparsers(dest="command", required=True)

    init = commands.add_parser("init")
    init.add_argument("--question", required=True)
    init.add_argument("--scope", required=True)
    init.add_argument("--snapshot-path", required=True)
    init.add_argument("--snapshot-digest", required=True)
    init.add_argument("--required-dimension", action="append", default=[])
    init.add_argument("--required-benchmark-profile", action="append", default=[])
    init.set_defaults(func=command_init)

    add_source = commands.add_parser("add-source")
    add_source.add_argument("--source-id", required=True)
    add_source.add_argument("--canonical-identity", required=True)
    add_source.add_argument("--canonical-version", required=True)
    add_source.add_argument("--read-version", required=True)
    add_source.add_argument("--read-depth", required=True)
    add_source.add_argument("--version-hash", required=True)
    add_source.add_argument("--role", default="")
    add_source.add_argument("--notes", default="")
    add_source.add_argument("--supersedes")
    add_source.set_defaults(func=command_add_source)

    add_entity = commands.add_parser("add-entity")
    add_entity.add_argument("--entity-id", required=True)
    add_entity.add_argument("--entity-type", required=True)
    add_entity.add_argument("--name", required=True)
    add_entity.add_argument("--description", required=True)
    add_entity.add_argument("--supersedes")
    add_entity.set_defaults(func=command_add_entity)

    add_claim = commands.add_parser("add-claim")
    add_claim.add_argument("--claim-id", required=True)
    add_claim.add_argument("--claim-text", required=True)
    add_claim.add_argument("--entity-id")
    add_claim.add_argument("--impact", required=True)
    add_claim.add_argument("--scope-statement", default="")
    add_claim.add_argument("--assumption", action="append", default=[])
    add_claim.add_argument("--condition", action="append", default=[])
    add_claim.add_argument("--unit", action="append", default=[])
    add_claim.add_argument("--exclusion", action="append", default=[])
    add_claim.add_argument("--defeater", action="append", default=[])
    add_claim.add_argument("--coverage-dimension", action="append", default=[])
    add_claim.add_argument("--benchmark-profile", action="append", default=[])
    add_claim.add_argument("--supersedes")
    add_claim.set_defaults(func=command_add_claim)

    add_evidence = commands.add_parser("add-evidence")
    add_evidence.add_argument("--evidence-id", required=True)
    add_evidence.add_argument("--claim-id", required=True)
    add_evidence.add_argument("--source-id", required=True)
    add_evidence.add_argument(
        "--polarity", required=True, choices=sorted(EVIDENCE_POLARITY)
    )
    add_evidence.add_argument("--exact-locator", required=True)
    add_evidence.add_argument("--independence-group", required=True)
    add_evidence.add_argument("--summary", required=True)
    add_evidence.add_argument("--notes", default="")
    add_evidence.add_argument("--supersedes")
    add_evidence.set_defaults(func=command_add_evidence)

    add_relation = commands.add_parser("add-relation")
    add_relation.add_argument("--relation-id", required=True)
    add_relation.add_argument("--relation-type", required=True)
    add_relation.add_argument("--from-ref", required=True)
    add_relation.add_argument("--to-ref", required=True)
    add_relation.add_argument("--notes", default="")
    add_relation.add_argument("--supersedes")
    add_relation.set_defaults(func=command_add_relation)

    record_gap = commands.add_parser("record-gap")
    record_gap.add_argument("--gap-id", required=True)
    record_gap.add_argument("--gap-type", required=True, choices=sorted(GAP_TYPES))
    record_gap.add_argument("--claim-id")
    record_gap.add_argument("--impact", required=True)
    record_gap.add_argument("--priority", choices=sorted(GAP_PRIORITIES))
    record_gap.add_argument("--decision-impact", choices=sorted(IMPACTS))
    record_gap.add_argument("--status", required=True, choices=sorted(GAP_STATUSES))
    record_gap.add_argument("--source", default="manual")
    record_gap.add_argument("--description", required=True)
    record_gap.add_argument("--grounds")
    record_gap.add_argument("--warrant")
    record_gap.add_argument("--backing")
    record_gap.add_argument("--qualifier")
    record_gap.add_argument("--defeaters")
    record_gap.add_argument("--search-test")
    record_gap.add_argument("--novelty-claimed", action="store_true")
    record_gap.add_argument(
        "--resolution-evidence-ref", action="append", default=[]
    )
    record_gap.add_argument("--resolution-source")
    record_gap.set_defaults(func=command_record_gap)

    transition_gap = commands.add_parser("transition-gap")
    transition_gap.add_argument("--gap-id", required=True)
    transition_gap.add_argument("--from-record-id", required=True)
    transition_gap.add_argument(
        "--status", required=True, choices=sorted(GAP_STATUSES)
    )
    transition_gap.add_argument("--reason", required=True)
    transition_gap.add_argument("--evidence-ref", action="append", default=[])
    transition_gap.add_argument("--resolution-source")
    transition_gap.set_defaults(func=command_transition_gap)

    derive = commands.add_parser("derive-gaps")
    derive.set_defaults(func=command_derive_gaps)

    status = commands.add_parser("status")
    status.set_defaults(func=command_status)

    validate = commands.add_parser("validate")
    validate.set_defaults(func=command_validate)

    ingest = commands.add_parser("ingest-zotero-snapshot")
    ingest.add_argument("--snapshot", required=True)
    ingest.add_argument("--allow-refresh", action="store_true")
    ingest.set_defaults(func=command_ingest_zotero_snapshot)

    snapshot = commands.add_parser("snapshot")
    snapshot.add_argument("--output", required=False)
    snapshot.set_defaults(func=command_snapshot)

    export = commands.add_parser("export")
    export.add_argument("--output", required=False)
    export.set_defaults(func=command_export)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    try:
        args = parser.parse_args(argv)
    except argparse.ArgumentError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    except SystemExit as exc:
        return int(exc.code) if isinstance(exc.code, int) else 2
    try:
        if not args.command:
            return 2
        return args.func(args)
    except (
        FileNotFoundError,
        OSError,
        ValueError,
        KeyError,
        TypeError,
        json.JSONDecodeError,
    ) as exc:
        print(f"{exc.__class__.__name__}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
