#!/usr/bin/env python3
"""Strict, acceptance-gated consumer for knowledge-network patch proposals."""

from __future__ import annotations

import argparse
import copy
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
import evidence_appraisal_binding as appraisal_binding


PATCH_V1_SCHEMA = "NetworkPatchProposal/v1"
PATCH_V2_SCHEMA = "NetworkPatchProposal/v2"
PATCH_V3_SCHEMA = "NetworkPatchProposal/v3"
PATCH_V4_SCHEMA = "NetworkPatchProposal/v4"
PLAN_SCHEMA = "NetworkPatchPlan/v1"
ACCEPTANCE_SCHEMA = "NetworkPatchAcceptance/v1"
VALIDATION_SCHEMA = "NetworkPatchValidation/v1"
APPLICATION_SCHEMA = "NetworkPatchApplicationResult/v1"
EVIDENCE_PACK_SCHEMA = "NetworkPatchEvidencePack/v1"
EVIDENCE_PACK_V2_SCHEMA = "NetworkPatchEvidencePack/v2"
TARGET_CLAIM_SCHEMA = "NetworkPatchTargetClaim/v1"
TARGET_CLAIM_V2_SCHEMA = "NetworkPatchTargetClaim/v2"
EXISTING_CLAIM_REF_SCHEMA = "NetworkPatchExistingClaimRef/v1"
READING_COLLECTION_SCHEMA = "PaperReadingEvidenceCollection/v1"
COLLECTION_CONSUMPTION_REF_SCHEMA = "ReviewedEvidenceCollectionConsumption/v1"
DIRECT_REVIEWED_SELECTION_ROUTE = "direct_reviewed_selection"

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

EVIDENCE_PACK_V2_FILE_ROLES = {
    "preconsumption_hypotheses",
    "review_requests",
    "reading_collection",
    "consumption_authority",
}

COLLECTION_CONSUMPTION_REF_FIELDS = {
    "schema",
    "route",
    "authority_id",
    "authority_digest",
    "authority_file_sha256",
    "consumed_hypotheses_sha256",
}

