#!/usr/bin/env python3
"""Build and validate PaperUnderstanding/v1 records.

This module implements a strict content-addressed validator and a light adapter
for the downstream PaperUnderstandingNoteInput/v1 projection used by
`$curate-research-to-zotero`.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCHEMA = "PaperUnderstanding/v1"
SCHEMA_VERSION = "1.0"
PROTOCOL_VERSION = "1.0"
PRODUCER = "learn-from-papers"
UNDERSTANDING_PREFIX = "paper-understanding-"
UNDERSTANDING_NOTES_INPUT_SCHEMA = "PaperUnderstandingNoteInput/v1"
VALIDATION_SCHEMA = "PaperUnderstandingValidation/v1"
VALIDATION_SCHEMA_VERSION = "1.0"
VALIDATOR_NAME = "learn-from-papers.paper-understanding"
VALIDATOR_VERSION = "1.0"
VALIDATION_PREFIX = "paper-understanding-validation-"

SCRIPT_DIR = Path(__file__).resolve().parent
_SOURCE_BUNDLE_PATH = SCRIPT_DIR / "paper_source_bundle.py"
if not _SOURCE_BUNDLE_PATH.is_file():
    raise RuntimeError("required peer script not found: paper_source_bundle.py")
_SOURCE_BUNDLE_SPEC = importlib.util.spec_from_file_location(
    "paper_source_bundle",
    str(_SOURCE_BUNDLE_PATH),
)
if _SOURCE_BUNDLE_SPEC is None or _SOURCE_BUNDLE_SPEC.loader is None:
    raise RuntimeError("failed to load paper_source_bundle.py")
_source_bundle_module = importlib.util.module_from_spec(_SOURCE_BUNDLE_SPEC)
_SOURCE_BUNDLE_SPEC.loader.exec_module(_source_bundle_module)
verify_source_bundle = _source_bundle_module.verify_bundle

_DOSSIER_PATH = SCRIPT_DIR / "paper_reading_dossier.py"
if not _DOSSIER_PATH.is_file():
    raise RuntimeError("required peer script not found: paper_reading_dossier.py")
_DOSSIER_SPEC = importlib.util.spec_from_file_location(
    "paper_reading_dossier",
    str(_DOSSIER_PATH),
)
if _DOSSIER_SPEC is None or _DOSSIER_SPEC.loader is None:
    raise RuntimeError("failed to load paper_reading_dossier.py")
_dossier_module = importlib.util.module_from_spec(_DOSSIER_SPEC)
_DOSSIER_SPEC.loader.exec_module(_dossier_module)
validate_dossier = _dossier_module.validate_dossier

CANONICAL_SHA_RE = re.compile(r"^[0-9a-f]{64}$")
ID_RE = re.compile(r"[A-Za-z][A-Za-z0-9._:-]{0,127}")
STATUS_VALUES = {"answered", "not_applicable", "unresolved"}
SOURCE_STATED_VALUES = {"source_stated", "agent_reconstructed"}
READER_ROUTE_VALUES = {"map", "evidence", "reconstruction"}
ACCESS_LEVEL_VALUES = {"full_text", "partial_text", "abstract_only", "metadata_only"}
RELATION_VALUES = {"supports", "qualifies", "refutes", "not_tested"}
NATURE_VALUES = {"source-stated", "agent-inferred", "externally-supported", "unresolved"}
CLAIM_STATUS_VALUES = {"answered", "terminal"}
WORKFLOW_NODE_KIND_VALUES = {"input", "intermediate", "output"}
DOSSIER_NATURE_BY_ORIGIN = {
    "source": "source-stated",
    "reconstruction": "agent-inferred",
    "supplement": "externally-supported",
}

TOP_LEVEL_KEYS = {
    "schema",
    "schema_version",
    "producer",
    "protocol_version",
    "generated_at",
    "research_retrieval_title",
    "source_binding",
    "executive_summary",
    "applicability",
    "workflow",
    "mathematical_principles",
    "algorithmic_principles",
    "conclusion",
    "contributions",
    "coverage",
    "claims",
    "understanding_id",
    "understanding_digest",
}

EXECUTIVE_KEYS = {
    "applicability_short",
    "conclusion_short",
    "summary",
    "claim_ids",
}

DOMAIN_BASE_KEYS = {"status", "rationale", "evidence_ids", "missing_information"}

SOURCE_BINDING_KEYS = {
    "source_id",
    "canonical_title",
    "authors",
    "year",
    "venue",
    "stable_identifier",
    "publication_status",
    "source_artifact_sha256",
    "source_bundle_id",
    "source_bundle_digest",
    "reading_dossier_id",
    "reading_dossier_digest",
    "paper_card_ref",
    "evidence_ledger_ref",
    "agent_inferences_explicit",
    "reading_depth",
    "access_level",
    "verified_at",
}

APPLICABILITY_KEYS = DOMAIN_BASE_KEYS | {
    "primary_use_case",
    "applies_when",
    "does_not_apply_when",
    "claim_ids",
}

WORKFLOW_KEYS = DOMAIN_BASE_KEYS | {
    "inputs",
    "preconditions",
    "steps",
    "outputs",
    "data_flow",
    "graph",
}
WORKFLOW_STEP_KEYS = {"step_id", "action", "output", "checks"}
GRAPH_KEYS = {"nodes", "operations"}
GRAPH_NODE_KEYS = {
    "node_id",
    "kind",
    "description",
    "semantic_type",
    "representation",
    "format",
    "shape",
    "unit",
}
GRAPH_OPERATION_KEYS = {"operation_id", "operation", "consumes", "produces"}

MATH_KEYS = DOMAIN_BASE_KEYS | {
    "assumptions",
    "derivation_steps",
    "results",
    "principles",
}
MATH_PRINCIPLE_KEYS = {
    "principle_id",
    "statement",
    "latex",
    "symbols",
    "assumptions",
    "derivation_steps",
    "results",
    "origin",
    "claim_ids",
    "locator",
}
MATH_DERIVATION_STEP_KEYS = {
    "step_id",
    "statement",
    "depends_on",
    "origin",
    "locator",
    "evidence_ids",
}

ALGO_KEYS = DOMAIN_BASE_KEYS | {
    "objective",
    "state_variables",
    "ordered_steps",
    "invariants",
    "failure_modes",
    "algorithms",
}
ALGO_ITEM_KEYS = {
    "algorithm_id",
    "name",
    "inputs",
    "outputs",
    "initialization",
    "ordered_steps",
    "update_rule",
    "stopping_condition",
    "complexity",
    "numerical_risks",
    "claim_ids",
    "locator",
    "origin",
}
ALGO_ORDERED_STEP_KEYS = {
    "step_id",
    "action",
    "depends_on",
    "consumes",
    "produces",
    "origin",
    "locator",
    "evidence_ids",
}

CONCLUSION_KEYS = DOMAIN_BASE_KEYS | {
    "statement",
    "confidence",
    "confidence_rationale",
    "claim_ids",
}

CONTRIBUTION_KEYS = {
    "contribution_id",
    "statement",
    "claim_ids",
    "evidence_ids",
    "domain_refs",
}
CLAIM_KEYS = {
    "claim_id",
    "hypothesis_id",
    "target_id",
    "statement",
    "relation",
    "nature",
    "scope",
    "evidence",
    "evidence_ids",
    "verifier_status",
    "confidence",
    "confidence_rationale",
    "status",
}
SCOPE_KEYS = {"assumptions", "conditions", "units", "exclusions"}
EVIDENCE_ITEM_KEYS = {"evidence_id", "summary", "locator"}
COVERAGE_KEYS = {"understood_claims", "terminal_claims"}
COVERAGE_CLAIM_KEYS = {"claim_id", "reason"}
NOTE_CONFIDENCE_VALUES = {"high", "medium", "low"}
VALIDATION_TOP_LEVEL_KEYS = {
    "schema",
    "schema_version",
    "understanding_id",
    "understanding_digest",
    "validator_name",
    "validator_version",
    "status",
    "source_binding_verified",
    "checks",
    "record_id",
    "record_digest",
}
VALIDATION_CHECK_KEYS = {"check_id", "status"}
VALIDATION_CHECK_IDS = (
    "closed_schema",
    "content_address",
    "cross_references",
    "source_binding",
)
VALIDATION_CHECK_STATUS_VALUES = {"passed", "not_checked"}
UNDERSTANDING_BINDING_KEYS = {
    "understanding_id",
    "understanding_digest",
    "validation_record_id",
    "validation_record_digest",
}



class ContractError(ValueError):
    """Raised when any PaperUnderstanding/v1 invariant is violated."""



def canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def sha256_hex(value: Any) -> str:
    digest = hashlib.sha256()
    if isinstance(value, str):
        value = value.encode("utf-8")
    digest.update(value)
    return digest.hexdigest()


def understanding_id(digest: str) -> str:
    return f"{UNDERSTANDING_PREFIX}{digest[:16]}"


def understanding_digest(payload: dict[str, Any]) -> str:
    normalized = {
        key: value
        for key, value in payload.items()
        if key not in {"understanding_id", "understanding_digest"}
    }
    return sha256_hex(canonical_json_bytes(normalized))


def validation_record_id(digest: str) -> str:
    return f"{VALIDATION_PREFIX}{digest[:16]}"


def validation_record_digest(payload: dict[str, Any]) -> str:
    normalized = {
        key: value
        for key, value in payload.items()
        if key not in {"record_id", "record_digest"}
    }
    return sha256_hex(canonical_json_bytes(normalized))


def _timestamp_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _require_object(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ContractError(f"{label} must be an object")
    return value


def _require_text(value: Any, label: str, *, allow_empty: bool = False) -> str:
    if not isinstance(value, str):
        raise ContractError(f"{label} must be a string")
    text = value.strip()
    if not text and not allow_empty:
        raise ContractError(f"{label} must be non-empty")
    if "\x00" in text:
        raise ContractError(f"{label} must not contain NUL")
    return text


def _require_id(value: Any, label: str) -> str:
    text = _require_text(value, label)
    if not ID_RE.fullmatch(text):
        raise ContractError(f"{label} must match the identifier pattern")
    return text


def _require_sha256(value: Any, label: str) -> str:
    text = _require_text(value, label)
    if not CANONICAL_SHA_RE.fullmatch(text):
        raise ContractError(f"{label} must be 64 lowercase hexadecimal characters")
    return text


def _require_bool(value: Any, label: str) -> bool:
    if not isinstance(value, bool):
        raise ContractError(f"{label} must be a boolean")
    return value


def _require_list(value: Any, label: str, *, nonempty: bool = True) -> list[Any]:
    if not isinstance(value, list):
        raise ContractError(f"{label} must be a list")
    if nonempty and not value:
        raise ContractError(f"{label} must be non-empty")
    return value


def _require_nonempty_list(value: Any, label: str) -> list[str]:
    return [
        _require_text(item, f"{label}[{index}]")
        for index, item in enumerate(_require_list(value, label, nonempty=True))
    ]


def _require_list_maybe_empty(value: Any, label: str) -> list[str]:
    return [
        _require_text(item, f"{label}[{index}]")
        for index, item in enumerate(_require_list(value, label, nonempty=False))
    ]


def _validate_math_derivation_dependencies(
    value: Any,
    label: str,
    *,
    prior_step_ids: set[str],
    assumptions: set[str],
    results: set[str],
) -> list[str]:
    dependencies = _require_list_maybe_empty(value, label)
    normalized: list[str] = []
    for index, raw in enumerate(dependencies):
        dependency = _require_text(raw, f"{label}[{index}]")
        if dependency.startswith("assumption:"):
            ref = dependency[len("assumption:") :]
            if not ref:
                raise ContractError(f"{label}[{index}] must reference a non-empty assumption")
            if ref not in assumptions:
                raise ContractError(
                    f"{label}[{index}] references unknown assumption: {ref}"
                )
            normalized.append(f"assumption:{ref}")
            continue

        if dependency.startswith("result:"):
            ref = dependency[len("result:") :]
            if not ref:
                raise ContractError(f"{label}[{index}] must reference a non-empty result")
            if ref not in results:
                raise ContractError(f"{label}[{index}] references unknown result: {ref}")
            normalized.append(f"result:{ref}")
            continue

        step_ref = dependency
        if dependency.startswith("step:"):
            step_ref = dependency[len("step:") :]
        if step_ref in prior_step_ids:
            normalized.append(f"step:{step_ref}")
            continue

        if dependency.startswith("step:"):
            raise ContractError(
                f"{label}[{index}] references future or unknown derivation step: {dependency}"
            )

        raise ContractError(
            f"{label}[{index}] references unknown derivation dependency: {dependency}"
        )
    return normalized


def _validate_ordered_step_dependencies(
    value: Any,
    label: str,
    *,
    prior_step_ids: set[str],
) -> list[str]:
    dependencies = _require_list_maybe_empty(value, label)
    normalized: list[str] = []
    for index, raw in enumerate(dependencies):
        dependency = _require_text(raw, f"{label}[{index}]")
        dep_ref = dependency
        if dependency.startswith("result:"):
            dep_ref = dependency[len("result:") :]
        dep_id = _require_id(dep_ref, f"{label}[{index}]")
        if dep_id not in prior_step_ids:
            raise ContractError(
                f"{label}[{index}] references future or unknown ordered step: {dependency}"
            )
        normalized.append(dep_id)
    return normalized


def _validate_derivation_steps(
    value: Any,
    label: str,
    *,
    prior_assumptions: set[str],
    declared_results: set[str],
) -> list[dict[str, Any]]:
    steps_raw = _require_list(value, label, nonempty=False)
    normalized: list[dict[str, Any]] = []
    prior_step_ids: set[str] = set()
    for index, raw_step in enumerate(steps_raw):
        step_label = f"{label}[{index}]"
        step = _require_object(raw_step, step_label)
        _require_keys(step, step_label, MATH_DERIVATION_STEP_KEYS)
        step_id = _require_id(step["step_id"], f"{step_label}.step_id")
        if step_id in prior_step_ids:
            raise ContractError(f"{step_label}.step_id is duplicated")
        depends_on = _validate_math_derivation_dependencies(
            step["depends_on"],
            f"{step_label}.depends_on",
            prior_step_ids=prior_step_ids,
            assumptions=prior_assumptions,
            results=declared_results,
        )
        normalized.append(
            {
                "step_id": step_id,
                "statement": _require_text(step["statement"], f"{step_label}.statement"),
                "depends_on": depends_on,
                "origin": _require_origin(step["origin"], f"{step_label}.origin"),
                "locator": _require_text(step["locator"], f"{step_label}.locator"),
                "evidence_ids": _require_list_maybe_empty(
                    step["evidence_ids"], f"{step_label}.evidence_ids"
                ),
            }
        )
        prior_step_ids.add(step_id)
    return normalized


def _require_scope(value: Any, label: str) -> dict[str, list[str]]:
    scope = _require_object(value, label)
    if set(scope) != SCOPE_KEYS:
        raise ContractError(f"{label} has unsupported keys: {sorted(set(scope))}")
    return {
        "assumptions": _require_list_maybe_empty(scope["assumptions"], f"{label}.assumptions"),
        "conditions": _require_list_maybe_empty(scope["conditions"], f"{label}.conditions"),
        "units": _require_list_maybe_empty(scope["units"], f"{label}.units"),
        "exclusions": _require_list_maybe_empty(scope["exclusions"], f"{label}.exclusions"),
    }


def _require_timestamp(value: Any, label: str) -> str:
    text = _require_text(value, label)
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ContractError(f"{label} must be ISO 8601 with a timezone") from exc
    if parsed.tzinfo is None:
        raise ContractError(f"{label} must include timezone")
    return parsed.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _require_status(value: Any, label: str) -> str:
    text = _require_text(value, label)
    if text not in STATUS_VALUES:
        raise ContractError(f"{label} must be one of: {', '.join(sorted(STATUS_VALUES))}")
    return text


def _require_origin(value: Any, label: str) -> str:
    text = _require_text(value, label)
    if text not in SOURCE_STATED_VALUES:
        raise ContractError(f"{label} must be source_stated or agent_reconstructed")
    return text


def _require_note_confidence(value: Any, label: str) -> str:
    text = _require_text(value, label)
    if text not in NOTE_CONFIDENCE_VALUES:
        raise ContractError(f"{label} must be one of: {', '.join(sorted(NOTE_CONFIDENCE_VALUES))}")
    return text


def _require_keys(value: dict[str, Any], label: str, expected: set[str]) -> None:
    unknown = set(value) - expected
    missing = expected - set(value)
    if unknown:
        raise ContractError(f"{label} has unknown fields: {sorted(unknown)}")
    if missing:
        raise ContractError(f"{label} is missing fields: {sorted(missing)}")


def _require_domain_base(
    section: dict[str, Any], label: str, *, status_required: bool = True
) -> tuple[str, list[str], list[str]]:
    section = _require_object(section, label)
    missing = DOMAIN_BASE_KEYS - set(section)
    if missing:
        raise ContractError(f"{label} is missing fields: {sorted(missing)}")
    status = _require_status(section["status"], f"{label}.status")
    rationale = _require_text(section["rationale"], f"{label}.rationale")
    evidence_ids = _require_list_maybe_empty(section["evidence_ids"], f"{label}.evidence_ids")
    missing_information = _require_list_maybe_empty(
        section["missing_information"],
        f"{label}.missing_information",
    )
    if status in {"answered", "not_applicable"} and not evidence_ids:
        raise ContractError(
            f"{label}.evidence_ids must not be empty when status is {status}"
        )
    if status == "unresolved" and not missing_information:
        raise ContractError(
            f"{label}.missing_information must not be empty when status is unresolved"
        )
    if status_required and not rationale:
        raise ContractError(f"{label}.rationale must be non-empty")
    return status, evidence_ids, missing_information


def _validate_contribution_list(
    values: Any,
    label: str,
    claim_ids: set[str],
    domain_refs: set[str],
) -> list[dict[str, Any]]:
    contributions: list[dict[str, Any]] = []
    ids: set[str] = set()
    seen_claims: set[str] = set()
    for index, raw in enumerate(_require_list(values, label, nonempty=False)):
        item_label = f"{label}[{index}]"
        item = _require_object(raw, item_label)
        _require_keys(item, item_label, CONTRIBUTION_KEYS)
        contribution_id = _require_id(item["contribution_id"], f"{item_label}.contribution_id")
        if contribution_id in ids:
            raise ContractError("contribution IDs must be unique")
        ids.add(contribution_id)
        statement = _require_text(item["statement"], f"{item_label}.statement")
        raw_claim_ids = [
            _require_id(claim_id, f"{item_label}.claim_ids[{index}]")
            for index, claim_id in enumerate(_require_list(item["claim_ids"], f"{item_label}.claim_ids"))
        ]
        if not raw_claim_ids:
            raise ContractError(f"{item_label}.claim_ids must not be empty")
        raw_evidence = _require_list_maybe_empty(item["evidence_ids"], f"{item_label}.evidence_ids")
        raw_domain_refs = [
            _require_id(ref, f"{item_label}.domain_refs[{index}]")
            for index, ref in enumerate(_require_list(item["domain_refs"], f"{item_label}.domain_refs"))
        ]
        if not raw_domain_refs:
            raise ContractError(f"{item_label}.domain_refs must not be empty")
        for ref in raw_domain_refs:
            if ref not in domain_refs:
                raise ContractError(f"{item_label}.domain_refs references unknown domain target: {ref}")
        for claim_id in raw_claim_ids:
            if claim_id not in claim_ids:
                raise ContractError(f"{item_label}.claim_ids references unknown claim_id: {claim_id}")
            seen_claims.add(claim_id)
        contributions.append(
            {
                "contribution_id": contribution_id,
                "statement": statement,
                "claim_ids": raw_claim_ids,
                "evidence_ids": raw_evidence,
                "domain_refs": raw_domain_refs,
            }
        )
    _ = seen_claims
    return contributions


def _validate_source_binding(value: Any) -> dict[str, Any]:
    binding = _require_object(value, "source_binding")
    _require_keys(binding, "source_binding", SOURCE_BINDING_KEYS)
    source_artifact_sha256 = _require_sha256(
        binding["source_artifact_sha256"],
        "source_binding.source_artifact_sha256",
    )
    source_bundle_digest = _require_sha256(
        binding["source_bundle_digest"],
        "source_binding.source_bundle_digest",
    )
    source_bundle_id = _require_id(binding["source_bundle_id"], "source_binding.source_bundle_id")
    reading_dossier_id = _require_id(
        binding["reading_dossier_id"],
        "source_binding.reading_dossier_id",
    )
    reading_dossier_digest = _require_sha256(
        binding["reading_dossier_digest"],
        "source_binding.reading_dossier_digest",
    )

    reading_depth = _require_text(binding["reading_depth"], "source_binding.reading_depth")
    if reading_depth not in READER_ROUTE_VALUES:
        raise ContractError(f"source_binding.reading_depth must be one of {sorted(READER_ROUTE_VALUES)}")

    access_level = _require_text(binding["access_level"], "source_binding.access_level")
    if access_level not in ACCESS_LEVEL_VALUES:
        raise ContractError(f"source_binding.access_level must be one of {sorted(ACCESS_LEVEL_VALUES)}")

    _ = _require_id(binding["source_id"], "source_binding.source_id")
    canonical_title = _require_text(binding["canonical_title"], "source_binding.canonical_title")
    authors = [
        _require_text(item, f"source_binding.authors[{index}]")
        for index, item in enumerate(_require_list(binding["authors"], "source_binding.authors"))
    ]
    if not authors:
        raise ContractError("source_binding.authors must not be empty")
    year = binding["year"]
    if not isinstance(year, int) or not (1000 <= year <= 9999):
        raise ContractError("source_binding.year must be an int in range [1000, 9999]")
    verified_at = _require_timestamp(binding["verified_at"], "source_binding.verified_at")
    paper_card_ref = _require_id(binding["paper_card_ref"], "source_binding.paper_card_ref")
    evidence_ledger_ref = _require_id(
        binding["evidence_ledger_ref"],
        "source_binding.evidence_ledger_ref",
    )
    agent_inferences_explicit = _require_bool(
        binding["agent_inferences_explicit"],
        "source_binding.agent_inferences_explicit",
    )
    if not agent_inferences_explicit:
        raise ContractError("source_binding.agent_inferences_explicit must be true")

    return {
        "source_id": _require_id(binding["source_id"], "source_binding.source_id"),
        "canonical_title": canonical_title,
        "authors": authors,
        "year": year,
        "venue": _require_text(binding["venue"], "source_binding.venue"),
        "stable_identifier": _require_text(
            binding["stable_identifier"],
            "source_binding.stable_identifier",
        ),
        "publication_status": _require_text(
            binding["publication_status"],
            "source_binding.publication_status",
        ),
        "source_artifact_sha256": source_artifact_sha256,
        "source_bundle_id": source_bundle_id,
        "source_bundle_digest": source_bundle_digest,
        "reading_dossier_id": reading_dossier_id,
        "reading_dossier_digest": reading_dossier_digest,
        "paper_card_ref": paper_card_ref,
        "evidence_ledger_ref": evidence_ledger_ref,
        "agent_inferences_explicit": True,
        "reading_depth": reading_depth,
        "access_level": access_level,
        "verified_at": verified_at,
    }


def _validate_live_source_binding(
    source_binding: dict[str, Any],
    *,
    source_bundle_path: str,
    source_path: str,
    dossier_path: str,
) -> dict[str, Any]:
    verified_bundle = verify_source_bundle(
        bundle=source_bundle_path,
        source=source_path,
    )
    dossier_raw = _read_json(dossier_path)
    verified_dossier = validate_dossier(
        dossier_raw,
        bundle=source_bundle_path,
        source=source_path,
    )
    expected = {
        "source_artifact_sha256": verified_bundle["source"]["source_sha256"],
        "source_bundle_id": verified_bundle["bundle_id"],
        "source_bundle_digest": verified_bundle["bundle_digest"],
        "reading_dossier_id": verified_dossier["dossier_id"],
        "reading_dossier_digest": verified_dossier["dossier_digest"],
        "source_id": verified_dossier["review_source"]["source_id"],
        "reading_depth": verified_dossier["inspection_depth"],
        "access_level": verified_dossier["access_level"],
    }
    for field, expected_value in expected.items():
        if source_binding[field] != expected_value:
            raise ContractError(f"source_binding.{field} does not match verified dossier")

    dossier_bundle = verified_dossier["source_bundle"]
    if dossier_bundle["bundle_id"] != verified_bundle["bundle_id"]:
        raise ContractError("dossier source_bundle.bundle_id mismatch")
    if dossier_bundle["bundle_digest"] != verified_bundle["bundle_digest"]:
        raise ContractError("dossier source_bundle.bundle_digest mismatch")
    if dossier_bundle["source_artifact_sha256"] != verified_bundle["source"]["source_sha256"]:
        raise ContractError("dossier source_bundle.source_artifact_sha256 mismatch")
    return verified_dossier


def _validate_applicability(value: Any, claim_ids: set[str]) -> dict[str, Any]:
    section = _require_object(value, "applicability")
    _require_keys(section, "applicability", APPLICABILITY_KEYS)
    status, evidence_ids, missing = _require_domain_base(section, "applicability")
    primary_use_case = _require_text(section["primary_use_case"], "applicability.primary_use_case")
    applies_when = [
        _require_text(item, f"applicability.applies_when[{index}]")
        for index, item in enumerate(_require_list(section["applies_when"], "applicability.applies_when"))
    ]
    if not applies_when:
        raise ContractError("applicability.applies_when must not be empty")
    does_not_apply_when = [
        _require_text(item, f"applicability.does_not_apply_when[{index}]")
        for index, item in enumerate(
            _require_list_maybe_empty(
                section["does_not_apply_when"],
                "applicability.does_not_apply_when",
            )
        )
    ]
    section_claim_ids = []
    for index, claim_id in enumerate(_require_list(section["claim_ids"], "applicability.claim_ids")):
        claim_ref = _require_id(claim_id, f"applicability.claim_ids[{index}]")
        if claim_ref not in claim_ids:
            raise ContractError(f"applicability.claim_ids references unknown claim_id: {claim_ref}")
        section_claim_ids.append(claim_ref)
    return {
        "status": status,
        "rationale": section["rationale"],
        "evidence_ids": evidence_ids,
        "missing_information": missing,
        "primary_use_case": primary_use_case,
        "applies_when": applies_when,
        "does_not_apply_when": does_not_apply_when,
        "claim_ids": section_claim_ids,
    }


def _validate_graph(value: Any, label: str) -> dict[str, Any]:
    graph = _require_object(value, f"{label}.graph")
    _require_keys(graph, f"{label}.graph", GRAPH_KEYS)
    nodes_raw = _require_list(graph["nodes"], f"{label}.graph.nodes")
    operations_raw = _require_list(graph["operations"], f"{label}.graph.operations")

    nodes: dict[str, dict[str, Any]] = {}
    input_nodes: list[str] = []
    output_nodes: list[str] = []
    produced_count: dict[str, int] = {}
    consumed_count: dict[str, int] = {}
    for index, raw_node in enumerate(nodes_raw):
        node_label = f"{label}.graph.nodes[{index}]"
        node = _require_object(raw_node, node_label)
        _require_keys(node, node_label, GRAPH_NODE_KEYS)
        node_id = _require_id(node["node_id"], f"{node_label}.node_id")
        if node_id in nodes:
            raise ContractError(f"{node_label}.node_id is duplicated")
        kind = _require_text(node["kind"], f"{node_label}.kind")
        if kind not in WORKFLOW_NODE_KIND_VALUES:
            raise ContractError(
                f"{node_label}.kind must be input, intermediate, or output"
            )
        produced_count[node_id] = 0
        consumed_count[node_id] = 0
        if kind == "input":
            input_nodes.append(node_id)
        if kind == "output":
            output_nodes.append(node_id)
        _require_text(node["semantic_type"], f"{node_label}.semantic_type")
        _require_text(node["representation"], f"{node_label}.representation")
        node_desc = _require_text(node["description"], f"{node_label}.description")
        nodes[node_id] = {
            "node_id": node_id,
            "kind": kind,
            "semantic_type": node["semantic_type"],
            "representation": node["representation"],
            "description": node_desc,
            "format": _require_text(node["format"], f"{node_label}.format"),
            "shape": _require_text(node["shape"], f"{node_label}.shape"),
            "unit": _require_text(node["unit"], f"{node_label}.unit"),
        }

    operations: list[dict[str, Any]] = []
    operation_ids: set[str] = set()
    node_refs = set(nodes)
    node_usage: set[str] = set()
    for index, raw_operation in enumerate(operations_raw):
        operation_label = f"{label}.graph.operations[{index}]"
        operation = _require_object(raw_operation, operation_label)
        _require_keys(operation, operation_label, GRAPH_OPERATION_KEYS)
        operation_id = _require_id(operation["operation_id"], f"{operation_label}.operation_id")
        if operation_id in operation_ids:
            raise ContractError(f"{operation_label}.operation_id is duplicated")
        operation_ids.add(operation_id)
        consumes = [
            _require_text(item, f"{operation_label}.consumes[{index}]")
            for index, item in enumerate(_require_list(operation["consumes"], f"{operation_label}.consumes"))
        ]
        produces = [
            _require_text(item, f"{operation_label}.produces[{index}]")
            for index, item in enumerate(_require_list(operation["produces"], f"{operation_label}.produces"))
        ]
        if not consumes or not produces:
            raise ContractError(f"{operation_label} must have non-empty consumes and produces")
        for node_id in consumes + produces:
            if node_id not in node_refs:
                raise ContractError(f"{operation_label} references unknown node: {node_id}")
            node_usage.add(node_id)
        operation_name = _require_text(operation["operation"], f"{operation_label}.operation")
        operations.append(
            {
                "operation_id": operation_id,
                "operation": operation_name,
                "consumes": consumes,
                "produces": produces,
            }
        )
        for node_id in consumes:
            consumed_count[node_id] += 1
            node_usage.add(node_id)
        for node_id in produces:
            produced_count[node_id] += 1
            node_usage.add(node_id)

    if not input_nodes:
        raise ContractError("workflow.graph must include at least one input node")
    if not output_nodes:
        raise ContractError("workflow.graph must include at least one output node")

    for node_id, node in nodes.items():
        produced = produced_count[node_id]
        consumed = consumed_count[node_id]
        if node["kind"] == "input" and (produced != 0 or consumed == 0):
            raise ContractError(
                f"workflow.graph input node {node_id} must be consumed and never produced"
            )
        if node["kind"] == "intermediate" and (produced == 0 or consumed == 0):
            raise ContractError(
                f"workflow.graph intermediate node {node_id} must be produced and consumed"
            )
        if node["kind"] == "output" and (produced == 0 or consumed != 0):
            raise ContractError(
                f"workflow.graph output node {node_id} must be produced and never consumed"
            )

    return {
        "nodes": list(nodes.values()),
        "operations": operations,
    }


def _validate_workflow(value: Any, claim_ids: set[str]) -> dict[str, Any]:
    section = _require_object(value, "workflow")
    _require_keys(section, "workflow", WORKFLOW_KEYS)
    status, evidence_ids, missing = _require_domain_base(section, "workflow")
    inputs = _require_list_maybe_empty(section["inputs"], "workflow.inputs")
    preconditions = _require_list_maybe_empty(section["preconditions"], "workflow.preconditions")
    outputs = _require_list_maybe_empty(section["outputs"], "workflow.outputs")
    data_flow = _require_list_maybe_empty(section["data_flow"], "workflow.data_flow")
    if status == "answered":
        if not inputs or not outputs:
            raise ContractError("workflow with answered status needs inputs and outputs")
    raw_steps = _require_list(section["steps"], "workflow.steps", nonempty=False)
    steps: list[dict[str, Any]] = []
    seen_steps: set[str] = set()
    for index, raw_step in enumerate(raw_steps):
        step_label = f"workflow.steps[{index}]"
        step = _require_object(raw_step, step_label)
        _require_keys(step, step_label, WORKFLOW_STEP_KEYS)
        step_id = _require_id(step["step_id"], f"{step_label}.step_id")
        if step_id in seen_steps:
            raise ContractError(f"{step_label}.step_id must be unique")
        seen_steps.add(step_id)
        checks = _require_list_maybe_empty(step["checks"], f"{step_label}.checks")
        steps.append(
            {
                "step_id": step_id,
                "action": _require_text(step["action"], f"{step_label}.action"),
                "output": _require_text(step["output"], f"{step_label}.output"),
                "checks": checks,
            }
        )

    graph = _validate_graph(section["graph"], "workflow")

    return {
        "status": status,
        "rationale": section["rationale"],
        "evidence_ids": evidence_ids,
        "missing_information": missing,
        "inputs": inputs,
        "preconditions": preconditions,
        "steps": steps,
        "outputs": outputs,
        "data_flow": data_flow,
        "graph": graph,
    }


def _validate_mathematical_principles(value: Any, claim_ids: set[str]) -> dict[str, Any]:
    section = _require_object(value, "mathematical_principles")
    _require_keys(section, "mathematical_principles", MATH_KEYS)
    status, evidence_ids, missing = _require_domain_base(section, "mathematical_principles")
    assumptions = _require_list_maybe_empty(section["assumptions"], "mathematical_principles.assumptions")
    results = _require_list_maybe_empty(section["results"], "mathematical_principles.results")
    derivation_steps = _validate_derivation_steps(
        section["derivation_steps"],
        "mathematical_principles.derivation_steps",
        prior_assumptions=set(assumptions),
        declared_results=set(results),
    )

    principles_raw = _require_list(section["principles"], "mathematical_principles.principles", nonempty=False)
    principles: list[dict[str, Any]] = []
    seen_principles: set[str] = set()
    for index, raw in enumerate(principles_raw):
        label = f"mathematical_principles.principles[{index}]"
        item = _require_object(raw, label)
        _require_keys(item, label, MATH_PRINCIPLE_KEYS)
        principle_id = _require_id(item["principle_id"], f"{label}.principle_id")
        if principle_id in seen_principles:
            raise ContractError("mathematical_principles.principles.principle_id must be unique")
        seen_principles.add(principle_id)
        symbols = _require_list_maybe_empty(item["symbols"], f"{label}.symbols")
        p_assumptions = _require_list_maybe_empty(item["assumptions"], f"{label}.assumptions")
        p_results = _require_list_maybe_empty(item["results"], f"{label}.results")
        p_derivation_steps = _validate_derivation_steps(
            item["derivation_steps"],
            f"{label}.derivation_steps",
            prior_assumptions=set(assumptions) | set(p_assumptions),
            declared_results=set(results) | set(p_results),
        )
        origin = _require_origin(item["origin"], f"{label}.origin")
        p_claims = []
        for claim_index, claim_id in enumerate(_require_list(item["claim_ids"], f"{label}.claim_ids")):
            cid = _require_id(claim_id, f"{label}.claim_ids[{claim_index}]")
            if cid not in claim_ids:
                raise ContractError(f"{label}.claim_ids references unknown claim_id: {cid}")
            p_claims.append(cid)
        if not p_claims:
            raise ContractError(f"{label}.claim_ids must not be empty")
        principles.append(
            {
                "principle_id": principle_id,
                "statement": _require_text(item["statement"], f"{label}.statement"),
                "latex": _require_text(item["latex"], f"{label}.latex"),
                "symbols": symbols,
                "assumptions": p_assumptions,
                "derivation_steps": p_derivation_steps,
                "results": p_results,
                "origin": origin,
                "locator": _require_text(item["locator"], f"{label}.locator"),
                "claim_ids": p_claims,
            }
        )

    if status == "answered" and not principles:
        raise ContractError("mathematical_principles.principles must be non-empty when answered")
    if status == "not_applicable" and any(
        (assumptions, derivation_steps, results, principles)
    ):
        raise ContractError(
            "mathematical_principles marked not_applicable must not contain placeholder math"
        )

    return {
        "status": status,
        "rationale": section["rationale"],
        "evidence_ids": evidence_ids,
        "missing_information": missing,
        "assumptions": assumptions,
        "derivation_steps": derivation_steps,
        "results": results,
        "principles": principles,
    }


def _validate_algorithmic_principles(value: Any, claim_ids: set[str]) -> dict[str, Any]:
    section = _require_object(value, "algorithmic_principles")
    _require_keys(section, "algorithmic_principles", ALGO_KEYS)
    status, evidence_ids, missing = _require_domain_base(section, "algorithmic_principles")
    objective = _require_text(section["objective"], "algorithmic_principles.objective")
    state_variables = _require_list_maybe_empty(
        section["state_variables"], "algorithmic_principles.state_variables"
    )
    raw_ordered_steps = _require_list(section["ordered_steps"], "algorithmic_principles.ordered_steps", nonempty=False)
    ordered_steps: list[dict[str, Any]] = []
    ordered_step_ids: set[str] = set()
    for index, raw_step in enumerate(raw_ordered_steps):
        step_label = f"algorithmic_principles.ordered_steps[{index}]"
        step = _require_object(raw_step, step_label)
        _require_keys(step, step_label, ALGO_ORDERED_STEP_KEYS)
        step_id = _require_id(step["step_id"], f"{step_label}.step_id")
        if step_id in ordered_step_ids:
            raise ContractError("algorithmic_principles.ordered_steps.step_id must be unique")
        depends_on = _validate_ordered_step_dependencies(
            step["depends_on"],
            f"{step_label}.depends_on",
            prior_step_ids=ordered_step_ids,
        )
        ordered_steps.append(
            {
                "step_id": step_id,
                "action": _require_text(step["action"], f"{step_label}.action"),
                "depends_on": depends_on,
                "consumes": _require_list_maybe_empty(step["consumes"], f"{step_label}.consumes"),
                "produces": _require_list_maybe_empty(step["produces"], f"{step_label}.produces"),
                "origin": _require_origin(step["origin"], f"{step_label}.origin"),
                "locator": _require_text(step["locator"], f"{step_label}.locator"),
                "evidence_ids": _require_list_maybe_empty(
                    step["evidence_ids"], f"{step_label}.evidence_ids"
                ),
            }
        )
        ordered_step_ids.add(step_id)
    invariants = _require_list_maybe_empty(section["invariants"], "algorithmic_principles.invariants")
    failure_modes = _require_list_maybe_empty(
        section["failure_modes"], "algorithmic_principles.failure_modes"
    )

    algorithms_raw = _require_list(section["algorithms"], "algorithmic_principles.algorithms", nonempty=False)
    algorithms: list[dict[str, Any]] = []
    seen_algorithms: set[str] = set()
    for index, raw in enumerate(algorithms_raw):
        label = f"algorithmic_principles.algorithms[{index}]"
        item = _require_object(raw, label)
        _require_keys(item, label, ALGO_ITEM_KEYS)
        algorithm_id = _require_id(item["algorithm_id"], f"{label}.algorithm_id")
        if algorithm_id in seen_algorithms:
            raise ContractError("algorithmic_principles.algorithms.algorithm_id must be unique")
        seen_algorithms.add(algorithm_id)
        claim_refs = []
        for claim_index, claim_id in enumerate(_require_list(item["claim_ids"], f"{label}.claim_ids")):
            cid = _require_id(claim_id, f"{label}.claim_ids[{claim_index}]")
            if cid not in claim_ids:
                raise ContractError(f"{label}.claim_ids references unknown claim_id: {cid}")
            claim_refs.append(cid)
        if not claim_refs:
            raise ContractError(f"{label}.claim_ids must not be empty")
        numerical_risks = [
            _require_text(item, f"{label}.numerical_risks[{risk_index}]")
            for risk_index, item in enumerate(
                _require_list(item["numerical_risks"], f"{label}.numerical_risks", nonempty=False)
            )
        ]
        raw_algorithm_steps = _require_list(
            item["ordered_steps"], f"{label}.ordered_steps", nonempty=True
        )
        algorithm_steps: list[dict[str, Any]] = []
        algorithm_step_ids: set[str] = set()
        for step_index, raw_algorithm_step in enumerate(raw_algorithm_steps):
            step_label = f"{label}.ordered_steps[{step_index}]"
            algo_step = _require_object(raw_algorithm_step, step_label)
            _require_keys(algo_step, step_label, ALGO_ORDERED_STEP_KEYS)
            step_id = _require_id(algo_step["step_id"], f"{step_label}.step_id")
            if step_id in algorithm_step_ids:
                raise ContractError(f"{step_label}.step_id is duplicated")
            depends_on = _validate_ordered_step_dependencies(
                algo_step["depends_on"],
                f"{step_label}.depends_on",
                prior_step_ids=algorithm_step_ids,
            )
            algorithm_steps.append(
                {
                    "step_id": step_id,
                    "action": _require_text(algo_step["action"], f"{step_label}.action"),
                    "depends_on": depends_on,
                    "consumes": _require_list_maybe_empty(
                        algo_step["consumes"], f"{step_label}.consumes"
                    ),
                    "produces": _require_list_maybe_empty(
                        algo_step["produces"], f"{step_label}.produces"
                    ),
                    "origin": _require_origin(algo_step["origin"], f"{step_label}.origin"),
                    "locator": _require_text(algo_step["locator"], f"{step_label}.locator"),
                    "evidence_ids": _require_list_maybe_empty(
                        algo_step["evidence_ids"], f"{step_label}.evidence_ids"
                    ),
                }
            )
            algorithm_step_ids.add(step_id)
        _require_origin(item["origin"], f"{label}.origin")
        algorithms.append(
            {
                "algorithm_id": algorithm_id,
                "name": _require_text(item["name"], f"{label}.name"),
                "inputs": _require_list_maybe_empty(item["inputs"], f"{label}.inputs"),
                "outputs": _require_list_maybe_empty(item["outputs"], f"{label}.outputs"),
                "initialization": _require_text(item["initialization"], f"{label}.initialization"),
                "ordered_steps": algorithm_steps,
                "update_rule": _require_text(item["update_rule"], f"{label}.update_rule"),
                "stopping_condition": _require_text(item["stopping_condition"], f"{label}.stopping_condition"),
                "complexity": _require_text(item["complexity"], f"{label}.complexity"),
                "numerical_risks": numerical_risks,
                "locator": _require_text(item["locator"], f"{label}.locator"),
                "claim_ids": claim_refs,
                "origin": item["origin"],
            }
        )

    if status == "answered" and not algorithms:
        raise ContractError("algorithmic_principles.algorithms must be non-empty when answered")
    if status == "answered" and not ordered_steps:
        raise ContractError(
            "algorithmic_principles.ordered_steps must be non-empty when answered"
        )

    return {
        "status": status,
        "rationale": section["rationale"],
        "evidence_ids": evidence_ids,
        "missing_information": missing,
        "objective": objective,
        "state_variables": state_variables,
        "ordered_steps": ordered_steps,
        "invariants": invariants,
        "failure_modes": failure_modes,
        "algorithms": algorithms,
    }


def _validate_conclusion(value: Any, claim_ids: set[str]) -> dict[str, Any]:
    section = _require_object(value, "conclusion")
    _require_keys(section, "conclusion", CONCLUSION_KEYS)
    status, evidence_ids, missing = _require_domain_base(section, "conclusion")
    statement = _require_text(section["statement"], "conclusion.statement")
    confidence = _require_text(section["confidence"], "conclusion.confidence")
    confidence_rationale = _require_text(section["confidence_rationale"], "conclusion.confidence_rationale")
    section_claim_ids = []
    for index, claim_id in enumerate(_require_list(section["claim_ids"], "conclusion.claim_ids")):
        cid = _require_id(claim_id, f"conclusion.claim_ids[{index}]")
        if cid not in claim_ids:
            raise ContractError(f"conclusion.claim_ids references unknown claim_id: {cid}")
        section_claim_ids.append(cid)

    if status == "answered" and not section_claim_ids:
        raise ContractError("conclusion.claim_ids must not be empty when answered")

    return {
        "status": status,
        "rationale": section["rationale"],
        "evidence_ids": evidence_ids,
        "missing_information": missing,
        "statement": statement,
        "confidence": confidence,
        "confidence_rationale": confidence_rationale,
        "claim_ids": section_claim_ids,
    }


def _validate_claims(value: Any, label: str) -> list[dict[str, Any]]:
    claims_raw = _require_list(value, label, nonempty=True)
    claims: list[dict[str, Any]] = []
    claim_ids: set[str] = set()
    for index, raw_claim in enumerate(claims_raw):
        claim_label = f"claims[{index}]"
        claim = _require_object(raw_claim, claim_label)
        _require_keys(claim, claim_label, CLAIM_KEYS)
        claim_id = _require_id(claim["claim_id"], f"{claim_label}.claim_id")
        if claim_id in claim_ids:
            raise ContractError("claim_id must be unique")
        claim_ids.add(claim_id)

        hypothesis_id = _require_id(claim["hypothesis_id"], f"{claim_label}.hypothesis_id")
        target_id = _require_id(claim["target_id"], f"{claim_label}.target_id")
        relation = _require_text(claim["relation"], f"{claim_label}.relation")
        if relation not in RELATION_VALUES:
            raise ContractError(f"{claim_label}.relation must be one of: {sorted(RELATION_VALUES)}")
        nature = _require_text(claim["nature"], f"{claim_label}.nature")
        if nature not in NATURE_VALUES:
            raise ContractError(f"{claim_label}.nature must be one of: {sorted(NATURE_VALUES)}")
        scope = _require_scope(claim["scope"], f"{claim_label}.scope")
        status = _require_text(claim["status"], f"{claim_label}.status")
        if status not in CLAIM_STATUS_VALUES:
            raise ContractError(f"{claim_label}.status must be answered or terminal")
        verifier_status = _require_text(claim["verifier_status"], f"{claim_label}.verifier_status")
        confidence = _require_text(claim["confidence"], f"{claim_label}.confidence")
        evidence_ids = [
            _require_text(item, f"{claim_label}.evidence_ids[{evidence_index}]")
            for evidence_index, item in enumerate(
                _require_list(claim["evidence_ids"], f"{claim_label}.evidence_ids", nonempty=False)
            )
        ]
        evidence = [
            _validate_claim_evidence(item, f"{claim_label}.evidence[{evidence_index}]")
            for evidence_index, item in enumerate(
                _require_list(claim["evidence"], f"{claim_label}.evidence", nonempty=False)
            )
        ]
        claims.append(
            {
                "claim_id": claim_id,
                "hypothesis_id": hypothesis_id,
                "target_id": target_id,
                "statement": _require_text(claim["statement"], f"{claim_label}.statement"),
                "relation": relation,
                "nature": nature,
                "scope": scope,
                "evidence_ids": evidence_ids,
                "evidence": evidence,
                "verifier_status": verifier_status,
                "confidence": confidence,
                "confidence_rationale": _require_text(
                    claim["confidence_rationale"],
                    f"{claim_label}.confidence_rationale",
                ),
                "status": status,
            }
        )
    return claims


def _validate_claim_evidence(value: Any, label: str) -> dict[str, str]:
    evidence = _require_object(value, label)
    _require_keys(evidence, label, EVIDENCE_ITEM_KEYS)
    evidence_id = _require_id(evidence["evidence_id"], f"{label}.evidence_id")
    summary = _require_text(evidence["summary"], f"{label}.summary")
    locator = _require_text(evidence["locator"], f"{label}.locator")
    return {
        "evidence_id": evidence_id,
        "summary": summary,
        "locator": locator,
    }


def _validate_coverage(value: Any, claim_ids: set[str]) -> dict[str, Any]:
    coverage = _require_object(value, "coverage")
    _require_keys(coverage, "coverage", COVERAGE_KEYS)
    understood_raw = _require_list(
        coverage["understood_claims"], "coverage.understood_claims", nonempty=False
    )
    terminal_raw = _require_list(
        coverage["terminal_claims"], "coverage.terminal_claims", nonempty=False
    )

    understood = _validate_coverage_claims(understood_raw, "coverage.understood_claims")
    terminal = _validate_coverage_claims(terminal_raw, "coverage.terminal_claims")

    understood_ids = {entry["claim_id"] for entry in understood}
    terminal_ids = {entry["claim_id"] for entry in terminal}
    if understood_ids.intersection(terminal_ids):
        overlap = sorted(understood_ids.intersection(terminal_ids))
        raise ContractError(f"coverage claim ids must be disjoint: {overlap}")

    all_cov = understood_ids | terminal_ids
    if all_cov != claim_ids:
        missing = sorted(claim_ids - all_cov)
        extra = sorted(all_cov - claim_ids)
        if missing:
            raise ContractError(f"coverage is missing claims: {missing}")
        if extra:
            raise ContractError(f"coverage references unknown claims: {extra}")

    return {
        "understood_claims": understood,
        "terminal_claims": terminal,
    }


def _validate_coverage_claims(raw: list[Any], label: str) -> list[dict[str, str]]:
    normalized: list[dict[str, str]] = []
    ids: set[str] = set()
    for index, item in enumerate(raw):
        item_label = f"{label}[{index}]"
        entry = _require_object(item, item_label)
        _require_keys(entry, item_label, COVERAGE_CLAIM_KEYS)
        claim_id = _require_id(entry["claim_id"], f"{item_label}.claim_id")
        if claim_id in ids:
            raise ContractError(f"{label} claim_id must be unique")
        ids.add(claim_id)
        normalized.append(
            {
                "claim_id": claim_id,
                "reason": _require_text(entry["reason"], f"{item_label}.reason"),
            }
        )
    return normalized


def _validate_executive_summary(value: Any, known_claim_ids: set[str]) -> tuple[dict[str, Any], str]:
    summary = _require_object(value, "executive_summary")
    _require_keys(summary, "executive_summary", EXECUTIVE_KEYS)
    applicability_short = _require_text(summary["applicability_short"], "executive_summary.applicability_short")
    conclusion_short = _require_text(summary["conclusion_short"], "executive_summary.conclusion_short")
    claim_ids = [
        _require_id(item, f"executive_summary.claim_ids[{index}")
        for index, item in enumerate(_require_list(summary["claim_ids"], "executive_summary.claim_ids"))
    ]
    if not claim_ids:
        raise ContractError("executive_summary.claim_ids must not be empty")
    for claim_id in claim_ids:
        if claim_id not in known_claim_ids:
            raise ContractError(
                f"executive_summary.claim_ids references unknown claim_id: {claim_id}"
            )

    retrieved = f"适用：{applicability_short}｜结论：{conclusion_short}"
    summary_copy = {
        "summary": _require_text(summary["summary"], "executive_summary.summary"),
        "applicability_short": applicability_short,
        "conclusion_short": conclusion_short,
        "claim_ids": claim_ids,
    }
    return summary_copy, retrieved


def _understanding_evidence_registry(
    claims: list[dict[str, Any]],
) -> dict[str, dict[str, str]]:
    registry: dict[str, dict[str, str]] = {}
    for claim_index, claim in enumerate(claims):
        evidence_ids = claim["evidence_ids"]
        row_ids = [row["evidence_id"] for row in claim["evidence"]]
        if len(evidence_ids) != len(set(evidence_ids)):
            raise ContractError(
                f"claims[{claim_index}].evidence_ids must not contain duplicates"
            )
        if len(row_ids) != len(set(row_ids)):
            raise ContractError(
                f"claims[{claim_index}].evidence must not contain duplicate evidence_id"
            )
        if row_ids != evidence_ids:
            raise ContractError(
                f"claims[{claim_index}].evidence rows must exactly match evidence_ids"
            )
        for row in claim["evidence"]:
            evidence_id_value = row["evidence_id"]
            if evidence_id_value in registry:
                raise ContractError(
                    f"evidence_id {evidence_id_value} is repeated across understanding claims"
                )
            registry[evidence_id_value] = {
                "claim_id": claim["claim_id"],
                "locator": row["locator"],
            }
    return registry


def _validate_evidence_refs(
    evidence_ids: list[str],
    label: str,
    registry: dict[str, dict[str, str]],
    *,
    allowed_claim_ids: set[str] | None = None,
) -> list[dict[str, str]]:
    if len(evidence_ids) != len(set(evidence_ids)):
        raise ContractError(f"{label} must not contain duplicate evidence_id")
    resolved: list[dict[str, str]] = []
    for evidence_id_value in evidence_ids:
        target = registry.get(evidence_id_value)
        if target is None:
            raise ContractError(
                f"{label} references unknown authoritative evidence_id: "
                f"{evidence_id_value}"
            )
        if (
            allowed_claim_ids is not None
            and target["claim_id"] not in allowed_claim_ids
        ):
            raise ContractError(
                f"{label} evidence {evidence_id_value} is not bound to a referenced claim"
            )
        resolved.append(target)
    return resolved


def _validate_authoritative_locator(
    locator: str,
    label: str,
    registry: dict[str, dict[str, str]],
    *,
    resolved_evidence: list[dict[str, str]] | None = None,
    allowed_claim_ids: set[str] | None = None,
) -> None:
    candidates = resolved_evidence
    if not candidates:
        candidates = [
            row
            for row in registry.values()
            if allowed_claim_ids is None or row["claim_id"] in allowed_claim_ids
        ]
    if locator not in {row["locator"] for row in candidates}:
        raise ContractError(
            f"{label} does not match an authoritative dossier/source locator"
        )


def _validate_evidence_reference_closure(
    *,
    registry: dict[str, dict[str, str]],
    applicability: dict[str, Any],
    workflow: dict[str, Any],
    mathematical: dict[str, Any],
    algorithmic: dict[str, Any],
    conclusion: dict[str, Any],
    contributions: list[dict[str, Any]],
    validate_locators: bool,
) -> None:
    _validate_evidence_refs(
        applicability["evidence_ids"],
        "applicability.evidence_ids",
        registry,
        allowed_claim_ids=set(applicability["claim_ids"]),
    )
    _validate_evidence_refs(workflow["evidence_ids"], "workflow.evidence_ids", registry)
    _validate_evidence_refs(
        mathematical["evidence_ids"],
        "mathematical_principles.evidence_ids",
        registry,
    )
    _validate_evidence_refs(
        algorithmic["evidence_ids"],
        "algorithmic_principles.evidence_ids",
        registry,
    )
    _validate_evidence_refs(
        conclusion["evidence_ids"],
        "conclusion.evidence_ids",
        registry,
        allowed_claim_ids=set(conclusion["claim_ids"]),
    )

    for index, contribution in enumerate(contributions):
        _validate_evidence_refs(
            contribution["evidence_ids"],
            f"contributions[{index}].evidence_ids",
            registry,
            allowed_claim_ids=set(contribution["claim_ids"]),
        )

    for index, step in enumerate(mathematical["derivation_steps"]):
        resolved = _validate_evidence_refs(
            step["evidence_ids"],
            f"mathematical_principles.derivation_steps[{index}].evidence_ids",
            registry,
        )
        if validate_locators:
            _validate_authoritative_locator(
                step["locator"],
                f"mathematical_principles.derivation_steps[{index}].locator",
                registry,
                resolved_evidence=resolved,
            )

    for principle_index, principle in enumerate(mathematical["principles"]):
        principle_claim_ids = set(principle["claim_ids"])
        if validate_locators:
            _validate_authoritative_locator(
                principle["locator"],
                f"mathematical_principles.principles[{principle_index}].locator",
                registry,
                allowed_claim_ids=principle_claim_ids,
            )
        for step_index, step in enumerate(principle["derivation_steps"]):
            label = (
                f"mathematical_principles.principles[{principle_index}]"
                f".derivation_steps[{step_index}]"
            )
            resolved = _validate_evidence_refs(
                step["evidence_ids"],
                f"{label}.evidence_ids",
                registry,
                allowed_claim_ids=principle_claim_ids,
            )
            if validate_locators:
                _validate_authoritative_locator(
                    step["locator"],
                    f"{label}.locator",
                    registry,
                    resolved_evidence=resolved,
                    allowed_claim_ids=principle_claim_ids,
                )

    for index, step in enumerate(algorithmic["ordered_steps"]):
        resolved = _validate_evidence_refs(
            step["evidence_ids"],
            f"algorithmic_principles.ordered_steps[{index}].evidence_ids",
            registry,
        )
        if validate_locators:
            _validate_authoritative_locator(
                step["locator"],
                f"algorithmic_principles.ordered_steps[{index}].locator",
                registry,
                resolved_evidence=resolved,
            )

    for algorithm_index, algorithm in enumerate(algorithmic["algorithms"]):
        algorithm_claim_ids = set(algorithm["claim_ids"])
        if validate_locators:
            _validate_authoritative_locator(
                algorithm["locator"],
                f"algorithmic_principles.algorithms[{algorithm_index}].locator",
                registry,
                allowed_claim_ids=algorithm_claim_ids,
            )
        for step_index, step in enumerate(algorithm["ordered_steps"]):
            label = (
                f"algorithmic_principles.algorithms[{algorithm_index}]"
                f".ordered_steps[{step_index}]"
            )
            resolved = _validate_evidence_refs(
                step["evidence_ids"],
                f"{label}.evidence_ids",
                registry,
                allowed_claim_ids=algorithm_claim_ids,
            )
            if validate_locators:
                _validate_authoritative_locator(
                    step["locator"],
                    f"{label}.locator",
                    registry,
                    resolved_evidence=resolved,
                    allowed_claim_ids=algorithm_claim_ids,
                )


def _validate_against_authoritative_dossier(
    claims: list[dict[str, Any]],
    dossier: dict[str, Any],
    *,
    applicability: dict[str, Any],
    workflow: dict[str, Any],
    mathematical: dict[str, Any],
    algorithmic: dict[str, Any],
    conclusion: dict[str, Any],
    contributions: list[dict[str, Any]],
) -> None:
    dossier_claims = {row["claim_id"]: row for row in dossier["claims"]}
    dossier_evidence = {
        row["evidence_id"]: row for row in dossier["evidence_records"]
    }
    registry = {
        evidence_id_value: {
            "claim_id": row["claim_id"],
            "locator": row["exact_locator"],
        }
        for evidence_id_value, row in dossier_evidence.items()
    }
    exact_claim_fields = (
        "hypothesis_id",
        "target_id",
        "statement",
        "relation",
        "scope",
        "verifier_status",
        "confidence",
    )
    for index, claim in enumerate(claims):
        dossier_claim = dossier_claims.get(claim["claim_id"])
        if dossier_claim is None:
            raise ContractError(
                f"claims[{index}].claim_id is absent from authoritative dossier"
            )
        for field in exact_claim_fields:
            if claim[field] != dossier_claim[field]:
                raise ContractError(
                    f"claims[{index}].{field} does not match authoritative dossier claim"
                )
        expected_nature = DOSSIER_NATURE_BY_ORIGIN[dossier_claim["origin"]]
        if claim["nature"] != expected_nature:
            raise ContractError(
                f"claims[{index}].nature does not match authoritative dossier origin"
            )
        expected_status = (
            "answered"
            if dossier["claim_support_eligible"][claim["claim_id"]]
            else "terminal"
        )
        if claim["status"] != expected_status:
            raise ContractError(
                f"claims[{index}].status does not match dossier support eligibility"
            )
        if claim["evidence_ids"] != dossier_claim["evidence_ids"]:
            raise ContractError(
                f"claims[{index}].evidence_ids do not exactly match dossier claim"
            )
        for evidence_index, evidence_row in enumerate(claim["evidence"]):
            dossier_row = dossier_evidence.get(evidence_row["evidence_id"])
            if dossier_row is None or dossier_row["claim_id"] != claim["claim_id"]:
                raise ContractError(
                    f"claims[{index}].evidence[{evidence_index}] does not resolve "
                    "to the bound dossier evidence record"
                )
            if evidence_row["summary"] != dossier_claim["statement"]:
                raise ContractError(
                    f"claims[{index}].evidence[{evidence_index}].summary must equal "
                    "the authoritative dossier claim statement"
                )
            if evidence_row["locator"] != dossier_row["exact_locator"]:
                raise ContractError(
                    f"claims[{index}].evidence[{evidence_index}].locator does not "
                    "match the source-rooted dossier locator"
                )

    _validate_evidence_reference_closure(
        registry=registry,
        applicability=applicability,
        workflow=workflow,
        mathematical=mathematical,
        algorithmic=algorithmic,
        conclusion=conclusion,
        contributions=contributions,
        validate_locators=True,
    )


def validate_understanding(
    raw: Any,
    *,
    require_identity: bool = True,
    source_bundle_path: str | None = None,
    source_path: str | None = None,
    dossier_path: str | None = None,
) -> dict[str, Any]:
    artifact = _require_object(raw, "root")
    required_top_level_keys = set(TOP_LEVEL_KEYS)
    if not require_identity:
        required_top_level_keys -= {"understanding_id", "understanding_digest"}
    _require_keys(artifact, "root", required_top_level_keys)

    if artifact["schema"] != SCHEMA:
        raise ContractError(f"schema must be {SCHEMA}")
    if artifact["schema_version"] != SCHEMA_VERSION:
        raise ContractError(f"schema_version must be {SCHEMA_VERSION}")
    if artifact["producer"] != PRODUCER:
        raise ContractError(f"producer must be {PRODUCER}")
    if artifact["protocol_version"] != PROTOCOL_VERSION:
        raise ContractError(f"protocol_version must be {PROTOCOL_VERSION}")
    generated_at = _require_timestamp(artifact["generated_at"], "generated_at")

    source_binding = _validate_source_binding(artifact["source_binding"])
    verification_paths = (source_bundle_path, source_path, dossier_path)
    if any(verification_paths) and not all(verification_paths):
        raise ContractError("source, bundle, and dossier must be provided together")
    verified_dossier: dict[str, Any] | None = None
    if all(verification_paths):
        verified_dossier = _validate_live_source_binding(
            source_binding,
            source_bundle_path=str(source_bundle_path),
            source_path=str(source_path),
            dossier_path=str(dossier_path),
        )

    claims = _validate_claims(artifact["claims"], "claims")
    claim_ids = {claim["claim_id"] for claim in claims}

    if not claim_ids:
        raise ContractError("claims must not be empty")

    executive_summary, retrieval_title = _validate_executive_summary(
        artifact["executive_summary"], claim_ids
    )
    provided_title = _require_text(
        artifact["research_retrieval_title"], "research_retrieval_title"
    )
    if provided_title != retrieval_title:
        raise ContractError("research_retrieval_title must equal required formula")

    applicability = _validate_applicability(artifact["applicability"], claim_ids)
    workflow = _validate_workflow(artifact["workflow"], claim_ids)
    mathematical_principles = _validate_mathematical_principles(
        artifact["mathematical_principles"], claim_ids
    )
    algorithmic_principles = _validate_algorithmic_principles(
        artifact["algorithmic_principles"], claim_ids
    )
    conclusion = _validate_conclusion(artifact["conclusion"], claim_ids)
    coverage = _validate_coverage(artifact["coverage"], claim_ids)
    domain_refs = {
        "workflow",
        "applicability",
        "conclusion",
        "mathematical_principles",
        "algorithmic_principles",
    }
    for step in workflow["steps"]:
        domain_refs.add(step["step_id"])
    for node in workflow["graph"]["nodes"]:
        domain_refs.add(node["node_id"])
    for operation in workflow["graph"]["operations"]:
        domain_refs.add(operation["operation_id"])
    for step in mathematical_principles["derivation_steps"]:
        domain_refs.add(step["step_id"])
    for principle in mathematical_principles["principles"]:
        domain_refs.add(principle["principle_id"])
        for step in principle["derivation_steps"]:
            domain_refs.add(step["step_id"])
    for step in algorithmic_principles["ordered_steps"]:
        domain_refs.add(step["step_id"])
    for algorithm in algorithmic_principles["algorithms"]:
        domain_refs.add(algorithm["algorithm_id"])
        for step in algorithm["ordered_steps"]:
            domain_refs.add(step["step_id"])
    contributions = _validate_contribution_list(
        artifact["contributions"], "contributions", claim_ids, domain_refs
    )
    understanding_registry = _understanding_evidence_registry(claims)
    _validate_evidence_reference_closure(
        registry=understanding_registry,
        applicability=applicability,
        workflow=workflow,
        mathematical=mathematical_principles,
        algorithmic=algorithmic_principles,
        conclusion=conclusion,
        contributions=contributions,
        validate_locators=False,
    )
    if verified_dossier is not None:
        _validate_against_authoritative_dossier(
            claims,
            verified_dossier,
            applicability=applicability,
            workflow=workflow,
            mathematical=mathematical_principles,
            algorithmic=algorithmic_principles,
            conclusion=conclusion,
            contributions=contributions,
        )

    normalized = {
        "schema": SCHEMA,
        "schema_version": SCHEMA_VERSION,
        "producer": PRODUCER,
        "protocol_version": PROTOCOL_VERSION,
        "generated_at": generated_at,
        "research_retrieval_title": retrieval_title,
        "source_binding": source_binding,
        "executive_summary": executive_summary,
        "applicability": applicability,
        "workflow": workflow,
        "mathematical_principles": mathematical_principles,
        "algorithmic_principles": algorithmic_principles,
        "conclusion": conclusion,
        "contributions": contributions,
        "coverage": coverage,
        "claims": claims,
    }

    if require_identity:
        computed_digest = understanding_digest(normalized)
        if artifact["understanding_digest"] != computed_digest:
            raise ContractError("understanding_digest is not content-addressed")
        if not artifact["understanding_id"].startswith(UNDERSTANDING_PREFIX):
            raise ContractError("understanding_id must start with paper-understanding-")
        if artifact["understanding_id"] != understanding_id(computed_digest):
            raise ContractError("understanding_id does not match understanding_digest")
        normalized["understanding_digest"] = artifact["understanding_digest"]
        normalized["understanding_id"] = artifact["understanding_id"]

    return normalized


def create_understanding(
    raw: Any,
    *,
    source_bundle: str | None = None,
    source: str | None = None,
    dossier: str | None = None,
    generated_at: str | None = None,
) -> dict[str, Any]:
    normalized = validate_understanding(
        raw,
        require_identity=False,
        source_bundle_path=source_bundle,
        source_path=source,
        dossier_path=dossier,
    )
    if generated_at is not None:
        normalized["generated_at"] = _require_timestamp(generated_at, "generated_at")
    else:
        normalized["generated_at"] = _timestamp_now()
    computed_digest = understanding_digest(normalized)
    normalized["understanding_digest"] = computed_digest
    normalized["understanding_id"] = understanding_id(computed_digest)
    return normalized


def create_validation_record(
    understanding: Any,
    *,
    source_bundle: str | None = None,
    source: str | None = None,
    dossier: str | None = None,
) -> dict[str, Any]:
    validated = validate_understanding(
        understanding,
        require_identity=True,
        source_bundle_path=source_bundle,
        source_path=source,
        dossier_path=dossier,
    )
    source_binding_verified = all((source_bundle, source, dossier))
    checks = [
        {"check_id": "closed_schema", "status": "passed"},
        {"check_id": "content_address", "status": "passed"},
        {
            "check_id": "cross_references",
            "status": "passed" if source_binding_verified else "not_checked",
        },
        {
            "check_id": "source_binding",
            "status": "passed" if source_binding_verified else "not_checked",
        },
    ]
    record = {
        "schema": VALIDATION_SCHEMA,
        "schema_version": VALIDATION_SCHEMA_VERSION,
        "understanding_id": validated["understanding_id"],
        "understanding_digest": validated["understanding_digest"],
        "validator_name": VALIDATOR_NAME,
        "validator_version": VALIDATOR_VERSION,
        "status": "passed",
        "source_binding_verified": source_binding_verified,
        "checks": checks,
    }
    digest = validation_record_digest(record)
    record["record_id"] = validation_record_id(digest)
    record["record_digest"] = digest
    return record


def validate_validation_record(
    raw: Any,
    *,
    understanding: dict[str, Any] | None = None,
) -> dict[str, Any]:
    record = _require_object(raw, "validation_record")
    _require_keys(record, "validation_record", VALIDATION_TOP_LEVEL_KEYS)
    if record["schema"] != VALIDATION_SCHEMA:
        raise ContractError(f"validation_record.schema must be {VALIDATION_SCHEMA}")
    if record["schema_version"] != VALIDATION_SCHEMA_VERSION:
        raise ContractError(
            f"validation_record.schema_version must be {VALIDATION_SCHEMA_VERSION}"
        )
    if record["validator_name"] != VALIDATOR_NAME:
        raise ContractError(f"validation_record.validator_name must be {VALIDATOR_NAME}")
    if record["validator_version"] != VALIDATOR_VERSION:
        raise ContractError(
            f"validation_record.validator_version must be {VALIDATOR_VERSION}"
        )
    if record["status"] != "passed":
        raise ContractError("validation_record.status must be passed")

    bound_digest = _require_sha256(
        record["understanding_digest"],
        "validation_record.understanding_digest",
    )
    bound_id = _require_id(
        record["understanding_id"],
        "validation_record.understanding_id",
    )
    if bound_id != understanding_id(bound_digest):
        raise ContractError("validation_record understanding identity is not content-addressed")

    checks_raw = _require_list(record["checks"], "validation_record.checks")
    if len(checks_raw) != len(VALIDATION_CHECK_IDS):
        raise ContractError("validation_record.checks must contain the canonical check set")
    checks: list[dict[str, str]] = []
    for index, (raw_check, expected_id) in enumerate(
        zip(checks_raw, VALIDATION_CHECK_IDS, strict=True)
    ):
        label = f"validation_record.checks[{index}]"
        check = _require_object(raw_check, label)
        _require_keys(check, label, VALIDATION_CHECK_KEYS)
        check_id = _require_text(check["check_id"], f"{label}.check_id")
        if check_id != expected_id:
            raise ContractError("validation_record.checks are not in canonical order")
        check_status = _require_text(check["status"], f"{label}.status")
        if check_status not in VALIDATION_CHECK_STATUS_VALUES:
            raise ContractError(f"{label}.status is unsupported")
        if check_id in {"closed_schema", "content_address"} and check_status != "passed":
            raise ContractError(f"{label}.status must be passed")
        checks.append({"check_id": check_id, "status": check_status})

    source_binding_verified = _require_bool(
        record["source_binding_verified"],
        "validation_record.source_binding_verified",
    )
    expected_live_status = "passed" if source_binding_verified else "not_checked"
    if checks[2]["status"] != expected_live_status:
        raise ContractError(
            "validation_record cross_references check disagrees with live verification"
        )
    if checks[-1]["status"] != expected_live_status:
        raise ContractError(
            "validation_record source_binding check disagrees with source_binding_verified"
        )

    normalized = {
        "schema": VALIDATION_SCHEMA,
        "schema_version": VALIDATION_SCHEMA_VERSION,
        "understanding_id": bound_id,
        "understanding_digest": bound_digest,
        "validator_name": VALIDATOR_NAME,
        "validator_version": VALIDATOR_VERSION,
        "status": "passed",
        "source_binding_verified": source_binding_verified,
        "checks": checks,
    }
    computed_digest = validation_record_digest(normalized)
    supplied_digest = _require_sha256(
        record["record_digest"],
        "validation_record.record_digest",
    )
    if supplied_digest != computed_digest:
        raise ContractError("validation_record.record_digest is not content-addressed")
    supplied_id = _require_id(record["record_id"], "validation_record.record_id")
    if supplied_id != validation_record_id(computed_digest):
        raise ContractError("validation_record.record_id does not match record_digest")

    if understanding is not None:
        if bound_id != understanding["understanding_id"]:
            raise ContractError("validation_record understanding_id binding mismatch")
        if bound_digest != understanding["understanding_digest"]:
            raise ContractError("validation_record understanding_digest binding mismatch")

    normalized["record_id"] = supplied_id
    normalized["record_digest"] = supplied_digest
    return normalized


def validate_note_input_projection(
    understanding: dict[str, Any],
    validation_record: dict[str, Any],
    *,
    source_bundle_path: str,
    source_path: str,
    dossier_path: str,
) -> dict[str, Any]:
    live_paths = (source_bundle_path, source_path, dossier_path)
    if not all(isinstance(path, str) and path.strip() for path in live_paths):
        raise ContractError(
            "final note projection requires source bundle, source, and dossier paths"
        )
    validated = validate_understanding(
        understanding,
        require_identity=True,
        source_bundle_path=source_bundle_path,
        source_path=source_path,
        dossier_path=dossier_path,
    )
    supplied_record = validate_validation_record(
        validation_record,
        understanding=validated,
    )
    live_record = create_validation_record(
        validated,
        source_bundle=source_bundle_path,
        source=source_path,
        dossier=dossier_path,
    )
    if supplied_record != live_record:
        raise ContractError(
            "supplied validation record is not exactly the deterministic live record"
        )
    return _build_note_input_projection(validated, live_record)


def _build_note_input_projection(
    understanding: dict[str, Any],
    validation_record: dict[str, Any] | None = None,
) -> dict[str, Any]:
    source_binding = understanding["source_binding"]
    if source_binding["reading_depth"] == "map":
        raise ContractError("map reading_depth cannot project PaperUnderstandingNoteInput/v1")
    if validation_record is None:
        raise ContractError("project-note-input requires a validation record")
    verified_record = validate_validation_record(
        validation_record,
        understanding=understanding,
    )
    if not verified_record["source_binding_verified"]:
        raise ContractError("project-note-input requires live-verified source binding")

    domain_names = (
        "applicability",
        "workflow",
        "mathematical_principles",
        "algorithmic_principles",
        "conclusion",
    )
    unresolved = [
        name for name in domain_names if understanding[name]["status"] == "unresolved"
    ]
    if unresolved:
        raise ContractError(
            f"unresolved domains cannot project note input: {sorted(unresolved)}"
        )

    ordered_claims = sorted(
        understanding["claims"],
        key=lambda claim: claim["claim_id"],
    )
    claim_ids = {claim["claim_id"] for claim in ordered_claims}
    understood_ids = {
        entry["claim_id"] for entry in understanding["coverage"]["understood_claims"]
    }
    if not understood_ids:
        raise ContractError("projected note input needs at least one understood claim")
    if not understood_ids <= claim_ids:
        raise ContractError("coverage.understood_claims contains an unknown claim")
    statement_claim_ids = list(understanding["executive_summary"]["claim_ids"])
    if not set(statement_claim_ids) <= understood_ids:
        raise ContractError(
            "executive_summary.claim_ids must all be understood before note projection"
        )

    applicability = understanding["applicability"]
    workflow = understanding["workflow"]
    if not applicability["does_not_apply_when"]:
        raise ContractError(
            "applicability.does_not_apply_when must be non-empty for note projection"
        )
    if not workflow["preconditions"]:
        raise ContractError("workflow.preconditions must be non-empty for note projection")
    if not workflow["steps"]:
        raise ContractError("workflow.steps must be non-empty for note projection")
    if not workflow["data_flow"]:
        raise ContractError("workflow.data_flow must be non-empty for note projection")
    if any(not step["checks"] for step in workflow["steps"]):
        raise ContractError("workflow.steps checks must be non-empty for note projection")

    def _map_note_status(value: str) -> str:
        if value == "answered":
            return "applicable"
        if value == "not_applicable":
            return "not_applicable"
        raise ContractError("unresolved status cannot be mapped to not_applicable")

    def _map_not_applicable_reason(section: dict[str, Any]) -> str | None:
        if section["status"] == "not_applicable":
            return section["rationale"]
        return None

    mathematical = understanding["mathematical_principles"]
    algorithmic = understanding["algorithmic_principles"]
    conclusion = understanding["conclusion"]
    return {
        "schema": UNDERSTANDING_NOTES_INPUT_SCHEMA,
        "understanding_binding": {
            "understanding_id": understanding["understanding_id"],
            "understanding_digest": understanding["understanding_digest"],
            "validation_record_id": verified_record["record_id"],
            "validation_record_digest": verified_record["record_digest"],
        },
        "executive_summary": {
            "research_retrieval_title": understanding["research_retrieval_title"],
            "summary": understanding["executive_summary"]["summary"],
            "claim_ids": statement_claim_ids,
        },
        "applicability": {
            "status": _map_note_status(applicability["status"]),
            "rationale": applicability["rationale"],
            "evidence_ids": applicability["evidence_ids"],
            "missing_information": applicability["missing_information"],
            "primary_use_case": applicability["primary_use_case"],
            "applies_when": applicability["applies_when"],
            "does_not_apply_when": applicability["does_not_apply_when"],
        },
        "workflow": {
            "status": _map_note_status(workflow["status"]),
            "rationale": workflow["rationale"],
            "evidence_ids": workflow["evidence_ids"],
            "missing_information": workflow["missing_information"],
            "inputs": workflow["inputs"],
            "preconditions": workflow["preconditions"],
            "outputs": workflow["outputs"],
            "data_flow": workflow["data_flow"],
            "steps": workflow["steps"],
            "graph": workflow["graph"],
        },
        "mathematical_principles": {
            "status": _map_note_status(mathematical["status"]),
            "rationale": mathematical["rationale"],
            "evidence_ids": mathematical["evidence_ids"],
            "missing_information": mathematical["missing_information"],
            "not_applicable_reason": _map_not_applicable_reason(mathematical),
            "assumptions": mathematical["assumptions"],
            "derivation_steps": mathematical["derivation_steps"],
            "results": mathematical["results"],
            "principles": [
                {
                    "principle_id": principle["principle_id"],
                    "statement": principle["statement"],
                    "latex": principle["latex"],
                    "symbols": principle["symbols"],
                    "role": "核心数学原理",
                    "assumptions": principle["assumptions"],
                    "derivation": [
                        step["statement"] for step in principle["derivation_steps"]
                    ],
                    "derivation_steps": principle["derivation_steps"],
                    "results": principle["results"],
                    "origin": principle["origin"],
                    "locator": principle["locator"],
                    "claim_ids": sorted(principle["claim_ids"]),
                }
                for principle in mathematical["principles"]
            ],
        },
        "algorithmic_principles": {
            "status": _map_note_status(algorithmic["status"]),
            "rationale": algorithmic["rationale"],
            "evidence_ids": algorithmic["evidence_ids"],
            "missing_information": algorithmic["missing_information"],
            "not_applicable_reason": _map_not_applicable_reason(algorithmic),
            "objective": algorithmic["objective"],
            "state_variables": algorithmic["state_variables"],
            "ordered_steps": algorithmic["ordered_steps"],
            "invariants": algorithmic["invariants"],
            "failure_modes": algorithmic["failure_modes"],
            "principles": [
                {
                    "algorithm_id": algorithm["algorithm_id"],
                    "name": algorithm["name"],
                    "inputs": algorithm["inputs"],
                    "outputs": algorithm["outputs"],
                    "initialization": algorithm["initialization"],
                    "steps": [step["action"] for step in algorithm["ordered_steps"]],
                    "ordered_steps": algorithm["ordered_steps"],
                    "update_rule": algorithm["update_rule"],
                    "stopping_condition": algorithm["stopping_condition"],
                    "complexity": algorithm["complexity"],
                    "numerical_risks": algorithm["numerical_risks"],
                    "origin": algorithm["origin"],
                    "locator": algorithm["locator"],
                    "claim_ids": sorted(algorithm["claim_ids"]),
                }
                for algorithm in algorithmic["algorithms"]
            ],
        },
        "conclusion": {
            "status": _map_note_status(conclusion["status"]),
            "rationale": conclusion["rationale"],
            "evidence_ids": conclusion["evidence_ids"],
            "missing_information": conclusion["missing_information"],
            "statement": conclusion["statement"],
            "claim_ids": sorted(conclusion["claim_ids"]),
            "confidence": _require_note_confidence(
                conclusion["confidence"],
                "conclusion.confidence",
            ),
            "confidence_rationale": conclusion["confidence_rationale"],
        },
        "contributions": [
            {
                "contribution_id": contribution["contribution_id"],
                "statement": contribution["statement"],
                "claim_ids": sorted(contribution["claim_ids"]),
                "evidence_ids": contribution["evidence_ids"],
                "domain_refs": contribution["domain_refs"],
            }
            for contribution in understanding["contributions"]
        ],
        "source_binding": {
            "source_id": source_binding["source_id"],
            "canonical_title": source_binding["canonical_title"],
            "authors": source_binding["authors"],
            "year": source_binding["year"],
            "venue": source_binding["venue"],
            "stable_identifier": source_binding["stable_identifier"],
            "publication_status": source_binding["publication_status"],
            "source_artifact_sha256": source_binding["source_artifact_sha256"],
            "source_bundle_id": source_binding["source_bundle_id"],
            "source_bundle_digest": source_binding["source_bundle_digest"],
            "reading_dossier_id": source_binding["reading_dossier_id"],
            "reading_dossier_digest": source_binding["reading_dossier_digest"],
            "paper_card_ref": source_binding["paper_card_ref"],
            "evidence_ledger_ref": source_binding["evidence_ledger_ref"],
            "agent_inferences_explicit": True,
        },
        "coverage": {
            "access_level": source_binding["access_level"],
            "reading_depth": source_binding["reading_depth"],
            "verified_at": source_binding["verified_at"],
            "claims": [
                {
                    "claim_id": claim["claim_id"],
                    "hypothesis_id": claim["hypothesis_id"],
                    "target_id": claim["target_id"],
                    "statement": claim["statement"],
                    "relation": claim["relation"],
                    "nature": claim["nature"],
                    "scope": claim["scope"],
                    "evidence": claim["evidence"],
                    "verifier_status": claim["verifier_status"],
                    "confidence": _require_note_confidence(
                        claim["confidence"],
                        f"coverage.claims[{claim['claim_id']}].confidence",
                    ),
                    "confidence_rationale": claim["confidence_rationale"],
                }
                for claim in ordered_claims
            ],
            "boundaries": [
                {
                    "boundary_id": f"terminal-{entry['claim_id']}",
                    "condition": "coverage terminal",
                    "effect": entry["reason"],
                    "locator": "coverage",
                    "claim_ids": [entry["claim_id"]],
                }
                for entry in sorted(
                    understanding["coverage"]["terminal_claims"],
                    key=lambda entry: entry["claim_id"],
                )
            ],
        },
    }


def _read_json(path: str | Path) -> dict[str, Any]:
    candidate = Path(path)
    if candidate.is_symlink() or not candidate.is_file():
        raise ContractError(f"cannot read non-regular file: {candidate}")
    try:
        return json.loads(candidate.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ContractError(f"cannot read JSON: {exc}") from exc


def _preflight_output_paths(paths: list[Path]) -> list[Path]:
    candidates: list[Path] = []
    seen: set[str] = set()
    for raw_path in paths:
        candidate = raw_path.expanduser()
        if not candidate.is_absolute():
            raise ContractError("output path must be absolute")
        key = os.path.abspath(candidate)
        if key in seen:
            raise ContractError(f"duplicate output path: {candidate}")
        seen.add(key)
        if candidate.is_symlink() or candidate.exists():
            raise ContractError(f"refusing to overwrite existing output: {candidate}")
        for ancestor in candidate.parents:
            if ancestor.is_symlink():
                raise ContractError(f"output ancestor must not be a symlink: {ancestor}")
            if ancestor.exists() and not ancestor.is_dir():
                raise ContractError(f"output ancestor must be a directory: {ancestor}")
        candidates.append(candidate)

    for candidate in candidates:
        candidate.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        if candidate.parent.is_symlink() or not candidate.parent.is_dir():
            raise ContractError(f"unsafe output directory: {candidate.parent}")
        if candidate.is_symlink() or candidate.exists():
            raise ContractError(f"output appeared during preflight: {candidate}")
    return candidates


def _write_outputs_atomically(outputs: list[tuple[Path, Any]]) -> None:
    if not outputs:
        return
    candidates = _preflight_output_paths([path for path, _ in outputs])
    temporaries: list[Path] = []
    committed: list[Path] = []
    try:
        for index, ((_, payload), candidate) in enumerate(zip(outputs, candidates, strict=True)):
            temp = candidate.parent / (
                f".{candidate.name}.{os.getpid()}.{index}.{os.urandom(8).hex()}.tmp"
            )
            flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
            if hasattr(os, "O_NOFOLLOW"):
                flags |= os.O_NOFOLLOW
            descriptor = os.open(temp, flags, 0o600)
            temporaries.append(temp)
            try:
                encoded = (
                    json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2)
                    + "\n"
                ).encode("utf-8")
                with os.fdopen(descriptor, "wb") as stream:
                    descriptor = -1
                    stream.write(encoded)
                    stream.flush()
                    os.fsync(stream.fileno())
            finally:
                if descriptor >= 0:
                    os.close(descriptor)
        for temp, candidate in zip(temporaries, candidates, strict=True):
            os.link(temp, candidate, follow_symlinks=False)
            committed.append(candidate)
            temp.unlink()
        temporaries.clear()
    except Exception:
        for candidate in reversed(committed):
            try:
                candidate.unlink()
            except FileNotFoundError:
                pass
        for temp in temporaries:
            try:
                temp.unlink()
            except FileNotFoundError:
                pass
        raise


def _write_output(path: Path, payload: Any) -> None:
    _write_outputs_atomically([(path, payload)])


def _write_private(path: Path, payload: Any) -> None:
    _write_output(path, payload)


def audit_understanding(artifact: dict[str, Any]) -> dict[str, Any]:
    understood = len(artifact["coverage"]["understood_claims"])
    terminal = len(artifact["coverage"]["terminal_claims"])
    return {
        "understanding_id": artifact["understanding_id"],
        "understanding_digest": artifact["understanding_digest"],
        "claim_count": len(artifact["claims"]),
        "understood_claims": understood,
        "terminal_claims": terminal,
        "domain_status": {
            "applicability": artifact["applicability"]["status"],
            "workflow": artifact["workflow"]["status"],
            "mathematical_principles": artifact["mathematical_principles"]["status"],
            "algorithmic_principles": artifact["algorithmic_principles"]["status"],
            "conclusion": artifact["conclusion"]["status"],
        },
        "source_reading_depth": artifact["source_binding"]["reading_depth"],
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subcommands = parser.add_subparsers(dest="command", required=True)

    create = subcommands.add_parser(
        "create",
        help="Validate a draft and write full PaperUnderstanding/v1 with identity fields",
    )
    create.add_argument("--input", required=True, help="PaperUnderstanding draft JSON")
    create.add_argument("--output", required=True, help="Output PaperUnderstanding JSON")
    create.add_argument("--bundle", help="Verified source bundle JSON path")
    create.add_argument("--source", help="Source document path for bundle verification")
    create.add_argument("--dossier", help="Verified PaperReadingDossier/v1 JSON path")
    create.add_argument("--generated-at", help="Override generated_at timestamp")

    validate = subcommands.add_parser(
        "validate",
        help="Validate a complete PaperUnderstanding/v1",
    )
    validate.add_argument("--input", required=True)
    validate.add_argument("--bundle")
    validate.add_argument("--source")
    validate.add_argument("--dossier")
    validate.add_argument(
        "--output",
        help="Optional output path for PaperUnderstandingValidation/v1",
    )

    audit = subcommands.add_parser(
        "audit",
        help="Run full validation and emit coverage summary",
    )
    audit.add_argument("--input", required=True)
    audit.add_argument("--bundle")
    audit.add_argument("--source")
    audit.add_argument("--dossier")

    project_note_input = subcommands.add_parser(
        "project-note-input",
        help="Emit PaperUnderstandingNoteInput/v1 projection",
    )
    project_note_input.add_argument("--understanding", required=True)
    project_note_input.add_argument("--output", required=True)
    project_note_input.add_argument(
        "--shadow-root",
        help="Opt-in absolute directory for writing a shadow copy",
    )
    project_note_input.add_argument(
        "--audit-root",
        help="Opt-in absolute directory for audit copy",
    )
    project_note_input.add_argument("--source-bundle", required=True)
    project_note_input.add_argument("--source", required=True)
    project_note_input.add_argument("--dossier", required=True)
    project_note_input.add_argument(
        "--validation-record",
        required=True,
        help="Validation record that must exactly match deterministic live regeneration",
    )

    return parser


def main(argv: list[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    try:
        if arguments.command == "create":
            raw = _read_json(arguments.input)
            created = create_understanding(
                raw,
                source_bundle=arguments.bundle,
                source=arguments.source,
                dossier=arguments.dossier,
                generated_at=arguments.generated_at,
            )
            _write_private(Path(arguments.output), created)
            print(
                json.dumps(
                    {
                        "schema": SCHEMA,
                        "valid": True,
                        "understanding_id": created["understanding_id"],
                        "understanding_digest": created["understanding_digest"],
                    },
                    sort_keys=True,
                )
            )
            return 0

        if arguments.command == "validate":
            raw = _read_json(arguments.input)
            record = create_validation_record(
                raw,
                source_bundle=arguments.bundle,
                source=arguments.source,
                dossier=arguments.dossier,
            )
            if arguments.output:
                _write_private(Path(arguments.output), record)
            print(json.dumps(record, sort_keys=True))
            return 0

        if arguments.command == "audit":
            raw = _read_json(arguments.input)
            validated = validate_understanding(
                raw,
                require_identity=True,
                source_bundle_path=arguments.bundle,
                source_path=arguments.source,
                dossier_path=arguments.dossier,
            )
            print(json.dumps(audit_understanding(validated), sort_keys=True))
            return 0

        if arguments.command == "project-note-input":
            raw = _read_json(arguments.understanding)
            supplied_record = _read_json(arguments.validation_record)
            validated = validate_understanding(
                raw,
                require_identity=True,
                source_bundle_path=arguments.source_bundle,
                source_path=arguments.source,
                dossier_path=arguments.dossier,
            )
            live_record = create_validation_record(
                validated,
                source_bundle=arguments.source_bundle,
                source=arguments.source,
                dossier=arguments.dossier,
            )
            projection = validate_note_input_projection(
                validated,
                supplied_record,
                source_bundle_path=arguments.source_bundle,
                source_path=arguments.source,
                dossier_path=arguments.dossier,
            )
            output = Path(arguments.output)
            shadow_output = (
                Path(arguments.shadow_root).expanduser() / output.name
                if arguments.shadow_root
                else None
            )
            audit_output = (
                Path(arguments.audit_root).expanduser() / output.name
                if arguments.audit_root
                else None
            )
            outputs: list[tuple[Path, Any]] = [(output, projection)]
            if shadow_output is not None:
                outputs.append((shadow_output, projection))
            if audit_output is not None:
                outputs.append((audit_output, projection))
            _write_outputs_atomically(outputs)

            manifest = {
                "schema": UNDERSTANDING_NOTES_INPUT_SCHEMA,
                "understanding_id": validated["understanding_id"],
                "understanding_digest": validated["understanding_digest"],
                "validation_record_id": live_record["record_id"],
                "validation_record_digest": live_record["record_digest"],
                "note_h1": validated["research_retrieval_title"],
                "note_path": str(output),
                "shadow_path": str(shadow_output) if shadow_output else None,
                "audit_path": str(audit_output) if audit_output else None,
            }
            print(json.dumps(manifest, sort_keys=True))
            return 0

    except (ContractError, OSError, json.JSONDecodeError, ValueError) as exc:
        print(f"paper-understanding validation failed: {exc}", file=sys.stderr)
        return 2

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
