#!/usr/bin/env python3
"""Build and validate PaperReadingDossier/v1 and project to v2 report sets."""

from __future__ import annotations

import argparse
import hashlib
import json
import importlib.util
import os
import re
import stat
import sys
import tempfile
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
_source_bundle_path = SCRIPT_DIR / "paper_source_bundle.py"
_source_bundle_spec = importlib.util.spec_from_file_location(
    "paper_source_bundle",
    str(_source_bundle_path),
)
if _source_bundle_spec is None or _source_bundle_spec.loader is None:
    raise RuntimeError("failed to load paper_source_bundle.py")
_source_bundle_module = importlib.util.module_from_spec(_source_bundle_spec)
_source_bundle_spec.loader.exec_module(_source_bundle_module)
SourceBundleContractError = _source_bundle_module.ContractError
locate_span = _source_bundle_module.locate_span
verify_bundle = _source_bundle_module.verify_bundle


SCHEMA = "PaperReadingDossier/v1"
SCHEMA_VERSION = "v1"
PROTOCOL_VERSION = "1.0"
PRODUCER = "learn-from-papers"
VERIFICATION_REQUEST_SCHEMA = "VerificationAttestationRequest/v1"
VERIFICATION_ATTESTATION_SCHEMA = "VerificationAttestation/v1"
VERIFIER_ATTESTATION_SCHEMA = VERIFICATION_ATTESTATION_SCHEMA
DOSSIER_PREFIX = "reading-dossier-"
DOSSIER_ID_PREFIX = "reading-dossier-"
V2_SET_PREFIX = "reading-report-set-v2-"
V2_REPORT_PREFIX = "reading-report-v2-"
SOURCE_BUNDLE_PREFIX = "paper-source-bundle-"
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
URL_ONLY_RE = re.compile(r"^https?://\S+$", re.IGNORECASE)
DOI_ONLY_RE = re.compile(r"(?i)^(?:doi:\s*)?10\.[0-9]{4,9}/\S+$")
EVIDENCE_ID_PREFIX = "evidence-"

DOSSIER_ACCESS_LEVELS = {"full_text", "partial_text", "abstract_only", "metadata_only"}
INSPECTION_DEPTHS = {"map", "evidence", "reconstruction"}
RECONSTRUCTION_STATUSES = {
    "not_applicable",
    "planned",
    "in_progress",
    "executed",
    "passed",
    "failed",
    "not_answerable",
}
RELATION_VALUES = {"supports", "qualifies", "refutes", "not_tested"}
VERIFICATION_MODES = {
    "independent_source_check",
    "same_context_diagnostic",
    "expert_review",
}
DECISIVE_VERIFICATION_MODES = {"independent_source_check", "expert_review"}
VERIFIER_STATUSES = {"passed", "failed", "unresolved", "not_tested"}
ORIGIN_VALUES = {"source", "reconstruction", "supplement"}
TERMINAL_STATES = {"decisive", "terminal", "non_eligible", "unanswered", "unanswerable"}
CARD_TYPES = {"page", "figure", "table", "equation", "theorem", "code", "supplement"}
RESULT_VALUES = {"passed", "failed", "not_run"}

V2_SCHEMA = "PaperReadingReportSet/v2"
V2_REPORT_SCHEMA = "PaperReadingReport/v2"
V2_SCHEMA_VERSION = "v2"
V2_RELATION_ALLOWLIST = RELATION_VALUES

REVIEW_SOURCE_KEYS = {"source_id", "source_digest", "acquisition_locator"}

DOSSIER_TOP_LEVEL_KEYS = {
    "schema",
    "schema_version",
    "producer",
    "protocol_version",
    "generated_at",
    "request_question_plan",
    "source_bundle",
    "review_source",
    "network_ref",
    "review_request_set_id",
    "review_request_set_digest",
    "review_request_id",
    "review_request_digest",
    "access_level",
    "inspection_depth",
    "reconstruction_status",
    "embedded_documents",
    "component_manifest",
    "claims",
    "evidence_records",
    "reconstruction_tasks",
    "correction_log",
    "unresolved_terminal_states",
    "claim_support_eligible",
    "gates",
    "completion_matrix",
    "audit_metrics",
    "dossier_id",
    "dossier_digest",
}

REQUEST_PLAN_KEYS = {
    "request_text",
    "subquestions",
    "abstention_conditions",
}
SUBQUESTION_KEYS = {"subquestion_id", "text", "required"}
ABSTENTION_KEYS = {"subquestion_id", "reason"}

EMBEDDED_DOCUMENT_KEYS = {"document_id", "instruction"}
COMPONENT_KEYS = {
    "component_id",
    "name",
    "artifact",
    "status",
    "inspected_units",
    "covered_units",
    "terminal_units",
    "document_id",
}
SCOPE_KEYS = {"assumptions", "conditions", "units", "exclusions"}

CLAIM_KEYS = {
    "claim_id",
    "hypothesis_id",
    "target_id",
    "statement",
    "relation",
    "origin",
    "scope",
    "verifier_status",
    "confidence",
    "evidence_ids",
    "subquestion_id",
    "verification",
    "reconstruction_task_ids",
    "citation_chain",
}
VERIFICATION_KEYS = {"mode", "verifier_id"}
VERIFICATION_LEGACY_KEYS = {"artifact_ref", "artifact_sha256", "subject_digest"}
VERIFICATION_REQUEST_KEYS = {
    "schema",
    "mode",
    "verifier_id",
    "producer_context_id",
    "subject_digest",
    "claim_id",
    "hypothesis_id",
    "target_id",
    "scope_digest",
    "evidence_bindings",
    "dossier_id",
    "dossier_digest",
    "source_bundle_id",
    "source_bundle_digest",
    "source_artifact_sha256",
    "support_candidate_eligible",
    "report_set_context",
    "expected_report_identities",
}
VERIFICATION_ATTESTATION_KEYS = {
    "schema",
    "mode",
    "verifier_id",
    "origin",
    "verdict",
    "basis",
    "request_ref",
    "request_digest",
    "subject_digest",
    "claim_id",
    "hypothesis_id",
    "target_id",
    "scope_digest",
    "evidence_bindings",
    "dossier_id",
    "dossier_digest",
    "source_bundle_id",
    "source_bundle_digest",
    "source_artifact_sha256",
    "support_candidate_eligible",
    "report_set_context",
    "expected_report_identities",
    "verifier_context_id",
    "producer_context_id",
    "created_at",
}
VERIFICATION_ORIGINS = {"external_verifier"}
REQUEST_BINDING_KEYS = {
    "evidence_id",
    "exact_locator",
    "page",
    "start_char",
    "end_char",
    "span_id",
    "span_hash",
}
VERIFICATION_REQUEST_DIR = "verification-requests"
VERIFICATION_ATTESTATION_DIR = "verification-attestations"
ATTESTATION_MODES = {"independent_source_check", "expert_review"}
ATTESTATION_VERDICTS = {
    "passed",
    "failed",
    "abstained",
    "not_run",
    "unresolved",
    "not_tested",
}

EVIDENCE_KEYS = {
    "evidence_id",
    "claim_id",
    "hypothesis_id",
    "target_id",
    "page",
    "start_char",
    "end_char",
    "relation",
    "verifier_status",
    "exact_locator",
    "card_type",
    "origin",
    "scope",
    "document_id",
    "span_hash",
    "span_id",
    "card",
    "reconstruction_task_ids",
    "citation_chain",
}

EVIDENCE_BINDING_KEYS = {
    "evidence_id",
    "exact_locator",
    "page",
    "start_char",
    "end_char",
    "span_id",
    "span_hash",
}

TASK_KEYS = {
    "task_id",
    "claim_id",
    "hypothesis_id",
    "command",
    "executed",
    "result",
    "result_match",
    "result_notes",
}
TERMINAL_ENTRY_KEYS = {"claim_id", "state", "reason"}
CORRECTION_LOG_KEYS = {"before", "source_check", "correction"}
NETWORK_REF_KEYS = {"network_id", "snapshot_id", "sha256"}

V2_SET_KEYS = {
    "schema",
    "schema_version",
    "producer",
    "protocol_version",
    "generated_at",
    "network_ref",
    "review_request_set_id",
    "review_request_set_digest",
    "source_bundle_id",
    "source_bundle_digest",
    "access_level",
    "inspection_depth",
    "reconstruction_status",
    "completion_matrix",
    "source_ref",
    "source_artifact_sha256",
    "review_source",
    "dossier_id",
    "dossier_digest",
    "report_set_id",
    "report_set_digest",
    "reports",
}

V2_REPORT_KEYS = {
    "schema",
    "schema_version",
    "producer",
    "protocol_version",
    "report_id",
    "report_digest",
    "review_request_id",
    "review_request_digest",
    "review_request_set_id",
    "review_request_set_digest",
    "hypothesis_id",
    "claim_id",
    "target_id",
    "claim_statement",
    "scope",
    "evidence_bindings",
    "evidence_relation",
    "relation",
    "actual_evidence_locator",
    "claim_support_eligible",
    "projection_status",
    "coverage_reason",
    "verifier_status",
    "access_level",
    "inspection_depth",
    "reconstruction_status",
    "source_bundle_id",
    "source_bundle_digest",
    "source_ref",
    "source_artifact_sha256",
    "review_source",
    "dossier_id",
    "dossier_digest",
    "evidence_ids",
    "verification",
}

REPORT_SET_ATTESTATION_CONTEXT_KEYS = V2_SET_KEYS - {
    "report_set_id",
    "report_set_digest",
    "reports",
}
EXPECTED_REPORT_IDENTITY_KEYS = {
    "claim_id",
    "hypothesis_id",
    "target_id",
    "subject_digest",
}

CARD_REQUIREMENTS = {
    "figure": {"caption", "axes", "render_required", "is_central_visual"},
    "table": {"title", "rows", "columns", "render_required", "is_central_visual"},
    "equation": {"expression", "variables", "render_required", "is_central_visual"},
    "theorem": {"statement", "assumptions", "dependencies"},
    "code": {"language", "snippet", "expected_output"},
    "supplement": {"description", "artifact_path"},
}


class ContractError(ValueError):
    """Raised when a dossier/report contract is violated."""


def canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
        "utf-8"
    )