ORIGIN_GAP_REF_FIELDS = {
    "gap_id",
    "record_id",
    "sequence",
    "status",
    "sha256",
}
READING_GROUP_REF_FIELDS = {
    "reading_group_id",
    "reading_group_digest",
    "source_id",
    "report_set_id",
    "report_set_digest",
}
SUBJECT_REF_FIELDS = {"subject_id", "subject_digest"}
CLAIM_RECORD_REF_FIELDS = {"record_id", "sequence", "sha256"}
CLAIM_SEMANTIC_FIELDS = {
    "claim_text",
    "entity_id",
    "impact",
    "is_factual",
    "scope_statement",
    "assumptions",
    "conditions",
    "units",
    "exclusions",
    "defeaters",
    "coverage_dimensions",
    "benchmark_profiles",
    "supersedes",
}
CLAIM_SCOPE_FIELDS = {
    "scope_statement",
    "assumptions",
    "conditions",
    "units",
    "exclusions",
    "defeaters",
    "coverage_dimensions",
    "benchmark_profiles",
}
REPORT_CLAIM_REF_FIELDS = {
    "basis_id",
    "basis_digest",
    "reading_group_id",
    "claim_id",
    "claim_digest",
    "reading_report_id",
    "reading_report_digest",
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


def require_evidence_id(value: Any, label: str) -> str:
    evidence_id = require_string(value, label)
    if not kn.EVIDENCE_ID_RE.fullmatch(evidence_id):
        raise ValueError(f"{label} is not a materializable evidence ID")
    return evidence_id


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


def require_string_list(value: Any, label: str, *, nonempty: bool = False) -> list[str]:
    if not isinstance(value, list) or any(
        not isinstance(item, str) or not item.strip() or item != item.strip()
        for item in value
    ):
        raise ValueError(f"{label} must be a canonical string list")
    if nonempty and not value:
        raise ValueError(f"{label} must be non-empty")
    require_unique(value, label)
    return value


def target_claim_id(action: dict[str, Any]) -> str:
    if action.get("action_type") == "propose_evidence_extension":
        existing = action.get("existing_claim_ref")
        if not isinstance(existing, dict):
            raise ValueError(
                "propose_evidence_extension requires an existing_claim_ref"
            )
        return require_string(existing.get("claim_id"), "existing_claim_ref.claim_id")
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
            raise ValueError(f"{label}.target_claim.{field} must be a string list")
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
            raise ValueError(
                f"{label}.target_claim.scope.{field} must be a string list"
            )
        require_unique(values, f"{label}.target_claim.scope.{field}")
    if (
        scope["coverage_dimensions"] != target["coverage_dimensions"]
        or scope["benchmark_profiles"] != target["benchmark_profiles"]
    ):
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


def validate_subject_ref(value: Any, label: str) -> dict[str, str]:
    ref = require_object(value, label)
    require_keys(ref, SUBJECT_REF_FIELDS, label)
    return {
        "subject_id": require_string(ref["subject_id"], f"{label}.subject_id"),
        "subject_digest": require_digest(
            ref["subject_digest"], f"{label}.subject_digest"
        ),
    }


def _claim_scope_from_semantics(semantics: dict[str, Any]) -> dict[str, Any]:
    return {
        field: copy.deepcopy(semantics[field])
        for field in (
            "scope_statement",
            "assumptions",
            "conditions",
            "units",
            "exclusions",
            "defeaters",
            "coverage_dimensions",
            "benchmark_profiles",
        )
    }


def validate_existing_claim_ref(
    value: Any,
    live_network: dict[str, Any],
    label: str = "existing_claim_ref",
) -> dict[str, Any]:
    """Bind an extension to one exact, active claim ledger row."""

    ref = require_object(value, label)
    require_keys(
        ref,
        {
            "schema",
            "schema_version",
            "claim_id",
            "claim_record_ref",
            "claim_semantics",
            "scope_digest",
            "claim_semantic_digest",
        },
        label,
    )
    if ref["schema"] != EXISTING_CLAIM_REF_SCHEMA or ref["schema_version"] != "1.0":
        raise ValueError(f"{label} schema/version mismatch")
    claim_id = require_string(ref["claim_id"], f"{label}.claim_id")
    if not kn.ID_RE.fullmatch(claim_id):
        raise ValueError(f"{label}.claim_id is invalid")

    record_ref = require_object(ref["claim_record_ref"], f"{label}.claim_record_ref")
    require_keys(
        record_ref,
        CLAIM_RECORD_REF_FIELDS,
        f"{label}.claim_record_ref",
    )
    sequence = record_ref["sequence"]
    if type(sequence) is not int or sequence < 0:
        raise ValueError(
            f"{label}.claim_record_ref.sequence must be a non-negative integer"
        )
    normalized_record_ref = {
        "record_id": require_string(
            record_ref["record_id"], f"{label}.claim_record_ref.record_id"
        ),
        "sequence": sequence,
        "sha256": require_digest(
            record_ref["sha256"], f"{label}.claim_record_ref.sha256"
        ),
    }

    semantics = require_object(ref["claim_semantics"], f"{label}.claim_semantics")
    require_keys(semantics, CLAIM_SEMANTIC_FIELDS, f"{label}.claim_semantics")
    require_string(semantics["claim_text"], f"{label}.claim_semantics.claim_text")
    if semantics["entity_id"] is not None:
        require_string(semantics["entity_id"], f"{label}.claim_semantics.entity_id")
    if semantics["impact"] not in kn.IMPACTS:
        raise ValueError(f"{label}.claim_semantics.impact is invalid")
    if semantics["is_factual"] is not False:
        raise ValueError(f"{label}.claim_semantics.is_factual must be false")
    require_string(
        semantics["scope_statement"],
        f"{label}.claim_semantics.scope_statement",
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
        require_string_list(semantics[field], f"{label}.claim_semantics.{field}")
    if semantics["supersedes"] is not None:
        require_string(semantics["supersedes"], f"{label}.claim_semantics.supersedes")
    scope = _claim_scope_from_semantics(semantics)
    if ref["scope_digest"] != digest_json(scope):
        raise ValueError(f"{label}.scope_digest mismatch")
    if ref["claim_semantic_digest"] != digest_json(semantics):
        raise ValueError(f"{label}.claim_semantic_digest mismatch")

    claims = live_network.get("claims")
    if not isinstance(claims, list):
        raise ValueError("live network claims must be a list")
    matches = [
        row
        for row in claims
        if isinstance(row, dict) and row.get("claim_id") == claim_id
    ]
    if len(matches) != 1:
        raise ValueError(f"{label} must bind exactly one live claim row")
    if any(
        isinstance(row, dict) and row.get("supersedes") == claim_id for row in claims
    ):
        raise ValueError(f"{label} cannot bind a superseded claim")
    live_row = matches[0]
    expected_record_ref = {
        "record_id": live_row.get("record_id"),
        "sequence": live_row.get("sequence"),
        "sha256": digest_json(live_row),
    }
    if normalized_record_ref != expected_record_ref:
        raise ValueError(f"{label}.claim_record_ref is stale or mismatched")
    expected_semantics = {
        field: copy.deepcopy(live_row.get(field)) for field in CLAIM_SEMANTIC_FIELDS
    }
    if semantics != expected_semantics:
        raise ValueError(f"{label}.claim_semantics do not match the live claim row")
    if ref["claim_id"] != live_row.get("claim_id"):
        raise ValueError(f"{label}.claim_id mismatch")
    return ref


def _validate_existing_claim_subject(
    action: dict[str, Any], existing: dict[str, Any], label: str
) -> None:
    semantics = existing["claim_semantics"]
    if action["hypothesis"] != semantics["claim_text"]:
        raise ValueError(
            f"{label}.hypothesis must exactly equal the existing claim text"
        )
    subject = {
        "hypothesis_id": action["hypothesis_id"],
        "claim_text": semantics["claim_text"],
        "impact": semantics["impact"],
        "target_signature": action["target_signature"]["signature"],
        **_claim_scope_from_semantics(semantics),
        "origin_gap_refs": copy.deepcopy(action["origin_gap_refs"]),
    }
    expected_digest = digest_json(subject)
    if action["subject_ref"] != {
        "subject_id": "reviewed-gap-claim-subject-" + expected_digest[:16],
        "subject_digest": expected_digest,
    }:
        raise ValueError(
            f"{label}.subject_ref does not exactly bind the existing claim semantics"
        )


def _origin_claim_route(
    origin_gap_refs: list[dict[str, Any]], live_network: dict[str, Any], label: str
) -> tuple[str, str | None]:
    gaps = live_network.get("gaps")
    if not isinstance(gaps, list):
        raise ValueError("live network gaps must be a list")
    gap_rows = {
        row.get("gap_id"): row
        for row in gaps
        if isinstance(row, dict) and isinstance(row.get("gap_id"), str)
    }
    claim_ids = [gap_rows[ref["gap_id"]].get("claim_id") for ref in origin_gap_refs]
    if all(claim_id is None for claim_id in claim_ids):
        return "new", None
    if all(isinstance(claim_id, str) and claim_id for claim_id in claim_ids):
        distinct = set(claim_ids)
        if len(distinct) == 1:
            return "extension", next(iter(distinct))
    raise ValueError(
        f"{label}.origin_gap_refs mix claimless or multiple existing-claim routes"
    )


def validate_collection_consumption_ref(
    value: Any, label: str = "proposal.consumption_ref"
) -> dict[str, str]:
    """Validate the detached-authority receipt carried by proposal v3/v4."""

    ref = require_object(value, label)
    require_keys(ref, COLLECTION_CONSUMPTION_REF_FIELDS, label)
    if ref["schema"] != COLLECTION_CONSUMPTION_REF_SCHEMA:
        raise ValueError(f"{label}.schema is invalid")
    if ref["route"] != DIRECT_REVIEWED_SELECTION_ROUTE:
        raise ValueError(f"{label}.route must be direct_reviewed_selection")
    authority_digest = require_digest(
        ref["authority_digest"], f"{label}.authority_digest"
    )
    expected_authority_id = (
        "reviewed-collection-consumption-authority-" + authority_digest[:16]
    )
    if ref["authority_id"] != expected_authority_id:
        raise ValueError(f"{label}.authority_id does not match authority_digest")
    return {
        "schema": ref["schema"],
        "route": ref["route"],
        "authority_id": ref["authority_id"],
        "authority_digest": authority_digest,
        "authority_file_sha256": require_digest(
            ref["authority_file_sha256"], f"{label}.authority_file_sha256"
        ),
        "consumed_hypotheses_sha256": require_digest(
            ref["consumed_hypotheses_sha256"],
            f"{label}.consumed_hypotheses_sha256",
        ),
    }


def validate_origin_gap_refs(
    value: Any,
    label: str,
    live_network: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    if not isinstance(value, list) or not value:
        raise ValueError(f"{label} must be a non-empty list")
    live_gaps = {
        gap.get("gap_id"): gap
        for gap in (live_network or {}).get("gaps", [])
        if isinstance(gap, dict) and isinstance(gap.get("gap_id"), str)
    }
    result: list[dict[str, Any]] = []
    for index, raw in enumerate(value):
        item_label = f"{label}[{index}]"
        ref = require_object(raw, item_label)
        require_keys(ref, ORIGIN_GAP_REF_FIELDS, item_label)
        gap_id = require_string(ref["gap_id"], f"{item_label}.gap_id")
        if gap_id.startswith("KGH-"):
            raise ValueError(f"{item_label}.gap_id must be a live network gap")
        sequence = ref["sequence"]
        if type(sequence) is not int or sequence < 0:
            raise ValueError(f"{item_label}.sequence must be a non-negative integer")
        normalized = {
            "gap_id": gap_id,
            "record_id": require_string(ref["record_id"], f"{item_label}.record_id"),
            "sequence": sequence,
            "status": require_string(ref["status"], f"{item_label}.status"),
            "sha256": require_digest(ref["sha256"], f"{item_label}.sha256"),
        }
        if live_network is not None:
            gap = live_gaps.get(gap_id)
            if gap is None:
                raise ValueError(f"{item_label} is not present in the live export")
            record_ref = require_object(
                gap.get("record_ref"), f"live gap {gap_id}.record_ref"
            )
            require_keys(
                record_ref,
                {"record_id", "sequence", "status", "sha256"},
                f"live gap {gap_id}.record_ref",
            )
            if {key: normalized[key] for key in record_ref} != record_ref:
                raise ValueError(f"{item_label} does not bind the current gap record")
            if normalized["status"] == "resolved":
                raise ValueError(f"{item_label} cannot originate from a resolved gap")
        result.append(normalized)
    require_unique([item["gap_id"] for item in result], label)
    require_unique([item["record_id"] for item in result], f"{label} record IDs")
    return result


def validate_reading_group_refs(value: Any, label: str) -> list[dict[str, str]]:
    if not isinstance(value, list) or len(value) < 2:
        raise ValueError(f"{label} must contain at least two reading groups")
    result: list[dict[str, str]] = []
    for index, raw in enumerate(value):
        item_label = f"{label}[{index}]"
        ref = require_object(raw, item_label)
        require_keys(ref, READING_GROUP_REF_FIELDS, item_label)
        result.append(
            {
                "reading_group_id": require_string(
                    ref["reading_group_id"], f"{item_label}.reading_group_id"
                ),
                "reading_group_digest": require_digest(
                    ref["reading_group_digest"],
                    f"{item_label}.reading_group_digest",
                ),
                "source_id": require_string(
                    ref["source_id"], f"{item_label}.source_id"
                ),
                "report_set_id": require_string(
                    ref["report_set_id"], f"{item_label}.report_set_id"
                ),
                "report_set_digest": require_digest(
                    ref["report_set_digest"], f"{item_label}.report_set_digest"
                ),
            }
        )
    for field in (
        "reading_group_id",
        "reading_group_digest",
        "source_id",
        "report_set_id",
        "report_set_digest",
    ):
        require_unique([item[field] for item in result], f"{label} {field}")
    return result


def validate_target_claim_v2(
    action: dict[str, Any],
    reviewed: list[dict[str, Any]],
    reading_group_refs: list[dict[str, str]],
    label: str,
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
            "target_signature",
            "subject_ref",
            "origin_gap_refs",
            "report_claim_refs",
            "scope",
            "scope_digest",
            "target_claim_digest",
        },
        f"{label}.target_claim",
    )
    if target["schema"] != TARGET_CLAIM_V2_SCHEMA or target["schema_version"] != "2.0":
        raise ValueError(f"{label}.target_claim schema/version mismatch")
    require_string(target["claim_text"], f"{label}.target_claim.claim_text")
    if target["entity_id"] is not None:
        require_string(target["entity_id"], f"{label}.target_claim.entity_id")
    if target["impact"] not in kn.IMPACTS:
        raise ValueError(f"{label}.target_claim.impact is invalid")
    if target["supersedes"] is not None:
        raise ValueError(f"{label}.target_claim.supersedes must be null")
    for field in ("coverage_dimensions", "benchmark_profiles"):
        require_string_list(target[field], f"{label}.target_claim.{field}")
    if target["target_signature"] != action["target_signature"]:
        raise ValueError(f"{label}.target_claim target signature mismatch")
    if (
        validate_subject_ref(target["subject_ref"], f"{label}.target_claim.subject_ref")
        != action["subject_ref"]
    ):
        raise ValueError(f"{label}.target_claim subject_ref mismatch")
    if target["origin_gap_refs"] != action["origin_gap_refs"]:
        raise ValueError(f"{label}.target_claim origin_gap_refs mismatch")

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
        require_string_list(scope[field], f"{label}.target_claim.scope.{field}")
    if (
        scope["coverage_dimensions"] != target["coverage_dimensions"]
        or scope["benchmark_profiles"] != target["benchmark_profiles"]
    ):
        raise ValueError(f"{label}.target_claim scope/profile projection mismatch")
    if target["scope_digest"] != digest_json(scope):
        raise ValueError(f"{label}.target_claim.scope_digest mismatch")

    refs = target["report_claim_refs"]
    if not isinstance(refs, list) or len(refs) != len(reviewed):
        raise ValueError(
            f"{label}.target_claim.report_claim_refs must cover every basis"
        )
    group_by_source_report = {
        (group["source_id"], group["report_set_id"], group["report_set_digest"]): group
        for group in reading_group_refs
    }
    normalized_refs: list[dict[str, str]] = []
    for index, (raw_ref, basis) in enumerate(zip(refs, reviewed)):
        ref_label = f"{label}.target_claim.report_claim_refs[{index}]"
        ref = require_object(raw_ref, ref_label)
        require_keys(ref, REPORT_CLAIM_REF_FIELDS, ref_label)
        normalized = {
            field: (
                require_digest(ref[field], f"{ref_label}.{field}")
                if field
                in {
                    "basis_digest",
                    "claim_digest",
                    "reading_report_digest",
                }
                else require_string(ref[field], f"{ref_label}.{field}")
            )
            for field in REPORT_CLAIM_REF_FIELDS
        }
        group = group_by_source_report.get(
            (basis["source_id"], basis["report_set_id"], basis["report_set_digest"])
        )
        if group is None or normalized != {
            "basis_id": basis["basis_id"],
            "basis_digest": basis["basis_digest"],
            "reading_group_id": group["reading_group_id"],
            "claim_id": basis["claim_id"],
            "claim_digest": basis["claim_digest"],
            "reading_report_id": basis["reading_report_id"],
            "reading_report_digest": basis["reading_report_digest"],
        }:
            raise ValueError(f"{ref_label} does not exactly project its basis")
        normalized_refs.append(normalized)
    require_unique(
        [item["basis_id"] for item in normalized_refs],
        f"{label}.target_claim.report_claim_refs basis IDs",
    )
    expected = digest_json(without(target, "claim_id", "target_claim_digest"))
    if target["target_claim_digest"] != expected:
        raise ValueError(f"{label}.target_claim_digest mismatch")
    if target["claim_id"] != f"claim-target-{expected[:16]}":
        raise ValueError(f"{label}.target_claim.claim_id mismatch")
    return target


def relation_operation_id(
    action: dict[str, Any],
    basis: dict[str, Any],
    relation_type: str = "supports",
) -> str:
    subject = {
        "target_signature": action["target_signature"],
        "target_claim_id": target_claim_id(action),
        "basis_id": basis["basis_id"],
        "basis_digest": basis["basis_digest"],
        "evidence_id": basis["evidence_id"],
        "relation_type": relation_type,
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


def _gate_argument_paths(args: argparse.Namespace) -> dict[str, Any] | None:
    values = {
        "package": getattr(args, "appraisal_package", None),
        "approval": getattr(args, "appraisal_approval", None),
        "prepared": getattr(args, "appraisal_prepared", None),
        "independent_review": getattr(args, "appraisal_independent_review", None),
        "owner_bundle": getattr(args, "appraisal_owner_bundle", None),
        "expected_authority_sha256": getattr(args, "expected_authority_sha256", None),
        "proposal": getattr(args, "proposal", None),
        "binding": getattr(args, "appraisal_binding", None),
        "projection": getattr(args, "appraisal_projection", None),
    }
    appraisal_values = {
        key: value for key, value in values.items() if key != "proposal"
    }
    lineage = list(getattr(args, "appraisal_lineage", None) or [])
    if (any(appraisal_values.values()) or lineage) and not all(
        appraisal_values.values()
    ):
        raise ValueError(
            "appraisal gate is incomplete; provide --appraisal-package, "
            "--appraisal-approval, --appraisal-prepared, "
            "--appraisal-independent-review, --appraisal-owner-bundle, --appraisal-binding, and "
            "--expected-authority-sha256 and --appraisal-projection together"
        )
    if not all(appraisal_values.values()):
        return None
    return {
        **{key: str(value) for key, value in values.items()},
        "lineage": [str(value) for value in lineage],
    }


def _load_optional_appraisal_gate(
    args: argparse.Namespace,
    proposal: dict[str, Any],
    network_ref: dict[str, str],
    paths: kn.Paths,
    records: dict[str, list[dict[str, Any]]],
) -> tuple[dict[str, Any] | None, list[str]]:
    raw_paths = _gate_argument_paths(args)
    if raw_paths is None:
        return None, []
    package = appraisal_binding.load_json_stable(
        raw_paths["package"], "appraisal package"
    )
    approval = appraisal_binding.load_json_stable(
        raw_paths["approval"], "appraisal approval"
    )
    prepared = appraisal_binding.load_json_stable(
        raw_paths["prepared"], "appraisal preparation"
    )
    independent_review = appraisal_binding.load_json_stable(
        raw_paths["independent_review"], "appraisal independent review"
    )
    owner_bundle = appraisal_binding.load_json_stable(
        raw_paths["owner_bundle"], "appraisal owner bundle"
    )
    lineage = [
        appraisal_binding.load_json_stable(path, f"appraisal lineage[{index}]")
        for index, path in enumerate(raw_paths["lineage"])
    ]
    binding = appraisal_binding.load_json_stable(
        raw_paths["binding"], "appraisal binding"
    )
    projection = appraisal_binding.load_json_stable(
        raw_paths["projection"], "appraisal projection"
    )
    prefix_counts = {
        name: int(binding["network_guard"]["ledgers"][name]["record_count"])
        for name in kn.LEDGER_NAMES
    }
    gate = appraisal_binding.validate_gate(
        package,
        approval,
        prepared,
        independent_review,
        owner_bundle,
        lineage,
        raw_paths["expected_authority_sha256"],
        proposal,
        binding,
        projection,
        network_ref,
        kn._claim_scopes_from_records(records, prefix_counts=prefix_counts),
    )
    consumed = kn._validate_guard_prefix(paths, records, gate)
    if consumed:
        raise ValueError(
            "appraisal binding already has consumed operations; regenerate from current authority"
        )
    cli_args = [
        "--appraisal-package",
        raw_paths["package"],
        "--appraisal-approval",
        raw_paths["approval"],
        "--appraisal-prepared",
        raw_paths["prepared"],
        "--appraisal-independent-review",
        raw_paths["independent_review"],
        "--appraisal-owner-bundle",
        raw_paths["owner_bundle"],
        "--expected-authority-sha256",
        raw_paths["expected_authority_sha256"],
        "--appraisal-proposal",
        raw_paths["proposal"],
        "--appraisal-binding",
        raw_paths["binding"],
        "--appraisal-projection",
        raw_paths["projection"],
    ]
    for path in raw_paths["lineage"]:
        cli_args.extend(["--appraisal-lineage", path])
    return gate, cli_args


def _binding_row(
    gate: dict[str, Any], action: dict[str, Any], basis: dict[str, Any]
) -> dict[str, Any]:
    matches = [
        row
        for row in gate["binding"]["relation_bindings"]
        if row["action_id"] == action["action_id"]
        and row["basis_id"] == basis["basis_id"]
    ]
    if len(matches) != 1:
        raise ValueError("appraisal gate does not bind an exact action evidence basis")
    return matches[0]


def _operation_ledger_subject(operation: dict[str, Any]) -> dict[str, Any]:
    operation_type = operation["operation_type"]
    payload = copy.deepcopy(operation["payload"])
    if operation_type == "add-claim":
        payload["is_factual"] = False
    elif operation_type == "add-relation":
        payload["from"] = payload.pop("from_ref")
        payload["to"] = payload.pop("to_ref")
    return payload


def validate_appraised_acceptance(
    acceptance: dict[str, Any],
    gate: dict[str, Any],
    records: dict[str, list[dict[str, Any]]],
) -> None:
    gap_records = {
        row["record_id"]: row
        for row in records["gaps"]
        if isinstance(row.get("record_id"), str)
    }
    consumed: set[str] = set()
    for decision in acceptance["decisions"]:
        if decision["decision"] != "accept":
            continue
        for operation in decision["operations"]:
            operation_type = operation["operation_type"]
            ledger_payload = _operation_ledger_subject(operation)
            authorization_subject = None
            if operation_type == "transition-gap":
                payload = operation["payload"]
                prior = gap_records.get(payload["from_record_id"])
                if prior is None or prior.get("gap_id") != payload["gap_id"]:
                    raise ValueError(
                        "appraised gap transition does not bind a live prior record"
                    )
                authorization_subject = {
                    "operation_type": "transition-gap",
                    "gap_id": payload["gap_id"],
                    "from_record_id": payload["from_record_id"],
                    "from_status": prior.get("status"),
                    "to_status": payload["status"],
                    "reason": payload["reason"],
                    "evidence_refs": sorted(payload["evidence_refs"]),
                    "resolution_source": payload["resolution_source"] or "",
                }
            authorization = appraisal_binding.authorize_mutation(
                gate,
                operation_type,
                ledger_payload,
                authorization_subject=authorization_subject,
                consumed_authorization_digests=consumed,
            )
            consumed.add(authorization["authorization_digest"])


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
    if (
        proposal["proposal_only"] is not True
        or proposal["novelty_claimed"] is not False
    ):
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
    require_evidence_id(basis["evidence_id"], f"{label}.evidence_id")
    for field in digest_fields:
        require_digest(basis[field], f"{label}.{field}")
    if (
        Path(basis["source_ref"]).name != basis["source_ref"]
        or "://" in basis["source_ref"]
    ):
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


def validate_proposal_v2(value: Any, network_ref: dict[str, str]) -> dict[str, Any]:
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
    if (
        proposal["proposal_only"] is not True
        or proposal["novelty_claimed"] is not False
    ):
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
        signature = require_object(
            action["target_signature"], f"{label}.target_signature"
        )
        require_keys(
            signature, {"target_kind", "signature"}, f"{label}.target_signature"
        )
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


def _validate_multi_reading_proposal(
    value: Any,
    network_ref: dict[str, str],
    live_network: dict[str, Any] | None = None,
    *,
    expected_schema: str,
    expected_version: str,
    allow_existing_claim_extension: bool,
) -> dict[str, Any]:
    """Validate the shared atomic multi-reading envelope and its route union."""

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
            "consumption_ref",
            "reading_collection_ref",
            "generated_at",
            "proposal_only",
            "novelty_claimed",
            "review_gate",
            "actions",
        },
        "proposal",
    )
    if (
        proposal["schema"] != expected_schema
        or proposal["schema_version"] != expected_version
    ):
        raise ValueError(
            f"proposal must use {expected_schema} schema_version {expected_version}"
        )
    if allow_existing_claim_extension and live_network is None:
        raise ValueError("NetworkPatchProposal/v4 requires the live network export")
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
    proposal["consumption_ref"] = validate_collection_consumption_ref(
        proposal["consumption_ref"]
    )
    collection_ref = require_object(
        proposal["reading_collection_ref"], "proposal.reading_collection_ref"
    )
    require_keys(
        collection_ref,
        {"collection_id", "collection_digest"},
        "proposal.reading_collection_ref",
    )
    require_string(
        collection_ref["collection_id"],
        "proposal.reading_collection_ref.collection_id",
    )
    require_digest(
        collection_ref["collection_digest"],
        "proposal.reading_collection_ref.collection_digest",
    )
    require_timestamp(proposal["generated_at"], "proposal.generated_at")
    if (
        proposal["proposal_only"] is not True
        or proposal["novelty_claimed"] is not False
    ):
        raise ValueError("proposal must remain proposal-only and non-novelty")
    if proposal["review_gate"] != "pending_research_knowledge_network_acceptance":
        raise ValueError("proposal.review_gate must remain pending acceptance")

    actions = proposal["actions"]
    if not isinstance(actions, list) or not actions:
        raise ValueError("proposal.actions must be non-empty")
    action_ids: list[str] = []
    action_digests: list[str] = []
    hypothesis_ids: list[str] = []
    subject_ids: list[str] = []
    evidence_ids: list[str] = []
    origin_gap_ids: list[str] = []
    target_claim_ids: list[str] = []
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
            "subject_ref",
            "origin_gap_refs",
            "reading_group_refs",
            "reviewed_evidence",
        }
        if action_type == "propose_relation":
            action_fields.add("target_claim")
        elif (
            allow_existing_claim_extension
            and action_type == "propose_evidence_extension"
        ):
            action_fields.add("existing_claim_ref")
        require_keys(
            action,
            action_fields,
            label,
        )
        allowed_action_types = {"propose_relation"}
        if allow_existing_claim_extension:
            allowed_action_types.add("propose_evidence_extension")
        if action_type not in allowed_action_types:
            raise ValueError(
                f"{label}.action_type must select an allowed multi-reading route"
            )
        if action["action_status"] != "proposed":
            raise ValueError(f"{label}.action_status must be proposed")
        require_string(action["hypothesis_id"], f"{label}.hypothesis_id")
        require_string(action["hypothesis"], f"{label}.hypothesis")
        signature = require_object(
            action["target_signature"], f"{label}.target_signature"
        )
        require_keys(
            signature, {"target_kind", "signature"}, f"{label}.target_signature"
        )
        if signature["target_kind"] != "relation":
            raise ValueError(f"{label}.target_signature.target_kind must be relation")
        require_string(signature["signature"], f"{label}.target_signature.signature")
        action["subject_ref"] = validate_subject_ref(
            action["subject_ref"], f"{label}.subject_ref"
        )
        action["origin_gap_refs"] = validate_origin_gap_refs(
            action["origin_gap_refs"], f"{label}.origin_gap_refs", live_network
        )
        route = "new"
        routed_claim_id: str | None = None
        if allow_existing_claim_extension:
            assert live_network is not None
            route, routed_claim_id = _origin_claim_route(
                action["origin_gap_refs"], live_network, label
            )
            expected_action_type = {
                "new": "propose_relation",
                "extension": "propose_evidence_extension",
            }[route]
            if action_type != expected_action_type:
                raise ValueError(
                    f"{label}.action_type does not match its origin-gap claim route"
                )
        action["reading_group_refs"] = validate_reading_group_refs(
            action["reading_group_refs"], f"{label}.reading_group_refs"
        )

        reviewed = action["reviewed_evidence"]
        if not isinstance(reviewed, list) or len(reviewed) < 2:
            raise ValueError(f"{label}.reviewed_evidence must contain multiple bases")
        bases: list[dict[str, Any]] = []
        for basis_index, raw_basis in enumerate(reviewed):
            bases.append(
                validate_basis(raw_basis, f"{label}.reviewed_evidence[{basis_index}]")
            )
        require_unique([basis["basis_id"] for basis in bases], f"{label} basis IDs")
        require_unique(
            [basis["basis_digest"] for basis in bases], f"{label} basis digests"
        )
        require_unique(
            [basis["evidence_id"] for basis in bases], f"{label} evidence IDs"
        )
        require_unique(
            [f"{basis['claim_id']}:{basis['evidence_id']}" for basis in bases],
            f"{label} claim/evidence identities",
        )
        group_projection: list[dict[str, str]] = []
        for basis in bases:
            identity = {
                "source_id": basis["source_id"],
                "report_set_id": basis["report_set_id"],
                "report_set_digest": basis["report_set_digest"],
            }
            candidates = [
                group
                for group in action["reading_group_refs"]
                if all(group[key] == identity[key] for key in identity)
            ]
            if len(candidates) != 1:
                raise ValueError(f"{label} basis does not map to one reading group")
            if not group_projection or group_projection[-1] != candidates[0]:
                group_projection.append(candidates[0])
        if group_projection != action["reading_group_refs"]:
            raise ValueError(
                f"{label}.reviewed_evidence must preserve reading-group order"
            )
        if len({basis["source_id"] for basis in bases}) < 2:
            raise ValueError(f"{label} requires at least two distinct source IDs")
        if not any(basis["access_level"] == "full_text" for basis in bases):
            raise ValueError(f"{label} requires at least one full-text basis")
        target: dict[str, Any] | None = None
        existing: dict[str, Any] | None = None
        if route == "new":
            target = validate_target_claim_v2(
                action, bases, action["reading_group_refs"], label
            )
        else:
            assert live_network is not None
            existing = validate_existing_claim_ref(
                action["existing_claim_ref"],
                live_network,
                f"{label}.existing_claim_ref",
            )
            if existing["claim_id"] != routed_claim_id:
                raise ValueError(
                    f"{label}.existing_claim_ref does not match its origin gaps"
                )
            _validate_existing_claim_subject(action, existing, label)
        if live_network is not None and target is not None:
            requirements = require_object(
                live_network.get("requirements"), "live network requirements"
            )
            require_keys(
                requirements,
                {"required_dimensions", "required_benchmark_profiles"},
                "live network requirements",
            )
            required_dimensions = require_string_list(
                requirements["required_dimensions"],
                "live network requirements.required_dimensions",
            )
            required_profiles = require_string_list(
                requirements["required_benchmark_profiles"],
                "live network requirements.required_benchmark_profiles",
            )
            unknown_dimensions = sorted(
                set(target["coverage_dimensions"]) - set(required_dimensions)
            )
            unknown_profiles = sorted(
                set(target["benchmark_profiles"]) - set(required_profiles)
            )
            if unknown_dimensions or unknown_profiles:
                raise ValueError(
                    f"{label}.target_claim injects unrequired coverage/profile values: "
                    f"dimensions={unknown_dimensions}, profiles={unknown_profiles}"
                )
        action_impact = (
            target["impact"]
            if target is not None
            else existing["claim_semantics"]["impact"]
        )
        if action_impact == "high" and len({basis["source_id"] for basis in bases}) < 2:
            raise ValueError(f"{label} high-impact target lacks independent sources")
        expected = digest_json(without(action, "action_id", "action_digest"))
        if action["action_digest"] != expected:
            raise ValueError(f"{label}.action_digest mismatch")
        if action["action_id"] != f"network-patch-action-{expected[:16]}":
            raise ValueError(f"{label}.action_id mismatch")
        action_ids.append(action["action_id"])
        action_digests.append(action["action_digest"])
        hypothesis_ids.append(action["hypothesis_id"])
        subject_ids.append(action["subject_ref"]["subject_id"])
        evidence_ids.extend(basis["evidence_id"] for basis in bases)
        origin_gap_ids.extend(ref["gap_id"] for ref in action["origin_gap_refs"])
        target_claim_ids.append(target_claim_id(action))
    require_unique(action_ids, "proposal action IDs")
    require_unique(action_digests, "proposal action digests")
    require_unique(hypothesis_ids, "proposal hypothesis IDs")
    require_unique(subject_ids, "proposal subject IDs")
    require_unique(evidence_ids, "proposal evidence IDs")
    require_unique(origin_gap_ids, "proposal origin gap IDs")
    require_unique(target_claim_ids, "proposal target claim IDs")
    expected = digest_json(without(proposal, "proposal_id", "proposal_digest"))
    if proposal["proposal_digest"] != expected:
        raise ValueError("proposal.proposal_digest mismatch")
    if proposal["proposal_id"] != f"network-patch-proposal-{expected[:16]}":
        raise ValueError("proposal.proposal_id mismatch")
    return proposal


