#!/usr/bin/env python3
"""Coordinate content-addressed stages for a compound research scenario."""

from __future__ import annotations

import argparse
import copy
import hashlib
import importlib.util
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any


SCENARIO_SCHEMA = "ResearchScenario/v1"
EXECUTION_SCHEMA = "ResearchPipelineExecution/v1"
SCHEMA_VERSION = "v1"
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
COLLECTION_KEY_RE = re.compile(r"^[A-Z0-9]{8}$")
FORBIDDEN_KEYS = {
    "authorization",
    "cookie",
    "password",
    "secret",
    "token",
    "api_key",
    "apikey",
}
PRE_APPRAISAL_STAGES = (
    "zotero_baseline",
    "network_seed",
    "topic_discovery",
    "source_acquisition",
    "source_normalization",
    "paper_understanding",
    "zotero_curation",
    "network_merge",
    "gap_cycle",
    "network_publish",
)
STAGES = (
    "zotero_baseline",
    "network_seed",
    "topic_discovery",
    "source_acquisition",
    "source_normalization",
    "paper_understanding",
    "evidence_appraisal",
    "zotero_curation",
    "network_merge",
    "gap_cycle",
    "network_publish",
)
LEGACY_STAGES = (
    "zotero_baseline",
    "network_seed",
    "topic_discovery",
    "source_acquisition",
    "paper_understanding",
    "zotero_curation",
    "network_merge",
    "gap_cycle",
    "network_publish",
)
PRE_APPRAISAL_DEPENDENCIES = {
    "zotero_baseline": (),
    "network_seed": ("zotero_baseline",),
    "topic_discovery": ("network_seed",),
    "source_acquisition": ("topic_discovery",),
    "source_normalization": ("source_acquisition",),
    "paper_understanding": ("source_acquisition", "source_normalization"),
    "zotero_curation": ("paper_understanding",),
    "network_merge": ("paper_understanding",),
    "gap_cycle": ("network_merge",),
    "network_publish": ("gap_cycle",),
}
DEPENDENCIES = {
    "zotero_baseline": (),
    "network_seed": ("zotero_baseline",),
    "topic_discovery": ("network_seed",),
    "source_acquisition": ("topic_discovery",),
    "source_normalization": ("source_acquisition",),
    "paper_understanding": ("source_acquisition", "source_normalization"),
    "evidence_appraisal": ("paper_understanding",),
    "zotero_curation": ("paper_understanding",),
    "network_merge": ("evidence_appraisal",),
    "gap_cycle": ("network_merge",),
    "network_publish": ("gap_cycle",),
}
LEGACY_DEPENDENCIES = {
    "zotero_baseline": (),
    "network_seed": ("zotero_baseline",),
    "topic_discovery": ("network_seed",),
    "source_acquisition": ("topic_discovery",),
    "paper_understanding": ("source_acquisition",),
    "zotero_curation": ("paper_understanding",),
    "network_merge": ("paper_understanding",),
    "gap_cycle": ("network_merge",),
    "network_publish": ("gap_cycle",),
}
LEGACY_EXECUTION_KEYS = {
    "schema",
    "schema_version",
    "execution_id",
    "scenario_id",
    "scenario_digest",
    "created_at",
    "updated_at",
    "stages",
    "history",
    "state_digest",
}
STAGE_KEYS = {
    "stage_id",
    "status",
    "dependencies",
    "artifacts",
    "reason",
    "updated_at",
}
HISTORY_KEYS = {
    "stage_id",
    "status",
    "artifact_sha256",
    "reason",
    "recorded_at",
}
MIGRATION_KEYS = {
    "schema",
    "schema_version",
    "migration_id",
    "migration_digest",
    "source_execution_id",
    "source_state_digest",
    "source_stage_ids",
    "target_stage_ids",
    "preserved_stages_digest",
    "preserved_history_digest",
    "verified_artifacts",
    "inserted_stage_id",
    "inserted_stage_status",
    "reason",
    "migrated_at",
}
STATUSES = {"pending", "running", "completed", "partial", "blocked"}
USABLE_DEPENDENCY_STATUSES = {"completed", "partial"}
TERMINAL_STAGE_STATUSES = {"completed", "partial", "blocked"}
DISCOVERY_RESULT_SET_SCHEMA = "ScholarDiscoveryResultSet/v2"
DISCOVERY_COMPLETE_STATUS = "complete_bounded"
TOPIC_DISCOVERY_RESULT_SET_ATTEMPT_SCHEMA = "ScholarDiscoveryResultSetAttempt/v1"
NETWORK_PUBLISH_EVIDENCE_SCHEMA = "ResearchNetworkPublishEvidence/v1"
TRANSITIONS = {
    "pending": {"running", "completed", "partial", "blocked"},
    "running": {"completed", "partial", "blocked"},
    "partial": {"running", "completed", "blocked"},
    "blocked": {"running"},
    "completed": set(),
}


class ContractError(ValueError):
    pass


class MigrationRequired(ContractError):
    def __init__(self, state_digest: str) -> None:
        super().__init__(
            "legacy pre-normalization execution requires explicit migration"
        )
        self.state_digest = state_digest


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def sha256_json(value: Any) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def _reject_duplicate_json_key_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ContractError(f"duplicate JSON key: {key!r}")
        result[key] = value
    return result


def _load_json_bytes(
    payload: bytes,
    path: Path,
    *,
    label: str,
    allow_invalid: bool = False,
) -> Any | None:
    try:
        return json.loads(
            payload.decode("utf-8"),
            object_pairs_hook=_reject_duplicate_json_key_pairs,
        )
    except (UnicodeDecodeError, json.JSONDecodeError):
        if allow_invalid:
            return None
        raise ContractError(f"{label} is invalid JSON: {path}")


