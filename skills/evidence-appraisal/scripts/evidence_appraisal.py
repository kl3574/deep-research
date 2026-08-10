"""Fail-closed, replayable evidence-appraisal contracts.

A set is a candidate record.  It becomes an approved deliverable only when a
separate ReviewedEvidenceAppraisalAuthority/v1 artifact approves the exact
prepared request, review, candidate set, and candidate package projection.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import importlib
import json
import os
import re
import stat
import sys
import tempfile
from pathlib import Path
from typing import Any, Mapping, Sequence


class ContractError(ValueError):
    """Raised when an appraisal artifact violates its frozen contract."""


APPRAISAL_DOMAINS = (
    "provenance",
    "scope_match",
    "design",
    "measurement",
    "analysis",
    "independence",
    "reproducibility",
    "reporting_completeness",
)
KEY_DOMAINS = (
    "provenance",
    "scope_match",
    "design",
    "measurement",
    "analysis",
    "reproducibility",
)
DOMAIN_VERDICTS = {"satisfied", "concern", "defeated", "unresolved", "not_applicable"}
RELATION_VERDICTS = {"supports", "qualifies", "contradicts", "not_tested", "unresolved"}
OVERALL_VERDICTS = {
    "decisive_within_scope",
    "qualified_only",
    "context_only",
    "inadmissible",
    "unresolved",
}
REPRODUCIBILITY_STATES = {
    "reproduced",
    "not_reproduced",
    "partial",
    "not_tested",
    "no_result",
    "unresolved",
}
CHALLENGE_AXES = (
    "claim_definition",
    "evidence_identity",
    "scope_boundary",
    "study_design",
    "measurement",
    "analysis",
    "confounding",
    "reproducibility",
    "reporting",
)
ROUTES = {
    "scholar_discovery",
    "source_acquisition",
    "full_text_review",
    "code_data",
    "manual_experiment",
}
OPPOSITES = {
    "eq": "neq",
    "neq": "eq",
    "lt": "gte",
    "gte": "lt",
    "lte": "gt",
    "gt": "lte",
    "inside": "outside",
    "outside": "inside",
    "present": "absent",
    "absent": "present",
    "reproduced": "not_reproduced",
    "not_reproduced": "reproduced",
    "supports": "does_not_support",
    "does_not_support": "supports",
}
CANONICAL_OBSERVATION_GOAL_TEMPLATE = (
    "target_metric={target_metric}; comparator={comparator}; boundary={boundary}; "
    "observation={operator} {value_or_state}; claim_implication={claim_implication}"
)
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
COMPOUND_LOCATOR_RE = re.compile(
    r"(?:[,;|&]|\b(?:and|through|to)\b|\b(?:pp?|figs?|tables?)\.??\s*\d+\s*[-–]\s*\d+)",
    re.IGNORECASE,
)
UNICODE_SEPARATOR_RE = re.compile(r"[\u0085\u2028\u2029]")
SAFE_PATH_SEGMENT = r"[A-Za-z0-9_][A-Za-z0-9._-]*"
SAFE_FRAGMENT_SPAN = r"[A-Za-z0-9][A-Za-z0-9._:-]*(?:-[A-Za-z0-9][A-Za-z0-9._:-]*)?"
PATH_FRAGMENT_LOCATOR_RE = re.compile(
    rf"^{SAFE_PATH_SEGMENT}(?:/{SAFE_PATH_SEGMENT})*#(?:char|line|page|eq|fig|table|section)={SAFE_FRAGMENT_SPAN}$"
)
PLAIN_LOCATOR_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 .:_-]*$")
PLAIN_NUMERIC_RANGE_RE = re.compile(r"\b[A-Za-z][A-Za-z .:_-]*\s+\d+\s*[-–]\s*\d+\b")

OWNER_BINDING_SCHEMA = "OwnerArtifactBinding/v1"
OWNER_BUNDLE_SCHEMA = "EvidenceAppraisalOwnerBundle/v1"
OWNER_RECEIPT_SCHEMA = "OwnerArtifactValidationReceipt/v1"
OWNER_VALIDATION_CONTRACTS = {
    "source": {
        "artifact_schema": "PaperSourceBundle/v1",
        "owner_validator": "learn_from_papers.source_bundle.verify/v1",
        "status": "verified",
    },
    "dossier": {
        "artifact_schema": "PaperReadingDossier/v1",
        "owner_validator": "learn_from_papers.dossier.validate/v1",
        "status": "finalized",
    },
    "report": {
        "artifact_schema": "PaperReadingReportSet/v2",
        "owner_validator": "learn_from_papers.report_set.finalized/v2",
        "status": "finalized",
    },
    "attestation": {
        "artifact_schema": "VerificationAttestation/v1",
        "owner_validator": "learn_from_papers.external_attestation.verify/v1",
        "status": "passed",
    },
}

# Compatibility aliases retained for downstream callers that imported the old names.
DOMAINS = APPRAISAL_DOMAINS
DV = DOMAIN_VERDICTS
RV = RELATION_VERDICTS
OV = OVERALL_VERDICTS
RS = REPRODUCIBILITY_STATES
AXES = CHALLENGE_AXES


def _bad(message: str) -> None:
    raise ContractError(message)


def _map(value: Any, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        _bad(f"{name} must be an object")
    return value


def _list(value: Any, name: str) -> list[Any]:
    if not isinstance(value, list):
        _bad(f"{name} must be an array")
    return value


def _string(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        _bad(f"{name} must be a non-empty string")
    return value


def _stable_id(value: Any, name: str) -> str:
    text = _string(value, name)
    if any(char.isspace() for char in text):
        _bad(f"{name} must be a whitespace-free stable identifier")
    return text


def _sha(value: Any, name: str) -> str:
    text = _string(value, name)
    if not SHA256_RE.fullmatch(text):
        _bad(f"{name} must be a lowercase SHA-256 digest")
    return text


def _exact_keys(value: Mapping[str, Any], expected: set[str], name: str) -> None:
    if set(value) != expected:
        _bad(
            f"{name} keys must be exactly {sorted(expected)}; "
            f"missing={sorted(expected - set(value))}, extra={sorted(set(value) - expected)}"
        )


def canonical_json_bytes(value: Any) -> bytes:
    """Canonical bytes used for every digest in this module."""
    try:
        return json.dumps(
            value,
            ensure_ascii=True,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ContractError("artifact is not canonical JSON") from exc


def _digest(value: Any) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _content_id(prefix: str, semantic_digest: str) -> str:
    return f"{prefix}-{semantic_digest}"


def _content_id_matches(
    value: Any, prefix: str, semantic_digest: str, name: str
) -> None:
    if value != _content_id(prefix, semantic_digest):
        _bad(f"{name} must be content-addressed from its semantic digest")


def _copy_without(value: Mapping[str, Any], excluded: set[str]) -> dict[str, Any]:
    return {
        key: copy.deepcopy(item) for key, item in value.items() if key not in excluded
    }


def _validate_reviewer_context(value: Any, name: str) -> Mapping[str, Any]:
    value = _map(value, name)
    _exact_keys(value, {"reviewer_ref", "review_method", "reviewed_at"}, name)
    for key, item in value.items():
        _stable_id(item, f"{name}.{key}")
    return value


def _validate_owner_artifact_binding(value: Any, name: str) -> Mapping[str, Any]:
    value = _map(value, name)
    _exact_keys(
        value,
        {
            "schema",
            "artifact_schema",
            "role",
            "lineage_id",
            "id",
            "raw_file_sha256",
            "content_or_semantic_digest",
            "owner_validator",
            "status",
        },
        name,
    )
    if value["schema"] != OWNER_BINDING_SCHEMA:
        _bad(f"{name}.schema must be {OWNER_BINDING_SCHEMA}")
    role = value["role"]
    contract = OWNER_VALIDATION_CONTRACTS.get(role)
    if contract is None:
        _bad(f"{name}.role is unsupported")
    if (
        value["artifact_schema"] != contract["artifact_schema"]
        or value["owner_validator"] != contract["owner_validator"]
    ):
        _bad(f"{name} must use the exact allowlisted owner validator contract")
    if role == "attestation":
        if value["status"] not in {"passed", "not_tested"}:
            _bad(f"{name}.status must be passed or terminal not_tested")
    elif value["status"] != contract["status"]:
        _bad(f"{name} must use the exact allowlisted owner validator contract")
    _stable_id(value["lineage_id"], f"{name}.lineage_id")
    _stable_id(value["id"], f"{name}.id")
    _sha(value["raw_file_sha256"], f"{name}.raw_file_sha256")
    _sha(value["content_or_semantic_digest"], f"{name}.content_or_semantic_digest")
    return value


def _owner_binding_digests(bindings: Sequence[Mapping[str, Any]]) -> list[str]:
    return [_digest(binding) for binding in bindings]


def _validate_owner_artifact_bindings(value: Any, name: str) -> list[Mapping[str, Any]]:
    bindings = [
        _validate_owner_artifact_binding(item, f"{name}[{index}]")
        for index, item in enumerate(_list(value, name))
    ]
    if len(bindings) < 4:
        _bad(
            f"{name} must bind source, dossier, finalized report, and external attestation artifacts"
        )
    digests = _owner_binding_digests(bindings)
    if len(digests) != len(set(digests)):
        _bad(f"{name} must not repeat an owner artifact binding")
    groups: dict[str, list[Mapping[str, Any]]] = {}
    identities: dict[tuple[str, str, str], str] = {}
    for binding in bindings:
        lineage_id = binding["lineage_id"]
        groups.setdefault(lineage_id, []).append(binding)
        identity = (
            binding["role"],
            binding["id"],
            binding["raw_file_sha256"],
        )
        prior_lineage = identities.get(identity)
        if prior_lineage is not None:
            _bad(
                f"{name} must not reuse an owner artifact identity across or within lineages"
            )
        identities[identity] = lineage_id
    for lineage_id, group in groups.items():
        roles = [binding["role"] for binding in group]
        if (
            roles.count("source") != 1
            or roles.count("dossier") != 1
            or roles.count("report") != 1
            or roles.count("attestation") < 1
        ):
            _bad(
                f"{name} lineage {lineage_id} must contain one source, one dossier, one report, and one or more attestations"
            )
        for role in ("source", "dossier", "report", "attestation"):
            ids = [binding["id"] for binding in group if binding["role"] == role]
            if len(ids) != len(set(ids)):
                _bad(
                    f"{name} lineage {lineage_id} must not duplicate {role} owner artifacts"
                )
    return bindings


def _validate_owner_binding_digests(
    value: Any, bindings: Sequence[Mapping[str, Any]], name: str
) -> list[str]:
    digests = [_sha(item, f"{name}[]") for item in _list(value, name)]
    expected = _owner_binding_digests(bindings)
    if digests != expected:
        _bad(f"{name} must bind the exact ordered owner artifact universe")
    return digests


def _owner_modules() -> tuple[Any, Any]:
    scripts = Path(__file__).resolve().parents[2] / "learn-from-papers" / "scripts"
    if not scripts.is_dir():
        _bad("learn-from-papers owner validators are unavailable")
    scripts_text = str(scripts)
    if scripts_text not in sys.path:
        sys.path.insert(0, scripts_text)
    try:
        return (
            importlib.import_module("paper_source_bundle"),
            importlib.import_module("paper_reading_dossier"),
        )
    except Exception as exc:
        raise ContractError(
            "learn-from-papers owner validators are unavailable"
        ) from exc


def _runtime_path(value: Any, name: str, *, required: bool) -> Path | None:
    if value is None:
        if required:
            _bad(f"{name} is required for this owner artifact role")
        return None
    text = _string(value, name)
    path = Path(text)
    if not path.is_file() or path.is_symlink():
        _bad(f"{name} must name a real non-symlink file")
    return path


def _runtime_directory(value: Any, name: str, *, required: bool) -> Path | None:
    if value is None:
        if required:
            _bad(f"{name} is required for this owner artifact role")
        return None
    text = _string(value, name)
    path = Path(text)
    if not path.is_dir() or path.is_symlink():
        _bad(f"{name} must name a real non-symlink directory")
    return path


def _read_runtime_json(path: Path, name: str) -> tuple[bytes, Mapping[str, Any]]:
    try:
        raw = path.read_bytes()
        payload = json.loads(raw)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ContractError(f"{name} must be readable JSON") from exc
    return raw, _map(payload, name)


def _validate_owner_receipt(
    value: Any, binding: Mapping[str, Any], binding_digest: str, name: str
) -> None:
    value = _map(value, name)
    _exact_keys(
        value,
        {
            "schema",
            "binding_digest",
            "raw_file_sha256",
            "content_or_semantic_digest",
            "owner_validator",
            "status",
        },
        name,
    )
    if value["schema"] != OWNER_RECEIPT_SCHEMA or value["status"] != "passed":
        _bad(f"{name} must be a passed {OWNER_RECEIPT_SCHEMA}")
    expected = {
        "binding_digest": binding_digest,
        "raw_file_sha256": binding["raw_file_sha256"],
        "content_or_semantic_digest": binding["content_or_semantic_digest"],
        "owner_validator": binding["owner_validator"],
    }
    for key, expected_value in expected.items():
        if value[key] != expected_value:
            _bad(f"{name}.{key} must bind the exact owner artifact")


def _validate_owner_bundle(
    value: Any, bindings: Sequence[Mapping[str, Any]]
) -> list[dict[str, Any]]:
    bindings = _validate_owner_artifact_bindings(
        list(bindings), "owner_artifact_bindings"
    )
    bundle = _map(value, "owner_bundle")
    _exact_keys(bundle, {"schema", "artifacts"}, "owner_bundle")
    if bundle["schema"] != OWNER_BUNDLE_SCHEMA:
        _bad(f"owner_bundle.schema must be {OWNER_BUNDLE_SCHEMA}")
    expected_by_digest = {
        digest: binding
        for digest, binding in zip(_owner_binding_digests(bindings), bindings)
    }
    runtime_by_digest: dict[str, Mapping[str, Any]] = {}
    for index, runtime in enumerate(
        _list(bundle["artifacts"], "owner_bundle.artifacts")
    ):
        runtime = _map(runtime, f"owner_bundle.artifacts[{index}]")
        _exact_keys(
            runtime,
            {
                "binding_digest",
                "artifact_path",
                "verification_receipt_path",
                "source_path",
                "bundle_path",
                "verification_root",
            },
            f"owner_bundle.artifacts[{index}]",
        )
        digest = _sha(
            runtime["binding_digest"], f"owner_bundle.artifacts[{index}].binding_digest"
        )
        if digest not in expected_by_digest or digest in runtime_by_digest:
            _bad("owner_bundle must provide each exact binding once and no extras")
        runtime_by_digest[digest] = runtime
    if set(runtime_by_digest) != set(expected_by_digest):
        _bad("owner_bundle is missing an exact owner artifact runtime entry")

    source_bundle_module, dossier_module = _owner_modules()
    validated: list[dict[str, Any]] = []
    for binding_digest, binding in zip(_owner_binding_digests(bindings), bindings):
        runtime = runtime_by_digest[binding_digest]
        role = binding["role"]
        artifact_path = _runtime_path(
            runtime["artifact_path"], f"owner {role}.artifact_path", required=True
        )
        receipt_path = _runtime_path(
            runtime["verification_receipt_path"],
            f"owner {role}.verification_receipt_path",
            required=True,
        )
        assert artifact_path is not None and receipt_path is not None
        raw, artifact = _read_runtime_json(artifact_path, f"owner {role} artifact")
        if hashlib.sha256(raw).hexdigest() != binding["raw_file_sha256"]:
            _bad(f"owner {role} artifact raw_file_sha256 mismatch")
        _, receipt = _read_runtime_json(
            receipt_path, f"owner {role} verification receipt"
        )
        _validate_owner_receipt(
            receipt, binding, binding_digest, f"owner {role} verification receipt"
        )
        source_path = _runtime_path(
            runtime["source_path"],
            f"owner {role}.source_path",
            required=role in {"source", "dossier"},
        )
        bundle_path = _runtime_path(
            runtime["bundle_path"],
            f"owner {role}.bundle_path",
            required=role == "dossier",
        )
        verification_root = _runtime_directory(
            runtime["verification_root"],
            f"owner {role}.verification_root",
            required=role == "report",
        )
        if role not in {"source", "dossier"} and source_path is not None:
            _bad(f"owner {role}.source_path is not allowed")
        if role != "dossier" and bundle_path is not None:
            _bad(f"owner {role}.bundle_path is not allowed")
        if role != "report" and verification_root is not None:
            _bad(f"owner {role}.verification_root is not allowed")
        try:
            if role == "source":
                assert source_path is not None
                normalized = source_bundle_module.verify_bundle(
                    bundle=str(artifact_path), source=str(source_path)
                )
                actual_id, actual_digest = (
                    normalized["bundle_id"],
                    normalized["bundle_digest"],
                )
            elif role == "dossier":
                assert source_path is not None and bundle_path is not None
                normalized = dossier_module.validate_dossier(
                    dict(artifact), bundle=str(bundle_path), source=str(source_path)
                )
                actual_id, actual_digest = (
                    normalized["dossier_id"],
                    normalized["dossier_digest"],
                )
            elif role == "report":
                assert verification_root is not None
                normalized = dossier_module.validate_report_set_v2(
                    dict(artifact),
                    verification_root=verification_root,
                    require_finalized=True,
                )
                actual_id, actual_digest = (
                    normalized["report_set_id"],
                    normalized["report_set_digest"],
                )
            else:
                normalized = dossier_module._validate_verification_attestation(
                    dict(artifact), "owner attestation"
                )
                if normalized["origin"] != "external_verifier" or normalized[
                    "verdict"
                ] not in {"passed", "not_tested"}:
                    _bad(
                        "owner attestation must be an external passed or terminal not_tested attestation"
                    )
                actual_digest = _digest(normalized)
                actual_id = _content_id("attestation", actual_digest)
        except ContractError:
            raise
        except Exception as exc:
            raise ContractError(
                f"owner {role} validator rejected the supplied artifact"
            ) from exc
        if artifact.get("schema") != binding["artifact_schema"]:
            _bad(f"owner {role} artifact_schema mismatch")
        if (
            actual_id != binding["id"]
            or actual_digest != binding["content_or_semantic_digest"]
        ):
            _bad(f"owner {role} artifact identity or semantic digest mismatch")
        validated.append(
            {
                "binding": binding,
                "binding_digest": binding_digest,
                "normalized": normalized,
                "raw_file_sha256": hashlib.sha256(raw).hexdigest(),
                "artifact_path": artifact_path,
                "verification_root": verification_root,
            }
        )

    by_lineage: dict[str, list[dict[str, Any]]] = {}
    for item in validated:
        by_lineage.setdefault(item["binding"]["lineage_id"], []).append(item)
    for lineage_id, items in by_lineage.items():
        by_role: dict[str, list[dict[str, Any]]] = {}
        for item in items:
            by_role.setdefault(item["binding"]["role"], []).append(item)
        source = by_role["source"][0]
        dossier = by_role["dossier"][0]
        report = by_role["report"][0]
        if (
            dossier["normalized"]["source_bundle"]["bundle_id"]
            != source["binding"]["id"]
            or dossier["normalized"]["source_bundle"]["bundle_digest"]
            != source["binding"]["content_or_semantic_digest"]
            or report["normalized"]["source_bundle_id"] != source["binding"]["id"]
            or report["normalized"]["source_bundle_digest"]
            != source["binding"]["content_or_semantic_digest"]
            or report["normalized"]["dossier_id"] != dossier["binding"]["id"]
            or report["normalized"]["dossier_digest"]
            != dossier["binding"]["content_or_semantic_digest"]
        ):
            _bad(
                f"owner lineage {lineage_id} source, dossier, and report artifacts must form one exact LFP lineage"
            )
        verification_root = report["verification_root"]
        assert verification_root is not None
        references: dict[str, str] = {}
        for index, report_item in enumerate(report["normalized"]["reports"]):
            verification = _map(
                report_item.get("verification"),
                f"owner lineage {lineage_id} report verification[{index}]",
            )
            artifact_ref = _string(
                verification.get("artifact_ref"),
                f"owner lineage {lineage_id} report verification[{index}].artifact_ref",
            )
            raw_sha = _sha(
                verification.get("artifact_sha256"),
                f"owner lineage {lineage_id} report verification[{index}].artifact_sha256",
            )
            if raw_sha in references:
                _bad(
                    f"owner lineage {lineage_id} must not repeat a report verification attestation"
                )
            references[raw_sha] = artifact_ref
        attestations = by_role["attestation"]
        attestation_raw_shas = [item["raw_file_sha256"] for item in attestations]
        if (
            not references
            or len(attestation_raw_shas) != len(set(attestation_raw_shas))
            or set(references) != set(attestation_raw_shas)
        ):
            _bad(
                f"owner lineage {lineage_id} attestations must exactly cover finalized report-set verification artifacts"
            )
        for attestation in attestations:
            verdict = attestation["normalized"]["verdict"]
            if attestation["binding"]["status"] != verdict or verdict not in {
                "passed",
                "not_tested",
            }:
                _bad(
                    f"owner lineage {lineage_id} attestation status must exactly replay passed or terminal not_tested"
                )
            expected_path = (
                verification_root / references[attestation["raw_file_sha256"]]
            ).resolve()
            if attestation["artifact_path"].resolve() != expected_path:
                _bad(
                    f"owner lineage {lineage_id} attestation artifact must exactly match the finalized report verification ref"
                )
    return validated


def _validate_cycle_ref(
    value: Any, set_id: str, cycle: int, name: str
) -> Mapping[str, Any]:
    value = _map(value, name)
    _exact_keys(value, {"appraisal_set_id", "appraisal_set_digest", "cycle"}, name)
    if value["appraisal_set_id"] != set_id:
        _bad(f"{name}.appraisal_set_id must remain in the same lineage")
    _sha(value["appraisal_set_digest"], f"{name}.appraisal_set_digest")
    if type(value["cycle"]) is not int or value["cycle"] != cycle - 1:
        _bad(f"{name}.cycle must equal current cycle minus one")
    return value


def _validate_request(request: Any) -> Mapping[str, Any]:
    request = _map(request, "request")
    _exact_keys(
        request,
        {"schema", "appraisal_set_id", "cycle", "prior_cycle_ref", "relation_keys"},
        "request",
    )
    if request["schema"] != "EvidenceAppraisalRequest/v1":
        _bad("request.schema must be EvidenceAppraisalRequest/v1")
    set_id = _stable_id(request["appraisal_set_id"], "request.appraisal_set_id")
    cycle = request["cycle"]
    if type(cycle) is not int or cycle < 0:
        _bad("request.cycle must be a non-negative integer")
    if cycle == 0:
        if request["prior_cycle_ref"] is not None:
            _bad("request cycle zero must have null prior_cycle_ref")
    elif request["prior_cycle_ref"] is None:
        _bad("request later cycle must have prior_cycle_ref")
    else:
        _validate_cycle_ref(
            request["prior_cycle_ref"], set_id, cycle, "request.prior_cycle_ref"
        )
    identities: set[tuple[str, str]] = set()
    keys = _list(request["relation_keys"], "request.relation_keys")
    if not keys:
        _bad("request.relation_keys must not be empty")
    for index, item in enumerate(keys):
        item = _map(item, f"request.relation_keys[{index}]")
        _exact_keys(
            item, {"claim_ref", "evidence_ref"}, f"request.relation_keys[{index}]"
        )
        identity = (
            _stable_id(item["claim_ref"], f"request.relation_keys[{index}].claim_ref"),
            _stable_id(
                item["evidence_ref"], f"request.relation_keys[{index}].evidence_ref"
            ),
        )
        if identity in identities:
            _bad(
                "request.relation_keys must not contain duplicate claim/evidence pairs"
            )
        identities.add(identity)
    return request


def prepare_appraisal(
    request: Mapping[str, Any],
    prepared_request_file_sha256: str | None = None,
    owner_artifact_bindings: Sequence[Mapping[str, Any]] = (),
) -> dict[str, Any]:
    """Prepare a request and bind its canonical source-file SHA-256.

    API callers without a detached source file receive the canonical request SHA.
    The CLI may supply a raw source-file SHA-256 instead.
    """
    request = _validate_request(request)
    bindings = _validate_owner_artifact_bindings(
        list(owner_artifact_bindings), "owner_artifact_bindings"
    )
    request_digest = _digest(request)
    source_sha = prepared_request_file_sha256 or request_digest
    _sha(source_sha, "prepared_request_file_sha256")
    return {
        "schema": "EvidenceAppraisalPreparation/v1",
        "request": copy.deepcopy(dict(request)),
        "request_digest": request_digest,
        "prepared_request_file_sha256": source_sha,
        "owner_artifact_bindings": copy.deepcopy(bindings),
        "owner_artifact_binding_digests": _owner_binding_digests(bindings),
    }


def _validate_prepared(value: Any) -> Mapping[str, Any]:
    value = _map(value, "prepared")
    _exact_keys(
        value,
        {
            "schema",
            "request",
            "request_digest",
            "prepared_request_file_sha256",
            "owner_artifact_bindings",
            "owner_artifact_binding_digests",
        },
        "prepared",
    )
    if value["schema"] != "EvidenceAppraisalPreparation/v1":
        _bad("prepared.schema must be EvidenceAppraisalPreparation/v1")
    request = _validate_request(value["request"])
    if value["request_digest"] != _digest(request):
        _bad("prepared.request_digest mismatch")
    _sha(value["prepared_request_file_sha256"], "prepared.prepared_request_file_sha256")
    bindings = _validate_owner_artifact_bindings(
        value["owner_artifact_bindings"], "prepared.owner_artifact_bindings"
    )
    _validate_owner_binding_digests(
        value["owner_artifact_binding_digests"],
        bindings,
        "prepared.owner_artifact_binding_digests",
    )
    return value


def _validate_locator_atom(value: Any, name: str) -> tuple[str, str]:
    value = _map(value, name)
    _exact_keys(value, {"source_ref", "locator"}, name)
    source = _stable_id(value["source_ref"], f"{name}.source_ref")
    locator = _string(value["locator"], f"{name}.locator")
    if (
        locator != locator.strip()
        or "\n" in locator
        or UNICODE_SEPARATOR_RE.search(locator)
    ):
        _bad(f"{name}.locator must be one exact non-compound locator atom")
    if "/" in locator or "#" in locator:
        if not PATH_FRAGMENT_LOCATOR_RE.fullmatch(locator):
            _bad(
                f"{name}.locator with path/fragment must be a safe relative path plus one exact marker span"
            )
        return source, locator
    if (
        COMPOUND_LOCATOR_RE.search(locator)
        or PLAIN_NUMERIC_RANGE_RE.search(locator)
        or not PLAIN_LOCATOR_RE.fullmatch(locator)
    ):
        _bad(f"{name}.locator must be one exact non-compound locator atom")
    return source, locator


def _validate_locator_refs(
    value: Any, lineage: list[str], name: str
) -> list[tuple[str, str]]:
    atoms: list[tuple[str, str]] = []
    for index, item in enumerate(_list(value, name)):
        atom = _validate_locator_atom(item, f"{name}[{index}]")
        if atom[0] not in lineage:
            _bad(f"{name}[{index}].source_ref must appear in source_lineage")
        if atom in atoms:
            _bad(f"{name} must not duplicate locator atoms")
        atoms.append(atom)
    if not atoms:
        _bad(f"{name} must not be empty")
    return atoms


def compute_attestation_binding_digest(
    prepared: Mapping[str, Any],
    claim_ref: str,
    evidence_ref: str,
    locator_ref: Mapping[str, Any],
    reviewer_context: Mapping[str, Any],
) -> str:
    """Return the required non-opaque attestation binding digest."""
    prepared = _validate_prepared(prepared)
    locator = _validate_locator_atom(locator_ref, "locator_ref")
    context = _validate_reviewer_context(reviewer_context, "reviewer_context")
    return _digest(
        {
            "prepared_request_digest": prepared["request_digest"],
            "relation_ref": {
                "claim_ref": _stable_id(claim_ref, "claim_ref"),
                "evidence_ref": _stable_id(evidence_ref, "evidence_ref"),
            },
            "locator_ref": {"source_ref": locator[0], "locator": locator[1]},
            "reviewer_context": copy.deepcopy(dict(context)),
        }
    )


def _validate_attestations(
    value: Any,
    locator_atoms: list[tuple[str, str]],
    relation: Mapping[str, Any],
    prepared: Mapping[str, Any] | None,
    reviewer_context: Mapping[str, Any] | None,
    name: str,
) -> list[Mapping[str, Any]]:
    by_id: dict[str, Mapping[str, Any]] = {}
    result: list[Mapping[str, Any]] = []
    for index, item in enumerate(_list(value, name)):
        item = _map(item, f"{name}[{index}]")
        _exact_keys(
            item,
            {
                "attestation_id",
                "state",
                "decisive",
                "locator_ref",
                "binding_digest",
                "owner_attestation_binding_digest",
                "supersedes_ref",
            },
            f"{name}[{index}]",
        )
        attestation_id = _stable_id(
            item["attestation_id"], f"{name}[{index}].attestation_id"
        )
        if attestation_id in by_id or item["state"] not in {"passed", "failed"}:
            _bad(f"{name} must have unique IDs and passed/failed states")
        if type(item["decisive"]) is not bool or (
            item["state"] == "failed" and item["decisive"]
        ):
            _bad(f"{name}[{index}].decisive is invalid for its state")
        locator = _validate_locator_atom(
            item["locator_ref"], f"{name}[{index}].locator_ref"
        )
        if locator not in locator_atoms:
            _bad(f"{name}[{index}].locator_ref must be an exact relation locator atom")
        binding = _sha(item["binding_digest"], f"{name}[{index}].binding_digest")
        _sha(
            item["owner_attestation_binding_digest"],
            f"{name}[{index}].owner_attestation_binding_digest",
        )
        if prepared is not None and reviewer_context is not None:
            expected = compute_attestation_binding_digest(
                prepared,
                relation["claim_ref"],
                relation["evidence_ref"],
                item["locator_ref"],
                reviewer_context,
            )
            if binding != expected:
                _bad(f"{name}[{index}].binding_digest is opaque or unrelated")
        if item["supersedes_ref"] is not None:
            _stable_id(item["supersedes_ref"], f"{name}[{index}].supersedes_ref")
        by_id[attestation_id] = item
        result.append(item)
    for attestation_id, item in by_id.items():
        supersedes = item["supersedes_ref"]
        if item["state"] == "failed" and supersedes is not None:
            _bad(f"{name} failed attestation {attestation_id} cannot supersede another")
        if item["state"] == "passed" and supersedes is not None:
            prior = by_id.get(supersedes)
            if prior is None or prior["state"] != "failed":
                _bad(
                    f"{name} passed attestation must supersede a local failed attestation"
                )
            if (
                _validate_locator_atom(item["locator_ref"], "passed.locator_ref")
                != _validate_locator_atom(prior["locator_ref"], "failed.locator_ref")
                or item["binding_digest"] != prior["binding_digest"]
            ):
                _bad(
                    f"{name} failed attestation must be superseded by the exact same atom"
                )
    for attestation_id, item in by_id.items():
        if item["state"] == "failed":
            replacements = [
                candidate
                for candidate in by_id.values()
                if candidate["state"] == "passed"
                and candidate["supersedes_ref"] == attestation_id
            ]
            if len(replacements) != 1:
                _bad(
                    f"{name} every failed attestation needs one explicit passed supersession"
                )
    return result


def _validate_supersedes_ref(value: Any, name: str) -> Mapping[str, Any] | None:
    if value is None:
        return None
    value = _map(value, name)
    _exact_keys(
        value,
        {
            "appraisal_set_id",
            "appraisal_set_digest",
            "cycle",
            "appraisal_id",
            "semantic_digest",
        },
        name,
    )
    _stable_id(value["appraisal_set_id"], f"{name}.appraisal_set_id")
    _sha(value["appraisal_set_digest"], f"{name}.appraisal_set_digest")
    if type(value["cycle"]) is not int or value["cycle"] < 0:
        _bad(f"{name}.cycle must be non-negative")
    _stable_id(value["appraisal_id"], f"{name}.appraisal_id")
    _sha(value["semantic_digest"], f"{name}.semantic_digest")
    return value


def _validate_domain_semantics(
    relation: Mapping[str, Any], attestations: list[Mapping[str, Any]], name: str
) -> None:
    domains = relation["domain_verdicts"]
    defeated = any(value == "defeated" for value in domains.values())
    key_ready = all(
        domains[key] in {"satisfied", "not_applicable"} for key in KEY_DOMAINS
    )
    key_unresolved = any(domains[key] == "unresolved" for key in KEY_DOMAINS)
    passed_decisive = any(
        item["state"] == "passed" and item["decisive"] for item in attestations
    )
    overall = relation["overall"]
    verdict = relation["relation_verdict"]
    reproducibility = relation["reproducibility_state"]
    if reproducibility in {"partial", "no_result"} and (
        overall != "unresolved" or verdict != "unresolved"
    ):
        _bad(f"{name} partial/no_result must remain unresolved")
    if defeated:
        if overall != "inadmissible":
            _bad(f"{name} defeated domain requires inadmissible overall")
        if verdict not in {"unresolved", "not_tested"}:
            _bad(f"{name} inadmissible evidence cannot assert a relation verdict")
        return
    if overall == "inadmissible":
        _bad(f"{name} inadmissible overall requires a defeated domain")
    if overall == "decisive_within_scope":
        if verdict not in {"supports", "contradicts"}:
            _bad(
                f"{name} decisive overall requires supports or contradicts relation verdict"
            )
        if not key_ready or key_unresolved:
            _bad(
                f"{name} decisive overall requires every key domain satisfied or not_applicable"
            )
        if reproducibility != "reproduced" or not passed_decisive:
            _bad(
                f"{name} decisive overall requires a passed decisive attestation and reproduced state"
            )
        return
    if overall == "qualified_only":
        if verdict not in {"supports", "qualifies", "contradicts"}:
            _bad(f"{name} qualified_only has an inconsistent relation verdict")
        if key_ready and reproducibility == "reproduced" and passed_decisive:
            _bad(
                f"{name} fully decisive evidence must not be downgraded to qualified_only"
            )
        return
    if overall == "context_only":
        if relation["domain_verdicts"]["scope_match"] not in {
            "concern",
            "unresolved",
            "not_applicable",
        }:
            _bad(f"{name} context_only requires an explicit scope limitation")
        if verdict not in {
            "supports",
            "qualifies",
            "contradicts",
            "not_tested",
            "unresolved",
        }:
            _bad(f"{name} context_only has an invalid relation verdict")
        return
    if overall == "unresolved":
        if verdict not in {"unresolved", "not_tested"}:
            _bad(f"{name} unresolved overall has an inconsistent relation verdict")
        if not key_unresolved and reproducibility not in {
            "partial",
            "no_result",
            "not_tested",
            "unresolved",
        }:
            _bad(
                f"{name} unresolved overall requires an unresolved key domain or incomplete result"
            )
        return
    _bad(f"{name}.overall is invalid")


def _validate_relation_draft(
    value: Any,
    prepared: Mapping[str, Any] | None,
    reviewer_context: Mapping[str, Any] | None,
    name: str,
) -> Mapping[str, Any]:
    value = _map(value, name)
    _exact_keys(
        value,
        {
            "schema",
            "claim_ref",
            "evidence_ref",
            "supersedes_prior_appraisal_ref",
            "relation_verdict",
            "domain_verdicts",
            "overall",
            "scope",
            "source_lineage",
            "locator_refs",
            "attestation_refs",
            "reproducibility_state",
        },
        name,
    )
    if value["schema"] != "EvidenceAppraisal/v1":
        _bad(f"{name}.schema must be EvidenceAppraisal/v1")
    _stable_id(value["claim_ref"], f"{name}.claim_ref")
    _stable_id(value["evidence_ref"], f"{name}.evidence_ref")
    _validate_supersedes_ref(
        value["supersedes_prior_appraisal_ref"],
        f"{name}.supersedes_prior_appraisal_ref",
    )
    if value["relation_verdict"] not in RELATION_VERDICTS:
        _bad(f"{name}.relation_verdict is invalid")
    if value["overall"] not in OVERALL_VERDICTS:
        _bad(f"{name}.overall is invalid")
    if value["reproducibility_state"] not in REPRODUCIBILITY_STATES:
        _bad(f"{name}.reproducibility_state is invalid")
    domains = _map(value["domain_verdicts"], f"{name}.domain_verdicts")
    _exact_keys(domains, set(APPRAISAL_DOMAINS), f"{name}.domain_verdicts")
    if any(verdict not in DOMAIN_VERDICTS for verdict in domains.values()):
        _bad(f"{name}.domain_verdicts has an invalid value")
    scope = _map(value["scope"], f"{name}.scope")
    _exact_keys(scope, {"population", "setting", "boundary"}, f"{name}.scope")
    for key, item in scope.items():
        _string(item, f"{name}.scope.{key}")
    lineage = [
        _stable_id(item, f"{name}.source_lineage[]")
        for item in _list(value["source_lineage"], f"{name}.source_lineage")
    ]
    if not lineage or len(set(lineage)) != len(lineage):
        _bad(f"{name}.source_lineage must have unique source references")
    atoms = _validate_locator_refs(
        value["locator_refs"], lineage, f"{name}.locator_refs"
    )
    attestations = _validate_attestations(
        value["attestation_refs"],
        atoms,
        value,
        prepared,
        reviewer_context,
        f"{name}.attestation_refs",
    )
    _validate_domain_semantics(value, attestations, name)
    return value


def _relation_semantic(value: Mapping[str, Any]) -> dict[str, Any]:
    return _copy_without(value, {"appraisal_id", "semantic_digest"})


def _materialize_relation(
    draft: Mapping[str, Any],
    prepared: Mapping[str, Any],
    reviewer_context: Mapping[str, Any],
    name: str,
) -> dict[str, Any]:
    _validate_relation_draft(draft, prepared, reviewer_context, name)
    semantic = _relation_semantic(draft)
    semantic_digest = _digest(semantic)
    result = copy.deepcopy(semantic)
    result["appraisal_id"] = _content_id("appraisal", semantic_digest)
    result["semantic_digest"] = semantic_digest
    return result


def _validate_final_relation(value: Any, name: str) -> Mapping[str, Any]:
    value = _map(value, name)
    expected = {
        "schema",
        "appraisal_id",
        "semantic_digest",
        "claim_ref",
        "evidence_ref",
        "supersedes_prior_appraisal_ref",
        "relation_verdict",
        "domain_verdicts",
        "overall",
        "scope",
        "source_lineage",
        "locator_refs",
        "attestation_refs",
        "reproducibility_state",
    }
    _exact_keys(value, expected, name)
    draft = _relation_semantic(value)
    _validate_relation_draft(draft, None, None, name)
    digest = _digest(draft)
    if value["semantic_digest"] != digest:
        _bad(f"{name}.semantic_digest mismatch")
    _content_id_matches(
        value["appraisal_id"], "appraisal", digest, f"{name}.appraisal_id"
    )
    return value


def format_adversarial_observation_goal(
    target_metric: str,
    comparator: str,
    boundary: str,
    operator: str,
    value_or_state: Any,
    claim_implication: str,
) -> str:
    """Return the frozen goal string with fixed order and single spaces."""
    _string(target_metric, "target_metric")
    _string(comparator, "comparator")
    _string(boundary, "boundary")
    if operator not in OPPOSITES or claim_implication not in {"supports", "challenges"}:
        _bad("invalid observation goal operator or implication")
    if isinstance(value_or_state, (Mapping, list)):
        _bad("value_or_state must be an exact scalar")
    value_text = _string(str(value_or_state), "value_or_state")
    return CANONICAL_OBSERVATION_GOAL_TEMPLATE.format(
        target_metric=target_metric,
        comparator=comparator,
        boundary=boundary,
        operator=operator,
        value_or_state=value_text,
        claim_implication=claim_implication,
    )


def _pair_goals(pair: Mapping[str, Any], name: str) -> tuple[str, str]:
    pair = _map(pair, name)
    _exact_keys(pair, {"common", "confirm", "refute"}, name)
    common = _map(pair["common"], f"{name}.common")
    _exact_keys(common, {"target_metric", "comparator", "boundary"}, f"{name}.common")
    for key, item in common.items():
        _string(item, f"{name}.common.{key}")
    observations: list[Mapping[str, Any]] = []
    for side in ("confirm", "refute"):
        observation = _map(pair[side], f"{name}.{side}")
        _exact_keys(
            observation,
            {"operator", "value_or_state", "claim_implication"},
            f"{name}.{side}",
        )
        if observation["operator"] not in OPPOSITES or observation[
            "claim_implication"
        ] not in {"supports", "challenges"}:
            _bad(f"{name}.{side} has invalid operator or implication")
        if isinstance(observation["value_or_state"], (Mapping, list)):
            _bad(f"{name}.{side}.value_or_state must be scalar")
        observations.append(observation)
    confirm, refute = observations
    if (
        confirm["claim_implication"] != "supports"
        or refute["claim_implication"] != "challenges"
        or OPPOSITES[confirm["operator"]] != refute["operator"]
        or canonical_json_bytes(confirm["value_or_state"])
        != canonical_json_bytes(refute["value_or_state"])
    ):
        _bad(
            "adversarial observation pair must use complementary operators and one exact value_or_state"
        )
    return (
        format_adversarial_observation_goal(
            common["target_metric"],
            common["comparator"],
            common["boundary"],
            confirm["operator"],
            confirm["value_or_state"],
            confirm["claim_implication"],
        ),
        format_adversarial_observation_goal(
            common["target_metric"],
            common["comparator"],
            common["boundary"],
            refute["operator"],
            refute["value_or_state"],
            refute["claim_implication"],
        ),
    )


def _relation_targets(
    relations: Sequence[Mapping[str, Any]],
) -> dict[str, Mapping[str, Any]]:
    return {relation["appraisal_id"]: relation for relation in relations}


def _validate_relation_ref(
    value: Any, targets: Mapping[str, Mapping[str, Any]], name: str
) -> Mapping[str, Any]:
    value = _map(value, name)
    _exact_keys(
        value, {"claim_ref", "evidence_ref", "appraisal_id", "semantic_digest"}, name
    )
    claim_ref = _stable_id(value["claim_ref"], f"{name}.claim_ref")
    evidence_ref = _stable_id(value["evidence_ref"], f"{name}.evidence_ref")
    appraisal_id = _stable_id(value["appraisal_id"], f"{name}.appraisal_id")
    semantic_digest = _sha(value["semantic_digest"], f"{name}.semantic_digest")
    target = targets.get(appraisal_id)
    if target is None or (
        target["claim_ref"],
        target["evidence_ref"],
        target["semantic_digest"],
    ) != (claim_ref, evidence_ref, semantic_digest):
        _bad(f"{name} must target one exact appraisal version in this appraisal set")
    return value


def _challenge_semantic(value: Mapping[str, Any]) -> dict[str, Any]:
    return _copy_without(
        value,
        {
            "challenge_id",
            "semantic_digest",
            "appraisal_set_id",
            "appraisal_set_digest",
            "confirm_goal",
            "refute_goal",
        },
    )


def _materialize_challenge(
    value: Any, targets: Mapping[str, Mapping[str, Any]], name: str
) -> dict[str, Any]:
    value = _map(value, name)
    _exact_keys(
        value,
        {
            "schema",
            "axis",
            "route",
            "statement",
            "status",
            "relation_ref",
            "adversarial_observation_pair",
        },
        name,
    )
    if value["schema"] != "EvidenceChallenge/v1":
        _bad(f"{name}.schema must be EvidenceChallenge/v1")
    if (
        value["axis"] not in CHALLENGE_AXES
        or value["route"] not in ROUTES
        or value["status"] not in {"open", "resolved", "not_tested"}
    ):
        _bad(f"{name} has invalid axis, route, or status")
    _string(value["statement"], f"{name}.statement")
    _validate_relation_ref(value["relation_ref"], targets, f"{name}.relation_ref")
    confirm_goal, refute_goal = _pair_goals(
        value["adversarial_observation_pair"], f"{name}.adversarial_observation_pair"
    )
    semantic = copy.deepcopy(dict(value))
    semantic_digest = _digest(semantic)
    return {
        **semantic,
        "challenge_id": _content_id("challenge", semantic_digest),
        "semantic_digest": semantic_digest,
        "confirm_goal": confirm_goal,
        "refute_goal": refute_goal,
    }


def _validate_challenge(
    value: Any,
    set_id: str,
    set_digest: str,
    targets: Mapping[str, Mapping[str, Any]],
    name: str,
) -> Mapping[str, Any]:
    value = _map(value, name)
    expected = {
        "schema",
        "challenge_id",
        "semantic_digest",
        "appraisal_set_id",
        "appraisal_set_digest",
        "axis",
        "route",
        "statement",
        "status",
        "relation_ref",
        "adversarial_observation_pair",
        "confirm_goal",
        "refute_goal",
    }
    _exact_keys(value, expected, name)
    if (
        value["appraisal_set_id"] != set_id
        or value["appraisal_set_digest"] != set_digest
    ):
        _bad(f"{name} must bind the current finalized appraisal set")
    materialized = _materialize_challenge(_challenge_semantic(value), targets, name)
    for key in ("challenge_id", "semantic_digest", "confirm_goal", "refute_goal"):
        if value[key] != materialized[key]:
            _bad(f"{name}.{key} must be derived from exact semantic content")
    return value


def _need_semantic(value: Mapping[str, Any]) -> dict[str, Any]:
    return _copy_without(
        value, {"need_id", "semantic_digest", "confirm_goal", "refute_goal"}
    )


def _validate_domain_anchors(value: Any, route: str, name: str) -> list[str]:
    anchors = _list(value, name)
    if route != "scholar_discovery":
        if anchors != []:
            _bad(f"{name} must be empty for a non-scholar route")
        return []
    if not 2 <= len(anchors) <= 6:
        _bad(f"{name} must contain two to six scholar query domain anchors")
    normalized: list[str] = []
    for index, anchor in enumerate(anchors):
        text = _string(anchor, f"{name}[{index}]")
        if text != text.strip() or "\n" in text or len(text) > 120:
            _bad(f"{name}[{index}] must be one short normalized phrase")
        normalized.append(text)
    if len(normalized) != len(set(normalized)):
        _bad(f"{name} must not repeat a domain anchor")
    return normalized


def _materialize_need(
    value: Any, targets: Mapping[str, Mapping[str, Any]], name: str
) -> dict[str, Any]:
    value = _map(value, name)
    _exact_keys(
        value,
        {
            "schema",
            "route",
            "relation_ref",
            "domain_anchors",
            "adversarial_observation_pair",
        },
        name,
    )
    if value["schema"] != "TargetedEvidenceNeed/v1" or value["route"] not in ROUTES:
        _bad(f"{name} has invalid schema or route")
    _validate_relation_ref(value["relation_ref"], targets, f"{name}.relation_ref")
    _validate_domain_anchors(
        value["domain_anchors"], value["route"], f"{name}.domain_anchors"
    )
    confirm_goal, refute_goal = _pair_goals(
        value["adversarial_observation_pair"], f"{name}.adversarial_observation_pair"
    )
    semantic = copy.deepcopy(dict(value))
    semantic_digest = _digest(semantic)
    return {
        **semantic,
        "need_id": _content_id("need", semantic_digest),
        "semantic_digest": semantic_digest,
        "confirm_goal": confirm_goal,
        "refute_goal": refute_goal,
    }


def _need_set_core(value: Mapping[str, Any]) -> dict[str, Any]:
    return _copy_without(value, {"need_set_digest"})


def _validate_need_set(
    value: Any,
    set_id: str,
    set_digest: str,
    expected_ids: list[str],
    expected_digests: list[str],
    targets: Mapping[str, Mapping[str, Any]],
) -> Mapping[str, Any]:
    value = _map(value, "targeted_evidence_need_set")
    _exact_keys(
        value,
        {
            "schema",
            "appraisal_set_id",
            "appraisal_set_digest",
            "needs",
            "need_set_semantic_digest",
            "need_set_digest",
        },
        "targeted_evidence_need_set",
    )
    if (
        value["schema"] != "TargetedEvidenceNeedSet/v1"
        or value["appraisal_set_id"] != set_id
        or value["appraisal_set_digest"] != set_digest
    ):
        _bad("targeted_evidence_need_set must bind the current finalized appraisal set")
    ids: list[str] = []
    digests: list[str] = []
    for index, item in enumerate(
        _list(value["needs"], "targeted_evidence_need_set.needs")
    ):
        item = _map(item, f"targeted_evidence_need_set.needs[{index}]")
        expected = {
            "schema",
            "need_id",
            "semantic_digest",
            "route",
            "relation_ref",
            "domain_anchors",
            "adversarial_observation_pair",
            "confirm_goal",
            "refute_goal",
        }
        _exact_keys(item, expected, f"targeted_evidence_need_set.needs[{index}]")
        materialized = _materialize_need(
            _need_semantic(item), targets, f"targeted_evidence_need_set.needs[{index}]"
        )
        for key in ("need_id", "semantic_digest", "confirm_goal", "refute_goal"):
            if item[key] != materialized[key]:
                _bad(f"targeted_evidence_need_set.needs[{index}].{key} must be derived")
        ids.append(item["need_id"])
        digests.append(item["semantic_digest"])
    if ids != expected_ids or digests != expected_digests or len(ids) != len(set(ids)):
        _bad(
            "targeted_evidence_need_set must exactly match set content-addressed need IDs and digests"
        )
    if value["need_set_semantic_digest"] != _digest(digests):
        _bad("targeted_evidence_need_set.need_set_semantic_digest mismatch")
    if value["need_set_digest"] != _digest(_need_set_core(value)):
        _bad("targeted_evidence_need_set.need_set_digest mismatch")
    return value


def _review_file_projection(value: Mapping[str, Any]) -> dict[str, Any]:
    return _copy_without(
        value, {"independent_review_file_sha256", "independent_review_digest"}
    )


def _review_semantic(value: Mapping[str, Any]) -> dict[str, Any]:
    return _copy_without(value, {"independent_review_digest"})


def _validate_review(value: Any, prepared: Mapping[str, Any]) -> Mapping[str, Any]:
    value = _map(value, "independent_review")
    expected = {
        "schema",
        "prepared_request_digest",
        "prepared_request_file_sha256",
        "independent_review_file_sha256",
        "independent_review_digest",
        "reviewer_context",
        "owner_artifact_binding_digests",
        "relation_appraisals",
        "challenges",
        "targeted_evidence_needs",
    }
    _exact_keys(value, expected, "independent_review")
    if value["schema"] != "EvidenceAppraisalIndependentReview/v1":
        _bad("independent_review.schema must be EvidenceAppraisalIndependentReview/v1")
    if (
        value["prepared_request_digest"] != prepared["request_digest"]
        or value["prepared_request_file_sha256"]
        != prepared["prepared_request_file_sha256"]
    ):
        _bad(
            "independent_review must bind the exact prepared request digest and file SHA"
        )
    expected_file_sha = _digest(_review_file_projection(value))
    if value["independent_review_file_sha256"] != expected_file_sha:
        _bad(
            "independent_review_file_sha256 must hash the exact review file projection"
        )
    if value["independent_review_digest"] != _digest(_review_semantic(value)):
        _bad("independent_review_digest mismatch")
    _validate_reviewer_context(
        value["reviewer_context"], "independent_review.reviewer_context"
    )
    _validate_owner_binding_digests(
        value["owner_artifact_binding_digests"],
        prepared["owner_artifact_bindings"],
        "independent_review.owner_artifact_binding_digests",
    )
    return value


def _predecessor_summary(prior: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "appraisal_set_id": prior["appraisal_set_id"],
        "appraisal_set_digest": prior["appraisal_set_digest"],
        "cycle": prior["cycle"],
        "relation_appraisal_ids": [
            item["appraisal_id"] for item in prior["relation_appraisals"]
        ],
        "challenge_ids": copy.deepcopy(prior["challenge_ids"]),
        "challenge_semantic_digests": copy.deepcopy(
            prior["challenge_semantic_digests"]
        ),
        "targeted_evidence_need_ids": copy.deepcopy(
            prior["targeted_evidence_need_ids"]
        ),
        "targeted_evidence_need_semantic_digests": copy.deepcopy(
            prior["targeted_evidence_need_semantic_digests"]
        ),
        "owner_artifact_binding_digests": copy.deepcopy(
            prior["owner_artifact_binding_digests"]
        ),
    }


def _validate_predecessor_summary(
    value: Any, set_id: str, cycle: int, prior_ref: Mapping[str, Any], name: str
) -> Mapping[str, Any]:
    value = _map(value, name)
    expected = {
        "appraisal_set_id",
        "appraisal_set_digest",
        "cycle",
        "relation_appraisal_ids",
        "challenge_ids",
        "challenge_semantic_digests",
        "targeted_evidence_need_ids",
        "targeted_evidence_need_semantic_digests",
        "owner_artifact_binding_digests",
    }
    _exact_keys(value, expected, name)
    if (
        value["appraisal_set_id"] != set_id
        or value["appraisal_set_digest"] != prior_ref["appraisal_set_digest"]
        or value["cycle"] != cycle - 1
    ):
        _bad(f"{name} must retain the exact same-lineage predecessor")
    for field, prefix in (
        ("relation_appraisal_ids", "appraisal"),
        ("challenge_ids", "challenge"),
        ("targeted_evidence_need_ids", "need"),
    ):
        values = [
            _stable_id(item, f"{name}.{field}[]")
            for item in _list(value[field], f"{name}.{field}")
        ]
        if len(values) != len(set(values)):
            _bad(f"{name}.{field} has duplicate IDs")
        if prefix == "appraisal":
            continue
    for ids_field, digest_field, prefix in (
        ("challenge_ids", "challenge_semantic_digests", "challenge"),
        (
            "targeted_evidence_need_ids",
            "targeted_evidence_need_semantic_digests",
            "need",
        ),
    ):
        digests = [
            _sha(item, f"{name}.{digest_field}[]")
            for item in _list(value[digest_field], f"{name}.{digest_field}")
        ]
        if len(digests) != len(_list(value[ids_field], f"{name}.{ids_field}")):
            _bad(f"{name}.{digest_field} must align with {ids_field}")
        for item, digest in zip(value[ids_field], digests):
            _content_id_matches(item, prefix, digest, f"{name}.{ids_field}")
    owner_digests = [
        _sha(item, f"{name}.owner_artifact_binding_digests[]")
        for item in _list(
            value["owner_artifact_binding_digests"],
            f"{name}.owner_artifact_binding_digests",
        )
    ]
    if not owner_digests or len(owner_digests) != len(set(owner_digests)):
        _bad(
            f"{name}.owner_artifact_binding_digests must contain an exact non-empty owner universe"
        )
    return value


def _set_core(value: Mapping[str, Any]) -> dict[str, Any]:
    return _copy_without(value, {"appraisal_set_digest", "seal"})


def _validate_set(value: Any) -> dict[str, Any]:
    value = _map(value, "appraisal_set")
    expected = {
        "schema",
        "appraisal_set_id",
        "cycle",
        "prior_cycle_ref",
        "immutable_predecessor_refs",
        "relation_appraisals",
        "challenge_ids",
        "challenge_semantic_digests",
        "targeted_evidence_need_ids",
        "targeted_evidence_need_semantic_digests",
        "owner_artifact_bindings",
        "owner_artifact_binding_digests",
        "appraisal_set_digest",
        "seal",
    }
    _exact_keys(value, expected, "appraisal_set")
    if value["schema"] != "EvidenceAppraisalSet/v1":
        _bad("appraisal_set.schema must be EvidenceAppraisalSet/v1")
    set_id = _stable_id(value["appraisal_set_id"], "appraisal_set.appraisal_set_id")
    owner_bindings = _validate_owner_artifact_bindings(
        value["owner_artifact_bindings"], "appraisal_set.owner_artifact_bindings"
    )
    _validate_owner_binding_digests(
        value["owner_artifact_binding_digests"],
        owner_bindings,
        "appraisal_set.owner_artifact_binding_digests",
    )
    cycle = value["cycle"]
    if type(cycle) is not int or cycle < 0:
        _bad("appraisal_set.cycle must be a non-negative integer")
    if cycle == 0:
        if (
            value["prior_cycle_ref"] is not None
            or value["immutable_predecessor_refs"] != []
        ):
            _bad("appraisal_set cycle zero cannot have predecessor references")
    else:
        if value["prior_cycle_ref"] is None:
            _bad("appraisal_set later cycle requires prior_cycle_ref")
        prior_ref = _validate_cycle_ref(
            value["prior_cycle_ref"], set_id, cycle, "appraisal_set.prior_cycle_ref"
        )
        predecessors = _list(
            value["immutable_predecessor_refs"],
            "appraisal_set.immutable_predecessor_refs",
        )
        if len(predecessors) != 1:
            _bad(
                "appraisal_set later cycle requires exactly one immutable predecessor ref"
            )
        _validate_predecessor_summary(
            predecessors[0],
            set_id,
            cycle,
            prior_ref,
            "appraisal_set.immutable_predecessor_refs[0]",
        )
    relations = _list(value["relation_appraisals"], "appraisal_set.relation_appraisals")
    if not relations:
        _bad("appraisal_set.relation_appraisals must not be empty")
    identities: dict[tuple[str, str], list[Mapping[str, Any]]] = {}
    appraisal_ids: set[str] = set()
    for index, relation in enumerate(relations):
        relation = _validate_final_relation(
            relation, f"appraisal_set.relation_appraisals[{index}]"
        )
        if relation["appraisal_id"] in appraisal_ids:
            _bad("appraisal_set relation appraisal IDs must be unique")
        appraisal_ids.add(relation["appraisal_id"])
        identities.setdefault(
            (relation["claim_ref"], relation["evidence_ref"]), []
        ).append(relation)
    for identity, entries in identities.items():
        if len(entries) > 1:
            for index, relation in enumerate(entries[1:], start=1):
                ref = relation["supersedes_prior_appraisal_ref"]
                if ref is None or not any(
                    previous["appraisal_id"] == ref["appraisal_id"]
                    and previous["semantic_digest"] == ref["semantic_digest"]
                    for previous in entries[:index]
                ):
                    _bad(
                        f"appraisal_set duplicate relation {identity} requires exact prior appraisal supersession"
                    )
    for ids_key, digests_key, prefix in (
        ("challenge_ids", "challenge_semantic_digests", "challenge"),
        (
            "targeted_evidence_need_ids",
            "targeted_evidence_need_semantic_digests",
            "need",
        ),
    ):
        ids = [
            _stable_id(item, f"appraisal_set.{ids_key}[]")
            for item in _list(value[ids_key], f"appraisal_set.{ids_key}")
        ]
        digests = [
            _sha(item, f"appraisal_set.{digests_key}[]")
            for item in _list(value[digests_key], f"appraisal_set.{digests_key}")
        ]
        if (
            len(ids) != len(digests)
            or len(ids) != len(set(ids))
            or len(digests) != len(set(digests))
        ):
            _bad(
                f"appraisal_set.{ids_key}/{digests_key} must be aligned unique semantic content"
            )
        for item, digest in zip(ids, digests):
            _content_id_matches(item, prefix, digest, f"appraisal_set.{ids_key}")
    digest = _digest(_set_core(value))
    if value["appraisal_set_digest"] != digest:
        _bad("appraisal_set digest mismatch")
    seal = _map(value["seal"], "appraisal_set.seal")
    _exact_keys(seal, {"algorithm", "digest"}, "appraisal_set.seal")
    if seal["algorithm"] != "sha256" or seal["digest"] != digest:
        _bad("appraisal_set seal mismatch")
    return copy.deepcopy(dict(value))


def _check_supersession_against_prior(
    new_relations: list[dict[str, Any]], prior: Mapping[str, Any] | None, set_id: str
) -> None:
    prior_by_identity: dict[tuple[str, str], list[Mapping[str, Any]]] = {}
    if prior is not None:
        for item in prior["relation_appraisals"]:
            prior_by_identity.setdefault(
                (item["claim_ref"], item["evidence_ref"]), []
            ).append(item)
    for relation in new_relations:
        identity = (relation["claim_ref"], relation["evidence_ref"])
        ref = relation["supersedes_prior_appraisal_ref"]
        existing = prior_by_identity.get(identity, [])
        if not existing:
            if ref is not None:
                _bad(
                    "new relation may supersede only an existing same claim/evidence appraisal"
                )
            continue
        if ref is None:
            _bad(
                "same claim/evidence in a later cycle requires supersedes_prior_appraisal_ref"
            )
        latest = existing[-1]
        if (
            ref["appraisal_set_id"] != set_id
            or ref["appraisal_set_digest"] != prior["appraisal_set_digest"]
            or ref["cycle"] != prior["cycle"]
            or latest["appraisal_id"] != ref["appraisal_id"]
            or latest["semantic_digest"] != ref["semantic_digest"]
        ):
            _bad(
                "supersedes_prior_appraisal_ref must point to the latest exact predecessor appraisal"
            )


def _validate_selected_owner_attestation_coverage(
    relations: Sequence[Mapping[str, Any]],
    owner_artifacts: Sequence[Mapping[str, Any]],
    name: str,
) -> None:
    """Replay every selected owner attestation against its exact LFP subject."""
    _, dossier_module = _owner_modules()
    decisive_modes = set(dossier_module.DECISIVE_VERIFICATION_MODES)
    external_attestations = {
        item["binding_digest"]: item
        for item in owner_artifacts
        if item["binding"]["role"] == "attestation"
    }
    reports_by_attestation_sha: dict[str, tuple[str, Mapping[str, Any]]] = {}
    for item in owner_artifacts:
        if item["binding"]["role"] != "report":
            continue
        lineage_id = item["binding"]["lineage_id"]
        normalized = _map(item["normalized"], "owner report")
        for report_index, report in enumerate(
            _list(normalized.get("reports"), "owner report.reports")
        ):
            report = _map(report, f"owner report.reports[{report_index}]")
            verification = _map(
                report.get("verification"),
                f"owner report.reports[{report_index}].verification",
            )
            artifact_sha = _sha(
                verification.get("artifact_sha256"),
                f"owner report.reports[{report_index}].verification.artifact_sha256",
            )
            if artifact_sha in reports_by_attestation_sha:
                _bad("owner reports must not repeat a verification attestation SHA")
            reports_by_attestation_sha[artifact_sha] = (lineage_id, report)

    def owner_locator_matches(binding: Mapping[str, Any], locator: str) -> bool:
        path_match = re.fullmatch(r"pages/page-(\d{4})\.txt#char=(\d+)-(\d+)", locator)
        if path_match is not None:
            page, start_char, end_char = (int(value) for value in path_match.groups())
            return (
                binding["page"] == page
                and binding["start_char"] == start_char
                and binding["end_char"] == end_char
            )
        return locator == binding["exact_locator"]

    for index, relation in enumerate(relations):
        relation_name = f"{name}[{index}]"
        refs = _list(relation["attestation_refs"], f"{relation_name}.attestation_refs")
        if (
            relation["overall"] in {"decisive_within_scope", "qualified_only"}
            and not refs
        ):
            _bad(
                f"{relation_name} selected decisive or qualified appraisal requires a passed external owner attestation"
            )
        for ref_index, ref in enumerate(refs):
            ref = _map(ref, f"{relation_name}.attestation_refs[{ref_index}]")
            owner_digest = _sha(
                ref.get("owner_attestation_binding_digest"),
                f"{relation_name}.attestation_refs[{ref_index}].owner_attestation_binding_digest",
            )
            owner_attestation = external_attestations.get(owner_digest)
            if owner_attestation is None:
                _bad(
                    f"{relation_name}.attestation_refs[{ref_index}] must reference an exact external owner attestation binding"
                )
            binding = owner_attestation["binding"]
            if (
                binding["status"] != "passed"
                or owner_attestation["normalized"]["verdict"] != "passed"
            ):
                _bad(
                    f"{relation_name}.attestation_refs[{ref_index}] must reference an external passed owner attestation"
                )
            if binding["lineage_id"] not in relation["source_lineage"]:
                _bad(
                    f"{relation_name}.attestation_refs[{ref_index}] must reference an owner attestation in the relation source_lineage"
                )
            normalized = _map(
                owner_attestation["normalized"],
                f"{relation_name}.attestation_refs[{ref_index}] owner attestation",
            )
            report_entry = reports_by_attestation_sha.get(
                owner_attestation["raw_file_sha256"]
            )
            if report_entry is None or report_entry[0] != binding["lineage_id"]:
                _bad(
                    f"{relation_name}.attestation_refs[{ref_index}] must replay through its same-lineage finalized owner report"
                )
            _, report = report_entry
            verification = _map(
                report.get("verification"),
                f"{relation_name}.attestation_refs[{ref_index}] owner report verification",
            )
            if (
                verification.get("subject_digest") != normalized.get("subject_digest")
                or verification.get("artifact_sha256")
                != owner_attestation["raw_file_sha256"]
                or report.get("claim_id") != normalized.get("claim_id")
                or report.get("evidence_bindings")
                != normalized.get("evidence_bindings")
            ):
                _bad(
                    f"{relation_name}.attestation_refs[{ref_index}] owner report subject does not replay the selected attestation"
                )
            if relation["claim_ref"] != normalized["claim_id"]:
                _bad(
                    f"{relation_name}.attestation_refs[{ref_index}] must match the selected owner subject claim_id"
                )
            locator = _validate_locator_atom(
                ref["locator_ref"],
                f"{relation_name}.attestation_refs[{ref_index}].locator_ref",
            )[1]
            matching_evidence = [
                evidence_binding
                for evidence_binding in normalized["evidence_bindings"]
                if evidence_binding["evidence_id"] == relation["evidence_ref"]
            ]
            if len(matching_evidence) != 1 or not owner_locator_matches(
                matching_evidence[0], locator
            ):
                _bad(
                    f"{relation_name}.attestation_refs[{ref_index}] must match the selected owner subject evidence binding and locator"
                )
            owner_eligible = (
                normalized["support_candidate_eligible"] is True
                and normalized["mode"] in decisive_modes
                and report.get("claim_support_eligible") is True
                and report.get("projection_status") == "decisive"
            )
            if ref["state"] == "passed" and ref["decisive"] and not owner_eligible:
                _bad(
                    f"{relation_name}.attestation_refs[{ref_index}].decisive requires an owner-eligible decisive attestation"
                )

        owner_eligible_passed = False
        for ref in refs:
            if ref["state"] != "passed":
                continue
            owner_attestation = external_attestations[
                ref["owner_attestation_binding_digest"]
            ]
            report_entry = reports_by_attestation_sha[
                owner_attestation["raw_file_sha256"]
            ]
            report = report_entry[1]
            normalized = owner_attestation["normalized"]
            if (
                normalized["support_candidate_eligible"] is True
                and normalized["mode"] in decisive_modes
                and report.get("claim_support_eligible") is True
                and report.get("projection_status") == "decisive"
            ):
                owner_eligible_passed = True
                break
        if (
            relation["overall"] in {"decisive_within_scope", "qualified_only"}
            and not owner_eligible_passed
        ):
            _bad(
                f"{relation_name} selected decisive or qualified appraisal requires an owner-eligible passed external attestation"
            )


def _materialize_cycle(
    prepared: Mapping[str, Any],
    review: Mapping[str, Any],
    owner_bundle: Mapping[str, Any],
    prior: Mapping[str, Any] | None = None,
) -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, Any]]:
    prepared = _validate_prepared(prepared)
    owner_artifacts = _validate_owner_bundle(
        owner_bundle, prepared["owner_artifact_bindings"]
    )
    review = _validate_review(review, prepared)
    request = prepared["request"]
    if prior is None:
        if request["cycle"] != 0:
            _bad("a nonzero-cycle request requires its validated predecessor")
    else:
        prior = _validate_set(prior)
        if (
            request["appraisal_set_id"] != prior["appraisal_set_id"]
            or request["cycle"] != prior["cycle"] + 1
            or request["prior_cycle_ref"]
            != {
                "appraisal_set_id": prior["appraisal_set_id"],
                "appraisal_set_digest": prior["appraisal_set_digest"],
                "cycle": prior["cycle"],
            }
        ):
            _bad("prepared request must bind the exact immediate predecessor lineage")
    relation_drafts = _list(
        review["relation_appraisals"], "independent_review.relation_appraisals"
    )
    expected_identities = [
        (item["claim_ref"], item["evidence_ref"]) for item in request["relation_keys"]
    ]
    actual_identities = [
        (item.get("claim_ref"), item.get("evidence_ref"))
        if isinstance(item, Mapping)
        else None
        for item in relation_drafts
    ]
    if actual_identities != expected_identities:
        _bad(
            "independent review relation appraisals must exactly match request order and identities"
        )
    current_relations = [
        _materialize_relation(
            item,
            prepared,
            review["reviewer_context"],
            f"independent_review.relation_appraisals[{index}]",
        )
        for index, item in enumerate(relation_drafts)
    ]
    _validate_selected_owner_attestation_coverage(
        current_relations,
        owner_artifacts,
        "independent_review.relation_appraisals",
    )
    _check_supersession_against_prior(
        current_relations, prior, request["appraisal_set_id"]
    )
    all_relations = (
        copy.deepcopy(prior["relation_appraisals"]) if prior is not None else []
    ) + current_relations
    targets = _relation_targets(all_relations)
    challenges = [
        _materialize_challenge(item, targets, f"independent_review.challenges[{index}]")
        for index, item in enumerate(
            _list(review["challenges"], "independent_review.challenges")
        )
    ]
    needs = [
        _materialize_need(
            item, targets, f"independent_review.targeted_evidence_needs[{index}]"
        )
        for index, item in enumerate(
            _list(
                review["targeted_evidence_needs"],
                "independent_review.targeted_evidence_needs",
            )
        )
    ]
    challenge_ids = [item["challenge_id"] for item in challenges]
    challenge_digests = [item["semantic_digest"] for item in challenges]
    need_ids = [item["need_id"] for item in needs]
    need_digests = [item["semantic_digest"] for item in needs]
    if len(challenge_ids) != len(set(challenge_ids)) or len(need_ids) != len(
        set(need_ids)
    ):
        _bad("current-cycle challenge and need semantic content must be unique")
    set_artifact: dict[str, Any] = {
        "schema": "EvidenceAppraisalSet/v1",
        "appraisal_set_id": request["appraisal_set_id"],
        "cycle": request["cycle"],
        "prior_cycle_ref": copy.deepcopy(request["prior_cycle_ref"]),
        "immutable_predecessor_refs": []
        if prior is None
        else [_predecessor_summary(prior)],
        "relation_appraisals": all_relations,
        "challenge_ids": challenge_ids,
        "challenge_semantic_digests": challenge_digests,
        "targeted_evidence_need_ids": need_ids,
        "targeted_evidence_need_semantic_digests": need_digests,
        "owner_artifact_bindings": copy.deepcopy(prepared["owner_artifact_bindings"]),
        "owner_artifact_binding_digests": copy.deepcopy(
            prepared["owner_artifact_binding_digests"]
        ),
    }
    set_artifact["appraisal_set_digest"] = _digest(set_artifact)
    set_artifact["seal"] = {
        "algorithm": "sha256",
        "digest": set_artifact["appraisal_set_digest"],
    }
    set_artifact = _validate_set(set_artifact)
    bound_challenges = [
        {
            **item,
            "appraisal_set_id": set_artifact["appraisal_set_id"],
            "appraisal_set_digest": set_artifact["appraisal_set_digest"],
        }
        for item in challenges
    ]
    bound_need_set: dict[str, Any] = {
        "schema": "TargetedEvidenceNeedSet/v1",
        "appraisal_set_id": set_artifact["appraisal_set_id"],
        "appraisal_set_digest": set_artifact["appraisal_set_digest"],
        "needs": needs,
        "need_set_semantic_digest": _digest(need_digests),
    }
    bound_need_set["need_set_digest"] = _digest(_need_set_core(bound_need_set))
    for index, item in enumerate(bound_challenges):
        _validate_challenge(
            item,
            set_artifact["appraisal_set_id"],
            set_artifact["appraisal_set_digest"],
            targets,
            f"challenges[{index}]",
        )
    _validate_need_set(
        bound_need_set,
        set_artifact["appraisal_set_id"],
        set_artifact["appraisal_set_digest"],
        need_ids,
        need_digests,
        targets,
    )
    return set_artifact, bound_challenges, bound_need_set


def finalize_appraisal(
    prepared: Mapping[str, Any],
    independent_review: Mapping[str, Any],
    owner_bundle: Mapping[str, Any],
) -> dict[str, Any]:
    """Materialize a candidate initial appraisal set; approval is a separate step."""
    result, _, _ = _materialize_cycle(prepared, independent_review, owner_bundle)
    return result


def validate_appraisal_set(appraisal_set: Mapping[str, Any]) -> dict[str, Any]:
    """Validate only the self-contained candidate-set contract.

    A valid candidate set is not an approved package.  Approval is validated by
    ``validate_appraisal_package`` with actual independent artifacts.
    """
    return _validate_set(appraisal_set)


def reconcile_appraisal(
    prior: Mapping[str, Any],
    prepared: Mapping[str, Any],
    return_set: Mapping[str, Any],
    return_review: Mapping[str, Any],
    owner_bundle: Mapping[str, Any],
) -> dict[str, Any]:
    """Create the next immutable cycle from an externally prepared artifact."""
    prior = _validate_set(prior)
    return_set = _map(return_set, "return_set")
    _exact_keys(
        return_set,
        {"schema", "appraisal_set_id", "prior_cycle_ref", "relation_keys"},
        "return_set",
    )
    if (
        return_set["schema"] != "EvidenceAppraisalReturnSet/v1"
        or return_set["appraisal_set_id"] != prior["appraisal_set_id"]
    ):
        _bad("return_set must use the exact prior set lineage ID")
    expected_prior = {
        "appraisal_set_id": prior["appraisal_set_id"],
        "appraisal_set_digest": prior["appraisal_set_digest"],
        "cycle": prior["cycle"],
    }
    if return_set["prior_cycle_ref"] != expected_prior:
        _bad("return_set must bind exact immutable predecessor ID/digest/cycle")
    expected_request = {
        "schema": "EvidenceAppraisalRequest/v1",
        "appraisal_set_id": prior["appraisal_set_id"],
        "cycle": prior["cycle"] + 1,
        "prior_cycle_ref": expected_prior,
        "relation_keys": copy.deepcopy(return_set["relation_keys"]),
    }
    prepared = _validate_prepared(prepared)
    if prepared["request"] != expected_request:
        _bad(
            "reconcile requires an externally prepared request bound to exact return-set lineage"
        )
    return _materialize_cycle(prepared, return_review, owner_bundle, prior)[0]


def _lineage_prior(
    appraisal_set: Mapping[str, Any], lineage: Sequence[Mapping[str, Any]]
) -> Mapping[str, Any] | None:
    validated: dict[tuple[str, str, int], Mapping[str, Any]] = {}
    for candidate in lineage:
        candidate = _validate_set(candidate)
        key = (
            candidate["appraisal_set_id"],
            candidate["appraisal_set_digest"],
            candidate["cycle"],
        )
        if key in validated:
            _bad("lineage must not repeat immutable predecessor artifacts")
        validated[key] = candidate

    def predecessor_of(current: Mapping[str, Any]) -> Mapping[str, Any] | None:
        if current["cycle"] == 0:
            return None
        prior_ref = current["prior_cycle_ref"]
        key = (
            prior_ref["appraisal_set_id"],
            prior_ref["appraisal_set_digest"],
            prior_ref["cycle"],
        )
        prior = validated.get(key)
        if prior is None:
            _bad(
                "package validation requires every exact immutable predecessor in its lineage"
            )
        if _predecessor_summary(prior) != current["immutable_predecessor_refs"][0]:
            _bad(
                "immutable predecessor summary does not project the actual predecessor"
            )
        predecessor_of(prior)
        return prior

    return predecessor_of(appraisal_set)


def _lineage_chain(
    appraisal_set: Mapping[str, Any], lineage: Sequence[Mapping[str, Any]]
) -> list[Mapping[str, Any]]:
    current = _validate_set(appraisal_set)
    available: dict[tuple[str, str, int], Mapping[str, Any]] = {}
    for candidate in lineage:
        candidate = _validate_set(candidate)
        key = (
            candidate["appraisal_set_id"],
            candidate["appraisal_set_digest"],
            candidate["cycle"],
        )
        if key in available:
            _bad("lineage must not repeat immutable predecessor artifacts")
        available[key] = candidate
    chain = [current]
    while chain[-1]["cycle"] > 0:
        previous = chain[-1]["prior_cycle_ref"]
        key = (
            previous["appraisal_set_id"],
            previous["appraisal_set_digest"],
            previous["cycle"],
        )
        prior = available.get(key)
        if prior is None:
            _bad(
                "package validation requires every exact immutable predecessor in its lineage"
            )
        if _predecessor_summary(prior) != chain[-1]["immutable_predecessor_refs"][0]:
            _bad(
                "immutable predecessor summary does not project the actual predecessor"
            )
        chain.append(prior)
    chain.reverse()
    return chain


def _owner_binding_universe(
    appraisal_set: Mapping[str, Any], lineage: Sequence[Mapping[str, Any]]
) -> tuple[list[list[Mapping[str, Any]]], list[Mapping[str, Any]]]:
    chain = _lineage_chain(appraisal_set, lineage)
    groups = [list(item["owner_artifact_bindings"]) for item in chain]
    unique: list[Mapping[str, Any]] = []
    seen: set[str] = set()
    for group in groups:
        for binding in group:
            digest = _digest(binding)
            if digest not in seen:
                seen.add(digest)
                unique.append(binding)
    return groups, unique


def _validate_owner_lineage_bundle(
    owner_bundle: Mapping[str, Any],
    appraisal_set: Mapping[str, Any],
    lineage: Sequence[Mapping[str, Any]],
) -> list[Mapping[str, Any]]:
    chain = _lineage_chain(appraisal_set, lineage)
    groups = [list(item["owner_artifact_bindings"]) for item in chain]
    universe: list[Mapping[str, Any]] = []
    seen: set[str] = set()
    for group in groups:
        for binding in group:
            digest = _digest(binding)
            if digest not in seen:
                seen.add(digest)
                universe.append(binding)
    owner_bundle = _map(owner_bundle, "owner_bundle")
    _exact_keys(owner_bundle, {"schema", "artifacts"}, "owner_bundle")
    if owner_bundle["schema"] != OWNER_BUNDLE_SCHEMA:
        _bad(f"owner_bundle.schema must be {OWNER_BUNDLE_SCHEMA}")
    entries = _list(owner_bundle["artifacts"], "owner_bundle.artifacts")
    by_digest: dict[str, Any] = {}
    for index, entry in enumerate(entries):
        entry = _map(entry, f"owner_bundle.artifacts[{index}]")
        digest = _sha(
            entry.get("binding_digest"),
            f"owner_bundle.artifacts[{index}].binding_digest",
        )
        if digest in by_digest:
            _bad("owner_bundle must not repeat a runtime artifact entry")
        by_digest[digest] = entry
    expected_digests = _owner_binding_digests(universe)
    if set(by_digest) != set(expected_digests):
        _bad(
            "owner_bundle must contain the exact owner artifact universe for all package cycles"
        )
    prior_count = 0
    for index, (set_artifact, group) in enumerate(zip(chain, groups)):
        group_digests = _owner_binding_digests(group)
        validated = _validate_owner_bundle(
            {
                "schema": OWNER_BUNDLE_SCHEMA,
                "artifacts": [by_digest[digest] for digest in group_digests],
            },
            group,
        )
        if index and (
            set_artifact["relation_appraisals"][:prior_count]
            != chain[index - 1]["relation_appraisals"]
        ):
            _bad(
                "later appraisal cycles must preserve exact immutable predecessor relation appraisals"
            )
        _validate_selected_owner_attestation_coverage(
            set_artifact["relation_appraisals"][prior_count:],
            validated,
            f"appraisal_set cycle {set_artifact['cycle']} selected relations",
        )
        prior_count = len(set_artifact["relation_appraisals"])
    return universe


def _owner_bundle_subset(
    owner_bundle: Mapping[str, Any], bindings: Sequence[Mapping[str, Any]]
) -> dict[str, Any]:
    owner_bundle = _map(owner_bundle, "owner_bundle")
    _exact_keys(owner_bundle, {"schema", "artifacts"}, "owner_bundle")
    if owner_bundle["schema"] != OWNER_BUNDLE_SCHEMA:
        _bad(f"owner_bundle.schema must be {OWNER_BUNDLE_SCHEMA}")
    expected = set(_owner_binding_digests(bindings))
    entries = _list(owner_bundle["artifacts"], "owner_bundle.artifacts")
    return {
        "schema": OWNER_BUNDLE_SCHEMA,
        "artifacts": [
            entry
            for entry in entries
            if isinstance(entry, Mapping) and entry.get("binding_digest") in expected
        ],
    }


def _candidate_projection(
    appraisal_set: Mapping[str, Any],
    challenges: list[Mapping[str, Any]],
    need_set: Mapping[str, Any],
    owner_artifact_binding_digests: list[str],
) -> dict[str, Any]:
    return {
        "schema": "EvidenceAppraisalPackage/v1",
        "appraisal_set": copy.deepcopy(dict(appraisal_set)),
        "challenges": copy.deepcopy(challenges),
        "targeted_evidence_need_set": copy.deepcopy(dict(need_set)),
        "immutable_predecessor_refs": copy.deepcopy(
            appraisal_set["immutable_predecessor_refs"]
        ),
        "owner_artifact_binding_digests": copy.deepcopy(owner_artifact_binding_digests),
    }


def _authority_core(value: Mapping[str, Any]) -> dict[str, Any]:
    return _copy_without(value, {"authority_id", "authority_digest", "seal"})


def _validate_authority(
    authority: Any,
    prepared: Mapping[str, Any],
    review: Mapping[str, Any],
    candidate_set_digest: str,
    candidate_package_digest: str,
    owner_artifact_binding_digests: list[str],
) -> Mapping[str, Any]:
    authority = _map(authority, "approval")
    expected = {
        "schema",
        "authority_id",
        "prepared_request_file_sha256",
        "prepared_request_digest",
        "independent_review_file_sha256",
        "independent_review_digest",
        "owner_artifact_binding_digests",
        "candidate_set_digest",
        "candidate_package_digest",
        "decision",
        "complete_scope",
        "no_known_omission",
        "reviewer_context",
        "authority_digest",
        "seal",
    }
    _exact_keys(authority, expected, "approval")
    if authority["schema"] != "ReviewedEvidenceAppraisalAuthority/v1":
        _bad("approval.schema must be ReviewedEvidenceAppraisalAuthority/v1")
    if (
        authority["prepared_request_file_sha256"]
        != prepared["prepared_request_file_sha256"]
        or authority["prepared_request_digest"] != prepared["request_digest"]
        or authority["independent_review_file_sha256"]
        != review["independent_review_file_sha256"]
        or authority["independent_review_digest"] != review["independent_review_digest"]
        or authority["owner_artifact_binding_digests"] != owner_artifact_binding_digests
        or authority["candidate_set_digest"] != candidate_set_digest
        or authority["candidate_package_digest"] != candidate_package_digest
    ):
        _bad("approval must bind exact prepared/review owner and candidate digests")
    if (
        authority["decision"] != "approved"
        or authority["complete_scope"] is not True
        or authority["no_known_omission"] is not True
    ):
        _bad("approval must explicitly approve a complete scope with no known omission")
    context = _validate_reviewer_context(
        authority["reviewer_context"], "approval.reviewer_context"
    )
    if context["reviewer_ref"] == review["reviewer_context"]["reviewer_ref"]:
        _bad("approval reviewer must be independent from the review reviewer")
    core = _authority_core(authority)
    digest = _digest(core)
    if authority["authority_digest"] != digest:
        _bad("approval.authority_digest mismatch")
    _content_id_matches(
        authority["authority_id"], "authority", digest, "approval.authority_id"
    )
    seal = _map(authority["seal"], "approval.seal")
    _exact_keys(seal, {"algorithm", "digest"}, "approval.seal")
    if seal["algorithm"] != "sha256" or seal["digest"] != digest:
        _bad("approval seal mismatch")
    return authority


def create_reviewed_authority(
    prepared: Mapping[str, Any],
    independent_review: Mapping[str, Any],
    appraisal_set: Mapping[str, Any],
    reviewer_context: Mapping[str, Any],
    owner_bundle: Mapping[str, Any],
    *,
    lineage: Sequence[Mapping[str, Any]] = (),
    decision: str = "approved",
    complete_scope: bool = True,
    no_known_omission: bool = True,
) -> dict[str, Any]:
    """Construct a detached authority artifact for an independently run approval step."""
    appraisal_set = _validate_set(appraisal_set)
    prior = _lineage_prior(appraisal_set, lineage)
    current_prepared = _validate_prepared(prepared)
    replayed_set, challenges, need_set = _materialize_cycle(
        current_prepared,
        independent_review,
        _owner_bundle_subset(owner_bundle, current_prepared["owner_artifact_bindings"]),
        prior,
    )
    if replayed_set != appraisal_set:
        _bad(
            "authority cannot approve a set that does not replay from prepared request and review"
        )
    review = _validate_review(independent_review, current_prepared)
    owner_bindings = _validate_owner_lineage_bundle(
        owner_bundle, appraisal_set, lineage
    )
    owner_digests = _owner_binding_digests(owner_bindings)
    candidate_digest = _digest(
        _candidate_projection(appraisal_set, challenges, need_set, owner_digests)
    )
    authority: dict[str, Any] = {
        "schema": "ReviewedEvidenceAppraisalAuthority/v1",
        "prepared_request_file_sha256": prepared["prepared_request_file_sha256"],
        "prepared_request_digest": prepared["request_digest"],
        "independent_review_file_sha256": review["independent_review_file_sha256"],
        "independent_review_digest": review["independent_review_digest"],
        "owner_artifact_binding_digests": copy.deepcopy(owner_digests),
        "candidate_set_digest": appraisal_set["appraisal_set_digest"],
        "candidate_package_digest": candidate_digest,
        "decision": decision,
        "complete_scope": complete_scope,
        "no_known_omission": no_known_omission,
        "reviewer_context": copy.deepcopy(
            dict(
                _validate_reviewer_context(
                    reviewer_context, "authority.reviewer_context"
                )
            )
        ),
    }
    authority["authority_digest"] = _digest(_authority_core(authority))
    authority["authority_id"] = _content_id("authority", authority["authority_digest"])
    authority["seal"] = {"algorithm": "sha256", "digest": authority["authority_digest"]}
    return _validate_authority(
        authority,
        current_prepared,
        review,
        appraisal_set["appraisal_set_digest"],
        candidate_digest,
        owner_digests,
    )  # type: ignore[return-value]


def _package_core(value: Mapping[str, Any]) -> dict[str, Any]:
    return _copy_without(value, {"package_digest", "seal"})


def build_appraisal_package(
    appraisal_set: Mapping[str, Any],
    prepared: Mapping[str, Any],
    independent_review: Mapping[str, Any],
    approval: Mapping[str, Any],
    owner_bundle: Mapping[str, Any],
    *,
    expected_authority_sha256: str,
    lineage: Sequence[Mapping[str, Any]] = (),
) -> dict[str, Any]:
    """Build a sealed final package only from an actual replayable approval."""
    appraisal_set = _validate_set(appraisal_set)
    prior = _lineage_prior(appraisal_set, lineage)
    current_prepared = _validate_prepared(prepared)
    replayed_set, challenges, need_set = _materialize_cycle(
        current_prepared,
        independent_review,
        _owner_bundle_subset(owner_bundle, current_prepared["owner_artifact_bindings"]),
        prior,
    )
    if replayed_set != appraisal_set:
        _bad(
            "package set must replay exactly from prepared request, review, and lineage"
        )
    prepared = current_prepared
    review = _validate_review(independent_review, prepared)
    owner_bindings = _validate_owner_lineage_bundle(
        owner_bundle, appraisal_set, lineage
    )
    owner_digests = _owner_binding_digests(owner_bindings)
    candidate_digest = _digest(
        _candidate_projection(appraisal_set, challenges, need_set, owner_digests)
    )
    approval = _validate_authority(
        approval,
        prepared,
        review,
        appraisal_set["appraisal_set_digest"],
        candidate_digest,
        owner_digests,
    )
    package: dict[str, Any] = {
        **_candidate_projection(appraisal_set, challenges, need_set, owner_digests),
        "approval_ref": {
            "authority_id": approval["authority_id"],
            "authority_digest": approval["authority_digest"],
        },
    }
    package["package_digest"] = _digest(_package_core(package))
    package["seal"] = {"algorithm": "sha256", "digest": package["package_digest"]}
    return validate_appraisal_package(
        package,
        approval,
        prepared,
        review,
        owner_bundle,
        expected_authority_sha256=expected_authority_sha256,
        lineage=lineage,
    )


def validate_appraisal_package(
    package: Mapping[str, Any],
    approval: Mapping[str, Any] | None,
    prepared: Mapping[str, Any] | None,
    independent_review: Mapping[str, Any] | None,
    owner_bundle: Mapping[str, Any] | None,
    *,
    expected_authority_sha256: str,
    lineage: Sequence[Mapping[str, Any]] = (),
) -> dict[str, Any]:
    """Replay a package with actual approval; a self-sealed package is insufficient."""
    package = _map(package, "appraisal_package")
    expected = {
        "schema",
        "appraisal_set",
        "challenges",
        "targeted_evidence_need_set",
        "immutable_predecessor_refs",
        "owner_artifact_binding_digests",
        "approval_ref",
        "package_digest",
        "seal",
    }
    _exact_keys(package, expected, "appraisal_package")
    if package["schema"] != "EvidenceAppraisalPackage/v1":
        _bad("appraisal_package.schema must be EvidenceAppraisalPackage/v1")
    expected_authority_sha256 = _sha(
        expected_authority_sha256, "expected_authority_sha256"
    )
    if (
        approval is None
        or prepared is None
        or independent_review is None
        or owner_bundle is None
    ):
        _bad(
            "final package validation requires the actual approval, prepared request, independent review, and owner artifact bundle"
        )
    appraisal_set = _validate_set(package["appraisal_set"])
    if (
        package["immutable_predecessor_refs"]
        != appraisal_set["immutable_predecessor_refs"]
    ):
        _bad("package must seal the exact immutable predecessor projection")
    prior = _lineage_prior(appraisal_set, lineage)
    current_prepared = _validate_prepared(prepared)
    replayed_set, challenges, need_set = _materialize_cycle(
        current_prepared,
        independent_review,
        _owner_bundle_subset(owner_bundle, current_prepared["owner_artifact_bindings"]),
        prior,
    )
    if (
        replayed_set != appraisal_set
        or package["challenges"] != challenges
        or package["targeted_evidence_need_set"] != need_set
    ):
        _bad("package content does not replay from actual source artifacts")
    targets = _relation_targets(appraisal_set["relation_appraisals"])
    for index, item in enumerate(package["challenges"]):
        _validate_challenge(
            item,
            appraisal_set["appraisal_set_id"],
            appraisal_set["appraisal_set_digest"],
            targets,
            f"appraisal_package.challenges[{index}]",
        )
    _validate_need_set(
        package["targeted_evidence_need_set"],
        appraisal_set["appraisal_set_id"],
        appraisal_set["appraisal_set_digest"],
        appraisal_set["targeted_evidence_need_ids"],
        appraisal_set["targeted_evidence_need_semantic_digests"],
        targets,
    )
    owner_bindings = _validate_owner_lineage_bundle(
        owner_bundle, appraisal_set, lineage
    )
    owner_digests = _owner_binding_digests(owner_bindings)
    if package["owner_artifact_binding_digests"] != owner_digests:
        _bad(
            "package must bind the exact replayed owner artifact universe without runtime paths"
        )
    candidate_digest = _digest(
        _candidate_projection(appraisal_set, challenges, need_set, owner_digests)
    )
    approval = _validate_authority(
        approval,
        current_prepared,
        _validate_review(independent_review, current_prepared),
        appraisal_set["appraisal_set_digest"],
        candidate_digest,
        owner_digests,
    )
    if approval["authority_digest"] != expected_authority_sha256:
        _bad(
            "approval authority digest is not in the caller-provided external trust boundary"
        )
    approval_ref = _map(package["approval_ref"], "appraisal_package.approval_ref")
    _exact_keys(
        approval_ref,
        {"authority_id", "authority_digest"},
        "appraisal_package.approval_ref",
    )
    if approval_ref != {
        "authority_id": approval["authority_id"],
        "authority_digest": approval["authority_digest"],
    }:
        _bad("package approval_ref must name the actual reviewed authority artifact")
    digest = _digest(_package_core(package))
    if package["package_digest"] != digest:
        _bad("appraisal_package digest mismatch")
    seal = _map(package["seal"], "appraisal_package.seal")
    _exact_keys(seal, {"algorithm", "digest"}, "appraisal_package.seal")
    if seal["algorithm"] != "sha256" or seal["digest"] != digest:
        _bad("appraisal_package seal mismatch")
    return copy.deepcopy(dict(package))


# Backward-compatible private name used by older focused tests.  It now cannot
# validate a final package without the detached approval/source artifacts.
def _validate_package(
    package: Mapping[str, Any], *args: Any, **kwargs: Any
) -> dict[str, Any]:
    return validate_appraisal_package(package, *args, **kwargs)


def _atomic_write_json(path: str | Path, artifact: Mapping[str, Any]) -> None:
    destination = Path(path)
    destination.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
    os.chmod(destination.parent, 0o700)
    if stat.S_IMODE(destination.parent.stat().st_mode) != 0o700:
        raise ContractError("destination directory mode must be 0700")
    fd: int | None = None
    temporary: str | None = None
    try:
        fd, temporary = tempfile.mkstemp(
            prefix=".evidence-appraisal-", dir=destination.parent
        )
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "wb") as stream:
            fd = None
            stream.write(canonical_json_bytes(artifact) + b"\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, destination)
        temporary = None
        if stat.S_IMODE(destination.stat().st_mode) != 0o600:
            raise ContractError("destination artifact mode must be 0600")
    except BaseException:
        if fd is not None:
            os.close(fd)
        if temporary is not None:
            try:
                os.unlink(temporary)
            except FileNotFoundError:
                pass
        raise


def write_appraisal_atomically(path: str | Path, artifact: Mapping[str, Any]) -> None:
    """Validate and atomically write a candidate set with private permissions."""
    _atomic_write_json(path, validate_appraisal_set(artifact))


def _read_json(path: str | Path) -> dict[str, Any]:
    with Path(path).open(encoding="utf-8") as stream:
        value = json.load(stream)
    if not isinstance(value, dict):
        _bad(f"{path} must contain a JSON object")
    return value


def _cli_owner_bundle(
    args: argparse.Namespace, bindings: Sequence[Mapping[str, Any]]
) -> dict[str, Any]:
    bundle_path = getattr(args, "owner_bundle", None)
    artifact_paths = getattr(args, "owner_artifact", [])
    receipt_paths = getattr(args, "owner_receipt", [])
    input_paths = getattr(args, "owner_input", [])
    if bundle_path:
        if artifact_paths or receipt_paths or input_paths:
            _bad(
                "use either --owner-bundle or repeatable --owner-artifact/--owner-receipt inputs"
            )
        return _read_json(bundle_path)
    if len(artifact_paths) != len(bindings) or len(receipt_paths) != len(bindings):
        _bad(
            "repeatable --owner-artifact and --owner-receipt must each cover every exact owner binding"
        )
    if input_paths and len(input_paths) != len(bindings):
        _bad(
            "repeatable --owner-input must be omitted or align one-for-one with owner bindings"
        )
    runtime_inputs = (
        [_read_json(path) for path in input_paths]
        if input_paths
        else [
            {"source_path": None, "bundle_path": None, "verification_root": None}
            for _ in bindings
        ]
    )
    artifacts: list[dict[str, Any]] = []
    for binding, artifact_path, receipt_path, inputs in zip(
        bindings, artifact_paths, receipt_paths, runtime_inputs
    ):
        _exact_keys(
            inputs,
            {"source_path", "bundle_path", "verification_root"},
            "owner runtime input",
        )
        artifacts.append(
            {
                "binding_digest": _digest(binding),
                "artifact_path": artifact_path,
                "verification_receipt_path": receipt_path,
                "source_path": inputs["source_path"],
                "bundle_path": inputs["bundle_path"],
                "verification_root": inputs["verification_root"],
            }
        )
    return {"schema": OWNER_BUNDLE_SCHEMA, "artifacts": artifacts}


def _main() -> int:
    parser = argparse.ArgumentParser(description="Evidence appraisal contract CLI")
    sub = parser.add_subparsers(dest="command", required=True)
    prepare_parser = sub.add_parser("prepare")
    prepare_parser.add_argument("request")
    prepare_parser.add_argument("output")
    prepare_parser.add_argument(
        "--owner-binding", action="append", default=[], required=True
    )
    finalize_parser = sub.add_parser("finalize")
    finalize_parser.add_argument("prepared")
    finalize_parser.add_argument("review")
    finalize_parser.add_argument("output")
    reconcile_parser = sub.add_parser("reconcile")
    reconcile_parser.add_argument("prior")
    reconcile_parser.add_argument("prepared")
    reconcile_parser.add_argument("return_set")
    reconcile_parser.add_argument("review")
    reconcile_parser.add_argument("output")
    authority_parser = sub.add_parser("authority")
    authority_parser.add_argument("prepared")
    authority_parser.add_argument("review")
    authority_parser.add_argument("appraisal_set")
    authority_parser.add_argument("output")
    authority_parser.add_argument("--reviewer-ref", required=True)
    authority_parser.add_argument("--review-method", required=True)
    authority_parser.add_argument("--reviewed-at", required=True)
    authority_parser.add_argument("--lineage", action="append", default=[])
    package_parser = sub.add_parser("package")
    package_parser.add_argument("appraisal_set")
    package_parser.add_argument("prepared")
    package_parser.add_argument("review")
    package_parser.add_argument("approval")
    package_parser.add_argument("output")
    package_parser.add_argument("--expected-authority-sha256", required=True)
    package_parser.add_argument("--lineage", action="append", default=[])
    validate_parser = sub.add_parser("validate")
    validate_parser.add_argument("artifact")
    validate_parser.add_argument("--approval")
    validate_parser.add_argument("--prepared")
    validate_parser.add_argument("--review")
    validate_parser.add_argument("--expected-authority-sha256")
    validate_parser.add_argument("--lineage", action="append", default=[])

    for command_parser in (
        prepare_parser,
        finalize_parser,
        reconcile_parser,
        authority_parser,
        package_parser,
        validate_parser,
    ):
        command_parser.add_argument("--owner-bundle")
        command_parser.add_argument("--owner-artifact", action="append", default=[])
        command_parser.add_argument("--owner-receipt", action="append", default=[])
        command_parser.add_argument("--owner-input", action="append", default=[])
    args = parser.parse_args()
    if args.command == "prepare":
        bindings = [_read_json(path) for path in args.owner_binding]
        _validate_owner_bundle(_cli_owner_bundle(args, bindings), bindings)
        raw = Path(args.request).read_bytes()
        _atomic_write_json(
            args.output,
            prepare_appraisal(
                _read_json(args.request),
                hashlib.sha256(raw).hexdigest(),
                bindings,
            ),
        )
    elif args.command == "finalize":
        prepared = _read_json(args.prepared)
        _atomic_write_json(
            args.output,
            finalize_appraisal(
                prepared,
                _read_json(args.review),
                _cli_owner_bundle(args, prepared["owner_artifact_bindings"]),
            ),
        )
    elif args.command == "reconcile":
        prepared = _read_json(args.prepared)
        _atomic_write_json(
            args.output,
            reconcile_appraisal(
                _read_json(args.prior),
                prepared,
                _read_json(args.return_set),
                _read_json(args.review),
                _cli_owner_bundle(args, prepared["owner_artifact_bindings"]),
            ),
        )
    elif args.command == "authority":
        lineage = [_read_json(path) for path in args.lineage]
        appraisal_set = _read_json(args.appraisal_set)
        owner_bindings = _owner_binding_universe(appraisal_set, lineage)[1]
        authority = create_reviewed_authority(
            _read_json(args.prepared),
            _read_json(args.review),
            appraisal_set,
            {
                "reviewer_ref": args.reviewer_ref,
                "review_method": args.review_method,
                "reviewed_at": args.reviewed_at,
            },
            _cli_owner_bundle(args, owner_bindings),
            lineage=lineage,
        )
        _atomic_write_json(args.output, authority)
    elif args.command == "package":
        lineage = [_read_json(path) for path in args.lineage]
        appraisal_set = _read_json(args.appraisal_set)
        owner_bindings = _owner_binding_universe(appraisal_set, lineage)[1]
        package = build_appraisal_package(
            appraisal_set,
            _read_json(args.prepared),
            _read_json(args.review),
            _read_json(args.approval),
            _cli_owner_bundle(args, owner_bindings),
            expected_authority_sha256=args.expected_authority_sha256,
            lineage=lineage,
        )
        _atomic_write_json(args.output, package)
    else:
        artifact = _read_json(args.artifact)
        if artifact.get("schema") == "EvidenceAppraisalSet/v1":
            validate_appraisal_set(artifact)
            print("valid EvidenceAppraisalSet/v1 candidate")
        elif artifact.get("schema") == "EvidenceAppraisalPackage/v1":
            if not (
                args.approval
                and args.prepared
                and args.review
                and args.expected_authority_sha256
            ):
                parser.error(
                    "package validation requires --approval --prepared --review --expected-authority-sha256 and an owner bundle"
                )
            lineage = [_read_json(path) for path in args.lineage]
            owner_bindings = _owner_binding_universe(
                artifact["appraisal_set"], lineage
            )[1]
            validate_appraisal_package(
                artifact,
                _read_json(args.approval),
                _read_json(args.prepared),
                _read_json(args.review),
                _cli_owner_bundle(args, owner_bindings),
                expected_authority_sha256=args.expected_authority_sha256,
                lineage=lineage,
            )
            print("valid reviewed EvidenceAppraisalPackage/v1")
        else:
            parser.error(
                "artifact must be EvidenceAppraisalSet/v1 or EvidenceAppraisalPackage/v1"
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