def validate_proposal_v3(
    value: Any,
    network_ref: dict[str, str],
    live_network: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Validate an atomic new-claim multi-reading proposal without weakening v2."""

    return _validate_multi_reading_proposal(
        value,
        network_ref,
        live_network,
        expected_schema=PATCH_V3_SCHEMA,
        expected_version="3.0",
        allow_existing_claim_extension=False,
    )


def validate_proposal_v4(
    value: Any,
    network_ref: dict[str, str],
    live_network: dict[str, Any],
) -> dict[str, Any]:
    """Validate the v4 new-claim or existing-claim multi-reading route."""

    return _validate_multi_reading_proposal(
        value,
        network_ref,
        live_network,
        expected_schema=PATCH_V4_SCHEMA,
        expected_version="4.0",
        allow_existing_claim_extension=True,
    )


def validate_proposal(
    value: Any,
    network_ref: dict[str, str],
    live_network: dict[str, Any] | None = None,
) -> dict[str, Any]:
    schema = value.get("schema") if isinstance(value, dict) else None
    if schema == PATCH_V2_SCHEMA:
        return validate_proposal_v2(value, network_ref)
    if schema == PATCH_V3_SCHEMA:
        return validate_proposal_v3(value, network_ref, live_network)
    if schema == PATCH_V4_SCHEMA:
        if live_network is None:
            raise ValueError("NetworkPatchProposal/v4 requires the live network export")
        return validate_proposal_v4(value, network_ref, live_network)
    raise ValueError("proposal must use NetworkPatchProposal/v2, v3, or v4")


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


def validate_evidence_pack_v1(
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
                loaded[role] = require_object(json.loads(raw.decode("utf-8")), label)
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
    if (
        require_digest(
            verification_ref["tree_sha256"],
            "evidence_pack.verification_root.tree_sha256",
        )
        != tree_digest
    ):
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


def load_reading_collection_module():
    path = (
        Path(__file__).resolve().parents[2]
        / "learn-from-papers"
        / "scripts"
        / "paper_reading_evidence_collection.py"
    )
    name = "rkn_paper_reading_evidence_collection_owner"
    existing = sys.modules.get(name)
    if existing is not None:
        return existing
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ValueError("PaperReadingEvidenceCollection/v1 owner is unavailable")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    if not callable(getattr(module, "validate_collection", None)):
        raise ValueError("PaperReadingEvidenceCollection/v1 validator is unavailable")
    return module


def validate_evidence_pack_v2(
    value: Any,
    proposal: dict[str, Any],
    network_ref: dict[str, str],
    *,
    live_network: dict[str, Any],
    expected_authority_file_sha256: str,
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
        },
        "evidence_pack",
    )
    if pack["schema"] != EVIDENCE_PACK_V2_SCHEMA or pack["schema_version"] != "2.0":
        raise ValueError("evidence_pack must use NetworkPatchEvidencePack/v2")
    if not regenerate:
        raise ValueError(
            "NetworkPatchEvidencePack/v2 authorized regeneration cannot be disabled"
        )
    if proposal.get("schema") not in {PATCH_V3_SCHEMA, PATCH_V4_SCHEMA}:
        raise ValueError("NetworkPatchEvidencePack/v2 requires proposal v3 or v4")
    validate_network_ref(pack["network_ref"], network_ref, "evidence_pack.network_ref")
    proposal_ref = require_object(pack["proposal_ref"], "evidence_pack.proposal_ref")
    require_keys(
        proposal_ref, {"proposal_id", "proposal_digest"}, "evidence_pack.proposal_ref"
    )
    if proposal_ref != {
        "proposal_id": proposal["proposal_id"],
        "proposal_digest": proposal["proposal_digest"],
    }:
        raise ValueError("evidence_pack proposal binding mismatch")
    artifacts = require_object(pack["artifacts"], "evidence_pack.artifacts")
    require_keys(artifacts, EVIDENCE_PACK_V2_FILE_ROLES, "evidence_pack.artifacts")
    loaded: dict[str, dict[str, Any]] = {}
    raw_files: dict[str, bytes] = {}
    paths: dict[str, Path] = {}
    for role in sorted(EVIDENCE_PACK_V2_FILE_ROLES):
        label = f"evidence_pack.artifacts.{role}"
        reference = require_object(artifacts[role], label)
        require_keys(reference, {"path", "sha256"}, label)
        path = _canonical_absolute_path(reference["path"], f"{label}.path")
        declared = require_digest(reference["sha256"], f"{label}.sha256")
        raw, observed = _stable_file_bytes(path, label)
        if declared != observed:
            raise ValueError(f"{label}.sha256 mismatch")
        try:
            loaded[role] = require_object(json.loads(raw.decode("utf-8")), label)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError(f"{label} must be UTF-8 JSON") from exc
        raw_files[role] = raw
        paths[role] = path

    expected_authority_sha = require_digest(
        expected_authority_file_sha256,
        "expected_authority_file_sha256",
    )
    authority_artifact_sha = artifacts["consumption_authority"]["sha256"]
    if authority_artifact_sha != expected_authority_sha:
        raise ValueError(
            "consumption authority artifact does not match the caller-held raw SHA-256"
        )

    module = load_gap_module()
    authority_validator = getattr(
        module, "validate_reviewed_collection_consumption_authority", None
    )
    if not callable(authority_validator):
        raise ValueError(
            "network-gap producer lacks the reviewed collection authority validator"
        )
    try:
        authority = authority_validator(loaded["consumption_authority"])
    except Exception as exc:
        raise ValueError(
            f"ReviewedEvidenceCollectionConsumptionAuthority/v1 replay failed: {exc}"
        ) from exc
    expected_consumption_ref = {
        "schema": COLLECTION_CONSUMPTION_REF_SCHEMA,
        "route": DIRECT_REVIEWED_SELECTION_ROUTE,
        "authority_id": authority["authority_id"],
        "authority_digest": authority["authority_digest"],
        "authority_file_sha256": expected_authority_sha,
        "consumed_hypotheses_sha256": authority["expected_consumed_hypotheses_sha256"],
    }
    if (
        validate_collection_consumption_ref(proposal.get("consumption_ref"))
        != expected_consumption_ref
    ):
        raise ValueError(
            "proposal consumption_ref does not match the detached authority and raw pin"
        )

    owner = load_reading_collection_module()
    try:
        collection = owner.validate_collection(loaded["reading_collection"])
    except owner.ContractError as exc:
        raise ValueError(
            f"PaperReadingEvidenceCollection/v1 owner replay failed: {exc}"
        ) from exc
    if collection["network_ref"] != network_ref:
        raise ValueError("reading collection network_ref mismatch")
    if proposal["reading_collection_ref"] != {
        "collection_id": collection["collection_id"],
        "collection_digest": collection["collection_digest"],
    }:
        raise ValueError("proposal reading_collection_ref mismatch")
    if collection["review_request_set_ref"] != {
        "review_request_set_id": proposal["request_ref"]["review_request_set_id"],
        "review_request_set_digest": proposal["request_ref"][
            "review_request_set_digest"
        ],
    }:
        raise ValueError("reading collection review-request binding mismatch")
    expected_groups = [
        {
            "reading_group_id": group["reading_group_id"],
            "reading_group_digest": group["reading_group_digest"],
            "source_id": group["source_ref"]["source_id"],
            "report_set_id": group["report_set_ref"]["report_set_id"],
            "report_set_digest": group["report_set_ref"]["report_set_digest"],
        }
        for group in collection["reading_groups"]
    ]
    for index, action in enumerate(proposal["actions"]):
        if action["reading_group_refs"] != expected_groups:
            raise ValueError(
                f"proposal.actions[{index}] does not bind every collection group in order"
            )

    expected_pack_digest = digest_json(without(pack, "pack_id", "pack_digest"))
    if pack["pack_digest"] != expected_pack_digest:
        raise ValueError("evidence_pack.pack_digest mismatch")
    if pack["pack_id"] != f"network-patch-evidence-pack-{expected_pack_digest[:16]}":
        raise ValueError("evidence_pack.pack_id mismatch")

    if regenerate:
        producer_name = (
            "propose_patch_v4"
            if proposal.get("schema") == PATCH_V4_SCHEMA
            else "propose_patch_v3"
        )
        producer = getattr(module, producer_name, None)
        if not callable(producer):
            raise ValueError(f"network-gap producer lacks {producer_name}")
        with tempfile.TemporaryDirectory(
            prefix="rkn-authorized-collection-snapshot-"
        ) as raw_stage:
            stage = Path(raw_stage)
            staged_paths: dict[str, Path] = {}
            for role in sorted(EVIDENCE_PACK_V2_FILE_ROLES):
                staged_path = stage / f"{role}.json"
                _write_private_snapshot(staged_path, raw_files[role])
                staged_paths[role] = staged_path
            try:
                regenerated = producer(
                    staged_paths["preconsumption_hypotheses"],
                    live_network,
                    staged_paths["review_requests"],
                    staged_paths["reading_collection"],
                    staged_paths["consumption_authority"],
                    expected_authority_file_sha256=expected_authority_sha,
                )
            except Exception as exc:
                raise ValueError(
                    f"strict authorized multi-reading regeneration failed: {exc}"
                ) from exc
        for role, path in paths.items():
            current_raw, _ = _stable_file_bytes(
                path, f"evidence_pack.artifacts.{role} postcheck"
            )
            if current_raw != raw_files[role]:
                raise ValueError(
                    f"evidence_pack artifact drifted during regeneration: {role}"
                )
        if regenerated != proposal:
            raise ValueError(
                "strict multi-reading regeneration does not match proposal payload"
            )
    return pack


def validate_evidence_pack(
    value: Any,
    proposal: dict[str, Any],
    network_ref: dict[str, str],
    *,
    live_network: dict[str, Any],
    expected_authority_file_sha256: str | None = None,
    regenerate: bool = True,
) -> dict[str, Any]:
    schema = value.get("schema") if isinstance(value, dict) else None
    if schema == EVIDENCE_PACK_SCHEMA:
        if (
            proposal.get("schema") != PATCH_V2_SCHEMA
            and proposal.get("schema") != PATCH_V1_SCHEMA
        ):
            raise ValueError("NetworkPatchEvidencePack/v1 requires proposal v1 or v2")
        return validate_evidence_pack_v1(
            value,
            proposal,
            network_ref,
            live_network=live_network,
            regenerate=regenerate,
        )
    if schema == EVIDENCE_PACK_V2_SCHEMA:
        if expected_authority_file_sha256 is None:
            raise ValueError(
                "NetworkPatchEvidencePack/v2 requires a caller-held "
                "expected authority file SHA-256"
            )
        return validate_evidence_pack_v2(
            value,
            proposal,
            network_ref,
            live_network=live_network,
            expected_authority_file_sha256=expected_authority_file_sha256,
            regenerate=regenerate,
        )
    raise ValueError("evidence_pack must use NetworkPatchEvidencePack/v1 or v2")


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
                "allowed_operation_types": (
                    []
                    if action["action_status"] == "blocked"
                    else {
                        "propose_node": [],
                        "propose_relation": [
                            "add-claim",
                            "add-evidence",
                            "add-relation",
                            "transition-gap",
                        ],
                        "propose_evidence_extension": [
                            "add-evidence",
                            "add-relation",
                            "transition-gap",
                        ],
                        "propose_evidence": ["add-evidence", "transition-gap"],
                    }[action["action_type"]]
                ),
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


def proposal_independence_errors(proposal: dict[str, Any]) -> list[str]:
    """Return source-independence blockers for newly applicable science."""

    errors: list[str] = []
    for index, action in enumerate(proposal.get("actions", [])):
        if action.get("action_type") not in {
            "propose_relation",
            "propose_evidence_extension",
        }:
            continue
        target = action.get("target_claim")
        existing = action.get("existing_claim_ref")
        impact = (
            target.get("impact")
            if isinstance(target, dict)
            else (
                existing.get("claim_semantics", {}).get("impact")
                if isinstance(existing, dict)
                and isinstance(existing.get("claim_semantics"), dict)
                else None
            )
        )
        if impact != "high":
            continue
        bases = action.get("reviewed_evidence", [])
        source_ids = {
            basis.get("source_id") for basis in bases if isinstance(basis, dict)
        }
        has_full_text = any(
            isinstance(basis, dict) and basis.get("access_level") == "full_text"
            for basis in bases
        )
        if len(source_ids) < 2:
            errors.append(
                f"proposal.actions[{index}] high-impact target requires at least "
                "two distinct source IDs"
            )
        if not has_full_text:
            errors.append(
                f"proposal.actions[{index}] high-impact target requires full text"
            )
    return errors


def require_applicable_source_independence(proposal: dict[str, Any]) -> None:
    errors = proposal_independence_errors(proposal)
    if errors:
        raise ValueError("; ".join(errors))


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
    acceptance_file = _canonical_absolute_path(acceptance_path, "acceptance.path")
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
    appraisal_gate: dict[str, Any] | None = None,
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
    if (
        acceptance["schema"] != ACCEPTANCE_SCHEMA
        or acceptance["schema_version"] != "1.0"
    ):
        raise ValueError("acceptance schema/version invalid")
    validate_network_ref(
        acceptance["network_ref"], network_ref, "acceptance.network_ref"
    )
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
        validate_authority_basis(item, f"acceptance.operator.authority_basis[{index}]")[
            "basis_id"
        ]
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
        if (
            decision["action_id"] != action["action_id"]
            or decision["action_digest"] != action["action_digest"]
        ):
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
        if decision["decision"] == "accept" and action["action_status"] == "blocked":
            raise ValueError(f"{label} blocked action cannot be accepted or applied")
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
                    raise ValueError(
                        f"{label} add-evidence must bind exactly one basis"
                    )
                basis = resolved_basis[0]
                binding_row = (
                    _binding_row(appraisal_gate, action, basis)
                    if appraisal_gate is not None
                    else None
                )
                projected_relation = (
                    binding_row["allowed_relation"]
                    if binding_row is not None
                    else "supports"
                )
                independence_group = (
                    binding_row["independence_group"]
                    if binding_row is not None
                    else source_independence_group(basis)
                )
                expected_evidence = {
                    "evidence_id": basis["evidence_id"],
                    "claim_id": (
                        target_claim_id(action)
                        if action["action_type"]
                        in {"propose_relation", "propose_evidence_extension"}
                        else basis["claim_id"]
                    ),
                    "source_id": basis["source_id"],
                    "polarity": projected_relation,
                    "exact_locator": basis["evidence_locator"],
                    "independence_group": independence_group,
                    "summary": action["hypothesis"],
                    "notes": f"accepted from {proposal['schema']}",
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
                if proposal["schema"] == PATCH_V2_SCHEMA:
                    if payload["gap_id"] != action["hypothesis_id"]:
                        raise ValueError(
                            f"{label} gap transition targets another hypothesis"
                        )
                elif payload["gap_id"] not in {
                    ref["gap_id"] for ref in action["origin_gap_refs"]
                }:
                    raise ValueError(
                        f"{label} gap transition targets a foreign origin gap"
                    )
                if {
                    (ref["basis_id"], ref["basis_digest"])
                    for ref in operation["basis_refs"]
                } != set(action_basis_order):
                    raise ValueError(
                        f"{label} gap transition must bind every action basis"
                    )
                if set(payload["evidence_refs"]) != {
                    basis["evidence_id"] for basis in action["reviewed_evidence"]
                }:
                    raise ValueError(f"{label} gap transition evidence refs mismatch")
                transition_operations.append(operation)
        if decision["decision"] == "accept":
            if proposal["schema"] == PATCH_V2_SCHEMA:
                if len(transition_operations) > 1 or (
                    transition_operations
                    and operations[-1]["operation_type"] != "transition-gap"
                ):
                    raise ValueError(f"{label} allows at most one final gap transition")
            else:
                origins = action["origin_gap_refs"]
                if len(transition_operations) != len(origins):
                    raise ValueError(
                        f"{label} must transition every origin gap atomically"
                    )
                if operations[-len(origins) :] != transition_operations:
                    raise ValueError(
                        f"{label} origin gap transitions must be the final operations"
                    )
                for transition, origin in zip(transition_operations, origins):
                    payload = transition["payload"]
                    if (
                        payload["gap_id"] != origin["gap_id"]
                        or payload["from_record_id"] != origin["record_id"]
                        or payload["status"] != "resolved"
                    ):
                        raise ValueError(
                            f"{label} origin gap transition is not the exact current record"
                        )
                    if action[
                        "action_type"
                    ] == "propose_evidence_extension" and payload[
                        "resolution_source"
                    ] != target_claim_id(action):
                        raise ValueError(
                            f"{label} extension resolution_source must be the existing claim"
                        )
            signature = action["target_signature"]["signature"]
            if action["action_type"] in {
                "propose_relation",
                "propose_evidence_extension",
            }:
                expected_types = []
                if action["action_type"] == "propose_relation":
                    expected_types.append("add-claim")
                expected_types.extend(["add-evidence"] * len(action_basis))
                expected_types.extend(["add-relation"] * len(action_basis))
                expected_types.extend(["transition-gap"] * len(transition_operations))
                if operation_types != expected_types:
                    raise ValueError(
                        f"{label} relation operation sequence is not canonical"
                    )
                if (
                    len(node_operations)
                    != (1 if action["action_type"] == "propose_relation" else 0)
                    or len(evidence_operations) != len(action_basis)
                    or len(relation_operations) != len(action_basis)
                ):
                    raise ValueError(f"{label} relation mapping is incomplete")
                observed_basis_order = [
                    (basis["basis_id"], basis["basis_digest"])
                    for _, basis in evidence_operations
                ]
                if observed_basis_order != action_basis_order:
                    raise ValueError(
                        f"{label} evidence operations cross or reorder bases"
                    )
                for relation, identity in zip(relation_operations, action_basis_order):
                    basis = action_basis[identity]
                    binding_row = (
                        _binding_row(appraisal_gate, action, basis)
                        if appraisal_gate is not None
                        else None
                    )
                    projected_relation = (
                        binding_row["allowed_relation"]
                        if binding_row is not None
                        else "supports"
                    )
                    relation_payload = relation["payload"]
                    if relation["basis_refs"] != [
                        {"basis_id": identity[0], "basis_digest": identity[1]}
                    ]:
                        raise ValueError(
                            f"{label} relation operation must bind one ordered basis"
                        )
                    expected_relation = {
                        "relation_id": relation_operation_id(
                            action, basis, projected_relation
                        ),
                        "relation_type": projected_relation,
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
                expected_types.extend(["transition-gap"] * len(transition_operations))
                if operation_types != expected_types or len(action_basis) != 1:
                    raise ValueError(
                        f"{label} evidence action requires one exact basis"
                    )
                if evidence_operations[0][0]["payload"]["evidence_id"] != signature:
                    raise ValueError(
                        f"{label} evidence does not match target signature"
                    )
            else:
                raise ValueError(
                    f"{label} propose_node acceptance requires a closed target_node"
                )
    require_unique(operation_ids, "acceptance operation IDs")
    require_unique(operation_digests, "acceptance operation digests")
    expected = digest_json(without(acceptance, "acceptance_id", "acceptance_digest"))
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
                expected_authority_file_sha256=getattr(
                    args, "expected_authority_file_sha256", None
                ),
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
            proposal = validate_proposal(proposal, network_ref, live_network)
            require_onboarded_sources(proposal, live_network)
            validate_evidence_pack(
                evidence_pack,
                proposal,
                network_ref,
                live_network=live_network,
                expected_authority_file_sha256=args.expected_authority_file_sha256,
            )
            appraisal_gate, _ = _load_optional_appraisal_gate(
                args, proposal, network_ref, paths, records
            )
            independence_errors = proposal_independence_errors(proposal)
            output = {
                "schema": VALIDATION_SCHEMA,
                "proposal_schema": proposal["schema"],
                "proposal_id": proposal["proposal_id"],
                "proposal_digest": proposal["proposal_digest"],
                "network_ref": network_ref,
                "valid": True,
                "apply_eligible": appraisal_gate is not None
                and not independence_errors,
                "appraisal_status": (
                    "reviewed_appraisal"
                    if appraisal_gate is not None
                    else "not_appraised_legacy"
                ),
                "reason": (
                    "; ".join(independence_errors)
                    if independence_errors
                    else (
                        "explicit_acceptance_still_required"
                        if appraisal_gate is not None
                        else "finalized_appraisal_binding_and_reviewed_projection_required"
                    )
                ),
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


def _safe_control_output(
    root: Path, directory_name: str, raw_output: str, label: str
) -> Path:
    directory = root / directory_name
    if directory.exists() or directory.is_symlink():
        metadata = directory.lstat()
        if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
            raise ValueError(f"{label} root must be a non-symlink directory")
    else:
        directory.mkdir(mode=0o700)
        kn._fsync_directory(root)
    output = Path(raw_output).expanduser()
    if not output.is_absolute():
        output = root / output
    if Path(os.path.normpath(str(output))) != output:
        raise ValueError(f"{label} output must be a canonical path")
    if output.parent != directory or not output.name or output.name.startswith("."):
        raise ValueError(
            f"{label} output must be a direct child of <root>/{directory_name}"
        )
    if os.path.lexists(output):
        raise ValueError(f"{label} output already exists; overwrite is forbidden")
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
        raise ValueError(
            "plan output appeared concurrently; overwrite refused"
        ) from exc
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def command_bind_appraisal(args: argparse.Namespace) -> int:
    paths = kn._safe_paths(args.root, args.network_id)
    with kn._exclusive_lock(paths):
        state, records, network_ref = validate_live_network(paths)
        live_network = kn._knowledge_network_export(paths, state, records)
        proposal = validate_proposal(
            read_contract(args.proposal, "proposal"), network_ref, live_network
        )
        require_onboarded_sources(proposal, live_network)
        require_applicable_source_independence(proposal)
        evidence_pack = read_contract(args.evidence_pack, "evidence_pack")
        validate_evidence_pack(
            evidence_pack,
            proposal,
            network_ref,
            live_network=live_network,
            expected_authority_file_sha256=args.expected_authority_file_sha256,
        )
        package = read_contract(args.appraisal_package, "appraisal package")
        approval = read_contract(args.appraisal_approval, "appraisal approval")
        prepared = read_contract(args.appraisal_prepared, "appraisal preparation")
        independent_review = read_contract(
            args.appraisal_independent_review, "appraisal independent review"
        )
        owner_bundle = read_contract(
            args.appraisal_owner_bundle, "appraisal owner bundle"
        )
        lineage = [
            read_contract(path, f"appraisal lineage[{index}]")
            for index, path in enumerate(args.appraisal_lineage)
        ]
        binding = appraisal_binding.create_binding(
            package,
            approval,
            prepared,
            independent_review,
            owner_bundle,
            lineage,
            args.expected_authority_sha256,
            proposal,
            network_ref,
            kn._scientific_binding_guard(paths, records),
            kn._claim_scopes_from_records(records),
            bound_at=args.as_of,
        )
        output_path = _safe_control_output(
            paths.root,
            "appraisal-bindings",
            args.output,
            "appraisal binding",
        )
        _write_json_exclusive_atomic(output_path, binding)
    print(json.dumps(binding, ensure_ascii=False, sort_keys=True, indent=2))
    return 0


def command_review_appraisal(args: argparse.Namespace) -> int:
    paths = kn._safe_paths(args.root, args.network_id)
    with kn._exclusive_lock(paths):
        state, records, network_ref = validate_live_network(paths)
        live_network = kn._knowledge_network_export(paths, state, records)
        proposal = validate_proposal(
            read_contract(args.proposal, "proposal"), network_ref, live_network
        )
        require_onboarded_sources(proposal, live_network)
        require_applicable_source_independence(proposal)
        package = read_contract(args.appraisal_package, "appraisal package")
        approval = read_contract(args.appraisal_approval, "appraisal approval")
        prepared = read_contract(args.appraisal_prepared, "appraisal preparation")
        independent_review = read_contract(
            args.appraisal_independent_review, "appraisal independent review"
        )
        owner_bundle = read_contract(
            args.appraisal_owner_bundle, "appraisal owner bundle"
        )
        lineage = [
            read_contract(path, f"appraisal lineage[{index}]")
            for index, path in enumerate(args.appraisal_lineage)
        ]
        binding_value = read_contract(args.appraisal_binding, "appraisal binding")
        prefix_counts = {
            name: int(binding_value["network_guard"]["ledgers"][name]["record_count"])
            for name in kn.LEDGER_NAMES
        }
        binding = appraisal_binding.validate_binding(
            binding_value,
            package,
            approval,
            prepared,
            independent_review,
            owner_bundle,
            lineage,
            args.expected_authority_sha256,
            proposal,
            network_ref,
            kn._claim_scopes_from_records(records, prefix_counts=prefix_counts),
        )
        if kn._scientific_binding_guard(paths, records) != binding["network_guard"]:
            raise ValueError("appraisal binding is stale before projection review")
        review = read_contract(args.review, "projection review")
        projection = appraisal_binding.create_reviewed_projection(
            binding,
            proposal,
            review,
            reviewed_at=args.as_of,
        )
        output_path = _safe_control_output(
            paths.root,
            "appraisal-projections",
            args.output,
            "appraisal projection",
        )
        _write_json_exclusive_atomic(output_path, projection)
    print(json.dumps(projection, ensure_ascii=False, sort_keys=True, indent=2))
    return 0


def command_prepare(args: argparse.Namespace) -> int:
    paths = kn._safe_paths(args.root, args.network_id)
    with kn._exclusive_lock(paths):
        state, records, network_ref = validate_live_network(paths)
        live_network = kn._knowledge_network_export(paths, state, records)
        proposal = read_contract(args.proposal, "proposal")
        evidence_pack = read_contract(args.evidence_pack, "evidence_pack")
        if proposal.get("schema") not in {
            PATCH_V2_SCHEMA,
            PATCH_V3_SCHEMA,
            PATCH_V4_SCHEMA,
        }:
            raise ValueError("prepare accepts only NetworkPatchProposal/v2, v3, or v4")
        proposal = validate_proposal(proposal, network_ref, live_network)
        require_onboarded_sources(proposal, live_network)
        require_applicable_source_independence(proposal)
        validate_evidence_pack(
            evidence_pack,
            proposal,
            network_ref,
            live_network=live_network,
            expected_authority_file_sha256=args.expected_authority_file_sha256,
        )
        _load_optional_appraisal_gate(args, proposal, network_ref, paths, records)
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
    staging_root: Path,
    network_id: str,
    operation: dict[str, Any],
    appraisal_cli_args: list[str],
) -> None:
    stdout = io.StringIO()
    stderr = io.StringIO()
    argv = [
        "--root",
        str(staging_root),
        "--network-id",
        network_id,
        *operation_arguments(operation),
        *appraisal_cli_args,
    ]
    with (
        kn._network_patch_atomic_context(),
        redirect_stdout(stdout),
        redirect_stderr(stderr),
    ):
        result = kn.main(argv)
    if result != 0:
        reason = (
            stderr.getvalue().strip() or stdout.getvalue().strip() or "unknown error"
        )
        raise ValueError(
            f"typed operation {operation['operation_id']} failed: {reason}"
        )


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
        raise ValueError(
            f"proposal actions already have terminal decisions: {repeated}"
        )


def decision_event(
    proposal: dict[str, Any],
    plan: dict[str, Any],
    acceptance: dict[str, Any],
    appraisal_gate: dict[str, Any] | None = None,
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
        "appraisal_gate": (
            copy.deepcopy(appraisal_gate["refs"])
            if appraisal_gate is not None
            else {
                "status": "not_appraised_legacy",
                "appraisal_package_ref": None,
                "appraisal_set_ref": None,
                "approval_ref": None,
                "owner_artifact_binding_digests": None,
                "expected_authority_sha256": None,
                "binding_ref": None,
                "projection_ref": None,
            }
        ),
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


def validate_resolved_derived_gap_postconditions(
    staged_state: dict[str, Any],
    staged_records: dict[str, list[dict[str, Any]]],
    acceptance: dict[str, Any],
) -> None:
    """Reject a staged resolution when deterministic derivation still emits it."""

    gaps_by_record = {
        row.get("record_id"): row
        for row in staged_records["gaps"]
        if isinstance(row.get("record_id"), str)
    }
    resolved_derived: set[str] = set()
    for decision in acceptance["decisions"]:
        if decision["decision"] != "accept":
            continue
        for operation in decision["operations"]:
            if operation["operation_type"] != "transition-gap":
                continue
            payload = operation["payload"]
            if payload["status"] != "resolved":
                continue
            prior = gaps_by_record.get(payload["from_record_id"])
            if not isinstance(prior, dict):
                continue
            if (
                prior.get("derivation_source") == "derive-gaps"
                or prior.get("source") == "derive-gaps"
            ):
                resolved_derived.add(payload["gap_id"])
    if not resolved_derived:
        return
    still_derived = {
        str(payload["gap_id"])
        for payload in kn._build_derived_gap_payloads(staged_state, staged_records)
    }
    violations = sorted(resolved_derived & still_derived)
    if violations:
        raise ValueError(
            "derived gap postcondition failed; resolved predicates still hold: "
            f"{violations}"
        )


def command_apply(args: argparse.Namespace) -> int:  # noqa: C901
    paths = kn._safe_paths(args.root, args.network_id)
    proposal_value = read_contract(args.proposal, "proposal")
    plan_value = read_contract(args.plan, "plan")
    acceptance_value = read_contract(args.acceptance, "acceptance")
    evidence_pack_value = read_contract(args.evidence_pack, "evidence_pack")
    with kn._exclusive_lock(paths):
        state, records, network_ref = validate_live_network(paths)
        live_network = kn._knowledge_network_export(paths, state, records)
        if proposal_value.get("schema") not in {
            PATCH_V2_SCHEMA,
            PATCH_V3_SCHEMA,
            PATCH_V4_SCHEMA,
        }:
            raise ValueError("apply accepts only NetworkPatchProposal/v2, v3, or v4")
        proposal = validate_proposal(proposal_value, network_ref, live_network)
        require_onboarded_sources(proposal, live_network)
        require_applicable_source_independence(proposal)
        validate_evidence_pack(
            evidence_pack_value,
            proposal,
            network_ref,
            live_network=live_network,
            expected_authority_file_sha256=args.expected_authority_file_sha256,
        )
        appraisal_gate, appraisal_cli_args = _load_optional_appraisal_gate(
            args, proposal, network_ref, paths, records
        )
        plan = validate_plan(plan_value, proposal, network_ref)
        acceptance = validate_acceptance(
            acceptance_value,
            proposal,
            plan,
            network_ref,
            appraisal_gate=appraisal_gate,
        )
        accepted_science = any(
            decision["decision"] == "accept" and decision["operations"]
            for decision in acceptance["decisions"]
        )
        if accepted_science and appraisal_gate is None:
            raise ValueError(
                "accepted scientific mutation requires finalized appraisal binding "
                "and reviewed exact-operation projection; legacy patch artifacts are read-only"
            )
        if accepted_science:
            validate_appraised_acceptance(acceptance, appraisal_gate, records)
        verify_authority_artifacts(acceptance, args.acceptance)
        reject_prior_terminal_decisions(records, acceptance)
        with tempfile.TemporaryDirectory(
            prefix=".network-patch-", dir=paths.root
        ) as raw:
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
                            staging_root,
                            paths.network_id,
                            operation,
                            appraisal_cli_args,
                        )
            staging_paths = kn._safe_paths(str(staging_root), paths.network_id)
            with kn._exclusive_lock(staging_paths):
                staged_state, staged_records = kn._load_state(staging_paths)
                validate_resolved_derived_gap_postconditions(
                    staged_state, staged_records, acceptance
                )
                event_payload = decision_event(
                    proposal, plan, acceptance, appraisal_gate
                )
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
                "appraisal_status": (
                    "reviewed_appraisal"
                    if appraisal_gate is not None
                    else "not_appraised_legacy"
                ),
                "before_network_ref": network_ref,
                "after_network_ref": after_ref,
                "decision_counts": {
                    decision: sum(
                        item["decision"] == decision for item in acceptance["decisions"]
                    )
                    for decision in sorted(DECISIONS)
                },
            }
            if not args.dry_run:
                contents = {
                    paths.state: staging_paths.state.read_text(encoding="utf-8")
                }
                ledger_updates = {
                    paths.ledger(name): (records[name], staged_records[name])
                    for name in kn.LEDGER_NAMES
                }
                kn._replace_files_transactionally(contents, ledger_updates)
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

    def add_appraisal_gate(command: argparse.ArgumentParser) -> None:
        command.add_argument("--appraisal-package")
        command.add_argument("--appraisal-approval")
        command.add_argument("--appraisal-prepared")
        command.add_argument("--appraisal-independent-review")
        command.add_argument("--appraisal-owner-bundle")
        command.add_argument("--appraisal-lineage", action="append", default=[])
        command.add_argument("--expected-authority-sha256")
        command.add_argument("--appraisal-binding")
        command.add_argument("--appraisal-projection")

    def add_collection_authority_pin(command: argparse.ArgumentParser) -> None:
        command.add_argument(
            "--expected-authority-file-sha256",
            help=(
                "caller-held SHA-256 of the exact detached collection-consumption "
                "authority file; required at runtime for proposal v3/v4"
            ),
        )

    validate = commands.add_parser("validate-patch")
    validate.add_argument("--proposal", required=True)
    validate.add_argument("--evidence-pack", required=True)
    add_collection_authority_pin(validate)
    add_appraisal_gate(validate)
    validate.set_defaults(func=command_validate)
    prepare = commands.add_parser("prepare-patch")
    prepare.add_argument("--proposal", required=True)
    prepare.add_argument("--evidence-pack", required=True)
    prepare.add_argument("--output", required=True)
    add_collection_authority_pin(prepare)
    add_appraisal_gate(prepare)
    prepare.set_defaults(func=command_prepare)
    apply = commands.add_parser("apply-patch")
    apply.add_argument("--proposal", required=True)
    apply.add_argument("--evidence-pack", required=True)
    apply.add_argument("--plan", required=True)
    apply.add_argument("--acceptance", required=True)
    apply.add_argument("--dry-run", action="store_true")
    add_collection_authority_pin(apply)
    add_appraisal_gate(apply)
    apply.set_defaults(func=command_apply)
    bind = commands.add_parser("bind-appraisal")
    bind.add_argument("--proposal", required=True)
    bind.add_argument("--evidence-pack", required=True)
    bind.add_argument("--appraisal-package", required=True)
    bind.add_argument("--appraisal-approval", required=True)
    bind.add_argument("--appraisal-prepared", required=True)
    bind.add_argument("--appraisal-independent-review", required=True)
    bind.add_argument("--appraisal-owner-bundle", required=True)
    bind.add_argument("--appraisal-lineage", action="append", default=[])
    bind.add_argument("--expected-authority-sha256", required=True)
    add_collection_authority_pin(bind)
    bind.add_argument("--as-of", required=True)
    bind.add_argument("--output", required=True)
    bind.set_defaults(func=command_bind_appraisal)
    review = commands.add_parser("review-appraisal")
    review.add_argument("--proposal", required=True)
    review.add_argument("--appraisal-package", required=True)
    review.add_argument("--appraisal-approval", required=True)
    review.add_argument("--appraisal-prepared", required=True)
    review.add_argument("--appraisal-independent-review", required=True)
    review.add_argument("--appraisal-owner-bundle", required=True)
    review.add_argument("--appraisal-lineage", action="append", default=[])
    review.add_argument("--expected-authority-sha256", required=True)
    review.add_argument("--appraisal-binding", required=True)
    review.add_argument("--review", required=True)
    review.add_argument("--as-of", required=True)
    review.add_argument("--output", required=True)
    review.set_defaults(func=command_review_appraisal)
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
