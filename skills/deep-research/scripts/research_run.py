#!/usr/bin/env python3
"""Deterministic, append-oriented ledger for an authorized research workspace.

The CLI records and validates research state. It does not access the network,
invoke a model, execute retrieved content, or decide that evidence is true.
"""

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
from typing import Any

from validate_research_handoff import validate_knowledge_network

SCHEMA_VERSION = "1"
RUN_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{2,62}")
ENTITY_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{1,62}")
TIMESTAMP_RE = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z")
PROTOCOL_REF_RE = re.compile(r"sha256:[0-9a-f]{64}")
SHA256_RE = re.compile(r"[0-9a-f]{64}")

LEDGER_NAMES = (
    "events",
    "gaps",
    "actions",
    "rounds",
    "sources",
    "claims",
    "conflicts",
    "errors",
)
MODES = {"targeted", "scoping", "rapid", "systematic"}
ACCESS_LEVELS = {"full_text", "partial_text", "abstract_only", "metadata_only"}
INSPECTION_STATES = {"inspected", "discovery_only"}
STATUS_CHECKS = {"passed", "not_applicable", "unverified"}
RELATIONS = {"supports", "contradicts", "qualifies", "not_tested"}
DECISIVE_RELATIONS = {"supports", "contradicts", "qualifies"}
DECISION_IMPACTS = {"high", "medium", "low"}
ROUND_STATUSES = {"completed", "partial", "failed", "interrupted"}
GAP_STATUSES = {"open", "resolved", "unresolved", "blocked", "deferred"}
TERMINAL_GAP_STATUSES = {"resolved", "unresolved"}
NETWORK_SUGGESTION_DEFAULTS = {
    "action_type": "discover",
    "priority": 3,
    "expected_information_gain": "missing evidence pattern for the gap",
}
NETWORK_GAP_TYPES = {"explicit", "deterministic_structural", "implicit_candidate"}
NETWORK_PRIORITIES = {"decision_critical", "high", "medium", "low"}
ACTION_URGENCY = {
    "reopen_gap": 0,
    "countercheck": 1,
    "corroborate": 2,
    "search_test": 3,
    "discover": 4,
    "inspect": 5,
}
ACTION_TYPES = {
    "discover",
    "inspect",
    "extract",
    "countercheck",
    "corroborate",
    "search_test",
    "merge",
    "citation_audit",
    "other",
}
ACTION_ARTIFACT_PREFIXES = {
    "discover": ("round:",),
    "inspect": ("source:", "round:"),
    "extract": ("claim:", "source:"),
    "countercheck": ("round:", "claim:", "conflict:"),
    "corroborate": ("round:", "source:", "claim:"),
    "search_test": ("round:", "source:"),
    "merge": ("claim:", "conflict:"),
    "citation_audit": ("claim:", "source:", "conflict:"),
    "other": ("round:", "source:", "claim:", "conflict:", "error:"),
}
ACTION_STATUSES = {"completed", "failed", "interrupted"}
COVERAGE_STATUSES = {"open", "met", "partial", "unmet"}
COVERAGE_BASES = {"coverage_audit", "protocol_complete", "partial_limit"}
OUTCOMES = {"complete", "partial"}
COMPLETE_STOP_REASONS = {"pragmatic_saturation", "protocol_complete"}
PARTIAL_STOP_REASONS = {
    "access_blocked",
    "budget_exhausted",
    "evidence_unresolved",
    "error",
    "scope_limited",
    "user_stopped",
}
FAILURE_CLASSES = {
    "access_denied",
    "not_found",
    "version_mismatch",
    "parse_failed",
    "runtime_failed",
    "worker_failed",
    "budget_exhausted",
    "prompt_injection",
    "other",
}
EVIDENCE_CLASSES = {
    "definition",
    "theorem_or_derivation",
    "synthetic_benchmark",
    "real_experiment",
    "observational_study",
    "review_synthesis",
    "normative_document",
    "implementation",
    "runtime_observation",
}
SOURCE_ROLES = {
    "orientation",
    "support",
    "contradict",
    "qualify",
    "implementation",
    "runtime",
}
GENERIC_LOCATORS = {
    "url",
    "homepage",
    "full text",
    "entire document",
    "whole document",
    "the entire document",
    "the entire paper",
    "document",
}


def _utcnow() -> str:
    return (
        datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    )


def _validate_run_id(value: str) -> str:
    if not RUN_ID_RE.fullmatch(value):
        raise ValueError(
            f"run_id must match [A-Za-z0-9][A-Za-z0-9._-]{{2,62}}: {value!r}"
        )
    return value


def _validate_entity_id(value: str, field: str) -> str:
    if not ENTITY_ID_RE.fullmatch(value):
        raise ValueError(
            f"{field} must match [A-Za-z0-9][A-Za-z0-9._:-]{{1,62}}: {value!r}"
        )
    return value


def _required_text(value: str | None, field: str) -> str:
    if value is None or not value.strip():
        raise ValueError(f"{field} must be non-empty")
    return value.strip()


def _clean_list(values: list[str] | None) -> list[str]:
    return [item.strip() for item in (values or []) if item.strip()]


def _optional_entity_id(value: str | None, field: str) -> str | None:
    if value is None:
        return None
    return _validate_entity_id(value, field)


def _positive_int(value: str) -> int:
    number = int(value)
    if number <= 0:
        raise argparse.ArgumentTypeError("must be a positive integer")
    return number


def _sha256_hex(value: str) -> str:
    if not SHA256_RE.fullmatch(value):
        raise argparse.ArgumentTypeError("must be 64 lowercase hexadecimal characters")
    return value


@dataclass(frozen=True)
class Paths:
    root: Path
    run_id: str

    @property
    def base(self) -> Path:
        return self.root / "runs" / self.run_id

    @property
    def state(self) -> Path:
        return self.base / "run.json"

    def ledger(self, name: str) -> Path:
        return self.base / f"{name}.jsonl"

    @property
    def lock_file(self) -> Path:
        return self.root / "runs" / ".locks" / f"{self.run_id}.lock"


def _paths(args: argparse.Namespace) -> Paths:
    root = Path(args.root).expanduser().resolve()
    paths = Paths(root, _validate_run_id(args.run_id))
    for label, candidate in (
        ("run directory", paths.base.resolve(strict=False)),
        ("lock file", paths.lock_file.resolve(strict=False)),
    ):
        if root != candidate and root not in candidate.parents:
            raise ValueError(f"{label} escapes the authorized root")
    return paths


@contextmanager
def _run_lock(paths: Paths, *, exclusive: bool):
    if not exclusive and not paths.lock_file.parent.exists():
        yield
        return
    paths.lock_file.parent.mkdir(parents=True, exist_ok=True)
    with paths.lock_file.open("a+", encoding="utf-8") as handle:
        operation = fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH
        fcntl.flock(handle.fileno(), operation)
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _write_atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            delete=False,
            dir=path.parent,
            prefix=f".{path.name}.",
        ) as handle:
            temp_path = Path(handle.name)
            json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        temp_path.replace(path)
    finally:
        if temp_path is not None and temp_path.exists():
            temp_path.unlink()


def _append_jsonl(path: Path, payload: dict[str, Any]) -> None:
    line = json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n"
    with path.open("a", encoding="utf-8") as handle:
        handle.write(line)
        handle.flush()
        os.fsync(handle.fileno())


def _read_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise ValueError(f"{path.name} must contain one JSON object")
    return value


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            try:
                value = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(
                    f"{path.name}: invalid JSONL at line {line_number}"
                ) from exc
            if not isinstance(value, dict):
                raise ValueError(
                    f"{path.name}: line {line_number} is not a JSON object"
                )
            records.append(value)
    return records


def _read_bundle(
    paths: Paths,
) -> tuple[dict[str, Any], dict[str, list[dict[str, Any]]]]:
    storage_paths = (("run state", paths.state),) + tuple(
        (f"{name} ledger", paths.ledger(name)) for name in LEDGER_NAMES
    )
    for label, path in storage_paths:
        if path.is_symlink():
            raise ValueError(f"{label} must not be a symbolic link: {path}")
        resolved = path.resolve(strict=False)
        if paths.root != resolved and paths.root not in resolved.parents:
            raise ValueError(f"{label} escapes the authorized root")
    if not paths.state.is_file():
        raise FileNotFoundError(f"run state missing: {paths.state}")
    state = _read_json(paths.state)
    records: dict[str, list[dict[str, Any]]] = {}
    for name in LEDGER_NAMES:
        ledger = paths.ledger(name)
        if not ledger.is_file():
            raise FileNotFoundError(f"run ledger missing: {ledger}")
        records[name] = _read_jsonl(ledger)
    return state, records


def _ordered_records(
    records: dict[str, list[dict[str, Any]]],
) -> list[tuple[str, dict[str, Any]]]:
    merged = [(name, record) for name in LEDGER_NAMES for record in records[name]]
    return sorted(
        merged,
        key=lambda item: (
            item[1].get("sequence")
            if isinstance(item[1].get("sequence"), int)
            and not isinstance(item[1].get("sequence"), bool)
            else -1
        ),
    )


def _next_sequence(records: dict[str, list[dict[str, Any]]]) -> int:
    sequences = [
        record.get("sequence", 0)
        for _, record in _ordered_records(records)
        if isinstance(record.get("sequence"), int)
        and not isinstance(record.get("sequence"), bool)
    ]
    return max(sequences, default=0) + 1


def _record(
    paths: Paths,
    records: dict[str, list[dict[str, Any]]],
    record_id: str,
    **payload: Any,
) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "run_id": paths.run_id,
        "record_id": record_id,
        "sequence": _next_sequence(records),
        "recorded_at": _utcnow(),
        **payload,
    }


def _ids(records: dict[str, list[dict[str, Any]]], key: str, ledger: str) -> set[Any]:
    return {record.get(key) for record in records[ledger]}


