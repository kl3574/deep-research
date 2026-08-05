#!/usr/bin/env python3
"""Validate and project PaperUnderstandingNoteInput/v1 to Zotero note HTML.

This module is deliberately offline. It never connects to Zotero and its write
contract permits mutation of only a child note's ``note`` field. Bibliographic
``title`` and ``shortTitle`` fields are source metadata and are never generated
or written by this projection layer.
"""

from __future__ import annotations

import argparse
import hashlib
import html
import importlib.util
import json
import os
import re
import stat
import sys
import unicodedata
from datetime import datetime
from html.parser import HTMLParser
from pathlib import Path
from types import ModuleType
from typing import Any


INPUT_SCHEMA = "PaperUnderstandingNoteInput/v1"
OUTPUT_SCHEMA = "PaperKnowledgeNote/v2"
PROJECTION_SCHEMA = "PaperKnowledgeNoteProjection/v1"
PROJECTION_ID_PREFIX = "paper-knowledge-note-projection-"
ZOTERO_NOTE_SCHEMA_VERSION = "9"
MAX_RETRIEVAL_TITLE_CODEPOINTS = 100
MAX_HTML_UTF8_BYTES = 512 * 1024
MAX_TEXT_CODEPOINTS = 12_000

SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
PRIVATE_KEY_RE = re.compile(r"(?<![A-Za-z0-9])[A-Z0-9]{8}(?![A-Za-z0-9])")
POSIX_ABSOLUTE_PATH_RE = re.compile(
    r"(?:^|[\s（(：:])/(?!/)(?:"
    r"(?:home|Users|root|tmp|var|etc|usr|opt|srv|mnt|media|run)(?:/[^<>\s]*)?"
    r"|(?:[^<>\s/]+/)+[^<>\s/]+)"
)
WINDOWS_ABSOLUTE_PATH_RE = re.compile(r"(?:^|[\s（(：:])[A-Za-z]:[\\/]")
CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
HTML_COMMENT_TOKEN_RE = re.compile(r"<!--|-->")
TITLE_DIGEST_RE = re.compile(r"(?<![0-9A-Fa-f])[0-9A-Fa-f]{64}(?![0-9A-Fa-f])")
DOI_RE = re.compile(r"(?i)(?<![0-9])10\.\d{4,9}/\S+")

RELATIONS = {"supports", "qualifies", "refutes", "not_tested"}
NATURES = {
    "source-stated",
    "agent-inferred",
    "externally-supported",
    "unresolved",
}
VERIFIER_STATUSES = {"passed", "failed", "unresolved", "not_tested"}
CONFIDENCE_LEVELS = {"high", "medium", "low"}
READING_DEPTHS = {"map", "evidence", "reconstruction"}
ACCESS_LEVELS = {"full_text", "partial_text", "abstract_only", "metadata_only"}
DOMAIN_STATUSES = {"applicable", "not_applicable", "unresolved"}
ORIGINS = {"source_stated", "agent_reconstructed"}
WORKFLOW_NODE_KINDS = {"input", "intermediate", "output"}

PYRAMID_SECTIONS = [
    "适用场景与结论",
    "工作流程与 I/O / 数据流",
    "数学原理与推导",
    "算法原理",
    "证据、边界与溯源",
]
CLAIM_HEADERS = [
    "Claim ID",
    "Hypothesis ID",
    "Target ID",
    "Relation",
    "性质",
    "主张",
    "Scope",
    "证据与精确定位",
    "核验与置信度",
]
PARENT_BIBLIOGRAPHIC_FIELDS = [
    "title",
    "shortTitle",
    "creators",
    "DOI",
    "date",
    "publicationTitle",
]
PROJECTION_MANIFEST_KEYS = {
    "schema",
    "projection_id",
    "projection_digest",
    "input_schema",
    "output_schema",
    "normalized_input_sha256",
    "understanding_binding",
    "html_sha256",
    "html_utf8_bytes",
    "retrieval_title",
    "retrieval_title_codepoints",
    "write_contract",
    "validation",
}
UPSTREAM_PROVENANCE_KEY = "upstream_provenance"
UPSTREAM_ARTIFACT_NAMES = (
    "note_input",
    "understanding",
    "validation_record",
    "source_bundle",
    "source",
    "dossier",
)
UPSTREAM_PROVENANCE_KEYS = {
    f"{name}_{suffix}"
    for name in UPSTREAM_ARTIFACT_NAMES
    for suffix in ("path", "sha256")
}
UNDERSTANDING_BINDING_KEYS = {
    "understanding_id",
    "understanding_digest",
    "validation_record_id",
    "validation_record_digest",
}

LEARN_SCRIPT_PATH = (
    Path(__file__).resolve().parents[2]
    / "learn-from-papers"
    / "scripts"
    / "paper_understanding.py"
)
_LEARN_MODULE: ModuleType | None = None
WRITE_CONTRACT_KEYS = {
    "target_item_type",
    "allowed_mutation_fields",
    "forbidden_parent_fields",
    "parent_bibliographic_fields_preserved",
    "zotero_write_performed",
}

