#!/usr/bin/env python3
"""Strict, acceptance-gated consumer for knowledge-network patch proposals."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import io
import json
import os
import re
import shutil
import stat
import sys
import tempfile
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime
from pathlib import Path
from typing import Any

import knowledge_network as kn


PATCH_V1_SCHEMA = "NetworkPatchProposal/v1"
PATCH_V2_SCHEMA = "NetworkPatchProposal/v2"
PLAN_SCHEMA = "NetworkPatchPlan/v1"
ACCEPTANCE_SCHEMA = "NetworkPatchAcceptance/v1"
VALIDATION_SCHEMA = "NetworkPatchValidation/v1"
APPLICATION_SCHEMA = "NetworkPatchApplicationResult/v1"
EVIDENCE_PACK_SCHEMA = "NetworkPatchEvidencePack/v1"
TARGET_CLAIM_SCHEMA = "NetworkPatchTargetClaim/v1"

HEX64_RE = re.compile(r"[0-9a-f]{64}")
UTC_RE = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z")
ACTION_TYPES = {"propose_node", "propose_relation", "propose_evidence"}
ACTION_FOR_TARGET_KIND = {
    "node": "propose_node",
    "relation": "propose_relation",
    "evidence": "propose_evidence",
    "boundary": "propose_evidence",
    "counterexample": "propose_evidence",
    "version": "propose_evidence",
    "benchmark": "propose_evidence",
    "benchmark_profile": "propose_evidence",
    "assumption": "propose_evidence",
    "mechanism": "propose_evidence",
    "metric": "propose_evidence",
    "measurement": "propose_evidence",
    "estimator": "propose_evidence",
    "failure_mode": "propose_evidence",
    "context": "propose_evidence",
}
DECISIONS = {"accept", "reject", "defer"}
INSPECTION_DEPTHS = {"evidence", "reconstruction"}
VERIFICATION_MODES = {"independent_source_check", "expert_review"}
OPERATION_TYPES = {
    "add-claim",
    "add-evidence",
    "add-relation",
    "transition-gap",
}

EVIDENCE_PACK_FILE_ROLES = {
    "hypotheses",
    "review_requests",
    "reading_reports",
    "dossier",
    "source_bundle",
    "source_artifact",
}

OPERATION_PAYLOAD_FIELDS = {
    "add-claim": {
        "claim_id",
        "claim_text",
        "entity_id",
        "impact",
        "scope_statement",
        "assumptions",
        "conditions",
        "units",
        "exclusions",
        "defeaters",
        "coverage_dimensions",
        "benchmark_profiles",
        "supersedes",
    },
    "add-evidence": {
        "evidence_id",
        "claim_id",
        "source_id",
        "polarity",
        "exact_locator",
        "independence_group",
        "summary",
        "notes",
        "supersedes",
    },
    "add-relation": {
        "relation_id",
        "relation_type",
        "from_ref",
        "to_ref",
        "notes",
        "supersedes",
    },
    "transition-gap": {
        "gap_id",
        "from_record_id",
        "status",
        "reason",
        "evidence_refs",
        "resolution_source",
    },
}

BASIS_FIELDS = {
    "basis_id",
    "basis_digest",
    "review_request_id",
    "review_request_digest",
    "report_set_id",
    "report_set_digest",
    "dossier_id",
    "dossier_digest",
    "reading_report_id",
    "reading_report_digest",
    "source_bundle_id",
    "source_bundle_digest",
    "source_artifact_sha256",
    "source_id",
    "source_digest",
    "claim_id",
    "claim_digest",
    "evidence_id",
    "evidence_digest",
    "span_id",
    "span_hash",
    "source_ref",
    "acquisition_locator",
    "evidence_locator",
    "relation",
    "access_level",
    "inspection_depth",
    "claim_support_eligible",
    "projection_status",
    "verification",
}


def canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def digest_json(value: Any) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def without(value: dict[str, Any], *fields: str) -> dict[str, Any]:
    return {key: item for key, item in value.items() if key not in fields}


def require_object(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be an object")
    return value


def require_keys(value: dict[str, Any], fields: set[str], label: str) -> None:
    missing = sorted(fields - set(value))
    unknown = sorted(set(value) - fields)
    if missing or unknown:
        parts = []
        if missing:
            parts.append(f"missing={missing}")
        if unknown:
            parts.append(f"unknown={unknown}")
        raise ValueError(f"{label} fields invalid: {', '.join(parts)}")


def require_string(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be a non-empty string")
    return value


def require_digest(value: Any, label: str) -> str:
    digest = require_string(value, label)
    if not HEX64_RE.fullmatch(digest):
        raise ValueError(f"{label} must be 64 lowercase hexadecimal characters")
    return digest


def require_timestamp(value: Any, label: str) -> str:
    timestamp = require_string(value, label)
    if not UTC_RE.fullmatch(timestamp):
        raise ValueError(f"{label} must be second-precision UTC ending in Z")
    try:
        datetime.strptime(timestamp, "%Y-%m-%dT%H:%M:%SZ")
    except ValueError as exc:
        raise ValueError(f"{label} is not a valid UTC timestamp") from exc
    return timestamp


def require_unique(values: list[str], label: str) -> None:
    if len(values) != len(set(values)):
        raise ValueError(f"{label} contains duplicates")


def target_claim_id(action: dict[str, Any]) -> str:
    target_claim = action.get("target_claim")
    if not isinstance(target_claim, dict):
        raise ValueError("propose_relation requires a closed target_claim payload")
    return target_claim["claim_id"]


def source_independence_group(basis: dict[str, Any]) -> str:
    """Group evidence by source lineage, never by its verifier identity."""
    return require_string(basis.get("source_id"), "basis.source_id")


def validate_target_claim(
    action: dict[str, Any], reviewed: list[dict[str, Any]], label: str
) -> dict[str, Any]:
    target = require_object(action.get("target_claim"), f"{label}.target_claim")
    require_keys(
        target,
        {
            "schema",
            "schema_version",
            "claim_id",
            "claim_text",
            "entity_id",
            "impact",
            "coverage_dimensions",
            "benchmark_profiles",
            "supersedes",
            "epistemic_status",
            "gap_hypothesis_id",
            "target_signature",
            "report_claim_id",
            "report_claim_digest",
            "scope",
            "scope_digest",
            "target_claim_digest",
        },
        f"{label}.target_claim",
    )
    if target["schema"] != TARGET_CLAIM_SCHEMA or target["schema_version"] != "1.0":
        raise ValueError(f"{label}.target_claim schema/version mismatch")
    require_string(target["claim_text"], f"{label}.target_claim.claim_text")
    if target["entity_id"] is not None:
        require_string(target["entity_id"], f"{label}.target_claim.entity_id")
    if target["impact"] not in kn.IMPACTS:
        raise ValueError(f"{label}.target_claim.impact is invalid")
    if target["supersedes"] is not None:
        raise ValueError(f"{label}.target_claim.supersedes must be null")
    for field in ("coverage_dimensions", "benchmark_profiles"):
        values = target[field]
        if not isinstance(values, list) or any(
            not isinstance(item, str) or not item for item in values
        ):
            raise ValueError(
                f"{label}.target_claim.{field} must be a string list"
            )
        require_unique(values, f"{label}.target_claim.{field}")

    scope = require_object(target["scope"], f"{label}.target_claim.scope")
    require_keys(
        scope,
        {
            "scope_statement",
            "assumptions",
            "conditions",
            "units",
            "exclusions",
            "defeaters",
            "coverage_dimensions",
            "benchmark_profiles",
        },
        f"{label}.target_claim.scope",
    )
    require_string(
        scope["scope_statement"], f"{label}.target_claim.scope.scope_statement"
    )
    for field in (
        "assumptions",
        "conditions",
        "units",
        "exclusions",
        "defeaters",
        "coverage_dimensions",
        "benchmark_profiles",
    ):
        values = scope[field]
        if not isinstance(values, list) or any(
            not isinstance(item, str) or not item for item in values
        ):
            raise ValueError(f"{label}.target_claim.scope.{field} must be a string list")
        require_unique(values, f"{label}.target_claim.scope.{field}")
    if scope["coverage_dimensions"] != target["coverage_dimensions"] or scope[
        "benchmark_profiles"
    ] != target["benchmark_profiles"]:
        raise ValueError(f"{label}.target_claim scope/profile projection mismatch")
    if target["scope_digest"] != digest_json(scope):
        raise ValueError(f"{label}.target_claim.scope_digest mismatch")

    if target["gap_hypothesis_id"] != action["hypothesis_id"]:
        raise ValueError(f"{label}.target_claim gap hypothesis mismatch")
    if target["target_signature"] != action["target_signature"]:
        raise ValueError(f"{label}.target_claim target signature mismatch")
    require_string(target["report_claim_id"], f"{label}.target_claim.report_claim_id")
    require_digest(
        target["report_claim_digest"], f"{label}.target_claim.report_claim_digest"
    )
    matches = [
        basis
        for basis in reviewed
        if basis["claim_id"] == target["report_claim_id"]
        and basis["claim_digest"] == target["report_claim_digest"]
    ]
    if not matches:
        raise ValueError(f"{label}.target_claim does not bind a reviewed report claim")

    epistemic = require_object(
        target["epistemic_status"], f"{label}.target_claim.epistemic_status"
    )
    require_keys(
        epistemic,
        {
            "projection_status",
            "claim_support_eligible",
            "inspection_depth",
            "relation",
        },
        f"{label}.target_claim.epistemic_status",
    )
    if not any(
        epistemic
        == {
            "projection_status": basis["projection_status"],
            "claim_support_eligible": basis["claim_support_eligible"],
            "inspection_depth": basis["inspection_depth"],
            "relation": basis["relation"],
        }
        for basis in matches
    ):
        raise ValueError(f"{label}.target_claim epistemic status mismatch")

    expected = digest_json(without(target, "claim_id", "target_claim_digest"))
    if target["target_claim_digest"] != expected:
        raise ValueError(f"{label}.target_claim_digest mismatch")
    if target["claim_id"] != f"claim-target-{expected[:16]}":
        raise ValueError(f"{label}.target_claim.claim_id mismatch")
    return target


def relation_operation_id(
    action: dict[str, Any], basis: dict[str, Any]
) -> str:
    subject = {
        "target_signature": action["target_signature"],
        "target_claim_id": target_claim_id(action),
        "basis_id": basis["basis_id"],
        "basis_digest": basis["basis_digest"],
        "evidence_id": basis["evidence_id"],
        "relation_type": "supports",
    }
    return "relation-" + digest_json(subject)[:16]


def current_network_ref(
    paths: kn.Paths,
    state: dict[str, Any],
    records: dict[str, list[dict[str, Any]]],
) -> dict[str, str]:
    exported = kn._knowledge_network_export(paths, state, records)
    return {
        "network_id": paths.network_id,
        "snapshot_id": str(exported["snapshot_id"]),
        "sha256": str(exported["content_sha256"]),
    }


def validate_network_ref(
    value: Any, expected: dict[str, str], label: str
) -> dict[str, str]:
    network_ref = require_object(value, label)
    require_keys(network_ref, {"network_id", "snapshot_id", "sha256"}, label)
    require_string(network_ref["network_id"], f"{label}.network_id")
    require_string(network_ref["snapshot_id"], f"{label}.snapshot_id")
    require_digest(network_ref["sha256"], f"{label}.sha256")
    if network_ref != expected:
        raise ValueError(f"{label} is stale or does not match the current network")
    return network_ref


def validate_v1_audit(value: Any, network_ref: dict[str, str]) -> dict[str, Any]:
    proposal = require_object(value, "proposal")
    require_keys(
        proposal,
        {
            "schema",
            "proposal_id",
            "network_ref",
            "generated_at",
            "basis_gap_ids",
            "proposal_only",
            "novelty_claimed",
            "nodes",
            "relations",
            "evidence",
            "review_gate",
        },
        "proposal",
    )
    if proposal["schema"] != PATCH_V1_SCHEMA:
        raise ValueError(f"proposal.schema must equal {PATCH_V1_SCHEMA}")
    require_string(proposal["proposal_id"], "proposal.proposal_id")
    validate_network_ref(proposal["network_ref"], network_ref, "proposal.network_ref")
    require_timestamp(proposal["generated_at"], "proposal.generated_at")
    gaps = proposal["basis_gap_ids"]
    if not isinstance(gaps, list) or not all(
        isinstance(item, str) and item.strip() for item in gaps
    ):
        raise ValueError("proposal.basis_gap_ids must be a string list")
    require_unique(gaps, "proposal.basis_gap_ids")
    if proposal["proposal_only"] is not True or proposal["novelty_claimed"] is not False:
        raise ValueError("v1 proposal must remain proposal-only and non-novelty")
    if proposal["review_gate"] != "pending_research_knowledge_network_validation":
        raise ValueError("v1 proposal review_gate is invalid")
    for collection in ("nodes", "relations", "evidence"):
        if not isinstance(proposal[collection], list):
            raise ValueError(f"proposal.{collection} must be a list")
    return proposal


def validate_basis(value: Any, label: str) -> dict[str, Any]:
    basis = require_object(value, label)
    require_keys(basis, BASIS_FIELDS, label)
    string_fields = {
        "review_request_id",
        "report_set_id",
        "dossier_id",
        "reading_report_id",
        "source_bundle_id",
        "source_id",
        "claim_id",
        "evidence_id",
        "span_id",
        "source_ref",
        "acquisition_locator",
        "evidence_locator",
    }
    digest_fields = {
        "review_request_digest",
        "report_set_digest",
        "dossier_digest",
        "reading_report_digest",
        "source_bundle_digest",
        "source_artifact_sha256",
        "source_digest",
        "claim_digest",
        "evidence_digest",
        "span_hash",
    }
    for field in string_fields:
        require_string(basis[field], f"{label}.{field}")
    for field in digest_fields:
        require_digest(basis[field], f"{label}.{field}")
    if Path(basis["source_ref"]).name != basis["source_ref"] or "://" in basis[
        "source_ref"
    ]:
        raise ValueError(f"{label}.source_ref must be a local artifact filename")
    if "://" in basis["evidence_locator"]:
        raise ValueError(f"{label}.evidence_locator must be source-rooted, not a URL")
    if basis["relation"] != "supports":
        raise ValueError(f"{label}.relation must be supports")
    if basis["access_level"] != "full_text":
        raise ValueError(f"{label}.access_level must be full_text")
    if basis["inspection_depth"] not in INSPECTION_DEPTHS:
        raise ValueError(f"{label}.inspection_depth is not eligible")
    if basis["claim_support_eligible"] is not True:
        raise ValueError(f"{label}.claim_support_eligible must be true")
    if basis["projection_status"] != "decisive":
        raise ValueError(f"{label}.projection_status must be decisive")
    verification = require_object(basis["verification"], f"{label}.verification")
    require_keys(
        verification,
        {"mode", "verifier_id", "artifact_sha256"},
        f"{label}.verification",
    )
    if verification["mode"] not in VERIFICATION_MODES:
        raise ValueError(f"{label}.verification.mode is not independently eligible")
    require_string(verification["verifier_id"], f"{label}.verification.verifier_id")
    require_digest(
        verification["artifact_sha256"], f"{label}.verification.artifact_sha256"
    )
    expected = digest_json(without(basis, "basis_id", "basis_digest"))
    if basis["basis_digest"] != expected:
        raise ValueError(f"{label}.basis_digest mismatch")
    if basis["basis_id"] != f"network-patch-basis-{expected[:16]}":
        raise ValueError(f"{label}.basis_id mismatch")
    return basis


def validate_proposal_v2(
    value: Any, network_ref: dict[str, str]
) -> dict[str, Any]:
    proposal = require_object(value, "proposal")
    require_keys(
        proposal,
        {
            "schema",
            "schema_version",
            "proposal_id",
            "proposal_digest",
            "network_ref",
            "request_ref",
            "generated_at",
            "proposal_only",
            "novelty_claimed",
            "review_gate",
            "actions",
        },
        "proposal",
    )
    if proposal["schema"] != PATCH_V2_SCHEMA or proposal["schema_version"] != "2.0":
        raise ValueError("proposal must use NetworkPatchProposal/v2 schema_version 2.0")
    validate_network_ref(proposal["network_ref"], network_ref, "proposal.network_ref")
    request_ref = require_object(proposal["request_ref"], "proposal.request_ref")
    require_keys(
        request_ref,
        {
            "request_set_id",
            "request_set_digest",
            "review_request_set_id",
            "review_request_set_digest",
        },
        "proposal.request_ref",
    )
    for field in ("request_set_id", "review_request_set_id"):
        require_string(request_ref[field], f"proposal.request_ref.{field}")
    for field in ("request_set_digest", "review_request_set_digest"):
        require_digest(request_ref[field], f"proposal.request_ref.{field}")
    require_timestamp(proposal["generated_at"], "proposal.generated_at")
    if proposal["proposal_only"] is not True or proposal["novelty_claimed"] is not False:
        raise ValueError("proposal must remain proposal-only and non-novelty")
    if proposal["review_gate"] != "pending_research_knowledge_network_acceptance":
        raise ValueError("proposal.review_gate must remain pending acceptance")
    actions = proposal["actions"]
    if not isinstance(actions, list):
        raise ValueError("proposal.actions must be a list")
    action_ids: list[str] = []
    action_digests: list[str] = []
    hypothesis_ids: list[str] = []
    report_sets: set[tuple[str, str]] = set()
    for index, raw_action in enumerate(actions):
        label = f"proposal.actions[{index}]"
        action = require_object(raw_action, label)
        action_type = action.get("action_type")
        action_fields = {
            "action_id",
            "action_digest",
            "action_type",
            "action_status",
            "hypothesis_id",
            "target_signature",
            "hypothesis",
            "reviewed_evidence",
        }
        if action_type == "propose_relation":
            action_fields.add("target_claim")
        require_keys(
            action,
            action_fields,
            label,
        )
        if action["action_type"] not in ACTION_TYPES:
            raise ValueError(f"{label}.action_type is invalid")
        if action["action_status"] not in {"proposed", "blocked"}:
            raise ValueError(f"{label}.action_status must be proposed or blocked")
        require_string(action["hypothesis_id"], f"{label}.hypothesis_id")
        require_string(action["hypothesis"], f"{label}.hypothesis")
        signature = require_object(action["target_signature"], f"{label}.target_signature")
        require_keys(signature, {"target_kind", "signature"}, f"{label}.target_signature")
        target_kind = signature.get("target_kind")
        if target_kind not in ACTION_FOR_TARGET_KIND:
            raise ValueError(f"{label}.target_signature.target_kind is invalid")
        if action["action_type"] != ACTION_FOR_TARGET_KIND[target_kind]:
            raise ValueError(f"{label}.target_signature.target_kind mismatch")
        require_string(signature["signature"], f"{label}.target_signature.signature")
        reviewed = action["reviewed_evidence"]
        if not isinstance(reviewed, list) or not reviewed:
            raise ValueError(f"{label}.reviewed_evidence must be non-empty")
        basis_ids: list[str] = []
        basis_digests: list[str] = []
        for basis_index, raw_basis in enumerate(reviewed):
            basis = validate_basis(
                raw_basis, f"{label}.reviewed_evidence[{basis_index}]"
            )
            basis_ids.append(basis["basis_id"])
            basis_digests.append(basis["basis_digest"])
            report_sets.add((basis["report_set_id"], basis["report_set_digest"]))
        require_unique(basis_ids, f"{label} basis IDs")
        require_unique(basis_digests, f"{label} basis digests")
        expected_status = "blocked"
        if action["action_type"] == "propose_relation" or (
            action["action_type"] == "propose_evidence"
            and target_kind == "evidence"
            and len(reviewed) == 1
            and signature["signature"] == reviewed[0]["evidence_id"]
        ):
            expected_status = "proposed"
        if action["action_status"] != expected_status:
            raise ValueError(
                f"{label}.action_status does not match materialization eligibility"
            )
        if action["action_type"] == "propose_relation":
            validate_target_claim(action, reviewed, label)
        expected = digest_json(without(action, "action_id", "action_digest"))
        if action["action_digest"] != expected:
            raise ValueError(f"{label}.action_digest mismatch")
        if action["action_id"] != f"network-patch-action-{expected[:16]}":
            raise ValueError(f"{label}.action_id mismatch")
        action_ids.append(action["action_id"])
        action_digests.append(action["action_digest"])
        hypothesis_ids.append(action["hypothesis_id"])
    require_unique(action_ids, "proposal action IDs")
    require_unique(action_digests, "proposal action digests")
    require_unique(hypothesis_ids, "proposal hypothesis IDs")
    if len(report_sets) > 1:
        raise ValueError("proposal actions must bind one report set")
    expected = digest_json(without(proposal, "proposal_id", "proposal_digest"))
    if proposal["proposal_digest"] != expected:
        raise ValueError("proposal.proposal_digest mismatch")
    if proposal["proposal_id"] != f"network-patch-proposal-{expected[:16]}":
        raise ValueError("proposal.proposal_id mismatch")
    return proposal


def _canonical_absolute_path(raw: Any, label: str) -> Path:
    text = require_string(raw, label)
    path = Path(text)
    if not path.is_absolute() or Path(os.path.normpath(text)) != path:
        raise ValueError(f"{label} must be a canonical absolute path")
    current = Path(path.anchor)
    for part in path.parts[1:]:
        current = current / part
        try:
            metadata = current.lstat()
        except OSError as exc:
            raise ValueError(f"{label} is unavailable: {current}") from exc
        if stat.S_ISLNK(metadata.st_mode):
            raise ValueError(f"{label} contains a symbolic-link component")
    return path


def _stable_file_bytes(path: Path, label: str) -> tuple[bytes, str]:
    path = _canonical_absolute_path(str(path), label)
    if not path.is_file():
        raise ValueError(f"{label} must be a regular file")
    descriptor, path_before, descriptor_before = kn._open_stable_snapshot(path)
    try:
        raw, digest, descriptor_after = kn._read_snapshot_descriptor(descriptor)
    finally:
        os.close(descriptor)
    kn._verify_snapshot_unchanged(
        path, path_before, descriptor_before, descriptor_after
    )
    if len(raw) != descriptor_after.st_size:
        raise ValueError(f"{label} size changed during read")
    return raw, digest.removeprefix("sha256:")


def _json_from_stable_file(path: Path, label: str) -> tuple[dict[str, Any], str]:
    raw, digest = _stable_file_bytes(path, label)
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"{label} must be UTF-8 JSON") from exc
    return require_object(value, label), digest


def _verification_tree_snapshot(
    raw_root: Any,
) -> tuple[Path, str, dict[str, bytes]]:
    root = _canonical_absolute_path(raw_root, "evidence_pack.verification_root.path")
    if not root.is_dir():
        raise ValueError("evidence_pack.verification_root.path must be a directory")
    rows: list[dict[str, Any]] = []
    files: dict[str, bytes] = {}
    for directory, dir_names, file_names in os.walk(root, followlinks=False):
        directory_path = Path(directory)
        dir_names.sort()
        file_names.sort()
        for name in dir_names:
            child = directory_path / name
            if child.is_symlink():
                raise ValueError("verification root contains a symlink directory")
        for name in file_names:
            child = directory_path / name
            raw, digest = _stable_file_bytes(child, "verification artifact")
            relative = child.relative_to(root).as_posix()
            files[relative] = raw
            rows.append(
                {
                    "path": relative,
                    "sha256": digest,
                    "size_bytes": len(raw),
                }
            )
    if not rows:
        raise ValueError("verification root must contain at least one artifact")
    return root, digest_json(rows), files


def _verification_tree_digest(raw_root: Any) -> tuple[Path, str]:
    root, digest, _ = _verification_tree_snapshot(raw_root)
    return root, digest


def _write_private_snapshot(path: Path, raw: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(
        path,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_CLOEXEC", 0),
        0o600,
    )
    try:
        view = memoryview(raw)
        while view:
            written = os.write(descriptor, view)
            view = view[written:]
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _bundle_artifact_snapshot(
    manifest: dict[str, Any], manifest_path: Path
) -> dict[str, bytes]:
    artifacts: dict[str, bytes] = {}
    rows = [*manifest.get("pages", []), *manifest.get("rendered_pages", [])]
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            raise ValueError(f"source bundle artifact[{index}] must be an object")
        relative_text = require_string(
            row.get("artifact_path"), f"source bundle artifact[{index}].artifact_path"
        )
        relative = Path(relative_text)
        if (
            relative.is_absolute()
            or ".." in relative.parts
            or Path(os.path.normpath(relative_text)) != relative
        ):
            raise ValueError("source bundle artifact path is unsafe")
        artifact_path = manifest_path.parent / relative
        raw, _ = _stable_file_bytes(artifact_path, "source bundle artifact")
        artifacts[relative.as_posix()] = raw
    return artifacts


def validate_evidence_pack(
    value: Any,
    proposal: dict[str, Any],
    network_ref: dict[str, str],
    *,
    live_network: dict[str, Any],
    regenerate: bool = True,
) -> dict[str, Any]:
    pack = require_object(value, "evidence_pack")
    require_keys(
        pack,
        {
            "schema",
            "schema_version",
            "pack_id",
            "pack_digest",
            "proposal_ref",
            "network_ref",
            "artifacts",
            "verification_root",
        },
        "evidence_pack",
    )
    if pack["schema"] != EVIDENCE_PACK_SCHEMA or pack["schema_version"] != "1.0":
        raise ValueError("evidence_pack schema/version invalid")
    validate_network_ref(pack["network_ref"], network_ref, "evidence_pack.network_ref")
    proposal_ref = require_object(pack["proposal_ref"], "evidence_pack.proposal_ref")
    require_keys(
        proposal_ref, {"proposal_id", "proposal_digest"}, "evidence_pack.proposal_ref"
    )
    expected_proposal_digest = proposal.get("proposal_digest") or digest_json(proposal)
    if proposal_ref != {
        "proposal_id": proposal["proposal_id"],
        "proposal_digest": expected_proposal_digest,
    }:
        raise ValueError("evidence_pack proposal binding mismatch")
    artifacts = require_object(pack["artifacts"], "evidence_pack.artifacts")
    require_keys(artifacts, EVIDENCE_PACK_FILE_ROLES, "evidence_pack.artifacts")
    loaded: dict[str, Any] = {}
    raw_files: dict[str, bytes] = {}
    paths: dict[str, Path] = {}
    for role in sorted(EVIDENCE_PACK_FILE_ROLES):
        label = f"evidence_pack.artifacts.{role}"
        reference = require_object(artifacts[role], label)
        require_keys(reference, {"path", "sha256"}, label)
        path = _canonical_absolute_path(reference["path"], f"{label}.path")
        declared = require_digest(reference["sha256"], f"{label}.sha256")
        paths[role] = path
        raw, observed = _stable_file_bytes(path, label)
        raw_files[role] = raw
        if role == "source_artifact":
            loaded[role] = None
        else:
            try:
                loaded[role] = require_object(
                    json.loads(raw.decode("utf-8")), label
                )
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise ValueError(f"{label} must be UTF-8 JSON") from exc
        if declared != observed:
            raise ValueError(f"{label}.sha256 mismatch")
    verification_ref = require_object(
        pack["verification_root"], "evidence_pack.verification_root"
    )
    require_keys(
        verification_ref,
        {"path", "tree_sha256"},
        "evidence_pack.verification_root",
    )
    verification_root, tree_digest, verification_files = _verification_tree_snapshot(
        verification_ref["path"]
    )
    if require_digest(
        verification_ref["tree_sha256"],
        "evidence_pack.verification_root.tree_sha256",
    ) != tree_digest:
        raise ValueError("evidence_pack verification tree digest mismatch")
    expected_pack_digest = digest_json(without(pack, "pack_id", "pack_digest"))
    if pack["pack_digest"] != expected_pack_digest:
        raise ValueError("evidence_pack.pack_digest mismatch")
    if pack["pack_id"] != f"network-patch-evidence-pack-{expected_pack_digest[:16]}":
        raise ValueError("evidence_pack.pack_id mismatch")
    if regenerate:
        module = load_gap_module()
        bundle_artifacts = _bundle_artifact_snapshot(
            loaded["source_bundle"], paths["source_bundle"]
        )
        with tempfile.TemporaryDirectory(prefix="rkn-evidence-snapshot-") as raw_stage:
            stage = Path(raw_stage)
            bundle_path = stage / "bundle" / paths["source_bundle"].name
            source_path = stage / "source" / paths["source_artifact"].name
            verification_path = stage / "verification"
            _write_private_snapshot(bundle_path, raw_files["source_bundle"])
            _write_private_snapshot(source_path, raw_files["source_artifact"])
            for relative, raw in bundle_artifacts.items():
                _write_private_snapshot(bundle_path.parent / relative, raw)
            for relative, raw in verification_files.items():
                _write_private_snapshot(verification_path / relative, raw)
            try:
                regenerated = module.propose_patch(
                    loaded["hypotheses"],
                    live_network,
                    loaded["review_requests"],
                    loaded["reading_reports"],
                    loaded["dossier"],
                    source_bundle_path=bundle_path,
                    source_artifact_path=source_path,
                    verification_root=verification_path,
                )
            except Exception as exc:
                raise ValueError(
                    f"strict upstream evidence reopening failed: {exc}"
                ) from exc
        for role, original_path in paths.items():
            current_raw, _ = _stable_file_bytes(
                original_path, f"evidence_pack.artifacts.{role} postcheck"
            )
            if current_raw != raw_files[role]:
                raise ValueError(
                    f"evidence_pack artifact drifted during regeneration: {role}"
                )
        _, current_tree_digest, current_verification_files = (
            _verification_tree_snapshot(str(verification_root))
        )
        if (
            current_tree_digest != tree_digest
            or current_verification_files != verification_files
        ):
            raise ValueError(
                "evidence_pack verification tree drifted during regeneration"
            )
        current_bundle_artifacts = _bundle_artifact_snapshot(
            loaded["source_bundle"], paths["source_bundle"]
        )
        if current_bundle_artifacts != bundle_artifacts:
            raise ValueError(
                "evidence_pack source bundle artifact drifted during regeneration"
            )
        if regenerated != proposal:
            raise ValueError(
                "strict upstream regeneration does not match proposal digest/payload"
            )
    return pack


def load_gap_module():
    path = (
        Path(__file__).resolve().parents[2]
        / "network-gap-discovery"
        / "scripts"
        / "network_gap_discovery.py"
    )
    name = "rkn_strict_network_gap_validator"
    existing = sys.modules.get(name)
    if existing is not None:
        return existing
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ValueError("strict network-gap validator is unavailable")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def create_plan(
    proposal: dict[str, Any],
    network_ref: dict[str, str],
    prepared_at: str | None = None,
) -> dict[str, Any]:
    plan: dict[str, Any] = {
        "schema": PLAN_SCHEMA,
        "schema_version": "1.0",
        "network_ref": network_ref,
        "proposal_ref": {
            "proposal_id": proposal["proposal_id"],
            "proposal_digest": proposal["proposal_digest"],
        },
        "prepared_at": prepared_at or kn._utcnow(),
        "apply_policy": "explicit_validated_acceptance_required",
        "actions": [
            {
                "action_id": action["action_id"],
                "action_digest": action["action_digest"],
                "action_type": action["action_type"],
                "action_status": (
                    "pending_acceptance"
                    if action["action_status"] == "proposed"
                    else "blocked"
                ),
                "allowed_operation_types": []
                if action["action_status"] == "blocked"
                else {
                    "propose_node": [],
                    "propose_relation": [
                        "add-claim",
                        "add-evidence",
                        "add-relation",
                        "transition-gap",
                    ],
                    "propose_evidence": ["add-evidence", "transition-gap"],
                }[action["action_type"]],
            }
            for action in proposal["actions"]
        ],
    }
    digest = digest_json(plan)
    plan["plan_id"] = f"network-patch-plan-{digest[:16]}"
    plan["plan_digest"] = digest
    return plan


def require_onboarded_sources(
    proposal: dict[str, Any], live_network: dict[str, Any]
) -> None:
    """Require source provenance to be onboarded before patch generation."""
    live_sources = {
        source["source_id"]: source
        for source in live_network.get("sources", [])
        if isinstance(source, dict) and isinstance(source.get("source_id"), str)
    }
    proposed_source_ids = {
        basis["source_id"]
        for action in proposal["actions"]
        for basis in action["reviewed_evidence"]
    }
    missing = sorted(proposed_source_ids - set(live_sources))
    version_mismatches = sorted(
        {
            basis["source_id"]
            for action in proposal["actions"]
            for basis in action["reviewed_evidence"]
            if basis["source_id"] in live_sources
            and live_sources[basis["source_id"]].get("version_hash")
            != "sha256:" + basis["source_artifact_sha256"]
        }
    )
    if missing or version_mismatches:
        raise ValueError(
            "source onboarding required before patch preparation; "
            f"missing source_id values: {missing}; artifact-version mismatches: "
            f"{version_mismatches}. Onboard the exact reviewed source version, "
            "export a new snapshot, and regenerate the gap audit and proposal."
        )


def validate_plan(
    value: Any, proposal: dict[str, Any], network_ref: dict[str, str]
) -> dict[str, Any]:
    plan = require_object(value, "plan")
    require_keys(
        plan,
        {
            "schema",
            "schema_version",
            "plan_id",
            "plan_digest",
            "network_ref",
            "proposal_ref",
            "prepared_at",
            "apply_policy",
            "actions",
        },
        "plan",
    )
    if plan["schema"] != PLAN_SCHEMA or plan["schema_version"] != "1.0":
        raise ValueError("plan schema/version invalid")
    validate_network_ref(plan["network_ref"], network_ref, "plan.network_ref")
    proposal_ref = require_object(plan["proposal_ref"], "plan.proposal_ref")
    require_keys(proposal_ref, {"proposal_id", "proposal_digest"}, "plan.proposal_ref")
    if proposal_ref != {
        "proposal_id": proposal["proposal_id"],
        "proposal_digest": proposal["proposal_digest"],
    }:
        raise ValueError("plan proposal binding mismatch")
    require_timestamp(plan["prepared_at"], "plan.prepared_at")
    if plan["apply_policy"] != "explicit_validated_acceptance_required":
        raise ValueError("plan.apply_policy invalid")
    expected_actions = create_plan(
        proposal, network_ref, prepared_at=plan["prepared_at"]
    )["actions"]
    if plan["actions"] != expected_actions:
        raise ValueError("plan.actions are not the canonical proposal projection")
    expected = digest_json(without(plan, "plan_id", "plan_digest"))
    if plan["plan_digest"] != expected:
        raise ValueError("plan.plan_digest mismatch")
    if plan["plan_id"] != f"network-patch-plan-{expected[:16]}":
        raise ValueError("plan.plan_id mismatch")
    return plan


def validate_operation(value: Any, label: str) -> dict[str, Any]:
    operation = require_object(value, label)
    require_keys(
        operation,
        {
            "operation_id",
            "operation_digest",
            "operation_type",
            "basis_refs",
            "payload",
        },
        label,
    )
    operation_type = operation["operation_type"]
    if operation_type not in OPERATION_TYPES:
        raise ValueError(f"{label}.operation_type invalid")
    payload = require_object(operation["payload"], f"{label}.payload")
    require_keys(payload, OPERATION_PAYLOAD_FIELDS[operation_type], f"{label}.payload")
    basis_refs = operation["basis_refs"]
    if not isinstance(basis_refs, list) or not basis_refs:
        raise ValueError(f"{label}.basis_refs must be non-empty")
    identities: list[tuple[str, str]] = []
    for index, raw_ref in enumerate(basis_refs):
        ref_label = f"{label}.basis_refs[{index}]"
        ref = require_object(raw_ref, ref_label)
        require_keys(ref, {"basis_id", "basis_digest"}, ref_label)
        require_string(ref["basis_id"], f"{ref_label}.basis_id")
        require_digest(ref["basis_digest"], f"{ref_label}.basis_digest")
        identities.append((ref["basis_id"], ref["basis_digest"]))
    if len(identities) != len(set(identities)):
        raise ValueError(f"{label}.basis_refs contains duplicates")
    expected = digest_json(without(operation, "operation_id", "operation_digest"))
    if operation["operation_digest"] != expected:
        raise ValueError(f"{label}.operation_digest mismatch")
    if operation["operation_id"] != f"network-operation-{expected[:16]}":
        raise ValueError(f"{label}.operation_id mismatch")
    return operation


def validate_authority_basis(value: Any, label: str) -> dict[str, Any]:
    basis = require_object(value, label)
    require_keys(
        basis,
        {"basis_id", "basis_type", "source_ref", "locator", "artifact_sha256"},
        label,
    )
    if basis["basis_type"] not in {
        "expert_review",
        "curation_policy",
        "user_authorization",
    }:
        raise ValueError(f"{label}.basis_type invalid")
    require_string(basis["source_ref"], f"{label}.source_ref")
    require_string(basis["locator"], f"{label}.locator")
    require_digest(basis["artifact_sha256"], f"{label}.artifact_sha256")
    expected = "patch-authority-basis-" + digest_json(without(basis, "basis_id"))[:16]
    if basis["basis_id"] != expected:
        raise ValueError(f"{label}.basis_id mismatch")
    return basis


def verify_authority_artifacts(
    acceptance: dict[str, Any], acceptance_path: str
) -> None:
    acceptance_file = _canonical_absolute_path(
        acceptance_path, "acceptance.path"
    )
    authority_root = acceptance_file.parent
    for index, basis in enumerate(acceptance["operator"]["authority_basis"]):
        relative_text = basis["source_ref"]
        relative = Path(relative_text)
        if (
            relative.is_absolute()
            or ".." in relative.parts
            or Path(os.path.normpath(relative_text)) != relative
        ):
            raise ValueError(
                f"acceptance authority basis[{index}] source_ref is unsafe"
            )
        artifact = authority_root / relative
        if artifact == acceptance_file:
            raise ValueError("acceptance cannot cite itself as its authority artifact")
        _, digest = _stable_file_bytes(
            artifact, f"acceptance authority basis[{index}] artifact"
        )
        if digest != basis["artifact_sha256"]:
            raise ValueError(
                f"acceptance authority basis[{index}] artifact SHA-256 mismatch"
            )


def validate_acceptance(
    value: Any,
    proposal: dict[str, Any],
    plan: dict[str, Any],
    network_ref: dict[str, str],
) -> dict[str, Any]:
    acceptance = require_object(value, "acceptance")
    require_keys(
        acceptance,
        {
            "schema",
            "schema_version",
            "acceptance_id",
            "acceptance_digest",
            "network_ref",
            "proposal_ref",
            "plan_ref",
            "decided_at",
            "operator",
            "decisions",
        },
        "acceptance",
    )
    if acceptance["schema"] != ACCEPTANCE_SCHEMA or acceptance["schema_version"] != "1.0":
        raise ValueError("acceptance schema/version invalid")
    validate_network_ref(acceptance["network_ref"], network_ref, "acceptance.network_ref")
    proposal_ref = require_object(acceptance["proposal_ref"], "acceptance.proposal_ref")
    require_keys(
        proposal_ref, {"proposal_id", "proposal_digest"}, "acceptance.proposal_ref"
    )
    if proposal_ref != {
        "proposal_id": proposal["proposal_id"],
        "proposal_digest": proposal["proposal_digest"],
    }:
        raise ValueError("acceptance proposal binding mismatch")
    plan_ref = require_object(acceptance["plan_ref"], "acceptance.plan_ref")
    require_keys(plan_ref, {"plan_id", "plan_digest"}, "acceptance.plan_ref")
    if plan_ref != {"plan_id": plan["plan_id"], "plan_digest": plan["plan_digest"]}:
        raise ValueError("acceptance plan binding mismatch")
    require_timestamp(acceptance["decided_at"], "acceptance.decided_at")
    operator = require_object(acceptance["operator"], "acceptance.operator")
    require_keys(
        operator,
        {"operator_id", "operator_role", "authority_basis"},
        "acceptance.operator",
    )
    require_string(operator["operator_id"], "acceptance.operator.operator_id")
    require_string(operator["operator_role"], "acceptance.operator.operator_role")
    authority = operator["authority_basis"]
    if not isinstance(authority, list) or not authority:
        raise ValueError("acceptance.operator.authority_basis must be non-empty")
    authority_ids = [
        validate_authority_basis(
            item, f"acceptance.operator.authority_basis[{index}]"
        )["basis_id"]
        for index, item in enumerate(authority)
    ]
    require_unique(authority_ids, "acceptance authority basis IDs")
    decisions = acceptance["decisions"]
    if not isinstance(decisions, list) or len(decisions) != len(proposal["actions"]):
        raise ValueError("acceptance must decide every proposal action exactly once")
    operation_ids: list[str] = []
    operation_digests: list[str] = []
    for index, (raw_decision, action) in enumerate(zip(decisions, proposal["actions"])):
        label = f"acceptance.decisions[{index}]"
        decision = require_object(raw_decision, label)
        require_keys(
            decision,
            {
                "action_id",
                "action_digest",
                "decision",
                "rationale",
                "authority_basis_ids",
                "operations",
            },
            label,
        )
        if decision["action_id"] != action["action_id"] or decision[
            "action_digest"
        ] != action["action_digest"]:
            raise ValueError(f"{label} does not bind its ordered proposal action")
        if decision["decision"] not in DECISIONS:
            raise ValueError(f"{label}.decision invalid")
        require_string(decision["rationale"], f"{label}.rationale")
        cited = decision["authority_basis_ids"]
        if not isinstance(cited, list) or not cited:
            raise ValueError(f"{label}.authority_basis_ids must be non-empty")
        require_unique(cited, f"{label}.authority_basis_ids")
        if not set(cited).issubset(authority_ids):
            raise ValueError(f"{label} cites an unknown authority basis")
        operations = decision["operations"]
        if not isinstance(operations, list):
            raise ValueError(f"{label}.operations must be a list")
        if decision["decision"] == "accept" and not operations:
            raise ValueError(f"{label} accepted action requires typed operations")
        if decision["decision"] != "accept" and operations:
            raise ValueError(f"{label} reject/defer must not contain operations")
        if (
            decision["decision"] == "accept"
            and action["action_status"] == "blocked"
        ):
            raise ValueError(
                f"{label} blocked action cannot be accepted or applied"
            )
        operation_types: list[str] = []
        action_basis = {
            (basis["basis_id"], basis["basis_digest"]): basis
            for basis in action["reviewed_evidence"]
        }
        action_basis_order = list(action_basis)
        evidence_operations: list[tuple[dict[str, Any], dict[str, Any]]] = []
        relation_operations: list[dict[str, Any]] = []
        node_operations: list[tuple[dict[str, Any], dict[str, Any]]] = []
        transition_operations: list[dict[str, Any]] = []
        for op_index, raw_operation in enumerate(operations):
            operation = validate_operation(
                raw_operation, f"{label}.operations[{op_index}]"
            )
            operation_ids.append(operation["operation_id"])
            operation_digests.append(operation["operation_digest"])
            operation_types.append(operation["operation_type"])
            payload = operation["payload"]
            resolved_basis: list[dict[str, Any]] = []
            for raw_ref in operation["basis_refs"]:
                identity = (raw_ref["basis_id"], raw_ref["basis_digest"])
                basis = action_basis.get(identity)
                if basis is None:
                    raise ValueError(f"{label} operation uses a foreign evidence basis")
                resolved_basis.append(basis)
            if operation["operation_type"] == "add-evidence":
                if len(resolved_basis) != 1:
                    raise ValueError(f"{label} add-evidence must bind exactly one basis")
                basis = resolved_basis[0]
                expected_evidence = {
                    "evidence_id": basis["evidence_id"],
                    "claim_id": (
                        target_claim_id(action)
                        if action["action_type"] == "propose_relation"
                        else basis["claim_id"]
                    ),
                    "source_id": basis["source_id"],
                    "polarity": "supports",
                    "exact_locator": basis["evidence_locator"],
                    "independence_group": source_independence_group(basis),
                    "summary": action["hypothesis"],
                    "notes": "accepted from NetworkPatchProposal/v2",
                    "supersedes": None,
                }
                if payload != expected_evidence:
                    raise ValueError(
                        f"{label} add-evidence is not the exact reviewed projection; "
                        "supersedes must be null"
                    )
                evidence_operations.append((operation, basis))
            elif operation["operation_type"] == "add-relation":
                relation_operations.append(operation)
            elif operation["operation_type"] == "add-claim":
                if action["action_type"] == "propose_relation":
                    if {
                        (ref["basis_id"], ref["basis_digest"])
                        for ref in operation["basis_refs"]
                    } != set(action_basis_order):
                        raise ValueError(
                            f"{label} target claim must bind every action basis"
                        )
                    target = action["target_claim"]
                    expected_claim = {
                        field: target[field]
                        for field in (
                            "claim_id",
                            "claim_text",
                            "entity_id",
                            "impact",
                            "coverage_dimensions",
                            "benchmark_profiles",
                            "supersedes",
                        )
                    }
                    expected_claim.update(
                        {
                            "scope_statement": target["scope"]["scope_statement"],
                            **{
                                field: target["scope"][field]
                                for field in (
                                    "assumptions",
                                    "conditions",
                                    "units",
                                    "exclusions",
                                    "defeaters",
                                )
                            },
                        }
                    )
                    if payload != expected_claim:
                        raise ValueError(
                            f"{label} target claim is not the canonical semantic mapping"
                        )
                    node_operations.append((operation, resolved_basis[0]))
                else:
                    raise ValueError(
                        f"{label} propose_node acceptance requires a closed target_node"
                    )
            elif operation["operation_type"] == "transition-gap":
                if payload["gap_id"] != action["hypothesis_id"]:
                    raise ValueError(f"{label} gap transition targets another hypothesis")
                if {
                    (ref["basis_id"], ref["basis_digest"])
                    for ref in operation["basis_refs"]
                } != set(action_basis_order):
                    raise ValueError(f"{label} gap transition must bind every action basis")
                if set(payload["evidence_refs"]) != {
                    basis["evidence_id"] for basis in action["reviewed_evidence"]
                }:
                    raise ValueError(f"{label} gap transition evidence refs mismatch")
                transition_operations.append(operation)
        if decision["decision"] == "accept":
            if len(transition_operations) > 1 or (
                transition_operations
                and operations[-1]["operation_type"] != "transition-gap"
            ):
                raise ValueError(f"{label} allows at most one final gap transition")
            signature = action["target_signature"]["signature"]
            if action["action_type"] == "propose_relation":
                expected_types = (
                    ["add-claim"]
                    + ["add-evidence"] * len(action_basis)
                    + ["add-relation"] * len(action_basis)
                )
                if transition_operations:
                    expected_types.append("transition-gap")
                if operation_types != expected_types:
                    raise ValueError(f"{label} relation operation sequence is not canonical")
                if (
                    len(node_operations) != 1
                    or len(evidence_operations) != len(action_basis)
                    or len(relation_operations) != len(action_basis)
                ):
                    raise ValueError(f"{label} relation mapping is incomplete")
                observed_basis_order = [
                    (basis["basis_id"], basis["basis_digest"])
                    for _, basis in evidence_operations
                ]
                if observed_basis_order != action_basis_order:
                    raise ValueError(f"{label} evidence operations cross or reorder bases")
                for relation, identity in zip(
                    relation_operations, action_basis_order
                ):
                    basis = action_basis[identity]
                    relation_payload = relation["payload"]
                    if relation["basis_refs"] != [
                        {"basis_id": identity[0], "basis_digest": identity[1]}
                    ]:
                        raise ValueError(
                            f"{label} relation operation must bind one ordered basis"
                        )
                    expected_relation = {
                        "relation_id": relation_operation_id(action, basis),
                        "relation_type": "supports",
                        "from_ref": "claim:" + target_claim_id(action),
                        "to_ref": "evidence:" + basis["evidence_id"],
                        "notes": "network-patch-action:" + action["action_digest"],
                        "supersedes": None,
                    }
                    if relation_payload != expected_relation:
                        raise ValueError(
                            f"{label} relation does not materialize its semantic target/basis"
                        )
            elif action["action_type"] == "propose_evidence":
                expected_types = ["add-evidence"]
                if transition_operations:
                    expected_types.append("transition-gap")
                if operation_types != expected_types or len(action_basis) != 1:
                    raise ValueError(f"{label} evidence action requires one exact basis")
                if evidence_operations[0][0]["payload"]["evidence_id"] != signature:
                    raise ValueError(f"{label} evidence does not match target signature")
            else:
                raise ValueError(
                    f"{label} propose_node acceptance requires a closed target_node"
                )
    require_unique(operation_ids, "acceptance operation IDs")
    require_unique(operation_digests, "acceptance operation digests")
    expected = digest_json(
        without(acceptance, "acceptance_id", "acceptance_digest")
    )
    if acceptance["acceptance_digest"] != expected:
        raise ValueError("acceptance.acceptance_digest mismatch")
    if acceptance["acceptance_id"] != f"network-patch-acceptance-{expected[:16]}":
        raise ValueError("acceptance.acceptance_id mismatch")
    return acceptance


def read_contract(raw_path: str, label: str) -> dict[str, Any]:
    path = _canonical_absolute_path(raw_path, f"{label}.path")
    value, _ = _json_from_stable_file(path, label)
    return value


def validate_live_network(
    paths: kn.Paths,
) -> tuple[dict[str, Any], dict[str, list[dict[str, Any]]], dict[str, str]]:
    state, records = kn._load_state(paths)
    errors = kn._validate_record_shapes(paths, state, records)
    if errors:
        raise ValueError("network validation failed: " + "; ".join(errors))
    return state, records, current_network_ref(paths, state, records)


def command_validate(args: argparse.Namespace) -> int:
    paths = kn._safe_paths(args.root, args.network_id)
    with kn._exclusive_lock(paths):
        state, records, network_ref = validate_live_network(paths)
        live_network = kn._knowledge_network_export(paths, state, records)
        proposal = read_contract(args.proposal, "proposal")
        evidence_pack = read_contract(args.evidence_pack, "evidence_pack")
        if proposal.get("schema") == PATCH_V1_SCHEMA:
            validate_v1_audit(proposal, network_ref)
            validate_evidence_pack(
                evidence_pack,
                proposal,
                network_ref,
                live_network=live_network,
                regenerate=False,
            )
            output = {
                "schema": VALIDATION_SCHEMA,
                "proposal_schema": PATCH_V1_SCHEMA,
                "proposal_id": proposal["proposal_id"],
                "proposal_digest": digest_json(proposal),
                "network_ref": network_ref,
                "valid": True,
                "apply_eligible": False,
                "reason": "v1_is_audit_only_and_lacks_decisive_evidence_bindings",
            }
        else:
            proposal = validate_proposal_v2(proposal, network_ref)
            require_onboarded_sources(proposal, live_network)
            validate_evidence_pack(
                evidence_pack,
                proposal,
                network_ref,
                live_network=live_network,
            )
            output = {
                "schema": VALIDATION_SCHEMA,
                "proposal_schema": PATCH_V2_SCHEMA,
                "proposal_id": proposal["proposal_id"],
                "proposal_digest": proposal["proposal_digest"],
                "network_ref": network_ref,
                "valid": True,
                "apply_eligible": True,
                "reason": "explicit_acceptance_still_required",
            }
    print(json.dumps(output, ensure_ascii=False, sort_keys=True, indent=2))
    return 0


def _safe_plan_output(root: Path, raw_output: str) -> Path:
    plan_root = root / "patch-plans"
    if plan_root.exists() or plan_root.is_symlink():
        metadata = plan_root.lstat()
        if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
            raise ValueError("patch-plans root must be a non-symlink directory")
    else:
        plan_root.mkdir(mode=0o700)
        kn._fsync_directory(root)
    output = Path(raw_output).expanduser()
    if not output.is_absolute():
        output = root / output
    if Path(os.path.normpath(str(output))) != output:
        raise ValueError("plan output must be a canonical path")
    if output.parent != plan_root or not output.name or output.name.startswith("."):
        raise ValueError("plan output must be a direct child of <root>/patch-plans")
    if os.path.lexists(output):
        raise ValueError("plan output already exists; overwrite is forbidden")
    return output


def _write_json_exclusive_atomic(path: Path, payload: dict[str, Any]) -> None:
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            "w",
            dir=path.parent,
            prefix=".plan-stage-",
            encoding="utf-8",
            delete=False,
        ) as handle:
            temporary = Path(handle.name)
            json.dump(payload, handle, ensure_ascii=False, sort_keys=True, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.link(temporary, path, follow_symlinks=False)
        kn._fsync_directory(path.parent)
    except FileExistsError as exc:
        raise ValueError("plan output appeared concurrently; overwrite refused") from exc
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def command_prepare(args: argparse.Namespace) -> int:
    paths = kn._safe_paths(args.root, args.network_id)
    with kn._exclusive_lock(paths):
        state, records, network_ref = validate_live_network(paths)
        live_network = kn._knowledge_network_export(paths, state, records)
        proposal = read_contract(args.proposal, "proposal")
        evidence_pack = read_contract(args.evidence_pack, "evidence_pack")
        if proposal.get("schema") != PATCH_V2_SCHEMA:
            raise ValueError("prepare accepts only NetworkPatchProposal/v2")
        proposal = validate_proposal_v2(proposal, network_ref)
        require_onboarded_sources(proposal, live_network)
        validate_evidence_pack(
            evidence_pack,
            proposal,
            network_ref,
            live_network=live_network,
        )
        plan = create_plan(proposal, network_ref)
        output_path = _safe_plan_output(paths.root, args.output)
        _write_json_exclusive_atomic(output_path, plan)
    print(json.dumps(plan, ensure_ascii=False, sort_keys=True, indent=2))
    return 0


def operation_arguments(operation: dict[str, Any]) -> list[str]:
    operation_type = operation["operation_type"]
    payload = operation["payload"]
    repeated = {
        "assumptions": "--assumption",
        "conditions": "--condition",
        "units": "--unit",
        "exclusions": "--exclusion",
        "defeaters": "--defeater",
        "coverage_dimensions": "--coverage-dimension",
        "benchmark_profiles": "--benchmark-profile",
        "evidence_refs": "--evidence-ref",
    }
    arguments = [operation_type]
    for key, value in payload.items():
        if key in repeated:
            if not isinstance(value, list) or not all(
                isinstance(item, str) and item for item in value
            ):
                raise ValueError(f"operation payload {key} must be a string list")
            for item in value:
                arguments.extend([repeated[key], item])
        elif value is not None:
            if not isinstance(value, str):
                raise ValueError(f"operation payload {key} must be a string or null")
            arguments.extend(["--" + key.replace("_", "-"), value])
    return arguments


def execute_staged_operation(
    staging_root: Path, network_id: str, operation: dict[str, Any]
) -> None:
    stdout = io.StringIO()
    stderr = io.StringIO()
    argv = [
        "--root",
        str(staging_root),
        "--network-id",
        network_id,
        *operation_arguments(operation),
    ]
    with redirect_stdout(stdout), redirect_stderr(stderr):
        result = kn.main(argv)
    if result != 0:
        reason = stderr.getvalue().strip() or stdout.getvalue().strip() or "unknown error"
        raise ValueError(f"typed operation {operation['operation_id']} failed: {reason}")


def reject_prior_terminal_decisions(
    records: dict[str, list[dict[str, Any]]], acceptance: dict[str, Any]
) -> None:
    terminal: set[str] = set()
    for event in records["events"]:
        if event.get("event_type") != "patch_decision":
            continue
        if event.get("acceptance_id") == acceptance["acceptance_id"]:
            raise ValueError("acceptance was already applied")
        for decision in event.get("decisions", []):
            if (
                isinstance(decision, dict)
                and decision.get("decision") in {"accept", "reject"}
                and isinstance(decision.get("action_digest"), str)
            ):
                terminal.add(decision["action_digest"])
    repeated = sorted(
        decision["action_digest"]
        for decision in acceptance["decisions"]
        if decision["action_digest"] in terminal
    )
    if repeated:
        raise ValueError(f"proposal actions already have terminal decisions: {repeated}")


def decision_event(
    proposal: dict[str, Any], plan: dict[str, Any], acceptance: dict[str, Any]
) -> dict[str, Any]:
    payload = {
        "event_type": "patch_decision",
        "network_id": proposal["network_ref"]["network_id"],
        "proposal_id": proposal["proposal_id"],
        "proposal_digest": proposal["proposal_digest"],
        "plan_id": plan["plan_id"],
        "plan_digest": plan["plan_digest"],
        "acceptance_id": acceptance["acceptance_id"],
        "acceptance_digest": acceptance["acceptance_digest"],
        "decided_at": acceptance["decided_at"],
        "operator": acceptance["operator"],
        "decisions": [
            {
                "action_id": item["action_id"],
                "action_digest": item["action_digest"],
                "decision": item["decision"],
                "rationale": item["rationale"],
                "authority_basis_ids": item["authority_basis_ids"],
                "operations": [
                    {
                        "operation_id": op["operation_id"],
                        "operation_digest": op["operation_digest"],
                    }
                    for op in item["operations"]
                ],
            }
            for item in acceptance["decisions"]
        ],
    }
    payload["event_digest"] = digest_json(payload)
    return payload


def command_apply(args: argparse.Namespace) -> int:  # noqa: C901
    paths = kn._safe_paths(args.root, args.network_id)
    proposal_value = read_contract(args.proposal, "proposal")
    plan_value = read_contract(args.plan, "plan")
    acceptance_value = read_contract(args.acceptance, "acceptance")
    evidence_pack_value = read_contract(args.evidence_pack, "evidence_pack")
    with kn._exclusive_lock(paths):
        state, records, network_ref = validate_live_network(paths)
        live_network = kn._knowledge_network_export(paths, state, records)
        if proposal_value.get("schema") != PATCH_V2_SCHEMA:
            raise ValueError("apply accepts only NetworkPatchProposal/v2")
        proposal = validate_proposal_v2(proposal_value, network_ref)
        require_onboarded_sources(proposal, live_network)
        validate_evidence_pack(
            evidence_pack_value,
            proposal,
            network_ref,
            live_network=live_network,
        )
        plan = validate_plan(plan_value, proposal, network_ref)
        acceptance = validate_acceptance(
            acceptance_value, proposal, plan, network_ref
        )
        verify_authority_artifacts(acceptance, args.acceptance)
        reject_prior_terminal_decisions(records, acceptance)
        with tempfile.TemporaryDirectory(prefix=".network-patch-", dir=paths.root) as raw:
            staging_root = Path(raw)
            staging_parent = staging_root / kn.NETWORK_ROOT
            staging_parent.mkdir(parents=True)
            shutil.copytree(
                paths.network_dir,
                staging_parent / paths.network_id,
                symlinks=True,
            )
            for decision in acceptance["decisions"]:
                if decision["decision"] == "accept":
                    for operation in decision["operations"]:
                        execute_staged_operation(
                            staging_root, paths.network_id, operation
                        )
            staging_paths = kn._safe_paths(str(staging_root), paths.network_id)
            with kn._exclusive_lock(staging_paths):
                staged_state, staged_records = kn._load_state(staging_paths)
                event_payload = decision_event(proposal, plan, acceptance)
                record_id = kn._record_id(
                    "event", "patch", event_payload["event_digest"][:16]
                )
                if not kn._append_candidate(
                    staging_paths,
                    staged_records,
                    "events",
                    record_id,
                    event_payload,
                ):
                    raise ValueError("patch decision event conflicts in staging")
                errors = kn._validate_record_shapes(
                    staging_paths, staged_state, staged_records
                )
                if errors:
                    raise ValueError(
                        "staged network validation failed: " + "; ".join(errors)
                    )
                after_ref = current_network_ref(
                    staging_paths, staged_state, staged_records
                )
            result = {
                "schema": APPLICATION_SCHEMA,
                "mode": "dry_run" if args.dry_run else "applied",
                "proposal_id": proposal["proposal_id"],
                "proposal_digest": proposal["proposal_digest"],
                "plan_id": plan["plan_id"],
                "plan_digest": plan["plan_digest"],
                "acceptance_id": acceptance["acceptance_id"],
                "acceptance_digest": acceptance["acceptance_digest"],
                "before_network_ref": network_ref,
                "after_network_ref": after_ref,
                "decision_counts": {
                    decision: sum(
                        item["decision"] == decision
                        for item in acceptance["decisions"]
                    )
                    for decision in sorted(DECISIONS)
                },
            }
            if not args.dry_run:
                contents = {
                    paths.state: staging_paths.state.read_text(encoding="utf-8"),
                    **{
                        paths.ledger(name): staging_paths.ledger(name).read_text(
                            encoding="utf-8"
                        )
                        for name in kn.LEDGER_NAMES
                    },
                }
                kn._replace_files_transactionally(contents)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Validate, prepare, and explicitly apply RKN patch proposals",
        exit_on_error=False,
    )
    parser.add_argument("--root", required=True)
    parser.add_argument("--network-id", required=True)
    commands = parser.add_subparsers(dest="command", required=True)
    validate = commands.add_parser("validate-patch")
    validate.add_argument("--proposal", required=True)
    validate.add_argument("--evidence-pack", required=True)
    validate.set_defaults(func=command_validate)
    prepare = commands.add_parser("prepare-patch")
    prepare.add_argument("--proposal", required=True)
    prepare.add_argument("--evidence-pack", required=True)
    prepare.add_argument("--output", required=True)
    prepare.set_defaults(func=command_prepare)
    apply = commands.add_parser("apply-patch")
    apply.add_argument("--proposal", required=True)
    apply.add_argument("--evidence-pack", required=True)
    apply.add_argument("--plan", required=True)
    apply.add_argument("--acceptance", required=True)
    apply.add_argument("--dry-run", action="store_true")
    apply.set_defaults(func=command_apply)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    try:
        args = parser.parse_args(argv)
    except argparse.ArgumentError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    except SystemExit as exc:
        return int(exc.code) if isinstance(exc.code, int) else 2
    try:
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
