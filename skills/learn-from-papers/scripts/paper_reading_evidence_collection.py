#!/usr/bin/env python3
"""Build and validate multi-source PaperReadingEvidenceCollection/v1 artifacts.

The collection is an aggregate of immutable, finalized
PaperReadingReportSet/v2 groups.  It does not merge reports, infer scientific
independence, or change any per-paper contract.  Its small public interface is
``build_collection(group_specs)`` and ``validate_collection(collection)``;
all live artifact replay stays behind that seam.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import re
import stat
from copy import deepcopy
from pathlib import Path
from typing import Any


SCRIPT_DIR = Path(__file__).resolve().parent


def _load_sibling(name: str, filename: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, SCRIPT_DIR / filename)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"failed to load {filename}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_source_bundle = _load_sibling(
    "paper_reading_evidence_collection_source_bundle",
    "paper_source_bundle.py",
)
_reading_dossier = _load_sibling(
    "paper_reading_evidence_collection_dossier",
    "paper_reading_dossier.py",
)


SCHEMA = "PaperReadingEvidenceCollection/v1"
SCHEMA_VERSION = "v1"
COLLECTION_ID_PREFIX = "paper-reading-evidence-collection-"
GROUP_ID_PREFIX = "paper-reading-evidence-group-"
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")

TOP_LEVEL_KEYS = {
    "schema",
    "schema_version",
    "collection_id",
    "collection_digest",
    "network_ref",
    "review_request_set_ref",
    "reading_groups",
}
NETWORK_REF_KEYS = {"network_id", "snapshot_id", "sha256"}
REQUEST_SET_REF_KEYS = {"review_request_set_id", "review_request_set_digest"}
GROUP_SPEC_KEYS = {
    "reading_reports",
    "dossier",
    "source_bundle",
    "source_artifact",
    "verification_root",
}
GROUP_KEYS = {
    "reading_group_id",
    "reading_group_digest",
    "refs",
    "report_set_ref",
    "dossier_ref",
    "source_bundle_ref",
    "source_ref",
}
GROUP_REFS_KEYS = GROUP_SPEC_KEYS
FILE_REF_KEYS = {"path", "sha256"}
TREE_REF_KEYS = {"path", "tree_digest"}
REPORT_SET_REF_KEYS = {"report_set_id", "report_set_digest"}
DOSSIER_REF_KEYS = {"dossier_id", "dossier_digest"}
SOURCE_BUNDLE_REF_KEYS = {"source_bundle_id", "source_bundle_digest"}
SOURCE_REF_KEYS = {"source_id", "source_digest"}


class ContractError(ValueError):
    """Raised when an evidence-collection invariant is violated."""


def canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def canonical_sha256(value: Any) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def canonical_group_digest(group: dict[str, Any]) -> str:
    return canonical_sha256(
        {
            key: value
            for key, value in group.items()
            if key not in {"reading_group_id", "reading_group_digest"}
        }
    )


def canonical_collection_digest(collection: dict[str, Any]) -> str:
    return canonical_sha256(
        {
            key: value
            for key, value in collection.items()
            if key not in {"collection_id", "collection_digest"}
        }
    )


def _content_id(prefix: str, digest: str) -> str:
    return f"{prefix}{digest[:16]}"


def _require_dict(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ContractError(f"{label} must be an object")
    return value


def _require_list(value: Any, label: str) -> list[Any]:
    if not isinstance(value, list):
        raise ContractError(f"{label} must be a list")
    return value


def _require_string(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise ContractError(f"{label} must be a non-empty string")
    if value != value.strip():
        raise ContractError(f"{label} must not contain surrounding whitespace")
    return value


def _require_sha256(value: Any, label: str) -> str:
    digest = _require_string(value, label)
    if not SHA256_RE.fullmatch(digest):
        raise ContractError(f"{label} must be 64 lowercase hex characters")
    return digest


def _reject_unknown_fields(
    value: dict[str, Any], allowed: set[str], label: str
) -> None:
    unknown = sorted(set(value) - allowed)
    missing = sorted(allowed - set(value))
    if unknown:
        raise ContractError(f"{label} contains unknown fields: {', '.join(unknown)}")
    if missing:
        raise ContractError(f"{label} is missing fields: {', '.join(missing)}")


def _validate_network_ref(value: Any, label: str) -> dict[str, str]:
    raw = _require_dict(value, label)
    _reject_unknown_fields(raw, NETWORK_REF_KEYS, label)
    return {
        "network_id": _require_string(raw.get("network_id"), f"{label}.network_id"),
        "snapshot_id": _require_string(raw.get("snapshot_id"), f"{label}.snapshot_id"),
        "sha256": _require_sha256(raw.get("sha256"), f"{label}.sha256"),
    }


def _validate_request_set_ref(value: Any, label: str) -> dict[str, str]:
    raw = _require_dict(value, label)
    _reject_unknown_fields(raw, REQUEST_SET_REF_KEYS, label)
    return {
        "review_request_set_id": _require_string(
            raw.get("review_request_set_id"),
            f"{label}.review_request_set_id",
        ),
        "review_request_set_digest": _require_sha256(
            raw.get("review_request_set_digest"),
            f"{label}.review_request_set_digest",
        ),
    }


def _validate_declared_ref(
    value: Any,
    *,
    label: str,
    keys: set[str],
    id_key: str,
    digest_key: str,
) -> dict[str, str]:
    raw = _require_dict(value, label)
    _reject_unknown_fields(raw, keys, label)
    return {
        id_key: _require_string(raw.get(id_key), f"{label}.{id_key}"),
        digest_key: _require_sha256(raw.get(digest_key), f"{label}.{digest_key}"),
    }


def _reject_symlink_components(path: Path, label: str) -> None:
    current = Path(path.anchor)
    for part in path.parts[1:]:
        current = current / part
        try:
            mode = os.lstat(current).st_mode
        except FileNotFoundError as exc:
            raise ContractError(f"{label} does not exist: {path}") from exc
        if stat.S_ISLNK(mode):
            raise ContractError(f"{label} must not traverse a symlink: {current}")


def _canonical_existing_path(value: Any, label: str, *, directory: bool) -> Path:
    text = _require_string(value, label)
    path = Path(text)
    if not path.is_absolute():
        raise ContractError(f"{label} must be an absolute path")
    if str(path) != text:
        raise ContractError(f"{label} must be a canonical absolute path")
    _reject_symlink_components(path, label)
    try:
        resolved = path.resolve(strict=True)
    except OSError as exc:
        raise ContractError(f"{label} cannot be resolved: {path}") from exc
    if str(resolved) != text:
        raise ContractError(f"{label} must be a canonical absolute path")
    mode = os.stat(path, follow_symlinks=False).st_mode
    if directory and not stat.S_ISDIR(mode):
        raise ContractError(f"{label} must be a directory: {path}")
    if not directory and not stat.S_ISREG(mode):
        raise ContractError(f"{label} must be a regular file: {path}")
    return path


def _file_fingerprint(metadata: os.stat_result) -> tuple[int, ...]:
    return (
        metadata.st_dev,
        metadata.st_ino,
        metadata.st_mode,
        metadata.st_size,
        metadata.st_mtime_ns,
        metadata.st_ctime_ns,
    )


def _read_regular_file(path: Path, label: str) -> bytes:
    before = os.stat(path, follow_symlinks=False)
    if not stat.S_ISREG(before.st_mode):
        raise ContractError(f"{label} must be a regular file")
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
    descriptor = os.open(path, flags)
    try:
        opened = os.fstat(descriptor)
        if not stat.S_ISREG(opened.st_mode):
            raise ContractError(f"{label} must be a regular file")
        if _file_fingerprint(before) != _file_fingerprint(opened):
            raise ContractError(f"{label} changed before it was opened")
        with os.fdopen(descriptor, "rb") as stream:
            descriptor = -1
            payload = stream.read()
            descriptor_after = os.fstat(stream.fileno())
    finally:
        if descriptor != -1:
            os.close(descriptor)
    after = os.stat(path, follow_symlinks=False)
    stable = _file_fingerprint(before)
    if any(
        fingerprint != stable
        for fingerprint in (
            _file_fingerprint(descriptor_after),
            _file_fingerprint(after),
        )
    ):
        raise ContractError(f"{label} changed while it was read")
    if len(payload) != descriptor_after.st_size:
        raise ContractError(f"{label} size changed while it was read")
    return payload


def _file_sha256(path: Path, label: str) -> str:
    return hashlib.sha256(_read_regular_file(path, label)).hexdigest()


def _load_json_bytes(payload: bytes, label: str) -> dict[str, Any]:
    try:
        value = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ContractError(f"{label} must contain a UTF-8 JSON object") from exc
    return _require_dict(value, label)


def _verification_tree_entries(root: Path) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []

    def visit(directory: Path, relative: Path) -> None:
        try:
            with os.scandir(directory) as iterator:
                children = sorted(iterator, key=lambda item: item.name)
        except OSError as exc:
            raise ContractError(f"cannot read verification tree: {directory}") from exc
        for child in children:
            child_path = directory / child.name
            child_relative = relative / child.name
            mode = child.stat(follow_symlinks=False).st_mode
            if stat.S_ISLNK(mode):
                raise ContractError(
                    f"verification tree must not contain symlinks: {child_path}"
                )
            if stat.S_ISDIR(mode):
                entries.append({"kind": "directory", "path": child_relative.as_posix()})
                visit(child_path, child_relative)
                continue
            if not stat.S_ISREG(mode):
                raise ContractError(
                    "verification tree may contain only regular files and "
                    f"directories: {child_path}"
                )
            payload = _read_regular_file(
                child_path,
                f"verification tree file {child_relative.as_posix()}",
            )
            entries.append(
                {
                    "kind": "file",
                    "path": child_relative.as_posix(),
                    "sha256": hashlib.sha256(payload).hexdigest(),
                    "size_bytes": len(payload),
                }
            )

    visit(root, Path())
    return entries


def verification_tree_digest(root: str | Path) -> str:
    path = _canonical_existing_path(str(root), "verification_root", directory=True)
    return canonical_sha256(_verification_tree_entries(path))


def _validate_file_ref(value: Any, label: str) -> tuple[dict[str, str], Path]:
    raw = _require_dict(value, label)
    _reject_unknown_fields(raw, FILE_REF_KEYS, label)
    path = _canonical_existing_path(raw.get("path"), f"{label}.path", directory=False)
    return (
        {
            "path": str(path),
            "sha256": _require_sha256(raw.get("sha256"), f"{label}.sha256"),
        },
        path,
    )


def _validate_tree_ref(value: Any, label: str) -> tuple[dict[str, str], Path]:
    raw = _require_dict(value, label)
    _reject_unknown_fields(raw, TREE_REF_KEYS, label)
    path = _canonical_existing_path(raw.get("path"), f"{label}.path", directory=True)
    return (
        {
            "path": str(path),
            "tree_digest": _require_sha256(
                raw.get("tree_digest"), f"{label}.tree_digest"
            ),
        },
        path,
    )


def _live_group_from_refs(
    refs: dict[str, Any], label: str
) -> tuple[dict[str, Any], dict[str, Any]]:
    _reject_unknown_fields(refs, GROUP_REFS_KEYS, f"{label}.refs")
    normalized_refs: dict[str, dict[str, str]] = {}
    paths: dict[str, Path] = {}
    for name in ("reading_reports", "dossier", "source_bundle", "source_artifact"):
        normalized_refs[name], paths[name] = _validate_file_ref(
            refs.get(name), f"{label}.refs.{name}"
        )
    normalized_refs["verification_root"], paths["verification_root"] = (
        _validate_tree_ref(
            refs.get("verification_root"),
            f"{label}.refs.verification_root",
        )
    )

    before_hashes = {
        name: _file_sha256(paths[name], f"{label}.{name}")
        for name in ("reading_reports", "dossier", "source_bundle", "source_artifact")
    }
    before_tree = verification_tree_digest(paths["verification_root"])
    for name, digest in before_hashes.items():
        if normalized_refs[name]["sha256"] != digest:
            raise ContractError(f"{label}.refs.{name}.sha256 does not match live bytes")
    if normalized_refs["verification_root"]["tree_digest"] != before_tree:
        raise ContractError(
            f"{label}.refs.verification_root.tree_digest does not match live tree"
        )

    report_set_raw = _load_json_bytes(
        _read_regular_file(paths["reading_reports"], f"{label}.reading_reports"),
        f"{label}.reading_reports",
    )
    dossier_raw = _load_json_bytes(
        _read_regular_file(paths["dossier"], f"{label}.dossier"),
        f"{label}.dossier",
    )

    try:
        verified_bundle = _source_bundle.verify_bundle(
            bundle=str(paths["source_bundle"]),
            source=str(paths["source_artifact"]),
        )
        validated_dossier = _reading_dossier.validate_dossier(
            dossier_raw,
            bundle=str(paths["source_bundle"]),
            source=str(paths["source_artifact"]),
        )
        validated_report_set = _reading_dossier.validate_report_set_v2(
            report_set_raw,
            verification_root=str(paths["verification_root"]),
            require_finalized=True,
        )
    except (_source_bundle.ContractError, _reading_dossier.ContractError) as exc:
        raise ContractError(f"{label} official replay failed: {exc}") from exc

    after_hashes = {
        name: _file_sha256(paths[name], f"{label}.{name}")
        for name in ("reading_reports", "dossier", "source_bundle", "source_artifact")
    }
    after_tree = verification_tree_digest(paths["verification_root"])
    if after_hashes != before_hashes or after_tree != before_tree:
        raise ContractError(f"{label} artifacts changed during live replay")

    network_ref = validated_report_set["network_ref"]
    if validated_dossier["network_ref"] != network_ref:
        raise ContractError(f"{label} dossier/report-set network_ref mismatch")
    request_set_ref = {
        "review_request_set_id": validated_report_set["review_request_set_id"],
        "review_request_set_digest": validated_report_set["review_request_set_digest"],
    }
    if request_set_ref != {
        "review_request_set_id": validated_dossier["review_request_set_id"],
        "review_request_set_digest": validated_dossier["review_request_set_digest"],
    }:
        raise ContractError(f"{label} dossier/report-set review request mismatch")

    expected_bundle_ref = {
        "source_bundle_id": verified_bundle["bundle_id"],
        "source_bundle_digest": verified_bundle["bundle_digest"],
    }
    if expected_bundle_ref != {
        "source_bundle_id": validated_dossier["source_bundle"]["bundle_id"],
        "source_bundle_digest": validated_dossier["source_bundle"]["bundle_digest"],
    }:
        raise ContractError(f"{label} dossier/source-bundle identity mismatch")
    if expected_bundle_ref != {
        "source_bundle_id": validated_report_set["source_bundle_id"],
        "source_bundle_digest": validated_report_set["source_bundle_digest"],
    }:
        raise ContractError(f"{label} report-set/source-bundle identity mismatch")

    source_sha256 = verified_bundle["source"]["source_sha256"]
    if before_hashes["source_artifact"] != source_sha256:
        raise ContractError(f"{label} source artifact hash mismatch")
    if validated_dossier["source_bundle"]["source_artifact_sha256"] != source_sha256:
        raise ContractError(f"{label} dossier source artifact hash mismatch")
    if validated_report_set["source_artifact_sha256"] != source_sha256:
        raise ContractError(f"{label} report-set source artifact hash mismatch")

    source_name = verified_bundle["source"]["name"]
    if validated_dossier["source_bundle"]["source_ref"] != source_name:
        raise ContractError(f"{label} dossier source_ref mismatch")
    if validated_report_set["source_ref"] != source_name:
        raise ContractError(f"{label} report-set source_ref mismatch")
    if validated_report_set["review_source"] != validated_dossier["review_source"]:
        raise ContractError(f"{label} dossier/report-set review_source mismatch")

    if validated_report_set["dossier_id"] != validated_dossier["dossier_id"]:
        raise ContractError(f"{label} dossier_id mismatch")
    if validated_report_set["dossier_digest"] != validated_dossier["dossier_digest"]:
        raise ContractError(f"{label} dossier_digest mismatch")

    live = {
        "network_ref": deepcopy(network_ref),
        "review_request_set_ref": request_set_ref,
        "report_set_ref": {
            "report_set_id": validated_report_set["report_set_id"],
            "report_set_digest": validated_report_set["report_set_digest"],
        },
        "dossier_ref": {
            "dossier_id": validated_dossier["dossier_id"],
            "dossier_digest": validated_dossier["dossier_digest"],
        },
        "source_bundle_ref": expected_bundle_ref,
        "source_ref": {
            "source_id": validated_report_set["review_source"]["source_id"],
            "source_digest": validated_report_set["review_source"]["source_digest"],
        },
        "source_artifact_sha256": source_sha256,
        "access_level": validated_report_set["access_level"],
    }
    return normalized_refs, live


def _group_sort_key(group: dict[str, Any]) -> tuple[str, str, str]:
    return (
        group["source_ref"]["source_id"],
        group["report_set_ref"]["report_set_id"],
        group["reading_group_id"],
    )


def _build_group(spec: Any, index: int) -> tuple[dict[str, Any], dict[str, Any]]:
    raw = _require_dict(spec, f"group_specs[{index}]")
    _reject_unknown_fields(raw, GROUP_SPEC_KEYS, f"group_specs[{index}]")
    refs: dict[str, Any] = {}
    for name in ("reading_reports", "dossier", "source_bundle", "source_artifact"):
        path = _canonical_existing_path(
            raw.get(name), f"group_specs[{index}].{name}", directory=False
        )
        refs[name] = {
            "path": str(path),
            "sha256": _file_sha256(path, f"group_specs[{index}].{name}"),
        }
    verification_root = _canonical_existing_path(
        raw.get("verification_root"),
        f"group_specs[{index}].verification_root",
        directory=True,
    )
    refs["verification_root"] = {
        "path": str(verification_root),
        "tree_digest": verification_tree_digest(verification_root),
    }
    normalized_refs, live = _live_group_from_refs(refs, f"reading_groups[{index}]")
    group = {
        "refs": normalized_refs,
        "report_set_ref": live["report_set_ref"],
        "dossier_ref": live["dossier_ref"],
        "source_bundle_ref": live["source_bundle_ref"],
        "source_ref": live["source_ref"],
    }
    group["reading_group_digest"] = canonical_group_digest(group)
    group["reading_group_id"] = _content_id(
        GROUP_ID_PREFIX, group["reading_group_digest"]
    )
    return group, live


def _validate_group(value: Any, index: int) -> tuple[dict[str, Any], dict[str, Any]]:
    label = f"reading_groups[{index}]"
    raw = _require_dict(deepcopy(value), label)
    _reject_unknown_fields(raw, GROUP_KEYS, label)
    reading_group_id = _require_string(
        raw.get("reading_group_id"), f"{label}.reading_group_id"
    )
    reading_group_digest = _require_sha256(
        raw.get("reading_group_digest"), f"{label}.reading_group_digest"
    )
    refs_raw = _require_dict(raw.get("refs"), f"{label}.refs")
    normalized_refs, live = _live_group_from_refs(refs_raw, label)
    group = {
        "refs": normalized_refs,
        "report_set_ref": _validate_declared_ref(
            raw.get("report_set_ref"),
            label=f"{label}.report_set_ref",
            keys=REPORT_SET_REF_KEYS,
            id_key="report_set_id",
            digest_key="report_set_digest",
        ),
        "dossier_ref": _validate_declared_ref(
            raw.get("dossier_ref"),
            label=f"{label}.dossier_ref",
            keys=DOSSIER_REF_KEYS,
            id_key="dossier_id",
            digest_key="dossier_digest",
        ),
        "source_bundle_ref": _validate_declared_ref(
            raw.get("source_bundle_ref"),
            label=f"{label}.source_bundle_ref",
            keys=SOURCE_BUNDLE_REF_KEYS,
            id_key="source_bundle_id",
            digest_key="source_bundle_digest",
        ),
        "source_ref": _validate_declared_ref(
            raw.get("source_ref"),
            label=f"{label}.source_ref",
            keys=SOURCE_REF_KEYS,
            id_key="source_id",
            digest_key="source_digest",
        ),
    }
    for name in ("report_set_ref", "dossier_ref", "source_bundle_ref", "source_ref"):
        if group[name] != live[name]:
            raise ContractError(f"{label}.{name} does not match live artifacts")
    expected_digest = canonical_group_digest(group)
    if reading_group_digest != expected_digest:
        raise ContractError(f"{label}.reading_group_digest does not match payload")
    expected_id = _content_id(GROUP_ID_PREFIX, expected_digest)
    if reading_group_id != expected_id:
        raise ContractError(f"{label}.reading_group_id does not match digest")
    group["reading_group_digest"] = expected_digest
    group["reading_group_id"] = expected_id
    return group, live


def _require_unique(values: list[str], label: str) -> None:
    if len(values) != len(set(values)):
        raise ContractError(f"reading_groups must use unique {label}")


def _validate_group_set(
    groups: list[dict[str, Any]], live_groups: list[dict[str, Any]]
) -> tuple[dict[str, str], dict[str, str]]:
    if len(groups) < 2:
        raise ContractError("reading_groups must contain at least two groups")
    if [group["reading_group_id"] for group in groups] != [
        group["reading_group_id"] for group in sorted(groups, key=_group_sort_key)
    ]:
        raise ContractError("reading_groups must use canonical order")

    _require_unique([group["reading_group_id"] for group in groups], "reading_group_id")
    _require_unique(
        [group["reading_group_digest"] for group in groups],
        "reading_group_digest",
    )
    _require_unique(
        [group["report_set_ref"]["report_set_id"] for group in groups],
        "report_set_id",
    )
    _require_unique(
        [group["report_set_ref"]["report_set_digest"] for group in groups],
        "report_set_digest",
    )
    _require_unique(
        [group["refs"]["reading_reports"]["sha256"] for group in groups],
        "reading_reports hash",
    )
    _require_unique([group["source_ref"]["source_id"] for group in groups], "source_id")
    _require_unique(
        [group["source_ref"]["source_digest"] for group in groups],
        "source_digest",
    )
    _require_unique(
        [live["source_artifact_sha256"] for live in live_groups],
        "source artifact hash",
    )

    network_ref = live_groups[0]["network_ref"]
    request_set_ref = live_groups[0]["review_request_set_ref"]
    if any(live["network_ref"] != network_ref for live in live_groups[1:]):
        raise ContractError("reading_groups contain mixed network_ref values")
    if any(
        live["review_request_set_ref"] != request_set_ref for live in live_groups[1:]
    ):
        raise ContractError(
            "reading_groups contain mixed review_request_set_ref values"
        )
    if not any(live["access_level"] == "full_text" for live in live_groups):
        raise ContractError("reading_groups require at least one full_text source")
    return deepcopy(network_ref), deepcopy(request_set_ref)


def build_collection(group_specs: list[dict[str, str]]) -> dict[str, Any]:
    """Build a collection by replaying explicit, one-source group specs."""

    specs = _require_list(group_specs, "group_specs")
    if len(specs) < 2:
        raise ContractError("group_specs must contain at least two groups")
    built = [_build_group(spec, index) for index, spec in enumerate(specs)]
    built.sort(key=lambda item: _group_sort_key(item[0]))
    groups = [item[0] for item in built]
    live_groups = [item[1] for item in built]
    network_ref, request_set_ref = _validate_group_set(groups, live_groups)
    collection = {
        "schema": SCHEMA,
        "schema_version": SCHEMA_VERSION,
        "network_ref": network_ref,
        "review_request_set_ref": request_set_ref,
        "reading_groups": groups,
    }
    collection["collection_digest"] = canonical_collection_digest(collection)
    collection["collection_id"] = _content_id(
        COLLECTION_ID_PREFIX, collection["collection_digest"]
    )
    return validate_collection(collection)


def validate_collection(collection: dict[str, Any]) -> dict[str, Any]:
    """Reopen and validate an exact PaperReadingEvidenceCollection/v1."""

    raw = _require_dict(deepcopy(collection), "collection")
    _reject_unknown_fields(raw, TOP_LEVEL_KEYS, "collection")
    if raw.get("schema") != SCHEMA:
        raise ContractError(f"collection.schema must equal {SCHEMA}")
    if raw.get("schema_version") != SCHEMA_VERSION:
        raise ContractError(f"collection.schema_version must equal {SCHEMA_VERSION}")
    declared_id = _require_string(raw.get("collection_id"), "collection.collection_id")
    declared_digest = _require_sha256(
        raw.get("collection_digest"), "collection.collection_digest"
    )
    declared_network_ref = _validate_network_ref(
        raw.get("network_ref"), "collection.network_ref"
    )
    declared_request_set_ref = _validate_request_set_ref(
        raw.get("review_request_set_ref"), "collection.review_request_set_ref"
    )
    group_values = _require_list(raw.get("reading_groups"), "collection.reading_groups")
    validated = [
        _validate_group(group, index) for index, group in enumerate(group_values)
    ]
    groups = [item[0] for item in validated]
    live_groups = [item[1] for item in validated]
    network_ref, request_set_ref = _validate_group_set(groups, live_groups)
    if declared_network_ref != network_ref:
        raise ContractError("collection.network_ref does not match live groups")
    if declared_request_set_ref != request_set_ref:
        raise ContractError(
            "collection.review_request_set_ref does not match live groups"
        )
    normalized = {
        "schema": SCHEMA,
        "schema_version": SCHEMA_VERSION,
        "network_ref": network_ref,
        "review_request_set_ref": request_set_ref,
        "reading_groups": groups,
    }
    expected_digest = canonical_collection_digest(normalized)
    if declared_digest != expected_digest:
        raise ContractError("collection.collection_digest does not match payload")
    expected_id = _content_id(COLLECTION_ID_PREFIX, expected_digest)
    if declared_id != expected_id:
        raise ContractError("collection.collection_id does not match digest")
    normalized["collection_digest"] = expected_digest
    normalized["collection_id"] = expected_id
    return normalized


__all__ = [
    "ContractError",
    "SCHEMA",
    "SCHEMA_VERSION",
    "build_collection",
    "canonical_collection_digest",
    "canonical_group_digest",
    "validate_collection",
    "verification_tree_digest",
]