TOP_LEVEL_KEYS = {
    "schema",
    "understanding_binding",
    "executive_summary",
    "applicability",
    "workflow",
    "mathematical_principles",
    "algorithmic_principles",
    "conclusion",
    "contributions",
    "source_binding",
    "coverage",
}
EXECUTIVE_SUMMARY_KEYS = {
    "research_retrieval_title",
    "summary",
    "claim_ids",
}
DOMAIN_METADATA_KEYS = {
    "status",
    "rationale",
    "evidence_ids",
    "missing_information",
}
APPLICABILITY_KEYS = DOMAIN_METADATA_KEYS | {
    "primary_use_case",
    "applies_when",
    "does_not_apply_when",
}
CONCLUSION_KEYS = DOMAIN_METADATA_KEYS | {
    "statement",
    "claim_ids",
    "confidence",
    "confidence_rationale",
}
CONTRIBUTION_KEYS = {
    "contribution_id",
    "statement",
    "claim_ids",
    "evidence_ids",
    "domain_refs",
}
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
}
COVERAGE_KEYS = {
    "access_level",
    "reading_depth",
    "verified_at",
    "claims",
    "boundaries",
}
WORKFLOW_KEYS = DOMAIN_METADATA_KEYS | {
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
MATH_GROUP_KEYS = DOMAIN_METADATA_KEYS | {
    "not_applicable_reason",
    "assumptions",
    "derivation_steps",
    "results",
    "principles",
}
ALGORITHM_GROUP_KEYS = DOMAIN_METADATA_KEYS | {
    "not_applicable_reason",
    "objective",
    "state_variables",
    "ordered_steps",
    "invariants",
    "failure_modes",
    "principles",
}
MATH_KEYS = {
    "principle_id",
    "statement",
    "latex",
    "symbols",
    "role",
    "assumptions",
    "derivation",
    "derivation_steps",
    "results",
    "origin",
    "locator",
    "claim_ids",
}
ALGORITHM_KEYS = {
    "algorithm_id",
    "name",
    "inputs",
    "outputs",
    "initialization",
    "steps",
    "ordered_steps",
    "update_rule",
    "stopping_condition",
    "complexity",
    "numerical_risks",
    "locator",
    "claim_ids",
    "origin",
}
MATH_DERIVATION_STEP_KEYS = {
    "step_id",
    "statement",
    "depends_on",
    "origin",
    "locator",
    "evidence_ids",
}
ALGORITHM_ORDERED_STEP_KEYS = {
    "step_id",
    "action",
    "depends_on",
    "consumes",
    "produces",
    "origin",
    "locator",
    "evidence_ids",
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
    "verifier_status",
    "confidence",
    "confidence_rationale",
}
SCOPE_KEYS = {"assumptions", "conditions", "units", "exclusions"}
EVIDENCE_KEYS = {"evidence_id", "summary", "locator"}
BOUNDARY_KEYS = {"boundary_id", "condition", "effect", "locator", "claim_ids"}


class ContractError(ValueError):
    """Raised when a project-note input or rendered projection is invalid."""


def canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def digest_value(value: Any) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def projection_content_digest(value: dict[str, Any]) -> str:
    return digest_value(
        {
            key: item
            for key, item in value.items()
            if key not in {"projection_id", "projection_digest"}
        }
    )


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _dict(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ContractError(f"{label} must be an object")
    return value


def _list(value: Any, label: str, *, nonempty: bool = True) -> list[Any]:
    if not isinstance(value, list) or (nonempty and not value):
        qualifier = "a nonempty array" if nonempty else "an array"
        raise ContractError(f"{label} must be {qualifier}")
    return value


def _exact_keys(value: dict[str, Any], allowed: set[str], label: str) -> None:
    unknown = set(value) - allowed
    missing = allowed - set(value)
    if unknown:
        raise ContractError(f"{label} contains unknown fields: {sorted(unknown)}")
    if missing:
        raise ContractError(f"{label} is missing fields: {sorted(missing)}")


def _privacy_guard(value: str, label: str) -> None:
    if HTML_COMMENT_TOKEN_RE.search(value):
        raise ContractError(f"{label} contains an HTML comment token")
    if PRIVATE_KEY_RE.search(value):
        raise ContractError(f"{label} contains a private-key-shaped token")
    if POSIX_ABSOLUTE_PATH_RE.search(value) or WINDOWS_ABSOLUTE_PATH_RE.search(value):
        raise ContractError(f"{label} contains an absolute local path")


def _text(value: Any, label: str, *, collapse: bool = True) -> str:
    if not isinstance(value, str):
        raise ContractError(f"{label} must be a string")
    normalized = unicodedata.normalize("NFC", value)
    if CONTROL_RE.search(normalized):
        raise ContractError(f"{label} contains control characters")
    normalized = " ".join(normalized.split()) if collapse else normalized.strip()
    if not normalized:
        raise ContractError(f"{label} must be nonempty")
    if len(normalized) > MAX_TEXT_CODEPOINTS:
        raise ContractError(f"{label} exceeds {MAX_TEXT_CODEPOINTS} code points")
    _privacy_guard(normalized, label)
    return normalized


def _string_list(
    value: Any,
    label: str,
    *,
    nonempty: bool = True,
) -> list[str]:
    return [
        _text(item, f"{label}[{index}]")
        for index, item in enumerate(_list(value, label, nonempty=nonempty))
    ]


def _id(value: Any, label: str) -> str:
    result = _text(value, label)
    if not re.fullmatch(r"[A-Za-z][A-Za-z0-9._:-]{0,127}", result):
        raise ContractError(f"{label} has an invalid identifier shape")
    return result


def _sha256(value: Any, label: str) -> str:
    if not isinstance(value, str) or not SHA256_RE.fullmatch(value):
        raise ContractError(f"{label} must be 64 lowercase hexadecimal characters")
    return value


def _timestamp(value: Any, label: str) -> str:
    result = _text(value, label)
    try:
        parsed = datetime.fromisoformat(result.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ContractError(f"{label} must be an ISO-8601 timestamp") from exc
    if parsed.tzinfo is None:
        raise ContractError(f"{label} must include a timezone")
    return result


def _validate_understanding_binding(value: Any) -> dict[str, str]:
    binding = _dict(value, "understanding_binding")
    _exact_keys(binding, UNDERSTANDING_BINDING_KEYS, "understanding_binding")
    return {
        "understanding_id": _id(
            binding["understanding_id"], "understanding_binding.understanding_id"
        ),
        "understanding_digest": _sha256(
            binding["understanding_digest"],
            "understanding_binding.understanding_digest",
        ),
        "validation_record_id": _id(
            binding["validation_record_id"],
            "understanding_binding.validation_record_id",
        ),
        "validation_record_digest": _sha256(
            binding["validation_record_digest"],
            "understanding_binding.validation_record_digest",
        ),
    }


def _id_list(
    value: Any,
    label: str,
    *,
    nonempty: bool = True,
) -> list[str]:
    result = [
        _id(item, f"{label}[{index}]")
        for index, item in enumerate(_list(value, label, nonempty=nonempty))
    ]
    if result != sorted(set(result)):
        raise ContractError(f"{label} must be sorted and unique")
    return result


def _id_sequence(
    value: Any,
    label: str,
    *,
    nonempty: bool = True,
) -> list[str]:
    result = [
        _id(item, f"{label}[{index}]")
        for index, item in enumerate(_list(value, label, nonempty=nonempty))
    ]
    if len(result) != len(set(result)):
        raise ContractError(f"{label} must be unique")
    return result


def _claim_ids(value: Any, label: str) -> list[str]:
    return _id_list(value, label)


def _known_claim_refs(
    value: Any,
    label: str,
    known_claim_ids: set[str],
) -> list[str]:
    result = _claim_ids(value, label)
    unknown = set(result) - known_claim_ids
    if unknown:
        raise ContractError(f"{label} references unknown claims: {sorted(unknown)}")
    return result


def _known_evidence_refs(
    value: Any,
    label: str,
    known_evidence_ids: set[str],
) -> list[str]:
    result = _id_sequence(value, label, nonempty=False)
    unknown = set(result) - known_evidence_ids
    if unknown:
        raise ContractError(f"{label} references unknown evidence: {sorted(unknown)}")
    return result


def _validate_domain_metadata(
    value: dict[str, Any],
    label: str,
    known_evidence_ids: set[str],
) -> dict[str, Any]:
    status = _text(value["status"], f"{label}.status")
    if status not in DOMAIN_STATUSES:
        raise ContractError(f"{label}.status is unsupported")
    evidence_ids = _known_evidence_refs(
        value["evidence_ids"], f"{label}.evidence_ids", known_evidence_ids
    )
    missing_information = _string_list(
        value["missing_information"],
        f"{label}.missing_information",
        nonempty=False,
    )
    if status == "applicable" and not evidence_ids:
        raise ContractError(f"{label}.evidence_ids must be nonempty when applicable")
    if status == "unresolved" and not missing_information:
        raise ContractError(
            f"{label}.missing_information must be nonempty when unresolved"
        )
    return {
        "status": status,
        "rationale": _text(value["rationale"], f"{label}.rationale"),
        "evidence_ids": evidence_ids,
        "missing_information": missing_information,
    }


def _origin(value: Any, label: str) -> str:
    result = _text(value, label)
    if result not in ORIGINS:
        raise ContractError(f"{label} is unsupported")
    return result


def _validate_math_derivation_steps(
    value: Any,
    label: str,
    *,
    assumptions: set[str],
    known_evidence_ids: set[str],
) -> list[dict[str, Any]]:
    steps: list[dict[str, Any]] = []
    prior_ids: set[str] = set()
    for index, raw_step in enumerate(_list(value, label, nonempty=False)):
        step_label = f"{label}[{index}]"
        step = _dict(raw_step, step_label)
        _exact_keys(step, MATH_DERIVATION_STEP_KEYS, step_label)
        step_id = _id(step["step_id"], f"{step_label}.step_id")
        if step_id in prior_ids:
            raise ContractError(f"{label} step IDs must be unique")
        dependencies = _string_list(
            step["depends_on"], f"{step_label}.depends_on", nonempty=False
        )
        for dependency in dependencies:
            if dependency.startswith("assumption:"):
                if dependency.removeprefix("assumption:") not in assumptions:
                    raise ContractError(
                        f"{step_label}.depends_on references an unknown assumption"
                    )
            elif dependency.startswith("step:"):
                if dependency.removeprefix("step:") not in prior_ids:
                    raise ContractError(
                        f"{step_label}.depends_on references a future or unknown step"
                    )
            else:
                raise ContractError(
                    f"{step_label}.depends_on must use assumption: or step: references"
                )
        steps.append(
            {
                "step_id": step_id,
                "statement": _text(step["statement"], f"{step_label}.statement"),
                "depends_on": dependencies,
                "origin": _origin(step["origin"], f"{step_label}.origin"),
                "locator": _text(step["locator"], f"{step_label}.locator"),
                "evidence_ids": _known_evidence_refs(
                    step["evidence_ids"],
                    f"{step_label}.evidence_ids",
                    known_evidence_ids,
                ),
            }
        )
        prior_ids.add(step_id)
    return steps


def _validate_algorithm_steps(
    value: Any,
    label: str,
    *,
    known_evidence_ids: set[str],
) -> list[dict[str, Any]]:
    steps: list[dict[str, Any]] = []
    prior_ids: set[str] = set()
    for index, raw_step in enumerate(_list(value, label, nonempty=False)):
        step_label = f"{label}[{index}]"
        step = _dict(raw_step, step_label)
        _exact_keys(step, ALGORITHM_ORDERED_STEP_KEYS, step_label)
        step_id = _id(step["step_id"], f"{step_label}.step_id")
        if step_id in prior_ids:
            raise ContractError(f"{label} step IDs must be unique")
        dependencies = _id_list(
            step["depends_on"], f"{step_label}.depends_on", nonempty=False
        )
        unknown = set(dependencies) - prior_ids
        if unknown:
            raise ContractError(
                f"{step_label}.depends_on references future or unknown steps: "
                f"{sorted(unknown)}"
            )
        steps.append(
            {
                "step_id": step_id,
                "action": _text(step["action"], f"{step_label}.action"),
                "depends_on": dependencies,
                "consumes": _string_list(
                    step["consumes"], f"{step_label}.consumes", nonempty=False
                ),
                "produces": _string_list(
                    step["produces"], f"{step_label}.produces", nonempty=False
                ),
                "origin": _origin(step["origin"], f"{step_label}.origin"),
                "locator": _text(step["locator"], f"{step_label}.locator"),
                "evidence_ids": _known_evidence_refs(
                    step["evidence_ids"],
                    f"{step_label}.evidence_ids",
                    known_evidence_ids,
                ),
            }
        )
        prior_ids.add(step_id)
    return steps


def _validate_workflow_graph(
    value: Any,
    label: str,
    *,
    require_endpoints: bool,
) -> dict[str, Any]:
    graph = _dict(value, label)
    _exact_keys(graph, GRAPH_KEYS, label)
    nodes: list[dict[str, str]] = []
    node_ids: set[str] = set()
    kinds: set[str] = set()
    for index, raw_node in enumerate(
        _list(graph["nodes"], f"{label}.nodes", nonempty=False)
    ):
        node_label = f"{label}.nodes[{index}]"
        node = _dict(raw_node, node_label)
        _exact_keys(node, GRAPH_NODE_KEYS, node_label)
        node_id = _id(node["node_id"], f"{node_label}.node_id")
        if node_id in node_ids:
            raise ContractError(f"{label} node IDs must be unique")
        node_ids.add(node_id)
        kind = _text(node["kind"], f"{node_label}.kind")
        if kind not in WORKFLOW_NODE_KINDS:
            raise ContractError(f"{node_label}.kind is unsupported")
        kinds.add(kind)
        nodes.append(
            {
                "node_id": node_id,
                "kind": kind,
                "description": _text(
                    node["description"], f"{node_label}.description"
                ),
                "semantic_type": _text(
                    node["semantic_type"], f"{node_label}.semantic_type"
                ),
                "representation": _text(
                    node["representation"], f"{node_label}.representation"
                ),
                "format": _text(node["format"], f"{node_label}.format"),
                "shape": _text(node["shape"], f"{node_label}.shape"),
                "unit": _text(node["unit"], f"{node_label}.unit"),
            }
        )
    operations: list[dict[str, Any]] = []
    operation_ids: set[str] = set()
    used_nodes: set[str] = set()
    for index, raw_operation in enumerate(
        _list(graph["operations"], f"{label}.operations", nonempty=False)
    ):
        operation_label = f"{label}.operations[{index}]"
        operation = _dict(raw_operation, operation_label)
        _exact_keys(operation, GRAPH_OPERATION_KEYS, operation_label)
        operation_id = _id(
            operation["operation_id"], f"{operation_label}.operation_id"
        )
        if operation_id in operation_ids:
            raise ContractError(f"{label} operation IDs must be unique")
        operation_ids.add(operation_id)
        consumes = _id_sequence(
            operation["consumes"], f"{operation_label}.consumes"
        )
        produces = _id_sequence(
            operation["produces"], f"{operation_label}.produces"
        )
        unknown = (set(consumes) | set(produces)) - node_ids
        if unknown:
            raise ContractError(
                f"{operation_label} references unknown nodes: {sorted(unknown)}"
            )
        used_nodes.update(consumes)
        used_nodes.update(produces)
        operations.append(
            {
                "operation_id": operation_id,
                "operation": _text(
                    operation["operation"], f"{operation_label}.operation"
                ),
                "consumes": consumes,
                "produces": produces,
            }
        )
    if require_endpoints and not {"input", "output"}.issubset(kinds):
        raise ContractError(f"{label} must contain input and output nodes")
    if node_ids - used_nodes:
        raise ContractError(f"{label} contains isolated nodes")
    return {"nodes": nodes, "operations": operations}


def _retrieval_title(value: Any, label: str) -> str:
    if not isinstance(value, str):
        raise ContractError(f"{label} must be a string")
    if "\n" in value or "\r" in value:
        raise ContractError(f"{label} must be a single line")
    result = _text(value, label)
    if "<" in result or ">" in result:
        raise ContractError(f"{label} must be plain text without HTML")
    if TITLE_DIGEST_RE.search(result) or DOI_RE.search(result):
        raise ContractError(f"{label} must not contain a digest or DOI")
    if len(result) > MAX_RETRIEVAL_TITLE_CODEPOINTS:
        raise ContractError(
            "research retrieval title exceeds "
            f"{MAX_RETRIEVAL_TITLE_CODEPOINTS} Unicode code points"
        )
    if not re.fullmatch(r"适用：.+｜结论(?:（[^\r\n）]+）)?：.+", result):
        raise ContractError(
            f"{label} must have the form 适用：<scenario>｜结论...：<bounded result>"
        )
    return result


def _validate_scope(value: Any, label: str) -> dict[str, list[str]]:
    scope = _dict(value, label)
    _exact_keys(scope, SCOPE_KEYS, label)
    return {
        key: _string_list(scope[key], f"{label}.{key}", nonempty=False)
        for key in ("assumptions", "conditions", "units", "exclusions")
    }


def _validate_claim(value: Any, index: int) -> dict[str, Any]:
    label = f"claims[{index}]"
    claim = _dict(value, label)
    _exact_keys(claim, CLAIM_KEYS, label)
    relation = _text(claim["relation"], f"{label}.relation")
    if relation not in RELATIONS:
        raise ContractError(f"{label}.relation is unsupported")
    nature = _text(claim["nature"], f"{label}.nature")
    if nature not in NATURES:
        raise ContractError(f"{label}.nature is unsupported")
    verifier_status = _text(claim["verifier_status"], f"{label}.verifier_status")
    if verifier_status not in VERIFIER_STATUSES:
        raise ContractError(f"{label}.verifier_status is unsupported")
    confidence = _text(claim["confidence"], f"{label}.confidence")
    if confidence not in CONFIDENCE_LEVELS:
        raise ContractError(f"{label}.confidence is unsupported")
    evidence_values = _list(
        claim["evidence"],
        f"{label}.evidence",
        nonempty=relation != "not_tested",
    )
    evidence: list[dict[str, str]] = []
    evidence_ids: set[str] = set()
    for evidence_index, raw_evidence in enumerate(evidence_values):
        evidence_label = f"{label}.evidence[{evidence_index}]"
        item = _dict(raw_evidence, evidence_label)
        _exact_keys(item, EVIDENCE_KEYS, evidence_label)
        evidence_id = _id(item["evidence_id"], f"{evidence_label}.evidence_id")
        if evidence_id in evidence_ids:
            raise ContractError(f"{label}.evidence IDs must be unique")
        evidence_ids.add(evidence_id)
        evidence.append(
            {
                "evidence_id": evidence_id,
                "summary": _text(item["summary"], f"{evidence_label}.summary"),
                "locator": _text(item["locator"], f"{evidence_label}.locator"),
            }
        )
    return {
        "claim_id": _id(claim["claim_id"], f"{label}.claim_id"),
        "hypothesis_id": _id(claim["hypothesis_id"], f"{label}.hypothesis_id"),
        "target_id": _id(claim["target_id"], f"{label}.target_id"),
        "statement": _text(claim["statement"], f"{label}.statement"),
        "relation": relation,
        "nature": nature,
        "scope": _validate_scope(claim["scope"], f"{label}.scope"),
        "evidence": evidence,
        "verifier_status": verifier_status,
        "confidence": confidence,
        "confidence_rationale": _text(
            claim["confidence_rationale"], f"{label}.confidence_rationale"
        ),
    }


def _validate_mathematical_principles(
    value: Any,
    label: str,
    *,
    known_claim_ids: set[str],
    known_evidence_ids: set[str],
) -> dict[str, Any]:
    group = _dict(value, label)
    _exact_keys(group, MATH_GROUP_KEYS, label)
    metadata = _validate_domain_metadata(group, label, known_evidence_ids)
    reason_value = group["not_applicable_reason"]
    if metadata["status"] == "applicable":
        if reason_value is not None:
            raise ContractError(
                f"{label}.not_applicable_reason must be null when applicable"
            )
        reason = None
    else:
        reason = _text(reason_value, f"{label}.not_applicable_reason")
    assumptions = _string_list(
        group["assumptions"], f"{label}.assumptions", nonempty=False
    )
    derivation_steps = _validate_math_derivation_steps(
        group["derivation_steps"],
        f"{label}.derivation_steps",
        assumptions=set(assumptions),
        known_evidence_ids=known_evidence_ids,
    )
    results = _string_list(group["results"], f"{label}.results", nonempty=False)
    principles_raw = _list(group["principles"], f"{label}.principles", nonempty=False)
    if metadata["status"] == "applicable" and not principles_raw:
        raise ContractError(f"{label}.principles must be nonempty when applicable")
    if metadata["status"] != "applicable" and principles_raw:
        raise ContractError(f"{label}.principles must be empty unless applicable")
    principles: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for index, raw in enumerate(principles_raw):
        item_label = f"{label}.principles[{index}]"
        item = _dict(raw, item_label)
        _exact_keys(item, MATH_KEYS, item_label)
        item_id = _id(item["principle_id"], f"{item_label}.principle_id")
        if item_id in seen_ids:
            raise ContractError(f"{label} IDs must be unique")
        seen_ids.add(item_id)
        claim_ids = _known_claim_refs(
            item["claim_ids"], f"{item_label}.claim_ids", known_claim_ids
        )
        principle_assumptions = _string_list(
            item["assumptions"], f"{item_label}.assumptions", nonempty=False
        )
        structured_steps = _validate_math_derivation_steps(
            item["derivation_steps"],
            f"{item_label}.derivation_steps",
            assumptions=set(assumptions) | set(principle_assumptions),
            known_evidence_ids=known_evidence_ids,
        )
        compatibility = _string_list(
            item["derivation"], f"{item_label}.derivation", nonempty=False
        )
        if compatibility != [step["statement"] for step in structured_steps]:
            raise ContractError(
                f"{item_label}.derivation must equal structured derivation statements"
            )
        principles.append(
            {
                "principle_id": item_id,
                "statement": _text(item["statement"], f"{item_label}.statement"),
                "latex": _text(item["latex"], f"{item_label}.latex", collapse=False),
                "symbols": _string_list(
                    item["symbols"], f"{item_label}.symbols", nonempty=False
                ),
                "role": _text(item["role"], f"{item_label}.role"),
                "assumptions": principle_assumptions,
                "derivation": compatibility,
                "derivation_steps": structured_steps,
                "results": _string_list(
                    item["results"], f"{item_label}.results", nonempty=False
                ),
                "origin": _origin(item["origin"], f"{item_label}.origin"),
                "locator": _text(item["locator"], f"{item_label}.locator"),
                "claim_ids": claim_ids,
            }
        )
    return {
        **metadata,
        "not_applicable_reason": reason,
        "assumptions": assumptions,
        "derivation_steps": derivation_steps,
        "results": results,
        "principles": principles,
    }


def _validate_algorithmic_principles(
    value: Any,
    label: str,
    *,
    known_claim_ids: set[str],
    known_evidence_ids: set[str],
) -> dict[str, Any]:
    group = _dict(value, label)
    _exact_keys(group, ALGORITHM_GROUP_KEYS, label)
    metadata = _validate_domain_metadata(group, label, known_evidence_ids)
    reason_value = group["not_applicable_reason"]
    if metadata["status"] == "applicable":
        if reason_value is not None:
            raise ContractError(
                f"{label}.not_applicable_reason must be null when applicable"
            )
        reason = None
    else:
        reason = _text(reason_value, f"{label}.not_applicable_reason")
    ordered_steps = _validate_algorithm_steps(
        group["ordered_steps"],
        f"{label}.ordered_steps",
        known_evidence_ids=known_evidence_ids,
    )
    principles_raw = _list(group["principles"], f"{label}.principles", nonempty=False)
    if metadata["status"] == "applicable" and not principles_raw:
        raise ContractError(f"{label}.principles must be nonempty when applicable")
    if metadata["status"] != "applicable" and principles_raw:
        raise ContractError(f"{label}.principles must be empty unless applicable")
    principles: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for index, raw in enumerate(principles_raw):
        item_label = f"{label}.principles[{index}]"
        item = _dict(raw, item_label)
        _exact_keys(item, ALGORITHM_KEYS, item_label)
        item_id = _id(item["algorithm_id"], f"{item_label}.algorithm_id")
        if item_id in seen_ids:
            raise ContractError(f"{label} IDs must be unique")
        seen_ids.add(item_id)
        structured_steps = _validate_algorithm_steps(
            item["ordered_steps"],
            f"{item_label}.ordered_steps",
            known_evidence_ids=known_evidence_ids,
        )
        compatibility = _string_list(
            item["steps"], f"{item_label}.steps", nonempty=False
        )
        if compatibility != [step["action"] for step in structured_steps]:
            raise ContractError(
                f"{item_label}.steps must equal structured ordered-step actions"
            )
        principles.append(
            {
                "algorithm_id": item_id,
                "name": _text(item["name"], f"{item_label}.name"),
                "inputs": _string_list(
                    item["inputs"], f"{item_label}.inputs", nonempty=False
                ),
                "outputs": _string_list(
                    item["outputs"], f"{item_label}.outputs", nonempty=False
                ),
                "initialization": _text(
                    item["initialization"], f"{item_label}.initialization"
                ),
                "steps": compatibility,
                "ordered_steps": structured_steps,
                "update_rule": _text(
                    item["update_rule"], f"{item_label}.update_rule"
                ),
                "stopping_condition": _text(
                    item["stopping_condition"], f"{item_label}.stopping_condition"
                ),
                "complexity": _text(
                    item["complexity"], f"{item_label}.complexity"
                ),
                "numerical_risks": _string_list(
                    item["numerical_risks"],
                    f"{item_label}.numerical_risks",
                    nonempty=False,
                ),
                "locator": _text(item["locator"], f"{item_label}.locator"),
                "claim_ids": _known_claim_refs(
                    item["claim_ids"], f"{item_label}.claim_ids", known_claim_ids
                ),
                "origin": _origin(item["origin"], f"{item_label}.origin"),
            }
        )
    return {
        **metadata,
        "not_applicable_reason": reason,
        "objective": _text(group["objective"], f"{label}.objective"),
        "state_variables": _string_list(
            group["state_variables"], f"{label}.state_variables", nonempty=False
        ),
        "ordered_steps": ordered_steps,
        "invariants": _string_list(
            group["invariants"], f"{label}.invariants", nonempty=False
        ),
        "failure_modes": _string_list(
            group["failure_modes"], f"{label}.failure_modes", nonempty=False
        ),
        "principles": principles,
    }


def validate_input(value: Any) -> dict[str, Any]:
    payload = _dict(value, "root")
    _exact_keys(payload, TOP_LEVEL_KEYS, "root")
    if payload["schema"] != INPUT_SCHEMA:
        raise ContractError(f"root.schema must be {INPUT_SCHEMA}")
    understanding_binding = _validate_understanding_binding(
        payload["understanding_binding"]
    )

    source = _dict(payload["source_binding"], "source_binding")
    _exact_keys(source, SOURCE_BINDING_KEYS, "source_binding")
    year = source["year"]
    if type(year) is not int or not 1000 <= year <= 9999:
        raise ContractError("source_binding.year must be an integer between 1000 and 9999")
    if source["agent_inferences_explicit"] is not True:
        raise ContractError("source_binding.agent_inferences_explicit must be true")
    normalized_source = {
        "source_id": _id(source["source_id"], "source_binding.source_id"),
        "canonical_title": _text(
            source["canonical_title"], "source_binding.canonical_title"
        ),
        "authors": _string_list(source["authors"], "source_binding.authors"),
        "year": year,
        "venue": _text(source["venue"], "source_binding.venue"),
        "stable_identifier": _text(
            source["stable_identifier"], "source_binding.stable_identifier"
        ),
        "publication_status": _text(
            source["publication_status"], "source_binding.publication_status"
        ),
        "source_artifact_sha256": _sha256(
            source["source_artifact_sha256"],
            "source_binding.source_artifact_sha256",
        ),
        "source_bundle_id": _id(
            source["source_bundle_id"], "source_binding.source_bundle_id"
        ),
        "source_bundle_digest": _sha256(
            source["source_bundle_digest"], "source_binding.source_bundle_digest"
        ),
        "reading_dossier_id": _id(
            source["reading_dossier_id"], "source_binding.reading_dossier_id"
        ),
        "reading_dossier_digest": _sha256(
            source["reading_dossier_digest"],
            "source_binding.reading_dossier_digest",
        ),
        "paper_card_ref": _id(
            source["paper_card_ref"], "source_binding.paper_card_ref"
        ),
        "evidence_ledger_ref": _id(
            source["evidence_ledger_ref"], "source_binding.evidence_ledger_ref"
        ),
        "agent_inferences_explicit": True,
    }

    coverage = _dict(payload["coverage"], "coverage")
    _exact_keys(coverage, COVERAGE_KEYS, "coverage")
    access_level = _text(coverage["access_level"], "coverage.access_level")
    if access_level not in ACCESS_LEVELS:
        raise ContractError("coverage.access_level is unsupported")
    reading_depth = _text(coverage["reading_depth"], "coverage.reading_depth")
    if reading_depth not in READING_DEPTHS:
        raise ContractError("coverage.reading_depth is unsupported")
    claims = [
        _validate_claim(item, index)
        for index, item in enumerate(_list(coverage["claims"], "coverage.claims"))
    ]
    claim_ids = [claim["claim_id"] for claim in claims]
    if len(claim_ids) != len(set(claim_ids)):
        raise ContractError("claim IDs must be unique")
    known_claim_ids = set(claim_ids)
    known_evidence_ids = {
        evidence["evidence_id"]
        for claim in claims
        for evidence in claim["evidence"]
    }

    executive = _dict(payload["executive_summary"], "executive_summary")
    _exact_keys(executive, EXECUTIVE_SUMMARY_KEYS, "executive_summary")
    executive_claim_ids = _known_claim_refs(
        executive["claim_ids"], "executive_summary.claim_ids", known_claim_ids
    )
    normalized_executive = {
        "research_retrieval_title": _retrieval_title(
            executive["research_retrieval_title"],
            "executive_summary.research_retrieval_title",
        ),
        "summary": _text(executive["summary"], "executive_summary.summary"),
        "claim_ids": executive_claim_ids,
    }

    applicability = _dict(payload["applicability"], "applicability")
    _exact_keys(applicability, APPLICABILITY_KEYS, "applicability")
    normalized_applicability = {
        **_validate_domain_metadata(
            applicability, "applicability", known_evidence_ids
        ),
        "primary_use_case": _text(
            applicability["primary_use_case"], "applicability.primary_use_case"
        ),
        "applies_when": _string_list(
            applicability["applies_when"],
            "applicability.applies_when",
            nonempty=applicability["status"] == "applicable",
        ),
        "does_not_apply_when": _string_list(
            applicability["does_not_apply_when"],
            "applicability.does_not_apply_when",
            nonempty=False,
        ),
    }

    conclusion = _dict(payload["conclusion"], "conclusion")
    _exact_keys(conclusion, CONCLUSION_KEYS, "conclusion")
    conclusion_claim_ids = _known_claim_refs(
        conclusion["claim_ids"], "conclusion.claim_ids", known_claim_ids
    )
    confidence = _text(conclusion["confidence"], "conclusion.confidence")
    if confidence not in CONFIDENCE_LEVELS:
        raise ContractError("conclusion.confidence is unsupported")
    normalized_conclusion = {
        **_validate_domain_metadata(conclusion, "conclusion", known_evidence_ids),
        "statement": _text(conclusion["statement"], "conclusion.statement"),
        "claim_ids": conclusion_claim_ids,
        "confidence": confidence,
        "confidence_rationale": _text(
            conclusion["confidence_rationale"], "conclusion.confidence_rationale"
        ),
    }
    title_forbidden_values = {
        str(normalized_source[key])
        for key in (
            "source_id",
            "stable_identifier",
            "source_artifact_sha256",
            "source_bundle_id",
            "source_bundle_digest",
            "reading_dossier_id",
            "reading_dossier_digest",
            "paper_card_ref",
            "evidence_ledger_ref",
        )
    }
    title = normalized_executive["research_retrieval_title"]
    if any(value and value in title for value in title_forbidden_values):
        raise ContractError(
            "executive_summary.research_retrieval_title contains a provenance identifier"
        )
    normalized_conclusion["relations"] = sorted(
        {
            claim["relation"]
            for claim in claims
            if claim["claim_id"] in conclusion_claim_ids
        }
    )

    workflow = _dict(payload["workflow"], "workflow")
    _exact_keys(workflow, WORKFLOW_KEYS, "workflow")
    workflow_metadata = _validate_domain_metadata(
        workflow, "workflow", known_evidence_ids
    )
    steps: list[dict[str, Any]] = []
    step_ids: set[str] = set()
    for index, raw_step in enumerate(
        _list(
            workflow["steps"],
            "workflow.steps",
            nonempty=workflow_metadata["status"] == "applicable",
        )
    ):
        label = f"workflow.steps[{index}]"
        step = _dict(raw_step, label)
        _exact_keys(step, WORKFLOW_STEP_KEYS, label)
        step_id = _id(step["step_id"], f"{label}.step_id")
        if step_id in step_ids:
            raise ContractError("workflow step IDs must be unique")
        step_ids.add(step_id)
        steps.append(
            {
                "step_id": step_id,
                "action": _text(step["action"], f"{label}.action"),
                "output": _text(step["output"], f"{label}.output"),
                "checks": _string_list(
                    step["checks"], f"{label}.checks", nonempty=False
                ),
            }
        )
    normalized_workflow = {
        **workflow_metadata,
        "inputs": _string_list(
            workflow["inputs"],
            "workflow.inputs",
            nonempty=workflow_metadata["status"] == "applicable",
        ),
        "preconditions": _string_list(
            workflow["preconditions"], "workflow.preconditions", nonempty=False
        ),
        "steps": steps,
        "outputs": _string_list(
            workflow["outputs"],
            "workflow.outputs",
            nonempty=workflow_metadata["status"] == "applicable",
        ),
        "data_flow": _string_list(
            workflow["data_flow"], "workflow.data_flow", nonempty=False
        ),
        "graph": _validate_workflow_graph(
            workflow["graph"],
            "workflow.graph",
            require_endpoints=workflow_metadata["status"] == "applicable",
        ),
    }

    mathematics = _validate_mathematical_principles(
        payload["mathematical_principles"],
        "mathematical_principles",
        known_claim_ids=known_claim_ids,
        known_evidence_ids=known_evidence_ids,
    )
    algorithm = _validate_algorithmic_principles(
        payload["algorithmic_principles"],
        "algorithmic_principles",
        known_claim_ids=known_claim_ids,
        known_evidence_ids=known_evidence_ids,
    )

    boundaries: list[dict[str, Any]] = []
    boundary_ids: set[str] = set()
    for index, raw_boundary in enumerate(
        _list(coverage["boundaries"], "coverage.boundaries", nonempty=False)
    ):
        label = f"coverage.boundaries[{index}]"
        boundary = _dict(raw_boundary, label)
        _exact_keys(boundary, BOUNDARY_KEYS, label)
        boundary_id = _id(boundary["boundary_id"], f"{label}.boundary_id")
        if boundary_id in boundary_ids:
            raise ContractError("boundary IDs must be unique")
        boundary_ids.add(boundary_id)
        referenced_claim_ids = _claim_ids(boundary["claim_ids"], f"{label}.claim_ids")
        unknown = set(referenced_claim_ids) - known_claim_ids
        if unknown:
            raise ContractError(f"{label} references unknown claims: {sorted(unknown)}")
        boundaries.append(
            {
                "boundary_id": boundary_id,
                "condition": _text(boundary["condition"], f"{label}.condition"),
                "effect": _text(boundary["effect"], f"{label}.effect"),
                "locator": _text(boundary["locator"], f"{label}.locator"),
                "claim_ids": referenced_claim_ids,
            }
        )

    contributions: list[dict[str, Any]] = []
    contribution_ids: set[str] = set()
    domain_refs = {
        "applicability",
        "workflow",
        "mathematical_principles",
        "algorithmic_principles",
        "conclusion",
        *(step["step_id"] for step in normalized_workflow["steps"]),
        *(node["node_id"] for node in normalized_workflow["graph"]["nodes"]),
        *(
            operation["operation_id"]
            for operation in normalized_workflow["graph"]["operations"]
        ),
        *(step["step_id"] for step in mathematics["derivation_steps"]),
        *(principle["principle_id"] for principle in mathematics["principles"]),
        *(
            step["step_id"]
            for principle in mathematics["principles"]
            for step in principle["derivation_steps"]
        ),
        *(step["step_id"] for step in algorithm["ordered_steps"]),
        *(principle["algorithm_id"] for principle in algorithm["principles"]),
        *(
            step["step_id"]
            for principle in algorithm["principles"]
            for step in principle["ordered_steps"]
        ),
    }
    for index, raw_contribution in enumerate(
        _list(payload["contributions"], "contributions", nonempty=False)
    ):
        label = f"contributions[{index}]"
        contribution = _dict(raw_contribution, label)
        _exact_keys(contribution, CONTRIBUTION_KEYS, label)
        contribution_id = _id(
            contribution["contribution_id"], f"{label}.contribution_id"
        )
        if contribution_id in contribution_ids:
            raise ContractError("contribution IDs must be unique")
        contribution_ids.add(contribution_id)
        contribution_domain_refs = _id_sequence(
            contribution["domain_refs"], f"{label}.domain_refs"
        )
        unknown_domain_refs = set(contribution_domain_refs) - domain_refs
        if unknown_domain_refs:
            raise ContractError(
                f"{label}.domain_refs references unknown domains: "
                f"{sorted(unknown_domain_refs)}"
            )
        contributions.append(
            {
                "contribution_id": contribution_id,
                "statement": _text(contribution["statement"], f"{label}.statement"),
                "claim_ids": _known_claim_refs(
                    contribution["claim_ids"], f"{label}.claim_ids", known_claim_ids
                ),
                "evidence_ids": _known_evidence_refs(
                    contribution["evidence_ids"],
                    f"{label}.evidence_ids",
                    known_evidence_ids,
                ),
                "domain_refs": contribution_domain_refs,
            }
        )

    return {
        "schema": INPUT_SCHEMA,
        "understanding_binding": understanding_binding,
        "executive_summary": normalized_executive,
        "applicability": normalized_applicability,
        "workflow": normalized_workflow,
        "mathematical_principles": mathematics,
        "algorithmic_principles": algorithm,
        "conclusion": normalized_conclusion,
        "contributions": contributions,
        "source_binding": normalized_source,
        "coverage": {
            "access_level": access_level,
            "reading_depth": reading_depth,
            "verified_at": _timestamp(coverage["verified_at"], "coverage.verified_at"),
            "claims": claims,
            "boundaries": boundaries,
        },
    }


def _escape(value: Any) -> str:
    return html.escape(str(value), quote=True)


def _list_html(values: list[str], *, ordered: bool = False) -> str:
    tag = "ol" if ordered else "ul"
    items = "".join(f"<li>{_escape(value)}</li>" for value in values)
    return f"<{tag}>{items}</{tag}>"


def _domain_metadata_html(domain: dict[str, Any]) -> str:
    evidence = "、".join(domain["evidence_ids"]) or "无"
    missing = "；".join(domain["missing_information"]) or "无"
    return (
        f"<p><strong>状态：</strong>{_escape(domain['status'])}；"
        f"<strong>理由：</strong>{_escape(domain['rationale'])}；"
        f"<strong>Evidence ID：</strong>{_escape(evidence)}；"
        f"<strong>缺失信息：</strong>{_escape(missing)}</p>"
    )


def _math_steps_html(steps: list[dict[str, Any]]) -> str:
    if not steps:
        return "<p>无已记录的结构化推导步骤。</p>"
    items = []
    for step in steps:
        dependencies = "、".join(step["depends_on"]) or "无"
        evidence = "、".join(step["evidence_ids"]) or "无"
        items.append(
            "<li>"
            f"<strong>{_escape(step['step_id'])}：</strong>{_escape(step['statement'])}"
            f"<br><strong>依赖：</strong>{_escape(dependencies)}"
            f"<br><strong>来源性质：</strong>{_escape(step['origin'])}"
            f"<br><strong>定位：</strong>{_escape(step['locator'])}"
            f"<br><strong>Evidence ID：</strong>{_escape(evidence)}"
            "</li>"
        )
    return "<ol>" + "".join(items) + "</ol>"


def _algorithm_steps_html(steps: list[dict[str, Any]]) -> str:
    if not steps:
        return "<p>无已记录的结构化算法步骤。</p>"
    items = []
    for step in steps:
        dependencies = "、".join(step["depends_on"]) or "无"
        consumes = "、".join(step["consumes"]) or "无"
        produces = "、".join(step["produces"]) or "无"
        evidence = "、".join(step["evidence_ids"]) or "无"
        items.append(
            "<li>"
            f"<strong>{_escape(step['step_id'])}：</strong>{_escape(step['action'])}"
            f"<br><strong>依赖：</strong>{_escape(dependencies)}"
            f"<br><strong>消费：</strong>{_escape(consumes)}"
            f"<br><strong>产生：</strong>{_escape(produces)}"
            f"<br><strong>来源性质：</strong>{_escape(step['origin'])}"
            f"<br><strong>定位：</strong>{_escape(step['locator'])}"
            f"<br><strong>Evidence ID：</strong>{_escape(evidence)}"
            "</li>"
        )
    return "<ol>" + "".join(items) + "</ol>"


def _scope_text(scope: dict[str, list[str]]) -> str:
    fields = [
        ("假设", scope["assumptions"]),
        ("条件", scope["conditions"]),
        ("单位", scope["units"]),
        ("排除", scope["exclusions"]),
    ]
    return "；".join(
        f"{label}：{'、'.join(values) if values else '无显式项'}"
        for label, values in fields
    )


def render_html(normalized: dict[str, Any]) -> str:
    source = normalized["source_binding"]
    executive = normalized["executive_summary"]
    applicability = normalized["applicability"]
    conclusion = normalized["conclusion"]
    coverage = normalized["coverage"]
    workflow = normalized["workflow"]
    lines = [
        (
            f'<div data-schema-version="{ZOTERO_NOTE_SCHEMA_VERSION}" '
            f'data-note-contract="{OUTPUT_SCHEMA}">'
        ),
        f"<h1>{_escape(executive['research_retrieval_title'])}</h1>",
        f"<h2>{PYRAMID_SECTIONS[0]}</h2>",
        (
            f"<p><strong>执行摘要：</strong>{_escape(executive['summary'])}；"
            "<strong>摘要 Claim ID：</strong>"
            f"{_escape('、'.join(executive['claim_ids']))}</p>"
        ),
        _domain_metadata_html(applicability),
        (
            f"<p><strong>适用场景：</strong>"
            f"{_escape(applicability['primary_use_case'])}</p>"
        ),
        "<h3>适用条件</h3>",
        _list_html(applicability["applies_when"]),
        "<h3>不适用条件</h3>",
        _list_html(applicability["does_not_apply_when"]),
        _domain_metadata_html(conclusion),
        f"<p><strong>条件化结论：</strong>{_escape(conclusion['statement'])}</p>",
        (
            "<p><strong>证据关系：</strong>"
            f"{_escape('、'.join(conclusion['relations']))}；"
            "<strong>关联 Claim ID：</strong>"
            f"{_escape('、'.join(conclusion['claim_ids']))}</p>"
        ),
        (
            f"<p><strong>结论置信度：</strong>{_escape(conclusion['confidence'])}；"
            f"<strong>理由：</strong>{_escape(conclusion['confidence_rationale'])}</p>"
        ),
        f"<h2>{PYRAMID_SECTIONS[1]}</h2>",
        _domain_metadata_html(workflow),
        "<h3>输入</h3>",
        _list_html(workflow["inputs"]),
        "<h3>前置条件</h3>",
        _list_html(workflow["preconditions"]),
        "<h3>工作步骤</h3>",
        "<ol>",
    ]
    for step in workflow["steps"]:
        lines.append(
            "<li>"
            f"<strong>{_escape(step['step_id'])}：</strong>{_escape(step['action'])}"
            f"<br><strong>输出：</strong>{_escape(step['output'])}"
            f"<br><strong>检查：</strong>{_escape('；'.join(step['checks']))}"
            "</li>"
        )
    lines.extend(
        [
            "</ol>",
            "<h3>输出</h3>",
            _list_html(workflow["outputs"]),
            "<h3>数据流</h3>",
            _list_html(workflow["data_flow"], ordered=True),
            "<h3>工作流图节点</h3>",
            (
                "<table><thead><tr>"
                "<th>Node ID</th><th>Kind</th><th>Description</th>"
                "<th>Semantic Type</th><th>Representation</th><th>Format</th>"
                "<th>Shape</th><th>Unit</th>"
                "</tr></thead><tbody>"
            ),
        ]
    )
    for node in workflow["graph"]["nodes"]:
        row = [
            node["node_id"],
            node["kind"],
            node["description"],
            node["semantic_type"],
            node["representation"],
            node["format"],
            node["shape"],
            node["unit"],
        ]
        lines.append(
            "<tr>" + "".join(f"<td>{_escape(cell)}</td>" for cell in row) + "</tr>"
        )
    lines.extend(["</tbody></table>", "<h3>工作流图操作</h3>", "<ul>"])
    for operation in workflow["graph"]["operations"]:
        consumes = "、".join(operation["consumes"]) or "无"
        produces = "、".join(operation["produces"]) or "无"
        lines.append(
            "<li>"
            f"<strong>{_escape(operation['operation_id'])}：</strong>"
            f"{_escape(operation['operation'])}；"
            f"消费：{_escape(consumes)}；产生：{_escape(produces)}"
            "</li>"
        )
    if not workflow["graph"]["operations"]:
        lines.append("<li>无已记录的工作流图操作。</li>")
    lines.extend(["</ul>", f"<h2>{PYRAMID_SECTIONS[2]}</h2>"])
    mathematics = normalized["mathematical_principles"]
    lines.extend(
        [
            _domain_metadata_html(mathematics),
            "<h3>全局数学假设</h3>",
            _list_html(mathematics["assumptions"]),
            "<h3>全局数学结果</h3>",
            _list_html(mathematics["results"]),
            "<h3>结构化推导步骤</h3>",
            _math_steps_html(mathematics["derivation_steps"]),
        ]
    )
    if mathematics["status"] != "applicable":
        lines.append(
            "<p><strong>不可应用或未决原因：</strong>"
            f"{_escape(mathematics['not_applicable_reason'])}</p>"
        )
    else:
        for principle in mathematics["principles"]:
            lines.extend(
                [
                    f"<h3>{_escape(principle['principle_id'])}｜{_escape(principle['statement'])}</h3>",
                    f'<pre class="math">$${_escape(principle["latex"])}$$</pre>',
                    (
                        "<p><strong>符号：</strong>"
                        f"{_escape('；'.join(principle['symbols']))}；"
                        f"<strong>作用：</strong>{_escape(principle['role'])}；"
                        f"<strong>来源性质：</strong>{_escape(principle['origin'])}；"
                        "<strong>假设：</strong>"
                        f"{_escape('；'.join(principle['assumptions']))}；"
                        "<strong>结果：</strong>"
                        f"{_escape('；'.join(principle['results']))}；"
                        f"<strong>定位：</strong>{_escape(principle['locator'])}；"
                        "<strong>关联 Claim ID：</strong>"
                        f"{_escape('、'.join(principle['claim_ids']))}</p>"
                    ),
                    "<h3>推导</h3>",
                    _math_steps_html(principle["derivation_steps"]),
                ]
            )
    lines.append(f"<h2>{PYRAMID_SECTIONS[3]}</h2>")
    algorithm = normalized["algorithmic_principles"]
    lines.extend(
        [
            _domain_metadata_html(algorithm),
            f"<p><strong>目标：</strong>{_escape(algorithm['objective'])}</p>",
            "<h3>状态变量</h3>",
            _list_html(algorithm["state_variables"]),
            "<h3>不变量</h3>",
            _list_html(algorithm["invariants"]),
            "<h3>失败模式</h3>",
            _list_html(algorithm["failure_modes"]),
            "<h3>结构化算法步骤</h3>",
            _algorithm_steps_html(algorithm["ordered_steps"]),
        ]
    )
    if algorithm["status"] != "applicable":
        lines.append(
            "<p><strong>不可应用或未决原因：</strong>"
            f"{_escape(algorithm['not_applicable_reason'])}</p>"
        )
    else:
        for principle in algorithm["principles"]:
            lines.extend(
                [
                    f"<h3>{_escape(principle['algorithm_id'])}｜{_escape(principle['name'])}</h3>",
                    f"<p><strong>输入：</strong>{_escape('；'.join(principle['inputs']))}</p>",
                    f"<p><strong>输出：</strong>{_escape('；'.join(principle['outputs']))}</p>",
                    f"<p><strong>初始化：</strong>{_escape(principle['initialization'])}</p>",
                    "<h3>算法步骤</h3>",
                    _algorithm_steps_html(principle["ordered_steps"]),
                    f"<p><strong>更新规则：</strong>{_escape(principle['update_rule'])}</p>",
                    (
                        "<p><strong>停止条件：</strong>"
                        f"{_escape(principle['stopping_condition'])}</p>"
                    ),
                    f"<p><strong>复杂度：</strong>{_escape(principle['complexity'])}</p>",
                    (
                        "<p><strong>数值风险：</strong>"
                        f"{_escape('；'.join(principle['numerical_risks']))}</p>"
                    ),
                    (
                        f"<p><strong>来源性质：</strong>{_escape(principle['origin'])}；"
                        f"<strong>定位：</strong>{_escape(principle['locator'])}；"
                        "<strong>关联 Claim ID：</strong>"
                        f"{_escape('、'.join(principle['claim_ids']))}</p>"
                    ),
                ]
            )
    lines.extend(
        [
            f"<h2>{PYRAMID_SECTIONS[4]}</h2>",
            "<h3>核心贡献</h3>",
            "<ul>",
        ]
    )
    for contribution in normalized["contributions"]:
        lines.append(
            "<li>"
            f"<strong>{_escape(contribution['contribution_id'])}：</strong>"
            f"{_escape(contribution['statement'])}；"
            f"Claim ID：{_escape('、'.join(contribution['claim_ids']))}；"
            f"Evidence ID：{_escape('、'.join(contribution['evidence_ids']))}；"
            f"Domain ref：{_escape('、'.join(contribution['domain_refs']))}"
            "</li>"
        )
    if not normalized["contributions"]:
        lines.append("<li>无已记录的独立贡献项。</li>")
    lines.extend(
        [
            "</ul>",
            "<h3>关键主张与证据</h3>",
            "<table><thead><tr>"
            + "".join(f"<th>{_escape(header)}</th>" for header in CLAIM_HEADERS)
            + "</tr></thead><tbody>",
        ]
    )
    for claim in coverage["claims"]:
        evidence_text = "；".join(
            f"{item['evidence_id']}：{item['summary']}（{item['locator']}）"
            for item in claim["evidence"]
        ) or "not_tested：无来源证据记录"
        verification = (
            f"{claim['verifier_status']}；{claim['confidence']}："
            f"{claim['confidence_rationale']}"
        )
        row = [
            claim["claim_id"],
            claim["hypothesis_id"],
            claim["target_id"],
            claim["relation"],
            claim["nature"],
            claim["statement"],
            _scope_text(claim["scope"]),
            evidence_text,
            verification,
        ]
        lines.append("<tr>" + "".join(f"<td>{_escape(cell)}</td>" for cell in row) + "</tr>")
    lines.extend(["</tbody></table>", "<h3>失败边界</h3>", "<ul>"])
    for boundary in coverage["boundaries"]:
        lines.append(
            "<li>"
            f"<strong>{_escape(boundary['boundary_id'])}：</strong>"
            f"{_escape(boundary['condition'])} → {_escape(boundary['effect'])}；"
            f"定位：{_escape(boundary['locator'])}；"
            f"Claim ID：{_escape('、'.join(boundary['claim_ids']))}"
            "</li>"
        )
    if not coverage["boundaries"]:
        lines.append("<li>无已记录的 terminal 失败边界。</li>")
    lines.extend(
        [
            "</ul>",
            "<h3>来源与阅读状态</h3>",
            (
                f"<p><strong>原文标题：</strong>{_escape(source['canonical_title'])}<br>"
                f"<strong>作者：</strong>{_escape('；'.join(source['authors']))}<br>"
                f"<strong>年份：</strong>{source['year']}<br>"
                f"<strong>期刊或载体：</strong>{_escape(source['venue'])}<br>"
                f"<strong>DOI或稳定标识：</strong>{_escape(source['stable_identifier'])}<br>"
                f"<strong>版本与出版状态：</strong>{_escape(source['publication_status'])}<br>"
                f"<strong>访问层级：</strong>{_escape(coverage['access_level'])}<br>"
                f"<strong>全文SHA-256：</strong>{source['source_artifact_sha256']}<br>"
                f"<strong>阅读深度：</strong>{_escape(coverage['reading_depth'])}<br>"
                f"<strong>核验时间：</strong>{_escape(coverage['verified_at'])}</p>"
            ),
            "<h3>溯源</h3>",
            (
                f"<p><strong>Source ID：</strong>{_escape(source['source_id'])}<br>"
                f"<strong>Source bundle：</strong>{_escape(source['source_bundle_id'])}；"
                f"SHA-256：{source['source_bundle_digest']}<br>"
                f"<strong>Reading dossier：</strong>{_escape(source['reading_dossier_id'])}；"
                f"SHA-256：{source['reading_dossier_digest']}<br>"
                f"<strong>Paper card：</strong>{_escape(source['paper_card_ref'])}<br>"
                f"<strong>证据账本：</strong>{_escape(source['evidence_ledger_ref'])}<br>"
                "<strong>Agent推断：</strong>已显式标记。</p>"
            ),
            "<h3>理解与验证绑定</h3>",
            (
                "<p><strong>Understanding ID：</strong>"
                f"{_escape(normalized['understanding_binding']['understanding_id'])}<br>"
                "<strong>Understanding SHA-256：</strong>"
                f"{normalized['understanding_binding']['understanding_digest']}<br>"
                "<strong>Validation record ID：</strong>"
                f"{_escape(normalized['understanding_binding']['validation_record_id'])}<br>"
                "<strong>Validation record SHA-256：</strong>"
                f"{normalized['understanding_binding']['validation_record_digest']}</p>"
            ),
            "<h3>Zotero 写入边界</h3>",
            (
                "<p>仅允许写入 child note 的 note 字段；父条目 bibliographic fields "
                "title、shortTitle、creators、DOI、date、publicationTitle 必须保持不变。"
                "研究检索短标题仅存在于本笔记 H1，不得写入父条目 shortTitle。</p>"
            ),
            "</div>",
        ]
    )
    rendered = "\n".join(lines) + "\n"
    if len(rendered.encode("utf-8")) > MAX_HTML_UTF8_BYTES:
        raise ContractError(f"rendered HTML exceeds {MAX_HTML_UTF8_BYTES} UTF-8 bytes")
    return rendered


class _ProjectionParser(HTMLParser):
    ALLOWED_TAGS = {
        "div",
        "h1",
        "h2",
        "h3",
        "p",
        "strong",
        "ul",
        "ol",
        "li",
        "table",
        "thead",
        "tbody",
        "tr",
        "th",
        "td",
        "pre",
        "br",
    }
    VOID_TAGS = {"br"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.stack: list[str] = []
        self.roots: list[tuple[str, dict[str, str]]] = []
        self.headings: list[tuple[str, str]] = []
        self.tables: list[list[list[str]]] = []
        self.math_blocks: list[str] = []
        self.comments: list[str] = []
        self.text: list[str] = []
        self.errors: list[str] = []
        self._capture_tag: str | None = None
        self._capture: list[str] = []
        self._current_table: list[list[str]] | None = None
        self._current_row: list[str] | None = None
        self._current_cell: list[str] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        clean = {key: value or "" for key, value in attrs}
        if tag not in self.ALLOWED_TAGS:
            self.errors.append(f"PN-HTML-01: forbidden element <{tag}>")
        if not self.stack:
            self.roots.append((tag, clean))
        allowed_attrs: set[str]
        if tag == "div" and not self.stack:
            allowed_attrs = {"data-schema-version", "data-note-contract"}
        elif tag == "pre":
            allowed_attrs = {"class"}
        else:
            allowed_attrs = set()
        unexpected_attrs = set(clean) - allowed_attrs
        if unexpected_attrs:
            self.errors.append(
                f"PN-HTML-02: forbidden attributes on <{tag}>: {sorted(unexpected_attrs)}"
            )
        if tag == "pre" and clean.get("class") != "math":
            self.errors.append("PN-HTML-02: pre elements must have class='math'")
        if tag not in self.VOID_TAGS:
            self.stack.append(tag)
        if tag in {"h1", "h2", "h3"} or (tag == "pre" and clean.get("class") == "math"):
            self._capture_tag = tag
            self._capture = []
        if tag == "table":
            self._current_table = []
        elif tag == "tr" and self._current_table is not None:
            self._current_row = []
        elif tag in {"th", "td"} and self._current_row is not None:
            self._current_cell = []

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)
        if tag not in self.VOID_TAGS:
            self.handle_endtag(tag)

    def handle_endtag(self, tag: str) -> None:
        if tag in self.VOID_TAGS:
            self.errors.append(f"PN-HTML-03: void element <{tag}> has an end tag")
            return
        if not self.stack or self.stack[-1] != tag:
            self.errors.append(f"PN-HTML-03: mismatched closing tag </{tag}>")
            return
        captured = " ".join("".join(self._capture).split())
        if self._capture_tag == tag:
            if tag in {"h1", "h2", "h3"}:
                self.headings.append((tag, captured))
            elif tag == "pre":
                self.math_blocks.append("".join(self._capture).strip())
            self._capture_tag = None
            self._capture = []
        if tag in {"th", "td"} and self._current_cell is not None and self._current_row is not None:
            self._current_row.append(" ".join("".join(self._current_cell).split()))
            self._current_cell = None
        elif tag == "tr" and self._current_row is not None and self._current_table is not None:
            self._current_table.append(self._current_row)
            self._current_row = None
        elif tag == "table" and self._current_table is not None:
            self.tables.append(self._current_table)
            self._current_table = None
        self.stack.pop()

    def handle_data(self, data: str) -> None:
        self.text.append(data)
        if self._capture_tag is not None:
            self._capture.append(data)
        if self._current_cell is not None:
            self._current_cell.append(data)

    def handle_comment(self, data: str) -> None:
        self.comments.append(data)
        self.errors.append("PN-HTML-06: HTML comments are forbidden")


def validate_rendered_html(
    raw: str,
    *,
    expected_title: str | None = None,
) -> tuple[list[str], list[str], dict[str, Any]]:
    errors: list[str] = []
    warnings: list[str] = []
    parser = _ProjectionParser()
    try:
        parser.feed(raw)
        parser.close()
    except Exception as exc:
        return [f"PN-HTML-00: parse failure: {exc}"], warnings, {}
    errors.extend(parser.errors)
    for index, comment in enumerate(parser.comments, start=1):
        if PRIVATE_KEY_RE.search(comment):
            errors.append(
                f"PN-PRIVACY-02: HTML comment {index} contains a "
                "private-key-shaped token"
            )
        if POSIX_ABSOLUTE_PATH_RE.search(comment) or WINDOWS_ABSOLUTE_PATH_RE.search(
            comment
        ):
            errors.append(
                f"PN-PRIVACY-02: HTML comment {index} contains an absolute local path"
            )
    if parser.stack:
        errors.append("PN-HTML-03: unclosed HTML elements")
    if len(parser.roots) != 1:
        errors.append(f"PN-HTML-04: expected one root, found {len(parser.roots)}")
        root_attrs: dict[str, str] = {}
    else:
        root_tag, root_attrs = parser.roots[0]
        if root_tag != "div":
            errors.append("PN-HTML-04: root must be div")
        if root_attrs.get("data-schema-version") != ZOTERO_NOTE_SCHEMA_VERSION:
            errors.append("PN-HTML-04: root schema version must be 9")
        if root_attrs.get("data-note-contract") != OUTPUT_SCHEMA:
            errors.append(f"PN-HTML-04: root note contract must be {OUTPUT_SCHEMA}")
    h1 = [text for tag, text in parser.headings if tag == "h1"]
    h2 = [text for tag, text in parser.headings if tag == "h2"]
    if len(h1) != 1 or not h1[0]:
        errors.append("PN-TITLE-01: expected one nonempty h1")
        title = None
    else:
        title = h1[0]
        try:
            _retrieval_title(title, "rendered h1")
        except ContractError as exc:
            errors.append(f"PN-TITLE-02: {exc}")
        if expected_title is not None and title != expected_title:
            errors.append("PN-TITLE-04: h1 differs from the supplied retrieval title")
    if h2 != PYRAMID_SECTIONS:
        errors.append(
            f"PN-STRUCT-01: h2 sections must equal the pyramid contract: {PYRAMID_SECTIONS}"
        )
    body_text = " ".join("".join(parser.text).split())
    try:
        _privacy_guard(body_text, "rendered note")
    except ContractError as exc:
        errors.append(f"PN-PRIVACY-01: {exc}")
    if re.search(r"<(?:img|iframe|object|embed|a)\b", raw, flags=re.I):
        errors.append("PN-HTML-05: remote-capable resource or link element is forbidden")
    if len(raw.encode("utf-8")) > MAX_HTML_UTF8_BYTES:
        errors.append("PN-SIZE-01: rendered HTML exceeds the project byte limit")
    claim_ids: list[str] = []
    claim_table = next(
        (table for table in parser.tables if table and table[0] == CLAIM_HEADERS),
        None,
    )
    if claim_table is None or len(claim_table) < 2:
        errors.append("PN-EVIDENCE-01: exact claim table is missing or empty")
    else:
        for row_index, row in enumerate(claim_table[1:], start=1):
            if len(row) != len(CLAIM_HEADERS):
                errors.append(f"PN-EVIDENCE-02: claim row {row_index} has wrong width")
                continue
            claim_ids.append(row[0])
            if row[3] not in RELATIONS:
                errors.append(f"PN-EVIDENCE-03: claim row {row_index} has invalid relation")
            if row[4] not in NATURES:
                errors.append(f"PN-EVIDENCE-04: claim row {row_index} has invalid nature")
            if not row[1] or not row[2] or not row[6] or not row[7]:
                errors.append(f"PN-EVIDENCE-05: claim row {row_index} lost provenance fields")
    for index, math_block in enumerate(parser.math_blocks, start=1):
        if not math_block.startswith("$$") or not math_block.endswith("$$"):
            errors.append(f"PN-MATH-01: math block {index} must use $$...$$")
    full_text_match = re.search(
        r"全文SHA-256[：:]\s*([0-9a-f]{64})(?![0-9a-f])",
        body_text,
    )
    access_match = re.search(r"访问层级[：:]\s*([a-z_]+)", body_text)
    depth_match = re.search(r"阅读深度[：:]\s*([a-z]+)", body_text)
    preserve_statement = (
        "仅允许写入 child note 的 note 字段" in body_text
        and "不得写入父条目 shortTitle" in body_text
    )
    if not preserve_statement:
        errors.append("PN-WRITE-01: parent bibliographic-field preservation statement is missing")
    summary = {
        "schema_version": root_attrs.get("data-schema-version"),
        "note_contract": root_attrs.get("data-note-contract"),
        "title": title,
        "title_codepoints": len(title) if title is not None else None,
        "sections": h2,
        "claim_ids": sorted(claim_ids),
        "math_block_count": len(parser.math_blocks),
        "reading_depth": depth_match.group(1) if depth_match else None,
        "access_level": access_match.group(1) if access_match else None,
        "full_text_sha256": full_text_match.group(1) if full_text_match else None,
        "html_utf8_bytes": len(raw.encode("utf-8")),
        "parent_bibliographic_fields_preserved": preserve_statement,
    }
    return errors, warnings, summary


def validate_projection_manifest(
    value: Any,
    *,
    rendered: str | None = None,
    require_upstream_provenance: bool = False,
    verify_upstream_provenance: bool = False,
) -> dict[str, Any]:
    manifest = _dict(value, "projection manifest")
    has_upstream = UPSTREAM_PROVENANCE_KEY in manifest
    expected_keys = set(PROJECTION_MANIFEST_KEYS)
    if has_upstream:
        expected_keys.add(UPSTREAM_PROVENANCE_KEY)
    _exact_keys(manifest, expected_keys, "projection manifest")
    if (require_upstream_provenance or verify_upstream_provenance) and not has_upstream:
        raise ContractError(
            "projection manifest requires live upstream provenance for staging"
        )
    if manifest["schema"] != PROJECTION_SCHEMA:
        raise ContractError(f"projection manifest.schema must be {PROJECTION_SCHEMA}")
    if manifest["input_schema"] != INPUT_SCHEMA:
        raise ContractError(f"projection manifest.input_schema must be {INPUT_SCHEMA}")
    if manifest["output_schema"] != OUTPUT_SCHEMA:
        raise ContractError(f"projection manifest.output_schema must be {OUTPUT_SCHEMA}")
    normalized_input_sha256 = _sha256(
        manifest["normalized_input_sha256"],
        "projection manifest.normalized_input_sha256",
    )
    html_sha256 = _sha256(
        manifest["html_sha256"], "projection manifest.html_sha256"
    )
    understanding_binding = _validate_understanding_binding(
        manifest["understanding_binding"]
    )
    upstream_provenance = None
    if has_upstream:
        upstream_provenance = _validate_upstream_provenance(
            manifest[UPSTREAM_PROVENANCE_KEY]
        )
    title = _retrieval_title(
        manifest["retrieval_title"], "projection manifest.retrieval_title"
    )
    if manifest["retrieval_title_codepoints"] != len(title):
        raise ContractError("projection manifest retrieval title length is invalid")
    html_utf8_bytes = manifest["html_utf8_bytes"]
    if type(html_utf8_bytes) is not int or not 0 < html_utf8_bytes <= MAX_HTML_UTF8_BYTES:
        raise ContractError("projection manifest html_utf8_bytes is invalid")

    write_contract = _dict(manifest["write_contract"], "write_contract")
    _exact_keys(write_contract, WRITE_CONTRACT_KEYS, "write_contract")
    if write_contract != {
        "target_item_type": "note",
        "allowed_mutation_fields": ["note"],
        "forbidden_parent_fields": PARENT_BIBLIOGRAPHIC_FIELDS,
        "parent_bibliographic_fields_preserved": True,
        "zotero_write_performed": False,
    }:
        raise ContractError(
            "projection manifest write contract must preserve all parent "
            "bibliographic fields and allow only child-note note mutation"
        )

    validation = _dict(manifest["validation"], "projection manifest.validation")
    _exact_keys(
        validation,
        {"status", "warnings", "summary"},
        "projection manifest.validation",
    )
    if validation["status"] != "verified":
        raise ContractError("projection manifest validation status must be verified")
    if not isinstance(validation["warnings"], list) or not all(
        isinstance(item, str) for item in validation["warnings"]
    ):
        raise ContractError("projection manifest validation warnings are invalid")
    stored_summary = _dict(
        validation["summary"], "projection manifest.validation.summary"
    )
    if (
        stored_summary.get("note_contract") != OUTPUT_SCHEMA
        or stored_summary.get("title") != title
        or stored_summary.get("parent_bibliographic_fields_preserved") is not True
    ):
        raise ContractError("projection manifest validation summary is inconsistent")

    expected_digest = projection_content_digest(manifest)
    if manifest["projection_digest"] != expected_digest:
        raise ContractError("projection manifest projection_digest is invalid")
    expected_id = f"{PROJECTION_ID_PREFIX}{expected_digest[:16]}"
    if manifest["projection_id"] != expected_id:
        raise ContractError("projection manifest projection_id is invalid")

    if rendered is not None:
        rendered_bytes = rendered.encode("utf-8")
        if sha256_text(rendered) != html_sha256:
            raise ContractError("projection manifest HTML hash does not match")
        if len(rendered_bytes) != html_utf8_bytes:
            raise ContractError("projection manifest HTML byte length does not match")
        errors, warnings, summary = validate_rendered_html(
            rendered,
            expected_title=title,
        )
        if errors:
            raise ContractError(f"projection manifest HTML is invalid: {errors}")
        if warnings != validation["warnings"] or summary != stored_summary:
            raise ContractError("projection manifest HTML validation readback differs")

    if verify_upstream_provenance:
        assert upstream_provenance is not None
        regenerated = _regenerate_note_input(upstream_provenance)
        normalized_regenerated = validate_input(regenerated)
        if digest_value(normalized_regenerated) != normalized_input_sha256:
            raise ContractError(
                "regenerated NoteInput hash differs from projection manifest"
            )
        if normalized_regenerated["understanding_binding"] != understanding_binding:
            raise ContractError(
                "regenerated upstream IDs differ from projection manifest binding"
            )

    normalized_manifest = {
        **manifest,
        "normalized_input_sha256": normalized_input_sha256,
        "understanding_binding": understanding_binding,
        "html_sha256": html_sha256,
        "retrieval_title": title,
    }
    if upstream_provenance is not None:
        normalized_manifest[UPSTREAM_PROVENANCE_KEY] = upstream_provenance
    return normalized_manifest


def validate_projection_html_readback(
    value: Any,
    *,
    projection_source_html: str,
    staged_html: str,
    require_exact_staged_hash: bool,
    require_upstream_provenance: bool = False,
) -> dict[str, Any]:
    manifest = validate_projection_manifest(
        value,
        rendered=projection_source_html,
        require_upstream_provenance=require_upstream_provenance,
        verify_upstream_provenance=require_upstream_provenance,
    )
    title = str(manifest["retrieval_title"])
    errors, _warnings, summary = validate_rendered_html(
        staged_html,
        expected_title=title,
    )
    if errors:
        raise ContractError(f"staged projection readback is invalid: {errors}")
    if (
        summary.get("note_contract") != OUTPUT_SCHEMA
        or summary.get("parent_bibliographic_fields_preserved") is not True
    ):
        raise ContractError("staged projection readback lost its write boundary")
    if require_exact_staged_hash and sha256_text(staged_html) != manifest["html_sha256"]:
        raise ContractError("staged projection HTML hash differs from projection source")
    return manifest


def projection_manifest(
    normalized: dict[str, Any],
    rendered: str,
    *,
    upstream_provenance: dict[str, str] | None = None,
) -> dict[str, Any]:
    retrieval_title = normalized["executive_summary"]["research_retrieval_title"]
    errors, warnings, summary = validate_rendered_html(
        rendered,
        expected_title=retrieval_title,
    )
    if errors:
        raise ContractError(f"renderer produced invalid HTML: {errors}")
    manifest: dict[str, Any] = {
        "schema": PROJECTION_SCHEMA,
        "projection_id": "",
        "projection_digest": "",
        "input_schema": INPUT_SCHEMA,
        "output_schema": OUTPUT_SCHEMA,
        "normalized_input_sha256": digest_value(normalized),
        "understanding_binding": normalized["understanding_binding"],
        "html_sha256": sha256_text(rendered),
        "html_utf8_bytes": len(rendered.encode("utf-8")),
        "retrieval_title": retrieval_title,
        "retrieval_title_codepoints": len(retrieval_title),
        "write_contract": {
            "target_item_type": "note",
            "allowed_mutation_fields": ["note"],
            "forbidden_parent_fields": PARENT_BIBLIOGRAPHIC_FIELDS,
            "parent_bibliographic_fields_preserved": True,
            "zotero_write_performed": False,
        },
        "validation": {
            "status": "verified",
            "warnings": warnings,
            "summary": summary,
        },
    }
    if upstream_provenance is not None:
        manifest[UPSTREAM_PROVENANCE_KEY] = _validate_upstream_provenance(
            upstream_provenance
        )
    digest = projection_content_digest(manifest)
    manifest["projection_digest"] = digest
    manifest["projection_id"] = f"{PROJECTION_ID_PREFIX}{digest[:16]}"
    return validate_projection_manifest(manifest, rendered=rendered)


def build_projection(
    value: Any,
    *,
    upstream_provenance: dict[str, str] | None = None,
) -> tuple[dict[str, Any], str, dict[str, Any]]:
    normalized = validate_input(value)
    rendered = render_html(normalized)
    return (
        normalized,
        rendered,
        projection_manifest(
            normalized,
            rendered,
            upstream_provenance=upstream_provenance,
        ),
    )


def verify_projection(value: Any, rendered: str) -> dict[str, Any]:
    normalized = validate_input(value)
    expected = render_html(normalized)
    if rendered != expected:
        raise ContractError("HTML is not the deterministic projection of the supplied input")
    return projection_manifest(normalized, rendered)


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ContractError(f"cannot read input JSON: {exc}") from exc


def _load_learn_module() -> ModuleType:
    global _LEARN_MODULE
    if _LEARN_MODULE is not None:
        return _LEARN_MODULE
    spec = importlib.util.spec_from_file_location(
        "curate_live_paper_understanding",
        LEARN_SCRIPT_PATH,
    )
    if spec is None or spec.loader is None:
        raise ContractError(f"cannot load learn validator: {LEARN_SCRIPT_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    _LEARN_MODULE = module
    return module


def _canonical_artifact_path(value: str | Path, label: str) -> Path:
    path = Path(value).expanduser()
    if not path.is_absolute():
        raise ContractError(f"{label} path must be absolute")
    try:
        resolved = path.resolve(strict=True)
    except OSError as exc:
        raise ContractError(f"{label} path is unavailable: {exc}") from exc
    if not resolved.is_file():
        raise ContractError(f"{label} path must be a regular file")
    return resolved


def _validate_upstream_provenance(value: Any) -> dict[str, str]:
    provenance = _dict(value, "upstream provenance")
    _exact_keys(provenance, UPSTREAM_PROVENANCE_KEYS, "upstream provenance")
    normalized: dict[str, str] = {}
    for name in UPSTREAM_ARTIFACT_NAMES:
        path_key = f"{name}_path"
        hash_key = f"{name}_sha256"
        raw_path = provenance[path_key]
        if not isinstance(raw_path, str) or not raw_path:
            raise ContractError(f"upstream provenance.{path_key} must be nonempty")
        if not Path(raw_path).is_absolute():
            raise ContractError(f"upstream provenance.{path_key} must be absolute")
        normalized[path_key] = raw_path
        normalized[hash_key] = _sha256(
            provenance[hash_key],
            f"upstream provenance.{hash_key}",
        )
    return normalized


def _build_upstream_provenance(
    *,
    note_input_path: Path,
    understanding_path: Path,
    validation_record_path: Path,
    source_bundle_path: Path,
    source_path: Path,
    dossier_path: Path,
) -> dict[str, str]:
    paths = {
        "note_input": note_input_path,
        "understanding": understanding_path,
        "validation_record": validation_record_path,
        "source_bundle": source_bundle_path,
        "source": source_path,
        "dossier": dossier_path,
    }
    provenance: dict[str, str] = {}
    for name, raw_path in paths.items():
        path = _canonical_artifact_path(raw_path, name)
        content = path.read_bytes()
        provenance[f"{name}_path"] = str(path)
        provenance[f"{name}_sha256"] = sha256_bytes(content)
    return _validate_upstream_provenance(provenance)


def _read_bound_artifact(
    provenance: dict[str, str],
    name: str,
) -> tuple[Path, bytes]:
    path = _canonical_artifact_path(provenance[f"{name}_path"], name)
    if str(path) != provenance[f"{name}_path"]:
        raise ContractError(f"{name} path no longer resolves to its bound path")
    content = path.read_bytes()
    observed = sha256_bytes(content)
    expected = provenance[f"{name}_sha256"]
    if observed != expected:
        raise ContractError(f"{name} hash changed: {observed} != {expected}")
    return path, content


def _json_object_from_bytes(content: bytes, label: str) -> dict[str, Any]:
    try:
        value = json.loads(content.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ContractError(f"{label} is not readable JSON: {exc}") from exc
    return _dict(value, label)


def _regenerate_note_input(provenance: dict[str, str]) -> dict[str, Any]:
    provenance = _validate_upstream_provenance(provenance)
    note_input_path, note_input_bytes = _read_bound_artifact(
        provenance, "note_input"
    )
    understanding_path, understanding_bytes = _read_bound_artifact(
        provenance, "understanding"
    )
    validation_path, validation_bytes = _read_bound_artifact(
        provenance, "validation_record"
    )
    source_bundle_path, _ = _read_bound_artifact(provenance, "source_bundle")
    source_path, _ = _read_bound_artifact(provenance, "source")
    dossier_path, _ = _read_bound_artifact(provenance, "dossier")
    supplied_input = _json_object_from_bytes(note_input_bytes, "supplied NoteInput")
    understanding = _json_object_from_bytes(
        understanding_bytes, "PaperUnderstanding"
    )
    validation_record = _json_object_from_bytes(
        validation_bytes, "PaperUnderstandingValidation"
    )
    try:
        regenerated = _load_learn_module().validate_note_input_projection(
            understanding,
            validation_record,
            source_bundle_path=str(source_bundle_path),
            source_path=str(source_path),
            dossier_path=str(dossier_path),
        )
    except Exception as exc:
        raise ContractError(f"upstream live validation failed: {exc}") from exc
    regenerated = _dict(regenerated, "regenerated NoteInput")
    if supplied_input != regenerated:
        raise ContractError(
            "supplied NoteInput does not exactly match live regenerated NoteInput"
        )
    if str(note_input_path) != provenance["note_input_path"]:
        raise ContractError("supplied NoteInput path binding changed")
    if str(understanding_path) != provenance["understanding_path"]:
        raise ContractError("understanding path binding changed")
    if str(validation_path) != provenance["validation_record_path"]:
        raise ContractError("validation-record path binding changed")
    return regenerated


def build_live_projection(
    *,
    note_input_path: Path,
    understanding_path: Path,
    validation_record_path: Path,
    source_bundle_path: Path,
    source_path: Path,
    dossier_path: Path,
) -> tuple[dict[str, Any], str, dict[str, Any]]:
    provenance = _build_upstream_provenance(
        note_input_path=note_input_path,
        understanding_path=understanding_path,
        validation_record_path=validation_record_path,
        source_bundle_path=source_bundle_path,
        source_path=source_path,
        dossier_path=dossier_path,
    )
    regenerated = _regenerate_note_input(provenance)
    normalized, rendered, manifest = build_projection(
        regenerated,
        upstream_provenance=provenance,
    )
    validate_projection_manifest(
        manifest,
        rendered=rendered,
        require_upstream_provenance=True,
        verify_upstream_provenance=True,
    )
    return normalized, rendered, manifest


def _prepare_private_output(path: Path) -> Path:
    path = path.expanduser()
    if not path.is_absolute():
        raise ContractError("output paths must be absolute")
    parent = path.parent.resolve(strict=True)
    parent_stat = parent.stat()
    if not stat.S_ISDIR(parent_stat.st_mode) or parent_stat.st_uid != os.getuid():
        raise ContractError("output parent must be a current-user-owned directory")
    if path.exists() or path.is_symlink():
        raise ContractError(f"refusing to overwrite output: {path}")
    return parent / path.name


def _write_exclusive(path: Path, value: bytes) -> None:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(path, flags, 0o600)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(value)
    except Exception:
        path.unlink(missing_ok=True)
        raise


def _write_projection_pair(
    html_path: Path,
    manifest_path: Path,
    rendered: str,
    manifest: dict[str, Any],
) -> None:
    html_path = _prepare_private_output(html_path)
    manifest_path = _prepare_private_output(manifest_path)
    if html_path == manifest_path:
        raise ContractError("HTML and manifest outputs must differ")
    _write_exclusive(html_path, rendered.encode("utf-8"))
    try:
        _write_exclusive(
            manifest_path,
            json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2).encode("utf-8")
            + b"\n",
        )
    except Exception:
        html_path.unlink(missing_ok=True)
        raise


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    preview = commands.add_parser("preview", help="Validate and show the offline write contract")
    preview.add_argument("input", type=Path)
    render = commands.add_parser("render", help="Write private HTML and projection manifest")
    render.add_argument("input", type=Path)
    render.add_argument("--output", type=Path, required=True)
    render.add_argument("--manifest", type=Path, required=True)
    verify = commands.add_parser("verify", help="Verify an existing deterministic projection")
    verify.add_argument("input", type=Path)
    verify.add_argument("html", type=Path)
    for command in (preview, render, verify):
        command.add_argument("--understanding", type=Path, required=True)
        command.add_argument("--validation-record", type=Path, required=True)
        command.add_argument("--source-bundle", type=Path, required=True)
        command.add_argument("--source", type=Path, required=True)
        command.add_argument("--dossier", type=Path, required=True)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        normalized, rendered, manifest = build_live_projection(
            note_input_path=args.input,
            understanding_path=args.understanding,
            validation_record_path=args.validation_record,
            source_bundle_path=args.source_bundle,
            source_path=args.source,
            dossier_path=args.dossier,
        )
        if args.command == "verify":
            observed = args.html.expanduser().resolve(strict=True).read_text(
                encoding="utf-8"
            )
            if observed != rendered:
                raise ContractError(
                    "HTML is not the deterministic projection of live regenerated input"
                )
        elif args.command == "render":
            _write_projection_pair(args.output, args.manifest, rendered, manifest)
        del normalized
        print(json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2))
        return 0
    except (ContractError, OSError, UnicodeError) as exc:
        print(f"paper knowledge note failed: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
