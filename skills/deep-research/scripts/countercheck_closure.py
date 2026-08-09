#!/usr/bin/env python3
"""Fail-closed closure checks for bounded countercheck rounds."""

from __future__ import annotations

import argparse
import copy
import hashlib
import importlib.util
import json
import os
import re
import stat
import sys
import tempfile
from pathlib import Path
from typing import Any


ROUND_INPUT_SCHEMA = "CountercheckRoundClosureInput/v1"
ROUND_OUTPUT_SCHEMA = "CountercheckRoundClosure/v1"
STREAK_INPUT_SCHEMA = "CountercheckStreakInput/v1"
STREAK_OUTPUT_SCHEMA = "CountercheckPragmaticSaturationAssessment/v1"
AXIS_PLAN_SCHEMA = "CountercheckAxisPlan/v1"
REQUEST_SCHEMA = "ScholarDiscoveryRequestSet/v1"
RESULT_SCHEMA = "ScholarDiscoveryResultSet/v1"
SCREENING_SCHEMA = "CountercheckScreeningSet/v1"
REVIEW_SCHEMA = "CountercheckTierAReviewSet/v1"
NETWORK_SCHEMA = "KnowledgeNetwork/v1"
PRIVATE_DIRECTORY_MODE = 0o700
PRIVATE_FILE_MODE = 0o600
HEX_RE = re.compile(r"[0-9a-f]{64}")
ROUND_STATUSES = {"completed", "partial", "failed", "interrupted"}
AXIS_DIMENSIONS = {
    "failure_boundary",
    "counterexample",
    "independent_replication",
    "identity_version_correction",
    "benchmark_null_case",
    "citation_neighborhood",
    "applicability_boundary",
}
COMPLETE_RESULT_STATUS = "complete_bounded"
DISCOVERY_RESULT_STATUSES = {
    COMPLETE_RESULT_STATUS,
    "partial_provider",
    "partial_budget",
    "blocked_capability",
}
TERMINAL_FAILURE_STATUSES = {
    "partial_provider",
    "partial_budget",
    "blocked_capability",
    "failed",
    "interrupted",
    "timeout",
    "rate_limited",
    "schema_changed",
    "budget_exhausted",
    "blocked",
    "not_provided_manual_required",
}
TERMINAL_REVIEW_STATUSES = {
    "accepted_evidence",
    "excluded",
    "duplicate",
    "not_eligible",
}
PENDING_REVIEW_STATUSES = {
    "pending",
    "fulltext_blocked",
    "acquisition_pending",
    "normalization_pending",
    "reading_pending",
}
SCREENING_DISPOSITIONS = {
    "tier_a",
    "excluded",
    "deferred",
    "duplicate",
    "unscreened",
}
ROUND_INPUT_FIELDS = {
    "schema",
    "round_id",
    "round_status",
    "assessed_at",
    "axis_plan_ref",
    "axis_sequence",
    "previous_closure_ref",
    "search_axis",
    "request_set_ref",
    "result_set_ref",
    "screening_ref",
    "tier_a_review_ref",
    "network_before_ref",
    "network_after_ref",
}
_SCHOLAR_OWNER: Any | None = None
_RKN_OWNER: Any | None = None
_NETWORK_EXPORT_VALIDATOR: Any | None = None


class ContractError(ValueError):
    """Raised when an input cannot support the requested bounded claim."""


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_json(value: Any) -> str:
    return sha256_bytes(canonical_bytes(value))


