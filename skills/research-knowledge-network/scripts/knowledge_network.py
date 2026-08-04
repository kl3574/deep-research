#!/usr/bin/env python3
"""Traceable research knowledge-network ledger for local evidence networks."""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import re
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
GAP_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{1,62}")
SNAPSHOT_DIGEST_RE = re.compile(r"sha256:[0-9a-f]{64}")

READ_DEPTHS = {"full", "partial", "metadata", "abstract"}
EVIDENCE_POLARITY = {"supports", "contradicts", "qualifies", "not_tested"}
GAP_TYPES = {"explicit", "deterministic_structural", "implicit_candidate"}
IMPACTS = {"high", "medium", "low"}
GAP_STATUSES = {"open", "resolved", "blocked"}
RELATION_TYPES = {"supports", "contradicts", "grounds", "refines", "depends", "enables"}
EVENT_TYPES = {"init", "derive_gaps", "status_snapshot"}


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


def _validate_snapshot_state(
    paths: Paths, state: dict[str, Any], errors: list[str]
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
    if not snapshot_file.is_absolute():
        snapshot_file = (paths.root / snapshot_file).resolve()
    try:
        digest = _sha256_file(snapshot_file)
        if state.get("corpus_snapshot_digest") != digest:
            errors.append("corpus snapshot digest mismatch")
    except (OSError, ValueError):
        errors.append("snapshot unavailable or invalid for digest check")


def _validate_source_records(
    rows: list[dict[str, Any]], network_id: str, errors: list[str]
) -> None:
    for row in rows:
        if row.get("schema_version") != SCHEMA_VERSION:
            errors.append("source record schema_version mismatch")
        if row.get("network_id") != network_id:
            errors.append(f"source {row.get('record_id')} network mismatch")
        if row.get("source_id") in (
            None,
            "",
        ):
            errors.append("source_id missing")
        if not ID_RE.fullmatch(str(row.get("source_id", ""))):
            errors.append(f"invalid source_id: {row.get('source_id')!r}")
        if row.get("record_id") != _record_id("source", str(row.get("source_id", ""))):
            errors.append(f"source record_id mismatch: {row.get('record_id')}")
        if (
            not isinstance(row.get("canonical_version"), str)
            or not row["canonical_version"].strip()
        ):
            errors.append(f"source {row.get('source_id')} missing canonical_version")
        if row.get("read_depth") not in READ_DEPTHS:
            errors.append(f"invalid read_depth for source {row.get('source_id')}")
        hash_value = str(row.get("version_hash", ""))
        if not SNAPSHOT_DIGEST_RE.fullmatch(hash_value):
            errors.append(f"invalid version_hash for source {row.get('source_id')}")


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
    if _value_is_nonlist(row.get("coverage_dimensions")):
        errors.append(f"claim {claim_id} coverage_dimensions must be list")
    if _value_is_nonlist(row.get("benchmark_profiles")):
        errors.append(f"claim {claim_id} benchmark_profiles must be list")


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
    rows: list[dict[str, Any]], known_claims: set[str], errors: list[str]
) -> None:
    for row in rows:
        _validate_gap_record(row, known_claims, errors)


def _validate_gap_record(
    row: dict[str, Any], known_claims: set[str], errors: list[str]
) -> None:
    gap_id = row.get("gap_id")
    if not GAP_ID_RE.fullmatch(str(gap_id or "")):
        errors.append(f"invalid gap_id: {gap_id!r}")
    if not _record_id_suffix_matches("gap", row, str(gap_id or "")):
        errors.append(f"gap record_id mismatch: {row.get('record_id')}")
    if row.get("gap_type") not in GAP_TYPES:
        errors.append(f"gap {gap_id} invalid gap_type")
    if row.get("status") not in GAP_STATUSES:
        errors.append(f"gap {gap_id} invalid status")
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