def _latest_coverage(records: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    coverage_events = [
        event for event in records["events"] if event.get("event") == "coverage_set"
    ]
    if not coverage_events:
        return {
            "status": "open",
            "basis": None,
            "unresolved_gaps": [],
            "rationale": None,
        }
    event = max(
        coverage_events,
        key=lambda item: (
            item.get("sequence") if isinstance(item.get("sequence"), int) else -1
        ),
    )
    return {
        "status": event.get("coverage_status"),
        "basis": event.get("basis"),
        "unresolved_gaps": event.get("unresolved_gaps", []),
        "rationale": event.get("rationale"),
    }


def _coverage_is_fresh(records: dict[str, list[dict[str, Any]]]) -> bool:
    coverage_events = [
        event for event in records["events"] if event.get("event") == "coverage_set"
    ]
    if not coverage_events:
        return False
    coverage_sequences = [
        event.get("sequence")
        for event in coverage_events
        if isinstance(event.get("sequence"), int)
        and not isinstance(event.get("sequence"), bool)
    ]
    if not coverage_sequences:
        return False
    coverage_sequence = max(coverage_sequences)
    for ledger, record in _ordered_records(records):
        sequence = record.get("sequence")
        if not isinstance(sequence, int) or sequence <= coverage_sequence:
            continue
        if ledger == "events" and record.get("event") == "finalized":
            continue
        return False
    return True


def _derive_lifecycle(records: dict[str, list[dict[str, Any]]]) -> str:
    lifecycle = "uninitialized"
    for ledger, record in _ordered_records(records):
        if ledger == "events" and record.get("event") == "initialized":
            lifecycle = "running"
        elif ledger == "errors" and record.get("fatal"):
            lifecycle = "interrupted"
        elif ledger == "events" and record.get("event") == "resumed":
            lifecycle = "running"
        elif ledger == "events" and record.get("event") == "finalized":
            lifecycle = "finalized"
    return lifecycle


def _derive_outcome(records: dict[str, list[dict[str, Any]]]) -> dict[str, Any] | None:
    finals = [event for event in records["events"] if event.get("event") == "finalized"]
    if not finals:
        return None
    event = max(
        finals,
        key=lambda item: (
            item.get("sequence") if isinstance(item.get("sequence"), int) else -1
        ),
    )
    return {
        "outcome": event.get("outcome"),
        "stop_reason": event.get("stop_reason"),
        "summary": event.get("summary"),
        "finalized_at": event.get("recorded_at"),
    }


def _saturation_rounds(rounds: list[dict[str, Any]]) -> list[str]:
    if len(rounds) < 2:
        return []
    last_two = rounds[-2:]
    if any(record.get("status") != "completed" for record in last_two):
        return []
    if any(record.get("new_information") is not False for record in last_two):
        return []
    fingerprints = {
        (
            record.get("gap_id"),
            " ".join(str(record.get("route_and_query_set", "")).split()).casefold(),
        )
        for record in last_two
    }
    if len(fingerprints) != 2:
        return []
    return [str(record.get("round_id")) for record in last_two]


def _conflict_state(
    records: dict[str, list[dict[str, Any]]],
) -> tuple[list[str], list[str]]:
    relations: dict[str, set[str]] = {}
    for row in records["claims"]:
        claim_id = row.get("claim_id")
        relation = row.get("relation")
        if isinstance(claim_id, str) and isinstance(relation, str):
            relations.setdefault(claim_id, set()).add(relation)

    resolved_conflict_ids = {
        event.get("conflict_id")
        for event in records["events"]
        if event.get("event") == "conflict_resolved"
        and isinstance(event.get("conflict_id"), str)
    }
    logged_claims: set[str] = set()
    open_claims: set[str] = set()
    for conflict in records["conflicts"]:
        affected = conflict.get("affected_claim_ids", [])
        if not isinstance(affected, list):
            affected = []
        logged_claims.update(item for item in affected if isinstance(item, str))
        if (
            not conflict.get("resolved")
            and conflict.get("conflict_id") not in resolved_conflict_ids
        ):
            open_claims.update(item for item in affected if isinstance(item, str))

    needs_log = {
        claim_id
        for claim_id, relation_set in relations.items()
        if "supports" in relation_set and "contradicts" in relation_set
    }
    return sorted(needs_log - logged_claims), sorted(open_claims)


def _claim_state(
    records: dict[str, list[dict[str, Any]]], open_conflict_claims: list[str]
) -> tuple[list[str], list[str], list[str]]:
    decisive: set[str] = set()
    not_tested: set[str] = set()
    all_claims: set[str] = set()
    for row in records["claims"]:
        claim_id = row.get("claim_id")
        if not isinstance(claim_id, str):
            continue
        all_claims.add(claim_id)
        if row.get("relation") in DECISIVE_RELATIONS:
            decisive.add(claim_id)
        elif row.get("relation") == "not_tested":
            not_tested.add(claim_id)
    open_set = set(open_conflict_claims)
    resolved = decisive - open_set
    unresolved = all_claims - resolved
    return sorted(resolved), sorted(unresolved), sorted(not_tested)


def _gap_state(records: dict[str, list[dict[str, Any]]]) -> dict[str, dict[str, Any]]:
    states: dict[str, dict[str, Any]] = {}
    for row in sorted(records["gaps"], key=lambda item: item.get("sequence", -1)):
        gap_id = row.get("gap_id")
        if not isinstance(gap_id, str):
            continue
        if row.get("operation") == "opened":
            states[gap_id] = {
                "gap_id": gap_id,
                "description": row.get("description"),
                "acceptance_criteria": row.get("acceptance_criteria"),
                "coverage_role": row.get("coverage_role"),
                "decision_impact": row.get("decision_impact"),
                "counterevidence_required": row.get("counterevidence_required"),
                "dependencies": row.get("dependencies", []),
                "priority": row.get("priority"),
                "status": "open",
                "open_instance_id": row.get("record_id"),
                "rationale": None,
                "artifact_refs": [],
                "next_action": None,
            }
        elif row.get("operation") == "status_set" and gap_id in states:
            states[gap_id].update(
                {
                    "status": row.get("status"),
                    "rationale": row.get("rationale"),
                    "artifact_refs": row.get("artifact_refs", []),
                    "next_action": row.get("next_action"),
                }
            )
            if row.get("status") == "open":
                states[gap_id]["open_instance_id"] = row.get("record_id")
    return states


def _action_state(
    records: dict[str, list[dict[str, Any]]],
) -> dict[str, dict[str, Any]]:
    states: dict[str, dict[str, Any]] = {}
    for row in sorted(records["actions"], key=lambda item: item.get("sequence", -1)):
        action_id = row.get("action_id")
        if not isinstance(action_id, str):
            continue
        if row.get("operation") == "started":
            states[action_id] = {
                "action_id": action_id,
                "gap_id": row.get("gap_id"),
                "action_type": row.get("action_type"),
                "inputs": row.get("inputs"),
                "expected_information_gain": row.get("expected_information_gain"),
                "budget": row.get("budget"),
                "branch_id": row.get("branch_id"),
                "attempt_id": row.get("attempt_id"),
                "status": "started",
                "result": None,
                "artifact_refs": [],
                "next_action": None,
                "remaining_uncertainty": None,
            }
        elif row.get("operation") == "finished" and action_id in states:
            states[action_id].update(
                {
                    "status": row.get("status"),
                    "result": row.get("result"),
                    "artifact_refs": row.get("artifact_refs", []),
                    "next_action": row.get("next_action"),
                    "remaining_uncertainty": row.get("remaining_uncertainty"),
                }
            )
    return states


def _coverage_blockers(
    state: dict[str, Any], records: dict[str, list[dict[str, Any]]]
) -> list[str]:
    contract = state.get("contract", {})
    promised = contract.get("coverage_gap_ids", [])
    gaps = _gap_state(records)
    actions = _action_state(records)
    blockers: list[str] = []
    for gap_id in promised if isinstance(promised, list) else []:
        if gap_id not in gaps:
            blockers.append(f"promised gap {gap_id!r} is not registered")
    for gap_id, gap in gaps.items():
        if gap.get("status") not in TERMINAL_GAP_STATUSES:
            blockers.append(f"gap {gap_id!r} is not terminal: {gap.get('status')!r}")
        gap_actions = [
            action for action in actions.values() if action.get("gap_id") == gap_id
        ]
        if not gap_actions:
            blockers.append(f"gap {gap_id!r} has no recorded action")
        if any(action.get("status") == "started" for action in gap_actions):
            blockers.append(f"gap {gap_id!r} has an active action")
        if gap.get("status") == "resolved" and not any(
            action.get("status") == "completed" for action in gap_actions
        ):
            blockers.append(f"resolved gap {gap_id!r} has no completed action")
        completed_finish_refs = {
            f"action:{action['action_id']}:finish"
            for action in gap_actions
            if action.get("status") == "completed"
        }
        terminal_finish_refs = {
            f"action:{action['action_id']}:finish"
            for action in gap_actions
            if action.get("status") in ACTION_STATUSES
        }
        gap_artifact_refs = set(gap.get("artifact_refs", []))
        if gap.get("status") == "resolved" and not (
            gap_artifact_refs & completed_finish_refs
        ):
            blockers.append(
                f"resolved gap {gap_id!r} does not reference its completed action"
            )
        if gap.get("status") == "unresolved" and not (
            gap_artifact_refs & terminal_finish_refs
        ):
            blockers.append(
                f"unresolved gap {gap_id!r} does not reference its attempted action"
            )
        if gap.get("counterevidence_required") and not any(
            action.get("action_type") == "countercheck"
            and action.get("status") == "completed"
            for action in gap_actions
        ):
            blockers.append(f"gap {gap_id!r} lacks a completed countercheck action")
    return sorted(set(blockers))


def _error_state(
    records: dict[str, list[dict[str, Any]]],
) -> tuple[list[str], list[str]]:
    resolved = {
        event.get("error_id")
        for event in records["events"]
        if event.get("event") == "error_resolved"
        and isinstance(event.get("error_id"), str)
    }
    blocking = {
        row.get("error_id")
        for row in records["errors"]
        if row.get("affects_coverage") is True
        and isinstance(row.get("error_id"), str)
        and row.get("error_id") not in resolved
    }
    return sorted(resolved), sorted(blocking)


def _summary(
    state: dict[str, Any],
    records: dict[str, list[dict[str, Any]]],
    validation_errors: list[str],
) -> dict[str, Any]:
    contract = state.get("contract", {})
    coverage = _latest_coverage(records)
    coverage_fresh = _coverage_is_fresh(records)
    lifecycle = _derive_lifecycle(records)
    unlogged_conflicts, open_conflicts = _conflict_state(records)
    resolved, unresolved, not_tested = _claim_state(records, open_conflicts)
    resolved_errors, blocking_errors = _error_state(records)
    gaps = _gap_state(records)
    actions = _action_state(records)
    coverage_blockers = _coverage_blockers(state, records)
    active_action_gap_ids = {
        action.get("gap_id")
        for action in actions.values()
        if action.get("status") == "started"
    }
    active_actions = [
        action
        for _, action in sorted(actions.items())
        if action.get("status") == "started"
    ]
    ready_gap_ids = sorted(
        gap_id
        for gap_id, gap in gaps.items()
        if gap.get("status") == "open"
        and gap_id not in active_action_gap_ids
        and all(
            gaps.get(dependency, {}).get("status") in TERMINAL_GAP_STATUSES
            for dependency in gap.get("dependencies", [])
        )
    )
    saturation_round_ids = _saturation_rounds(records["rounds"])
    has_decisive_relations = any(
        row.get("relation") in DECISIVE_RELATIONS for row in records["claims"]
    )
    mode = contract.get("mode")
    pragmatic_saturation = (
        not validation_errors
        and mode != "systematic"
        and coverage.get("status") == "met"
        and coverage.get("basis") == "coverage_audit"
        and coverage_fresh
        and has_decisive_relations
        and not unlogged_conflicts
        and not blocking_errors
        and not coverage_blockers
        and bool(saturation_round_ids)
    )
    systematic_complete = (
        not validation_errors
        and mode == "systematic"
        and coverage.get("status") == "met"
        and coverage.get("basis") == "protocol_complete"
        and coverage_fresh
        and has_decisive_relations
        and not unlogged_conflicts
        and not blocking_errors
        and not coverage_blockers
    )
    max_rounds = contract.get("max_rounds")
    max_relations = contract.get("max_relations")
    return {
        "lifecycle": lifecycle,
        "coverage": coverage,
        "coverage_fresh": coverage_fresh,
        "counts": {
            "events": len(records["events"]),
            "gaps": len(gaps),
            "gap_events": len(records["gaps"]),
            "actions": len(actions),
            "action_events": len(records["actions"]),
            "rounds": len(records["rounds"]),
            "sources": len(records["sources"]),
            "claim_relations": len(records["claims"]),
            "semantic_claims": len({row.get("claim_id") for row in records["claims"]}),
            "conflicts": len(records["conflicts"]),
            "errors": len(records["errors"]),
        },
        "claim_resolution": {
            "resolved_claim_ids": resolved,
            "unresolved_claim_ids": unresolved,
            "not_tested_claim_ids": not_tested,
            "open_conflict_claim_ids": open_conflicts,
            "unlogged_conflict_claim_ids": unlogged_conflicts,
        },
        "error_resolution": {
            "resolved_error_ids": resolved_errors,
            "blocking_error_ids": blocking_errors,
        },
        "coverage_blockers": coverage_blockers,
        "gap_status": {
            gap_id: gap.get("status") for gap_id, gap in sorted(gaps.items())
        },
        "active_actions": active_actions,
        "ready_gap_ids": ready_gap_ids,
        "saturation_round_ids": saturation_round_ids,
        "can_claim_pragmatic_saturation": pragmatic_saturation,
        "can_finalize_complete": (
            lifecycle == "running" and (pragmatic_saturation or systematic_complete)
        ),
        "can_finalize_partial": (
            not validation_errors
            and lifecycle in {"running", "interrupted"}
            and coverage.get("status") in {"met", "partial", "unmet"}
            and coverage_fresh
            and not active_actions
        ),
        "round_limit_reached": (
            isinstance(max_rounds, int) and len(records["rounds"]) >= max_rounds
        ),
        "relation_limit_reached": (
            isinstance(max_relations, int) and len(records["claims"]) >= max_relations
        ),
        "outcome": _derive_outcome(records),
    }


def _read_regular_file_bytes(
    path: Path,
) -> tuple[bytes, tuple[int, int, int, int, int]]:
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags)
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode):
            raise ValueError(f"knowledge network must be a regular file: {path}")
        chunks: list[bytes] = []
        while True:
            chunk = os.read(descriptor, 1024 * 1024)
            if not chunk:
                break
            chunks.append(chunk)
    finally:
        os.close(descriptor)
    identity = (
        metadata.st_dev,
        metadata.st_ino,
        metadata.st_size,
        metadata.st_mtime_ns,
        metadata.st_ctime_ns,
    )
    return b"".join(chunks), identity