def require_dict(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ContractError(f"{label} must be an object")
    return value


def require_list(value: Any, label: str) -> list[Any]:
    if not isinstance(value, list):
        raise ContractError(f"{label} must be a list")
    return value


def require_string(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ContractError(f"{label} must be a non-empty string")
    return value.strip()


def require_bool(value: Any, label: str) -> bool:
    if not isinstance(value, bool):
        raise ContractError(f"{label} must be a boolean")
    return value


def require_nonnegative_int(value: Any, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ContractError(f"{label} must be a nonnegative integer")
    return value


def require_positive_int(value: Any, label: str) -> int:
    value = require_nonnegative_int(value, label)
    if value == 0:
        raise ContractError(f"{label} must be positive")
    return value


def require_hex(value: Any, label: str) -> str:
    text = require_string(value, label)
    if not HEX_RE.fullmatch(text):
        raise ContractError(f"{label} must be 64 lowercase hex characters")
    return text


def require_unique_strings(value: Any, label: str, *, nonempty: bool = False) -> list[str]:
    rows = require_list(value, label)
    strings = [require_string(row, f"{label}[]") for row in rows]
    if nonempty and not strings:
        raise ContractError(f"{label} must not be empty")
    if len(strings) != len(set(strings)):
        raise ContractError(f"{label} must contain unique strings")
    return strings


def normalize_query(value: Any) -> str:
    return " ".join(require_string(value, "query").casefold().split())


def _require_substantive_text(value: Any, label: str) -> str:
    text = require_string(value, label)
    if len(" ".join(text.split())) < 12:
        raise ContractError(f"{label} must be a substantive pre-reviewed statement")
    return text


def read_json_file(path: Path, label: str) -> tuple[dict[str, Any], str]:
    if not path.is_absolute():
        raise ContractError(f"{label}.path must be absolute")
    if path.is_symlink() or not path.is_file():
        raise ContractError(f"{label}.path must be a regular non-symlink file")
    raw = path.read_bytes()
    try:
        value = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ContractError(f"{label}.path must contain valid UTF-8 JSON") from exc
    return require_dict(value, label), sha256_bytes(raw)


def load_artifact_ref(value: Any, label: str) -> tuple[dict[str, Any], dict[str, Any]]:
    ref = require_dict(value, label)
    expected = require_hex(ref.get("sha256"), f"{label}.sha256")
    path = Path(require_string(ref.get("path"), f"{label}.path"))
    artifact, observed = read_json_file(path, label)
    if observed != expected:
        raise ContractError(f"{label} sha256 mismatch")
    return ref, artifact


def _ensure_private_output_directory(directory: Path) -> None:
    directory = directory.absolute()
    missing: list[Path] = []
    cursor = directory
    while not cursor.exists():
        missing.append(cursor)
        parent = cursor.parent
        if parent == cursor:
            raise ContractError(f"cannot resolve output parent: {directory}")
        cursor = parent
    if cursor.is_symlink() or not cursor.is_dir():
        raise ContractError(f"output parent must be a directory: {cursor}")
    for candidate in reversed(missing):
        try:
            os.mkdir(candidate, PRIVATE_DIRECTORY_MODE)
        except FileExistsError:
            pass
        if candidate.is_symlink() or not candidate.is_dir():
            raise ContractError(f"output parent must be a directory: {candidate}")
        os.chmod(candidate, PRIVATE_DIRECTORY_MODE, follow_symlinks=False)
    if directory.is_symlink() or not directory.is_dir():
        raise ContractError(f"output parent must be a private directory: {directory}")
    mode = stat.S_IMODE(os.stat(directory, follow_symlinks=False).st_mode)
    if mode & 0o077:
        raise ContractError(
            f"output directory must not grant group or other access: {directory}"
        )


def write_json(path: Path, value: Any) -> None:
    target = path.absolute()
    if target.is_symlink():
        raise ContractError(f"refusing symlink output: {target}")
    if target.exists() and not target.is_file():
        raise ContractError(f"output must be a regular file: {target}")
    _ensure_private_output_directory(target.parent)
    payload = canonical_bytes(value) + b"\n"
    descriptor: int | None = None
    temporary: Path | None = None
    try:
        descriptor, name = tempfile.mkstemp(
            prefix=f".{target.name}.", suffix=".tmp", dir=target.parent
        )
        temporary = Path(name)
        os.fchmod(descriptor, PRIVATE_FILE_MODE)
        with os.fdopen(descriptor, "wb") as handle:
            descriptor = None
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        if stat.S_IMODE(temporary.stat().st_mode) != PRIVATE_FILE_MODE:
            raise ContractError("private temporary output mode is not 0600")
        os.replace(temporary, target)
        temporary = None
        os.chmod(target, PRIVATE_FILE_MODE, follow_symlinks=False)
        directory_descriptor = os.open(
            target.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
        )
        try:
            os.fsync(directory_descriptor)
        finally:
            os.close(directory_descriptor)
    except BaseException:
        if descriptor is not None:
            os.close(descriptor)
        if temporary is not None:
            try:
                temporary.unlink()
            except FileNotFoundError:
                pass
        raise


def _load_scholar_owner() -> Any:
    global _SCHOLAR_OWNER
    if _SCHOLAR_OWNER is not None:
        return _SCHOLAR_OWNER
    script = (
        Path(__file__).resolve().parents[2]
        / "scholar-discovery"
        / "scripts"
        / "scholar_discovery.py"
    )
    if script.is_symlink() or not script.is_file():
        raise ContractError(f"scholar-discovery owner script is unavailable: {script}")
    module_name = "_deep_research_countercheck_scholar_owner"
    spec = importlib.util.spec_from_file_location(module_name, script)
    if spec is None or spec.loader is None:
        raise ContractError("cannot load scholar-discovery owner validator")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    try:
        spec.loader.exec_module(module)
    except Exception as exc:
        sys.modules.pop(module_name, None)
        raise ContractError(f"cannot load scholar-discovery owner validator: {exc}") from exc
    for name in ("validate_request_set", "validate_result_set"):
        if not callable(getattr(module, name, None)):
            raise ContractError(f"scholar-discovery owner lacks {name}")
    _SCHOLAR_OWNER = module
    return module


def _load_rkn_owner() -> Any:
    global _RKN_OWNER
    if _RKN_OWNER is not None:
        return _RKN_OWNER
    script = (
        Path(__file__).resolve().parents[2]
        / "research-knowledge-network"
        / "scripts"
        / "knowledge_network.py"
    )
    if script.is_symlink() or not script.is_file():
        raise ContractError(f"research-knowledge-network owner is unavailable: {script}")
    module_name = "_deep_research_countercheck_rkn_owner"
    spec = importlib.util.spec_from_file_location(module_name, script)
    if spec is None or spec.loader is None:
        raise ContractError("cannot load research-knowledge-network owner")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    try:
        spec.loader.exec_module(module)
    except Exception as exc:
        sys.modules.pop(module_name, None)
        raise ContractError(f"cannot load research-knowledge-network owner: {exc}") from exc
    if not callable(getattr(module, "_sha256_json", None)):
        raise ContractError("research-knowledge-network owner lacks _sha256_json")
    _RKN_OWNER = module
    return module


def _load_network_export_validator() -> Any:
    global _NETWORK_EXPORT_VALIDATOR
    if _NETWORK_EXPORT_VALIDATOR is not None:
        return _NETWORK_EXPORT_VALIDATOR
    script = Path(__file__).with_name("validate_research_handoff.py")
    if script.is_symlink() or not script.is_file():
        raise ContractError(f"KnowledgeNetwork/v1 validator is unavailable: {script}")
    module_name = "_deep_research_countercheck_network_export_validator"
    spec = importlib.util.spec_from_file_location(module_name, script)
    if spec is None or spec.loader is None:
        raise ContractError("cannot load KnowledgeNetwork/v1 validator")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    try:
        spec.loader.exec_module(module)
    except Exception as exc:
        sys.modules.pop(module_name, None)
        raise ContractError(f"cannot load KnowledgeNetwork/v1 validator: {exc}") from exc
    if not callable(getattr(module, "validate_knowledge_network", None)):
        raise ContractError("KnowledgeNetwork/v1 validator entrypoint is unavailable")
    _NETWORK_EXPORT_VALIDATOR = module
    return module


def canonical_network_content_sha256(network: dict[str, Any]) -> str:
    payload = copy.deepcopy(require_dict(network, "network"))
    payload.pop("content_sha256", None)
    try:
        digest = _load_rkn_owner()._sha256_json(payload)
    except Exception as exc:
        raise ContractError(f"network canonical digest failed: {exc}") from exc
    prefix = "sha256:"
    if not isinstance(digest, str) or not digest.startswith(prefix):
        raise ContractError("research-knowledge-network returned an invalid digest")
    return require_hex(digest[len(prefix) :], "canonical network content sha256")


def _owner_validate(function_name: str, value: Any, label: str) -> dict[str, Any]:
    owner = _load_scholar_owner()
    try:
        validated = getattr(owner, function_name)(copy.deepcopy(value))
    except Exception as exc:
        raise ContractError(f"{label} failed scholar-discovery owner validation: {exc}") from exc
    return require_dict(validated, label)


def _artifact_binding(ref: dict[str, Any]) -> dict[str, str]:
    return {
        "path": require_string(ref.get("path"), "artifact path"),
        "sha256": require_hex(ref.get("sha256"), "artifact sha256"),
    }


def canonical_axis_plan_digest(document: dict[str, Any]) -> str:
    payload = copy.deepcopy(document)
    payload.pop("plan_id", None)
    payload.pop("plan_digest", None)
    return sha256_json(payload)


def validate_axis_plan(value: Any) -> dict[str, Any]:
    plan = require_dict(value, "axis plan")
    expected_fields = {
        "schema",
        "plan_id",
        "plan_digest",
        "created_at",
        "network_content_sha256",
        "review_status",
        "axes",
    }
    if set(plan) != expected_fields:
        raise ContractError(f"axis plan fields must be exactly {sorted(expected_fields)}")
    if plan.get("schema") != AXIS_PLAN_SCHEMA:
        raise ContractError(f"axis plan schema must be {AXIS_PLAN_SCHEMA}")
    require_string(plan.get("created_at"), "axis plan.created_at")
    require_hex(plan.get("network_content_sha256"), "axis plan.network_content_sha256")
    if plan.get("review_status") != "approved":
        raise ContractError("axis plan must be pre-reviewed with review_status=approved")
    axes = require_list(plan.get("axes"), "axis plan.axes")
    if len(axes) < 2:
        raise ContractError("axis plan must pre-review at least two ordered axes")

    dimensions: set[str] = set()
    provider_sets: set[tuple[str, ...]] = set()
    falsifiers: set[str] = set()
    information_gains: set[str] = set()
    round_ids: set[str] = set()
    for index, raw_axis in enumerate(axes, start=1):
        axis = require_dict(raw_axis, f"axis plan.axes[{index - 1}]")
        fields = {
            "sequence",
            "round_id",
            "dimension",
            "provider_families",
            "falsifier",
            "expected_information_gain",
        }
        if set(axis) != fields:
            raise ContractError(
                f"axis plan.axes[{index - 1}] fields must be exactly {sorted(fields)}"
            )
        if require_positive_int(axis.get("sequence"), "axis sequence") != index:
            raise ContractError("axis plan sequences must be contiguous and ordered from one")
        round_id = require_string(axis.get("round_id"), "axis round_id")
        if round_id in round_ids:
            raise ContractError("axis plan round IDs must be unique")
        round_ids.add(round_id)
        dimension = require_string(axis.get("dimension"), "axis dimension")
        if dimension not in AXIS_DIMENSIONS:
            raise ContractError(f"unsupported axis dimension: {dimension}")
        if dimension in dimensions:
            raise ContractError("axis plan dimensions must be pairwise orthogonal")
        dimensions.add(dimension)
        provider_families = require_unique_strings(
            axis.get("provider_families"), "axis provider_families", nonempty=True
        )
        if provider_families != sorted(provider_families):
            raise ContractError("axis provider_families must be in canonical sorted order")
        provider_key = tuple(provider_families)
        if provider_key in provider_sets:
            raise ContractError("axis plan provider-family sets must be pairwise distinct")
        provider_sets.add(provider_key)
        falsifier = normalize_query(
            _require_substantive_text(axis.get("falsifier"), "axis falsifier")
        )
        if falsifier in falsifiers:
            raise ContractError("axis plan falsifiers must be pairwise distinct")
        falsifiers.add(falsifier)
        gain = normalize_query(
            _require_substantive_text(
                axis.get("expected_information_gain"), "axis expected_information_gain"
            )
        )
        if gain in information_gains:
            raise ContractError(
                "axis plan expected-information-gain statements must be pairwise distinct"
            )
        information_gains.add(gain)

    digest = require_hex(plan.get("plan_digest"), "axis plan.plan_digest")
    if canonical_axis_plan_digest(plan) != digest:
        raise ContractError("axis plan.plan_digest mismatch")
    if plan.get("plan_id") != f"countercheck-axis-plan-{digest[:16]}":
        raise ContractError("axis plan.plan_id mismatch")
    return plan


def _validate_network_ref(value: Any, label: str) -> dict[str, str]:
    ref, network = load_artifact_ref(value, label)
    if ref.get("authoritative") is not True:
        raise ContractError(f"{label}.authoritative must be true")
    if network.get("schema") != NETWORK_SCHEMA:
        raise ContractError(f"{label} schema must be {NETWORK_SCHEMA}")
    validation_errors = _load_network_export_validator().validate_knowledge_network(
        copy.deepcopy(network)
    )
    if validation_errors:
        raise ContractError(
            f"{label} failed KnowledgeNetwork/v1 validation: "
            + "; ".join(str(error) for error in validation_errors)
        )
    snapshot_id = require_string(ref.get("snapshot_id"), f"{label}.snapshot_id")
    content_sha256 = require_hex(ref.get("content_sha256"), f"{label}.content_sha256")
    if network.get("snapshot_id") != snapshot_id:
        raise ContractError(f"{label} snapshot_id mismatch")
    if network.get("content_sha256") != content_sha256:
        raise ContractError(f"{label} content_sha256 mismatch")
    expected_content_sha256 = canonical_network_content_sha256(network)
    if content_sha256 != expected_content_sha256:
        raise ContractError(
            f"{label} content_sha256 does not match the RKN canonical export payload"
        )
    return {
        "path": require_string(ref.get("path"), f"{label}.path"),
        "file_sha256": ref["sha256"],
        "snapshot_id": snapshot_id,
        "content_sha256": content_sha256,
    }


def _network_request_binding_matches(
    request_network_ref: dict[str, Any], network: dict[str, str]
) -> bool:
    return request_network_ref.get("sha256") == network["content_sha256"]


def _network_fingerprint(network: dict[str, str]) -> str:
    return network["content_sha256"]


def _validate_request_set(value: dict[str, Any]) -> dict[str, Any]:
    value = _owner_validate("validate_request_set", value, "request set")
    if value.get("schema") != REQUEST_SCHEMA:
        raise ContractError(f"request set schema must be {REQUEST_SCHEMA}")
    requests = require_list(value.get("requests"), "requests")
    request_ids: list[str] = []
    hypothesis_ids: list[str] = []
    queries: list[dict[str, str]] = []
    provider_families: set[str] = set()
    filters: list[dict[str, Any]] = []
    request_by_id: dict[str, dict[str, Any]] = {}
    for index, raw_request in enumerate(requests):
        request = require_dict(raw_request, f"requests[{index}]")
        request_id = require_string(request.get("request_id"), "request_id")
        request_ids.append(request_id)
        request_by_id[request_id] = request
        gap_ref = require_dict(request.get("gap_ref"), f"{request_id}.gap_ref")
        gap_id = require_string(gap_ref.get("gap_id"), "gap_ref.gap_id")
        hypothesis_ids.append(gap_id)
        if request.get("gap_hypothesis_id") != gap_id:
            raise ContractError(f"{request_id}.gap_hypothesis_id mismatch")
        routes = require_dict(request.get("routes"), f"{request_id}.routes")
        automatic = require_unique_strings(
            routes.get("automatic"), f"{request_id}.routes.automatic", nonempty=True
        )
        provider_families.update(automatic)
        scholar_policy = require_string(
            routes.get("google_scholar"), f"{request_id}.routes.google_scholar"
        )
        if scholar_policy != "disabled":
            provider_families.add("google_scholar_manual")
        query_seeds = require_list(request.get("query_seeds"), f"{request_id}.query_seeds")
        for seed in query_seeds:
            query = require_dict(seed, f"{request_id}.query_seed")
            queries.append(
                {
                    "request_id": request_id,
                    "objective": require_string(query.get("objective"), "query objective"),
                    "normalized_query": normalize_query(query.get("query")),
                }
            )
        filters.append(require_dict(request.get("metadata_filters", {}), "metadata_filters"))
    if len(request_ids) != len(set(request_ids)):
        raise ContractError("request IDs must be unique")
    return {
        "request_set_id": require_string(value.get("request_set_id"), "request_set_id"),
        "request_set_digest": require_hex(
            value.get("request_set_digest"), "request_set_digest"
        ),
        "request_ids": request_ids,
        "request_by_id": request_by_id,
        "hypothesis_ids": sorted(set(hypothesis_ids)),
        "queries": queries,
        "provider_families": sorted(provider_families),
        "filters": filters,
        "network_id": require_string(value.get("network_id"), "request network_id"),
        "network_ref": require_dict(value.get("network_ref"), "request network_ref"),
    }


def _validate_axis(
    value: Any,
    request_info: dict[str, Any],
    plan_axis: dict[str, Any],
) -> dict[str, Any]:
    axis = require_dict(value, "search_axis")
    if set(axis) != {"dimension", "queries"}:
        raise ContractError("search_axis fields must be exactly dimension and queries")
    dimension = require_string(axis.get("dimension"), "search_axis.dimension")
    if dimension != plan_axis["dimension"]:
        raise ContractError("search_axis.dimension does not match pre-reviewed axis plan")
    if request_info["provider_families"] != plan_axis["provider_families"]:
        raise ContractError(
            "request provider families do not match the pre-reviewed axis plan"
        )
    raw_bindings = require_list(axis.get("queries"), "search_axis.queries")
    bindings: list[dict[str, str]] = []
    for index, raw in enumerate(raw_bindings):
        binding = require_dict(raw, f"search_axis.queries[{index}]")
        if set(binding) != {"query_id", "request_id", "objective", "normalized_query"}:
            raise ContractError("search-axis query binding has unsupported fields")
        bindings.append(
            {
                "query_id": require_string(binding.get("query_id"), "query_id"),
                "request_id": require_string(
                    binding.get("request_id"), "query request_id"
                ),
                "objective": require_string(binding.get("objective"), "query objective"),
                "normalized_query": normalize_query(binding.get("normalized_query")),
            }
        )
    if not bindings:
        raise ContractError("search_axis.queries must not be empty")
    query_ids = [row["query_id"] for row in bindings]
    if len(query_ids) != len(set(query_ids)):
        raise ContractError("query IDs must be unique")
    tuples = [
        (row["request_id"], row["objective"], row["normalized_query"])
        for row in bindings
    ]
    expected_tuples = [
        (row["request_id"], row["objective"], row["normalized_query"])
        for row in request_info["queries"]
    ]
    if sorted(tuples) != sorted(expected_tuples):
        raise ContractError("search-axis query bindings do not exactly match request queries")
    if len(tuples) != len(set(tuples)):
        raise ContractError("request query tuples must be unique")
    axis_payload = {
        "sequence": plan_axis["sequence"],
        "dimension": dimension,
        "provider_families": list(plan_axis["provider_families"]),
        "falsifier": plan_axis["falsifier"],
        "expected_information_gain": plan_axis["expected_information_gain"],
        "selected_hypothesis_ids": request_info["hypothesis_ids"],
        "normalized_queries": sorted({row["normalized_query"] for row in bindings}),
        "query_ids": sorted(query_ids),
        "filters": request_info["filters"],
    }
    axis_payload["fingerprint"] = sha256_json(axis_payload)
    return axis_payload


def _result_failure_status(value: dict[str, Any], label: str) -> str:
    status = value.get("status")
    if not isinstance(status, str):
        status = value.get("failure_type")
    status = require_string(status, f"{label}.status")
    if status not in TERMINAL_FAILURE_STATUSES:
        raise ContractError(f"{label} has nonterminal or unknown status: {status}")
    return status


def _validate_results(
    value: dict[str, Any], request_info: dict[str, Any], network: dict[str, str]
) -> tuple[bool, list[dict[str, str]]]:
    document = _owner_validate("validate_result_set", value, "result set")
    if document.get("schema") != RESULT_SCHEMA:
        raise ContractError(f"result set schema must be {RESULT_SCHEMA}")
    for field in ("request_set_id", "request_set_digest"):
        if document.get(field) != request_info[field]:
            raise ContractError(f"result set {field} mismatch")
    if document.get("network_id") != request_info["network_id"]:
        raise ContractError("result set network_id mismatch")
    result_network_ref = require_dict(document.get("network_ref"), "result network_ref")
    if not _network_request_binding_matches(result_network_ref, network):
        raise ContractError("result set network content binding mismatch")

    represented: dict[str, str] = {}
    occurrences: list[dict[str, str]] = []
    for index, raw in enumerate(require_list(document.get("results"), "results")):
        result = require_dict(raw, f"results[{index}]")
        request_id = require_string(result.get("request_id"), "result request_id")
        request = request_info["request_by_id"].get(request_id)
        if request is None:
            raise ContractError(f"result set includes unknown request {request_id}")
        if result.get("request_digest") != sha256_json(request):
            raise ContractError(f"result request_digest mismatch for {request_id}")
        if result.get("hypothesis_id") != request.get("gap_hypothesis_id"):
            raise ContractError(f"result hypothesis_id mismatch for {request_id}")
        status = require_string(result.get("discovery_status"), "result discovery_status")
        if status not in DISCOVERY_RESULT_STATUSES:
            raise ContractError(f"unknown owner discovery_status: {status}")
        represented[request_id] = status
        seen_candidate_ids: set[str] = set()
        for candidate_index, raw_candidate in enumerate(
            require_list(result.get("ranked_candidates"), "ranked_candidates")
        ):
            candidate = require_dict(
                raw_candidate, f"results[{index}].ranked_candidates[{candidate_index}]"
            )
            candidate_id = require_string(candidate.get("candidate_id"), "candidate_id")
            if candidate_id in seen_candidate_ids:
                raise ContractError(
                    f"result {request_id} repeats candidate occurrence {candidate_id}"
                )
            seen_candidate_ids.add(candidate_id)
            occurrences.append(
                {"request_id": request_id, "candidate_id": candidate_id}
            )

    failures = require_list(document.get("failures", []), "failures")
    for index, raw in enumerate(failures):
        failure = require_dict(raw, f"failures[{index}]")
        request_id = require_string(failure.get("request_id"), "failure request_id")
        if request_id not in request_info["request_by_id"]:
            raise ContractError(f"result set failure includes unknown request {request_id}")
        represented[request_id] = _result_failure_status(failure, f"failures[{index}]")
    if set(represented) != set(request_info["request_ids"]):
        raise ContractError("result/failure records do not terminally close every request")
    occurrences.sort(key=lambda row: (row["request_id"], row["candidate_id"]))
    provider_complete = (
        not failures
        and all(status == COMPLETE_RESULT_STATUS for status in represented.values())
    )
    return provider_complete, occurrences


def _validate_screening(
    value: dict[str, Any],
    round_id: str,
    request_info: dict[str, Any],
    result_ref: dict[str, Any],
    expected_occurrences: list[dict[str, str]],
) -> list[str]:
    if value.get("schema") != SCREENING_SCHEMA:
        raise ContractError(f"screening schema must be {SCREENING_SCHEMA}")
    if value.get("round_id") != round_id:
        raise ContractError("screening round_id mismatch")
    if value.get("request_set_id") != request_info["request_set_id"]:
        raise ContractError("screening request_set_id mismatch")
    if value.get("request_set_digest") != request_info["request_set_digest"]:
        raise ContractError("screening request_set_digest mismatch")
    selected_ids = require_unique_strings(
        value.get("selected_request_ids"), "selected_request_ids", nonempty=True
    )
    if selected_ids != request_info["request_ids"]:
        raise ContractError("selected request set does not close exactly in request order")

    result_binding = require_dict(value.get("result_set_ref"), "screening.result_set_ref")
    if set(result_binding) != {"schema", "sha256"}:
        raise ContractError("screening.result_set_ref must contain schema and sha256")
    if result_binding.get("schema") != RESULT_SCHEMA:
        raise ContractError("screening.result_set_ref schema mismatch")
    if result_binding.get("sha256") != result_ref.get("sha256"):
        raise ContractError("screening result-set artifact digest mismatch")
    expected_universe_digest = sha256_json(expected_occurrences)
    if value.get("candidate_occurrence_universe_sha256") != expected_universe_digest:
        raise ContractError("screening candidate occurrence universe digest mismatch")

    rows = require_list(value.get("candidate_occurrences"), "candidate_occurrences")
    observed_occurrences: list[dict[str, str]] = []
    tier_a_ids: set[str] = set()
    unscreened = 0
    for index, raw in enumerate(rows):
        row = require_dict(raw, f"candidate_occurrences[{index}]")
        expected_fields = {"request_id", "candidate_id", "disposition", "reason"}
        if set(row) != expected_fields:
            raise ContractError(
                f"candidate_occurrences[{index}] fields must be exactly {sorted(expected_fields)}"
            )
        occurrence = {
            "request_id": require_string(row.get("request_id"), "occurrence request_id"),
            "candidate_id": require_string(row.get("candidate_id"), "occurrence candidate_id"),
        }
        observed_occurrences.append(occurrence)
        disposition = require_string(row.get("disposition"), "screening disposition")
        if disposition not in SCREENING_DISPOSITIONS:
            raise ContractError(f"unsupported screening disposition: {disposition}")
        require_string(row.get("reason"), "screening reason")
        if disposition == "tier_a":
            tier_a_ids.add(occurrence["candidate_id"])
        if disposition == "unscreened":
            unscreened += 1
    if observed_occurrences != expected_occurrences:
        raise ContractError(
            "screening candidate occurrences must exactly cover the ordered result universe"
        )
    declared_unscreened = require_nonnegative_int(
        value.get("unscreened_occurrence_count"), "unscreened_occurrence_count"
    )
    if declared_unscreened != unscreened:
        raise ContractError("unscreened_occurrence_count does not match occurrence rows")
    if not require_bool(value.get("screening_complete"), "screening_complete"):
        raise ContractError("screening is not complete")
    if unscreened:
        raise ContractError("screening has unscreened occurrences")
    declared_tier_a = require_unique_strings(
        value.get("tier_a_candidate_ids"), "tier_a_candidate_ids"
    )
    if declared_tier_a != sorted(tier_a_ids):
        raise ContractError(
            "tier_a_candidate_ids must exactly match tier_a occurrence dispositions"
        )
    return declared_tier_a


def _validate_review(
    value: dict[str, Any], round_id: str, request_info: dict[str, Any], tier_a_ids: list[str]
) -> tuple[int, int]:
    if value.get("schema") != REVIEW_SCHEMA:
        raise ContractError(f"review schema must be {REVIEW_SCHEMA}")
    if value.get("round_id") != round_id:
        raise ContractError("review round_id mismatch")
    for field in ("request_set_id", "request_set_digest"):
        if value.get(field) != request_info[field]:
            raise ContractError(f"review {field} mismatch")
    review_ids = require_unique_strings(value.get("tier_a_candidate_ids"), "review IDs")
    if review_ids != tier_a_ids:
        raise ContractError("review IDs do not exactly match screened Tier-A IDs")
    reviews = require_list(value.get("reviews"), "reviews")
    seen: set[str] = set()
    pending = 0
    accepted = 0
    for index, raw in enumerate(reviews):
        review = require_dict(raw, f"reviews[{index}]")
        candidate_id = require_string(review.get("candidate_id"), "candidate_id")
        if candidate_id in seen:
            raise ContractError(f"duplicate review for candidate {candidate_id}")
        seen.add(candidate_id)
        status = require_string(review.get("status"), "review status")
        adds = require_bool(review.get("decision_relevant_add"), "decision_relevant_add")
        if status in PENDING_REVIEW_STATUSES:
            if adds:
                raise ContractError("pending review cannot assert a decision-relevant addition")
            pending += 1
        elif status in TERMINAL_REVIEW_STATUSES:
            if adds != (status == "accepted_evidence"):
                raise ContractError("review status and decision_relevant_add disagree")
            accepted += int(adds)
        else:
            raise ContractError(f"unknown review status: {status}")
    if seen != set(review_ids) or len(reviews) != len(review_ids):
        raise ContractError("reviews do not exactly cover screened Tier-A IDs")
    declared_complete = require_bool(value.get("review_complete"), "review_complete")
    if declared_complete != (pending == 0):
        raise ContractError("review_complete does not match review terminality")
    return pending, accepted


def _sealed_payload(payload: dict[str, Any], id_prefix: str) -> dict[str, Any]:
    sealed = dict(payload)
    digest = sha256_json(sealed)
    sealed["closure_digest"] = digest
    sealed["closure_id"] = id_prefix + digest[:16]
    return sealed


def _validate_sealed(value: dict[str, Any], schema: str, id_prefix: str) -> None:
    if value.get("schema") != schema:
        raise ContractError(f"schema must be {schema}")
    digest = require_hex(value.get("closure_digest"), "closure_digest")
    payload = dict(value)
    payload.pop("closure_digest", None)
    payload.pop("closure_id", None)
    if sha256_json(payload) != digest:
        raise ContractError("closure_digest mismatch")
    if value.get("closure_id") != id_prefix + digest[:16]:
        raise ContractError("closure_id mismatch")
    if value.get("systematic_review_completeness") is not False:
        raise ContractError("systematic_review_completeness must remain false")
    if value.get("domain_completeness") is not False:
        raise ContractError("domain_completeness must remain false")


def _axis_plan_binding(ref: dict[str, Any], plan: dict[str, Any]) -> dict[str, Any]:
    return {
        **_artifact_binding(ref),
        "plan_id": plan["plan_id"],
        "plan_digest": plan["plan_digest"],
        "network_content_sha256": plan["network_content_sha256"],
        "axis_count": len(plan["axes"]),
    }


def _load_replayed_closure_ref(
    value: Any, label: str
) -> tuple[dict[str, Any], dict[str, Any]]:
    ref, closure = load_artifact_ref(value, label)
    return ref, replay_round_closure(closure)


def close_round(
    manifest: dict[str, Any], manifest_sha256: str, manifest_path: Path
) -> dict[str, Any]:
    if set(manifest) != ROUND_INPUT_FIELDS:
        raise ContractError(f"round input fields must be exactly {sorted(ROUND_INPUT_FIELDS)}")
    if manifest.get("schema") != ROUND_INPUT_SCHEMA:
        raise ContractError(f"input schema must be {ROUND_INPUT_SCHEMA}")
    round_id = require_string(manifest.get("round_id"), "round_id")
    round_status = require_string(manifest.get("round_status"), "round_status")
    if round_status not in ROUND_STATUSES:
        raise ContractError(f"unsupported round_status: {round_status}")
    assessed_at = require_string(manifest.get("assessed_at"), "assessed_at")

    before = _validate_network_ref(manifest.get("network_before_ref"), "network_before_ref")
    after = _validate_network_ref(manifest.get("network_after_ref"), "network_after_ref")
    plan_ref, raw_plan = load_artifact_ref(manifest.get("axis_plan_ref"), "axis_plan_ref")
    plan = validate_axis_plan(raw_plan)
    if plan["network_content_sha256"] != before["content_sha256"]:
        raise ContractError("axis plan does not bind the authoritative before-network content")
    sequence = require_positive_int(manifest.get("axis_sequence"), "axis_sequence")
    if sequence > len(plan["axes"]):
        raise ContractError("axis_sequence exceeds the pre-reviewed axis plan")
    plan_axis = plan["axes"][sequence - 1]
    if plan_axis["round_id"] != round_id:
        raise ContractError("round_id does not match the ordered axis plan")

    previous_binding: dict[str, str] | None = None
    previous_ref_value = manifest.get("previous_closure_ref")
    if sequence == 1:
        if previous_ref_value is not None:
            raise ContractError("the first planned axis must not declare a previous closure")
    else:
        if previous_ref_value is None:
            raise ContractError("a non-first planned axis must bind the previous closure")
        previous_ref, previous = _load_replayed_closure_ref(
            previous_ref_value, "previous_closure_ref"
        )
        if previous["axis_sequence"] != sequence - 1:
            raise ContractError("previous closure does not immediately precede this axis")
        if previous["round_id"] != plan["axes"][sequence - 2]["round_id"]:
            raise ContractError("previous closure round does not match the ordered axis plan")
        if previous["axis_plan_binding"]["sha256"] != plan_ref["sha256"]:
            raise ContractError("previous closure belongs to a different axis plan")
        if previous["network_after"]["content_sha256"] != before["content_sha256"]:
            raise ContractError("previous closure and current round do not share network content")
        previous_binding = _artifact_binding(previous_ref)

    request_ref, request_set = load_artifact_ref(
        manifest.get("request_set_ref"), "request_set_ref"
    )
    result_ref, result_set = load_artifact_ref(
        manifest.get("result_set_ref"), "result_set_ref"
    )
    screening_ref, screening = load_artifact_ref(
        manifest.get("screening_ref"), "screening_ref"
    )
    review_ref, review = load_artifact_ref(
        manifest.get("tier_a_review_ref"), "tier_a_review_ref"
    )
    request_info = _validate_request_set(request_set)
    if not _network_request_binding_matches(request_info["network_ref"], before):
        raise ContractError("request set does not bind the authoritative network content")
    axis = _validate_axis(manifest.get("search_axis"), request_info, plan_axis)
    provider_complete, occurrences = _validate_results(result_set, request_info, before)
    tier_a_ids = _validate_screening(
        screening, round_id, request_info, result_ref, occurrences
    )
    pending_count, accepted_count = _validate_review(
        review, round_id, request_info, tier_a_ids
    )
    network_unchanged = _network_fingerprint(before) == _network_fingerprint(after)
    if accepted_count == 0 and not network_unchanged:
        raise ContractError("authoritative network content drifted without accepted evidence")
    observed_no_add = accepted_count == 0 and pending_count == 0 and network_unchanged
    qualifying_no_add = (
        observed_no_add and provider_complete and round_status == "completed"
    )
    if accepted_count:
        closure_status = "evidence_added"
    elif pending_count:
        closure_status = "review_pending"
    elif not provider_complete:
        closure_status = "partial_provider"
    elif qualifying_no_add:
        closure_status = "qualifying_no_add"
    else:
        closure_status = "observed_no_add"
    input_ref = {
        "path": str(manifest_path.absolute()),
        "sha256": require_hex(manifest_sha256, "input manifest sha256"),
    }
    payload = {
        "schema": ROUND_OUTPUT_SCHEMA,
        "round_id": round_id,
        "round_status": round_status,
        "assessed_at": assessed_at,
        "round_input_ref": input_ref,
        "input_manifest_sha256": manifest_sha256,
        "closure_status": closure_status,
        "observed_no_add": observed_no_add,
        "qualifying_no_add": qualifying_no_add,
        "provider_coverage_complete": provider_complete,
        "tier_a_review_terminal": pending_count == 0,
        "tier_a_pending_count": pending_count,
        "decision_relevant_add_count": accepted_count,
        "network_digest_unchanged": network_unchanged,
        "request_ids": request_info["request_ids"],
        "query_ids": axis["query_ids"],
        "selected_hypothesis_ids": axis["selected_hypothesis_ids"],
        "search_axis": axis,
        "axis_sequence": sequence,
        "axis_plan_binding": _axis_plan_binding(plan_ref, plan),
        "previous_closure_binding": previous_binding,
        "network_before": before,
        "network_after": after,
        "artifact_bindings": {
            "request_set": _artifact_binding(request_ref),
            "result_set": _artifact_binding(result_ref),
            "screening": _artifact_binding(screening_ref),
            "tier_a_review": _artifact_binding(review_ref),
        },
        "claim_scope": "bounded_countercheck_round_only",
        "systematic_review_completeness": False,
        "domain_completeness": False,
    }
    return _sealed_payload(payload, "countercheck-closure-")


def replay_round_closure(value: Any) -> dict[str, Any]:
    closure = require_dict(value, "round closure")
    _validate_sealed(closure, ROUND_OUTPUT_SCHEMA, "countercheck-closure-")
    input_ref, manifest = load_artifact_ref(
        closure.get("round_input_ref"), "round closure.round_input_ref"
    )
    expected = close_round(
        manifest,
        input_ref["sha256"],
        Path(require_string(input_ref.get("path"), "round input path")),
    )
    if expected != closure:
        raise ContractError("round closure does not match replayed artifact references")
    return expected


def assess_streak(
    manifest: dict[str, Any], manifest_sha256: str, manifest_path: Path
) -> dict[str, Any]:
    if set(manifest) != {"schema", "assessed_at", "closure_refs"}:
        raise ContractError(
            "streak input fields must be exactly schema, assessed_at, and closure_refs"
        )
    if manifest.get("schema") != STREAK_INPUT_SCHEMA:
        raise ContractError(f"input schema must be {STREAK_INPUT_SCHEMA}")
    assessed_at = require_string(manifest.get("assessed_at"), "assessed_at")
    raw_refs = require_list(manifest.get("closure_refs"), "closure_refs")
    if not raw_refs:
        raise ContractError("closure_refs must not be empty")
    closures: list[dict[str, Any]] = []
    bindings: list[dict[str, str]] = []
    seen_round_ids: set[str] = set()
    for index, raw_ref in enumerate(raw_refs):
        ref, raw_closure = load_artifact_ref(raw_ref, f"closure_refs[{index}]")
        closure = replay_round_closure(raw_closure)
        round_id = require_string(closure.get("round_id"), "closure round_id")
        if round_id in seen_round_ids:
            raise ContractError(f"duplicate closure round_id: {round_id}")
        seen_round_ids.add(round_id)
        closures.append(closure)
        bindings.append(_artifact_binding(ref))

    plan_binding = closures[0]["axis_plan_binding"]
    plan_ref, raw_plan = load_artifact_ref(plan_binding, "assessment axis plan")
    plan = validate_axis_plan(raw_plan)
    if len(closures) != len(plan["axes"]):
        raise ContractError("closure_refs must include every ordered axis-plan closure")
    expected_round_ids = [axis["round_id"] for axis in plan["axes"]]
    if [closure["round_id"] for closure in closures] != expected_round_ids:
        raise ContractError("closure_refs do not preserve the complete axis-plan order")
    for index, closure in enumerate(closures):
        if closure["axis_sequence"] != index + 1:
            raise ContractError("closure axis sequences are not contiguous")
        if closure["axis_plan_binding"]["sha256"] != plan_ref["sha256"]:
            raise ContractError("closures do not share one immutable axis plan")
        expected_previous = None if index == 0 else bindings[index - 1]
        if closure["previous_closure_binding"] != expected_previous:
            raise ContractError("closure previous chain does not match closure_refs order")

    streak: list[dict[str, Any]] = []
    reset_round_ids: list[str] = []
    for closure in closures:
        if closure.get("closure_status") != "qualifying_no_add":
            streak = []
            reset_round_ids.append(closure["round_id"])
        else:
            streak.append(closure)
    blockers: list[str] = []
    qualifying_pair: list[dict[str, Any]] = []
    if len(streak) < 2:
        blockers.append("latest consecutive qualifying_no_add streak has fewer than two rounds")
    else:
        qualifying_pair = streak[-2:]
        first, second = qualifying_pair
        if set(first["request_ids"]) & set(second["request_ids"]):
            blockers.append("request IDs are reused across the final two rounds")
        if set(first["query_ids"]) & set(second["query_ids"]):
            blockers.append("query IDs are reused across the final two rounds")
        first_axis = first["search_axis"]
        second_axis = second["search_axis"]
        if first_axis["dimension"] == second_axis["dimension"]:
            blockers.append("search-axis dimensions are not orthogonal")
        if first_axis["provider_families"] == second_axis["provider_families"]:
            blockers.append("search-axis provider families are not orthogonal")
        if set(first["selected_hypothesis_ids"]) & set(second["selected_hypothesis_ids"]):
            blockers.append("selected hypothesis IDs overlap")
        if set(first_axis["normalized_queries"]) & set(second_axis["normalized_queries"]):
            blockers.append("normalized queries overlap")
        if first_axis["fingerprint"] == second_axis["fingerprint"]:
            blockers.append("search-axis fingerprints are identical")
        if _network_fingerprint(first["network_after"]) != _network_fingerprint(
            second["network_before"]
        ):
            blockers.append("final rounds do not bind the same frozen network content")
        if _network_fingerprint(first["network_before"]) != _network_fingerprint(
            second["network_after"]
        ):
            blockers.append("authoritative network content drifted across final rounds")
    pragmatic_saturation = bool(qualifying_pair) and not blockers
    input_ref = {
        "path": str(manifest_path.absolute()),
        "sha256": require_hex(manifest_sha256, "streak input sha256"),
    }
    payload = {
        "schema": STREAK_OUTPUT_SCHEMA,
        "assessed_at": assessed_at,
        "streak_input_ref": input_ref,
        "input_manifest_sha256": manifest_sha256,
        "status": (
            "pragmatic_saturation"
            if pragmatic_saturation
            else "insufficient_qualifying_streak"
        ),
        "pragmatic_saturation": pragmatic_saturation,
        "qualifying_round_ids": [row["round_id"] for row in qualifying_pair],
        "latest_qualifying_streak_length": len(streak),
        "reset_round_ids": reset_round_ids,
        "blockers": blockers,
        "axis_plan_binding": _axis_plan_binding(plan_ref, plan),
        "closure_bindings": bindings,
        "claim_scope": "bounded_countercheck_only",
        "systematic_review_completeness": False,
        "domain_completeness": False,
    }
    return _sealed_payload(payload, "countercheck-streak-")


def replay_streak_assessment(value: Any) -> dict[str, Any]:
    assessment = require_dict(value, "streak assessment")
    _validate_sealed(assessment, STREAK_OUTPUT_SCHEMA, "countercheck-streak-")
    input_ref, manifest = load_artifact_ref(
        assessment.get("streak_input_ref"), "streak assessment.streak_input_ref"
    )
    expected = assess_streak(
        manifest,
        input_ref["sha256"],
        Path(require_string(input_ref.get("path"), "streak input path")),
    )
    if expected != assessment:
        raise ContractError("streak assessment does not match replayed artifact references")
    return expected


def load_input(path: Path, label: str) -> tuple[dict[str, Any], str]:
    return read_json_file(path.absolute(), label)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    for name in ("close-round", "assess-streak"):
        command = subparsers.add_parser(name)
        command.add_argument("--input", required=True)
        command.add_argument("--output", required=True)
    validate = subparsers.add_parser("validate")
    validate.add_argument("--input", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        input_path = Path(args.input).absolute()
        value, digest = load_input(input_path, "input")
        if args.command == "close-round":
            output = close_round(value, digest, input_path)
            write_json(Path(args.output), output)
        elif args.command == "assess-streak":
            output = assess_streak(value, digest, input_path)
            write_json(Path(args.output), output)
        else:
            schema = value.get("schema")
            if schema == ROUND_OUTPUT_SCHEMA:
                replay_round_closure(value)
            elif schema == STREAK_OUTPUT_SCHEMA:
                replay_streak_assessment(value)
            elif schema == AXIS_PLAN_SCHEMA:
                validate_axis_plan(value)
            else:
                raise ContractError("unsupported validation schema")
    except (ContractError, OSError) as exc:
        print(f"countercheck closure failed: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