def sha256_hex(value: Any) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _now_utc() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _require_non_empty_string(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ContractError(f"{label} must be a non-empty string")
    return value.strip()


def _require_bool(value: Any, label: str) -> bool:
    if not isinstance(value, bool):
        raise ContractError(f"{label} must be a boolean")
    return value


def _require_int(value: Any, label: str, minimum: int = 0) -> int:
    if not isinstance(value, int) or value < minimum:
        raise ContractError(f"{label} must be >= {minimum}")
    return value


def _require_list(value: Any, label: str) -> list[Any]:
    if not isinstance(value, list):
        raise ContractError(f"{label} must be a list")
    return value


def _require_dict(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ContractError(f"{label} must be an object")
    return value


def _require_sha256(value: Any, label: str) -> str:
    value = _require_non_empty_string(value, label)
    if not SHA256_RE.fullmatch(value):
        raise ContractError(f"{label} must be 64 lowercase hex")
    return value


def _require_timestamp(value: Any, label: str) -> str:
    value = _require_non_empty_string(value, label)
    if not value.endswith("Z"):
        raise ContractError(f"{label} must be UTC and end with Z")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ContractError(f"{label} must be UTC ISO-8601") from exc
    if parsed.tzinfo != timezone.utc:
        raise ContractError(f"{label} must be UTC")
    return value


def _require_enum(value: Any, label: str, values: set[str]) -> str:
    value = _require_non_empty_string(value, label)
    if value not in values:
        raise ContractError(f"{label} must be one of: {', '.join(sorted(values))}")
    return value


def _reject_unknown_fields(payload: dict[str, Any], allowed: set[str], label: str) -> None:
    extras = set(payload) - allowed
    if extras:
        raise ContractError(f"{label} contains unknown keys: {', '.join(sorted(extras))}")


def _require_string_list(value: Any, label: str, *, allow_empty: bool = True) -> list[str]:
    values = _require_list(value, label)
    for index, item in enumerate(values):
        if not isinstance(item, str) or not item.strip():
            raise ContractError(f"{label}[{index}] must be non-empty strings")
    if not allow_empty and not values:
        raise ContractError(f"{label} must not be empty")
    return [item.strip() for item in values]


def _validate_exact_locator(value: Any, label: str) -> str:
    text = _require_non_empty_string(value, label)
    lowered = text.lower()
    if URL_ONLY_RE.fullmatch(text) or DOI_ONLY_RE.fullmatch(lowered):
        raise ContractError(f"{label} must not be DOI/URL-only")
    return text


def _validate_network_ref(raw: Any, label: str) -> dict[str, str]:
    network = _require_dict(raw, label)
    _reject_unknown_fields(network, NETWORK_REF_KEYS, label)
    return {
        "network_id": _require_non_empty_string(network.get("network_id"), f"{label}.network_id"),
        "snapshot_id": _require_non_empty_string(network.get("snapshot_id"), f"{label}.snapshot_id"),
        "sha256": _require_sha256(network.get("sha256"), f"{label}.sha256"),
    }


def _validate_scope(raw: Any, label: str) -> dict[str, list[str]]:
    scope = _require_dict(raw, label)
    _reject_unknown_fields(scope, SCOPE_KEYS, label)
    return {
        "assumptions": _require_string_list(scope.get("assumptions", []), f"{label}.assumptions"),
        "conditions": _require_string_list(scope.get("conditions", []), f"{label}.conditions"),
        "units": _require_string_list(scope.get("units", []), f"{label}.units"),
        "exclusions": _require_string_list(scope.get("exclusions", []), f"{label}.exclusions"),
    }


def _validate_claim_verification(
    raw: Any,
    label: str,
    *,
    allow_artifact: bool = False,
) -> dict[str, Any]:
    verification = _require_dict(raw, label)
    _reject_unknown_fields(
        verification,
        VERIFICATION_KEYS | VERIFICATION_LEGACY_KEYS,
        label,
    )
    artifact_keys = VERIFICATION_LEGACY_KEYS.intersection(verification)
    if artifact_keys and not allow_artifact:
        raise ContractError(f"{label} draft must contain only mode and verifier_id")
    if artifact_keys and artifact_keys != VERIFICATION_LEGACY_KEYS:
        missing = VERIFICATION_LEGACY_KEYS - artifact_keys
        raise ContractError(
            f"{label} artifact binding is incomplete; missing: {', '.join(sorted(missing))}"
        )
    validated: dict[str, Any] = {
        "mode": _require_enum(
            verification.get("mode"),
            f"{label}.mode",
            VERIFICATION_MODES,
        ),
        "verifier_id": _require_non_empty_string(
            verification.get("verifier_id"),
            f"{label}.verifier_id",
        ),
    }
    if artifact_keys:
        validated.update(
            {
                "artifact_ref": _require_non_empty_string(
                    verification.get("artifact_ref"),
                    f"{label}.artifact_ref",
                ),
                "artifact_sha256": _require_sha256(
                    verification.get("artifact_sha256"),
                    f"{label}.artifact_sha256",
                ),
                "subject_digest": _require_sha256(
                    verification.get("subject_digest"),
                    f"{label}.subject_digest",
                ),
            }
        )
    return validated


def _validate_plan(raw: Any) -> dict[str, Any]:
    plan = _require_dict(raw, "request_question_plan")
    _reject_unknown_fields(plan, REQUEST_PLAN_KEYS, "request_question_plan")
    request_text = _require_non_empty_string(plan.get("request_text"), "request_question_plan.request_text")
    subquestions_raw = _require_list(plan.get("subquestions"), "request_question_plan.subquestions")
    if not subquestions_raw:
        raise ContractError("request_question_plan.subquestions must not be empty")

    seen_sub = set[str]()
    subquestions: list[dict[str, Any]] = []
    for index, item in enumerate(subquestions_raw):
        subquestion = _require_dict(item, f"request_question_plan.subquestions[{index}]")
        _reject_unknown_fields(
            subquestion,
            SUBQUESTION_KEYS,
            f"request_question_plan.subquestions[{index}]",
        )
        sub_id = _require_non_empty_string(
            subquestion.get("subquestion_id"), f"request_question_plan.subquestions[{index}].subquestion_id"
        )
        if sub_id in seen_sub:
            raise ContractError(f"duplicate subquestion_id: {sub_id}")
        seen_sub.add(sub_id)
        text = _require_non_empty_string(
            subquestion.get("text"),
            f"request_question_plan.subquestions[{index}].text",
        )
        required = _require_bool(subquestion.get("required"), f"request_question_plan.subquestions[{index}].required")
        subquestions.append(
            {"subquestion_id": sub_id, "text": text, "required": required}
        )

    abstention_conditions = []
    for index, item in enumerate(plan.get("abstention_conditions", [])):
        abst = _require_dict(item, f"request_question_plan.abstention_conditions[{index}]")
        _reject_unknown_fields(
            abst,
            ABSTENTION_KEYS,
            f"request_question_plan.abstention_conditions[{index}]",
        )
        abstention_conditions.append(
            {
                "subquestion_id": _require_non_empty_string(
                    abst.get("subquestion_id"),
                    f"request_question_plan.abstention_conditions[{index}].subquestion_id",
                ),
                "reason": _require_non_empty_string(
                    abst.get("reason"),
                    f"request_question_plan.abstention_conditions[{index}].reason",
                ),
            }
        )
    return {
        "request_text": request_text,
        "subquestions": subquestions,
        "abstention_conditions": abstention_conditions,
    }


def _validate_embedded_documents(raw: Any) -> list[dict[str, Any]]:
    docs = _require_list(raw, "embedded_documents")
    if not docs:
        raise ContractError("embedded_documents must not be empty")
    seen = set[str]()
    validated: list[dict[str, Any]] = []
    for index, item in enumerate(docs):
        doc = _require_dict(item, f"embedded_documents[{index}]")
        _reject_unknown_fields(doc, EMBEDDED_DOCUMENT_KEYS, f"embedded_documents[{index}]")
        doc_id = _require_non_empty_string(doc.get("document_id"), f"embedded_documents[{index}].document_id")
        if doc_id in seen:
            raise ContractError(f"duplicate document_id: {doc_id}")
        seen.add(doc_id)
        validated.append(
            {
                "document_id": doc_id,
                "instruction": _require_non_empty_string(
                    doc.get("instruction"),
                    f"embedded_documents[{index}].instruction",
                ),
            }
        )
    return validated


def _validate_component_manifest(raw: Any) -> list[dict[str, Any]]:
    components = _require_list(raw, "component_manifest")
    if not components:
        raise ContractError("component_manifest must not be empty")
    seen = set[str]()
    validated: list[dict[str, Any]] = []
    for index, item in enumerate(components):
        component = _require_dict(item, f"component_manifest[{index}]")
        _reject_unknown_fields(component, COMPONENT_KEYS, f"component_manifest[{index}]")
        component_id = _require_non_empty_string(
            component.get("component_id"), f"component_manifest[{index}].component_id"
        )
        if component_id in seen:
            raise ContractError(f"duplicate component_id: {component_id}")
        seen.add(component_id)
        inspected = _require_int(component.get("inspected_units"), f"component_manifest[{index}].inspected_units")
        covered = _require_int(component.get("covered_units"), f"component_manifest[{index}].covered_units")
        terminal = _require_int(component.get("terminal_units"), f"component_manifest[{index}].terminal_units")
        if covered > inspected:
            raise ContractError(
                f"component_manifest[{index}].covered_units cannot exceed inspected_units"
            )
        if terminal > inspected:
            raise ContractError(
                f"component_manifest[{index}].terminal_units cannot exceed inspected_units"
            )
        name = _require_non_empty_string(component.get("name"), f"component_manifest[{index}].name")
        artifact = _require_non_empty_string(component.get("artifact"), f"component_manifest[{index}].artifact")
        status = _require_enum(
            component.get("status"),
            f"component_manifest[{index}].status",
            {"covered", "partial", "not_covered", "not_applicable"},
        )
        document_id = _require_non_empty_string(
            component.get("document_id"),
            f"component_manifest[{index}].document_id",
        )
        validated.append(
            {
                "component_id": component_id,
                "name": name,
                "artifact": artifact,
                "status": status,
                "inspected_units": inspected,
                "covered_units": covered,
                "terminal_units": terminal,
                "document_id": document_id,
            }
        )
    return validated


def _validate_source_bundle(raw: Any, expected: dict[str, str] | None) -> dict[str, str]:
    bundle = _require_dict(raw, "source_bundle")
    _reject_unknown_fields(
        bundle,
        {"bundle_id", "bundle_digest", "source_ref", "source_artifact_sha256"},
        "source_bundle",
    )
    bundle_id = _require_non_empty_string(bundle.get("bundle_id"), "source_bundle.bundle_id")
    if not bundle_id.startswith(SOURCE_BUNDLE_PREFIX):
        raise ContractError("source_bundle.bundle_id has invalid prefix")
    bundle_digest = _require_sha256(bundle.get("bundle_digest"), "source_bundle.bundle_digest")
    source_ref = _require_non_empty_string(bundle.get("source_ref"), "source_bundle.source_ref")
    source_artifact_sha256 = _require_sha256(
        bundle.get("source_artifact_sha256"), "source_bundle.source_artifact_sha256"
    )
    if expected is not None:
        if expected["bundle_id"] != bundle_id:
            raise ContractError("source_bundle.bundle_id does not match verified source bundle")
        if expected["bundle_digest"] != bundle_digest:
            raise ContractError("source_bundle.bundle_digest does not match verified source bundle")
        if expected["source_ref"] != source_ref:
            raise ContractError("source_bundle.source_ref does not match verified source bundle")
        if expected["source_artifact_sha256"] != source_artifact_sha256:
            raise ContractError(
                "source_bundle.source_artifact_sha256 does not match verified source bundle"
            )
    return {
        "bundle_id": bundle_id,
        "bundle_digest": bundle_digest,
        "source_ref": source_ref,
        "source_artifact_sha256": source_artifact_sha256,
    }


def _validate_review_source(raw: Any, label: str) -> dict[str, str]:
    source = _require_dict(raw, label)
    _reject_unknown_fields(source, REVIEW_SOURCE_KEYS, label)
    return {
        "source_id": _require_non_empty_string(source.get("source_id"), f"{label}.source_id"),
        "source_digest": _require_sha256(source.get("source_digest"), f"{label}.source_digest"),
        "acquisition_locator": _require_non_empty_string(
            source.get("acquisition_locator"), f"{label}.acquisition_locator"
        ),
    }


def _validate_correction_log(raw: Any) -> list[dict[str, str]]:
    items = _require_list(raw, "correction_log")
    validated: list[dict[str, str]] = []
    for index, item in enumerate(items):
        log = _require_dict(item, f"correction_log[{index}]")
        _reject_unknown_fields(log, CORRECTION_LOG_KEYS, f"correction_log[{index}]")
        validated.append(
            {
                "before": _require_non_empty_string(log.get("before"), f"correction_log[{index}].before"),
                "source_check": _require_non_empty_string(
                    log.get("source_check"), f"correction_log[{index}].source_check"
                ),
                "correction": _require_non_empty_string(
                    log.get("correction"), f"correction_log[{index}].correction"
                ),
            }
        )
    return validated


def _validate_citation_item(item: Any, label: str) -> dict[str, Any]:
    citation = _require_dict(item, label)
    _reject_unknown_fields(
        citation,
        {"citation_id", "evidence_id", "exact_locator", "verified", "scope"},
        label,
    )
    return {
        "citation_id": _require_non_empty_string(citation.get("citation_id"), f"{label}.citation_id"),
        "evidence_id": _require_non_empty_string(citation.get("evidence_id"), f"{label}.evidence_id"),
        "exact_locator": _validate_exact_locator(
            citation.get("exact_locator"),
            f"{label}.exact_locator",
        ),
        "verified": _require_bool(citation.get("verified"), f"{label}.verified"),
        "scope": _validate_scope(citation.get("scope", {}), f"{label}.scope"),
    }


def _validate_card(card_type: str, raw: Any, label: str) -> dict[str, Any]:
    if raw is None:
        raise ContractError(f"{label} must be present for card_type {card_type}")
    card = _require_dict(raw, label)
    required = CARD_REQUIREMENTS[card_type]
    _reject_unknown_fields(card, required, label)
    normalized: dict[str, Any] = {}
    for key in sorted(required):
        if key in {"rows", "columns"}:
            value = _require_list(card.get(key), f"{label}.{key}")
            normalized[key] = [_require_non_empty_string(v, f"{label}.{key} item") for v in value]
            if not normalized[key]:
                raise ContractError(f"{label}.{key} must not be empty")
            continue
        if isinstance(card.get(key), bool):
            normalized[key] = _require_bool(card.get(key), f"{label}.{key}")
        elif key in {"is_central_visual", "render_required"}:
            normalized[key] = _require_bool(card.get(key), f"{label}.{key}")
        else:
            normalized[key] = _require_non_empty_string(card.get(key), f"{label}.{key}")
    return normalized


def _validate_claim(raw: Any, index: int, doc_ids: set[str], subquestion_ids: set[str]) -> dict[str, Any]:
    claim = _require_dict(raw, f"claims[{index}]")
    _reject_unknown_fields(claim, CLAIM_KEYS, f"claims[{index}]")
    claim_id = _require_non_empty_string(claim.get("claim_id"), f"claims[{index}].claim_id")
    hypothesis_id = _require_non_empty_string(claim.get("hypothesis_id"), f"claims[{index}].hypothesis_id")
    target_id = _require_non_empty_string(claim.get("target_id"), f"claims[{index}].target_id")
    statement = _require_non_empty_string(claim.get("statement"), f"claims[{index}].statement")
    relation = _require_enum(claim.get("relation"), f"claims[{index}].relation", RELATION_VALUES)
    origin = _require_enum(claim.get("origin"), f"claims[{index}].origin", ORIGIN_VALUES)
    scope = _validate_scope(claim.get("scope", {}), f"claims[{index}].scope")
    verifier_status = _require_enum(claim.get("verifier_status"), f"claims[{index}].verifier_status", VERIFIER_STATUSES)
    confidence = _require_enum(
        claim.get("confidence"), f"claims[{index}].confidence", {"low", "medium", "high"}
    )
    evidence_ids = _require_string_list(
        claim.get("evidence_ids", []),
        f"claims[{index}].evidence_ids",
    )
    subquestion_id = claim.get("subquestion_id")
    if subquestion_id is not None:
        subquestion_id = _require_non_empty_string(subquestion_id, f"claims[{index}].subquestion_id")
        if subquestion_id not in subquestion_ids:
            raise ContractError(
                f"claims[{index}].subquestion_id references unknown subquestion: {subquestion_id}"
            )

    reconstruction_task_ids = _require_string_list(
        claim.get("reconstruction_task_ids", []),
        f"claims[{index}].reconstruction_task_ids",
    )
    citation_chain = _require_list(claim.get("citation_chain", []), f"claims[{index}].citation_chain")
    resolved_chain = [_validate_citation_item(item, f"claims[{index}].citation_chain[{i}]") for i, item in enumerate(citation_chain)]
    verification = _validate_claim_verification(
        claim.get("verification"),
        f"claims[{index}].verification",
    )

    return {
        "claim_id": claim_id,
        "hypothesis_id": hypothesis_id,
        "target_id": target_id,
        "statement": statement,
        "relation": relation,
        "origin": origin,
        "scope": scope,
        "verifier_status": verifier_status,
        "confidence": confidence,
        "evidence_ids": evidence_ids,
        "subquestion_id": subquestion_id,
        "verification": verification,
        "reconstruction_task_ids": reconstruction_task_ids,
        "citation_chain": resolved_chain,
    }


def _validate_evidence(
    raw: Any, index: int, claims: set[str], docs: set[str], task_ids: set[str]
) -> dict[str, Any]:
    evidence = _require_dict(raw, f"evidence_records[{index}]")
    _reject_unknown_fields(evidence, EVIDENCE_KEYS, f"evidence_records[{index}]")

    evidence_id = _require_non_empty_string(evidence.get("evidence_id"), f"evidence_records[{index}].evidence_id")
    claim_id = _require_non_empty_string(evidence.get("claim_id"), f"evidence_records[{index}].claim_id")
    if claim_id not in claims:
        raise ContractError(f"evidence_records[{index}].claim_id references unknown claim")
    hypothesis_id = _require_non_empty_string(evidence.get("hypothesis_id"), f"evidence_records[{index}].hypothesis_id")
    target_id = _require_non_empty_string(evidence.get("target_id"), f"evidence_records[{index}].target_id")
    page = _require_int(evidence.get("page"), f"evidence_records[{index}].page", minimum=1)
    start_char = _require_int(evidence.get("start_char"), f"evidence_records[{index}].start_char")
    end_char = _require_int(evidence.get("end_char"), f"evidence_records[{index}].end_char")
    if end_char < start_char:
        raise ContractError(f"evidence_records[{index}].end_char must be >= start_char")
    relation = _require_enum(
        evidence.get("relation"),
        f"evidence_records[{index}].relation",
        RELATION_VALUES,
    )
    verifier_status = _require_enum(
        evidence.get("verifier_status"),
        f"evidence_records[{index}].verifier_status",
        VERIFIER_STATUSES,
    )
    exact_locator = _validate_exact_locator(
        evidence.get("exact_locator"), f"evidence_records[{index}].exact_locator"
    )
    card_type = _require_enum(evidence.get("card_type"), f"evidence_records[{index}].card_type", CARD_TYPES)
    origin = _require_enum(
        evidence.get("origin"),
        f"evidence_records[{index}].origin",
        ORIGIN_VALUES,
    )
    scope = _validate_scope(evidence.get("scope", {}), f"evidence_records[{index}].scope")
    document_id = _require_non_empty_string(
        evidence.get("document_id"), f"evidence_records[{index}].document_id"
    )
    if document_id not in docs:
        raise ContractError(f"evidence_records[{index}].document_id references unknown document")
    card = evidence.get("card")
    if card_type in CARD_REQUIREMENTS and card_type != "page":
        card = _validate_card(card_type, card, f"evidence_records[{index}].card")
    elif card_type == "page":
        if card not in ({}, None):
            raise ContractError(
                f"evidence_records[{index}].card is not expected for card_type=page"
            )
    elif card is not None:
        raise ContractError(
            f"evidence_records[{index}].card is not expected for card_type={card_type}"
        )

    task_refs = _require_string_list(
        evidence.get("reconstruction_task_ids", []),
        f"evidence_records[{index}].reconstruction_task_ids",
    )
    for task_id in task_refs:
        if task_id not in task_ids:
            # strict cross-artifact isolation.
            raise ContractError(
                f"evidence_records[{index}].reconstruction_task_ids[{task_refs.index(task_id)}] "
                f"references unknown task {task_id}"
            )

    span_hash = evidence.get("span_hash")
    if span_hash is not None:
        span_hash = _require_sha256(span_hash, f"evidence_records[{index}].span_hash")
    span_id = evidence.get("span_id")
    if span_id is not None:
        span_id = _require_non_empty_string(span_id, f"evidence_records[{index}].span_id")
        if not span_id.startswith("source-passages-span-"):
            raise ContractError(
                f"evidence_records[{index}].span_id must be source-passages-span-<16hex>"
            )

    citation_chain = _require_list(evidence.get("citation_chain", []), f"evidence_records[{index}].citation_chain")
    resolved_chain = [_validate_citation_item(item, f"evidence_records[{index}].citation_chain[{i}]") for i, item in enumerate(citation_chain)]

    return {
        "evidence_id": evidence_id,
        "claim_id": claim_id,
        "hypothesis_id": hypothesis_id,
        "target_id": target_id,
        "page": page,
        "start_char": start_char,
        "end_char": end_char,
        "relation": relation,
        "verifier_status": verifier_status,
        "exact_locator": exact_locator,
        "card_type": card_type,
        "origin": origin,
        "scope": scope,
        "document_id": document_id,
        "reconstruction_task_ids": task_refs,
        "citation_chain": resolved_chain,
        "card": card,
        "span_hash": span_hash,
        "span_id": span_id,
    }


def _validate_task(raw: Any, index: int, claim_ids: set[str], hypo_ids: set[str]) -> dict[str, Any]:
    task = _require_dict(raw, f"reconstruction_tasks[{index}]")
    _reject_unknown_fields(task, TASK_KEYS, f"reconstruction_tasks[{index}]")
    task_id = _require_non_empty_string(task.get("task_id"), f"reconstruction_tasks[{index}].task_id")
    claim_id = _require_non_empty_string(task.get("claim_id"), f"reconstruction_tasks[{index}].claim_id")
    if claim_id not in claim_ids:
        raise ContractError(f"reconstruction_tasks[{index}].claim_id references unknown claim")
    hypothesis_id = _require_non_empty_string(task.get("hypothesis_id"), f"reconstruction_tasks[{index}].hypothesis_id")
    if hypothesis_id == "":
        raise ContractError(f"reconstruction_tasks[{index}].hypothesis_id must be non-empty")
    command = _require_non_empty_string(task.get("command"), f"reconstruction_tasks[{index}].command")
    executed = _require_bool(task.get("executed"), f"reconstruction_tasks[{index}].executed")
    result = _require_enum(task.get("result"), f"reconstruction_tasks[{index}].result", RESULT_VALUES)
    result_match = _require_bool(task.get("result_match"), f"reconstruction_tasks[{index}].result_match")
    result_notes = _require_non_empty_string(
        task.get("result_notes"), f"reconstruction_tasks[{index}].result_notes"
    )

    if executed and result == "not_run":
        raise ContractError(f"reconstruction_tasks[{index}].result cannot be not_run when executed=True")
    if not executed and result != "not_run":
        raise ContractError(
            f"reconstruction_tasks[{index}].result must be not_run when executed=False"
        )
    if result == "passed" and not result_match:
        raise ContractError(
            f"reconstruction_tasks[{index}].result_match must be true when result=passed"
        )
    if result_match and (not executed or result != "passed"):
        raise ContractError(
            f"reconstruction_tasks[{index}].result_match implies executed=True and result=passed"
        )

    return {
        "task_id": task_id,
        "claim_id": claim_id,
        "hypothesis_id": hypothesis_id,
        "command": command,
        "executed": executed,
        "result": result,
        "result_match": result_match,
        "result_notes": result_notes,
    }


def _validate_top_level_dossier(payload: dict[str, Any]) -> None:
    _reject_unknown_fields(
        payload,
        DOSSIER_TOP_LEVEL_KEYS,
        "dossier",
    )
    if _require_enum(payload.get("schema"), "dossier.schema", {SCHEMA}) != SCHEMA:
        raise ContractError("dossier.schema must be PaperReadingDossier/v1")
    if _require_non_empty_string(
        payload.get("schema_version"), "dossier.schema_version"
    ) != SCHEMA_VERSION:
        raise ContractError("dossier.schema_version must be v1")
    if _require_non_empty_string(payload.get("producer"), "dossier.producer") != PRODUCER:
        raise ContractError("dossier.producer must be learn-from-papers")
    if _require_non_empty_string(
        payload.get("protocol_version"), "dossier.protocol_version"
    ) != PROTOCOL_VERSION:
        raise ContractError("dossier.protocol_version must be 1.0")
    _require_timestamp(payload.get("generated_at"), "dossier.generated_at")


def _validate_id_pairs(
    claims: list[dict[str, Any]],
    evidence: list[dict[str, Any]],
) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    claim_ids = {claim["claim_id"] for claim in claims}
    evidence_ids = {ev["evidence_id"] for ev in evidence}
    if len(claim_ids) != len(claims):
        raise ContractError("duplicate claim_id found")
    if len(evidence_ids) != len(evidence):
        raise ContractError("duplicate evidence_id found")

    claim_map = {claim["claim_id"]: claim for claim in claims}
    evidence_map = {ev["evidence_id"]: ev for ev in evidence}
    return claim_map, evidence_map


def _validate_cross_refs(
    claims: list[dict[str, Any]],
    evidence: list[dict[str, Any]],
    tasks: list[dict[str, Any]],
) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    claim_map, evidence_map = _validate_id_pairs(claims, evidence)
    task_map = {task["task_id"]: task for task in tasks}
    if len(task_map) != len(tasks):
        raise ContractError("duplicate task_id found")

    for claim in claims:
        for evidence_id in claim["evidence_ids"]:
            if evidence_id not in evidence_map:
                raise ContractError(f"claim {claim['claim_id']} references unknown evidence_id {evidence_id}")
            evidence_obj = evidence_map[evidence_id]
            if evidence_obj["claim_id"] != claim["claim_id"]:
                raise ContractError(
                    f"claim {claim['claim_id']} evidence {evidence_id} does not match claim_id binding"
                )
            if evidence_obj["hypothesis_id"] != claim["hypothesis_id"]:
                raise ContractError(
                    f"claim {claim['claim_id']} evidence {evidence_id} does not match hypothesis_id"
                )
            if evidence_obj["target_id"] != claim["target_id"]:
                raise ContractError(
                    f"claim {claim['claim_id']} evidence {evidence_id} does not match target_id"
                )
            if evidence_obj["relation"] != claim["relation"]:
                raise ContractError(
                    f"claim {claim['claim_id']} relation differs from evidence {evidence_id}"
                )
            if evidence_obj["scope"] != claim["scope"]:
                raise ContractError(
                    f"claim {claim['claim_id']} evidence {evidence_id} scope does not match claim scope"
                )

        for task_id in claim["reconstruction_task_ids"]:
            if task_id not in task_map:
                raise ContractError(
                    f"claim {claim['claim_id']} references unknown reconstruction_task_id {task_id}"
                )
            if task_map[task_id]["claim_id"] != claim["claim_id"]:
                raise ContractError(
                    f"reconstruction task {task_id} claim_id mismatch for claim {claim['claim_id']}"
                )
            if task_map[task_id]["hypothesis_id"] != claim["hypothesis_id"]:
                raise ContractError(
                    f"reconstruction task {task_id} hypothesis_id mismatch for claim {claim['claim_id']}"
                )

    for evidence_obj in evidence:
        for task_id in evidence_obj["reconstruction_task_ids"]:
            if task_id not in task_map:
                raise ContractError(
                    f"evidence {evidence_obj['evidence_id']} references unknown reconstruction_task_id {task_id}"
                )

    return claim_map, evidence_map, task_map


def _enforce_span_contract(
    evidence: dict[str, Any], bundle: str, source_path: str | None
) -> tuple[str, str]:
    if source_path is None:
        raise ContractError("bundle validation requires source path")
    span = locate_span(
        bundle=bundle,
        page=evidence["page"],
        start_char=evidence["start_char"],
        end_char=evidence["end_char"],
    )
    expected_hash = span["span_hash"]
    expected_locator = span["exact_locator"]
    expected_id = span["span_id"]
    provided_hash = evidence.get("span_hash")
    provided_id = evidence.get("span_id")
    if provided_hash is not None and provided_hash != expected_hash:
        raise ContractError(
            f"evidence {evidence['evidence_id']} span_hash does not match source-rooted span"
        )
    if provided_id is not None and provided_id != expected_id:
        raise ContractError(
            f"evidence {evidence['evidence_id']} span_id does not match source-rooted span"
        )
    evidence["exact_locator"] = expected_locator
    evidence["span_hash"] = expected_hash
    evidence["span_id"] = expected_id
    return expected_hash, expected_id


def _validate_render_requirements(
    evidence: dict[str, Any], verified_bundle: dict[str, Any] | None
) -> None:
    if evidence["card_type"] not in {"figure", "table", "equation"}:
        return
    card = evidence["card"]
    if card is None:
        raise ContractError(
            f"evidence {evidence['evidence_id']} must include typed card for card_type {evidence['card_type']}"
        )
    needs_rendered_page = card.get("render_required") or (
        evidence["card_type"] == "table" and card.get("is_central_visual")
    )
    if not needs_rendered_page:
        return
    rendered_pages = verified_bundle.get("rendered_pages") if verified_bundle is not None else None
    if not rendered_pages:
        raise ContractError(
            f"evidence {evidence['evidence_id']} requires rendered artifact for "
            f"page {evidence['page']}"
        )
    matches = any(item["page_index"] == evidence["page"] for item in rendered_pages)
    if not matches:
        raise ContractError(
            f"evidence {evidence['evidence_id']} requires rendered page {evidence['page']} "
            f"but source bundle has no rendered artifact"
        )


def _compute_claim_support_eligibility(
    claim: dict[str, Any],
    evidence_map: dict[str, dict[str, Any]],
    tasks_map: dict[str, dict[str, Any]],
    access_level: str,
    inspection_depth: str,
) -> bool:
    if claim["relation"] == "not_tested":
        return False
    if claim["verifier_status"] != "passed":
        return False
    if claim["verification"]["mode"] == "same_context_diagnostic":
        return False
    if access_level != "full_text":
        return False
    if inspection_depth not in {"evidence", "reconstruction"}:
        return False
    if not claim["evidence_ids"]:
        return False
    for evidence_id in claim["evidence_ids"]:
        ev = evidence_map[evidence_id]
        if ev["relation"] != claim["relation"]:
            return False
        if ev["verifier_status"] != "passed":
            return False
    if not claim["reconstruction_task_ids"]:
        return True
    for task_id in claim["reconstruction_task_ids"]:
        task = tasks_map[task_id]
        if not task["executed"]:
            return False
        if task["result"] != "passed":
            return False
        if not task["result_match"]:
            return False
        if task["hypothesis_id"] != claim["hypothesis_id"]:
            return False
    return True


def _required_subquestion_coverage(plan: dict[str, Any], claims: list[dict[str, Any]]) -> dict[str, int]:
    required = {item["subquestion_id"] for item in plan["subquestions"] if item["required"]}
    abstention = {item["subquestion_id"] for item in plan["abstention_conditions"]}
    answered = set[str]()
    for claim in claims:
        if claim["subquestion_id"]:
            answered.add(claim["subquestion_id"])
    overlap = answered.intersection(abstention).intersection(required)
    if overlap:
        raise ContractError(
            "required subquestions cannot be both answered and abstained: "
            + ",".join(sorted(overlap))
        )
    covered = answered.intersection(required).union(abstention.intersection(required))
    return {
        "required": len(required),
        "answered": len(answered.intersection(required)),
        "abstained": len(abstention.intersection(required)),
        "unanswered": len(required.difference(covered)),
    }


def _build_completion_matrix(
    plan: dict[str, Any],
    components: list[dict[str, Any]],
    claims: list[dict[str, Any]],
    evidence: list[dict[str, Any]],
    claim_support_eligible: dict[str, bool],
) -> dict[str, Any]:
    answered_required = _required_subquestion_coverage(plan, claims)
    eligible = sum(1 for value in claim_support_eligible.values() if value)
    total_claims = len(claims)
    total_units = sum(item["inspected_units"] for item in components)
    total_covered = sum(item["covered_units"] for item in components)
    total_terminal = sum(item["terminal_units"] for item in components)
    verified_evidence = sum(1 for item in evidence if item["verifier_status"] == "passed")
    return {
        "subquestions": {
            "required": answered_required["required"],
            "answered": answered_required["answered"],
            "abstained": answered_required["abstained"],
            "unanswered": answered_required["unanswered"],
        },
        "claims": {
            "total": total_claims,
            "eligible": eligible,
            "non_eligible": total_claims - eligible,
            "decisive": eligible,
            "terminal": total_claims - eligible,
        },
        "evidence": {
            "total": len(evidence),
            "verified": verified_evidence,
        },
        "components": {
            "total_units": total_units,
            "covered_units": total_covered,
            "terminal_units": total_terminal,
        },
    }


def _build_terminal_states(
    claims: list[dict[str, Any]],
    eligibility: dict[str, bool],
    plan: dict[str, Any],
    abstentions: set[str],
) -> list[dict[str, str]]:
    states: list[dict[str, str]] = []
    for claim in claims:
        if eligibility[claim["claim_id"]]:
            continue
        if claim["relation"] == "not_tested":
            state = "unanswered"
            reason = "claim marked not_tested"
        elif claim["subquestion_id"] in abstentions:
            state = "unanswerable"
            reason = "abstention condition recorded"
        elif claim["verifier_status"] == "unresolved":
            state = "terminal"
            reason = "verifier unresolved"
        elif claim["verifier_status"] in {"failed", "not_tested"}:
            state = "non_eligible"
            reason = f"verifier_status={claim['verifier_status']}"
        else:
            state = "non_eligible"
            reason = "claim does not meet decisive eligibility"
        states.append({"claim_id": claim["claim_id"], "state": state, "reason": reason})
    return states


def _build_gates(
    claim_support_eligible: dict[str, bool],
    required_answered: dict[str, int],
    bundle_verified: bool,
) -> dict[str, bool]:
    return {
        "bundle_verified": bundle_verified,
        "required_subquestions_covered": (
            required_answered["required"]
            <= required_answered["answered"] + required_answered["abstained"]
        ),
        "any_claim_eligible": any(claim_support_eligible.values()),
        "claim_span_integrity": True,
    }


def _normalize_unresolved_terminal_states(
    raw: Any,
    expected: list[dict[str, str]],
    claim_ids: set[str],
    label: str,
) -> list[dict[str, str]]:
    items = _require_list(raw, label)
    normalized: list[dict[str, str]] = []
    seen = set[str]()
    for index, item in enumerate(items):
        entry = _require_dict(item, f"{label}[{index}]")
        _reject_unknown_fields(entry, TERMINAL_ENTRY_KEYS, f"{label}[{index}]")
        claim_id = _require_non_empty_string(entry.get("claim_id"), f"{label}[{index}].claim_id")
        if claim_id not in claim_ids:
            raise ContractError(f"{label}[{index}] claim_id is not in claims")
        if claim_id in seen:
            raise ContractError(f"{label}[{index}] duplicate claim_id {claim_id}")
        seen.add(claim_id)
        normalized.append(
            {
                "claim_id": claim_id,
                "state": _require_enum(
                    entry.get("state"),
                    f"{label}[{index}].state",
                    TERMINAL_STATES,
                ),
                "reason": _require_non_empty_string(
                    entry.get("reason"),
                    f"{label}[{index}].reason",
                ),
            }
        )

    if len(normalized) != len(expected):
        raise ContractError("dossier.unresolved_terminal_states does not match recomputed terminal states")
    if normalized != expected:
        raise ContractError("dossier.unresolved_terminal_states does not match recomputed terminal states")
    return normalized


def _validate_reconstruction_contract(
    inspection_depth: str,
    reconstruction_status: str,
    tasks: list[dict[str, Any]],
) -> None:
    has_tasks = bool(tasks)
    all_tasks_passed = all(
        task["executed"] and task["result"] == "passed" and task["result_match"] for task in tasks
    )

    if reconstruction_status == "planned":
        if any(task["executed"] for task in tasks):
            raise ContractError("planned reconstruction_status cannot have executed tasks")

    if reconstruction_status in {"executed", "passed"}:
        if not has_tasks:
            raise ContractError(
                "executed/passed reconstruction_status requires at least one reconstruction task"
            )
        if not all_tasks_passed:
            raise ContractError(
                "executed/passed reconstruction_status requires all tasks executed and passed"
            )

    if reconstruction_status == "not_applicable" and tasks:
        raise ContractError("not_applicable reconstruction_status cannot include reconstruction tasks")

    if inspection_depth == "reconstruction":
        if not has_tasks:
            raise ContractError("inspection_depth=reconstruction requires at least one reconstruction task")
        if not all_tasks_passed:
            raise ContractError(
                "inspection_depth=reconstruction requires all reconstruction tasks executed and passed"
            )

    if inspection_depth in {"map", "evidence"} and reconstruction_status in {"in_progress", "failed", "passed", "executed"}:
        if not has_tasks:
            raise ContractError(
                f"inspection_depth={inspection_depth} cannot have reconstruction_status={reconstruction_status} without tasks"
            )


def _compute_audit_metrics(
    claims: list[dict[str, Any]],
    evidence: list[dict[str, Any]],
    claim_support_eligible: dict[str, bool],
) -> dict[str, Any]:
    high = sum(1 for claim in claims if claim["confidence"] == "high")
    medium = sum(1 for claim in claims if claim["confidence"] == "medium")
    low = sum(1 for claim in claims if claim["confidence"] == "low")
    eligible = sum(1 for value in claim_support_eligible.values() if value)
    return {
        "total_claims": len(claims),
        "total_evidence": len(evidence),
        "eligible_claims": eligible,
        "high_confidence_claims": high,
        "medium_confidence_claims": medium,
        "low_confidence_claims": low,
    }


def _canonical_id(prefix: str, digest: str) -> str:
    return prefix + digest[:16]


def _dossier_digest(payload: dict[str, Any]) -> str:
    return sha256_hex({key: value for key, value in payload.items() if key not in {"dossier_id", "dossier_digest"}})


def _validate_request_binding(raw: dict[str, Any]) -> dict[str, str]:
    review_request_set_id = _require_non_empty_string(
        raw.get("review_request_set_id"),
        "review_request_set_id",
    )
    review_request_set_digest = _require_sha256(
        raw.get("review_request_set_digest"), "review_request_set_digest"
    )
    review_request_id = _require_non_empty_string(
        raw.get("review_request_id"), "review_request_id"
    )
    review_request_digest = _require_sha256(
        raw.get("review_request_digest"), "review_request_digest"
    )
    return {
        "review_request_set_id": review_request_set_id,
        "review_request_set_digest": review_request_set_digest,
        "review_request_id": review_request_id,
        "review_request_digest": review_request_digest,
    }


def _normalize_plan_coverage(
    plan: dict[str, Any], claims: list[dict[str, Any]]
) -> tuple[dict[str, int], bool]:
    subquestions = {item["subquestion_id"] for item in plan["subquestions"] if item["required"]}
    abstentions = {item["subquestion_id"] for item in plan["abstention_conditions"]}
    answered = {claim["subquestion_id"] for claim in claims if claim["subquestion_id"]}
    overlap = answered.intersection(abstentions)
    if overlap:
        raise ContractError(
            "subquestions cannot be both answered and abstained: "
            + ",".join(sorted(overlap))
        )
    for required_sub in subquestions:
        if required_sub not in answered and required_sub not in abstentions:
            raise ContractError(
                f"required subquestion {required_sub} is unanswered and no abstention condition exists"
            )
    covered = answered.intersection(subquestions).union(abstentions.intersection(subquestions))
    return {
        "required": len(subquestions),
        "answered": len(answered.intersection(subquestions)),
        "abstained": len(abstentions.intersection(subquestions)),
    }, len(covered) >= len(subquestions)


def _validate_verified_citation_match(
    item: dict[str, Any], label: str, evidence_map: dict[str, dict[str, Any]]
) -> None:
    if not item["verified"]:
        return
    target = evidence_map[item["evidence_id"]]
    if item["exact_locator"] != target["exact_locator"]:
        raise ContractError(f"{label}.exact_locator must match referenced evidence canonical locator")
    if item["scope"] != target["scope"]:
        raise ContractError(f"{label}.scope must match referenced evidence scope")


def _validate_evidence_bindings(raw: Any, label: str) -> list[dict[str, Any]]:
    bindings = _require_list(raw, label)
    seen: set[str] = set()
    normalized: list[dict[str, Any]] = []
    for index, item in enumerate(bindings):
        binding = _require_dict(item, f"{label}[{index}]")
        _reject_unknown_fields(binding, EVIDENCE_BINDING_KEYS, f"{label}[{index}]")
        evidence_id = _require_non_empty_string(
            binding.get("evidence_id"), f"{label}[{index}].evidence_id"
        )
        if evidence_id in seen:
            raise ContractError(f"{label}[{index}] duplicate evidence_id {evidence_id}")
        seen.add(evidence_id)
        page = _require_int(binding.get("page"), f"{label}[{index}].page", minimum=1)
        start_char = _require_int(binding.get("start_char"), f"{label}[{index}].start_char")
        end_char = _require_int(binding.get("end_char"), f"{label}[{index}].end_char")
        if end_char < start_char:
            raise ContractError(
                f"{label}[{index}].end_char must be >= {label}[{index}].start_char"
            )
        span_hash = _require_sha256(binding.get("span_hash"), f"{label}[{index}].span_hash")
        span_id = _require_non_empty_string(binding.get("span_id"), f"{label}[{index}].span_id")
        if not span_id.startswith("source-passages-span-"):
            raise ContractError(f"{label}[{index}].span_id must be source-passages-span-<16hex>")
        exact_locator = _validate_exact_locator(
            binding.get("exact_locator"), f"{label}[{index}].exact_locator"
        )
        normalized.append(
            {
                "evidence_id": evidence_id,
                "exact_locator": exact_locator,
                "page": page,
                "start_char": start_char,
                "end_char": end_char,
                "span_id": span_id,
                "span_hash": span_hash,
            }
        )
    return normalized


def _validate_dossier(
    raw: dict[str, Any],
    *,
    bundle: str | None = None,
    source: str | None = None,
    canonicalize: bool = False,
) -> dict[str, Any]:
    payload = deepcopy(raw)
    if not isinstance(payload, dict):
        raise ContractError("dossier must be an object")

    _validate_top_level_dossier(payload)
    plan = _validate_plan(payload.get("request_question_plan"))
    network_ref = _validate_network_ref(payload.get("network_ref"), "network_ref")
    binding = _validate_request_binding(payload)
    review_source = _validate_review_source(payload.get("review_source"), "review_source")

    access_level = _require_enum(payload.get("access_level"), "access_level", DOSSIER_ACCESS_LEVELS)
    inspection_depth = _require_enum(payload.get("inspection_depth"), "inspection_depth", INSPECTION_DEPTHS)
    reconstruction_status = _require_enum(
        payload.get("reconstruction_status"), "reconstruction_status", RECONSTRUCTION_STATUSES
    )
    embedded_documents = _validate_embedded_documents(payload.get("embedded_documents"))
    component_manifest = _validate_component_manifest(payload.get("component_manifest"))

    subquestion_ids = {item["subquestion_id"] for item in plan["subquestions"]}
    claims_raw = _require_list(payload.get("claims"), "claims")
    tasks_raw = _require_list(payload.get("reconstruction_tasks"), "reconstruction_tasks")
    evidence_raw = _require_list(payload.get("evidence_records"), "evidence_records")
    docs = {doc["document_id"] for doc in embedded_documents}

    claims = [_validate_claim(claim, index, docs, subquestion_ids) for index, claim in enumerate(claims_raw)]
    task_ids = {task["task_id"] for task in tasks_raw}
    tasks = [
        _validate_task(
            task,
            index,
            {claim["claim_id"] for claim in claims},
            {claim["hypothesis_id"] for claim in claims},
        )
        for index, task in enumerate(tasks_raw)
    ]

    claim_ids = {claim["claim_id"] for claim in claims}
    evidence = [
        _validate_evidence(evidence_item, index, claim_ids, docs, task_ids)
        for index, evidence_item in enumerate(evidence_raw)
    ]

    claim_map, evidence_map, task_map = _validate_cross_refs(
        claims,
        evidence,
        tasks,
    )

    if bundle is None and source is None:
        raise ContractError("bundle and source are required for deterministic dossier validation")

    verified_bundle = None
    try:
        verified_bundle = verify_bundle(bundle=bundle, source=source)
    except SourceBundleContractError as exc:
        raise ContractError(str(exc)) from exc

    bundle_binding_expected = {
        "bundle_id": verified_bundle["bundle_id"],
        "bundle_digest": verified_bundle["bundle_digest"],
        "source_ref": verified_bundle["source"]["name"],
        "source_artifact_sha256": verified_bundle["source"]["source_sha256"],
    }
    source_bundle = _validate_source_bundle(payload.get("source_bundle"), bundle_binding_expected)

    for evidence_item in evidence:
        _enforce_span_contract(evidence_item, bundle=bundle, source_path=source)
        _validate_render_requirements(evidence_item, verified_bundle)

    # validate plan coverage and required subquestion gates.
    _, required_answered_ok = _normalize_plan_coverage(plan, claims)

    # validate citation chains and evidence/claim linkage.
    all_citation_ids = set[str]()
    for claim_index, claim in enumerate(claims):
        for citation_index, item in enumerate(claim["citation_chain"]):
            if item["citation_id"] in all_citation_ids:
                raise ContractError(
                    f"duplicate citation_id {item['citation_id']} in claim {claim['claim_id']}"
                )
            all_citation_ids.add(item["citation_id"])
            if item["evidence_id"] not in evidence_map:
                raise ContractError(
                    f"claim {claim['claim_id']} citation references missing evidence {item['evidence_id']}"
                )
            target_evidence = evidence_map[item["evidence_id"]]
            if item["verified"] and target_evidence["verifier_status"] != "passed":
                raise ContractError(
                    f"claim {claim['claim_id']} citation {item['citation_id']} marked verified but evidence failed"
                )
            _validate_verified_citation_match(
                item,
                f"claims[{claim_index}].citation_chain[{citation_index}]",
                evidence_map,
            )
            _validate_exact_locator(item["exact_locator"], "citation exact_locator")

    for evidence_index, evidence_item in enumerate(evidence):
        for citation_index, item in enumerate(evidence_item["citation_chain"]):
            if item["citation_id"] in all_citation_ids:
                raise ContractError(
                    f"duplicate citation_id {item['citation_id']} across claims/evidence"
                )
            if item["evidence_id"] not in evidence_map:
                raise ContractError(
                    f"evidence {evidence_item['evidence_id']} citation references missing evidence {item['evidence_id']}"
                )
            if item["verified"] and evidence_map[item["evidence_id"]]["verifier_status"] != "passed":
                raise ContractError(
                    f"evidence {evidence_item['evidence_id']} citation {item['citation_id']} marked verified but evidence failed"
                )
            _validate_verified_citation_match(
                item,
                f"evidence_records[{evidence_index}].citation_chain[{citation_index}]",
                evidence_map,
            )
            _validate_exact_locator(item["exact_locator"], "citation exact_locator")

    claim_support_eligible: dict[str, bool] = {}
    for claim in claims:
        support = _compute_claim_support_eligibility(
            claim,
            evidence_map,
            task_map,
            access_level=access_level,
            inspection_depth=inspection_depth,
        )
        if claim["confidence"] == "high" and not support:
            # explicit overclaim guardrail
            raise ContractError(
                f"claim {claim['claim_id']} claims high confidence but is not fully supported"
            )
        claim_support_eligible[claim["claim_id"]] = support

    _validate_reconstruction_contract(inspection_depth, reconstruction_status, tasks)

    required_coverage = _required_subquestion_coverage(plan, claims)
    completion_matrix = _build_completion_matrix(
        plan,
        component_manifest,
        claims,
        evidence,
        claim_support_eligible,
    )
    gates = _build_gates(claim_support_eligible, required_coverage, True)
    # explicit reconstruction gate
    if access_level == "metadata_only" and claims:
        raise ContractError("metadata_only access cannot support claim assertions with source-rooted evidence")
    if not gates["bundle_verified"]:
        raise ContractError("bundle must be verified for dossier generation")
    if not gates["required_subquestions_covered"]:
        raise ContractError("required subquestions must be covered (or abstained)")
    if not gates["claim_span_integrity"]:
        raise ContractError("span integrity check failed")

    unresolved_terminal_states = _build_terminal_states(
        claims,
        claim_support_eligible,
        plan,
        {item["subquestion_id"] for item in plan["abstention_conditions"]},
    )
    audit_metrics = _compute_audit_metrics(
        claims,
        evidence,
        claim_support_eligible,
    )

    normalized = {
        "schema": SCHEMA,
        "schema_version": SCHEMA_VERSION,
        "producer": PRODUCER,
        "protocol_version": PROTOCOL_VERSION,
        "generated_at": _require_timestamp(
            payload.get("generated_at") if payload.get("generated_at") else _now_utc(),
            "generated_at",
        ),
        "request_question_plan": plan,
        "source_bundle": source_bundle,
        "network_ref": network_ref,
        "review_request_set_id": binding["review_request_set_id"],
        "review_request_set_digest": binding["review_request_set_digest"],
        "review_request_id": binding["review_request_id"],
        "review_request_digest": binding["review_request_digest"],
        "review_source": review_source,
        "access_level": access_level,
        "inspection_depth": inspection_depth,
        "reconstruction_status": reconstruction_status,
        "embedded_documents": embedded_documents,
        "component_manifest": component_manifest,
        "claims": claims,
        "evidence_records": evidence,
        "reconstruction_tasks": tasks,
        "correction_log": _validate_correction_log(payload.get("correction_log", [])),
    }

    if not normalized["claims"]:
        raise ContractError("claims must not be empty")
    if canonicalize:
        normalized["claim_support_eligible"] = claim_support_eligible
        normalized["gates"] = gates
        normalized["completion_matrix"] = completion_matrix
        normalized["audit_metrics"] = audit_metrics
        normalized["unresolved_terminal_states"] = unresolved_terminal_states
        normalized["dossier_id"] = _canonical_id(DOSSIER_ID_PREFIX, _dossier_digest(normalized))
        normalized["dossier_digest"] = _dossier_digest(normalized)
    else:
        if payload.get("claim_support_eligible") != claim_support_eligible:
            raise ContractError("claim_support_eligible does not match recomputed value")
        if payload.get("gates") != gates:
            raise ContractError("gates does not match recomputed value")
        if payload.get("completion_matrix") != completion_matrix:
            raise ContractError("completion_matrix does not match recomputed value")
        if payload.get("audit_metrics") != audit_metrics:
            raise ContractError("audit_metrics does not match recomputed value")
        normalized["claim_support_eligible"] = claim_support_eligible
        normalized["gates"] = gates
        normalized["completion_matrix"] = completion_matrix
        normalized["audit_metrics"] = audit_metrics
        normalized["unresolved_terminal_states"] = _normalize_unresolved_terminal_states(
            payload.get("unresolved_terminal_states"),
            expected=unresolved_terminal_states,
            claim_ids={claim["claim_id"] for claim in claims},
            label="dossier.unresolved_terminal_states",
        )
        normalized["dossier_id"] = _require_non_empty_string(
            payload.get("dossier_id"),
            "dossier.dossier_id",
        )
        normalized["dossier_digest"] = _require_sha256(
            payload.get("dossier_digest"),
            "dossier.dossier_digest",
        )

    normalized = _verify_dossier_ids_and_digests(normalized)
    return normalized


def _verify_dossier_ids_and_digests(dossier: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(dossier["dossier_id"], str) or not dossier["dossier_id"].startswith(DOSSIER_ID_PREFIX):
        raise ContractError("dossier_id has invalid prefix")
    expected = _dossier_digest(dossier)
    if dossier["dossier_digest"] != expected:
        raise ContractError("dossier_digest does not match dossier payload")
    expected_id = _canonical_id(DOSSIER_ID_PREFIX, expected)
    if dossier["dossier_id"] != expected_id:
        raise ContractError("dossier_id does not match dossier_digest")
    return dossier


def create_dossier(
    draft: dict[str, Any],
    *,
    bundle: str,
    source: str,
    generated_at: str | None = None,
) -> dict[str, Any]:
    normalized = deepcopy(draft)
    if generated_at is not None:
        _require_timestamp(generated_at, "generated_at")
        normalized["generated_at"] = generated_at
    return _validate_dossier(normalized, bundle=bundle, source=source, canonicalize=True)


def validate_dossier(
    dossier: dict[str, Any], *, bundle: str | None = None, source: str | None = None
) -> dict[str, Any]:
    return _validate_dossier(dossier, bundle=bundle, source=source, canonicalize=False)


def _v2_dossier_digest(document: dict[str, Any]) -> str:
    return sha256_hex(
        {key: value for key, value in document.items() if key not in {"report_set_id", "report_set_digest"}}
    )


def _assign_report_set_identity(report_set: dict[str, Any]) -> None:
    payload = {
        key: value
        for key, value in report_set.items()
        if key not in {"report_set_id", "report_set_digest"}
    }
    report_set["report_set_digest"] = _v2_dossier_digest(payload)
    report_set["report_set_id"] = _canonical_id(V2_SET_PREFIX, report_set["report_set_digest"])


def _v2_report_digest(document: dict[str, Any]) -> str:
    return sha256_hex(
        {key: value for key, value in document.items() if key not in {"report_id", "report_digest"}}
    )


def _assign_report_identity(report: dict[str, Any]) -> None:
    payload = {key: value for key, value in report.items() if key not in {"report_id", "report_digest"}}
    report["report_digest"] = _v2_report_digest(payload)
    report["report_id"] = _canonical_id(V2_REPORT_PREFIX, report["report_digest"])


def canonical_report_subject_digest(report: dict[str, Any]) -> str:
    """Canonical digest for report evidence-binding verification."""
    payload = deepcopy(report)
    for key in {
        "report_id",
        "report_digest",
        "projection_status",
        "claim_support_eligible",
    }:
        payload.pop(key, None)
    if "verification" in payload and isinstance(payload["verification"], dict):
        payload["verification"] = _strip_subject_artifact_fields(payload["verification"])
    return sha256_hex(payload)


def _report_set_completion_matrix(
    raw: Any,
    reports: list[dict[str, Any]],
    *,
    pending: bool = False,
) -> dict[str, Any]:
    matrix = deepcopy(_require_dict(raw, "report_set.completion_matrix"))
    claims = _require_dict(matrix.get("claims"), "report_set.completion_matrix.claims")
    claim_keys = {"total", "eligible", "non_eligible", "decisive", "terminal"}
    _reject_unknown_fields(claims, claim_keys, "report_set.completion_matrix.claims")
    if set(claims) != claim_keys:
        missing = claim_keys - set(claims)
        raise ContractError(
            "report_set.completion_matrix.claims missing keys: "
            + ", ".join(sorted(missing))
        )
    total = len(reports)
    if pending:
        eligible = 0
        decisive = 0
    else:
        eligible = sum(report.get("claim_support_eligible") is True for report in reports)
        decisive = sum(report.get("projection_status") == "decisive" for report in reports)
    matrix["claims"] = {
        "total": total,
        "eligible": eligible,
        "non_eligible": total - eligible,
        "decisive": decisive,
        "terminal": total - decisive,
    }
    return matrix


def _report_set_attestation_context(report_set: dict[str, Any]) -> dict[str, Any]:
    reports = _require_list(report_set.get("reports"), "report_set.reports")
    context = {
        key: deepcopy(report_set.get(key))
        for key in REPORT_SET_ATTESTATION_CONTEXT_KEYS
    }
    context["completion_matrix"] = _report_set_completion_matrix(
        context["completion_matrix"],
        reports,
        pending=True,
    )
    return context


def _expected_report_identities(report_set: dict[str, Any]) -> list[dict[str, str]]:
    reports = _require_list(report_set.get("reports"), "report_set.reports")
    identities = [
        {
            "claim_id": _require_non_empty_string(report.get("claim_id"), "report.claim_id"),
            "hypothesis_id": _require_non_empty_string(
                report.get("hypothesis_id"), "report.hypothesis_id"
            ),
            "target_id": _require_non_empty_string(report.get("target_id"), "report.target_id"),
            "subject_digest": canonical_report_subject_digest(report),
        }
        for report in reports
    ]
    return sorted(
        identities,
        key=lambda item: (
            item["claim_id"],
            item["hypothesis_id"],
            item["target_id"],
            item["subject_digest"],
        ),
    )


def _validate_report_set_context(raw: Any, label: str) -> dict[str, Any]:
    context = deepcopy(_require_dict(raw, label))
    _reject_unknown_fields(context, REPORT_SET_ATTESTATION_CONTEXT_KEYS, label)
    if set(context) != REPORT_SET_ATTESTATION_CONTEXT_KEYS:
        missing = REPORT_SET_ATTESTATION_CONTEXT_KEYS - set(context)
        raise ContractError(f"{label} missing keys: {', '.join(sorted(missing))}")
    _validate_network_ref(context.get("network_ref"), f"{label}.network_ref")
    _report_set_completion_matrix(context.get("completion_matrix"), [], pending=True)
    return context


def _validate_expected_report_identities(raw: Any, label: str) -> list[dict[str, str]]:
    values = _require_list(raw, label)
    if not values:
        raise ContractError(f"{label} must not be empty")
    validated: list[dict[str, str]] = []
    seen_claims: set[str] = set()
    seen_subjects: set[str] = set()
    for index, item in enumerate(values):
        identity = _require_dict(item, f"{label}[{index}]")
        _reject_unknown_fields(
            identity,
            EXPECTED_REPORT_IDENTITY_KEYS,
            f"{label}[{index}]",
        )
        if set(identity) != EXPECTED_REPORT_IDENTITY_KEYS:
            raise ContractError(f"{label}[{index}] is incomplete")
        normalized = {
            "claim_id": _require_non_empty_string(
                identity.get("claim_id"), f"{label}[{index}].claim_id"
            ),
            "hypothesis_id": _require_non_empty_string(
                identity.get("hypothesis_id"), f"{label}[{index}].hypothesis_id"
            ),
            "target_id": _require_non_empty_string(
                identity.get("target_id"), f"{label}[{index}].target_id"
            ),
            "subject_digest": _require_sha256(
                identity.get("subject_digest"), f"{label}[{index}].subject_digest"
            ),
        }
        if normalized["claim_id"] in seen_claims:
            raise ContractError(f"{label} contains duplicate claim_id")
        if normalized["subject_digest"] in seen_subjects:
            raise ContractError(f"{label} contains duplicate subject_digest")
        seen_claims.add(normalized["claim_id"])
        seen_subjects.add(normalized["subject_digest"])
        validated.append(normalized)
    return sorted(
        validated,
        key=lambda item: (
            item["claim_id"],
            item["hypothesis_id"],
            item["target_id"],
            item["subject_digest"],
        ),
    )


def _safe_parent(path: Path) -> None:
    current = path
    while current != current.parent:
        if current.is_symlink():
            raise ContractError(f"refusing symlink path element: {current}")
        current = current.parent


def _write_atomic(path: Path, payload: bytes) -> None:
    _safe_parent(path)
    _safe_parent(path.parent)
    path.parent.mkdir(parents=True, exist_ok=True)

    fd = -1
    temp_path: Path | None = None
    try:
        fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
        temp_path = Path(temp_name)
        _safe_parent(temp_path)
        _safe_parent(path)
        with os.fdopen(fd, "wb") as temp_file:
            temp_file.write(payload)
            temp_file.flush()
            os.fsync(temp_file.fileno())
        fd = -1

        _safe_parent(path)
        if path.exists() and path.is_symlink():
            raise ContractError(f"refusing symlink output path during publish: {path}")
        if path.parent.is_symlink():
            raise ContractError(f"refusing symlink output directory during publish: {path.parent}")

        temp_path.replace(path)
        _safe_parent(path.parent)
    finally:
        if fd != -1:
            os.close(fd)
        if temp_path is not None and temp_path.exists():
            temp_path.unlink(missing_ok=True)


def _report_set_projection_binding(dossier: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema": V2_SCHEMA,
        "schema_version": V2_SCHEMA_VERSION,
        "producer": PRODUCER,
        "protocol_version": PROTOCOL_VERSION,
        "generated_at": dossier["generated_at"],
        "network_ref": dossier["network_ref"],
        "review_request_set_id": dossier["review_request_set_id"],
        "review_request_set_digest": dossier["review_request_set_digest"],
        "source_bundle_id": dossier["source_bundle"]["bundle_id"],
        "source_bundle_digest": dossier["source_bundle"]["bundle_digest"],
        "source_ref": dossier["source_bundle"]["source_ref"],
        "source_artifact_sha256": dossier["source_bundle"]["source_artifact_sha256"],
        "review_source": dossier["review_source"],
        "dossier_id": dossier["dossier_id"],
        "dossier_digest": dossier["dossier_digest"],
        "access_level": dossier["access_level"],
        "inspection_depth": dossier["inspection_depth"],
        "reconstruction_status": dossier["reconstruction_status"],
        "completion_matrix": dossier["completion_matrix"],
    }


def _project_claims(dossier: dict[str, Any], *, projection_finalized: bool = False) -> list[dict[str, Any]]:
    evidence_by_id = {evidence["evidence_id"]: evidence for evidence in dossier["evidence_records"]}

    projections: list[dict[str, Any]] = []
    for claim in dossier["claims"]:
        evidence_ids_sorted = sorted(claim["evidence_ids"])
        eligible = dossier["claim_support_eligible"].get(claim["claim_id"], False)
        evidence_for_claim: list[dict[str, Any]] = []
        for evidence_id in evidence_ids_sorted:
            if evidence_id not in evidence_by_id:
                raise ContractError(
                    f"claim {claim['claim_id']} references evidence_id {evidence_id} missing in dossier evidence_records"
                )
            evidence_for_claim.append(evidence_by_id[evidence_id])
        matching_relation = [
            item["exact_locator"]
            for item in evidence_for_claim
            if item["relation"] == claim["relation"]
        ]
        locator = matching_relation[0] if matching_relation else None
        status = _compute_report_projection_status(
            eligible,
            claim["verification"],
            finalized=projection_finalized,
        )
        reason = None
        if not eligible:
            for item in dossier["unresolved_terminal_states"]:
                if item["claim_id"] == claim["claim_id"]:
                    reason = item["reason"]
                    break
        if status == "decisive" and not locator:
            raise ContractError(f"decisive claim {claim['claim_id']} has no evidence locator")

        evidence_bindings: list[dict[str, Any]] = []
        for evidence in evidence_for_claim:
            evidence_bindings.append(
                {
                    "evidence_id": evidence["evidence_id"],
                    "exact_locator": evidence["exact_locator"],
                    "page": evidence["page"],
                    "start_char": evidence["start_char"],
                    "end_char": evidence["end_char"],
                    "span_hash": evidence["span_hash"],
                    "span_id": evidence["span_id"],
                }
            )

        report = {
            "schema": V2_REPORT_SCHEMA,
            "schema_version": V2_SCHEMA_VERSION,
            "producer": PRODUCER,
            "protocol_version": PROTOCOL_VERSION,
            "report_id": "",
            "report_digest": "",
            "review_request_id": dossier["review_request_id"],
            "review_request_digest": dossier["review_request_digest"],
            "review_request_set_id": dossier["review_request_set_id"],
            "review_request_set_digest": dossier["review_request_set_digest"],
            "hypothesis_id": claim["hypothesis_id"],
            "claim_id": claim["claim_id"],
            "target_id": claim["target_id"],
            "claim_statement": claim["statement"],
            "scope": claim["scope"],
            "evidence_bindings": evidence_bindings,
            "evidence_relation": claim["relation"],
            "relation": claim["relation"],
            "actual_evidence_locator": locator,
            # Dossier eligibility is a structural support candidate. A report is
            # not eligible until finalize-attestations validates an external
            # attestation over the frozen report subject.
            "claim_support_eligible": False,
            "projection_status": status,
            "coverage_reason": reason,
            "verifier_status": claim["verifier_status"],
            "access_level": dossier["access_level"],
            "inspection_depth": dossier["inspection_depth"],
            "reconstruction_status": dossier["reconstruction_status"],
            "source_bundle_id": dossier["source_bundle"]["bundle_id"],
            "source_bundle_digest": dossier["source_bundle"]["bundle_digest"],
            "source_ref": dossier["source_bundle"]["source_ref"],
            "source_artifact_sha256": dossier["source_bundle"]["source_artifact_sha256"],
            "review_source": dossier["review_source"],
            "dossier_id": dossier["dossier_id"],
            "dossier_digest": dossier["dossier_digest"],
            "evidence_ids": evidence_ids_sorted,
            "verification": claim["verification"],
        }
        report["report_digest"] = _v2_report_digest(report)
        report["report_id"] = _canonical_id(V2_REPORT_PREFIX, report["report_digest"])
        projections.append(report)
    return projections


def _safe_artifact_path(
    root: str | Path, artifact_ref: str, *, label: str
) -> Path:
    root_path = Path(root)
    if root_path.is_symlink():
        raise ContractError(f"verification_root must be a non-symlink directory: {root_path}")
    if root_path.exists() and not root_path.is_dir():
        raise ContractError(f"verification_root must be a directory: {root_path}")
    relative = Path(_require_non_empty_string(artifact_ref, label))
    if relative.is_absolute() or ".." in relative.parts:
        raise ContractError(f"{label} must be a safe relative path")
    current = root_path
    for part in relative.parts:
        current = current / part
        if current.is_symlink():
            raise ContractError("verification path must not traverse symlinks")
    resolved_root = root_path.resolve()
    resolved = current.resolve()
    if resolved_root not in resolved.parents and resolved != resolved_root:
        raise ContractError("verification artifact escapes verification_root")
    return resolved


def _canonical_evidence_bindings(report: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {
            "evidence_id": binding["evidence_id"],
            "exact_locator": binding["exact_locator"],
            "page": binding["page"],
            "start_char": binding["start_char"],
            "end_char": binding["end_char"],
            "span_id": binding["span_id"],
            "span_hash": binding["span_hash"],
        }
        for binding in report.get("evidence_bindings", [])
    ]


def _write_verification_artifact(
    verification_root: str | Path,
    directory: str,
    payload: dict[str, Any],
    *,
    label: str,
) -> tuple[str, str]:
    payload_bytes = canonical_json_bytes(payload) + b"\n"
    artifact_sha256 = hashlib.sha256(payload_bytes).hexdigest()
    artifact_ref = str(Path(directory) / f"{artifact_sha256}.json")
    artifact_path = _safe_artifact_path(
        verification_root, artifact_ref, label=f"{label}.artifact_ref"
    )
    if artifact_path.exists():
        if not artifact_path.is_file() or artifact_path.read_bytes() != payload_bytes:
            raise ContractError(f"{label} content-address collision: {artifact_ref}")
    else:
        _write_atomic(artifact_path, payload_bytes)
    return artifact_ref, artifact_sha256


def _read_verification_artifact(
    verification_root: str | Path,
    artifact_ref: str,
    *,
    label: str,
) -> tuple[dict[str, Any], str]:
    artifact_path = _safe_artifact_path(
        verification_root, artifact_ref, label=f"{label}.artifact_ref"
    )
    try:
        before = os.stat(artifact_path, follow_symlinks=False)
    except FileNotFoundError:
        raise ContractError(f"{label} artifact not found: {artifact_ref}")
    if not stat.S_ISREG(before.st_mode):
        raise ContractError(f"{label} artifact must be a regular file")
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
    descriptor = os.open(artifact_path, flags)
    try:
        opened = os.fstat(descriptor)
        if not stat.S_ISREG(opened.st_mode):
            raise ContractError(f"{label} artifact must be a regular file")
        if (before.st_dev, before.st_ino) != (opened.st_dev, opened.st_ino):
            raise ContractError(f"{label} artifact changed before read")
        with os.fdopen(descriptor, "rb") as artifact_file:
            descriptor = -1
            raw = artifact_file.read()
    finally:
        if descriptor != -1:
            os.close(descriptor)
    actual_sha = hashlib.sha256(raw).hexdigest()
    if Path(artifact_ref).name != f"{actual_sha}.json":
        raise ContractError(f"{label} artifact_ref is not the canonical content address")
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ContractError(f"{label} artifact must be UTF-8 JSON") from exc
    payload = _require_dict(payload, f"{label} artifact")
    canonical = canonical_json_bytes(payload) + b"\n"
    if canonical != raw:
        raise ContractError(f"{label} artifact must use canonical JSON plus newline")
    return payload, actual_sha


def _require_canonical_verification_ref(
    artifact_ref: str,
    artifact_sha256: str,
    schema: str,
    *,
    label: str,
) -> None:
    directory_by_schema = {
        VERIFICATION_REQUEST_SCHEMA: VERIFICATION_REQUEST_DIR,
        VERIFICATION_ATTESTATION_SCHEMA: VERIFICATION_ATTESTATION_DIR,
    }
    if schema not in directory_by_schema:
        raise ContractError(f"{label} has unsupported artifact schema")
    expected = str(Path(directory_by_schema[schema]) / f"{artifact_sha256}.json")
    if artifact_ref != expected:
        raise ContractError(f"{label} must equal canonical path {expected}")


def _strip_subject_artifact_fields(value: Any) -> Any:
    if not isinstance(value, dict):
        return deepcopy(value)
    return {
        key: deepcopy(nested)
        for key, nested in value.items()
        if key not in VERIFICATION_LEGACY_KEYS
    }


def _verification_artifact_descriptor(
    *,
    mode: str,
    verifier_id: str,
    artifact_ref: str,
    artifact_sha256: str,
    subject_digest: str,
) -> dict[str, Any]:
    return _validate_claim_verification(
        {
            "mode": mode,
            "verifier_id": verifier_id,
            "artifact_ref": artifact_ref,
            "artifact_sha256": artifact_sha256,
            "subject_digest": subject_digest,
        },
        "verification artifact descriptor",
        allow_artifact=True,
    )


def _build_verification_request(
    report: dict[str, Any],
    *,
    producer_context_id: str,
    support_candidate_eligible: bool,
    report_set_context: dict[str, Any],
    expected_report_identities: list[dict[str, str]],
) -> dict[str, Any]:
    verification = _validate_claim_verification(
        report.get("verification"),
        f"report[{report['report_id']}] verification",
        allow_artifact=True,
    )
    request: dict[str, Any] = {
        "schema": VERIFICATION_REQUEST_SCHEMA,
        "mode": verification["mode"],
        "verifier_id": verification["verifier_id"],
        "producer_context_id": _require_non_empty_string(
            producer_context_id, "producer_context_id"
        ),
        "claim_id": _require_non_empty_string(report.get("claim_id"), "report.claim_id"),
        "hypothesis_id": _require_non_empty_string(
            report.get("hypothesis_id"), "report.hypothesis_id"
        ),
        "target_id": _require_non_empty_string(report.get("target_id"), "report.target_id"),
        "scope_digest": sha256_hex(report.get("scope")),
        "evidence_bindings": _canonical_evidence_bindings(report),
        "dossier_id": _require_non_empty_string(report.get("dossier_id"), "report.dossier_id"),
        "dossier_digest": _require_sha256(report.get("dossier_digest"), "report.dossier_digest"),
        "source_bundle_id": _require_non_empty_string(
            report.get("source_bundle_id"), "report.source_bundle_id"
        ),
        "source_bundle_digest": _require_sha256(
            report.get("source_bundle_digest"), "report.source_bundle_digest"
        ),
        "source_artifact_sha256": _require_sha256(
            report.get("source_artifact_sha256"), "report.source_artifact_sha256"
        ),
        "support_candidate_eligible": _require_bool(
            support_candidate_eligible,
            "support_candidate_eligible",
        ),
        "report_set_context": deepcopy(report_set_context),
        "expected_report_identities": deepcopy(expected_report_identities),
    }
    request["subject_digest"] = canonical_report_subject_digest(report)
    return request


def _emit_verification_request(
    report: dict[str, Any],
    verification_root: str | Path,
    *,
    producer_context_id: str,
    support_candidate_eligible: bool,
    report_set_context: dict[str, Any],
    expected_report_identities: list[dict[str, str]],
) -> dict[str, Any]:
    request = _build_verification_request(
        report,
        producer_context_id=producer_context_id,
        support_candidate_eligible=support_candidate_eligible,
        report_set_context=report_set_context,
        expected_report_identities=expected_report_identities,
    )
    artifact_ref, artifact_sha256 = _write_verification_artifact(
        verification_root,
        VERIFICATION_REQUEST_DIR,
        request,
        label="verification request",
    )
    return _verification_artifact_descriptor(
        mode=request["mode"],
        verifier_id=request["verifier_id"],
        artifact_ref=artifact_ref,
        artifact_sha256=artifact_sha256,
        subject_digest=request["subject_digest"],
    )


def _validate_verification_request(raw: Any, label: str) -> dict[str, Any]:
    request = _require_dict(raw, label)
    _reject_unknown_fields(request, VERIFICATION_REQUEST_KEYS, label)
    _require_non_empty_string(request.get("schema"), f"{label}.schema")
    if request.get("schema") != VERIFICATION_REQUEST_SCHEMA:
        raise ContractError(f"{label}.schema must equal {VERIFICATION_REQUEST_SCHEMA}")
    mode = _require_enum(request.get("mode"), f"{label}.mode", VERIFICATION_MODES)
    verifier_id = _require_non_empty_string(request.get("verifier_id"), f"{label}.verifier_id")
    producer_context_id = _require_non_empty_string(
        request.get("producer_context_id"), f"{label}.producer_context_id"
    )
    subject_digest = _require_sha256(request.get("subject_digest"), f"{label}.subject_digest")
    evidence_bindings = _validate_evidence_bindings(
        request.get("evidence_bindings"),
        f"{label}.evidence_bindings",
    )
    validated = {
        "schema": VERIFICATION_REQUEST_SCHEMA,
        "mode": mode,
        "verifier_id": verifier_id,
        "producer_context_id": producer_context_id,
        "subject_digest": subject_digest,
        "claim_id": _require_non_empty_string(request.get("claim_id"), f"{label}.claim_id"),
        "hypothesis_id": _require_non_empty_string(
            request.get("hypothesis_id"), f"{label}.hypothesis_id"
        ),
        "target_id": _require_non_empty_string(request.get("target_id"), f"{label}.target_id"),
        "scope_digest": _require_sha256(request.get("scope_digest"), f"{label}.scope_digest"),
        "evidence_bindings": evidence_bindings,
        "dossier_id": _require_non_empty_string(request.get("dossier_id"), f"{label}.dossier_id"),
        "dossier_digest": _require_sha256(request.get("dossier_digest"), f"{label}.dossier_digest"),
        "source_bundle_id": _require_non_empty_string(
            request.get("source_bundle_id"), f"{label}.source_bundle_id"
        ),
        "source_bundle_digest": _require_sha256(
            request.get("source_bundle_digest"), f"{label}.source_bundle_digest"
        ),
        "source_artifact_sha256": _require_sha256(
            request.get("source_artifact_sha256"), f"{label}.source_artifact_sha256"
        ),
        "support_candidate_eligible": _require_bool(
            request.get("support_candidate_eligible"),
            f"{label}.support_candidate_eligible",
        ),
        "report_set_context": _validate_report_set_context(
            request.get("report_set_context"), f"{label}.report_set_context"
        ),
        "expected_report_identities": _validate_expected_report_identities(
            request.get("expected_report_identities"),
            f"{label}.expected_report_identities",
        ),
    }
    return validated


def _build_verification_attestation(
    report: dict[str, Any],
    request: dict[str, Any],
    *,
    verifier_id: str,
    mode: str,
    verdict: str,
    basis: str,
    verifier_context_id: str,
    request_ref: str,
    request_digest: str,
) -> dict[str, Any]:
    if mode != request["mode"]:
        raise ContractError("attestation mode must match request mode")
    attestation = {
        "schema": VERIFICATION_ATTESTATION_SCHEMA,
        "mode": mode,
        "verifier_id": _require_non_empty_string(verifier_id, "attest.verifier_id"),
        "origin": "external_verifier",
        "verdict": _require_enum(verdict, "attest.verdict", ATTESTATION_VERDICTS),
        "basis": _require_non_empty_string(basis, "attest.basis"),
        "request_ref": _require_non_empty_string(request_ref, "attest.request_ref"),
        "request_digest": _require_sha256(request_digest, "attest.request_digest"),
        "subject_digest": request["subject_digest"],
        "claim_id": report["claim_id"],
        "hypothesis_id": report["hypothesis_id"],
        "target_id": report["target_id"],
        "scope_digest": request["scope_digest"],
        "evidence_bindings": request["evidence_bindings"],
        "dossier_id": report["dossier_id"],
        "dossier_digest": report["dossier_digest"],
        "source_bundle_id": report["source_bundle_id"],
        "source_bundle_digest": report["source_bundle_digest"],
        "source_artifact_sha256": report["source_artifact_sha256"],
        "support_candidate_eligible": request["support_candidate_eligible"],
        "report_set_context": request["report_set_context"],
        "expected_report_identities": request["expected_report_identities"],
        "verifier_context_id": _require_non_empty_string(
            verifier_context_id, "attest.verifier_context_id"
        ),
        "producer_context_id": request["producer_context_id"],
        "created_at": _now_utc(),
    }
    return attestation


def _emit_verification_attestation(
    report: dict[str, Any],
    verification_root: str | Path,
    request: dict[str, Any],
    *,
    verifier_id: str,
    mode: str,
    verdict: str,
    basis: str,
    verifier_context_id: str,
    request_ref: str,
    request_digest: str,
) -> dict[str, Any]:
    attestation = _build_verification_attestation(
        report,
        request,
        verifier_id=verifier_id,
        mode=mode,
        verdict=verdict,
        basis=basis,
        verifier_context_id=verifier_context_id,
        request_ref=request_ref,
        request_digest=request_digest,
    )
    artifact_ref, artifact_sha256 = _write_verification_artifact(
        verification_root,
        VERIFICATION_ATTESTATION_DIR,
        attestation,
        label="verification attestation",
    )
    return _verification_artifact_descriptor(
        mode=attestation["mode"],
        verifier_id=attestation["verifier_id"],
        artifact_ref=artifact_ref,
        artifact_sha256=artifact_sha256,
        subject_digest=attestation["subject_digest"],
    )


def _validate_verification_attestation(raw: Any, label: str) -> dict[str, Any]:
    attestation = _require_dict(raw, label)
    _reject_unknown_fields(attestation, VERIFICATION_ATTESTATION_KEYS, label)
    if attestation.get("schema") != VERIFICATION_ATTESTATION_SCHEMA:
        raise ContractError(f"{label}.schema must equal {VERIFICATION_ATTESTATION_SCHEMA}")
    validated = {
        "schema": VERIFICATION_ATTESTATION_SCHEMA,
        "mode": _require_enum(attestation.get("mode"), f"{label}.mode", VERIFICATION_MODES),
        "verifier_id": _require_non_empty_string(
            attestation.get("verifier_id"), f"{label}.verifier_id"
        ),
        "origin": _require_enum(
            attestation.get("origin"), f"{label}.origin", VERIFICATION_ORIGINS
        ),
        "verdict": _require_enum(
            attestation.get("verdict"), f"{label}.verdict", ATTESTATION_VERDICTS
        ),
        "basis": _require_non_empty_string(attestation.get("basis"), f"{label}.basis"),
        "request_ref": _require_non_empty_string(
            attestation.get("request_ref"), f"{label}.request_ref"
        ),
        "request_digest": _require_sha256(
            attestation.get("request_digest"), f"{label}.request_digest"
        ),
        "subject_digest": _require_sha256(
            attestation.get("subject_digest"), f"{label}.subject_digest"
        ),
        "claim_id": _require_non_empty_string(attestation.get("claim_id"), f"{label}.claim_id"),
        "hypothesis_id": _require_non_empty_string(
            attestation.get("hypothesis_id"), f"{label}.hypothesis_id"
        ),
        "target_id": _require_non_empty_string(attestation.get("target_id"), f"{label}.target_id"),
        "scope_digest": _require_sha256(attestation.get("scope_digest"), f"{label}.scope_digest"),
        "evidence_bindings": _validate_evidence_bindings(
            attestation.get("evidence_bindings"),
            f"{label}.evidence_bindings",
        ),
        "dossier_id": _require_non_empty_string(
            attestation.get("dossier_id"), f"{label}.dossier_id"
        ),
        "dossier_digest": _require_sha256(
            attestation.get("dossier_digest"), f"{label}.dossier_digest"
        ),
        "source_bundle_id": _require_non_empty_string(
            attestation.get("source_bundle_id"), f"{label}.source_bundle_id"
        ),
        "source_bundle_digest": _require_sha256(
            attestation.get("source_bundle_digest"), f"{label}.source_bundle_digest"
        ),
        "source_artifact_sha256": _require_sha256(
            attestation.get("source_artifact_sha256"), f"{label}.source_artifact_sha256"
        ),
        "support_candidate_eligible": _require_bool(
            attestation.get("support_candidate_eligible"),
            f"{label}.support_candidate_eligible",
        ),
        "report_set_context": _validate_report_set_context(
            attestation.get("report_set_context"), f"{label}.report_set_context"
        ),
        "expected_report_identities": _validate_expected_report_identities(
            attestation.get("expected_report_identities"),
            f"{label}.expected_report_identities",
        ),
        "verifier_context_id": _require_non_empty_string(
            attestation.get("verifier_context_id"), f"{label}.verifier_context_id"
        ),
        "producer_context_id": _require_non_empty_string(
            attestation.get("producer_context_id"), f"{label}.producer_context_id"
        ),
        "created_at": _require_timestamp(attestation.get("created_at"), f"{label}.created_at"),
    }
    return validated


def _compute_report_projection_status(
    support_candidate_eligible: bool,
    verification: dict[str, Any],
    *,
    finalized: bool = False,
) -> str:
    if (
        finalized
        and verification.get("origin") == "external_verifier"
        and verification.get("verdict") == "passed"
        and verification.get("mode") in DECISIVE_VERIFICATION_MODES
        and support_candidate_eligible
    ):
        return "decisive"
    return "terminal_coverage"


def _validate_verification_report_bindings(
    artifact: dict[str, Any],
    report: dict[str, Any],
    *,
    descriptor: dict[str, Any],
    report_set_context: dict[str, Any],
    expected_report_identities: list[dict[str, str]],
    label: str,
) -> None:
    expected_bindings = _canonical_evidence_bindings(report)
    expected_values = {
        "claim_id": report["claim_id"],
        "hypothesis_id": report["hypothesis_id"],
        "target_id": report["target_id"],
        "scope_digest": sha256_hex(report["scope"]),
        "dossier_id": report["dossier_id"],
        "dossier_digest": report["dossier_digest"],
        "source_bundle_id": report["source_bundle_id"],
        "source_bundle_digest": report["source_bundle_digest"],
        "source_artifact_sha256": report["source_artifact_sha256"],
    }
    if artifact["mode"] != descriptor["mode"]:
        raise ContractError(f"{label}.mode does not match report verification")
    if artifact["verifier_id"] != descriptor["verifier_id"]:
        raise ContractError(f"{label}.verifier_id does not match report verification")
    if artifact["subject_digest"] != descriptor["subject_digest"]:
        raise ContractError(f"{label}.subject_digest does not match report verification")
    if artifact["subject_digest"] != canonical_report_subject_digest(report):
        raise ContractError(f"{label}.subject_digest does not match frozen report subject")
    if artifact["evidence_bindings"] != expected_bindings:
        raise ContractError(f"{label}.evidence_bindings do not match report")
    if artifact["report_set_context"] != report_set_context:
        raise ContractError(f"{label}.report_set_context does not match report-set")
    if artifact["expected_report_identities"] != expected_report_identities:
        raise ContractError(f"{label}.expected_report_identities do not match report-set")
    for key, expected in expected_values.items():
        if artifact[key] != expected:
            raise ContractError(f"{label}.{key} does not match report")


def _parse_report_verification(
    raw: Any,
    index: int,
    *,
    report: dict[str, Any],
    report_set_context: dict[str, Any],
    expected_report_identities: list[dict[str, str]],
    verification_root: str | Path | None = None,
    finalize: bool = False,
) -> tuple[str, dict[str, Any], dict[str, Any] | None, bool, str]:
    label = f"reports[{index}].verification"
    descriptor = _validate_claim_verification(raw, label, allow_artifact=True)
    if "artifact_ref" not in descriptor:
        if finalize:
            raise ContractError(f"{label} must reference an external attestation")
        return "draft", descriptor, None, False, "terminal_coverage"
    if verification_root is None:
        raise ContractError(f"{label} requires verification_root to reopen its artifact")

    artifact_file, actual_sha256 = _read_verification_artifact(
        verification_root,
        descriptor["artifact_ref"],
        label=label,
    )
    if actual_sha256 != descriptor["artifact_sha256"]:
        raise ContractError(f"{label}.artifact_sha256 does not match artifact bytes")
    schema = _require_non_empty_string(artifact_file.get("schema"), f"{label} artifact.schema")
    _require_canonical_verification_ref(
        descriptor["artifact_ref"],
        descriptor["artifact_sha256"],
        schema,
        label=label,
    )

    if schema == VERIFICATION_REQUEST_SCHEMA:
        request = _validate_verification_request(artifact_file, f"{label} request")
        _validate_verification_report_bindings(
            request,
            report,
            descriptor=descriptor,
            report_set_context=report_set_context,
            expected_report_identities=expected_report_identities,
            label=f"{label} request",
        )
        if finalize:
            raise ContractError(f"{label} still references a request, not an attestation")
        return "request", descriptor, request, False, "terminal_coverage"

    if schema != VERIFICATION_ATTESTATION_SCHEMA:
        raise ContractError(
            f"{label} artifact.schema must be {VERIFICATION_REQUEST_SCHEMA} or "
            f"{VERIFICATION_ATTESTATION_SCHEMA}"
        )

    attestation = _validate_verification_attestation(
        artifact_file,
        f"{label} attestation",
    )
    _validate_verification_report_bindings(
        attestation,
        report,
        descriptor=descriptor,
        report_set_context=report_set_context,
        expected_report_identities=expected_report_identities,
        label=f"{label} attestation",
    )
    request_file, request_sha256 = _read_verification_artifact(
        verification_root,
        attestation["request_ref"],
        label=f"{label} request",
    )
    if request_sha256 != attestation["request_digest"]:
        raise ContractError(f"{label} request_digest does not match request bytes")
    request = _validate_verification_request(request_file, f"{label} request")
    _require_canonical_verification_ref(
        attestation["request_ref"],
        attestation["request_digest"],
        request["schema"],
        label=f"{label} request",
    )
    _validate_verification_report_bindings(
        request,
        report,
        descriptor={
            "mode": request["mode"],
            "verifier_id": request["verifier_id"],
            "subject_digest": request["subject_digest"],
        },
        report_set_context=report_set_context,
        expected_report_identities=expected_report_identities,
        label=f"{label} request",
    )
    bound_keys = {
        "mode",
        "verifier_id",
        "producer_context_id",
        "subject_digest",
        "claim_id",
        "hypothesis_id",
        "target_id",
        "scope_digest",
        "evidence_bindings",
        "dossier_id",
        "dossier_digest",
        "source_bundle_id",
        "source_bundle_digest",
        "source_artifact_sha256",
        "support_candidate_eligible",
        "report_set_context",
        "expected_report_identities",
    }
    for key in bound_keys:
        if attestation[key] != request[key]:
            raise ContractError(f"{label} request/attestation {key} mismatch")
    if attestation["verifier_context_id"] == request["producer_context_id"]:
        raise ContractError(
            f"{label} verifier_context_id must differ from producer_context_id"
        )
    if attestation["origin"] != "external_verifier":
        raise ContractError(f"{label} origin must be external_verifier")

    eligible = bool(
        finalize
        and attestation["support_candidate_eligible"]
        and attestation["verdict"] == "passed"
        and attestation["mode"] in DECISIVE_VERIFICATION_MODES
    )
    status = _compute_report_projection_status(
        attestation["support_candidate_eligible"],
        attestation,
        finalized=finalize,
    )
    return "attestation", descriptor, attestation, eligible, status


def project_report_set(
    dossier: dict[str, Any],
    *,
    bundle: str,
    source: str,
    generated_at: str | None = None,
    projection_finalized: bool = False,
) -> dict[str, Any]:
    if generated_at is not None:
        dossier = deepcopy(dossier)
        dossier["generated_at"] = _require_timestamp(generated_at, "generated_at")
    validated = _validate_dossier(dossier, bundle=bundle, source=source, canonicalize=False)
    set_payload = _report_set_projection_binding(validated)
    if generated_at is not None:
        set_payload["generated_at"] = validated["generated_at"]

    reports = _project_claims(validated, projection_finalized=projection_finalized)
    set_payload["reports"] = reports
    set_payload["completion_matrix"] = _report_set_completion_matrix(
        set_payload["completion_matrix"],
        reports,
    )
    set_payload["report_set_digest"] = _v2_dossier_digest(set_payload)
    set_payload["report_set_id"] = _canonical_id(V2_SET_PREFIX, set_payload["report_set_digest"])

    projected = validate_report_set_v2(set_payload)
    return projected


def validate_report_set_v2(
    report_set: dict[str, Any],
    *,
    verification_root: str | Path | None = None,
    require_finalized: bool = False,
) -> dict[str, Any]:
    payload = _require_dict(report_set, "report_set")
    _reject_unknown_fields(payload, V2_SET_KEYS, "report_set")
    if _require_enum(payload.get("schema"), "report_set.schema", {V2_SCHEMA}) != V2_SCHEMA:
        raise ContractError("report_set.schema must be PaperReadingReportSet/v2")
    if _require_non_empty_string(payload.get("schema_version"), "report_set.schema_version") != V2_SCHEMA_VERSION:
        raise ContractError("report_set.schema_version must be v2")
    if _require_non_empty_string(payload.get("producer"), "report_set.producer") != PRODUCER:
        raise ContractError("report_set.producer must be learn-from-papers")
    if _require_non_empty_string(payload.get("protocol_version"), "report_set.protocol_version") != PROTOCOL_VERSION:
        raise ContractError("report_set.protocol_version must be 1.0")
    _require_timestamp(payload.get("generated_at"), "report_set.generated_at")

    set_payload = {key: value for key, value in payload.items() if key not in {"report_set_id", "report_set_digest"}}
    set_payload["network_ref"] = _validate_network_ref(payload.get("network_ref"), "report_set.network_ref")
    _require_non_empty_string(payload.get("source_bundle_id"), "report_set.source_bundle_id")
    _require_sha256(payload.get("source_bundle_digest"), "report_set.source_bundle_digest")
    source_ref = _require_non_empty_string(payload.get("source_ref"), "report_set.source_ref")
    source_artifact_sha256 = _require_sha256(
        payload.get("source_artifact_sha256"), "report_set.source_artifact_sha256"
    )
    set_payload["review_source"] = _validate_review_source(
        payload.get("review_source"), "report_set.review_source"
    )
    _require_non_empty_string(
        payload.get("review_request_set_id"), "report_set.review_request_set_id"
    )
    _require_sha256(payload.get("review_request_set_digest"), "report_set.review_request_set_digest")
    _require_non_empty_string(payload.get("dossier_id"), "report_set.dossier_id")
    if not payload["dossier_id"].startswith(DOSSIER_ID_PREFIX):
        raise ContractError("report_set.dossier_id must start with reading-dossier-")
    _require_sha256(payload.get("dossier_digest"), "report_set.dossier_digest")

    reports = _require_list(payload.get("reports"), "report_set.reports")
    if not reports:
        raise ContractError("report_set.reports must not be empty")
    report_ids = [
        _require_non_empty_string(report.get("report_id"), f"reports[{index}].report_id")
        for index, report in enumerate(reports)
    ]
    claim_ids = [
        _require_non_empty_string(report.get("claim_id"), f"reports[{index}].claim_id")
        for index, report in enumerate(reports)
    ]
    if len(report_ids) != len(set(report_ids)):
        raise ContractError("report_set.reports contains duplicate report_id")
    if len(claim_ids) != len(set(claim_ids)):
        raise ContractError("report_set.reports contains duplicate claim_id")
    report_set_context = _report_set_attestation_context(payload)
    expected_report_identities = _expected_report_identities(payload)
    validated_reports: list[dict[str, Any]] = []

    for index, report in enumerate(reports):
        report_payload = _require_dict(report, f"report_set.reports[{index}]")
        _reject_unknown_fields(report_payload, V2_REPORT_KEYS, f"report_set.reports[{index}]")
        if _require_enum(report_payload.get("schema"), f"report_set.reports[{index}].schema", {V2_REPORT_SCHEMA}) != V2_REPORT_SCHEMA:
            raise ContractError("report schema must be PaperReadingReport/v2")
        if _require_non_empty_string(report_payload.get("schema_version"), f"report_set.reports[{index}].schema_version") != V2_SCHEMA_VERSION:
            raise ContractError("report schema_version must be v2")
        if _require_non_empty_string(report_payload.get("producer"), f"reports[{index}].producer") != PRODUCER:
            raise ContractError("report producer must be learn-from-papers")
        if _require_non_empty_string(
            report_payload.get("protocol_version"), f"report_set.reports[{index}].protocol_version"
        ) != PROTOCOL_VERSION:
            raise ContractError("report protocol_version must be 1.0")

        _require_non_empty_string(report_payload.get("review_request_id"), f"reports[{index}].review_request_id")
        _require_sha256(report_payload.get("review_request_digest"), f"reports[{index}].review_request_digest")
        _require_non_empty_string(report_payload.get("review_request_set_id"), f"reports[{index}].review_request_set_id")
        _require_sha256(report_payload.get("review_request_set_digest"), f"reports[{index}].review_request_set_digest")
        _require_non_empty_string(report_payload.get("hypothesis_id"), f"reports[{index}].hypothesis_id")
        _require_non_empty_string(report_payload.get("claim_id"), f"reports[{index}].claim_id")
        _require_non_empty_string(report_payload.get("target_id"), f"reports[{index}].target_id")
        _require_non_empty_string(
            report_payload.get("claim_statement"), f"reports[{index}].claim_statement"
        )
        report_payload["scope"] = _validate_scope(report_payload.get("scope"), f"reports[{index}].scope")
        _require_non_empty_string(report_payload.get("dossier_id"), f"reports[{index}].dossier_id")
        if report_payload["dossier_id"] != payload["dossier_id"]:
            raise ContractError(f"reports[{index}] dossier_id must match report-set dossier_id")
        _require_sha256(report_payload.get("dossier_digest"), f"reports[{index}].dossier_digest")
        if report_payload["dossier_digest"] != payload["dossier_digest"]:
            raise ContractError(f"reports[{index}] dossier_digest must match report-set dossier_digest")
        _require_non_empty_string(report_payload.get("source_ref"), f"reports[{index}].source_ref")
        if report_payload["source_ref"] != source_ref:
            raise ContractError(f"reports[{index}] source_ref must match report-set source_ref")
        _require_sha256(
            report_payload.get("source_artifact_sha256"),
            f"reports[{index}].source_artifact_sha256",
        )
        if report_payload.get("source_artifact_sha256") != source_artifact_sha256:
            raise ContractError(
                f"reports[{index}] source_artifact_sha256 must match report-set source_artifact_sha256"
            )
        report_payload["review_source"] = _validate_review_source(
            report_payload.get("review_source"), f"reports[{index}].review_source"
        )
        if report_payload["review_source"] != set_payload["review_source"]:
            raise ContractError(f"reports[{index}] review_source must match report-set review_source")
        claim_support_eligible = _require_bool(
            report_payload.get("claim_support_eligible"),
            f"reports[{index}].claim_support_eligible",
        )
        (
            verification_kind,
            report_payload["verification"],
            _,
            expected_eligibility,
            projected_status,
        ) = _parse_report_verification(
            report_payload.get("verification"),
            index,
            report=report_payload,
            report_set_context=report_set_context,
            expected_report_identities=expected_report_identities,
            verification_root=verification_root,
            finalize=require_finalized,
        )
        if verification_kind not in {"draft", "request", "attestation"}:
            raise ContractError(f"reports[{index}] unsupported verification kind")
        if claim_support_eligible != expected_eligibility:
            raise ContractError(
                f"reports[{index}] claim_support_eligible must match verified attestation state"
            )
        if report_payload["projection_status"] != projected_status:
            raise ContractError(
                f"reports[{index}] projection_status must match verified verification"
            )
        _require_enum(
            report_payload.get("relation"), f"reports[{index}].relation", V2_RELATION_ALLOWLIST
        )
        _require_enum(
            report_payload.get("evidence_relation"),
            f"reports[{index}].evidence_relation",
            V2_RELATION_ALLOWLIST,
        )
        if report_payload["evidence_relation"] != report_payload["relation"]:
            raise ContractError(
                f"reports[{index}] evidence_relation must match relation"
            )
        _require_bool(report_payload.get("claim_support_eligible"), f"reports[{index}].claim_support_eligible")
        _require_enum(
            report_payload.get("projection_status"),
            f"reports[{index}].projection_status",
            {"decisive", "terminal_coverage"},
        )
        report_payload["actual_evidence_locator"] = report_payload.get("actual_evidence_locator")
        if report_payload["actual_evidence_locator"] is not None:
            _validate_exact_locator(
                report_payload["actual_evidence_locator"],
                f"reports[{index}].actual_evidence_locator",
            )
        _require_non_empty_string(
            report_payload.get("source_bundle_id"), f"reports[{index}].source_bundle_id"
        )
        _require_sha256(report_payload.get("source_bundle_digest"), f"reports[{index}].source_bundle_digest")
        if report_payload["projection_status"] == "decisive" and not report_payload["claim_support_eligible"]:
            raise ContractError(f"reports[{index}] decisive projection requires claim_support_eligible=true")
        if not report_payload["claim_support_eligible"] and report_payload["projection_status"] != "terminal_coverage":
            raise ContractError(f"reports[{index}] noneligible claim not marked terminal")
        if not report_payload["actual_evidence_locator"] and report_payload["claim_support_eligible"]:
            raise ContractError(f"decisive report {index} must carry actual_evidence_locator")
        evidence_bindings = _validate_evidence_bindings(
            report_payload.get("evidence_bindings"),
            f"reports[{index}].evidence_bindings",
        )
        evidence_ids = _require_string_list(
            report_payload.get("evidence_ids", []), f"reports[{index}].evidence_ids"
        )
        if len(evidence_ids) != len(set(evidence_ids)):
            raise ContractError(f"reports[{index}].evidence_ids contains duplicate evidence_id")
        evidence_binding_ids = [binding["evidence_id"] for binding in evidence_bindings]
        if len(evidence_binding_ids) != len(set(evidence_binding_ids)):
            raise ContractError(
                f"reports[{index}].evidence_bindings contains duplicate evidence_id"
            )
        if set(evidence_ids) != set(evidence_binding_ids):
            raise ContractError(f"reports[{index}].evidence_ids must match evidence_bindings")
        if report_payload["claim_support_eligible"] and not evidence_ids:
            raise ContractError(f"reports[{index}] decisive claim must include evidence_ids")
        if report_payload["claim_support_eligible"]:
            if report_payload["actual_evidence_locator"] not in {
                binding["exact_locator"] for binding in evidence_bindings
            }:
                raise ContractError(
                    f"decisive report {index} actual_evidence_locator must match one evidence_binding exact_locator"
                )
        if report_payload["coverage_reason"] is not None:
            _require_non_empty_string(
                report_payload.get("coverage_reason"), f"reports[{index}].coverage_reason"
            )
        if report_payload.get("actual_evidence_locator") is not None and not evidence_bindings:
            raise ContractError(
                f"reports[{index}] evidence_bindings cannot be empty when actual_evidence_locator is set"
            )
        if report_payload["review_request_set_id"] != payload.get("review_request_set_id"):
            raise ContractError(
                f"reports[{index}] review_request_set_id must match report-set review_request_set_id"
            )
        if report_payload["review_request_set_digest"] != payload.get("review_request_set_digest"):
            raise ContractError(
                f"reports[{index}] review_request_set_digest must match report-set review_request_set_digest"
            )
        report_payload["evidence_bindings"] = evidence_bindings
        report_payload["evidence_ids"] = evidence_ids

        canonical = {key: value for key, value in report_payload.items() if key not in {"report_id", "report_digest"}}
        digest = _v2_report_digest(canonical)
        report_id = _canonical_id(V2_REPORT_PREFIX, digest)
        if _require_non_empty_string(
            report_payload.get("report_digest"), f"reports[{index}].report_digest"
        ) != digest:
            raise ContractError(f"reports[{index}].report_digest mismatch")
        if _require_non_empty_string(
            report_payload.get("report_id"), f"reports[{index}].report_id"
        ) != report_id:
            raise ContractError(f"reports[{index}].report_id mismatch")
        if report_payload.get("source_bundle_id") != payload.get("source_bundle_id"):
            raise ContractError(f"reports[{index}] bundle_id must match report-set source_bundle_id")
        if report_payload.get("source_bundle_digest") != payload.get("source_bundle_digest"):
            raise ContractError(f"reports[{index}] bundle_digest must match report-set source_bundle_digest")
        if report_payload.get("access_level") != payload.get("access_level"):
            raise ContractError(f"reports[{index}] access_level must match report-set access_level")
        if report_payload.get("inspection_depth") != payload.get("inspection_depth"):
            raise ContractError(f"reports[{index}] inspection_depth mismatch")
        if report_payload.get("reconstruction_status") != payload.get("reconstruction_status"):
            raise ContractError(f"reports[{index}] reconstruction_status mismatch")
        validated_reports.append(report_payload)

    set_payload["reports"] = validated_reports
    expected_completion_matrix = _report_set_completion_matrix(
        payload.get("completion_matrix"),
        validated_reports,
    )
    if payload.get("completion_matrix") != expected_completion_matrix:
        raise ContractError("report_set.completion_matrix does not match reports")
    set_payload["completion_matrix"] = expected_completion_matrix
    expected_report_set_digest = _v2_dossier_digest(set_payload)
    if _require_sha256(payload.get("report_set_digest"), "report_set.report_set_digest") != expected_report_set_digest:
        raise ContractError("report_set_digest does not match payload")
    expected_set_id = _canonical_id(V2_SET_PREFIX, expected_report_set_digest)
    if _require_non_empty_string(payload.get("report_set_id"), "report_set.report_set_id") != expected_set_id:
        raise ContractError("report_set_id does not match digest")
    return {
        **set_payload,
        "report_set_digest": expected_report_set_digest,
        "report_set_id": expected_set_id,
    }


def _load_json(path: str | Path) -> Any:
    target = Path(path)
    data = target.read_text(encoding="utf-8")
    payload = json.loads(data)
    if not isinstance(payload, dict):
        raise ContractError("input file must contain a JSON object")
    return payload


def _write_json(path: str | Path, payload: Any) -> None:
    output = Path(path)
    _write_atomic(output, canonical_json_bytes(payload) + b"\n")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subcommands = parser.add_subparsers(dest="command", required=True)

    create = subcommands.add_parser("create", help="Canonicalize PaperReadingDossier/v1")
    create.add_argument("--input", required=True, help="Draft dossier JSON path")
    create.add_argument("--output", required=True)
    create.add_argument("--bundle", required=True, help="Source bundle JSON path")
    create.add_argument("--source", required=True, help="Original source document path")
    create.add_argument("--generated-at", help="Override generated_at in UTC")

    validate = subcommands.add_parser("validate", help="Validate PaperReadingDossier/v1")
    validate.add_argument("--input", required=True, help="Dossier JSON path")
    validate.add_argument("--bundle", required=True, help="Source bundle JSON path")
    validate.add_argument("--source", required=True, help="Original source document path")

    audit = subcommands.add_parser("audit", help="Run dossier audit and print computed metrics")
    audit.add_argument("--input", required=True, help="Dossier JSON path")
    audit.add_argument("--bundle", required=True, help="Source bundle JSON path")
    audit.add_argument("--source", required=True, help="Original source document path")

    project = subcommands.add_parser(
        "project-report-set", help="Project dossier to PaperReadingReportSet/v2"
    )
    project.add_argument("--input", required=True, help="Dossier JSON path")
    project.add_argument("--output", required=True, help="Output report-set JSON path")
    project.add_argument("--bundle", required=True, help="Source bundle JSON path")
    project.add_argument("--source", required=True, help="Original source document path")
    project.add_argument("--generated-at", help="Override generated_at in UTC")

    prepare = subcommands.add_parser(
        "prepare-attestations",
        help="Project dossier and write verification request artifacts",
    )
    prepare.add_argument("--input", required=True, help="Dossier JSON path")
    prepare.add_argument("--output", required=True, help="Output report-set JSON path")
    prepare.add_argument("--bundle", required=True, help="Source bundle JSON path")
    prepare.add_argument("--source", required=True, help="Original source document path")
    prepare.add_argument(
        "--verification-root",
        required=True,
        help="Directory to write verifier attestation request/attestation artifacts",
    )
    prepare.add_argument(
        "--producer-context-id",
        required=True,
        help="Producer context id recorded on verification requests",
    )
    prepare.add_argument("--generated-at", help="Override generated_at in UTC")

    attest = subcommands.add_parser(
        "attest",
        help="Attach verification attestations based on request artifacts",
    )
    attest.add_argument("--input", required=True, help="Request-only report-set JSON path")
    attest.add_argument("--output", required=True, help="Output report-set JSON path")
    attest.add_argument(
        "--verification-root",
        required=True,
        help="Directory containing request artifacts and receiving attestations",
    )
    attest.add_argument(
        "--mode",
        required=True,
        choices=sorted(VERIFICATION_MODES),
        help="Verification mode to write into attestation artifacts",
    )
    attest.add_argument(
        "--verifier-id",
        required=True,
        help="External verifier identity recorded on attestation artifacts",
    )
    attest.add_argument(
        "--verdict",
        required=True,
        choices=sorted(ATTESTATION_VERDICTS),
        help="Attestation verdict",
    )
    attest.add_argument("--basis", required=True, help="Attestation basis text")
    attest.add_argument(
        "--verifier-context-id",
        required=True,
        help="External verifier context id",
    )
    attest.add_argument(
        "--report-id",
        help="Select one request-state report; required when the set has multiple reports",
    )

    finalize = subcommands.add_parser(
        "finalize-attestations",
        help="Validate report-set with finalized attestations and recompute ids",
    )
    finalize.add_argument("--input", required=True, help="Attestation report-set JSON path")
    finalize.add_argument("--output", required=True, help="Output finalized report-set JSON path")
    finalize.add_argument(
        "--verification-root",
        required=True,
        help="Directory containing request and attestation artifacts",
    )

    return parser


def main(argv: list[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    try:
        if arguments.command == "create":
            dossier = create_dossier(
                _load_json(arguments.input),
                bundle=arguments.bundle,
                source=arguments.source,
                generated_at=arguments.generated_at,
            )
            _write_json(arguments.output, dossier)
            return 0
        if arguments.command == "validate":
            validate_dossier(
                _load_json(arguments.input),
                bundle=arguments.bundle,
                source=arguments.source,
            )
            print(
                json.dumps(
                    {"valid": True, "schema": SCHEMA},
                    sort_keys=True,
                )
            )
            return 0
        if arguments.command == "audit":
            validated = validate_dossier(
                _load_json(arguments.input),
                bundle=arguments.bundle,
                source=arguments.source,
            )
            print(
                json.dumps(
                    {
                        "valid": True,
                        "dossier_id": validated["dossier_id"],
                        "claim_support_eligible": validated["claim_support_eligible"],
                        "completion_matrix": validated["completion_matrix"],
                        "audit_metrics": validated["audit_metrics"],
                    },
                    sort_keys=True,
                )
            )
            return 0
        if arguments.command == "project-report-set":
            projected = project_report_set(
                _load_json(arguments.input),
                bundle=arguments.bundle,
                source=arguments.source,
                generated_at=arguments.generated_at,
            )
            _write_json(arguments.output, projected)
            return 0
        if arguments.command == "prepare-attestations":
            dossier = validate_dossier(
                _load_json(arguments.input),
                bundle=arguments.bundle,
                source=arguments.source,
            )
            projected = project_report_set(
                dossier,
                bundle=arguments.bundle,
                source=arguments.source,
                generated_at=arguments.generated_at,
            )
            projected = validate_report_set_v2(projected)
            report_set_context = _report_set_attestation_context(projected)
            expected_report_identities = _expected_report_identities(projected)
            for report in projected["reports"]:
                report["projection_status"] = "terminal_coverage"
                report["verification"] = _emit_verification_request(
                    report,
                    arguments.verification_root,
                    producer_context_id=arguments.producer_context_id,
                    support_candidate_eligible=dossier["claim_support_eligible"][
                        report["claim_id"]
                    ],
                    report_set_context=report_set_context,
                    expected_report_identities=expected_report_identities,
                )
                _assign_report_identity(report)
            _assign_report_set_identity(projected)
            projected = validate_report_set_v2(
                projected,
                verification_root=arguments.verification_root,
            )
            _write_json(arguments.output, projected)
            return 0
        if arguments.command == "attest":
            projected = validate_report_set_v2(
                _load_json(arguments.input),
                verification_root=arguments.verification_root,
            )
            if len(projected["reports"]) > 1 and arguments.report_id is None:
                raise ContractError("--report-id is required for a multi-report set")
            selected = 0
            for index, report in enumerate(projected["reports"]):
                if arguments.report_id is not None and report["report_id"] != arguments.report_id:
                    continue
                verification_kind, _, request, _, _ = _parse_report_verification(
                    report["verification"],
                    index,
                    report=report,
                    report_set_context=_report_set_attestation_context(projected),
                    expected_report_identities=_expected_report_identities(projected),
                    verification_root=arguments.verification_root,
                )
                if verification_kind != "request" or request is None:
                    raise ContractError(
                        f"report {report['report_id']} must be in request state before attest"
                    )
                if request["mode"] != arguments.mode:
                    raise ContractError(
                        f"report {report['report_id']} mode mismatch with --mode"
                    )
                if request["verifier_id"] != arguments.verifier_id:
                    raise ContractError(
                        f"report {report['report_id']} request.verifier_id mismatch with --verifier-id"
                    )
                if request["producer_context_id"] == arguments.verifier_context_id:
                    raise ContractError(
                        f"report {report['report_id']} verifier_context_id must differ from producer_context_id"
                    )
                report["verification"] = _emit_verification_attestation(
                    report,
                    arguments.verification_root,
                    request,
                    verifier_id=arguments.verifier_id,
                    mode=arguments.mode,
                    verdict=arguments.verdict,
                    basis=arguments.basis,
                    verifier_context_id=arguments.verifier_context_id,
                    request_ref=report["verification"]["artifact_ref"],
                    request_digest=report["verification"]["artifact_sha256"],
                )
                report["claim_support_eligible"] = False
                report["projection_status"] = "terminal_coverage"
                _assign_report_identity(report)
                selected += 1
            if selected != 1:
                raise ContractError("--report-id must match exactly one request-state report")
            _assign_report_set_identity(projected)
            projected = validate_report_set_v2(
                projected,
                verification_root=arguments.verification_root,
            )
            _write_json(arguments.output, projected)
            return 0
        if arguments.command == "finalize-attestations":
            finalized = validate_report_set_v2(
                _load_json(arguments.input),
                verification_root=arguments.verification_root,
            )
            for index, report in enumerate(finalized["reports"]):
                verification_kind, _, _, eligible, status = _parse_report_verification(
                    report["verification"],
                    index,
                    report=report,
                    report_set_context=_report_set_attestation_context(finalized),
                    expected_report_identities=_expected_report_identities(finalized),
                    verification_root=arguments.verification_root,
                    finalize=True,
                )
                if verification_kind != "attestation":
                    raise ContractError(
                        f"report {report['report_id']} must reference an external attestation"
                    )
                report["claim_support_eligible"] = eligible
                report["projection_status"] = status
                _assign_report_identity(report)
            finalized["completion_matrix"] = _report_set_completion_matrix(
                finalized["completion_matrix"],
                finalized["reports"],
            )
            _assign_report_set_identity(finalized)
            finalized = validate_report_set_v2(
                finalized,
                verification_root=arguments.verification_root,
                require_finalized=True,
            )
            _write_json(arguments.output, finalized)
            return 0
    except (ContractError, SourceBundleContractError, json.JSONDecodeError, ValueError, TypeError, OSError) as exc:
        print(f"paper-reading-dossier failed: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