def _network_policy_errors(payload: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    for index, gap in enumerate(payload.get("gaps", [])):
        if not isinstance(gap, dict):
            continue
        label = f"knowledge_network.gaps[{index}]"
        priority = gap.get("priority")
        valid_priority = (
            isinstance(priority, str) and priority in NETWORK_PRIORITIES
        ) or (
            isinstance(priority, int)
            and not isinstance(priority, bool)
            and priority > 0
        )
        if not valid_priority:
            errors.append(
                f"{label}.priority must be decision_critical, high, medium, low, "
                "or a positive integer"
            )
        gap_type = gap.get("gap_type")
        if gap_type is not None and gap_type not in NETWORK_GAP_TYPES:
            errors.append(f"{label}.gap_type is invalid")
        impact = gap.get("impact")
        if impact is not None and impact not in DECISION_IMPACTS:
            errors.append(f"{label}.impact is invalid")
        if gap.get("novelty_claimed") not in {None, False}:
            errors.append(f"{label}.novelty_claimed must be false when present")
        if gap_type == "implicit_candidate":
            for field in ("grounds", "warrant", "backing", "qualifier"):
                if not isinstance(gap.get(field), str) or not gap[field].strip():
                    errors.append(
                        f"{label}.{field} is required for an implicit candidate"
                    )
            defeaters = gap.get("defeaters")
            if not isinstance(defeaters, list) or not all(
                isinstance(item, str) and item.strip() for item in defeaters
            ):
                errors.append(
                    f"{label}.defeaters must be a list of non-empty strings"
                )
            if (
                not isinstance(gap.get("search_test"), str)
                or not gap["search_test"].strip()
            ):
                errors.append(
                    f"{label}.search_test is required for an implicit candidate"
                )
    return errors


def _load_knowledge_network(
    path: Path, expected_sha256: str
) -> tuple[dict[str, Any], dict[str, str]]:
    if not path.is_absolute():
        raise ValueError("network path must be absolute")
    if path.is_symlink():
        raise ValueError(f"knowledge network must not be a symlink: {path}")
    if not path.exists():
        raise ValueError(f"network payload not found: {path}")

    first_bytes, first_identity = _read_regular_file_bytes(path)
    actual_sha256 = hashlib.sha256(first_bytes).hexdigest()
    if actual_sha256 != expected_sha256:
        raise ValueError(
            "knowledge network SHA-256 mismatch: "
            f"expected {expected_sha256}, got {actual_sha256}"
        )
    try:
        payload = json.loads(first_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid knowledge network JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise ValueError("knowledge network root must be an object")

    validation_errors = validate_knowledge_network(payload)
    validation_errors.extend(_network_policy_errors(payload))
    if validation_errors:
        raise ValueError(
            "invalid KnowledgeNetwork/v1: " + "; ".join(validation_errors)
        )

    second_bytes, second_identity = _read_regular_file_bytes(path)
    if (
        second_identity != first_identity
        or hashlib.sha256(second_bytes).hexdigest() != actual_sha256
    ):
        raise ValueError("knowledge network changed while being read")
    return payload, {
        "schema": payload["schema"],
        "network_id": payload["network_id"],
        "snapshot_id": payload["snapshot_id"],
        "sha256": actual_sha256,
    }


def _network_gap_has_single_source(
    payload: dict[str, Any], gap: dict[str, Any]
) -> bool:
    objects: dict[str, dict[str, Any]] = {}
    for node in payload.get("nodes", []):
        if isinstance(node, dict) and isinstance(node.get("node_id"), str):
            objects[node["node_id"]] = node
    for relation in payload.get("relations", []):
        if isinstance(relation, dict) and isinstance(relation.get("relation_id"), str):
            objects[relation["relation_id"]] = relation
    source_ids: set[str] = set()
    for object_id in gap.get("derived_from", []):
        obj = objects.get(object_id, {})
        for provenance in obj.get("provenance", []):
            source_id = provenance.get("source_id")
            if isinstance(source_id, str):
                source_ids.add(source_id)
    return len(source_ids) == 1


def _network_suggested_action_type(
    payload: dict[str, Any], gap: dict[str, Any]
) -> str:
    if gap.get("gap_type") == "implicit_candidate":
        return "search_test"
    if gap.get("reason") == "conflict":
        return "countercheck"
    if gap.get("reason") == "missing":
        return "discover"
    if _network_gap_has_single_source(payload, gap):
        return "corroborate"
    return "inspect"


def _decision_critical_rank(value: Any) -> int:
    return 0 if value == "decision_critical" else 1


def _numeric_priority_rank(value: Any) -> int:
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    return NETWORK_SUGGESTION_DEFAULTS["priority"]


def _impact_rank(value: Any) -> int:
    return {"high": 0, "medium": 1, "low": 2}.get(value, 3)


def _network_impact(gap: dict[str, Any]) -> str:
    impact = gap.get("impact")
    if isinstance(impact, str):
        return impact
    if gap.get("priority") in {"decision_critical", "high"}:
        return "high"
    if gap.get("priority") == "low":
        return "low"
    return "medium"


def _run_gap_suggested_action(gap: dict[str, Any]) -> str:
    if gap.get("counterevidence_required"):
        return "countercheck"
    return NETWORK_SUGGESTION_DEFAULTS["action_type"]


def _build_next_actions_from_run(
    gaps: dict[str, dict[str, Any]], ready_gap_ids: set[str]
) -> list[dict[str, Any]]:
    suggestions: list[dict[str, Any]] = []
    for gap_id in sorted(ready_gap_ids):
        gap = gaps[gap_id]
        if gap.get("status") != "open":
            continue
        action = _run_gap_suggested_action(gap)
        suggestions.append(
            {
                "source": "run",
                "gap_id": gap_id,
                "open_instance_id": gap.get("open_instance_id"),
                "action_type": action,
                "priority": gap.get("priority") or NETWORK_SUGGESTION_DEFAULTS["priority"],
                "impact": gap.get("decision_impact", "medium"),
                "description": gap.get("description", ""),
                "next_action": gap.get("next_action"),
                "expected_information_gain": f"Close {gap_id} to satisfy its acceptance criteria.",
            }
        )
    return suggestions


def _build_next_actions_from_network(
    payload: dict[str, Any],
    run_gaps: dict[str, dict[str, Any]],
    ready_gap_ids: set[str],
) -> list[dict[str, Any]]:
    suggestions: list[dict[str, Any]] = []
    for gap in sorted(payload["gaps"], key=lambda candidate: candidate["gap_id"]):
        if gap.get("status") != "open":
            continue
        gap_id = gap["gap_id"]
        run_gap = run_gaps.get(gap_id)
        source = "knowledge_network"
        open_instance_id = None
        if run_gap is not None:
            if run_gap.get("status") == "open":
                if gap_id not in ready_gap_ids:
                    continue
                source = "run+knowledge_network"
                open_instance_id = run_gap.get("open_instance_id")
            else:
                suggestions.append(
                    {
                        "source": "run+knowledge_network",
                        "gap_id": gap_id,
                        "action_type": "reopen_gap",
                        "priority": gap["priority"],
                        "impact": _network_impact(gap),
                        "gap_type": gap.get(
                            "gap_type", "deterministic_structural"
                        ),
                        "reason": gap["reason"],
                        "derived_from": list(gap["derived_from"]),
                        "next_action": gap["next_action"],
                        "description": gap.get(
                            "description",
                            f"Knowledge-network gap {gap_id}: {gap['reason']}.",
                        ),
                        "requires_explicit_reopen": True,
                        "reopen_reason": gap["next_action"],
                        "expected_information_gain": (
                            f"Explicitly reopen {gap_id} before scheduling work."
                        ),
                    }
                )
                continue
        action_type = _network_suggested_action_type(payload, gap)
        candidate: dict[str, Any] = {
            "source": source,
            "gap_id": gap_id,
            "open_instance_id": open_instance_id,
            "action_type": action_type,
            "priority": gap["priority"],
            "impact": _network_impact(gap),
            "gap_type": gap.get("gap_type", "deterministic_structural"),
            "reason": gap["reason"],
            "derived_from": list(gap["derived_from"]),
            "next_action": gap["next_action"],
            "description": gap.get(
                "description", f"Knowledge-network gap {gap_id}: {gap['reason']}."
            ),
            "expected_information_gain": (
                "Run the explicit falsifiable search test."
                if action_type == "search_test"
                else f"Address the network-derived {gap['reason']} gap {gap_id}."
            ),
        }
        if action_type == "search_test":
            candidate["search_test"] = gap["search_test"]
            candidate["novelty_claimed"] = False
        suggestions.append(candidate)
    return suggestions


def _finalize_suggestions(
    candidates: list[dict[str, Any]], max_suggestions: int | None
) -> list[dict[str, Any]]:
    deduplicated: dict[tuple[str, str, str], dict[str, Any]] = {}
    for candidate in candidates:
        open_instance = candidate.get("open_instance_id")
        source_identity = (
            f"run:{open_instance}"
            if isinstance(open_instance, str)
            else f"network:{candidate.get('source')}"
        )
        identity = (
            source_identity,
            str(candidate.get("gap_id")),
            str(candidate.get("action_type")),
        )
        deduplicated[identity] = candidate
    ordered = sorted(
        deduplicated.values(),
        key=lambda candidate: (
            _decision_critical_rank(candidate.get("priority")),
            _impact_rank(candidate.get("impact")),
            _numeric_priority_rank(candidate.get("priority")),
            ACTION_URGENCY.get(candidate.get("action_type"), 99),
            str(candidate.get("source")),
            str(candidate.get("gap_id")),
        ),
    )
    if max_suggestions is not None:
        ordered = ordered[:max_suggestions]
    finalized: list[dict[str, Any]] = []
    for index, candidate in enumerate(ordered, start=1):
        row = dict(candidate)
        row["suggestion_id"] = (
            f"suggest:{index}:{row['gap_id']}:{row['action_type']}"
        )
        finalized.append(row)
    return finalized


def _validate_envelopes(
    paths: Paths, records: dict[str, list[dict[str, Any]]], errors: list[str]
) -> None:
    record_ids: set[str] = set()
    sequences: list[int] = []
    for ledger, ledger_records in records.items():
        previous = 0
        for index, record in enumerate(ledger_records, start=1):
            prefix = f"{ledger}.jsonl line {index}"
            if record.get("schema_version") != SCHEMA_VERSION:
                errors.append(f"{prefix}: schema_version mismatch")
            if record.get("run_id") != paths.run_id:
                errors.append(f"{prefix}: run_id mismatch")
            record_id = record.get("record_id")
            if not isinstance(record_id, str) or not record_id:
                errors.append(f"{prefix}: invalid record_id")
            elif record_id in record_ids:
                errors.append(f"duplicate record_id: {record_id!r}")
            else:
                record_ids.add(record_id)
            sequence = record.get("sequence")
            if (
                not isinstance(sequence, int)
                or isinstance(sequence, bool)
                or sequence <= 0
            ):
                errors.append(f"{prefix}: sequence must be a positive integer")
            else:
                if sequence <= previous:
                    errors.append(f"{prefix}: sequences are not increasing")
                previous = sequence
                sequences.append(sequence)
            timestamp = record.get("recorded_at")
            if not isinstance(timestamp, str) or not TIMESTAMP_RE.fullmatch(timestamp):
                errors.append(f"{prefix}: invalid UTC recorded_at")
    if sorted(sequences) != list(range(1, len(sequences) + 1)):
        errors.append("global sequence must be unique and contiguous from 1")


def _validate_events(
    state: dict[str, Any], records: dict[str, list[dict[str, Any]]], errors: list[str]
) -> None:
    allowed = {
        "initialized",
        "coverage_set",
        "conflict_resolved",
        "error_resolved",
        "resumed",
        "finalized",
    }
    init_events = []
    final_events = []
    for event in records["events"]:
        event_type = event.get("event")
        if event_type not in allowed:
            errors.append(f"unknown event type: {event_type!r}")
            continue
        if event_type == "initialized":
            init_events.append(event)
            if event.get("record_id") != "event:init":
                errors.append("initialized event must use record_id 'event:init'")
            if event.get("sequence") != 1:
                errors.append("initialized event must be sequence 1")
            if event.get("contract") != state.get("contract"):
                errors.append("initialized contract does not match run.json")
        elif event_type == "coverage_set":
            status = event.get("coverage_status")
            basis = event.get("basis")
            gaps = event.get("unresolved_gaps")
            if status not in COVERAGE_STATUSES - {"open"}:
                errors.append(f"coverage event has invalid status: {status!r}")
            if basis not in COVERAGE_BASES:
                errors.append(f"coverage event has invalid basis: {basis!r}")
            if not isinstance(gaps, list):
                errors.append(
                    "coverage unresolved_gaps must be a list of non-empty strings"
                )
            elif any(not isinstance(item, str) or not item.strip() for item in gaps):
                errors.append(
                    "coverage unresolved_gaps must be a list of non-empty strings"
                )
            elif status == "met" and gaps:
                errors.append("coverage status met cannot retain unresolved gaps")
            elif status in {"partial", "unmet"} and not gaps:
                errors.append("partial/unmet coverage requires an unresolved gap")
            if (
                not isinstance(event.get("rationale"), str)
                or not event["rationale"].strip()
            ):
                errors.append("coverage event requires a rationale")
        elif event_type == "error_resolved":
            for field in ("error_id", "resolution", "resolution_evidence"):
                if not isinstance(event.get(field), str) or not event[field].strip():
                    errors.append(f"error_resolved event requires {field}")
        elif event_type == "conflict_resolved":
            for field in ("conflict_id", "resolution", "discriminating_evidence"):
                if not isinstance(event.get(field), str) or not event[field].strip():
                    errors.append(f"conflict_resolved event requires {field}")
        elif event_type == "finalized":
            final_events.append(event)
            if event.get("outcome") not in OUTCOMES:
                errors.append("finalized event has invalid outcome")
            for field in ("stop_reason", "summary"):
                if not isinstance(event.get(field), str) or not event[field].strip():
                    errors.append(f"finalized event requires {field}")
    if len(init_events) != 1:
        errors.append("ledger must contain exactly one initialized event")
    if len(final_events) > 1:
        errors.append("ledger cannot contain more than one finalized event")
    known_errors = {
        row.get("error_id")
        for row in records["errors"]
        if isinstance(row.get("error_id"), str)
    }
    resolved_error_ids: list[str] = []
    for event in records["events"]:
        if event.get("event") != "error_resolved":
            continue
        error_id = event.get("error_id")
        if error_id not in known_errors:
            errors.append(f"error_resolved references unknown error_id {error_id!r}")
        if isinstance(error_id, str):
            resolved_error_ids.append(error_id)
    if len(resolved_error_ids) != len(set(resolved_error_ids)):
        errors.append("an error cannot be resolved more than once")

    conflicts_by_id = {
        row.get("conflict_id"): row
        for row in records["conflicts"]
        if isinstance(row.get("conflict_id"), str)
    }
    resolved_conflict_ids: list[str] = []
    for event in records["events"]:
        if event.get("event") != "conflict_resolved":
            continue
        conflict_id = event.get("conflict_id")
        conflict = conflicts_by_id.get(conflict_id)
        if conflict is None:
            errors.append(
                f"conflict_resolved references unknown conflict_id {conflict_id!r}"
            )
        else:
            if conflict.get("resolved") is True:
                errors.append(f"conflict {conflict_id!r} was already resolved")
            conflict_sequence = conflict.get("sequence")
            event_sequence = event.get("sequence")
            if (
                isinstance(conflict_sequence, int)
                and not isinstance(conflict_sequence, bool)
                and isinstance(event_sequence, int)
                and not isinstance(event_sequence, bool)
                and conflict_sequence >= event_sequence
            ):
                errors.append(f"conflict_resolved precedes conflict {conflict_id!r}")
        if isinstance(conflict_id, str):
            resolved_conflict_ids.append(conflict_id)
    if len(resolved_conflict_ids) != len(set(resolved_conflict_ids)):
        errors.append("a conflict cannot be resolved more than once")


def _validate_gaps(
    state: dict[str, Any], records: dict[str, list[dict[str, Any]]], errors: list[str]
) -> None:
    promised = state.get("contract", {}).get("coverage_gap_ids", [])
    promised_set = set(promised) if isinstance(promised, list) else set()
    promised_counterchecks = state.get("contract", {}).get(
        "counterevidence_gap_ids", []
    )
    promised_countercheck_set = (
        set(promised_counterchecks)
        if isinstance(promised_counterchecks, list)
        else set()
    )
    all_records = {
        row.get("record_id"): row
        for _, row in _ordered_records(records)
        if isinstance(row.get("record_id"), str)
    }
    openings: dict[str, dict[str, Any]] = {}
    rows_by_gap: dict[str, list[dict[str, Any]]] = {}
    for row in records["gaps"]:
        gap_id = row.get("gap_id")
        if not isinstance(gap_id, str):
            errors.append("gap_id must be a string")
            continue
        try:
            _validate_entity_id(gap_id, "gap_id")
        except ValueError as exc:
            errors.append(str(exc))
        rows_by_gap.setdefault(gap_id, []).append(row)
        operation = row.get("operation")
        if operation == "opened":
            if gap_id in openings:
                errors.append(f"gap {gap_id!r} is opened more than once")
            openings[gap_id] = row
            if row.get("record_id") != f"gap:{gap_id}:open":
                errors.append(f"gap {gap_id!r} opening record_id mismatch")
            for field in ("description", "acceptance_criteria"):
                if not isinstance(row.get(field), str) or not row[field].strip():
                    errors.append(f"gap {gap_id!r} requires {field}")
            role = row.get("coverage_role")
            if role not in {"promised", "emergent"}:
                errors.append(f"gap {gap_id!r} has invalid coverage_role")
            elif role == "promised" and gap_id not in promised_set:
                errors.append(f"gap {gap_id!r} is promised but absent from contract")
            elif role == "emergent" and gap_id in promised_set:
                errors.append(f"contract gap {gap_id!r} cannot be marked emergent")
            if row.get("decision_impact") not in DECISION_IMPACTS:
                errors.append(f"gap {gap_id!r} has invalid decision_impact")
            if not isinstance(row.get("counterevidence_required"), bool):
                errors.append(
                    f"gap {gap_id!r} counterevidence_required must be boolean"
                )
            elif role == "promised" and row.get("counterevidence_required") != (
                gap_id in promised_countercheck_set
            ):
                errors.append(
                    f"gap {gap_id!r} counterevidence flag does not match contract"
                )
            dependencies = row.get("dependencies")
            if not isinstance(dependencies, list) or any(
                not isinstance(item, str) for item in (dependencies or [])
            ):
                errors.append(f"gap {gap_id!r} dependencies must be a string list")
            elif len(dependencies) != len(set(dependencies)):
                errors.append(f"gap {gap_id!r} repeats dependencies")
            elif gap_id in dependencies:
                errors.append(f"gap {gap_id!r} cannot depend on itself")
            priority = row.get("priority")
            if (
                not isinstance(priority, int)
                or isinstance(priority, bool)
                or priority <= 0
            ):
                errors.append(f"gap {gap_id!r} priority must be a positive integer")
        elif operation == "status_set":
            if row.get("record_id") != f"gap:{gap_id}:status:{row.get('sequence')}":
                errors.append(f"gap {gap_id!r} status record_id mismatch")
            if row.get("status") not in GAP_STATUSES:
                errors.append(f"gap {gap_id!r} has invalid status")
            if (
                not isinstance(row.get("rationale"), str)
                or not row["rationale"].strip()
            ):
                errors.append(f"gap {gap_id!r} status requires rationale")
            artifact_refs = row.get("artifact_refs")
            if not isinstance(artifact_refs, list) or any(
                not isinstance(item, str) for item in (artifact_refs or [])
            ):
                errors.append(f"gap {gap_id!r} artifact_refs must be a string list")
            else:
                if row.get("status") in TERMINAL_GAP_STATUSES and not artifact_refs:
                    errors.append(f"terminal gap {gap_id!r} requires artifact_refs")
                for record_id in artifact_refs:
                    target = all_records.get(record_id)
                    if target is None:
                        errors.append(
                            f"gap {gap_id!r} references unknown artifact {record_id!r}"
                        )
                    elif target.get("sequence", 0) >= row.get("sequence", 0):
                        errors.append(
                            f"gap {gap_id!r} artifact {record_id!r} is not earlier"
                        )
            if row.get("status") != "resolved" and (
                not isinstance(row.get("next_action"), str)
                or not row["next_action"].strip()
            ):
                errors.append(f"non-resolved gap {gap_id!r} requires next_action")
        else:
            errors.append(f"gap {gap_id!r} has invalid operation {operation!r}")

    for gap_id in promised_set:
        opening = openings.get(gap_id)
        if opening is None:
            continue
        if opening.get("coverage_role") != "promised":
            errors.append(f"contract gap {gap_id!r} must be marked promised")
    for gap_id, rows in rows_by_gap.items():
        opening = openings.get(gap_id)
        if opening is None:
            errors.append(f"gap {gap_id!r} has status rows but no opening")
            continue
        opening_sequence = opening.get("sequence", 0)
        for row in rows:
            if (
                row.get("operation") == "status_set"
                and row.get("sequence", 0) <= opening_sequence
            ):
                errors.append(f"gap {gap_id!r} status precedes its opening")

    dependency_map = {
        gap_id: opening.get("dependencies", [])
        for gap_id, opening in openings.items()
        if isinstance(opening.get("dependencies"), list)
    }
    for gap_id, dependencies in dependency_map.items():
        for dependency in dependencies:
            if dependency not in openings:
                errors.append(f"gap {gap_id!r} depends on unknown gap {dependency!r}")

    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(gap_id: str) -> None:
        if gap_id in visiting:
            errors.append(f"gap dependency cycle includes {gap_id!r}")
            return
        if gap_id in visited:
            return
        visiting.add(gap_id)
        for dependency in dependency_map.get(gap_id, []):
            if isinstance(dependency, str) and dependency in dependency_map:
                visit(dependency)
        visiting.remove(gap_id)
        visited.add(gap_id)

    for gap_id in dependency_map:
        visit(gap_id)


def _validate_actions(
    records: dict[str, list[dict[str, Any]]], errors: list[str]
) -> None:
    known_gaps = {
        row.get("gap_id")
        for row in records["gaps"]
        if row.get("operation") == "opened" and isinstance(row.get("gap_id"), str)
    }
    all_records = {
        row.get("record_id"): row
        for _, row in _ordered_records(records)
        if isinstance(row.get("record_id"), str)
    }
    rows_by_action: dict[str, list[dict[str, Any]]] = {}
    for row in records["actions"]:
        action_id = row.get("action_id")
        if not isinstance(action_id, str):
            errors.append("action_id must be a string")
            continue
        try:
            _validate_entity_id(action_id, "action_id")
        except ValueError as exc:
            errors.append(str(exc))
        rows_by_action.setdefault(action_id, []).append(row)
        operation = row.get("operation")
        if operation == "started":
            if row.get("record_id") != f"action:{action_id}:start":
                errors.append(f"action {action_id!r} start record_id mismatch")
            if row.get("gap_id") not in known_gaps:
                errors.append(f"action {action_id!r} references unknown gap")
            if row.get("action_type") not in ACTION_TYPES:
                errors.append(f"action {action_id!r} has invalid action_type")
            for field in ("inputs", "expected_information_gain", "budget"):
                if not isinstance(row.get(field), str) or not row[field].strip():
                    errors.append(f"action {action_id!r} requires {field}")
        elif operation == "finished":
            if row.get("record_id") != f"action:{action_id}:finish":
                errors.append(f"action {action_id!r} finish record_id mismatch")
            if row.get("status") not in ACTION_STATUSES:
                errors.append(f"action {action_id!r} has invalid terminal status")
            if not isinstance(row.get("result"), str) or not row["result"].strip():
                errors.append(f"action {action_id!r} requires result")
            if (
                not isinstance(row.get("remaining_uncertainty"), str)
                or not row["remaining_uncertainty"].strip()
            ):
                errors.append(f"action {action_id!r} requires remaining_uncertainty")
            artifact_refs = row.get("artifact_refs")
            if not isinstance(artifact_refs, list) or any(
                not isinstance(item, str) for item in (artifact_refs or [])
            ):
                errors.append(
                    f"action {action_id!r} artifact_refs must be a string list"
                )
            else:
                if row.get("status") == "completed" and not artifact_refs:
                    errors.append(
                        f"completed action {action_id!r} requires artifact_refs"
                    )
                for record_id in artifact_refs:
                    target = all_records.get(record_id)
                    if target is None:
                        errors.append(
                            f"action {action_id!r} references unknown artifact {record_id!r}"
                        )
                    elif target.get("sequence", 0) >= row.get("sequence", 0):
                        errors.append(
                            f"action {action_id!r} artifact {record_id!r} is not earlier"
                        )
            if row.get("status") != "completed" and (
                not isinstance(row.get("next_action"), str)
                or not row["next_action"].strip()
            ):
                errors.append(
                    f"failed/interrupted action {action_id!r} requires next_action"
                )
        else:
            errors.append(f"action {action_id!r} has invalid operation {operation!r}")

    for action_id, rows in rows_by_action.items():
        starts = [row for row in rows if row.get("operation") == "started"]
        finishes = [row for row in rows if row.get("operation") == "finished"]
        if len(starts) != 1:
            errors.append(f"action {action_id!r} must have exactly one start")
        if len(finishes) > 1:
            errors.append(f"action {action_id!r} has more than one finish")
        if (
            starts
            and finishes
            and finishes[0].get("sequence", 0) <= starts[0].get("sequence", 0)
        ):
            errors.append(f"action {action_id!r} finish precedes start")
        if starts and finishes and finishes[0].get("status") == "completed":
            start = starts[0]
            finish = finishes[0]
            action_rounds = [
                row for row in records["rounds"] if row.get("action_id") == action_id
            ]
            if any(row.get("status") != "completed" for row in action_rounds):
                errors.append(
                    f"completed action {action_id!r} contains a non-completed round"
                )
            allowed_prefixes = ACTION_ARTIFACT_PREFIXES.get(
                start.get("action_type"), ()
            )
            for record_id in finish.get("artifact_refs", []):
                if not record_id.startswith(allowed_prefixes):
                    errors.append(
                        f"action {action_id!r} artifact {record_id!r} does not fit "
                        f"action_type {start.get('action_type')!r}"
                    )
                target = all_records.get(record_id)
                if record_id.startswith("round:") and target is not None:
                    if target.get("status") != "completed":
                        errors.append(
                            f"completed action {action_id!r} references a non-completed round"
                        )
                    if target.get("action_id") != action_id:
                        errors.append(
                            f"action {action_id!r} references a round from another action"
                        )
                    if target.get("gap_id") != start.get("gap_id"):
                        errors.append(
                            f"action {action_id!r} references a round from another gap"
                        )


def _validate_coverage_against_gaps(
    state: dict[str, Any], records: dict[str, list[dict[str, Any]]], errors: list[str]
) -> None:
    mode = state.get("contract", {}).get("mode")
    for event in records["events"]:
        if event.get("event") != "coverage_set":
            continue
        status = event.get("coverage_status")
        basis = event.get("basis")
        if status == "met":
            expected_basis = (
                "protocol_complete" if mode == "systematic" else "coverage_audit"
            )
            if basis != expected_basis:
                errors.append(
                    f"coverage met in mode {mode!r} requires basis={expected_basis}"
                )
            sequence = event.get("sequence", 0)
            prefix = {
                name: [row for row in rows if row.get("sequence", 0) < sequence]
                for name, rows in records.items()
            }
            for blocker in _coverage_blockers(state, prefix):
                errors.append(f"coverage met before gate passed: {blocker}")
        elif status in {"partial", "unmet"} and basis != "partial_limit":
            errors.append(f"coverage {status} requires basis=partial_limit")


def _validate_rounds(
    records: dict[str, list[dict[str, Any]]], errors: list[str]
) -> None:
    seen: set[str] = set()
    gaps = _gap_state(records)
    actions = _action_state(records)
    action_starts = {
        row.get("action_id"): row
        for row in records["actions"]
        if row.get("operation") == "started" and isinstance(row.get("action_id"), str)
    }
    for row in records["rounds"]:
        round_id = row.get("round_id")
        if not isinstance(round_id, str):
            errors.append("round_id must be a string")
            continue
        try:
            _validate_entity_id(round_id, "round_id")
            _validate_entity_id(str(row.get("gap_id", "")), "gap_id")
        except ValueError as exc:
            errors.append(str(exc))
        if round_id in seen:
            errors.append(f"duplicate round_id: {round_id!r}")
        seen.add(round_id)
        if row.get("record_id") != f"round:{round_id}":
            errors.append(f"round {round_id!r} record_id mismatch")
        gap_id = row.get("gap_id")
        action_id = row.get("action_id")
        if gap_id not in gaps:
            errors.append(f"round {round_id!r} references unknown gap_id")
        if action_id not in actions:
            errors.append(f"round {round_id!r} references unknown action_id")
        elif actions[action_id].get("gap_id") != gap_id:
            errors.append(f"round {round_id!r} action/gap mismatch")
        start = action_starts.get(action_id)
        if start is not None and start.get("sequence", 0) >= row.get("sequence", 0):
            errors.append(f"round {round_id!r} precedes its action start")
        for field in (
            "decision_critical_gap",
            "route_and_query_set",
            "filters_version_date",
            "result",
        ):
            if not isinstance(row.get(field), str) or not row[field].strip():
                errors.append(f"round {round_id!r} requires {field}")
        if row.get("status") not in ROUND_STATUSES:
            errors.append(f"round {round_id!r} has invalid status")
        if not isinstance(row.get("new_information"), bool):
            errors.append(f"round {round_id!r} new_information must be boolean")
        for field in ("screened", "included", "exclusions", "new_information_types"):
            value = row.get(field)
            if not isinstance(value, list) or any(
                not isinstance(item, str) for item in value
            ):
                errors.append(f"round {round_id!r} {field} must be a string list")
        screened_value = row.get("screened")
        included_value = row.get("included")
        screened = set(screened_value) if isinstance(screened_value, list) else set()
        included = set(included_value) if isinstance(included_value, list) else set()
        if isinstance(screened_value, list) and len(screened) != len(screened_value):
            errors.append(f"round {round_id!r} repeats screened candidates")
        if isinstance(included_value, list) and len(included) != len(included_value):
            errors.append(f"round {round_id!r} repeats included candidates")
        if not included.issubset(screened):
            errors.append(f"round {round_id!r} included items must also be screened")
        information_types = row.get("new_information_types", [])
        if row.get("new_information") is True and not information_types:
            errors.append(f"round {round_id!r} new information requires a type")
        if row.get("new_information") is False and information_types:
            errors.append(f"round {round_id!r} zero information cannot list new types")


def _validate_sources(
    records: dict[str, list[dict[str, Any]]], errors: list[str]
) -> None:
    seen: set[str] = set()
    for row in records["sources"]:
        source_id = row.get("source_id")
        if not isinstance(source_id, str):
            errors.append("source_id must be a string")
            continue
        try:
            _validate_entity_id(source_id, "source_id")
        except ValueError as exc:
            errors.append(str(exc))
        if source_id in seen:
            errors.append(f"duplicate source_id: {source_id!r}")
        seen.add(source_id)
        if row.get("record_id") != f"source:{source_id}":
            errors.append(f"source {source_id!r} record_id mismatch")
        for field in ("canonical_identity", "canonical_version", "read_version"):
            if not isinstance(row.get(field), str) or not row[field].strip():
                errors.append(f"source {source_id!r} requires {field}")
        if row.get("access_level") not in ACCESS_LEVELS:
            errors.append(f"source {source_id!r} has invalid access_level")
        if row.get("inspection_state") not in INSPECTION_STATES:
            errors.append(f"source {source_id!r} has invalid inspection_state")
        if row.get("status_check") not in STATUS_CHECKS:
            errors.append(f"source {source_id!r} has invalid status_check")
        if row.get("evidence_class") not in EVIDENCE_CLASSES:
            errors.append(f"source {source_id!r} has invalid evidence_class")
        if row.get("role") not in SOURCE_ROLES:
            errors.append(f"source {source_id!r} has invalid role")


def _validate_claims(
    records: dict[str, list[dict[str, Any]]], errors: list[str]
) -> None:
    source_by_id = {row.get("source_id"): row for row in records["sources"]}
    seen_relations: set[str] = set()
    claim_texts: dict[str, str] = {}
    claim_ids_by_normalized_text: dict[str, str] = {}
    claim_impacts: dict[str, str] = {}
    for row in records["claims"]:
        relation_id = row.get("relation_id")
        claim_id = row.get("claim_id")
        if not isinstance(relation_id, str) or not isinstance(claim_id, str):
            errors.append("claim relation_id and claim_id must be strings")
            continue
        try:
            _validate_entity_id(relation_id, "relation_id")
            _validate_entity_id(claim_id, "claim_id")
        except ValueError as exc:
            errors.append(str(exc))
        if relation_id in seen_relations:
            errors.append(f"duplicate relation_id: {relation_id!r}")
        seen_relations.add(relation_id)
        if row.get("record_id") != f"claim:{relation_id}":
            errors.append(f"relation {relation_id!r} record_id mismatch")
        claim_text = row.get("claim_text")
        if not isinstance(claim_text, str) or not claim_text.strip():
            errors.append(f"relation {relation_id!r} requires claim_text")
        elif claim_id in claim_texts and claim_texts[claim_id] != claim_text:
            errors.append(f"claim {claim_id!r} has inconsistent claim_text")
        else:
            claim_texts[claim_id] = claim_text
            normalized_text = " ".join(claim_text.split()).casefold()
            prior_claim_id = claim_ids_by_normalized_text.get(normalized_text)
            if prior_claim_id is not None and prior_claim_id != claim_id:
                errors.append(
                    "the same normalized claim_text cannot use different claim_ids: "
                    f"{prior_claim_id!r} and {claim_id!r}"
                )
            else:
                claim_ids_by_normalized_text[normalized_text] = claim_id
        impact = row.get("decision_impact")
        if impact not in DECISION_IMPACTS:
            errors.append(f"relation {relation_id!r} has invalid decision_impact")
        elif claim_id in claim_impacts and claim_impacts[claim_id] != impact:
            errors.append(f"claim {claim_id!r} has inconsistent decision_impact")
        else:
            claim_impacts[claim_id] = impact
        relation = row.get("relation")
        if relation not in RELATIONS:
            errors.append(f"relation {relation_id!r} has invalid relation")
        if row.get("evidence_class") not in EVIDENCE_CLASSES:
            errors.append(f"relation {relation_id!r} has invalid evidence_class")
        if row.get("version_fit") not in {"yes", "no", "unknown"}:
            errors.append(f"relation {relation_id!r} has invalid version_fit")
        for field in ("faithful_evidence", "scope_and_applicability"):
            if not isinstance(row.get(field), str) or not row[field].strip():
                errors.append(f"relation {relation_id!r} requires {field}")
        source_id = row.get("source_id")
        source = source_by_id.get(source_id)
        if source is None:
            errors.append(
                f"relation {relation_id!r} references unknown source_id {source_id!r}"
            )
            continue
        if relation in DECISIVE_RELATIONS:
            locator = row.get("exact_locator")
            if (
                not isinstance(locator, str)
                or not locator.strip()
                or locator.strip().casefold() in GENERIC_LOCATORS
                or locator.strip().casefold().startswith(("http://", "https://"))
            ):
                errors.append(f"relation {relation_id!r} requires a precise locator")
            if row.get("version_fit") != "yes":
                errors.append(f"relation {relation_id!r} requires version_fit=yes")
            if source.get("access_level") in {"abstract_only", "metadata_only"}:
                errors.append(
                    f"relation {relation_id!r} has insufficient source access"
                )
            if source.get("inspection_state") != "inspected":
                errors.append(f"relation {relation_id!r} source was not inspected")
            if source.get("status_check") == "unverified":
                errors.append(f"relation {relation_id!r} source status is unverified")


def _validate_conflicts(
    records: dict[str, list[dict[str, Any]]], errors: list[str]
) -> None:
    known_claims = {row.get("claim_id") for row in records["claims"]}
    seen: set[str] = set()
    for row in records["conflicts"]:
        conflict_id = row.get("conflict_id")
        if not isinstance(conflict_id, str):
            errors.append("conflict_id must be a string")
            continue
        try:
            _validate_entity_id(conflict_id, "conflict_id")
        except ValueError as exc:
            errors.append(str(exc))
        if conflict_id in seen:
            errors.append(f"duplicate conflict_id: {conflict_id!r}")
        seen.add(conflict_id)
        if row.get("record_id") != f"conflict:{conflict_id}":
            errors.append(f"conflict {conflict_id!r} record_id mismatch")
        affected = row.get("affected_claim_ids")
        if not isinstance(affected, list) or not affected:
            errors.append(f"conflict {conflict_id!r} requires affected_claim_ids")
            continue
        if len(affected) != len(set(affected)):
            errors.append(f"conflict {conflict_id!r} repeats affected_claim_ids")
        unknown = [claim_id for claim_id in affected if claim_id not in known_claims]
        if unknown:
            errors.append(
                f"conflict {conflict_id!r} references unknown claims: {unknown}"
            )
        if (
            not isinstance(row.get("conflict_type"), str)
            or not row["conflict_type"].strip()
        ):
            errors.append(f"conflict {conflict_id!r} requires conflict_type")
        if not isinstance(row.get("resolved"), bool):
            errors.append(f"conflict {conflict_id!r} resolved must be boolean")
        elif row["resolved"]:
            for field in ("resolution", "discriminating_evidence"):
                if not isinstance(row.get(field), str) or not row[field].strip():
                    errors.append(f"resolved conflict {conflict_id!r} requires {field}")
        elif (
            not isinstance(row.get("next_check"), str) or not row["next_check"].strip()
        ):
            errors.append(f"open conflict {conflict_id!r} requires next_check")


def _validate_errors(
    records: dict[str, list[dict[str, Any]]], errors: list[str]
) -> None:
    known_rounds = {row.get("round_id") for row in records["rounds"]}
    known_gaps = set(_gap_state(records))
    known_actions = set(_action_state(records))
    seen: set[str] = set()
    for row in records["errors"]:
        error_id = row.get("error_id")
        if not isinstance(error_id, str):
            errors.append("error_id must be a string")
            continue
        try:
            _validate_entity_id(error_id, "error_id")
        except ValueError as exc:
            errors.append(str(exc))
        if error_id in seen:
            errors.append(f"duplicate error_id: {error_id!r}")
        seen.add(error_id)
        if row.get("record_id") != f"error:{error_id}":
            errors.append(f"error {error_id!r} record_id mismatch")
        if row.get("failure_class") not in FAILURE_CLASSES:
            errors.append(f"error {error_id!r} has invalid failure_class")
        for field in ("message", "next_safe_action"):
            if not isinstance(row.get(field), str) or not row[field].strip():
                errors.append(f"error {error_id!r} requires {field}")
        if not isinstance(row.get("retryable"), bool) or not isinstance(
            row.get("fatal"), bool
        ):
            errors.append(f"error {error_id!r} retryable/fatal must be boolean")
        if not isinstance(row.get("affects_coverage"), bool):
            errors.append(f"error {error_id!r} affects_coverage must be boolean")
        if not isinstance(row.get("partial_artifacts"), list):
            errors.append(f"error {error_id!r} partial_artifacts must be a list")
        round_id = row.get("round_id")
        if round_id is not None and round_id not in known_rounds:
            errors.append(f"error {error_id!r} references unknown round_id")
        gap_id = row.get("gap_id")
        if gap_id is not None and gap_id not in known_gaps:
            errors.append(f"error {error_id!r} references unknown gap_id")
        action_id = row.get("action_id")
        if action_id is not None and action_id not in known_actions:
            errors.append(f"error {error_id!r} references unknown action_id")


def _validate_transitions(
    records: dict[str, list[dict[str, Any]]], errors: list[str]
) -> None:
    lifecycle = "uninitialized"
    for ledger, record in _ordered_records(records):
        event = record.get("event") if ledger == "events" else None
        if event == "initialized":
            if lifecycle != "uninitialized":
                errors.append("initialized event is out of order")
            lifecycle = "running"
        elif ledger == "errors":
            if lifecycle not in {"running", "interrupted"}:
                errors.append("error record is outside an active lifecycle")
            if record.get("fatal"):
                lifecycle = "interrupted"
        elif event == "resumed":
            if lifecycle != "interrupted":
                errors.append("resumed event requires interrupted lifecycle")
            lifecycle = "running"
        elif event == "finalized":
            if lifecycle not in {"running", "interrupted"}:
                errors.append("finalized event requires an active lifecycle")
            lifecycle = "finalized"
        elif event == "coverage_set":
            if lifecycle != "running":
                errors.append("coverage can be set only while running")
        elif event in {"conflict_resolved", "error_resolved"}:
            if lifecycle != "running":
                errors.append("conflicts/errors can be resolved only while running")
        elif ledger != "events" and lifecycle != "running":
            errors.append(
                f"{ledger} record was written while lifecycle was {lifecycle}"
            )


def _validate_final_gate(
    state: dict[str, Any], records: dict[str, list[dict[str, Any]]], errors: list[str]
) -> None:
    finals = [row for row in records["events"] if row.get("event") == "finalized"]
    if not finals:
        return
    final = finals[0]
    prefix = {
        name: [row for row in rows if row.get("sequence", 0) < final.get("sequence", 0)]
        for name, rows in records.items()
    }
    prefix_errors: list[str] = []
    pre_summary = _summary(state, prefix, prefix_errors)
    outcome = final.get("outcome")
    if outcome == "complete":
        if not pre_summary["can_finalize_complete"]:
            errors.append("complete outcome did not pass the completion gate")
        expected_reason = (
            "protocol_complete"
            if state.get("contract", {}).get("mode") == "systematic"
            else "pragmatic_saturation"
        )
        if final.get("stop_reason") != expected_reason:
            errors.append(f"complete outcome requires stop_reason={expected_reason}")
    elif outcome == "partial":
        if not pre_summary["can_finalize_partial"]:
            errors.append(
                "partial outcome requires an explicit non-open coverage status"
            )
        if final.get("stop_reason") not in PARTIAL_STOP_REASONS:
            errors.append("partial outcome has an invalid or misleading stop_reason")


def _validate_bundle(
    paths: Paths,
    state: dict[str, Any],
    records: dict[str, list[dict[str, Any]]],
) -> list[str]:
    errors: list[str] = []
    if state.get("schema_version") != SCHEMA_VERSION:
        errors.append("run.json schema_version mismatch")
    if state.get("run_id") != paths.run_id:
        errors.append("run.json run_id mismatch")
    contract = state.get("contract")
    if not isinstance(contract, dict):
        errors.append("run.json contract must be an object")
    else:
        for field in (
            "question",
            "decision_or_use",
            "scope",
            "coverage_promise",
            "currentness",
            "risk",
        ):
            if not isinstance(contract.get(field), str) or not contract[field].strip():
                errors.append(f"contract requires {field}")
        if contract.get("mode") not in MODES:
            errors.append("contract has invalid mode")
        protocol_ref = contract.get("protocol_ref")
        if contract.get("mode") == "systematic":
            if not isinstance(protocol_ref, str) or not PROTOCOL_REF_RE.fullmatch(
                protocol_ref
            ):
                errors.append(
                    "systematic mode requires protocol_ref=sha256:<64 lowercase hex>"
                )
        elif protocol_ref is not None and (
            not isinstance(protocol_ref, str)
            or not PROTOCOL_REF_RE.fullmatch(protocol_ref)
        ):
            errors.append("protocol_ref must be null or sha256:<64 lowercase hex>")
        exclusions = contract.get("exclusions")
        if not isinstance(exclusions, list) or any(
            not isinstance(item, str) or not item.strip() for item in (exclusions or [])
        ):
            errors.append("contract exclusions must be a string list")
        coverage_gap_ids = contract.get("coverage_gap_ids")
        if not isinstance(coverage_gap_ids, list) or not coverage_gap_ids:
            errors.append("contract requires at least one coverage_gap_id")
        else:
            if len(coverage_gap_ids) != len(set(coverage_gap_ids)):
                errors.append("contract coverage_gap_ids must be unique")
            for gap_id in coverage_gap_ids:
                if not isinstance(gap_id, str):
                    errors.append("contract coverage_gap_ids must be strings")
                    continue
                try:
                    _validate_entity_id(gap_id, "coverage_gap_id")
                except ValueError as exc:
                    errors.append(str(exc))
        counterevidence_gap_ids = contract.get("counterevidence_gap_ids")
        if not isinstance(counterevidence_gap_ids, list):
            errors.append("contract counterevidence_gap_ids must be a list")
        else:
            if len(counterevidence_gap_ids) != len(set(counterevidence_gap_ids)):
                errors.append("contract counterevidence_gap_ids must be unique")
            unknown_counter_gaps = [
                gap_id
                for gap_id in counterevidence_gap_ids
                if not isinstance(coverage_gap_ids, list)
                or gap_id not in coverage_gap_ids
            ]
            if unknown_counter_gaps:
                errors.append(
                    "counterevidence_gap_ids must be declared coverage gaps: "
                    f"{unknown_counter_gaps}"
                )
        for field in ("max_rounds", "max_relations"):
            value = contract.get(field)
            if value is not None and (
                not isinstance(value, int) or isinstance(value, bool) or value <= 0
            ):
                errors.append(f"contract {field} must be null or a positive integer")

    _validate_envelopes(paths, records, errors)
    _validate_events(state, records, errors)
    _validate_gaps(state, records, errors)
    _validate_actions(records, errors)
    _validate_rounds(records, errors)
    _validate_sources(records, errors)
    _validate_claims(records, errors)
    _validate_conflicts(records, errors)
    _validate_errors(records, errors)
    _validate_coverage_against_gaps(state, records, errors)
    _validate_transitions(records, errors)
    _validate_final_gate(state, records, errors)
    return errors


def _cache_warnings(
    state: dict[str, Any],
    records: dict[str, list[dict[str, Any]]],
    summary: dict[str, Any],
) -> list[str]:
    warnings = []
    if state.get("status") != summary["lifecycle"]:
        warnings.append("run.json status cache is stale")
    if state.get("coverage") != summary["coverage"]:
        warnings.append("run.json coverage cache is stale")
    if state.get("outcome") != summary["outcome"]:
        warnings.append("run.json outcome cache is stale")
    cached_counts = state.get("summary", {}).get("counts")
    if cached_counts != summary["counts"]:
        warnings.append("run.json summary cache is stale")
    return warnings


def _refresh_state(
    paths: Paths,
    state: dict[str, Any],
    records: dict[str, list[dict[str, Any]]],
    errors: list[str],
) -> dict[str, Any]:
    summary = _summary(state, records, errors)
    state["status"] = summary["lifecycle"]
    state["coverage"] = summary["coverage"]
    state["outcome"] = summary["outcome"]
    state["summary"] = summary
    state.setdefault("meta", {})["updated_at"] = _utcnow()
    _write_atomic_json(paths.state, state)
    return summary


def _load_valid(
    paths: Paths,
) -> tuple[dict[str, Any], dict[str, list[dict[str, Any]]], list[str]]:
    state, records = _read_bundle(paths)
    return state, records, _validate_bundle(paths, state, records)


def _print_errors(errors: list[str]) -> None:
    print("run validation failed:", file=sys.stderr)
    for error in errors:
        print(f"- {error}", file=sys.stderr)


def _append_candidate(
    paths: Paths,
    state: dict[str, Any],
    records: dict[str, list[dict[str, Any]]],
    ledger: str,
    candidate: dict[str, Any],
) -> tuple[bool, dict[str, Any] | None]:
    proposed = {name: list(rows) for name, rows in records.items()}
    proposed[ledger].append(candidate)
    errors = _validate_bundle(paths, state, proposed)
    if errors:
        _print_errors(errors)
        return False, None
    _append_jsonl(paths.ledger(ledger), candidate)
    new_state, new_records = _read_bundle(paths)
    new_errors = _validate_bundle(paths, new_state, new_records)
    if new_errors:
        _print_errors(new_errors)
        return False, None
    return True, _refresh_state(paths, new_state, new_records, new_errors)


def command_init(args: argparse.Namespace) -> int:
    paths = _paths(args)
    if paths.base.exists():
        print(f"run directory already exists: {paths.base}", file=sys.stderr)
        return 1
    if args.mode == "systematic" and (
        not isinstance(args.protocol_ref, str)
        or not PROTOCOL_REF_RE.fullmatch(args.protocol_ref)
    ):
        raise ValueError(
            "systematic mode requires --protocol-ref sha256:<64 lowercase hex>"
        )
    if args.mode != "systematic" and args.protocol_ref is not None:
        if not PROTOCOL_REF_RE.fullmatch(args.protocol_ref):
            raise ValueError("protocol_ref must be sha256:<64 lowercase hex>")
    coverage_gap_ids = _clean_list(args.coverage_gap_id)
    if len(coverage_gap_ids) != len(set(coverage_gap_ids)):
        raise ValueError("coverage_gap_id values must be unique")
    for gap_id in coverage_gap_ids:
        _validate_entity_id(gap_id, "coverage_gap_id")
    counterevidence_gap_ids = _clean_list(args.counterevidence_gap_id)
    if len(counterevidence_gap_ids) != len(set(counterevidence_gap_ids)):
        raise ValueError("counterevidence_gap_id values must be unique")
    unknown_counter_gaps = [
        gap_id for gap_id in counterevidence_gap_ids if gap_id not in coverage_gap_ids
    ]
    if unknown_counter_gaps:
        raise ValueError(
            "counterevidence_gap_id must also be a coverage_gap_id: "
            f"{unknown_counter_gaps}"
        )
    contract = {
        "mode": args.mode,
        "question": _required_text(args.question, "question"),
        "decision_or_use": _required_text(args.decision_or_use, "decision_or_use"),
        "scope": _required_text(args.scope, "scope"),
        "exclusions": _clean_list(args.exclusion),
        "coverage_promise": _required_text(args.coverage, "coverage"),
        "coverage_gap_ids": coverage_gap_ids,
        "counterevidence_gap_ids": counterevidence_gap_ids,
        "currentness": _required_text(args.currentness, "currentness"),
        "risk": _required_text(args.risk, "risk"),
        "protocol_ref": args.protocol_ref,
        "max_rounds": args.max_rounds,
        "max_relations": args.max_relations,
    }
    paths.base.mkdir(parents=True)
    for name in LEDGER_NAMES:
        paths.ledger(name).touch()
    state = {
        "schema_version": SCHEMA_VERSION,
        "run_id": paths.run_id,
        "contract": contract,
        "status": "running",
        "coverage": {
            "status": "open",
            "basis": None,
            "unresolved_gaps": [],
            "rationale": None,
        },
        "outcome": None,
        "summary": {"counts": {name: 0 for name in LEDGER_NAMES}},
        "meta": {"created_at": _utcnow(), "updated_at": _utcnow()},
    }
    _write_atomic_json(paths.state, state)
    records = {name: [] for name in LEDGER_NAMES}
    init_event = _record(
        paths,
        records,
        "event:init",
        event="initialized",
        contract=contract,
    )
    ok, summary = _append_candidate(paths, state, records, "events", init_event)
    if not ok:
        return 1
    print(json.dumps({"run_dir": str(paths.base), "summary": summary}, indent=2))
    return 0


def _active(
    args: argparse.Namespace, *, allow_interrupted: bool = False
) -> tuple[Paths, dict[str, Any], dict[str, list[dict[str, Any]]]] | None:
    paths = _paths(args)
    state, records, errors = _load_valid(paths)
    if errors:
        _print_errors(errors)
        return None
    lifecycle = _derive_lifecycle(records)
    allowed = {"running", "interrupted"} if allow_interrupted else {"running"}
    if lifecycle not in allowed:
        print(f"command is not allowed while lifecycle is {lifecycle}", file=sys.stderr)
        return None
    return paths, state, records


def command_record_gap(args: argparse.Namespace) -> int:
    loaded = _active(args)
    if loaded is None:
        return 1
    paths, state, records = loaded
    gap_id = _validate_entity_id(args.gap_id, "gap_id")
    if gap_id in _gap_state(records):
        print("gap_id already exists", file=sys.stderr)
        return 1
    candidate = _record(
        paths,
        records,
        f"gap:{gap_id}:open",
        gap_id=gap_id,
        operation="opened",
        description=_required_text(args.description, "description"),
        acceptance_criteria=_required_text(
            args.acceptance_criteria, "acceptance_criteria"
        ),
        coverage_role=args.coverage_role,
        decision_impact=args.decision_impact,
        counterevidence_required=args.counterevidence_required,
        dependencies=_clean_list(args.depends_on),
        priority=args.priority,
    )
    ok, _ = _append_candidate(paths, state, records, "gaps", candidate)
    return 0 if ok else 1


def command_set_gap_status(args: argparse.Namespace) -> int:
    loaded = _active(args)
    if loaded is None:
        return 1
    paths, state, records = loaded
    gap_id = _validate_entity_id(args.gap_id, "gap_id")
    if gap_id not in _gap_state(records):
        print("unknown gap_id", file=sys.stderr)
        return 1
    sequence = _next_sequence(records)
    candidate = _record(
        paths,
        records,
        f"gap:{gap_id}:status:{sequence}",
        gap_id=gap_id,
        operation="status_set",
        status=args.status,
        rationale=_required_text(args.rationale, "rationale"),
        artifact_refs=_clean_list(args.artifact_ref),
        next_action=(args.next_action or "").strip(),
    )
    ok, _ = _append_candidate(paths, state, records, "gaps", candidate)
    return 0 if ok else 1


def command_start_action(args: argparse.Namespace) -> int:
    loaded = _active(args)
    if loaded is None:
        return 1
    paths, state, records = loaded
    action_id = _validate_entity_id(args.action_id, "action_id")
    if action_id in _action_state(records):
        print("action_id already exists", file=sys.stderr)
        return 1
    gap_id = _validate_entity_id(args.gap_id, "gap_id")
    gaps = _gap_state(records)
    gap = gaps.get(gap_id)
    if gap is None:
        print("unknown gap_id", file=sys.stderr)
        return 1
    if gap.get("status") in TERMINAL_GAP_STATUSES:
        print("terminal gap must be reopened before a new action", file=sys.stderr)
        return 1
    unmet_dependencies = [
        dependency
        for dependency in gap.get("dependencies", [])
        if gaps.get(dependency, {}).get("status") not in TERMINAL_GAP_STATUSES
    ]
    if unmet_dependencies:
        print(
            f"gap dependencies are not terminal: {unmet_dependencies}", file=sys.stderr
        )
        return 1
    candidate = _record(
        paths,
        records,
        f"action:{action_id}:start",
        action_id=action_id,
        operation="started",
        gap_id=gap_id,
        action_type=args.action_type,
        inputs=_required_text(args.inputs, "inputs"),
        expected_information_gain=_required_text(
            args.expected_information_gain, "expected_information_gain"
        ),
        budget=_required_text(args.budget, "budget"),
        branch_id=_optional_entity_id(args.branch_id, "branch_id"),
        attempt_id=_optional_entity_id(args.attempt_id, "attempt_id"),
    )
    ok, _ = _append_candidate(paths, state, records, "actions", candidate)
    return 0 if ok else 1


def command_finish_action(args: argparse.Namespace) -> int:
    loaded = _active(args)
    if loaded is None:
        return 1
    paths, state, records = loaded
    action_id = _validate_entity_id(args.action_id, "action_id")
    action = _action_state(records).get(action_id)
    if action is None:
        print("unknown action_id", file=sys.stderr)
        return 1
    if action.get("status") != "started":
        print("action is already terminal", file=sys.stderr)
        return 1
    candidate = _record(
        paths,
        records,
        f"action:{action_id}:finish",
        action_id=action_id,
        operation="finished",
        status=args.status,
        result=_required_text(args.result, "result"),
        remaining_uncertainty=_required_text(
            args.remaining_uncertainty, "remaining_uncertainty"
        ),
        artifact_refs=_clean_list(args.artifact_ref),
        next_action=(args.next_action or "").strip(),
    )
    ok, _ = _append_candidate(paths, state, records, "actions", candidate)
    return 0 if ok else 1


def command_record_round(args: argparse.Namespace) -> int:
    loaded = _active(args)
    if loaded is None:
        return 1
    paths, state, records = loaded
    if args.round_id in _ids(records, "round_id", "rounds"):
        print("round_id already exists", file=sys.stderr)
        return 1
    max_rounds = state["contract"].get("max_rounds")
    if isinstance(max_rounds, int) and len(records["rounds"]) >= max_rounds:
        print("round limit reached", file=sys.stderr)
        return 1
    gap_id = _validate_entity_id(args.gap_id, "gap_id")
    action_id = _validate_entity_id(args.action_id, "action_id")
    action = _action_state(records).get(action_id)
    if action is None or action.get("status") != "started":
        print("round requires an active action_id", file=sys.stderr)
        return 1
    if action.get("gap_id") != gap_id:
        print("round action_id does not belong to gap_id", file=sys.stderr)
        return 1
    screened = _clean_list(args.screened)
    included = _clean_list(args.included)
    exclusions = _clean_list(args.exclusion)
    information_types = _clean_list(args.new_information_type)
    candidate = _record(
        paths,
        records,
        f"round:{_validate_entity_id(args.round_id, 'round_id')}",
        round_id=args.round_id,
        gap_id=gap_id,
        action_id=action_id,
        branch_id=_optional_entity_id(args.branch_id, "branch_id"),
        attempt_id=_optional_entity_id(args.attempt_id, "attempt_id"),
        decision_critical_gap=_required_text(args.gap, "gap"),
        route_and_query_set=_required_text(
            args.route_and_query_set, "route_and_query_set"
        ),
        filters_version_date=_required_text(
            args.filters_version_date, "filters_version_date"
        ),
        screened=screened,
        included=included,
        exclusions=exclusions,
        status=args.status,
        new_information=args.new_information == "yes",
        new_information_types=information_types,
        result=_required_text(args.result, "result"),
    )
    ok, _ = _append_candidate(paths, state, records, "rounds", candidate)
    return 0 if ok else 1


def command_record_source(args: argparse.Namespace) -> int:
    loaded = _active(args)
    if loaded is None:
        return 1
    paths, state, records = loaded
    if args.source_id in _ids(records, "source_id", "sources"):
        print("source_id already exists", file=sys.stderr)
        return 1
    source_id = _validate_entity_id(args.source_id, "source_id")
    candidate = _record(
        paths,
        records,
        f"source:{source_id}",
        source_id=source_id,
        canonical_identity=_required_text(
            args.canonical_identity, "canonical_identity"
        ),
        canonical_version=_required_text(args.canonical_version, "canonical_version"),
        read_version=_required_text(args.read_version, "read_version"),
        access_level=args.access_level,
        inspection_state=args.inspection_state,
        status_check=args.status_check,
        evidence_class=args.evidence_class,
        role=args.role,
    )
    ok, _ = _append_candidate(paths, state, records, "sources", candidate)
    return 0 if ok else 1


def command_record_claim(args: argparse.Namespace) -> int:
    loaded = _active(args)
    if loaded is None:
        return 1
    paths, state, records = loaded
    if args.relation_id in _ids(records, "relation_id", "claims"):
        print("relation_id already exists", file=sys.stderr)
        return 1
    max_relations = state["contract"].get("max_relations")
    if isinstance(max_relations, int) and len(records["claims"]) >= max_relations:
        print("relation limit reached", file=sys.stderr)
        return 1
    relation_id = _validate_entity_id(args.relation_id, "relation_id")
    candidate = _record(
        paths,
        records,
        f"claim:{relation_id}",
        relation_id=relation_id,
        claim_id=_validate_entity_id(args.claim_id, "claim_id"),
        claim_text=_required_text(args.claim_text, "claim_text"),
        source_id=_validate_entity_id(args.source_id, "source_id"),
        relation=args.relation,
        faithful_evidence=_required_text(args.faithful_evidence, "faithful_evidence"),
        exact_locator=(args.exact_locator or "").strip(),
        evidence_class=args.evidence_class,
        scope_and_applicability=_required_text(
            args.scope_and_applicability, "scope_and_applicability"
        ),
        version_fit=args.version_fit,
        decision_impact=args.decision_impact,
    )
    ok, _ = _append_candidate(paths, state, records, "claims", candidate)
    return 0 if ok else 1


def command_record_conflict(args: argparse.Namespace) -> int:
    loaded = _active(args)
    if loaded is None:
        return 1
    paths, state, records = loaded
    if args.conflict_id in _ids(records, "conflict_id", "conflicts"):
        print("conflict_id already exists", file=sys.stderr)
        return 1
    conflict_id = _validate_entity_id(args.conflict_id, "conflict_id")
    candidate = _record(
        paths,
        records,
        f"conflict:{conflict_id}",
        conflict_id=conflict_id,
        affected_claim_ids=_clean_list(args.affected_claim_id),
        conflict_type=_required_text(args.conflict_type, "conflict_type"),
        resolved=args.resolved,
        resolution=(args.resolution or "").strip(),
        discriminating_evidence=(args.discriminating_evidence or "").strip(),
        next_check=(args.next_check or "").strip(),
    )
    ok, _ = _append_candidate(paths, state, records, "conflicts", candidate)
    return 0 if ok else 1


def command_resolve_conflict(args: argparse.Namespace) -> int:
    loaded = _active(args)
    if loaded is None:
        return 1
    paths, state, records = loaded
    conflict_id = _validate_entity_id(args.conflict_id, "conflict_id")
    conflicts_by_id = {
        row.get("conflict_id"): row
        for row in records["conflicts"]
        if isinstance(row.get("conflict_id"), str)
    }
    conflict = conflicts_by_id.get(conflict_id)
    if conflict is None:
        print("unknown conflict_id", file=sys.stderr)
        return 1
    resolved_ids = {
        event.get("conflict_id")
        for event in records["events"]
        if event.get("event") == "conflict_resolved"
    }
    if conflict.get("resolved") is True or conflict_id in resolved_ids:
        print("conflict_id is already resolved", file=sys.stderr)
        return 1
    candidate = _record(
        paths,
        records,
        f"event:conflict-resolved:{conflict_id}",
        event="conflict_resolved",
        conflict_id=conflict_id,
        resolution=_required_text(args.resolution, "resolution"),
        discriminating_evidence=_required_text(
            args.discriminating_evidence, "discriminating_evidence"
        ),
    )
    ok, _ = _append_candidate(paths, state, records, "events", candidate)
    return 0 if ok else 1


def command_record_error(args: argparse.Namespace) -> int:
    loaded = _active(args, allow_interrupted=True)
    if loaded is None:
        return 1
    paths, state, records = loaded
    if args.error_id in _ids(records, "error_id", "errors"):
        print("error_id already exists", file=sys.stderr)
        return 1
    error_id = _validate_entity_id(args.error_id, "error_id")
    candidate = _record(
        paths,
        records,
        f"error:{error_id}",
        error_id=error_id,
        failure_class=args.failure_class,
        message=_required_text(args.message, "message"),
        gap_id=_optional_entity_id(args.gap_id, "gap_id"),
        action_id=_optional_entity_id(args.action_id, "action_id"),
        branch_id=_optional_entity_id(args.branch_id, "branch_id"),
        attempt_id=_optional_entity_id(args.attempt_id, "attempt_id"),
        round_id=_optional_entity_id(args.round_id, "round_id"),
        retryable=args.retryable == "yes",
        affects_coverage=not args.does_not_affect_coverage,
        partial_artifacts=_clean_list(args.partial_artifact),
        next_safe_action=_required_text(args.next_safe_action, "next_safe_action"),
        fatal=args.fatal,
    )
    ok, _ = _append_candidate(paths, state, records, "errors", candidate)
    return 0 if ok else 1


def command_resolve_error(args: argparse.Namespace) -> int:
    loaded = _active(args)
    if loaded is None:
        return 1
    paths, state, records = loaded
    known_errors = _ids(records, "error_id", "errors")
    if args.error_id not in known_errors:
        print("unknown error_id", file=sys.stderr)
        return 1
    resolved_errors, _ = _error_state(records)
    if args.error_id in resolved_errors:
        print("error_id is already resolved", file=sys.stderr)
        return 1
    candidate = _record(
        paths,
        records,
        f"event:error-resolved:{_next_sequence(records)}",
        event="error_resolved",
        error_id=args.error_id,
        resolution=_required_text(args.resolution, "resolution"),
        resolution_evidence=_required_text(
            args.resolution_evidence, "resolution_evidence"
        ),
    )
    ok, _ = _append_candidate(paths, state, records, "events", candidate)
    return 0 if ok else 1


def command_set_coverage(args: argparse.Namespace) -> int:
    loaded = _active(args)
    if loaded is None:
        return 1
    paths, state, records = loaded
    candidate = _record(
        paths,
        records,
        f"event:coverage:{_next_sequence(records)}",
        event="coverage_set",
        coverage_status=args.status,
        basis=args.basis,
        unresolved_gaps=_clean_list(args.unresolved_gap),
        rationale=_required_text(args.rationale, "rationale"),
    )
    ok, _ = _append_candidate(paths, state, records, "events", candidate)
    return 0 if ok else 1


def command_resume(args: argparse.Namespace) -> int:
    paths = _paths(args)
    state, records, errors = _load_valid(paths)
    if errors:
        _print_errors(errors)
        return 1
    lifecycle = _derive_lifecycle(records)
    resumed = False
    if lifecycle == "interrupted":
        candidate = _record(
            paths,
            records,
            f"event:resume:{_next_sequence(records)}",
            event="resumed",
        )
        ok, summary = _append_candidate(paths, state, records, "events", candidate)
        if not ok:
            return 1
        resumed = True
    elif lifecycle == "running":
        summary = _refresh_state(paths, state, records, errors)
    else:
        print(f"cannot resume lifecycle {lifecycle}", file=sys.stderr)
        return 1
    print(
        json.dumps(
            {
                "resumed": resumed,
                "lifecycle": summary["lifecycle"],
                "next_round_index": summary["counts"]["rounds"] + 1,
                "unresolved_gaps": summary["coverage"]["unresolved_gaps"],
                "active_actions": summary["active_actions"],
                "ready_gap_ids": summary["ready_gap_ids"],
            },
            indent=2,
        )
    )
    return 0


def command_finalize(args: argparse.Namespace) -> int:
    paths = _paths(args)
    state, records, errors = _load_valid(paths)
    if errors:
        _print_errors(errors)
        return 1
    existing = _derive_outcome(records)
    requested = {
        "outcome": args.outcome,
        "stop_reason": _required_text(args.stop_reason, "stop_reason"),
        "summary": _required_text(args.summary, "summary"),
    }
    if existing is not None:
        comparable = {key: existing[key] for key in requested}
        if comparable == requested:
            _refresh_state(paths, state, records, errors)
            print("run already finalized with the same outcome")
            return 0
        print("run is already finalized with a different outcome", file=sys.stderr)
        return 1
    candidate = _record(
        paths,
        records,
        "event:finalize",
        event="finalized",
        **requested,
    )
    ok, _ = _append_candidate(paths, state, records, "events", candidate)
    return 0 if ok else 1


def _status_payload(paths: Paths) -> tuple[dict[str, Any], int]:
    state, records = _read_bundle(paths)
    errors = _validate_bundle(paths, state, records)
    summary = _summary(state, records, errors)
    return {
        "schema_version": SCHEMA_VERSION,
        "run_id": paths.run_id,
        "contract": state.get("contract"),
        "summary": summary,
        "validation_errors": errors,
        "cache_warnings": _cache_warnings(state, records, summary),
    }, 1 if errors else 0


def command_status(args: argparse.Namespace) -> int:
    payload, code = _status_payload(_paths(args))
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    return code


def command_suggest_next(args: argparse.Namespace) -> int:
    paths = _paths(args)
    state, records = _read_bundle(paths)
    validation_errors = _validate_bundle(paths, state, records)
    if validation_errors:
        _print_errors(validation_errors)
        return 1

    if bool(args.network_path) != bool(args.knowledge_network_sha256):
        print(
            "--network-path and --knowledge-network-sha256 must be provided together",
            file=sys.stderr,
        )
        return 1

    network_payload: dict[str, Any] | None = None
    network_binding: dict[str, str] | None = None
    if args.network_path:
        try:
            network_payload, network_binding = _load_knowledge_network(
                Path(args.network_path), args.knowledge_network_sha256
            )
        except (OSError, ValueError) as exc:
            print(f"{exc.__class__.__name__}: {exc}", file=sys.stderr)
            return 1

    summary = _summary(state, records, validation_errors)
    candidates: list[dict[str, Any]] = []
    if summary["lifecycle"] == "running":
        gap_state = _gap_state(records)
        ready_gap_ids = set(summary["ready_gap_ids"])
        candidates.extend(_build_next_actions_from_run(gap_state, ready_gap_ids))
        if network_payload is not None:
            network_candidates = _build_next_actions_from_network(
                network_payload, gap_state, ready_gap_ids
            )
            replaced_gap_ids = {
                row["gap_id"]
                for row in network_candidates
                if row.get("source") == "run+knowledge_network"
                and row.get("action_type") != "reopen_gap"
            }
            candidates = [
                row for row in candidates if row["gap_id"] not in replaced_gap_ids
            ]
            candidates.extend(network_candidates)
    suggestions = _finalize_suggestions(candidates, args.max_suggestions)
    print(
        json.dumps(
            {
                "schema_version": SCHEMA_VERSION,
                "run_id": paths.run_id,
                "summary": summary,
                "validation_errors": validation_errors,
                "knowledge_network": network_binding,
                "next_actions": suggestions,
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
    )
    return 0


def command_validate(args: argparse.Namespace) -> int:
    payload, code = _status_payload(_paths(args))
    if code:
        _print_errors(payload["validation_errors"])
    else:
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    return code


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Validate an authorized deep-research run ledger",
        exit_on_error=False,
    )
    parser.add_argument("--root", required=True, help="Explicitly authorized workspace")
    parser.add_argument("--run-id", required=True)
    commands = parser.add_subparsers(dest="command", required=True)

    init = commands.add_parser("init")
    init.add_argument("--mode", choices=sorted(MODES), default="targeted")
    init.add_argument("--protocol-ref")
    init.add_argument("--question", required=True)
    init.add_argument("--decision-or-use", required=True)
    init.add_argument("--scope", required=True)
    init.add_argument("--exclusion", action="append")
    init.add_argument("--coverage", required=True)
    init.add_argument("--coverage-gap-id", action="append", required=True)
    init.add_argument("--counterevidence-gap-id", action="append")
    init.add_argument("--currentness", required=True)
    init.add_argument("--risk", required=True)
    init.add_argument("--max-rounds", type=_positive_int)
    init.add_argument("--max-relations", type=_positive_int)
    init.set_defaults(func=command_init)

    gap = commands.add_parser("record-gap")
    gap.add_argument("--gap-id", required=True)
    gap.add_argument("--description", required=True)
    gap.add_argument("--acceptance-criteria", required=True)
    gap.add_argument("--coverage-role", choices=("promised", "emergent"), required=True)
    gap.add_argument(
        "--decision-impact", choices=sorted(DECISION_IMPACTS), required=True
    )
    gap.add_argument("--counterevidence-required", action="store_true")
    gap.add_argument("--depends-on", action="append")
    gap.add_argument("--priority", type=_positive_int, required=True)
    gap.set_defaults(func=command_record_gap)

    gap_status = commands.add_parser("set-gap-status")
    gap_status.add_argument("--gap-id", required=True)
    gap_status.add_argument("--status", choices=sorted(GAP_STATUSES), required=True)
    gap_status.add_argument("--rationale", required=True)
    gap_status.add_argument("--artifact-ref", action="append")
    gap_status.add_argument("--next-action")
    gap_status.set_defaults(func=command_set_gap_status)

    start_action = commands.add_parser("start-action")
    start_action.add_argument("--action-id", required=True)
    start_action.add_argument("--gap-id", required=True)
    start_action.add_argument(
        "--action-type", choices=sorted(ACTION_TYPES), required=True
    )
    start_action.add_argument("--inputs", required=True)
    start_action.add_argument("--expected-information-gain", required=True)
    start_action.add_argument("--budget", required=True)
    start_action.add_argument("--branch-id")
    start_action.add_argument("--attempt-id")
    start_action.set_defaults(func=command_start_action)

    finish_action = commands.add_parser("finish-action")
    finish_action.add_argument("--action-id", required=True)
    finish_action.add_argument(
        "--status", choices=sorted(ACTION_STATUSES), required=True
    )
    finish_action.add_argument("--result", required=True)
    finish_action.add_argument("--remaining-uncertainty", required=True)
    finish_action.add_argument("--artifact-ref", action="append")
    finish_action.add_argument("--next-action")
    finish_action.set_defaults(func=command_finish_action)

    round_parser = commands.add_parser("record-round")
    round_parser.add_argument("--round-id", required=True)
    round_parser.add_argument("--gap-id", required=True)
    round_parser.add_argument("--action-id", required=True)
    round_parser.add_argument("--branch-id")
    round_parser.add_argument("--attempt-id")
    round_parser.add_argument("--gap", required=True)
    round_parser.add_argument("--route-and-query-set", required=True)
    round_parser.add_argument("--filters-version-date", required=True)
    round_parser.add_argument("--screened", action="append")
    round_parser.add_argument("--included", action="append")
    round_parser.add_argument("--exclusion", action="append")
    round_parser.add_argument("--status", choices=sorted(ROUND_STATUSES), required=True)
    round_parser.add_argument("--new-information", choices=("yes", "no"), required=True)
    round_parser.add_argument("--new-information-type", action="append")
    round_parser.add_argument("--result", required=True)
    round_parser.set_defaults(func=command_record_round)

    source = commands.add_parser("record-source")
    source.add_argument("--source-id", required=True)
    source.add_argument("--canonical-identity", required=True)
    source.add_argument("--canonical-version", required=True)
    source.add_argument("--read-version", required=True)
    source.add_argument("--access-level", choices=sorted(ACCESS_LEVELS), required=True)
    source.add_argument(
        "--inspection-state", choices=sorted(INSPECTION_STATES), required=True
    )
    source.add_argument("--status-check", choices=sorted(STATUS_CHECKS), required=True)
    source.add_argument(
        "--evidence-class", choices=sorted(EVIDENCE_CLASSES), required=True
    )
    source.add_argument("--role", choices=sorted(SOURCE_ROLES), required=True)
    source.set_defaults(func=command_record_source)

    claim = commands.add_parser("record-claim")
    claim.add_argument("--relation-id", required=True)
    claim.add_argument("--claim-id", required=True)
    claim.add_argument("--claim-text", required=True)
    claim.add_argument("--source-id", required=True)
    claim.add_argument("--relation", choices=sorted(RELATIONS), required=True)
    claim.add_argument("--faithful-evidence", required=True)
    claim.add_argument("--exact-locator")
    claim.add_argument(
        "--evidence-class", choices=sorted(EVIDENCE_CLASSES), required=True
    )
    claim.add_argument("--scope-and-applicability", required=True)
    claim.add_argument("--version-fit", choices=("yes", "no", "unknown"), required=True)
    claim.add_argument(
        "--decision-impact", choices=sorted(DECISION_IMPACTS), required=True
    )
    claim.set_defaults(func=command_record_claim)

    conflict = commands.add_parser("record-conflict")
    conflict.add_argument("--conflict-id", required=True)
    conflict.add_argument("--affected-claim-id", action="append", required=True)
    conflict.add_argument("--conflict-type", required=True)
    conflict.add_argument("--resolved", action="store_true")
    conflict.add_argument("--resolution")
    conflict.add_argument("--discriminating-evidence")
    conflict.add_argument("--next-check")
    conflict.set_defaults(func=command_record_conflict)

    resolve_conflict = commands.add_parser("resolve-conflict")
    resolve_conflict.add_argument("--conflict-id", required=True)
    resolve_conflict.add_argument("--resolution", required=True)
    resolve_conflict.add_argument("--discriminating-evidence", required=True)
    resolve_conflict.set_defaults(func=command_resolve_conflict)

    error = commands.add_parser("record-error")
    error.add_argument("--error-id", required=True)
    error.add_argument(
        "--failure-class", choices=sorted(FAILURE_CLASSES), required=True
    )
    error.add_argument("--message", required=True)
    error.add_argument("--gap-id")
    error.add_argument("--action-id")
    error.add_argument("--branch-id")
    error.add_argument("--attempt-id")
    error.add_argument("--round-id")
    error.add_argument("--retryable", choices=("yes", "no"), required=True)
    error.add_argument("--partial-artifact", action="append")
    error.add_argument("--next-safe-action", required=True)
    error.add_argument("--fatal", action="store_true")
    error.add_argument("--does-not-affect-coverage", action="store_true")
    error.set_defaults(func=command_record_error)

    resolve_error = commands.add_parser("resolve-error")
    resolve_error.add_argument("--error-id", required=True)
    resolve_error.add_argument("--resolution", required=True)
    resolve_error.add_argument("--resolution-evidence", required=True)
    resolve_error.set_defaults(func=command_resolve_error)

    coverage = commands.add_parser("set-coverage")
    coverage.add_argument(
        "--status", choices=sorted(COVERAGE_STATUSES - {"open"}), required=True
    )
    coverage.add_argument("--basis", choices=sorted(COVERAGE_BASES), required=True)
    coverage.add_argument("--unresolved-gap", action="append")
    coverage.add_argument("--rationale", required=True)
    coverage.set_defaults(func=command_set_coverage)

    resume = commands.add_parser("resume")
    resume.set_defaults(func=command_resume)

    finalize = commands.add_parser("finalize")
    finalize.add_argument("--outcome", choices=sorted(OUTCOMES), required=True)
    finalize.add_argument(
        "--stop-reason",
        choices=sorted(COMPLETE_STOP_REASONS | PARTIAL_STOP_REASONS),
        required=True,
    )
    finalize.add_argument("--summary", required=True)
    finalize.set_defaults(func=command_finalize)

    status = commands.add_parser("status")
    status.set_defaults(func=command_status)
    suggest_next = commands.add_parser("suggest-next")
    suggest_next.add_argument("--network-path")
    suggest_next.add_argument(
        "--knowledge-network-sha256",
        type=_sha256_hex,
        help="Required SHA-256 binding for --network-path",
    )
    suggest_next.add_argument("--max-suggestions", type=_positive_int)
    suggest_next.set_defaults(func=command_suggest_next)
    validate = commands.add_parser("validate")
    validate.set_defaults(func=command_validate)
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
        read_only = args.command in {"status", "suggest-next", "validate"}
        with _run_lock(_paths(args), exclusive=not read_only):
            return args.func(args)
    except (
        AttributeError,
        FileNotFoundError,
        json.JSONDecodeError,
        KeyError,
        OSError,
        TypeError,
        ValueError,
    ) as exc:
        print(f"{exc.__class__.__name__}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
