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
STAGES = (
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
DEPENDENCIES = {
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
TRANSITIONS = {
    "pending": {"running", "completed", "blocked"},
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
                raise ContractError(f"{label} contains forbidden credential field {key!r}")
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

    target = copy.deepcopy(require_dict(scenario.get("zotero_target"), "scenario.zotero_target"))
    group_id = target.get("group_id")
    if isinstance(group_id, bool) or not isinstance(group_id, int) or group_id <= 0:
        raise ContractError("scenario.zotero_target.group_id must be a positive integer")
    target["library_name"] = require_string(
        target.get("library_name"), "scenario.zotero_target.library_name"
    )
    collection_key = require_string(
        target.get("collection_key"), "scenario.zotero_target.collection_key"
    )
    if not COLLECTION_KEY_RE.fullmatch(collection_key):
        raise ContractError("scenario.zotero_target.collection_key must be 8 uppercase alphanumerics")
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
        gap_id = require_string(need.get("gap_id"), f"scenario.topic_needs[{index}].gap_id")
        if gap_id in gap_ids:
            raise ContractError(f"duplicate scenario topic gap_id: {gap_id}")
        if gap_id.startswith("derived:missing-dimension:"):
            raise ContractError("structural missing-dimension gaps need semantic topic definitions")
        gap_ids.add(gap_id)
    return scenario


def execution_digest(value: dict[str, Any]) -> str:
    return sha256_json({key: item for key, item in value.items() if key != "state_digest"})


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
        if stage.get("dependencies") != list(
            LEGACY_DEPENDENCIES[stage["stage_id"]]
        ):
            raise ContractError(f"{label}.dependencies are invalid")
        if not isinstance(stage.get("artifacts"), list):
            raise ContractError(f"{label}.artifacts must be a list")
        stage["artifacts"] = [
            validate_artifact(artifact, f"{label}.artifacts[{artifact_index}]")
            for artifact_index, artifact in enumerate(stage["artifacts"])
        ]
        require_timestamp(stage.get("updated_at"), f"{label}.updated_at")
        if stage["status"] == "completed" and not stage["artifacts"]:
            raise ContractError(f"{label} completed without a bound artifact")
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
    if migration.get("schema") != "ResearchPipelineMigration/v1":
        raise ContractError(f"{label}.schema is invalid")
    if migration.get("schema_version") != SCHEMA_VERSION:
        raise ContractError(f"{label}.schema_version is invalid")
    if migration.get("source_stage_ids") != list(LEGACY_STAGES):
        raise ContractError(f"{label}.source_stage_ids is invalid")
    if migration.get("target_stage_ids") != list(STAGES):
        raise ContractError(f"{label}.target_stage_ids is invalid")
    for key in (
        "source_state_digest",
        "preserved_stages_digest",
        "preserved_history_digest",
    ):
        if not SHA256_RE.fullmatch(str(migration.get(key))):
            raise ContractError(f"{label}.{key} is invalid")
    if migration.get("inserted_stage_id") != "source_normalization":
        raise ContractError(f"{label}.inserted_stage_id is invalid")
    if migration.get("inserted_stage_status") not in {"pending", "blocked"}:
        raise ContractError(f"{label}.inserted_stage_status is invalid")
    if migration.get("reason") != "normalization evidence required":
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
    if not isinstance(stages, list) or [stage.get("stage_id") for stage in stages] != list(STAGES):
        raise ContractError("execution.stages must contain the canonical ordered stages")
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
        if stage["status"] == "completed" and not stage["artifacts"]:
            raise ContractError(f"{label} completed without a bound artifact")
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
    state_digest = require_string(execution.get("state_digest"), "execution.state_digest")
    if not SHA256_RE.fullmatch(state_digest) or state_digest != execution_digest(execution):
        raise ContractError("execution.state_digest is invalid")
    return execution


def artifact_from_path(path_value: str) -> dict[str, Any]:
    path = Path(path_value).expanduser().resolve()
    if path.is_symlink() or not path.is_file():
        raise ContractError(f"artifact must be a regular non-symlink file: {path}")
    payload = path.read_bytes()
    return {
        "path": str(path),
        "sha256": hashlib.sha256(payload).hexdigest(),
        "size": len(payload),
    }


def migrate_legacy_execution(
    value: Any, *, as_of: str, inserted_status: str = "pending"
) -> dict[str, Any]:
    legacy = validate_legacy_execution(value)
    timestamp = require_timestamp(as_of, "as_of")
    if datetime.fromisoformat(timestamp.replace("Z", "+00:00")) < datetime.fromisoformat(
        legacy["updated_at"].replace("Z", "+00:00")
    ):
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
        "target_stage_ids": list(STAGES),
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
    if status not in STATUSES - {"pending"}:
        raise ContractError("recorded status must be running, completed, partial, or blocked")
    stage = next(item for item in execution["stages"] if item["stage_id"] == stage_id)
    if status not in TRANSITIONS[stage["status"]]:
        raise ContractError(f"invalid stage transition {stage['status']} -> {status}")
    by_id = {item["stage_id"]: item for item in execution["stages"]}
    if status in {"running", "completed"}:
        incomplete = [
            dependency
            for dependency in stage["dependencies"]
            if by_id[dependency]["status"] != "completed"
        ]
        if incomplete:
            raise ContractError(
                f"stage {stage_id} has incomplete dependencies: {', '.join(incomplete)}"
            )
    artifacts = [artifact_from_path(path) for path in artifact_paths]
    if status == "completed" and not (stage["artifacts"] or artifacts):
        raise ContractError("completed stage requires at least one artifact")
    for artifact in artifacts:
        if artifact not in stage["artifacts"]:
            stage["artifacts"].append(artifact)
    stage["status"] = status
    stage["reason"] = reason
    stage["updated_at"] = timestamp
    execution["updated_at"] = timestamp
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
    return validate_execution(execution)


def pipeline_status(value: Any) -> dict[str, Any]:
    execution = validate_execution(value)
    by_id = {stage["stage_id"]: stage for stage in execution["stages"]}
    ready = []
    for stage in execution["stages"]:
        if stage["status"] not in {"pending", "partial", "blocked"}:
            continue
        if all(by_id[dependency]["status"] == "completed" for dependency in stage["dependencies"]):
            ready.append(stage["stage_id"])
    return {
        "execution_id": execution["execution_id"],
        "state_digest": execution["state_digest"],
        "ready_stages": ready,
        "active_stages": [
            stage["stage_id"] for stage in execution["stages"] if stage["status"] == "running"
        ],
        "blocked_stages": [
            stage["stage_id"] for stage in execution["stages"] if stage["status"] == "blocked"
        ],
        "completed_stage_count": sum(
            stage["status"] == "completed" for stage in execution["stages"]
        ),
        "can_publish": by_id["gap_cycle"]["status"] == "completed",
        "complete": all(stage["status"] == "completed" for stage in execution["stages"]),
    }


def load_scholar_module():
    path = Path(__file__).resolve().parents[2] / "scholar-discovery" / "scripts" / "scholar_discovery.py"
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
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


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
    record.add_argument("--status", choices=sorted(STATUSES - {"pending"}), required=True)
    record.add_argument("--artifact", action="append", default=[])
    record.add_argument("--reason")
    record.add_argument("--as-of", required=True)
    record.add_argument("--output", required=True)
    status = subcommands.add_parser("status")
    status.add_argument("--execution", required=True)
    migrate = subcommands.add_parser("migrate")
    migrate.add_argument("--input", required=True)
    migrate.add_argument("--as-of", required=True)
    migrate.add_argument("--inserted-status", choices=("pending", "blocked"), default="pending")
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
            print(json.dumps(pipeline_status(load_json(args.execution)), sort_keys=True))
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
                validated = validate_execution(value)
            else:
                raise ContractError(f"unsupported schema: {schema!r}")
            print(json.dumps({"valid": True, "schema": validated["schema"]}, sort_keys=True))
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