def _validate_event_records(rows: list[dict[str, Any]], errors: list[str]) -> None:
    for row in rows:
        if row.get("schema_version") != SCHEMA_VERSION:
            errors.append("event record schema_version mismatch")
        event_type = row.get("event_type")
        if event_type not in EVENT_TYPES:
            errors.append(f"event {row.get('record_id')} invalid event_type")


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

    _validate_snapshot_state(paths, state, errors)

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
    _validate_gap_records(records["gaps"], known["claims"], errors)
    _validate_event_records(records["events"], errors)
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
        return f"derived:{kind}:{claim_id}:{extra}"
    return f"derived:{kind}:{claim_id}"


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
    claim_map = _collect_claim_map(records["claims"])
    by_claim = _group_evidence_by_claim(records["evidence"])
    open_conflicts = _derive_conflicts(records)
    high_impact_open = _count_high_impact_open_claims(claim_map, by_claim)
    open_gaps = _collect_open_gaps(records["gaps"])
    missing_dim_claims, missing_profile_claims = _collect_missing_coverage_claims(
        records["claims"],
        required_dimensions,
        required_profiles,
    )
    blockers = _collect_completion_blockers(
        high_impact_open,
        open_conflicts,
        missing_dim_claims,
        missing_profile_claims,
    )

    return {
        "network_id": paths.network_id,
        "schema_version": SCHEMA_VERSION,
        "counts": {name: len(records[name]) for name in LEDGER_NAMES},
        "open_conflicts": open_conflicts,
        "open_gaps": sorted(set(open_gaps)),
        "high_impact_claims_with_no_decisive_evidence": high_impact_open,
        "coverage": {
            "required_dimensions": required_dimensions,
            "required_benchmark_profiles": required_profiles,
            "missing_dimension_claim_ids": missing_dim_claims,
            "missing_profile_claim_ids": missing_profile_claims,
        },
        "completion": {
            "can_complete": not blockers,
            "blockers": blockers,
        },
        "snapshot": {
            "path": state.get("corpus_snapshot_path"),
            "digest": state.get("corpus_snapshot_digest"),
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
            if row.get("polarity") in {"supports", "contradicts", "qualifies"}
        }
        if not decisive:
            count += 1
    return count


def _collect_open_gaps(gaps: list[dict[str, Any]]) -> list[str]:
    return [
        row.get("gap_id")
        for row in gaps
        if isinstance(row.get("gap_id"), str) and row.get("status") == "open"
    ]


def _collect_missing_coverage_claims(
    claims: list[dict[str, Any]],
    required_dimensions: list[str],
    required_profiles: list[str],
) -> tuple[list[str], list[str]]:
    missing_dim_claims: list[str] = []
    missing_profile_claims: list[str] = []
    required_dimension_set = set(_sort_items(required_dimensions))
    required_profile_set = set(_sort_items(required_profiles))

    for claim in claims:
        claim_id = claim.get("claim_id")
        if not isinstance(claim_id, str):
            continue
        dimensions = sorted(_sort_items(claim.get("coverage_dimensions", [])))
        profiles = sorted(_sort_items(claim.get("benchmark_profiles", [])))
        dimension_missing = required_dimension_set - set(dimensions)
        profile_missing = required_profile_set - set(profiles)
        if dimension_missing and claim_id not in missing_dim_claims:
            missing_dim_claims.append(claim_id)
        if profile_missing and claim_id not in missing_profile_claims:
            missing_profile_claims.append(claim_id)
    return missing_dim_claims, missing_profile_claims


def _collect_completion_blockers(
    high_impact_open: int,
    open_conflicts: list[str],
    missing_dim_claims: list[str],
    missing_profile_claims: list[str],
) -> list[str]:
    blockers: list[str] = []
    if high_impact_open:
        blockers.append("open_high_impact_claim")
    if open_conflicts:
        blockers.append("open_conflict")
    if missing_dim_claims or missing_profile_claims:
        blockers.append("unmet_coverage")
    return blockers


def _derive_gaps_payload_for_claim(
    claim_id: str,
    claim: dict[str, Any],
    evidences: list[dict[str, Any]],
    required_dimensions: list[str],
    required_profiles: list[str],
) -> list[dict[str, Any]]:
    payloads: list[dict[str, Any]] = []

    coverage_dimensions = sorted(_sort_items(claim.get("coverage_dimensions", [])))
    coverage_profiles = sorted(_sort_items(claim.get("benchmark_profiles", [])))
    decisive = {
        row.get("polarity")
        for row in evidences
        if row.get("polarity") in {"supports", "contradicts", "qualifies"}
    }
    groups = {
        row.get("independence_group")
        for row in evidences
        if isinstance(row.get("independence_group"), str)
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

    for dim in required_dimensions:
        if dim not in coverage_dimensions:
            payloads.append(
                {
                    "gap_id": _make_gap_id("derived_missing_dimension", claim_id, dim),
                    "gap_type": "deterministic_structural",
                    "claim_id": claim_id,
                    "impact": "medium",
                    "status": "open",
                    "description": (
                        f"Claim {claim_id} missing promised "
                        f"dimension {dim}."
                    ),
                    "derivation_source": "derive-gaps",
                    "derivation_rule": "missing_dimension",
                    "missing_dimension": dim,
                }
            )
    for profile in required_profiles:
        if profile not in coverage_profiles:
            payloads.append(
                {
                    "gap_id": _make_gap_id(
                        "derived_missing_profile", claim_id, profile
                    ),
                    "gap_type": "deterministic_structural",
                    "claim_id": claim_id,
                    "impact": "medium",
                    "status": "open",
                    "description": (
                        f"Claim {claim_id} missing promised benchmark "
                        f"profile {profile}."
                    ),
                    "derivation_source": "derive-gaps",
                    "derivation_rule": "missing_benchmark_profile",
                    "missing_profile": profile,
                }
            )

    return payloads


def command_init(args: argparse.Namespace) -> int:
    paths = _safe_paths(args.root, args.network_id)
    if paths.network_dir.exists():
        print(f"network already exists: {args.network_id}", file=sys.stderr)
        return 1

    snapshot_path = _safe_relative_path(paths.root, args.snapshot_path, "snapshot path")
    if not snapshot_path.is_file() or snapshot_path.is_symlink():
        print("snapshot path must be a regular file", file=sys.stderr)
        return 1

    digest = _sha256_file(snapshot_path)
    if digest != args.snapshot_digest:
        print(
            "snapshot digest mismatch",
            file=sys.stderr,
        )
        return 1

    if not SNAPSHOT_DIGEST_RE.fullmatch(args.snapshot_digest):
        print("snapshot_digest must be sha256:<64 hex>", file=sys.stderr)
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
        "corpus_snapshot_digest": digest,
        "required_dimensions": sorted(_sort_items(args.required_dimension)),
        "required_benchmark_profiles": sorted(
            _sort_items(args.required_benchmark_profile)
        ),
    }
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
        payload = {
            "claim_id": claim_id,
            "claim_text": _ensure_value(args.claim_text, "claim_text"),
            "entity_id": entity_id,
            "impact": _ensure_value(args.impact, "impact"),
            "is_factual": False,
            "coverage_dimensions": sorted(_sort_items(set(args.coverage_dimension))),
            "benchmark_profiles": sorted(_sort_items(set(args.benchmark_profile))),
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
        }
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
        return (
            0
            if _append_candidate(
                paths,
                records,
                "gaps",
                _record_id("gap", gap_id),
                payload,
            )
            else 1
        )


def _required_list(state: dict[str, Any], key: str) -> list[str]:
    value = state.get(key)
    return value if isinstance(value, list) else []


def _append_derived_gaps_for_claim(
    paths: Paths,
    records: dict[str, list[dict[str, Any]]],
    claim: dict[str, Any],
    claim_evidences: list[dict[str, Any]],
    required_dimensions: list[str],
    required_profiles: list[str],
) -> int:
    generated = 0
    claim_id = claim.get("claim_id")
    if not isinstance(claim_id, str):
        return generated
    payloads = _derive_gaps_payload_for_claim(
        claim_id,
        claim,
        claim_evidences,
        required_dimensions,
        required_profiles,
    )
    for payload in payloads:
        gap_id = payload["gap_id"]
        if _append_candidate(
            paths,
            records,
            "gaps",
            _record_id("gap", gap_id),
            payload,
        ):
            generated += 1
    return generated


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


def _append_isolated_claim_gaps(
    paths: Paths, records: dict[str, list[dict[str, Any]]], claim_ids: list[str]
) -> int:
    generated = 0
    for claim_id in claim_ids:
        payload = _build_implicit_isolated_gap_payload(claim_id)
        if _append_candidate(
            paths,
            records,
            "gaps",
            _record_id("gap", payload["gap_id"]),
            payload,
        ):
            generated += 1
    return generated


def command_derive_gaps(args: argparse.Namespace) -> int:
    with _exclusive_lock(_safe_paths(args.root, args.network_id)):
        paths = _safe_paths(args.root, args.network_id)
        state, records = _load_state(paths)
        claim_evidence = _group_evidence_by_claim(records["evidence"])
        required_dimensions = _required_list(state, "required_dimensions")
        required_profiles = _required_list(state, "required_benchmark_profiles")
        generated = 0
        for claim in records["claims"]:
            generated += _append_derived_gaps_for_claim(
                paths,
                records,
                claim,
                claim_evidence.get(claim.get("claim_id", ""), []),
                required_dimensions,
                required_profiles,
            )

        topology = _derive_topology(records)
        generated += _append_isolated_claim_gaps(
            paths, records, topology["isolated_claims"]
        )

        event_payload = {
            "event_type": "derive_gaps",
            "source": "derive-gaps",
            "status": "ok",
            "derived_count": generated,
        }
        _append_candidate(
            paths,
            records,
            "events",
            _record_id("event", "derive-gaps"),
            event_payload,
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


def command_export(args: argparse.Namespace) -> int:
    paths = _safe_paths(args.root, args.network_id)
    state, records = _load_state(paths)
    errors = _validate_record_shapes(paths, state, records)
    if errors:
        print("validation errors:\n" + "\n".join(errors), file=sys.stderr)
        return 1
    payload = {
        "network_id": paths.network_id,
        "sources": sorted(records["sources"], key=lambda row: row.get("record_id")),
        "entities": sorted(records["entities"], key=lambda row: row.get("record_id")),
        "claims": sorted(records["claims"], key=lambda row: row.get("record_id")),
        "evidence": sorted(records["evidence"], key=lambda row: row.get("record_id")),
        "relations": sorted(records["relations"], key=lambda row: row.get("record_id")),
        "gaps": sorted(records["gaps"], key=lambda row: row.get("record_id")),
        "events": sorted(records["events"], key=lambda row: row.get("record_id")),
        "snapshot_digest": state.get("corpus_snapshot_digest"),
    }
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
    record_gap.set_defaults(func=command_record_gap)

    derive = commands.add_parser("derive-gaps")
    derive.set_defaults(func=command_derive_gaps)

    status = commands.add_parser("status")
    status.set_defaults(func=command_status)

    validate = commands.add_parser("validate")
    validate.set_defaults(func=command_validate)

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