def require_dict(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ContractError(f"{label} must be an object")
    return value


def require_string(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ContractError(f"{label} must be a non-empty string")
    return value.strip()


def require_string_list(value: Any, label: str, *, nonempty: bool = False) -> list[str]:
    if not isinstance(value, list) or any(
        not isinstance(item, str) or not item.strip() for item in value
    ):
        raise ContractError(f"{label} must be a list of non-empty strings")
    result = [item.strip() for item in value]
    if nonempty and not result:
        raise ContractError(f"{label} must not be empty")
    return result


def require_timestamp(value: Any, label: str) -> str:
    text = require_string(value, label)
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ContractError(f"{label} must be an ISO-8601 timestamp") from exc
    if parsed.tzinfo is None:
        raise ContractError(f"{label} must include a timezone")
    return text


def scan_forbidden_keys(value: Any, label: str = "scenario") -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str):
                raise ContractError(f"{label} keys must be strings")
            if key.casefold() in FORBIDDEN_KEYS:
                raise ContractError(
                    f"{label} contains forbidden credential field {key!r}"
                )
            scan_forbidden_keys(item, f"{label}.{key}")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            scan_forbidden_keys(item, f"{label}[{index}]")


def validate_scenario(value: Any) -> dict[str, Any]:
    scenario = copy.deepcopy(require_dict(value, "scenario"))
    scan_forbidden_keys(scenario)
    if scenario.get("schema") != SCENARIO_SCHEMA:
        raise ContractError(f"scenario.schema must equal {SCENARIO_SCHEMA}")
    if scenario.get("schema_version", SCHEMA_VERSION) != SCHEMA_VERSION:
        raise ContractError("scenario.schema_version is unsupported")
    scenario["schema_version"] = SCHEMA_VERSION
    for field in (
        "scenario_id",
        "question",
        "decision_or_use",
        "scope",
        "currentness",
        "risk",
    ):
        scenario[field] = require_string(scenario.get(field), f"scenario.{field}")
    scenario["exclusions"] = require_string_list(
        scenario.get("exclusions", []), "scenario.exclusions"
    )
    scenario["knowledge_dimensions"] = require_string_list(
        scenario.get("knowledge_dimensions"),
        "scenario.knowledge_dimensions",
        nonempty=True,
    )
    if len(set(scenario["knowledge_dimensions"])) != len(
        scenario["knowledge_dimensions"]
    ):
        raise ContractError("scenario.knowledge_dimensions contains duplicates")

    target = copy.deepcopy(
        require_dict(scenario.get("zotero_target"), "scenario.zotero_target")
    )
    group_id = target.get("group_id")
    if isinstance(group_id, bool) or not isinstance(group_id, int) or group_id <= 0:
        raise ContractError(
            "scenario.zotero_target.group_id must be a positive integer"
        )
    target["library_name"] = require_string(
        target.get("library_name"), "scenario.zotero_target.library_name"
    )
    collection_key = require_string(
        target.get("collection_key"), "scenario.zotero_target.collection_key"
    )
    if not COLLECTION_KEY_RE.fullmatch(collection_key):
        raise ContractError(
            "scenario.zotero_target.collection_key must be 8 uppercase alphanumerics"
        )
    target["collection_key"] = collection_key
    target["collection_path"] = require_string_list(
        target.get("collection_path"),
        "scenario.zotero_target.collection_path",
        nonempty=True,
    )
    scenario["zotero_target"] = target

    policy = require_string(
        scenario.get("google_scholar_policy", "manual_optional"),
        "scenario.google_scholar_policy",
    ).lower()
    if policy not in {"disabled", "manual_optional", "manual_required"}:
        raise ContractError("scenario.google_scholar_policy is invalid")
    scenario["google_scholar_policy"] = policy
    scenario["automatic_providers"] = require_string_list(
        scenario.get("automatic_providers", ["crossref", "semantic_scholar"]),
        "scenario.automatic_providers",
        nonempty=True,
    )
    if "google_scholar" in scenario["automatic_providers"]:
        raise ContractError("Google Scholar cannot be an automatic provider")
    needs = scenario.get("topic_needs")
    if not isinstance(needs, list) or not needs:
        raise ContractError("scenario.topic_needs must be a non-empty list")
    gap_ids: set[str] = set()
    for index, raw_need in enumerate(needs):
        need = require_dict(raw_need, f"scenario.topic_needs[{index}]")
        gap_id = require_string(
            need.get("gap_id"), f"scenario.topic_needs[{index}].gap_id"
        )
        if gap_id in gap_ids:
            raise ContractError(f"duplicate scenario topic gap_id: {gap_id}")
        if gap_id.startswith("derived:missing-dimension:"):
            raise ContractError(
                "structural missing-dimension gaps need semantic topic definitions"
            )
        gap_ids.add(gap_id)
    return scenario


def execution_digest(value: dict[str, Any]) -> str:
    return sha256_json(
        {key: item for key, item in value.items() if key != "state_digest"}
    )


def initialize_execution(value: Any, *, as_of: str) -> dict[str, Any]:
    scenario = validate_scenario(value)
    timestamp = require_timestamp(as_of, "as_of")
    scenario_digest = sha256_json(scenario)
    execution = {
        "schema": EXECUTION_SCHEMA,
        "schema_version": SCHEMA_VERSION,
        "execution_id": f"pipeline-{scenario_digest[:16]}",
        "scenario_id": scenario["scenario_id"],
        "scenario_digest": scenario_digest,
        "created_at": timestamp,
        "updated_at": timestamp,
        "stages": [
            {
                "stage_id": stage,
                "status": "pending",
                "dependencies": list(DEPENDENCIES[stage]),
                "artifacts": [],
                "reason": None,
                "updated_at": timestamp,
            }
            for stage in STAGES
        ],
        "migration_provenance": [],
        "history": [],
        "state_digest": "",
    }
    execution["state_digest"] = execution_digest(execution)
    return validate_execution(execution)


def validate_artifact(value: Any, label: str) -> dict[str, Any]:
    artifact = require_dict(value, label)
    path = require_string(artifact.get("path"), f"{label}.path")
    digest = require_string(artifact.get("sha256"), f"{label}.sha256")
    if not SHA256_RE.fullmatch(digest):
        raise ContractError(f"{label}.sha256 is invalid")
    size = artifact.get("size")
    if isinstance(size, bool) or not isinstance(size, int) or size < 0:
        raise ContractError(f"{label}.size must be a nonnegative integer")
    return {"path": path, "sha256": digest, "size": size}


def require_exact_keys(value: dict[str, Any], expected: set[str], label: str) -> None:
    actual = set(value)
    if actual != expected:
        raise ContractError(
            f"{label} keys mismatch; missing={sorted(expected - actual)}, "
            f"unknown={sorted(actual - expected)}"
        )


def validate_history_rows(
    history: Any, *, allowed_stages: tuple[str, ...], label: str
) -> list[dict[str, Any]]:
    if not isinstance(history, list):
        raise ContractError(f"{label} must be a list")
    for index, raw_row in enumerate(history):
        row = require_dict(raw_row, f"{label}[{index}]")
        require_exact_keys(row, HISTORY_KEYS, f"{label}[{index}]")
        if row.get("stage_id") not in allowed_stages:
            raise ContractError(f"{label}[{index}].stage_id is invalid")
        if row.get("status") not in STATUSES - {"pending"}:
            raise ContractError(f"{label}[{index}].status is invalid")
        digests = row.get("artifact_sha256")
        if not isinstance(digests, list) or any(
            not isinstance(item, str) or not SHA256_RE.fullmatch(item)
            for item in digests
        ):
            raise ContractError(f"{label}[{index}].artifact_sha256 is invalid")
        reason = row.get("reason")
        if reason is not None and not isinstance(reason, str):
            raise ContractError(f"{label}[{index}].reason is invalid")
        require_timestamp(row.get("recorded_at"), f"{label}[{index}].recorded_at")
    return history


def validate_legacy_execution(value: Any) -> dict[str, Any]:
    execution = copy.deepcopy(require_dict(value, "legacy execution"))
    require_exact_keys(execution, LEGACY_EXECUTION_KEYS, "legacy execution")
    if execution.get("schema") != EXECUTION_SCHEMA:
        raise ContractError(f"legacy execution.schema must equal {EXECUTION_SCHEMA}")
    if execution.get("schema_version") != SCHEMA_VERSION:
        raise ContractError("legacy execution.schema_version is unsupported")
    require_string(execution.get("execution_id"), "legacy execution.execution_id")
    require_string(execution.get("scenario_id"), "legacy execution.scenario_id")
    scenario_digest = require_string(
        execution.get("scenario_digest"), "legacy execution.scenario_digest"
    )
    if not SHA256_RE.fullmatch(scenario_digest):
        raise ContractError("legacy execution.scenario_digest is invalid")
    require_timestamp(execution.get("created_at"), "legacy execution.created_at")
    require_timestamp(execution.get("updated_at"), "legacy execution.updated_at")
    stages = execution.get("stages")
    if not isinstance(stages, list) or [
        stage.get("stage_id") for stage in stages if isinstance(stage, dict)
    ] != list(LEGACY_STAGES):
        raise ContractError(
            "legacy execution stages must equal the exact pre-normalization order"
        )
    for index, stage in enumerate(stages):
        label = f"legacy execution.stages[{index}]"
        require_exact_keys(stage, STAGE_KEYS, label)
        if stage.get("status") not in STATUSES:
            raise ContractError(f"{label}.status is invalid")
        if stage.get("dependencies") != list(LEGACY_DEPENDENCIES[stage["stage_id"]]):
            raise ContractError(f"{label}.dependencies are invalid")
        if not isinstance(stage.get("artifacts"), list):
            raise ContractError(f"{label}.artifacts must be a list")
        stage["artifacts"] = [
            validate_artifact(artifact, f"{label}.artifacts[{artifact_index}]")
            for artifact_index, artifact in enumerate(stage["artifacts"])
        ]
        require_timestamp(stage.get("updated_at"), f"{label}.updated_at")
        if stage["status"] in {"completed", "partial"} and not stage["artifacts"]:
            raise ContractError(f"{label} {stage['status']} without a bound artifact")
    validate_history_rows(
        execution.get("history"),
        allowed_stages=LEGACY_STAGES,
        label="legacy execution.history",
    )
    state_digest = require_string(
        execution.get("state_digest"), "legacy execution.state_digest"
    )
    if not SHA256_RE.fullmatch(state_digest) or state_digest != execution_digest(
        execution
    ):
        raise ContractError("legacy execution.state_digest is invalid")
    return execution


def migration_digest(value: dict[str, Any]) -> str:
    return sha256_json(
        {
            key: item
            for key, item in value.items()
            if key not in {"migration_id", "migration_digest"}
        }
    )


def validate_migration(value: Any, label: str) -> dict[str, Any]:
    migration = copy.deepcopy(require_dict(value, label))
    require_exact_keys(migration, MIGRATION_KEYS, label)
    migration_schema = migration.get("schema")
    if migration_schema not in {
        "ResearchPipelineMigration/v1",
        "ResearchPipelineMigration/v2",
    }:
        raise ContractError(f"{label}.schema is invalid")
    if migration.get("schema_version") != SCHEMA_VERSION:
        raise ContractError(f"{label}.schema_version is invalid")
    expected = (
        (
            list(LEGACY_STAGES),
            list(PRE_APPRAISAL_STAGES),
            "source_normalization",
            "normalization evidence required",
        )
        if migration_schema == "ResearchPipelineMigration/v1"
        else (
            list(PRE_APPRAISAL_STAGES),
            list(STAGES),
            "evidence_appraisal",
            "finalized evidence appraisal required before network merge",
        )
    )
    if migration.get("source_stage_ids") != expected[0]:
        raise ContractError(f"{label}.source_stage_ids is invalid")
    if migration.get("target_stage_ids") != expected[1]:
        raise ContractError(f"{label}.target_stage_ids is invalid")
    for key in (
        "source_state_digest",
        "preserved_stages_digest",
        "preserved_history_digest",
    ):
        if not SHA256_RE.fullmatch(str(migration.get(key))):
            raise ContractError(f"{label}.{key} is invalid")
    if migration.get("inserted_stage_id") != expected[2]:
        raise ContractError(f"{label}.inserted_stage_id is invalid")
    if migration.get("inserted_stage_status") not in {"pending", "blocked"}:
        raise ContractError(f"{label}.inserted_stage_status is invalid")
    if migration.get("reason") != expected[3]:
        raise ContractError(f"{label}.reason is invalid")
    require_timestamp(migration.get("migrated_at"), f"{label}.migrated_at")
    artifacts = migration.get("verified_artifacts")
    if not isinstance(artifacts, list):
        raise ContractError(f"{label}.verified_artifacts must be a list")
    migration["verified_artifacts"] = [
        validate_artifact(artifact, f"{label}.verified_artifacts[{index}]")
        for index, artifact in enumerate(artifacts)
    ]
    digest = migration_digest(migration)
    if migration.get("migration_digest") != digest:
        raise ContractError(f"{label}.migration_digest is invalid")
    if migration.get("migration_id") != f"pipeline-migration-{digest[:16]}":
        raise ContractError(f"{label}.migration_id is invalid")
    return migration


def validate_pre_appraisal_execution(value: Any) -> dict[str, Any]:
    execution = copy.deepcopy(require_dict(value, "pre-appraisal execution"))
    if execution.get("schema") != EXECUTION_SCHEMA:
        raise ContractError(
            f"pre-appraisal execution.schema must equal {EXECUTION_SCHEMA}"
        )
    if execution.get("schema_version") != SCHEMA_VERSION:
        raise ContractError("pre-appraisal execution.schema_version is unsupported")
    require_string(
        execution.get("execution_id"), "pre-appraisal execution.execution_id"
    )
    require_string(execution.get("scenario_id"), "pre-appraisal execution.scenario_id")
    scenario_digest = require_string(
        execution.get("scenario_digest"), "pre-appraisal execution.scenario_digest"
    )
    if not SHA256_RE.fullmatch(scenario_digest):
        raise ContractError("pre-appraisal execution.scenario_digest is invalid")
    require_timestamp(execution.get("created_at"), "pre-appraisal execution.created_at")
    require_timestamp(execution.get("updated_at"), "pre-appraisal execution.updated_at")
    stages = execution.get("stages")
    if not isinstance(stages, list) or [
        stage.get("stage_id") for stage in stages if isinstance(stage, dict)
    ] != list(PRE_APPRAISAL_STAGES):
        raise ContractError("pre-appraisal execution stages are invalid")
    for index, stage in enumerate(stages):
        label = f"pre-appraisal execution.stages[{index}]"
        require_exact_keys(stage, STAGE_KEYS, label)
        if stage.get("status") not in STATUSES:
            raise ContractError(f"{label}.status is invalid")
        if stage.get("dependencies") != list(
            PRE_APPRAISAL_DEPENDENCIES[stage["stage_id"]]
        ):
            raise ContractError(f"{label}.dependencies are invalid")
        if not isinstance(stage.get("artifacts"), list):
            raise ContractError(f"{label}.artifacts must be a list")
        stage["artifacts"] = [
            validate_artifact(artifact, f"{label}.artifacts[{artifact_index}]")
            for artifact_index, artifact in enumerate(stage["artifacts"])
        ]
        require_timestamp(stage.get("updated_at"), f"{label}.updated_at")
        if stage["status"] in {"completed", "partial"} and not stage["artifacts"]:
            raise ContractError(f"{label} {stage['status']} without a bound artifact")
    validate_history_rows(
        execution.get("history"),
        allowed_stages=PRE_APPRAISAL_STAGES,
        label="pre-appraisal execution.history",
    )
    provenance = execution.get("migration_provenance", [])
    if not isinstance(provenance, list):
        raise ContractError(
            "pre-appraisal execution.migration_provenance must be a list"
        )
    for index, migration in enumerate(provenance):
        validate_migration(
            migration, f"pre-appraisal execution.migration_provenance[{index}]"
        )
    state_digest = require_string(
        execution.get("state_digest"), "pre-appraisal execution.state_digest"
    )
    if not SHA256_RE.fullmatch(state_digest) or state_digest != execution_digest(
        execution
    ):
        raise ContractError("pre-appraisal execution.state_digest is invalid")
    return execution


def validate_execution(value: Any) -> dict[str, Any]:
    execution = copy.deepcopy(require_dict(value, "execution"))
    raw_stages = execution.get("stages")
    raw_stage_ids = (
        [stage.get("stage_id") for stage in raw_stages if isinstance(stage, dict)]
        if isinstance(raw_stages, list)
        else []
    )
    if raw_stage_ids == list(LEGACY_STAGES):
        legacy = validate_legacy_execution(execution)
        raise MigrationRequired(legacy["state_digest"])
    if raw_stage_ids == list(PRE_APPRAISAL_STAGES):
        return validate_pre_appraisal_execution(execution)
    if execution.get("schema") != EXECUTION_SCHEMA:
        raise ContractError(f"execution.schema must equal {EXECUTION_SCHEMA}")
    if execution.get("schema_version") != SCHEMA_VERSION:
        raise ContractError("execution.schema_version is unsupported")
    require_string(execution.get("execution_id"), "execution.execution_id")
    require_string(execution.get("scenario_id"), "execution.scenario_id")
    scenario_digest = require_string(
        execution.get("scenario_digest"), "execution.scenario_digest"
    )
    if not SHA256_RE.fullmatch(scenario_digest):
        raise ContractError("execution.scenario_digest is invalid")
    require_timestamp(execution.get("created_at"), "execution.created_at")
    require_timestamp(execution.get("updated_at"), "execution.updated_at")
    stages = execution.get("stages")
    if not isinstance(stages, list) or [
        stage.get("stage_id") for stage in stages
    ] != list(STAGES):
        raise ContractError(
            "execution.stages must contain the canonical ordered stages"
        )
    for index, stage in enumerate(stages):
        label = f"execution.stages[{index}]"
        if stage.get("status") not in STATUSES:
            raise ContractError(f"{label}.status is invalid")
        if stage.get("dependencies") != list(DEPENDENCIES[stage["stage_id"]]):
            raise ContractError(f"{label}.dependencies are invalid")
        if not isinstance(stage.get("artifacts"), list):
            raise ContractError(f"{label}.artifacts must be a list")
        stage["artifacts"] = [
            validate_artifact(artifact, f"{label}.artifacts[{artifact_index}]")
            for artifact_index, artifact in enumerate(stage["artifacts"])
        ]
        require_timestamp(stage.get("updated_at"), f"{label}.updated_at")
        if stage["status"] in {"completed", "partial"} and not stage["artifacts"]:
            raise ContractError(f"{label} {stage['status']} without a bound artifact")
    validate_history_rows(
        execution.get("history"),
        allowed_stages=STAGES,
        label="execution.history",
    )
    provenance = execution.get("migration_provenance", [])
    if not isinstance(provenance, list):
        raise ContractError("execution.migration_provenance must be a list")
    for index, migration in enumerate(provenance):
        validate_migration(migration, f"execution.migration_provenance[{index}]")
    state_digest = require_string(
        execution.get("state_digest"), "execution.state_digest"
    )
    if not SHA256_RE.fullmatch(state_digest) or state_digest != execution_digest(
        execution
    ):
        raise ContractError("execution.state_digest is invalid")
    return execution


def artifact_from_path(path_value: str) -> dict[str, Any]:
    unresolved = Path(path_value).expanduser()
    if unresolved.is_symlink():
        raise ContractError(
            f"artifact must be a regular non-symlink file: {unresolved}"
        )
    path = unresolved.resolve()
    if not path.is_file():
        raise ContractError(f"artifact must be a regular non-symlink file: {path}")
    payload = path.read_bytes()
    return {
        "path": str(path),
        "sha256": hashlib.sha256(payload).hexdigest(),
        "size": len(payload),
    }


def _load_bound_json_artifact(artifact: dict[str, Any]) -> Any | None:
    path = Path(artifact["path"])
    if path.is_symlink() or not path.is_file():
        raise ContractError(
            f"bound artifact is no longer a regular non-symlink file: {path}"
        )
    payload = path.read_bytes()
    if (
        len(payload) != artifact["size"]
        or hashlib.sha256(payload).hexdigest() != artifact["sha256"]
    ):
        raise ContractError(f"bound artifact content drifted: {path}")
    return _load_json_bytes(payload, path, label="bound artifact", allow_invalid=True)


def _topic_discovery_artifact_status(
    artifacts: list[dict[str, Any]],
) -> tuple[str, list[str]]:
    scholar = load_scholar_module()
    request_sets: dict[str, tuple[dict[str, Any], str]] = {}
    authorizations: dict[str, tuple[dict[str, Any], str]] = {}
    result_sets_by_request_set: dict[str, list[dict[str, Any]]] = {}
    for artifact in artifacts:
        payload = _load_bound_json_artifact(artifact)
        if not isinstance(payload, dict):
            continue
        schema = payload.get("schema")
        if schema in {
            scholar.REQUEST_SET_SCHEMA,
            scholar.APPRAISAL_REQUEST_SET_SCHEMA,
        }:
            try:
                request_set = scholar.validate_request_set(payload)
            except scholar.ContractError as exc:
                raise ContractError(
                    f"topic_discovery request-set artifact is invalid: {exc}"
                ) from exc
            request_set_id = request_set["request_set_id"]
            if request_set_id in request_sets:
                raise ContractError(
                    "topic_discovery request-set artifacts repeat an ID"
                )
            request_sets[request_set_id] = (request_set, artifact["sha256"])
        elif schema == scholar.SEARCH_EXECUTION_AUTHORIZATION_SCHEMA:
            authorization_id = payload.get("authorization_id")
            if not isinstance(authorization_id, str) or not authorization_id:
                raise ContractError(
                    "topic_discovery execution authorization has no authorization_id"
                )
            if authorization_id in authorizations:
                raise ContractError(
                    "topic_discovery execution authorization artifacts repeat an ID"
                )
            authorizations[authorization_id] = (payload, artifact["sha256"])
        elif schema == DISCOVERY_RESULT_SET_SCHEMA:
            request_set_id = payload.get("request_set_id")
            if not isinstance(request_set_id, str):
                raise ContractError("topic_discovery result-set artifact missing request_set_id")
            result_sets_by_request_set.setdefault(request_set_id, []).append(
                {
                    "record_type": "result_set",
                    "payload": payload,
                    "attempt": 0,
                }
            )
        elif schema == TOPIC_DISCOVERY_RESULT_SET_ATTEMPT_SCHEMA:
            if not isinstance(payload.get("request_set_id"), str) or not payload.get(
                "request_set_id"
            ):
                raise ContractError(
                    "ScholarDiscoveryResultSetAttempt/v1 missing request_set_id"
                )
            if payload.get("schema_version") != SCHEMA_VERSION:
                raise ContractError("ScholarDiscoveryResultSetAttempt/v1 schema_version is unsupported")
            attempt = payload.get("attempt")
            if not isinstance(attempt, int) or attempt <= 0:
                raise ContractError(
                    "ScholarDiscoveryResultSetAttempt/v1 attempt must be a positive integer"
                )
            supersedes_attempt = payload.get("supersedes_attempt")
            if supersedes_attempt is not None and (
                not isinstance(supersedes_attempt, int) or supersedes_attempt <= 0
            ):
                raise ContractError(
                    "ScholarDiscoveryResultSetAttempt/v1 supersedes_attempt must be null or a positive integer"
                )
            result_set = payload.get("result_set")
            if not isinstance(result_set, dict):
                raise ContractError(
                    "ScholarDiscoveryResultSetAttempt/v1 result_set must be an object"
                )
            result_sets_by_request_set.setdefault(payload["request_set_id"], []).append(
                {
                    "record_type": "attempt",
                    "payload": result_set,
                    "supersedes_attempt": supersedes_attempt,
                    "attempt": attempt,
                    "request_set_id": payload["request_set_id"],
                    "request_set_digest": require_string(
                        payload.get("request_set_digest"), "topic discovery attempt request_set_digest"
                    ),
                }
            )
        else:
            continue

    has_any_result_set = any(
        item["record_type"] == "result_set"
        for rows in result_sets_by_request_set.values()
        for item in rows
    )
    has_any_attempt = any(
        item["record_type"] == "attempt"
        for rows in result_sets_by_request_set.values()
        for item in rows
    )
    if not has_any_result_set and not has_any_attempt:
        raise ContractError(
            "terminal topic_discovery requires a validated "
            "ScholarDiscoveryResultSet/v2 artifact with its bound request set and "
            "execution authorization"
        )

    validated_by_request_set: dict[str, list[dict[str, Any]]] = {}

    def validate_result_record(
        request_set_id: str, payload: dict[str, Any], *, expected_request_set_digest: str | None = None
    ) -> dict[str, Any]:
        if request_set_id not in request_sets:
            raise ContractError(
                "ScholarDiscoveryResultSet/v2 requires its bound request-set artifact"
            )
        ref = payload.get("execution_authorization_ref")
        if not isinstance(ref, dict):
            raise ContractError(
                "ScholarDiscoveryResultSet/v2 requires execution_authorization_ref"
            )
        authorization_id = ref.get("authorization_id")
        if (
            not isinstance(authorization_id, str)
            or authorization_id not in authorizations
        ):
            raise ContractError(
                "ScholarDiscoveryResultSet/v2 requires its bound execution authorization artifact"
            )
        request_set, request_set_file_sha256 = request_sets[request_set_id]
        authorization, authorization_file_sha256 = authorizations[authorization_id]
        try:
            validated = scholar.validate_result_set(
                payload,
                request_set_value=request_set,
                execution_authority=authorization,
                expected_execution_authority_sha256=authorization_file_sha256,
                execution_authority_file_sha256=authorization_file_sha256,
                request_set_file_sha256=request_set_file_sha256,
            )
        except scholar.ContractError as exc:
            raise ContractError(
                f"topic_discovery result-set artifact is invalid: {exc}"
            ) from exc
        if (
            expected_request_set_digest is not None
            and validated["request_set_digest"] != expected_request_set_digest
        ):
            raise ContractError(
                "ScholarDiscoveryResultSetAttempt/v1 request_set_digest is invalid"
            )
        return validated

    for request_set_id, rows in sorted(result_sets_by_request_set.items()):
        has_plain = any(row["record_type"] == "result_set" for row in rows)
        has_attempts = any(row["record_type"] == "attempt" for row in rows)
        if has_plain and has_attempts:
            raise ContractError(
                "multiple result sets for one request_set_id require an "
                "explicit ScholarDiscoveryResultSetAttempt/v1 supersession contract"
            )
        if has_plain and len(rows) > 1:
            raise ContractError(
                "multiple result sets for one request_set_id require an "
                "explicit ScholarDiscoveryResultSetAttempt/v1 supersession contract"
            )
        if has_attempts:
            attempts: dict[int, dict[str, Any]] = {}
            for row in rows:
                attempt = row["attempt"]
                if attempt in attempts:
                    raise ContractError(
                        f"ScholarDiscoveryResultSetAttempt/v1 duplicate attempt for {request_set_id}"
                    )
                attempts[attempt] = row
            for row in rows:
                supersedes = row["supersedes_attempt"]
                attempt = row["attempt"]
                if supersedes is not None and supersedes not in attempts:
                    raise ContractError(
                        f"ScholarDiscoveryResultSetAttempt/v1 supersedes_attempt {supersedes} "
                        f"does not reference an attempt for {request_set_id}"
                    )
                if supersedes is not None and supersedes >= attempt:
                    raise ContractError(
                        f"ScholarDiscoveryResultSetAttempt/v1 supersedes_attempt for {request_set_id} "
                        "must be less than the attempt number"
                    )
            roots = [attempt for attempt, row in attempts.items() if row["supersedes_attempt"] is None]
            if len(roots) != 1:
                raise ContractError(
                    "ScholarDiscoveryResultSetAttempt/v1 requires a single chain root "
                    f"for {request_set_id}"
                )
            current = roots[0]
            visited = set[int]()
            for _ in range(len(attempts)):
                if current in visited:
                    raise ContractError(
                        f"ScholarDiscoveryResultSetAttempt/v1 chain for {request_set_id} contains a cycle"
                    )
                visited.add(current)
                children = [
                    attempt for attempt, row in attempts.items() if row["supersedes_attempt"] == current
                ]
                if not children:
                    break
                if len(children) != 1:
                    raise ContractError(
                        f"ScholarDiscoveryResultSetAttempt/v1 requires a linear supersession chain for {request_set_id}"
                    )
                current = children[0]
            if len(visited) != len(attempts):
                raise ContractError(
                    f"ScholarDiscoveryResultSetAttempt/v1 chain for {request_set_id} is incomplete"
                )
            validated_attempts: list[dict[str, Any]] = []
            for attempt in sorted(attempts):
                row = attempts[attempt]
                payload = row["payload"]
                validated = validate_result_record(
                    request_set_id,
                    payload,
                    expected_request_set_digest=row["request_set_digest"],
                )
                validated_attempts.append(validated)
            validated_by_request_set[request_set_id] = validated_attempts
        else:
            row = rows[0]
            payload = row["payload"]
            validated = validate_result_record(request_set_id, payload)
            validated_by_request_set[request_set_id] = [validated]

    if not validated_by_request_set:
        raise ContractError(
            "terminal topic_discovery requires a validated "
            "ScholarDiscoveryResultSet/v2 artifact with its bound request set and "
            "execution authorization"
        )

    limitations: list[str] = []
    for request_set_id, result_sets in sorted(validated_by_request_set.items()):
        for result_set in result_sets:
            failures = result_set.get("failures", [])
            if failures:
                limitations.append(f"{request_set_id}:request_failures")
            results = result_set["results"]
            if not results:
                limitations.append(f"{request_set_id}:no_results")
            for result in results:
                discovery_status = result["discovery_status"]
                if discovery_status != DISCOVERY_COMPLETE_STATUS:
                    limitations.append(
                        f"{request_set_id}:{result['request_id']}:{discovery_status}"
                    )
    return ("partial" if limitations else "completed"), limitations


def load_appraisal_module():
    path = (
        Path(__file__).resolve().parents[2]
        / "evidence-appraisal"
        / "scripts"
        / "evidence_appraisal.py"
    )
    name = "pipeline_evidence_appraisal_owner"
    existing = sys.modules.get(name)
    if existing is not None:
        return existing
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ContractError(f"cannot load evidence-appraisal owner: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def load_research_network_publish_module():
    path = (
        Path(__file__).resolve().parents[2]
        / "research-network-publish"
        / "scripts"
        / "render_network_html.py"
    )
    name = "pipeline_research_network_publish"
    existing = sys.modules.get(name)
    if existing is not None:
        return existing
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ContractError(f"cannot load research-network-publish owner: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _binding_digest_universe(value: Any) -> frozenset[str] | None:
    """Return one exact, unordered binding-digest universe or ``None``.

    The owner validates each artifact's complete structure.  This pre-screen
    only establishes that a detached owner bundle has the same non-duplicated
    binding universe as the package, without treating its runtime entry order
    as semantic.
    """
    if not isinstance(value, list) or not value:
        return None
    if any(
        not isinstance(digest, str) or not SHA256_RE.fullmatch(digest)
        for digest in value
    ):
        return None
    if len(value) != len(set(value)):
        return None
    return frozenset(value)


def _owner_bundle_binding_universe(value: Any) -> frozenset[str] | None:
    if not isinstance(value, dict) or not isinstance(value.get("artifacts"), list):
        return None
    return _binding_digest_universe(
        [
            artifact.get("binding_digest") if isinstance(artifact, dict) else None
            for artifact in value["artifacts"]
        ]
    )


def _owner_bundle_matches_binding_universe(
    owner_bundle: Any, expected_universe: frozenset[str] | None
) -> bool:
    return (
        expected_universe is not None
        and _owner_bundle_binding_universe(owner_bundle) == expected_universe
    )


def _validate_evidence_appraisal_artifacts(
    artifacts: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    owner = load_appraisal_module()
    payloads = [_load_bound_json_artifact(artifact) for artifact in artifacts]
    packages = [
        item
        for item in payloads
        if isinstance(item, dict)
        and item.get("schema") == "EvidenceAppraisalPackage/v1"
    ]
    approvals = [
        item
        for item in payloads
        if isinstance(item, dict)
        and item.get("schema") == "ReviewedEvidenceAppraisalAuthority/v1"
    ]
    preparations = [
        item
        for item in payloads
        if isinstance(item, dict)
        and item.get("schema") == "EvidenceAppraisalPreparation/v1"
    ]
    reviews = [
        item
        for item in payloads
        if isinstance(item, dict)
        and item.get("schema") == "EvidenceAppraisalIndependentReview/v1"
    ]
    owner_bundles = [
        item
        for item in payloads
        if isinstance(item, dict)
        and item.get("schema") == "EvidenceAppraisalOwnerBundle/v1"
    ]
    lineage_sets = [
        item
        for item in payloads
        if isinstance(item, dict) and item.get("schema") == "EvidenceAppraisalSet/v1"
    ]
    authority_expectations = [
        item
        for item in payloads
        if isinstance(item, dict)
        and item.get("schema") == "EvidenceAppraisalAuthorityExpectation/v1"
    ]
    if not packages:
        raise ContractError(
            "terminal evidence_appraisal requires an owner-replayable "
            "EvidenceAppraisalPackage/v1; a candidate set alone is not finalized"
        )
    validated_packages: list[dict[str, Any]] = []
    for package in packages:
        approval_ref = package.get("approval_ref")
        matching_approvals = [
            item
            for item in approvals
            if isinstance(approval_ref, dict)
            and {
                "authority_id": item.get("authority_id"),
                "authority_digest": item.get("authority_digest"),
            }
            == approval_ref
        ]
        if len(matching_approvals) != 1:
            raise ContractError(
                "evidence_appraisal package requires one exact detached approval"
            )
        approval = matching_approvals[0]
        matching_expectations = [
            item
            for item in authority_expectations
            if set(item) == {"schema", "expected_authority_sha256"}
            and item.get("expected_authority_sha256")
            == approval.get("authority_digest")
        ]
        if len(matching_expectations) != 1:
            raise ContractError(
                "evidence_appraisal package requires one externally supplied "
                "authority SHA-256 expectation"
            )
        expected_authority_sha256 = matching_expectations[0][
            "expected_authority_sha256"
        ]
        if not isinstance(expected_authority_sha256, str) or not SHA256_RE.fullmatch(
            expected_authority_sha256
        ):
            raise ContractError("evidence_appraisal authority expectation is invalid")
        matching_preparations = [
            item
            for item in preparations
            if item.get("request_digest") == approval.get("prepared_request_digest")
            and item.get("prepared_request_file_sha256")
            == approval.get("prepared_request_file_sha256")
        ]
        if len(matching_preparations) != 1:
            raise ContractError(
                "evidence_appraisal package requires one exact prepared request"
            )
        prepared = matching_preparations[0]
        matching_reviews = [
            item
            for item in reviews
            if item.get("prepared_request_digest") == prepared.get("request_digest")
            and item.get("prepared_request_file_sha256")
            == prepared.get("prepared_request_file_sha256")
            and item.get("independent_review_digest")
            == approval.get("independent_review_digest")
            and item.get("independent_review_file_sha256")
            == approval.get("independent_review_file_sha256")
        ]
        if len(matching_reviews) != 1:
            raise ContractError(
                "evidence_appraisal package requires one exact independent review"
            )
        appraisal_set = package.get("appraisal_set")
        if not isinstance(appraisal_set, dict):
            raise ContractError("evidence_appraisal package appraisal_set is invalid")
        package_binding_universe = _binding_digest_universe(
            package.get("owner_artifact_binding_digests")
        )
        matching_owner_bundles = [
            item
            for item in owner_bundles
            if _owner_bundle_matches_binding_universe(item, package_binding_universe)
        ]
        if len(matching_owner_bundles) != 1:
            raise ContractError(
                "evidence_appraisal package requires one exact owner artifact bundle"
            )
        lineage = sorted(
            (
                item
                for item in lineage_sets
                if item.get("appraisal_set_id") == appraisal_set.get("appraisal_set_id")
                and isinstance(item.get("cycle"), int)
                and isinstance(appraisal_set.get("cycle"), int)
                and item["cycle"] < appraisal_set["cycle"]
            ),
            key=lambda item: item["cycle"],
        )
        try:
            validated_packages.append(
                owner.validate_appraisal_package(
                    package,
                    approval,
                    prepared,
                    matching_reviews[0],
                    matching_owner_bundles[0],
                    expected_authority_sha256=expected_authority_sha256,
                    lineage=lineage,
                )
            )
        except owner.ContractError as exc:
            raise ContractError(
                f"evidence_appraisal owner package replay failed: {exc}"
            ) from exc
    identities = [item["package_digest"] for item in validated_packages]
    if len(identities) != len(set(identities)):
        raise ContractError("evidence_appraisal contains duplicate finalized packages")
    return validated_packages


def _load_publication_input_file(
    value: Any,
    label: str,
    *,
    require_content_sha256: bool,
) -> tuple[dict[str, Any], Path, bytes]:
    ref = require_dict(value, label)
    path = Path(require_string(ref.get("path"), f"{label}.path")).expanduser().resolve()
    if path.is_symlink():
        raise ContractError(f"{label}.path must be a regular file: {path}")
    if not path.is_file():
        raise ContractError(f"{label}.path must point to a regular file: {path}")
    size = ref.get("size")
    if isinstance(size, bool) or not isinstance(size, int) or size < 0:
        raise ContractError(f"{label}.size must be a nonnegative integer")
    sha = require_string(ref.get("sha256"), f"{label}.sha256")
    if not SHA256_RE.fullmatch(sha):
        raise ContractError(f"{label}.sha256 must be a 64-character lowercase SHA-256")
    data = path.read_bytes()
    if len(data) != size:
        raise ContractError(f"{label}.size does not match file content: {path}")
    if hashlib.sha256(data).hexdigest() != sha:
        raise ContractError(f"{label}.sha256 does not match file content: {path}")
    payload = dict(ref)
    if require_content_sha256:
        content_sha256 = require_string(ref.get("content_sha256"), f"{label}.content_sha256")
        if not SHA256_RE.fullmatch(content_sha256):
            raise ContractError(f"{label}.content_sha256 must be a 64-character lowercase SHA-256")
        payload["content_sha256"] = content_sha256
    return payload, path, data


def _load_publication_json_payload(
    payload: Any, label: str, *, require_content_sha256: bool = True
) -> tuple[dict[str, Any], Path]:
    reference, path, raw = _load_publication_input_file(
        payload,
        label,
        require_content_sha256=require_content_sha256,
    )
    document = _load_json_bytes(
        raw,
        path,
        label=f"{label} payload",
        allow_invalid=False,
    )
    if not isinstance(document, dict):
        raise ContractError(f"{label} top-level payload must be an object: {path}")
    if require_content_sha256:
        canonical = copy.deepcopy(document)
        payload_content_sha256 = canonical.pop("content_sha256", None)
        if (
            not isinstance(payload_content_sha256, str)
            or not SHA256_RE.fullmatch(payload_content_sha256)
        ):
            raise ContractError(f"{label}.content_sha256 is invalid")
        if payload_content_sha256 != reference["content_sha256"]:
            raise ContractError(f"{label}.content_sha256 mismatch: {path}")
        if hashlib.sha256(canonical_bytes(canonical)).hexdigest() != payload_content_sha256:
            raise ContractError(f"{label}.content_sha256 mismatch: {path}")
    return document, path


def _validate_network_publish_artifacts(
    artifacts: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    publisher = load_research_network_publish_module()
    payloads = [_load_bound_json_artifact(artifact) for artifact in artifacts]
    evidences = [
        item
        for item in payloads
        if isinstance(item, dict) and item.get("schema") == NETWORK_PUBLISH_EVIDENCE_SCHEMA
    ]
    if not evidences:
        raise ContractError(
            "terminal network_publish requires a validated "
            "ResearchNetworkPublishEvidence/v1 artifact with replayable public HTML"
        )
    if len(evidences) != 1:
        raise ContractError(
            "network_publish expects exactly one ResearchNetworkPublishEvidence/v1 artifact"
        )
    evidence = evidences[0]
    if evidence.get("schema_version") != SCHEMA_VERSION:
        raise ContractError("ResearchNetworkPublishEvidence/v1 schema_version is unsupported")
    if evidence.get("mode") != publisher.PUBLIC_MODE:
        raise ContractError("ResearchNetworkPublishEvidence/v1 mode must be public-redacted")
    _ = require_timestamp(
        evidence.get("generated_at"), "ResearchNetworkPublishEvidence/v1.generated_at"
    )

    network_ref = require_dict(
        evidence.get("network"), "ResearchNetworkPublishEvidence/v1.network"
    )
    if set(network_ref) != {
        "path",
        "sha256",
        "size",
        "content_sha256",
        "network_id",
        "snapshot_id",
    }:
        raise ContractError("ResearchNetworkPublishEvidence/v1.network has invalid keys")
    network_payload, _ = _load_publication_json_payload(
        network_ref,
        "ResearchNetworkPublishEvidence/v1.network",
        require_content_sha256=True,
    )
    if network_payload.get("schema") != "KnowledgeNetwork/v1":
        raise ContractError(
            "ResearchNetworkPublishEvidence/v1.network must be a KnowledgeNetwork/v1"
        )
    if (
        network_ref["network_id"] != network_payload["network_id"]
        or network_ref["snapshot_id"] != network_payload["snapshot_id"]
        or network_ref["content_sha256"] != network_payload["content_sha256"]
    ):
        raise ContractError(
            "ResearchNetworkPublishEvidence/v1.network binding metadata does not match loaded network"
        )

    research_map_payload: dict[str, Any] | None = None
    research_map_ref = evidence.get("research_map")
    if research_map_ref is not None:
        research_map_ref_payload = require_dict(
            research_map_ref, "ResearchNetworkPublishEvidence/v1.research_map"
        )
        if set(research_map_ref_payload) != {
            "path",
            "sha256",
            "size",
            "content_sha256",
            "network_snapshot_id",
        }:
            raise ContractError("ResearchNetworkPublishEvidence/v1.research_map has invalid keys")
        research_map_payload, _ = _load_publication_json_payload(
            research_map_ref_payload,
            "ResearchNetworkPublishEvidence/v1.research_map",
            require_content_sha256=True,
        )
        if (
            research_map_payload.get("network_snapshot_id")
            != network_payload["snapshot_id"]
        ):
            raise ContractError(
                "ResearchNetworkPublishEvidence/v1.research_map network_snapshot_id does not match network"
            )
        if research_map_ref_payload["content_sha256"] != sha256_json(
            {
                key: item
                for key, item in research_map_payload.items()
                if key not in {"content_sha256"}
            }
        ):
            if sha256_json(
                {
                    key: item
                    for key, item in research_map_payload.items()
                    if key not in {"content_sha256"}
                }
            ) != research_map_ref_payload["content_sha256"]:
                raise ContractError(
                    "ResearchNetworkPublishEvidence/v1.research_map.content_sha256 is invalid"
                )

    publication_ref = require_dict(
        evidence.get("publication_html"),
        "ResearchNetworkPublishEvidence/v1.publication_html",
    )
    if set(publication_ref) != {
        "path",
        "sha256",
        "size",
        "rendered_document_sha256",
    }:
        raise ContractError("ResearchNetworkPublishEvidence/v1.publication_html has invalid keys")
    publication_path = Path(
        require_string(
            publication_ref.get("path"),
            "ResearchNetworkPublishEvidence/v1.publication_html.path",
        )
    ).expanduser()
    if publication_path.is_symlink() or not publication_path.is_file():
        raise ContractError(
            "ResearchNetworkPublishEvidence/v1.publication_html.path must be a regular file"
        )
    publication_size = publication_ref.get("size")
    if isinstance(publication_size, bool) or not isinstance(publication_size, int):
        raise ContractError(
            "ResearchNetworkPublishEvidence/v1.publication_html.size must be a nonnegative integer"
        )
    if publication_size < 0:
        raise ContractError(
            "ResearchNetworkPublishEvidence/v1.publication_html.size must be nonnegative"
        )
    publication_html_sha256 = require_string(
        publication_ref.get("sha256"),
        "ResearchNetworkPublishEvidence/v1.publication_html.sha256",
    )
    if not SHA256_RE.fullmatch(publication_html_sha256):
        raise ContractError(
            "ResearchNetworkPublishEvidence/v1.publication_html.sha256 is invalid"
        )
    publication_rendered_sha256 = require_string(
        publication_ref.get("rendered_document_sha256"),
        "ResearchNetworkPublishEvidence/v1.publication_html.rendered_document_sha256",
    )
    if not SHA256_RE.fullmatch(publication_rendered_sha256):
        raise ContractError(
            "ResearchNetworkPublishEvidence/v1.publication_html.rendered_document_sha256 is invalid"
        )
    publication_document = publication_path.read_bytes()
    if len(publication_document) != publication_size:
        raise ContractError(
            "ResearchNetworkPublishEvidence/v1.publication_html.size does not match file content"
        )
    if hashlib.sha256(publication_document).hexdigest() != publication_html_sha256:
        raise ContractError(
            "ResearchNetworkPublishEvidence/v1.publication_html.sha256 does not match file content"
        )
    if publication_html_sha256 != publication_rendered_sha256:
        raise ContractError(
            "ResearchNetworkPublishEvidence/v1.publication_html hashes are inconsistent"
        )

    try:
        publisher.validate_inputs(network_payload, research_map_payload)
        projection = publisher.build_projection(
            network_payload, research_map_payload, publisher.PUBLIC_MODE
        )
        rendered = publisher.render_document(projection)
        publisher.assert_output_privacy(rendered, publisher.PUBLIC_MODE)
        if hashlib.sha256(rendered.encode("utf-8")).hexdigest() != publication_rendered_sha256:
            raise ContractError(
                "ResearchNetworkPublishEvidence/v1 publication_html rendered_document_sha256 is incorrect"
            )
    except publisher.ContractError as exc:
        raise ContractError(f"network_publish owner replay failed: {exc}") from exc
    if publication_document != rendered.encode("utf-8"):
        raise ContractError(
            "ResearchNetworkPublishEvidence/v1 publication_html does not match owner-rendered output"
        )
    return [evidence]


def _validate_pipeline_stage_coverage(execution: dict[str, Any]) -> None:
    by_id = {item["stage_id"]: item for item in execution["stages"]}
    topic_discovery = by_id.get("topic_discovery")
    if topic_discovery is not None:
        if (
            topic_discovery["status"] in TERMINAL_STAGE_STATUSES
            and topic_discovery["artifacts"]
        ):
            artifact_status, limitations = _topic_discovery_artifact_status(
                topic_discovery["artifacts"]
            )
            if (
                topic_discovery["status"] in {"completed", "partial"}
                and topic_discovery["status"] != artifact_status
            ):
                detail = (
                    ", ".join(limitations)
                    if limitations
                    else "all bounded routes complete"
                )
                raise ContractError(
                    "topic_discovery stage status does not match provider/route coverage: "
                    f"record --status {artifact_status}; {detail}"
                )
    evidence_appraisal = by_id.get("evidence_appraisal")
    if (
        evidence_appraisal is not None
        and evidence_appraisal["status"] in {"completed", "partial", "blocked"}
        and evidence_appraisal["artifacts"]
    ):
        _validate_evidence_appraisal_artifacts(evidence_appraisal["artifacts"])
    network_publish = by_id.get("network_publish")
    if (
        network_publish is not None
        and network_publish["status"] in {"completed", "partial", "blocked"}
        and network_publish["artifacts"]
    ):
        _validate_network_publish_artifacts(network_publish["artifacts"])


def _validate_current_stage_artifacts(execution: dict[str, Any]) -> None:
    _validate_pipeline_stage_coverage(execution)


def migrate_legacy_execution(
    value: Any, *, as_of: str, inserted_status: str = "pending"
) -> dict[str, Any]:
    raw = require_dict(value, "migration input")
    raw_stages = raw.get("stages")
    raw_stage_ids = (
        [stage.get("stage_id") for stage in raw_stages if isinstance(stage, dict)]
        if isinstance(raw_stages, list)
        else []
    )
    if raw_stage_ids == list(PRE_APPRAISAL_STAGES):
        prior = validate_pre_appraisal_execution(raw)
        timestamp = require_timestamp(as_of, "as_of")
        if datetime.fromisoformat(
            timestamp.replace("Z", "+00:00")
        ) < datetime.fromisoformat(prior["updated_at"].replace("Z", "+00:00")):
            raise ContractError(
                "migration timestamp cannot precede execution updated_at"
            )
        if inserted_status not in {"pending", "blocked"}:
            raise ContractError("inserted migration status must be pending or blocked")
        verified_artifacts = []
        for stage in prior["stages"]:
            for artifact in stage["artifacts"]:
                live = artifact_from_path(artifact["path"])
                if live != artifact:
                    raise ContractError(
                        f"pre-appraisal artifact binding drifted: {artifact['path']}"
                    )
                verified_artifacts.append(live)
        migrated = copy.deepcopy(prior)
        migrated["updated_at"] = timestamp
        appraisal_stage = {
            "stage_id": "evidence_appraisal",
            "status": inserted_status,
            "dependencies": ["paper_understanding"],
            "artifacts": [],
            "reason": "finalized evidence appraisal required before network merge",
            "updated_at": timestamp,
        }
        migrated["stages"].insert(6, appraisal_stage)
        network_merge = next(
            stage
            for stage in migrated["stages"]
            if stage["stage_id"] == "network_merge"
        )
        network_merge["dependencies"] = ["evidence_appraisal"]
        migration = {
            "schema": "ResearchPipelineMigration/v2",
            "schema_version": SCHEMA_VERSION,
            "migration_id": "",
            "migration_digest": "",
            "source_execution_id": prior["execution_id"],
            "source_state_digest": prior["state_digest"],
            "source_stage_ids": list(PRE_APPRAISAL_STAGES),
            "target_stage_ids": list(STAGES),
            "preserved_stages_digest": sha256_json(prior["stages"]),
            "preserved_history_digest": sha256_json(prior["history"]),
            "verified_artifacts": verified_artifacts,
            "inserted_stage_id": "evidence_appraisal",
            "inserted_stage_status": inserted_status,
            "reason": "finalized evidence appraisal required before network merge",
            "migrated_at": timestamp,
        }
        digest = migration_digest(migration)
        migration["migration_digest"] = digest
        migration["migration_id"] = f"pipeline-migration-{digest[:16]}"
        migrated["migration_provenance"] = [
            *migrated.get("migration_provenance", []),
            migration,
        ]
        migrated["state_digest"] = execution_digest(migrated)
        return validate_execution(migrated)
    legacy = validate_legacy_execution(value)
    timestamp = require_timestamp(as_of, "as_of")
    if datetime.fromisoformat(
        timestamp.replace("Z", "+00:00")
    ) < datetime.fromisoformat(legacy["updated_at"].replace("Z", "+00:00")):
        raise ContractError("migration timestamp cannot precede legacy updated_at")
    if inserted_status not in {"pending", "blocked"}:
        raise ContractError("inserted migration status must be pending or blocked")
    verified_artifacts = []
    for stage in legacy["stages"]:
        for artifact in stage["artifacts"]:
            live = artifact_from_path(artifact["path"])
            if live != artifact:
                raise ContractError(
                    f"legacy artifact binding drifted: {artifact['path']}"
                )
            verified_artifacts.append(live)
    migrated = copy.deepcopy(legacy)
    migrated["updated_at"] = timestamp
    normalization_stage = {
        "stage_id": "source_normalization",
        "status": inserted_status,
        "dependencies": ["source_acquisition"],
        "artifacts": [],
        "reason": "normalization evidence required",
        "updated_at": timestamp,
    }
    migrated["stages"].insert(4, normalization_stage)
    understanding = next(
        stage
        for stage in migrated["stages"]
        if stage["stage_id"] == "paper_understanding"
    )
    understanding["dependencies"] = ["source_acquisition", "source_normalization"]
    migration = {
        "schema": "ResearchPipelineMigration/v1",
        "schema_version": SCHEMA_VERSION,
        "migration_id": "",
        "migration_digest": "",
        "source_execution_id": legacy["execution_id"],
        "source_state_digest": legacy["state_digest"],
        "source_stage_ids": list(LEGACY_STAGES),
        "target_stage_ids": list(PRE_APPRAISAL_STAGES),
        "preserved_stages_digest": sha256_json(legacy["stages"]),
        "preserved_history_digest": sha256_json(legacy["history"]),
        "verified_artifacts": verified_artifacts,
        "inserted_stage_id": "source_normalization",
        "inserted_stage_status": inserted_status,
        "reason": "normalization evidence required",
        "migrated_at": timestamp,
    }
    digest = migration_digest(migration)
    migration["migration_digest"] = digest
    migration["migration_id"] = f"pipeline-migration-{digest[:16]}"
    migrated["migration_provenance"] = [migration]
    migrated["state_digest"] = execution_digest(migrated)
    return validate_execution(migrated)


def record_stage(
    execution_value: Any,
    *,
    stage_id: str,
    status: str,
    artifact_paths: list[str],
    reason: str | None,
    as_of: str,
) -> dict[str, Any]:
    execution = validate_execution(execution_value)
    timestamp = require_timestamp(as_of, "as_of")
    if stage_id not in STAGES:
        raise ContractError(f"unknown pipeline stage: {stage_id}")
    if stage_id not in {item["stage_id"] for item in execution["stages"]}:
        raise MigrationRequired(execution["state_digest"])
    if status not in STATUSES - {"pending"}:
        raise ContractError(
            "recorded status must be running, completed, partial, or blocked"
        )
    stage = next(item for item in execution["stages"] if item["stage_id"] == stage_id)
    if status not in TRANSITIONS[stage["status"]]:
        raise ContractError(f"invalid stage transition {stage['status']} -> {status}")
    by_id = {item["stage_id"]: item for item in execution["stages"]}
    if status in {"running", "completed", "partial"}:
        incomplete = [
            dependency
            for dependency in stage["dependencies"]
            if by_id[dependency]["status"] not in USABLE_DEPENDENCY_STATUSES
        ]
        if incomplete:
            raise ContractError(
                f"stage {stage_id} has incomplete dependencies: {', '.join(incomplete)}"
            )
    artifacts = [artifact_from_path(path) for path in artifact_paths]
    if status in {"completed", "partial"} and not (stage["artifacts"] or artifacts):
        raise ContractError(f"{status} stage requires at least one artifact")
    execution = copy.deepcopy(execution)
    stage = next(item for item in execution["stages"] if item["stage_id"] == stage_id)
    stage_artifacts = stage["artifacts"]
    for artifact in artifacts:
        if artifact not in stage_artifacts:
            stage_artifacts.append(artifact)
    stage["status"] = status
    stage["reason"] = reason
    stage["updated_at"] = timestamp
    execution["updated_at"] = timestamp
    _validate_current_stage_artifacts(execution)
    execution["history"].append(
        {
            "stage_id": stage_id,
            "status": status,
            "artifact_sha256": [artifact["sha256"] for artifact in artifacts],
            "reason": reason,
            "recorded_at": timestamp,
        }
    )
    execution["state_digest"] = execution_digest(execution)
    validated = validate_execution(execution)
    return validated


def pipeline_status(value: Any) -> dict[str, Any]:
    execution = validate_execution(value)
    _validate_current_stage_artifacts(execution)
    by_id = {stage["stage_id"]: stage for stage in execution["stages"]}
    appraisal_stage = by_id.get("evidence_appraisal")
    appraisal_terminal = (
        appraisal_stage is not None
        and appraisal_stage["status"] in TERMINAL_STAGE_STATUSES
    )
    ready = []
    for stage in execution["stages"]:
        if stage["status"] not in {"pending", "partial", "blocked"}:
            continue
        if all(
            by_id[dependency]["status"] in USABLE_DEPENDENCY_STATUSES
            for dependency in stage["dependencies"]
        ):
            ready.append(stage["stage_id"])
    stages_terminal = appraisal_terminal and all(
        stage["status"] in TERMINAL_STAGE_STATUSES for stage in execution["stages"]
    )
    coverage_complete = appraisal_stage is not None and all(
        stage["status"] == "completed" for stage in execution["stages"]
    )
    return {
        "execution_id": execution["execution_id"],
        "state_digest": execution["state_digest"],
        "ready_stages": ready,
        "active_stages": [
            stage["stage_id"]
            for stage in execution["stages"]
            if stage["status"] == "running"
        ],
        "blocked_stages": [
            stage["stage_id"]
            for stage in execution["stages"]
            if stage["status"] == "blocked"
        ],
        "partial_stages": [
            stage["stage_id"]
            for stage in execution["stages"]
            if stage["status"] == "partial"
        ],
        "completed_stage_count": sum(
            stage["status"] == "completed" for stage in execution["stages"]
        ),
        "terminal_stage_count": sum(
            stage["status"] in TERMINAL_STAGE_STATUSES for stage in execution["stages"]
        ),
        "stage_actions_terminal": stages_terminal,
        "evidence_appraisal_status": (
            appraisal_stage["status"]
            if appraisal_stage is not None
            else "not_recorded_legacy"
        ),
        "evidence_appraisal_terminal": appraisal_terminal,
        "migration_required": (
            [] if appraisal_stage is not None else ["evidence_appraisal"]
        ),
        "coverage_complete": coverage_complete,
        "can_finalize_complete": stages_terminal and coverage_complete,
        "can_finalize_partial": stages_terminal and not coverage_complete,
        "can_publish": appraisal_terminal
        and by_id["gap_cycle"]["status"] in USABLE_DEPENDENCY_STATUSES,
        "outcome": (
            "complete"
            if coverage_complete
            else "partial"
            if stages_terminal
            else "running"
        ),
        "complete": coverage_complete,
    }


def load_scholar_module():
    path = (
        Path(__file__).resolve().parents[2]
        / "scholar-discovery"
        / "scripts"
        / "scholar_discovery.py"
    )
    spec = importlib.util.spec_from_file_location("pipeline_scholar_discovery", path)
    if spec is None or spec.loader is None:
        raise ContractError(f"cannot load scholar-discovery module: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def compile_topic_requests(
    scenario_value: Any,
    network_value: Any,
    *,
    as_of: str,
) -> dict[str, Any]:
    scenario = validate_scenario(scenario_value)
    network = require_dict(network_value, "network")
    if network.get("schema") != "KnowledgeNetwork/v1":
        raise ContractError("network.schema must equal KnowledgeNetwork/v1")
    network_id = require_string(network.get("network_id"), "network.network_id")
    snapshot_id = require_string(network.get("snapshot_id"), "network.snapshot_id")
    content_sha256 = require_string(
        network.get("content_sha256"), "network.content_sha256"
    )
    if not SHA256_RE.fullmatch(content_sha256):
        raise ContractError("network.content_sha256 is invalid")
    timestamp = require_timestamp(as_of, "as_of")
    topic_need_set = {
        "schema": "ResearchTopicNeedSet/v1",
        "schema_version": SCHEMA_VERSION,
        "topic_id": scenario["scenario_id"],
        "question": scenario["question"],
        "as_of": timestamp,
        "google_scholar_policy": scenario["google_scholar_policy"],
        "automatic_providers": scenario["automatic_providers"],
        "network_ref": {
            "network_id": network_id,
            "snapshot_id": snapshot_id,
            "sha256": content_sha256,
        },
        "needs": copy.deepcopy(scenario["topic_needs"]),
    }
    scholar = load_scholar_module()
    try:
        return scholar.compile_topic_need_set(topic_need_set)
    except scholar.ContractError as exc:
        raise ContractError(str(exc)) from exc


def load_json(path_value: str) -> Any:
    path = Path(path_value)
    if path.is_symlink() or not path.is_file():
        raise ContractError(f"input must be a regular non-symlink file: {path}")
    return _load_json_bytes(
        path.read_bytes(),
        path,
        label="input",
        allow_invalid=False,
    )


def write_json_exclusive(path_value: str, value: Any) -> None:
    path = Path(path_value)
    if path.exists() or path.is_symlink():
        raise ContractError(f"refusing to overwrite output: {path}")
    if path.parent.is_symlink():
        raise ContractError(f"refusing symlink output parent: {path.parent}")
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    payload = canonical_bytes(value) + b"\n"
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    flags |= getattr(os, "O_NOFOLLOW", 0)
    descriptor = -1
    created = False
    try:
        descriptor = os.open(path, flags, 0o600)
        created = True
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "wb") as handle:
            descriptor = -1
            handle.write(payload)
    except FileExistsError as exc:
        raise ContractError(f"refusing to overwrite output: {path}") from exc
    except BaseException:
        if descriptor >= 0:
            os.close(descriptor)
        if created:
            path.unlink(missing_ok=True)
        raise


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description=__doc__)
    subcommands = root.add_subparsers(dest="command", required=True)
    init = subcommands.add_parser("init")
    init.add_argument("--scenario", required=True)
    init.add_argument("--as-of", required=True)
    init.add_argument("--output", required=True)
    compile_topic = subcommands.add_parser("compile-topic")
    compile_topic.add_argument("--scenario", required=True)
    compile_topic.add_argument("--network", required=True)
    compile_topic.add_argument("--as-of", required=True)
    compile_topic.add_argument("--output", required=True)
    record = subcommands.add_parser("record-stage")
    record.add_argument("--execution", required=True)
    record.add_argument("--stage", choices=STAGES, required=True)
    record.add_argument(
        "--status", choices=sorted(STATUSES - {"pending"}), required=True
    )
    record.add_argument("--artifact", action="append", default=[])
    record.add_argument("--reason")
    record.add_argument("--as-of", required=True)
    record.add_argument("--output", required=True)
    status = subcommands.add_parser("status")
    status.add_argument("--execution", required=True)
    migrate = subcommands.add_parser("migrate")
    migrate.add_argument("--input", required=True)
    migrate.add_argument("--as-of", required=True)
    migrate.add_argument(
        "--inserted-status", choices=("pending", "blocked"), default="pending"
    )
    migrate.add_argument("--output", required=True)
    validate = subcommands.add_parser("validate")
    validate.add_argument("--input", required=True)
    return root


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        if args.command == "init":
            write_json_exclusive(
                args.output,
                initialize_execution(load_json(args.scenario), as_of=args.as_of),
            )
        elif args.command == "compile-topic":
            write_json_exclusive(
                args.output,
                compile_topic_requests(
                    load_json(args.scenario),
                    load_json(args.network),
                    as_of=args.as_of,
                ),
            )
        elif args.command == "record-stage":
            write_json_exclusive(
                args.output,
                record_stage(
                    load_json(args.execution),
                    stage_id=args.stage,
                    status=args.status,
                    artifact_paths=args.artifact,
                    reason=args.reason,
                    as_of=args.as_of,
                ),
            )
        elif args.command == "status":
            print(
                json.dumps(pipeline_status(load_json(args.execution)), sort_keys=True)
            )
        elif args.command == "migrate":
            write_json_exclusive(
                args.output,
                migrate_legacy_execution(
                    load_json(args.input),
                    as_of=args.as_of,
                    inserted_status=args.inserted_status,
                ),
            )
        else:
            value = load_json(args.input)
            schema = value.get("schema") if isinstance(value, dict) else None
            if schema == SCENARIO_SCHEMA:
                validated = validate_scenario(value)
            elif schema == EXECUTION_SCHEMA:
                pipeline_status(value)
                validated = validate_execution(value)
            else:
                raise ContractError(f"unsupported schema: {schema!r}")
            print(
                json.dumps(
                    {"valid": True, "schema": validated["schema"]}, sort_keys=True
                )
            )
        return 0
    except MigrationRequired as exc:
        print(
            json.dumps(
                {
                    "schema": "ResearchPipelineDiagnostic/v1",
                    "code": "migration_required",
                    "legacy_state_digest": exc.state_digest,
                    "message": str(exc),
                    "recommended_command": "migrate",
                },
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 2
    except (ContractError, json.JSONDecodeError, OSError) as exc:
        print(f"research-pipeline validation failed: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
