#!/usr/bin/env python3
"""Probe a research knowledge network without mutating it."""

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
from collections import Counter, deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


NETWORK_SCHEMA = "KnowledgeNetwork/v1"
PROBE_SCHEMA = "NetworkGapProbe/v1"
HYPOTHESES_SCHEMA = "KnowledgeGapHypotheses/v1"
REQUEST_SET_SCHEMA = "ScholarDiscoveryRequestSet/v1"
APPRAISAL_REQUEST_SET_SCHEMA = "AppraisalScholarDiscoveryRequestSet/v1"
LEARN_FROM_PAPERS_REQUEST_SET_SCHEMA = "LearnFromPapersRequestSet/v1"
LEARN_FROM_PAPERS_REQUEST_SCHEMA = "LearnFromPapersRequest/v1"
RESULT_SET_SCHEMA = "ScholarDiscoveryResultSet/v1"
RESULT_SET_V2_SCHEMA = "ScholarDiscoveryResultSet/v2"
REQUEST_SCHEMA = "ScholarDiscoveryRequest/v1"
RESULT_SCHEMA = "ScholarDiscoveryResult/v1"
REVIEWED_EVIDENCE_SET_SCHEMA = "ReviewedEvidenceSet/v1"
REVIEWED_EVIDENCE_SCHEMA = "ReviewedEvidence/v1"
PAPER_READING_REPORT_SET_SCHEMA = "PaperReadingReportSet/v1"
PAPER_READING_REPORT_SCHEMA = "PaperReadingReport/v1"
PAPER_READING_REPORT_SET_V2_SCHEMA = "PaperReadingReportSet/v2"
PAPER_UNDERSTANDING_GAP_SCHEMA = "PaperUnderstandingGap/v1"
UNDERSTANDING_NETWORK_PROJECTION_SCHEMA = "UnderstandingNetworkProjection/v1"
PATCH_SCHEMA = "NetworkPatchProposal/v2"
PATCH_V1_SCHEMA = "NetworkPatchProposal/v1"
PATCH_SCHEMA_VERSION = "2.0"
VERIFICATION_REQUEST_SCHEMA = "VerificationAttestationRequest/v1"
VERIFIER_ATTESTATION_SCHEMA = "VerificationAttestation/v1"
TARGET_CLAIM_SCHEMA = "NetworkPatchTargetClaim/v1"
EVIDENCE_CHALLENGE_SCHEMA = "EvidenceChallenge/v1"
TARGETED_EVIDENCE_NEED_SET_SCHEMA = "TargetedEvidenceNeedSet/v1"
SEARCH_HISTORY_INDEX_SCHEMA = "SearchHistoryIndex/v1"
SEARCH_HISTORY_INDEX_V2_SCHEMA = "SearchHistoryIndex/v2"
HISTORY_AUTHORITY_MANIFEST_SCHEMA = "HistoryAuthorityManifest/v1"
HISTORY_AUTHORITY_CANDIDATE_SCHEMA = "HistoryAuthorityCandidate/v1"
REVIEWED_HISTORY_AUTHORITY_SCHEMA = "ReviewedHistoryAuthority/v1"
APPRAISAL_COMPILATION_SCHEMA = "AppraisalNeedCompilation/v1"
APPRAISAL_ORIGIN_SCHEMA = "EvidenceAppraisalNeedOrigin/v1"
REQUEST_PROJECTION_PROFILE_SCHEMA = "ScholarRequestProjectionProfile/v1"
APPRAISAL_ROUTE_DISPATCH_SCHEMA = "EvidenceAppraisalRouteDispatch/v1"

SCHEMA_VERSION = "1.0"
REQUEST_SET_SCHEMA_VERSION = "v1"
PAPER_READING_REPORT_SET_SCHEMA_VERSION = "v1"
REQUEST_SET_ID_PREFIX = "request-set-"
GENERIC_REQUEST_ID_PREFIX = "SDR-"
APPRAISAL_REQUEST_ID_PREFIX = "ASDR-"
LEARN_REQUEST_SET_ID_PREFIX = "LFR-"
SOURCE_ID_PREFIX = "SRC-"
REPORT_SET_ID_PREFIX = "reading-report-set-"
READING_REPORT_ID_PREFIX = "reading-report-"
V2_READING_REPORT_ID_PREFIX = "reading-report-v2-"
PASSAGE_ID_PREFIX = "passage-"
LOCATOR_TYPES = {"page", "section", "figure", "table", "equation"}
READING_REPORT_PROTOCOL = "1.0"
READER_PRODUCER = "learn-from-papers"
READING_DEPTH_ONLY_FULL_TEXT = "full_text"
V2_RELATION_TO_OUTCOME = {
    "supports": "supports",
    "refutes": "contradicts",
    "qualifies": "unknown",
    "not_tested": "unknown",
}
EPISTEMIC_RELATION_VOCABULARY = [
    "supports",
    "qualifies",
    "refutes",
    "not_tested",
]

PAPER_UNDERSTANDING_GAP_TO_PROJECTION = {
    "missing_input_format": "workflow",
    "missing_data_flow": "workflow",
    "missing_derivation_step": "math",
    "missing_algorithm_detail": "algorithm",
    "missing_applicability_boundary": "applicability",
    "missing_conclusion_scope": "conclusion",
}
PAPER_UNDERSTANDING_GAP_TYPES = set(PAPER_UNDERSTANDING_GAP_TO_PROJECTION)
PAPER_UNDERSTANDING_GAP_FIELD_PREFIXES = {
    "missing_input_format": ("workflow.graph.nodes",),
    "missing_data_flow": ("workflow.data_flow", "workflow.graph.operations"),
    "missing_derivation_step": (
        "mathematical_principles.derivation_steps",
        "mathematical_principles.principles",
    ),
    "missing_algorithm_detail": (
        "algorithmic_principles.objective",
        "algorithmic_principles.state_variables",
        "algorithmic_principles.ordered_steps",
        "algorithmic_principles.invariants",
        "algorithmic_principles.failure_modes",
        "algorithmic_principles.algorithms",
    ),
    "missing_applicability_boundary": (
        "applicability.applies_when",
        "applicability.does_not_apply_when",
    ),
    "missing_conclusion_scope": (
        "conclusion.statement",
        "conclusion.confidence",
        "conclusion.confidence_rationale",
    ),
}
PAPER_UNDERSTANDING_GAP_FIELD_PATTERNS = {
    "missing_input_format": re.compile(
        r"workflow\.graph\.nodes(?:\[[0-9]+\])?\.format"
    ),
    "missing_data_flow": re.compile(
        r"workflow\.(?:data_flow(?:\[[0-9]+\])?|graph\.operations"
        r"(?:\[[0-9]+\])?(?:\.(?:consumes|produces)(?:\[[0-9]+\])?)?)"
    ),
    "missing_derivation_step": re.compile(
        r"mathematical_principles\.(?:derivation_steps(?:\[[0-9]+\])?|"
        r"principles\[[0-9]+\]\.derivation_steps(?:\[[0-9]+\])?)"
    ),
    "missing_algorithm_detail": re.compile(
        r"algorithmic_principles\.(?:objective|state_variables|ordered_steps|"
        r"invariants|failure_modes|algorithms)(?:\[[0-9]+\])?"
        r"(?:\.[A-Za-z_][A-Za-z0-9_]*(?:\[[0-9]+\])?)*"
    ),
    "missing_applicability_boundary": re.compile(
        r"applicability\.(?:applies_when|does_not_apply_when)(?:\[[0-9]+\])?"
    ),
    "missing_conclusion_scope": re.compile(
        r"conclusion\.(?:statement|confidence|confidence_rationale)"
    ),
}
SENSITIVE_EXTERNAL_QUERY_PATTERNS = (
    re.compile(r"(?:^|\s)(?:/(?:home|root|Users)/|~/|[A-Za-z]:[\\/])"),
    re.compile(r"\b(?:file://|ghp_|github_pat_|sk-|xox[baprs]-)[A-Za-z0-9_./-]+", re.I),
    re.compile(
        r"\b(?:api[_ -]?key|access[_ -]?token|authorization|cookie)\s*[:=]", re.I
    ),
    re.compile(r"\b(?=[A-Z0-9]{8}\b)(?=[A-Z0-9]*[A-Z])(?=[A-Z0-9]*[0-9])[A-Z0-9]{8}\b"),
    re.compile(r"\b[0-9a-f]{32,64}\b", re.I),
)

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
TARGET_KINDS = set(ACTION_FOR_TARGET_KIND)
PATCH_ACTION_STATUSES = {"proposed", "blocked"}
STATUSES = {
    "proposed",
    "selected",
    "testing",
    "awaiting",
    "results",
    "no_signal",
    "content_found",
    "already_covered",
    "supported_gap",
    "contested",
    "refuted",
    "unresolved",
    "blocked",
    "superseded",
}
ACTIVE_STATUSES = {
    "proposed",
    "selected",
    "testing",
    "awaiting",
    "results",
    "unresolved",
    "no_signal",
}
DISCOVERY_ACTIVE_STATUSES = {
    "proposed",
    "selected",
    "testing",
    "unresolved",
    "no_signal",
    "awaiting",
}
SATURATION_BLOCKING_STATUSES = {
    "proposed",
    "selected",
    "testing",
    "unresolved",
    "awaiting",
    "results",
}
SATURATION_TERMINAL_STATUSES = {
    "no_signal",
    "content_found",
    "already_covered",
    "supported_gap",
    "contested",
    "refuted",
}
DISCOVERY_RESULT_STATUSES = {"results"}
MANUAL_RESULT_STATUSES = {"awaiting"}
CANDIDATE_FOR_REVIEW_STATUSES = {"results"}
LEVELS = {"high", "medium", "low"}
QUERY_OBJECTIVES = {
    "known_item",
    "orientation",
    "confirm",
    "refute",
    "recent_primary",
    "seminal",
    "methods",
    "benchmark",
    "citation_forward",
    "citation_backward",
    "update",
}
AUTOMATIC_PROVIDERS = {
    "openalex",
    "semantic_scholar",
    "crossref",
    "opencitations",
    "pubmed",
    "europepmc",
    "arxiv",
}
DISCOVERY_STATUSES = {
    "complete_bounded",
    "partial_provider",
    "partial_budget",
    "blocked_capability",
    "pending",
}
READ_DEPTHS = {"full_text", "evidence"}
CANDIDATE_SIGNAL_MAX_TOTAL = 64
CANDIDATE_SIGNAL_TIER_BUDGETS = {
    "explicit_high_impact": 24,
    "explicit": 8,
    "unmet_gate": 4,
    "single_source": 12,
    "isolate": 6,
    "low_confidence": 6,
    "structural": 4,
}
CANDIDATE_SIGNAL_TIER_ORDER = tuple(CANDIDATE_SIGNAL_TIER_BUDGETS)
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
INTERNAL_QUERY_BLOCKLIST = {
    "completion.gate_checks.",
    "unmet_declared_gate:",
}
INTERNAL_QUERY_PREFIXES = {
    "gap:",
    "relation:",
    "node:",
    "claim:",
    "derived:",
    "gap-",
    "rel-",
    "claim-",
    "clm-",
    "gaph:",
    "kgh-",
    "entity:",
    "completion.gate_checks.",
}
INTERNAL_QUERY_FIELD_NAMES = {"completion", "gate", "status", "entity"}
QUERY_STOP_WORDS = {
    "a",
    "an",
    "at",
    "and",
    "as",
    "by",
    "for",
    "from",
    "in",
    "into",
    "is",
    "it",
    "no",
    "of",
    "on",
    "or",
    "the",
    "this",
    "to",
    "via",
    "with",
    "without",
    "around",
    "benchmark",
}
SEMANTIC_QUERY_MAX_WORDS = 12
APPRAISAL_QUERY_LABEL_TERMS = {
    "boundary",
    "claim",
    "challenges",
    "comparator",
    "implication",
    "metric",
    "observation",
    "state",
    "supports",
    "target",
    "value",
}
QUERY_TERM_BLOCKLIST = {
    "claims_property",
    "evidence",
    "needed",
    "potential",
    "probe",
    "signal",
    "suggested",
    "targeted",
}
GAP_REASON_TERM_BLOCKLIST = {
    "an",
    "and",
    "at",
    "benchmark",
    "complete",
    "coverage",
    "claim",
    "decisive",
    "gap",
    "high-impact",
    "identify",
    "for",
    "in",
    "locally",
    "missing",
    "needed",
    "of",
    "open",
    "slot",
    "the",
    "to",
    "unresolved",
    "which",
}
QUERY_TOKEN_RE = re.compile(r"[^\W_][\w.:+-]*", re.UNICODE)

EVIDENCE_CHALLENGE_AXES = {
    "counterexample",
    "alternative_explanation",
    "boundary_condition",
    "method_failure",
    "independent_replication",
    "data_code_artifact",
    "omitted_baseline",
    "negative_or_missing_result",
    "correction_retraction_version",
}
EVIDENCE_TARGET_DIMENSIONS = {
    "provenance_integrity",
    "claim_entailment",
    "scope_directness",
    "method_validity",
    "result_uncertainty",
    "artifact_reproducibility",
    "independence_overlap",
    "missing_conflict",
}
EVIDENCE_CHALLENGE_STATUSES = {
    "open",
    "resolved",
    "unresolved",
    "blocked",
    "superseded",
}
EVIDENCE_CHALLENGE_ROUTES = {
    "targeted_evidence_need",
    "within_source_review",
    "runtime_or_reconstruction",
    "terminal_unresolved",
}
EVIDENCE_NEED_ROUTES = {
    "scholar_discovery",
    "source_acquisition",
    "full_text_review",
    "code_data",
    "manual_experiment",
    "version_status_check",
}
EVIDENCE_NEED_STATUSES = {
    "proposed",
    "selected",
    "in_progress",
    "satisfied",
    "unresolved",
    "blocked",
    "superseded",
}
CHALLENGE_AXIS_SIGNATURE_FIELD = {
    "counterexample": "target_scope",
    "alternative_explanation": "comparator",
    "boundary_condition": "boundary_variable",
    "method_failure": "evidence_class",
    "independent_replication": "independence_requirement",
    "data_code_artifact": "evidence_class",
    "omitted_baseline": "comparator",
    "negative_or_missing_result": "evidence_class",
    "correction_retraction_version": "evidence_class",
}
SEMANTIC_SIGNATURE_FIELDS = {
    "target_scope",
    "evidence_class",
    "comparator",
    "boundary_variable",
    "independence_requirement",
}
STRUCTURAL_APPRAISAL_PATTERNS = (
    re.compile(r"\bnetwork\s+dimension\b", re.I),
    re.compile(r"\bsemantic\s+enrichment\s+required\b", re.I),
    re.compile(
        r"\b(?:missing[-_ ]dimension|validation_target|surrogate_family|task_type)\b",
        re.I,
    ),
)
OBSERVATION_OPERATOR_COMPLEMENTS = {
    "eq": "neq",
    "lt": "gte",
    "lte": "gt",
    "inside": "outside",
    "present": "absent",
    "reproduced": "not_reproduced",
    "supports": "does_not_support",
}
OBSERVATION_OPERATOR_QUERY_TEXT = {
    "eq": "equals",
    "neq": "unequal differs",
    "lt": "below",
    "gte": "at least threshold",
    "lte": "at most threshold",
    "gt": "above",
    "inside": "inside range",
    "outside": "outside range",
    "present": "present observed",
    "absent": "absent missing",
    "reproduced": "replicated reproduced",
    "not_reproduced": "replication failure nonreproduction",
    "supports": "supports corroborates",
    "does_not_support": "contradicts unsupported",
}

PROBE_FAMILIES = [
    {
        "probe_id": "probe:competency-coverage",
        "family": "competency_coverage",
        "question": "Which promised question, dimension, benchmark, or locally complete slot is unanswered?",
    },
    {
        "probe_id": "probe:taxonomy-contrast",
        "family": "taxonomy_contrast",
        "question": "Which concepts in landmark taxonomies or reviews are absent or only aliases?",
    },
    {
        "probe_id": "probe:perspective-expansion",
        "family": "perspective_expansion",
        "question": "Which object, mechanism, method, evidence, context, boundary, or artifact view is missing?",
    },
    {
        "probe_id": "probe:abc-bridge",
        "family": "abc_bridge",
        "question": "Which context-matched A-B and B-C paths justify a falsifiable A-C search?",
    },
    {
        "probe_id": "probe:citation-frontier",
        "family": "citation_frontier",
        "question": "What relevant cited, citing, related, or unused information is outside the network?",
    },
    {
        "probe_id": "probe:counterevidence-boundary",
        "family": "counterevidence_boundary",
        "question": "Which null, failure, replication, counterexample, or discriminating evidence is absent?",
    },
    {
        "probe_id": "probe:temporal-version",
        "family": "temporal_version",
        "question": "Which update, correction, retraction, superseding version, or time boundary is missing?",
    },
    {
        "probe_id": "probe:relation-context-arity",
        "family": "relation_context_arity",
        "question": "Which pairwise edge hides necessary context, conditions, or an n-ary event?",
    },
]


class ContractError(ValueError):
    """Raised when a gap-discovery contract fails closed."""


_READING_DOSSIER_MODULE: Any | None = None


def _reading_dossier_module() -> Any:
    global _READING_DOSSIER_MODULE
    if _READING_DOSSIER_MODULE is not None:
        return _READING_DOSSIER_MODULE
    module_path = (
        Path(__file__).resolve().parents[2]
        / "learn-from-papers"
        / "scripts"
        / "paper_reading_dossier.py"
    )
    if not module_path.is_file() or module_path.is_symlink():
        raise ContractError("learn-from-papers paper_reading_dossier.py is unavailable")
    spec = importlib.util.spec_from_file_location(
        "network_gap_discovery_paper_reading_dossier", module_path
    )
    if spec is None or spec.loader is None:
        raise ContractError("cannot load learn-from-papers dossier validator")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    if not callable(getattr(module, "validate_report_set_v2", None)):
        raise ContractError(
            "learn-from-papers dossier validator lacks validate_report_set_v2"
        )
    _READING_DOSSIER_MODULE = module
    return module


_SCHOLAR_DISCOVERY_MODULE: Any | None = None


def _scholar_discovery_module() -> Any:
    global _SCHOLAR_DISCOVERY_MODULE
    if _SCHOLAR_DISCOVERY_MODULE is not None:
        return _SCHOLAR_DISCOVERY_MODULE
    module_path = (
        Path(__file__).resolve().parents[2]
        / "scholar-discovery"
        / "scripts"
        / "scholar_discovery.py"
    )
    if not module_path.is_file() or module_path.is_symlink():
        raise ContractError(
            "scholar-discovery is required to validate SearchHistoryIndex/v1 or v2"
        )
    spec = importlib.util.spec_from_file_location(
        "network_gap_discovery_scholar_discovery", module_path
    )
    if spec is None or spec.loader is None:
        raise ContractError("cannot load scholar-discovery history validator")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    required = {
        "validate_search_history_index",
        "canonical_semantic_terms",
        "semantic_signature_from_terms",
    }
    if any(not callable(getattr(module, name, None)) for name in required):
        raise ContractError(
            "scholar-discovery lacks the SearchHistoryIndex owner interface"
        )
    _SCHOLAR_DISCOVERY_MODULE = module
    return module


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def sha256_json(value: Any) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def canonical_request_set_digest(document: dict[str, Any]) -> str:
    normalized = {
        key: value
        for key, value in document.items()
        if key not in {"request_set_id", "request_set_digest"}
    }
    return sha256_json(normalized)


def canonical_evidence_set_digest(document: dict[str, Any]) -> str:
    normalized = {
        key: value
        for key, value in document.items()
        if key not in {"evidence_set_id", "evidence_set_digest"}
    }
    return sha256_json(normalized)


def canonical_report_set_digest(document: dict[str, Any]) -> str:
    normalized = {
        key: value
        for key, value in document.items()
        if key
        not in {
            "report_set_id",
            "report_set_digest",
            "reading_report_set_id",
            "reading_report_set_digest",
            "network_id",
            "network_snapshot_sha256",
            "source_artifact_sha256",
        }
    }
    return sha256_json(normalized)


def canonical_reading_report_digest(document: dict[str, Any]) -> str:
    normalized = {
        key: value
        for key, value in document.items()
        if key not in {"report_id", "report_digest"}
    }
    return sha256_json(normalized)


def canonical_paper_understanding_gap_digest(document: dict[str, Any]) -> str:
    """Hash a gap observation without its content-derived identity fields."""
    normalized = {
        key: value
        for key, value in document.items()
        if key not in {"gap_id", "gap_digest"}
    }
    return sha256_json(normalized)


def canonical_evidence_passage_digest(document: dict[str, Any]) -> str:
    normalized = {
        key: value
        for key, value in document.items()
        if key not in {"passage_id", "passage_digest"}
    }
    return sha256_json(normalized)


def _as_string_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        text = value.strip()
        return [text] if text else []
    if not isinstance(value, list):
        return []
    return [item.strip() for item in value if isinstance(item, str) and item.strip()]


def normalize_hypothesis_id(value: str) -> str:
    value = value.strip()
    return value[4:] if value.startswith("gap:") else value


def load_json(path: str | Path) -> Any:
    candidate = Path(path)
    if candidate.is_symlink() or not candidate.is_file():
        raise ContractError(f"input must be a regular non-symlink file: {candidate}")
    with candidate.open("r", encoding="utf-8") as handle:
        return json.load(handle)


PRIVATE_FILE_MODE = 0o600
PRIVATE_DIRECTORY_MODE = 0o700


def _ensure_private_output_directory(directory: Path) -> None:
    missing: list[Path] = []
    cursor = directory
    while not cursor.exists():
        if cursor.is_symlink():
            raise ContractError(f"refusing symlink output directory: {cursor}")
        missing.append(cursor)
        parent = cursor.parent
        if parent == cursor:
            raise ContractError(f"cannot resolve output directory: {directory}")
        cursor = parent

    if cursor.is_symlink() or not cursor.is_dir():
        raise ContractError(f"output parent must be a directory: {cursor}")

    for candidate in reversed(missing):
        created = False
        try:
            os.mkdir(candidate, PRIVATE_DIRECTORY_MODE)
            created = True
        except FileExistsError:
            pass
        if candidate.is_symlink() or not candidate.is_dir():
            raise ContractError(
                f"output parent must be a private directory: {candidate}"
            )
        if created:
            os.chmod(candidate, PRIVATE_DIRECTORY_MODE, follow_symlinks=False)

    if directory.is_symlink() or not directory.is_dir():
        raise ContractError(f"output parent must be a private directory: {directory}")
    mode = stat.S_IMODE(os.stat(directory, follow_symlinks=False).st_mode)
    if mode & 0o077:
        raise ContractError(
            f"output directory must not grant group or other access: {directory}"
        )


def write_json(path: str | Path, value: Any) -> None:
    target = Path(path)
    if target.is_symlink():
        raise ContractError(f"refusing symlink output: {target}")
    if target.exists() and not target.is_file():
        raise ContractError(f"output must be a regular file: {target}")
    _ensure_private_output_directory(target.parent)

    payload = canonical_bytes(value) + b"\n"
    temporary: Path | None = None
    descriptor: int | None = None
    try:
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{target.name}.", suffix=".tmp", dir=target.parent
        )
        temporary = Path(temporary_name)
        os.fchmod(descriptor, PRIVATE_FILE_MODE)
        with os.fdopen(descriptor, "wb") as handle:
            descriptor = None
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        if (
            stat.S_IMODE(os.stat(temporary, follow_symlinks=False).st_mode)
            != PRIVATE_FILE_MODE
        ):
            raise ContractError("private temporary output mode is not 0600")
        os.replace(temporary, target)
        temporary = None
        os.chmod(target, PRIVATE_FILE_MODE, follow_symlinks=False)
        directory_flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
        directory_descriptor = os.open(target.parent, directory_flags)
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


def require_dict(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ContractError(f"{label} must be an object")
    return value


def require_string(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ContractError(f"{label} must be a non-empty string")
    return value.strip()


def require_string_list(value: Any, label: str, nonempty: bool = False) -> list[str]:
    if not isinstance(value, list) or any(
        not isinstance(item, str) or not item.strip() for item in value
    ):
        raise ContractError(f"{label} must be a list of non-empty strings")
    if nonempty and not value:
        raise ContractError(f"{label} must not be empty")
    return [item.strip() for item in value]


def require_timestamp(value: Any, label: str) -> str:
    text = require_string(value, label)
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ContractError(f"{label} must be an ISO-8601 timestamp") from exc
    if parsed.tzinfo is None:
        raise ContractError(f"{label} must include a timezone")
    return text


def timestamp_now() -> str:
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def ensure_sha256(value: Any, label: str) -> str:
    text = require_string(value, label)
    if not SHA256_RE.fullmatch(text):
        raise ContractError(f"{label} must be 64 lowercase hex characters")
    return text


def _path_has_prefix(path: str, prefix: str) -> bool:
    return (
        path == prefix or path.startswith(f"{prefix}.") or path.startswith(f"{prefix}[")
    )


def _validate_understanding_gap_field(gap_type: str, value: Any, label: str) -> str:
    path = require_string(value, label)
    prefixes = PAPER_UNDERSTANDING_GAP_FIELD_PREFIXES[gap_type]
    if not any(_path_has_prefix(path, prefix) for prefix in prefixes):
        raise ContractError(
            f"{label} must use an allowed {gap_type} field prefix: {sorted(prefixes)}"
        )
    if not PAPER_UNDERSTANDING_GAP_FIELD_PATTERNS[gap_type].fullmatch(path):
        raise ContractError(f"{label} is not a supported {gap_type} field path")
    return path


def _require_external_query_safe(value: Any, label: str) -> str:
    text = require_string(value, label)
    if _query_has_internal_marker(text):
        raise ContractError(f"{label} must not contain internal IDs or field names")
    if any(pattern.search(text) for pattern in SENSITIVE_EXTERNAL_QUERY_PATTERNS):
        raise ContractError(f"{label} must not contain secrets, private paths, or keys")
    return text


def validate_paper_understanding_gap(value: Any) -> dict[str, Any]:
    """Validate a missing-detail observation without interpreting paper semantics.

    The referenced PaperUnderstanding and adapter projection are opaque here. Their
    content-addressed validation/projection records are provenance, not input for a
    second semantic reading pass in this skill.
    """
    gap = require_dict(value, "paper understanding gap")
    expected_keys = {
        "schema",
        "gap_id",
        "gap_digest",
        "gap_type",
        "projection_type",
        "missing_field",
        "question",
        "search_terms",
        "provenance",
        "novelty_claimed",
    }
    if set(gap) != expected_keys:
        raise ContractError(
            f"paper understanding gap must contain exactly {sorted(expected_keys)}"
        )
    if gap.get("schema") != PAPER_UNDERSTANDING_GAP_SCHEMA:
        raise ContractError(
            "paper understanding gap.schema must equal "
            f"{PAPER_UNDERSTANDING_GAP_SCHEMA}"
        )

    gap_type = require_string(gap.get("gap_type"), "paper understanding gap.gap_type")
    if gap_type not in PAPER_UNDERSTANDING_GAP_TYPES:
        raise ContractError(
            "paper understanding gap.gap_type must be one of "
            f"{sorted(PAPER_UNDERSTANDING_GAP_TYPES)}"
        )
    projection_type = require_string(
        gap.get("projection_type"), "paper understanding gap.projection_type"
    )
    if projection_type != PAPER_UNDERSTANDING_GAP_TO_PROJECTION[gap_type]:
        raise ContractError(
            "paper understanding gap.projection_type is incompatible with gap_type"
        )
    missing_field = _validate_understanding_gap_field(
        gap_type,
        gap.get("missing_field"),
        "paper understanding gap.missing_field",
    )
    _require_external_query_safe(
        gap.get("question"), "paper understanding gap.question"
    )
    if gap.get("novelty_claimed") is not False:
        raise ContractError("paper understanding gap.novelty_claimed must be false")

    terms = require_dict(
        gap.get("search_terms"), "paper understanding gap.search_terms"
    )
    if set(terms) != {"must", "should", "must_not"}:
        raise ContractError(
            "paper understanding gap.search_terms must contain exactly "
            "must, should, and must_not"
        )
    for key in ("must", "should", "must_not"):
        entries = require_string_list(
            terms.get(key),
            f"paper understanding gap.search_terms.{key}",
            nonempty=key == "must",
        )
        if len(entries) != len(set(entries)):
            raise ContractError(
                f"paper understanding gap.search_terms.{key} must be unique"
            )
        for index, entry in enumerate(entries):
            _require_external_query_safe(
                entry, f"paper understanding gap.search_terms.{key}[{index}]"
            )

    provenance = require_dict(
        gap.get("provenance"), "paper understanding gap.provenance"
    )
    if set(provenance) != {
        "understanding_binding",
        "projection_ref",
        "basis_refs",
    }:
        raise ContractError(
            "paper understanding gap.provenance must contain exactly "
            "understanding_binding, projection_ref, and basis_refs"
        )

    understanding_binding = require_dict(
        provenance.get("understanding_binding"),
        "paper understanding gap.provenance.understanding_binding",
    )
    if set(understanding_binding) != {
        "understanding_id",
        "understanding_digest",
        "validation_record_id",
        "validation_record_digest",
    }:
        raise ContractError(
            "understanding_binding must contain exactly understanding_id, "
            "understanding_digest, validation_record_id, and validation_record_digest"
        )
    require_string(
        understanding_binding.get("understanding_id"),
        "understanding_binding.understanding_id",
    )
    ensure_sha256(
        understanding_binding.get("understanding_digest"),
        "understanding_binding.understanding_digest",
    )
    if understanding_binding.get("understanding_id") != (
        "paper-understanding-" + understanding_binding["understanding_digest"][:16]
    ):
        raise ContractError(
            "understanding_binding.understanding_id does not match understanding_digest"
        )
    validation_record_digest = ensure_sha256(
        understanding_binding.get("validation_record_digest"),
        "understanding_binding.validation_record_digest",
    )
    if understanding_binding.get("validation_record_id") != (
        "paper-understanding-validation-" + validation_record_digest[:16]
    ):
        raise ContractError(
            "understanding_binding.validation_record_id does not match "
            "validation_record_digest"
        )

    projection_ref = require_dict(
        provenance.get("projection_ref"),
        "paper understanding gap.provenance.projection_ref",
    )
    if set(projection_ref) != {
        "schema",
        "projection_id",
        "projection_digest",
        "projection_type",
        "payload_digest",
    }:
        raise ContractError(
            "projection_ref must contain exactly schema, projection_id, "
            "projection_digest, projection_type, and payload_digest"
        )
    if projection_ref.get("schema") != UNDERSTANDING_NETWORK_PROJECTION_SCHEMA:
        raise ContractError(
            "projection_ref.schema must equal "
            f"{UNDERSTANDING_NETWORK_PROJECTION_SCHEMA}"
        )
    require_string(projection_ref.get("projection_id"), "projection_ref.projection_id")
    ensure_sha256(
        projection_ref.get("projection_digest"), "projection_ref.projection_digest"
    )
    if projection_ref.get("projection_id") != (
        "understanding-projection-" + projection_ref["projection_digest"][:16]
    ):
        raise ContractError(
            "projection_ref.projection_id does not match projection_digest"
        )
    if projection_ref.get("projection_type") != projection_type:
        raise ContractError("projection_ref.projection_type does not match gap")
    payload_digest = ensure_sha256(
        projection_ref.get("payload_digest"), "projection_ref.payload_digest"
    )

    basis_refs = provenance.get("basis_refs")
    if not isinstance(basis_refs, list) or not basis_refs:
        raise ContractError(
            "paper understanding gap.provenance.basis_refs must be a non-empty list"
        )
    seen_basis: set[tuple[str, str, str, str]] = set()
    covers_missing_field = False
    for index, raw_basis in enumerate(basis_refs):
        basis = require_dict(
            raw_basis, f"paper understanding gap.provenance.basis_refs[{index}]"
        )
        if set(basis) != {
            "ref_type",
            "projection_type",
            "source_path",
            "payload_digest",
        }:
            raise ContractError(
                "paper understanding gap basis refs must contain exactly ref_type, "
                "projection_type, source_path, and payload_digest"
            )
        if basis.get("ref_type") != "understanding_projection_path":
            raise ContractError("paper understanding gap basis ref_type is invalid")
        if basis.get("projection_type") != projection_type:
            raise ContractError(
                "paper understanding gap basis projection_type mismatch"
            )
        basis_path = _validate_understanding_gap_field(
            gap_type,
            basis.get("source_path"),
            f"paper understanding gap.provenance.basis_refs[{index}].source_path",
        )
        if (
            ensure_sha256(
                basis.get("payload_digest"),
                f"paper understanding gap.provenance.basis_refs[{index}].payload_digest",
            )
            != payload_digest
        ):
            raise ContractError("paper understanding gap basis payload_digest mismatch")
        basis_key = (
            basis["ref_type"],
            basis["projection_type"],
            basis_path,
            basis["payload_digest"],
        )
        if basis_key in seen_basis:
            raise ContractError("paper understanding gap basis refs must be unique")
        seen_basis.add(basis_key)
        covers_missing_field = covers_missing_field or basis_path == missing_field
    if not covers_missing_field:
        raise ContractError(
            "paper understanding gap basis refs must bind missing_field"
        )

    gap_digest = ensure_sha256(
        gap.get("gap_digest"), "paper understanding gap.gap_digest"
    )
    if gap_digest != canonical_paper_understanding_gap_digest(gap):
        raise ContractError("paper understanding gap.gap_digest is invalid")
    if gap.get("gap_id") != f"understanding-gap-{gap_digest[:16]}":
        raise ContractError("paper understanding gap.gap_id is invalid")
    return gap


def request_digest(request: dict[str, Any]) -> str:
    return sha256_json(request)


def access_to_read_depth(access_level: str) -> str:
    return "full_text" if access_level == "full_text" else "evidence"


def validate_network(value: Any) -> dict[str, Any]:
    network = require_dict(value, "network")
    if network.get("schema") != NETWORK_SCHEMA:
        raise ContractError(f"network.schema must equal {NETWORK_SCHEMA}")
    declared_content_sha256 = ensure_sha256(
        network.get("content_sha256"), "network.content_sha256"
    )
    expected_content_sha256 = sha256_json(
        {key: item for key, item in network.items() if key != "content_sha256"}
    )
    if declared_content_sha256 != expected_content_sha256:
        raise ContractError(
            "network.content_sha256 must hash the canonical export payload "
            "without content_sha256"
        )
    require_string(network.get("network_id"), "network.network_id")
    require_string(network.get("snapshot_id"), "network.snapshot_id")
    for field in ("nodes", "relations", "gaps"):
        if not isinstance(network.get(field), list):
            raise ContractError(f"network.{field} must be a list")

    network_node_ids = [
        str(node.get("node_id")) for node in network["nodes"] if node.get("node_id")
    ]
    if len(network_node_ids) != len(set(network_node_ids)):
        raise ContractError("network nodes must have unique node_id")

    network_relation_ids = [
        str(relation.get("relation_id"))
        for relation in network["relations"]
        if relation.get("relation_id") is not None
    ]
    if len(network_relation_ids) != len(set(network_relation_ids)):
        raise ContractError("network relations must have unique relation_id")

    sources = network.get("sources", [])
    if not isinstance(sources, list):
        raise ContractError("network.sources must be a list when present")
    source_ids = []
    for index, source in enumerate(sources):
        entry = require_dict(source, f"network.sources[{index}]")
        source_ids.append(
            require_string(
                entry.get("source_id"), f"network.sources[{index}].source_id"
            )
        )
    if len(source_ids) != len(set(source_ids)):
        raise ContractError("network sources must have unique source_id")

    return network


def _live_source_ids(network: dict[str, Any]) -> set[str]:
    validated = validate_network(network)
    return {
        source["source_id"]
        for source in validated.get("sources", [])
        if isinstance(source, dict) and isinstance(source.get("source_id"), str)
    }


def _dedupe_terms(values: list[str]) -> list[str]:
    seen = set()
    output = []
    for value in values:
        normalized = value.strip()
        if not normalized:
            continue
        key = normalized.lower()
        if key in seen:
            continue
        seen.add(key)
        output.append(normalized)
    return output


def _query_has_internal_marker(value: str) -> bool:
    lower = value.lower()
    if any(marker in lower for marker in INTERNAL_QUERY_BLOCKLIST):
        return True
    if re.search(
        r"\b(?:gap|relation|node|claim|derived|unmet_declared_gate|completion\.)[:_-][A-Za-z0-9_-]+",
        lower,
    ):
        return True
    if re.search(r"\bcompletion\.gate_checks\.[a-z0-9_]+\b", lower):
        return True
    for token in QUERY_TOKEN_RE.findall(lower):
        if token in INTERNAL_QUERY_FIELD_NAMES:
            return True
        if _query_token_is_internal(token):
            return True
    return False


def _query_token_is_internal(token: str) -> bool:
    lower = token.lower()
    if lower in INTERNAL_QUERY_FIELD_NAMES:
        return True
    if any(lower.startswith(prefix) for prefix in INTERNAL_QUERY_PREFIXES):
        return True
    if re.fullmatch(
        r"(?:g|rel|kgh|gaph|entity|claim|derived)[-_:][a-zA-Z0-9._+-]+",
        lower,
    ):
        return True
    if re.fullmatch(r"[a-z0-9_]+(?:\.[a-z0-9_]+){1,}", lower):
        return True
    return False


def _query_semantic_token_candidates(value: str) -> list[str]:
    tokens = QUERY_TOKEN_RE.findall(value.lower())
    output: list[str] = []
    for token in tokens:
        if token in QUERY_TERM_BLOCKLIST:
            continue
        if token in QUERY_STOP_WORDS:
            continue
        if token.isnumeric():
            continue
        if _query_token_is_internal(token):
            continue
        output.append(token)
    return output


def _query_has_semantic_content(
    value: str, required_terms: list[str] | None = None
) -> bool:
    if _query_has_internal_marker(value):
        return False
    if "no evidence for" in value.lower() and "at this snapshot" in value.lower():
        return False

    if len(value.split()) > SEMANTIC_QUERY_MAX_WORDS:
        return False

    lower = value.lower()
    required = [term.lower() for term in (required_terms or []) if term]
    if required:
        for term in required:
            if term and term in lower:
                return True

    tokens = _query_semantic_token_candidates(value)
    if not tokens:
        return False
    if len(tokens) > SEMANTIC_QUERY_MAX_WORDS:
        return False
    semantic_count = sum(1 for token in tokens if len(token) > 3)
    return semantic_count >= 1


def _normalize_terms(values: list[str]) -> str:
    return " ".join(
        _dedupe_terms(
            [
                value.strip()
                for value in values
                if isinstance(value, str) and value.strip()
            ]
        )
    )


def _strip_internal_query_tokens(value: str) -> str:
    tokens = QUERY_TOKEN_RE.findall(value)
    return " ".join(token for token in tokens if not _query_token_is_internal(token))


def _collect_node_labels(node: dict[str, Any] | None) -> list[str]:
    if node is None:
        return []
    values: list[str] = []
    if isinstance(node.get("label"), str):
        values.append(str(node["label"]))
    aliases = node.get("aliases")
    if isinstance(aliases, list):
        for alias in aliases:
            if isinstance(alias, str):
                values.append(alias)
    return values


def _claim_node_for_gap(
    gap: dict[str, Any] | None,
    node_lookup: dict[str, dict[str, Any]],
) -> dict[str, Any] | None:
    if not isinstance(gap, dict):
        return None
    claim_id = gap.get("claim_id")
    if not isinstance(claim_id, str) or not claim_id.strip():
        return None
    claim_id = claim_id.strip()
    candidates = [claim_id]
    if not claim_id.startswith("claim:"):
        candidates.insert(0, f"claim:{claim_id}")
    for candidate in candidates:
        node = node_lookup.get(candidate)
        if isinstance(node, dict) and node.get("kind") == "claim":
            return node
    return None


def _collect_semantic_terms(values: list[Any]) -> list[str]:
    terms: list[str] = []
    for value in values:
        if value is None:
            continue
        if isinstance(value, str):
            text = value.strip()
            if text:
                terms.append(text)
                terms.extend(_query_semantic_token_candidates(text))
            continue
        if not isinstance(value, list):
            continue
        for item in value:
            if not isinstance(item, str):
                continue
            text = item.strip()
            if text:
                terms.append(text)
                terms.extend(_query_semantic_token_candidates(text))
    return terms


def _collect_node_terms(node: dict[str, Any] | None) -> list[str]:
    return _collect_semantic_terms(
        [
            node.get("label") if isinstance(node, dict) else None,
            node.get("aliases") if isinstance(node, dict) else None,
            node.get("search_terms") if isinstance(node, dict) else None,
            node.get("taxonomy_terms") if isinstance(node, dict) else None,
            node.get("topics") if isinstance(node, dict) else None,
        ]
    )


def _collect_relation_terms(relation: dict[str, Any] | None) -> list[str]:
    return _collect_semantic_terms(
        [
            relation.get("search_terms") if isinstance(relation, dict) else None,
            relation.get("notes") if isinstance(relation, dict) else None,
        ]
    )


def _collect_research_context_terms(network: dict[str, Any]) -> list[str]:
    context = network.get("research_context") if isinstance(network, dict) else None
    if not isinstance(context, dict):
        return []
    return _collect_semantic_terms(
        [
            context.get("search_terms"),
            context.get("domain_phrases"),
            context.get("research_terms"),
            context.get("topics"),
        ]
    )


def _normalize_search_terms(values: list[str]) -> list[str]:
    tokens = _query_semantic_token_candidates(" ".join(values))
    if not tokens:
        return []
    normalized: list[str] = []
    workflow_terms = {
        "gap",
        "open",
        "explicit",
        "missing",
        "coverage",
        "completion",
        "gate",
        "status",
    }
    for token in tokens:
        lowered = token.lower()
        if lowered in workflow_terms:
            continue
        if lowered in GAP_REASON_TERM_BLOCKLIST:
            continue
        if _query_has_internal_marker(token):
            continue
        normalized.append(token)
    return _dedupe_terms(normalized)


def _need_semantic_enrichment(terms: list[str]) -> bool:
    tokens = _normalize_search_terms(terms)
    if len(tokens) < 2:
        return True
    if all(token in QUERY_STOP_WORDS for token in tokens):
        return True
    return False


def _build_semantic_search_spec(
    signal: dict[str, Any],
    network: dict[str, Any],
) -> tuple[list[str], bool]:
    node_lookup = {
        str(node.get("node_id")): node
        for node in network["nodes"]
        if node.get("node_id")
    }
    relation_lookup = {
        str(rel.get("relation_id")): rel
        for rel in network["relations"]
        if rel.get("relation_id")
    }
    gap_lookup = {
        str(gap.get("gap_id")): gap for gap in network["gaps"] if gap.get("gap_id")
    }

    kind = signal.get("kind")
    ref = str(signal.get("refs", [""])[0])
    terms: list[str] = []
    structural_only = False
    gap_context_terms = _collect_research_context_terms(network)

    explicit_gap = kind == "explicit_open_gap"

    if explicit_gap:
        gap = gap_lookup.get(ref)
        claim_node = _claim_node_for_gap(gap, node_lookup)
        if ref.startswith("derived:missing-dimension:") or (
            gap is not None and gap.get("gap_type") == "deterministic_structural"
        ):
            return [], True
        if gap is not None:
            terms.extend(_collect_node_terms(claim_node))
            if claim_node is None:
                terms.extend(
                    _collect_semantic_terms(
                        [
                            gap.get("title"),
                            gap.get("name"),
                            gap.get("reason"),
                            gap.get("description"),
                            gap.get("next_action"),
                        ]
                    )
                )

    elif kind == "unmet_declared_gate":
        structural_only = True

    elif kind == "topological_isolate":
        node = node_lookup.get(ref)
        terms.extend(_collect_node_terms(node))

    elif kind == "low_confidence_relation":
        relation = relation_lookup.get(ref)
        if relation is not None:
            source = node_lookup.get(str(relation.get("from_id")))
            target = node_lookup.get(str(relation.get("to_id")))
            source_labels = _collect_node_terms(source)
            target_labels = _collect_node_terms(target)
            terms.extend(source_labels)
            terms.extend(target_labels)
            terms.extend(_collect_relation_terms(relation))

    else:
        structural_only = True
        if signal.get("reason") and isinstance(signal["reason"], str):
            terms.extend(_collect_semantic_terms([signal["reason"]]))

    terms.extend(gap_context_terms)
    terms = _normalize_search_terms(terms)

    if _need_semantic_enrichment(terms):
        structural_only = True

    if kind == "unmet_declared_gate":
        structural_only = True

    return terms, structural_only


def _build_semantic_search_query(
    terms: list[str],
    objective: str,
    fallback: str = "benchmark evidence",
) -> str:
    fragments = _dedupe_terms(
        [term for term in terms if isinstance(term, str) and term.strip()]
    )
    if not fragments:
        fragments = [fallback]

    anchor = next((term for term in fragments if " " in term.strip()), None)
    if anchor is not None:
        fragments = [anchor] + [term for term in fragments if term != anchor]

    refute_modifiers = [
        "limitation",
        "comparison",
        "counterfactual",
        "counterexample",
        "null",
        "scope",
    ]
    if objective == "refute":
        fragments = fragments + refute_modifiers

    query_tokens: list[str] = []
    for fragment in fragments:
        if " " in fragment:
            cleaned_fragment = _strip_internal_query_tokens(fragment)
            if cleaned_fragment:
                cleaned_terms = cleaned_fragment.split()
                if len(cleaned_terms) <= SEMANTIC_QUERY_MAX_WORDS:
                    query_tokens.append(" ".join(cleaned_terms))
                else:
                    query_tokens.extend(cleaned_terms)
            else:
                query_tokens.extend(_query_semantic_token_candidates(fragment))
            continue
        query_tokens.extend(_query_semantic_token_candidates(fragment))
    expanded_query_tokens: list[str] = []
    for token in query_tokens:
        if " " in token:
            expanded_query_tokens.extend(token.split())
        else:
            expanded_query_tokens.append(token)
    query_tokens = _dedupe_terms(expanded_query_tokens)
    if not query_tokens:
        query_tokens = fallback.split()

    if objective == "confirm":
        return " ".join(query_tokens[:SEMANTIC_QUERY_MAX_WORDS])
    if objective == "refute":
        return " ".join(query_tokens[:SEMANTIC_QUERY_MAX_WORDS])
    return " ".join(query_tokens[:SEMANTIC_QUERY_MAX_WORDS])


GENERIC_DISCOVERY_TEXT = {
    "confidence may require independent evidence",
    "multiple bounded routes and grounded fallback",
    "semantic enrichment required",
}


def _is_generic_discovery_text(value: Any) -> bool:
    if not isinstance(value, str):
        return True
    normalized = re.sub(r"\s+", " ", value.strip().casefold())
    return not normalized or normalized in GENERIC_DISCOVERY_TEXT


def _semantic_paper_need(
    label: Any,
    search_terms: list[str],
    *,
    independent_evidence: bool = False,
) -> str:
    if (
        isinstance(label, str)
        and not _is_generic_discovery_text(label)
        and not _query_has_internal_marker(label)
        and _query_has_semantic_content(label)
    ):
        return label.strip()

    semantic_query = _build_semantic_search_query(search_terms, "confirm", fallback="")
    if semantic_query.strip():
        prefix = (
            "Find independent primary evidence that directly tests"
            if independent_evidence
            else "Find primary evidence that directly tests"
        )
        return f"{prefix}: {semantic_query}."
    return "Resolve missing semantic source and target labels before scholarly search."


def _semantic_acceptance_criteria(label: Any, search_terms: list[str]) -> str:
    paper_need = _semantic_paper_need(label, search_terms)
    return (
        "Primary full-text evidence must directly evaluate the bounded need "
        f'"{paper_need}" and report the tested method or comparison, assumptions, '
        "result or limitation, and an exact source locator."
    )


def network_ref(network: dict[str, Any]) -> dict[str, str]:
    validated = validate_network(network)
    return {
        "network_id": validated["network_id"],
        "snapshot_id": validated["snapshot_id"],
        "sha256": validated["content_sha256"],
    }


def network_reference_index(network: dict[str, Any]) -> dict[str, set[str]]:
    nodes = {
        str(node.get("node_id"))
        for node in network["nodes"]
        if node.get("node_id") is not None
    }
    relations = {
        str(relation.get("relation_id"))
        for relation in network["relations"]
        if relation.get("relation_id") is not None
    }
    gaps = {
        str(gap.get("gap_id"))
        for gap in network["gaps"]
        if gap.get("gap_id") is not None
    }
    completion = require_dict(network.get("completion", {}), "network.completion")
    gate_checks = require_dict(
        completion.get("gate_checks", {}), "network.completion.gate_checks"
    )
    gate_refs = {f"completion.gate_checks.{gate}" for gate in gate_checks}
    return {
        "network_id": {network["network_id"]},
        "nodes": nodes,
        "relations": relations,
        "gaps": gaps,
        "gate_refs": gate_refs,
    }


def validate_network_ref(
    value: Any, label: str, network: dict[str, Any] | None = None
) -> dict[str, str]:
    ref = require_dict(value, label)
    require_string(ref.get("network_id"), f"{label}.network_id")
    require_string(ref.get("snapshot_id"), f"{label}.snapshot_id")
    digest = require_string(ref.get("sha256"), f"{label}.sha256")
    ensure_sha256(digest, f"{label}.sha256")
    if network is not None and ref != network_ref(validate_network(network)):
        raise ContractError(f"{label} does not match supplied network")
    return ref


def validate_hypothesis_reference(
    ref_id: str, index: dict[str, set[str]], label: str
) -> None:
    if ref_id in {f"network:{network_id}" for network_id in index["network_id"]}:
        return
    if (
        ref_id in index["nodes"]
        or ref_id in index["relations"]
        or ref_id in index["gaps"]
    ):
        return
    if ref_id.startswith("node:") and ref_id.split(":", 1)[1] in index["nodes"]:
        return
    if ref_id.startswith("relation:") and ref_id.split(":", 1)[1] in index["relations"]:
        return
    if ref_id.startswith("gap:") and ref_id.split(":", 1)[1] in index["gaps"]:
        return
    if ref_id in index["gate_refs"]:
        return
    raise ContractError(f"{label} must reference current network context")


def connected_components(
    node_ids: set[str], adjacency: dict[str, set[str]]
) -> list[list[str]]:
    unseen = set(node_ids)
    components: list[list[str]] = []
    while unseen:
        start = min(unseen)
        unseen.remove(start)
        queue = deque([start])
        component: list[str] = []
        while queue:
            current = queue.popleft()
            component.append(current)
            for neighbor in sorted(adjacency.get(current, set())):
                if neighbor in unseen:
                    unseen.remove(neighbor)
                    queue.append(neighbor)
        components.append(sorted(component))
    return sorted(components, key=lambda item: (-len(item), item))


def _gap_declared_priority(gap: dict[str, Any]) -> str:
    declared = gap.get("declared_priority")
    if declared in {"P0", "P1", "P2", "P3"}:
        return str(declared)
    if gap.get("decision_impact") == "high":
        return "decision_high"
    if gap.get("priority") == "decision_critical" or gap.get("impact") == "high":
        return "legacy_high"
    if gap.get("impact") == "medium":
        return "legacy_medium"
    return "low"


def _gap_signal_tier(gap: dict[str, Any]) -> str:
    gap_id = str(gap.get("gap_id") or "")
    rule = str(gap.get("derivation_rule") or "")
    if rule == "single_independent_source" or gap_id.startswith(
        "derived:single-source:"
    ):
        return "single_source"
    if rule == "isolated_claim" or gap_id.startswith("derived:isolated:"):
        return "isolate"
    if gap.get("gap_type") == "explicit" and gap.get("claim_id") is None:
        priority = _gap_declared_priority(gap)
        if priority in {
            "P0",
            "P1",
            "decision_high",
            "legacy_high",
            "legacy_medium",
        }:
            return "explicit_high_impact"
        return "explicit"
    if gap.get("gap_type") == "explicit":
        return "explicit"
    return "structural"


def _candidate_signal_context(
    signal: dict[str, Any], network: dict[str, Any]
) -> tuple[str, str, str, str]:
    gap_lookup = {
        str(gap.get("gap_id")): gap for gap in network["gaps"] if gap.get("gap_id")
    }
    kind = str(signal.get("kind") or "")
    ref = str(signal.get("refs", [""])[0])
    if kind == "explicit_open_gap":
        gap = gap_lookup.get(ref, {})
        tier = _gap_signal_tier(gap)
        priority = _gap_declared_priority(gap)
        claim_id = gap.get("claim_id")
        if isinstance(claim_id, str) and claim_id:
            subject = claim_id if claim_id.startswith("claim:") else f"claim:{claim_id}"
            node_lookup = {
                str(node.get("node_id")): node
                for node in network["nodes"]
                if node.get("node_id")
            }
            claim_node = _claim_node_for_gap(gap, node_lookup)
            claim_label = (
                str(claim_node.get("label") or "").strip()
                if claim_node is not None
                else ""
            )
            label = (
                claim_label
                if claim_label and not _query_has_internal_marker(claim_label)
                else "Claim evidence requires semantic enrichment"
            )
        else:
            label = str(gap.get("description") or gap.get("reason") or ref)
            normalized = re.sub(r"\W+", " ", label.casefold()).strip()
            subject = f"gap-semantic:{normalized or ref}"
        return tier, priority, subject, label
    if kind == "unmet_declared_gate":
        return "unmet_gate", "decision_high", ref, str(signal.get("reason") or ref)
    if kind == "topological_isolate":
        return "isolate", "low", ref, str(signal.get("reason") or ref)
    if kind == "low_confidence_relation":
        search_terms, _ = _build_semantic_search_spec(signal, network)
        label = _semantic_paper_need(
            signal.get("reason"),
            search_terms,
            independent_evidence=True,
        )
        return "low_confidence", "low", ref, label
    return "structural", "low", ref, str(signal.get("reason") or ref)


def _candidate_signal_sort_key(signal: dict[str, Any]) -> tuple[Any, ...]:
    priority_order = {
        "P0": 0,
        "decision_high": 1,
        "legacy_high": 2,
        "P1": 3,
        "legacy_medium": 4,
        "P2": 5,
        "P3": 6,
        "low": 7,
    }
    return (
        CANDIDATE_SIGNAL_TIER_ORDER.index(str(signal["tier"])),
        priority_order.get(str(signal["source_priority"]), 8),
        str(signal.get("semantic_label") or "").casefold(),
        str(signal["signal_id"]),
    )


def _bounded_candidate_signals(
    signals: list[dict[str, Any]], network: dict[str, Any]
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    enriched: list[dict[str, Any]] = []
    for source in signals:
        signal = dict(source)
        tier, priority, subject, label = _candidate_signal_context(signal, network)
        signal.update(
            {
                "tier": tier,
                "source_priority": priority,
                "dedupe_key": subject,
                "semantic_label": label,
            }
        )
        enriched.append(signal)

    deduplicated: list[dict[str, Any]] = []
    seen_subjects: set[str] = set()
    duplicate_by_tier: Counter[str] = Counter()
    for signal in sorted(enriched, key=_candidate_signal_sort_key):
        subject = str(signal["dedupe_key"])
        if subject in seen_subjects:
            duplicate_by_tier[str(signal["tier"])] += 1
            continue
        seen_subjects.add(subject)
        deduplicated.append(signal)

    selected: list[dict[str, Any]] = []
    selected_by_tier: Counter[str] = Counter()
    budget_suppressed_by_tier: Counter[str] = Counter()
    for signal in deduplicated:
        tier = str(signal["tier"])
        if (
            len(selected) >= CANDIDATE_SIGNAL_MAX_TOTAL
            or selected_by_tier[tier] >= CANDIDATE_SIGNAL_TIER_BUDGETS[tier]
        ):
            budget_suppressed_by_tier[tier] += 1
            continue
        selected.append(signal)
        selected_by_tier[tier] += 1

    suppressed_by_tier = Counter(duplicate_by_tier)
    suppressed_by_tier.update(budget_suppressed_by_tier)
    summary = {
        "raw_count": len(signals),
        "deduplicated_count": len(deduplicated),
        "selected_count": len(selected),
        "suppressed_count": len(signals) - len(selected),
        "selected_by_tier": dict(sorted(selected_by_tier.items())),
        "suppressed_by_tier": dict(sorted(suppressed_by_tier.items())),
    }
    return selected, summary


def scan_network(value: Any) -> dict[str, Any]:
    network = validate_network(value)
    nodes = {
        str(node.get("node_id")): node
        for node in network["nodes"]
        if node.get("node_id") is not None
    }
    node_ids = set(nodes)
    adjacency = {node_id: set() for node_id in node_ids}
    dangling: list[str] = []
    low_confidence: list[str] = []
    missing_provenance: list[str] = []
    predicate_counts: Counter[str] = Counter()
    for relation in network["relations"]:
        relation_id = str(relation.get("relation_id", "<missing>"))
        source = relation.get("from_id")
        target = relation.get("to_id")
        predicate_counts[str(relation.get("predicate", "<missing>"))] += 1
        if source not in node_ids or target not in node_ids:
            dangling.append(relation_id)
        else:
            adjacency[str(source)].add(str(target))
            adjacency[str(target)].add(str(source))
        if relation.get("confidence") in {"low", "unknown", None} or relation.get(
            "status"
        ) in {"unresolved", "conflicting"}:
            low_confidence.append(relation_id)
        if not relation.get("provenance"):
            missing_provenance.append(relation_id)

    isolates = sorted(
        node_id
        for node_id, neighbors in adjacency.items()
        if not neighbors and nodes[node_id].get("kind") != "source"
    )
    components = connected_components(node_ids, adjacency)
    open_gaps = sorted(
        str(gap.get("gap_id"))
        for gap in network["gaps"]
        if gap.get("status") not in {"resolved", "closed"}
    )
    completion = require_dict(network.get("completion", {}), "network.completion")
    gate_checks = require_dict(
        completion.get("gate_checks", {}), "network.completion.gate_checks"
    )
    unmet_gates = sorted(
        key for key, passed in gate_checks.items() if passed is not True
    )

    signals: list[dict[str, Any]] = []
    for gap_id in open_gaps:
        signals.append(
            {
                "signal_id": "signal:gap:" + sha256_json(gap_id)[:12],
                "kind": "explicit_open_gap",
                "refs": [gap_id],
                "classification": "deterministic_structural_signal",
                "reason": "an explicit open gap is present in this snapshot",
            }
        )
    for gate in unmet_gates:
        signals.append(
            {
                "signal_id": "signal:gate:" + sha256_json(gate)[:12],
                "kind": "unmet_declared_gate",
                "refs": [f"completion.gate_checks.{gate}"],
                "classification": "deterministic_structural_signal",
                "reason": "an explicit completion contract is unmet",
            }
        )
    for node_id in isolates:
        signals.append(
            {
                "signal_id": "signal:isolate:" + sha256_json(node_id)[:12],
                "kind": "topological_isolate",
                "refs": [node_id],
                "classification": "implicit_candidate_signal",
                "reason": "topology may reflect aliasing, scope, or missing relations",
            }
        )
    for relation_id in sorted(set(low_confidence)):
        signals.append(
            {
                "signal_id": "signal:low-confidence:" + sha256_json(relation_id)[:12],
                "kind": "low_confidence_relation",
                "refs": [relation_id],
                "classification": "implicit_candidate_signal",
                "reason": "confidence may require independent evidence",
            }
        )
    selected_signals, signal_summary = _bounded_candidate_signals(signals, network)
    probe = {
        "schema": PROBE_SCHEMA,
        "network_ref": network_ref(network),
        "open_world_policy": "absence_is_unknown_without_local_completeness_contract",
        "counts": {
            "nodes": len(nodes),
            "relations": len(network["relations"]),
            "gaps": len(network["gaps"]),
            "node_kinds": dict(
                sorted(
                    Counter(
                        node.get("kind", "<missing>") for node in nodes.values()
                    ).items()
                )
            ),
            "predicates": dict(sorted(predicate_counts.items())),
        },
        "existing_open_gap_ids": open_gaps,
        "unmet_completion_gates": unmet_gates,
        "topological_isolates": isolates,
        "connected_components": components,
        "dangling_relation_ids": sorted(set(dangling)),
        "low_confidence_relation_ids": sorted(set(low_confidence)),
        "relation_ids_without_provenance": sorted(set(missing_provenance)),
        "candidate_signals": selected_signals,
        "candidate_signal_policy": {
            "max_total": CANDIDATE_SIGNAL_MAX_TOTAL,
            "tier_order": list(CANDIDATE_SIGNAL_TIER_ORDER),
            "tier_budgets": dict(CANDIDATE_SIGNAL_TIER_BUDGETS),
            "legacy_probe_strategy": "deterministic_bounded_projection",
        },
        "candidate_signal_summary": signal_summary,
        "probe_families": PROBE_FAMILIES,
        "novelty_claimed": False,
    }
    return validate_probe(probe)


def validate_probe(value: Any) -> dict[str, Any]:
    probe = require_dict(value, "probe")
    if probe.get("schema") != PROBE_SCHEMA:
        raise ContractError(f"probe.schema must equal {PROBE_SCHEMA}")
    validate_network_ref(probe.get("network_ref"), "probe.network_ref")
    if probe.get("novelty_claimed") is not False:
        raise ContractError("probe.novelty_claimed must be false")
    if not isinstance(probe.get("candidate_signals"), list):
        raise ContractError("probe.candidate_signals must be a list")
    policy = probe.get("candidate_signal_policy")
    if policy is not None:
        policy = require_dict(policy, "probe.candidate_signal_policy")
        max_total = policy.get("max_total")
        if (
            not isinstance(max_total, int)
            or not 0 < max_total <= CANDIDATE_SIGNAL_MAX_TOTAL
        ):
            raise ContractError("probe candidate signal max_total is invalid")
        if len(probe["candidate_signals"]) > max_total:
            raise ContractError("probe candidate signals exceed max_total")
    return probe


def signal_hypothesis_signature(signal: dict[str, Any]) -> str:
    kind = signal.get("kind")
    if kind == "explicit_open_gap":
        semantic_label = signal.get("semantic_label")
        if isinstance(semantic_label, str) and semantic_label.strip():
            return semantic_label.strip()
        reason = signal.get("reason")
        if isinstance(reason, str) and reason.strip():
            return reason.strip()
        return "semantic enrichment required"
    if kind == "unmet_declared_gate":
        return "semantic enrichment required"
    if kind == "topological_isolate":
        return "topological isolate"
    if kind == "low_confidence_relation":
        return "low confidence relation"
    return str(signal.get("kind", "candidate"))


def _require_string_allow_empty(value: Any, label: str) -> str:
    if not isinstance(value, str):
        raise ContractError(f"{label} must be a string")
    return value


def _canonical_own_digest(record: dict[str, Any], digest_field: str) -> str:
    normalized = copy.deepcopy(record)
    normalized[digest_field] = ""
    return sha256_json(normalized)


def _require_sorted_unique_strings(
    value: Any, label: str, *, nonempty: bool = False
) -> list[str]:
    values = require_string_list(value, label, nonempty)
    if values != sorted(set(values)):
        raise ContractError(f"{label} must be sorted and unique")
    return values


def _validate_semantic_signature(value: Any, label: str) -> dict[str, str]:
    signature = require_dict(value, label)
    if set(signature) != SEMANTIC_SIGNATURE_FIELDS:
        raise ContractError(
            f"{label} field set must be exactly {sorted(SEMANTIC_SIGNATURE_FIELDS)}"
        )
    for field in sorted(SEMANTIC_SIGNATURE_FIELDS):
        _require_external_query_safe(signature.get(field), f"{label}.{field}")
    return signature


def _validate_appraisal_set_ref(value: Any, label: str) -> dict[str, str]:
    ref = require_dict(value, label)
    if set(ref) != {"appraisal_set_id", "appraisal_set_digest"}:
        raise ContractError(
            f"{label} must contain exactly appraisal_set_id and appraisal_set_digest"
        )
    require_string(ref.get("appraisal_set_id"), f"{label}.appraisal_set_id")
    ensure_sha256(ref.get("appraisal_set_digest"), f"{label}.appraisal_set_digest")
    return ref


def _validate_adversarial_observation_pair(
    value: Any,
    label: str,
    semantic_signature: dict[str, str],
) -> dict[str, Any]:
    pair = require_dict(value, label)
    if set(pair) != {"target_metric", "comparator", "boundary", "confirm", "refute"}:
        raise ContractError(
            f"{label} must contain exactly target_metric, comparator, boundary, "
            "confirm, and refute"
        )
    for field in ("target_metric", "comparator", "boundary"):
        _require_external_query_safe(pair.get(field), f"{label}.{field}")
    if pair["comparator"] != semantic_signature["comparator"]:
        raise ContractError(f"{label}.comparator must match semantic_signature")
    if pair["boundary"] != semantic_signature["boundary_variable"]:
        raise ContractError(f"{label}.boundary must match semantic_signature")
    arms: dict[str, dict[str, str]] = {}
    for arm_name in ("confirm", "refute"):
        arm = require_dict(pair.get(arm_name), f"{label}.{arm_name}")
        if set(arm) != {"operator", "value_or_state", "claim_implication"}:
            raise ContractError(
                f"{label}.{arm_name} must contain exactly operator, value_or_state, "
                "and claim_implication"
            )
        operator = require_string(arm.get("operator"), f"{label}.{arm_name}.operator")
        _require_external_query_safe(
            arm.get("value_or_state"), f"{label}.{arm_name}.value_or_state"
        )
        implication = require_string(
            arm.get("claim_implication"),
            f"{label}.{arm_name}.claim_implication",
        )
        arms[arm_name] = {
            "operator": operator,
            "value_or_state": arm["value_or_state"],
            "claim_implication": implication,
        }
    confirm = arms["confirm"]
    refute = arms["refute"]
    if confirm["operator"] not in OBSERVATION_OPERATOR_COMPLEMENTS:
        raise ContractError(f"{label}.confirm.operator is unsupported")
    if refute["operator"] != OBSERVATION_OPERATOR_COMPLEMENTS[confirm["operator"]]:
        raise ContractError(f"{label} operators must be an ordered complementary pair")
    if " ".join(confirm["value_or_state"].casefold().split()) != " ".join(
        refute["value_or_state"].casefold().split()
    ):
        raise ContractError(
            f"{label} arms must test the same normalized value_or_state"
        )
    if confirm["claim_implication"] != "supports":
        raise ContractError(f"{label}.confirm.claim_implication must equal supports")
    if refute["claim_implication"] != "challenges":
        raise ContractError(f"{label}.refute.claim_implication must equal challenges")
    return pair


def format_adversarial_observation_goal(pair: dict[str, Any], objective: str) -> str:
    if objective not in {"confirm", "refute"}:
        raise ContractError("observation goal objective must be confirm or refute")
    arm = pair[objective]
    return (
        f"target_metric={pair['target_metric']}; "
        f"comparator={pair['comparator']}; "
        f"boundary={pair['boundary']}; "
        f"observation={arm['operator']} {arm['value_or_state']}; "
        f"claim_implication={arm['claim_implication']}"
    )


def _format_producer_observation_goal(pair_value: Any, objective: str) -> str:
    pair = require_dict(pair_value, "producer adversarial_observation_pair")
    if set(pair) != {"common", "confirm", "refute"}:
        raise ContractError(
            "producer adversarial_observation_pair must contain exactly "
            "common, confirm, and refute"
        )
    common = require_dict(pair.get("common"), "producer observation pair.common")
    if set(common) != {"target_metric", "comparator", "boundary"}:
        raise ContractError("producer observation pair.common field set is invalid")
    arm = require_dict(pair.get(objective), f"producer observation pair.{objective}")
    if set(arm) != {"operator", "value_or_state", "claim_implication"}:
        raise ContractError(
            f"producer observation pair.{objective} field set is invalid"
        )
    return (
        f"target_metric={require_string(common['target_metric'], 'target_metric')}; "
        f"comparator={require_string(common['comparator'], 'comparator')}; "
        f"boundary={require_string(common['boundary'], 'boundary')}; "
        f"observation={require_string(arm['operator'], 'operator')} "
        f"{require_string(str(arm['value_or_state']), 'value_or_state')}; "
        f"claim_implication={require_string(arm['claim_implication'], 'claim_implication')}"
    )


def _evidence_appraisal_module() -> Any:
    module_path = (
        Path(__file__).resolve().parents[2]
        / "evidence-appraisal"
        / "scripts"
        / "evidence_appraisal.py"
    )
    spec = importlib.util.spec_from_file_location(
        "_network_gap_evidence_appraisal", module_path
    )
    if spec is None or spec.loader is None:
        raise ContractError("cannot load evidence-appraisal producer adapter")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def validate_evidence_appraisal_package(
    value: Any,
    approval: Any | None = None,
    prepared: Any | None = None,
    independent_review: Any | None = None,
    owner_bundle: Any | None = None,
    *,
    expected_authority_sha256: str | None = None,
    lineage: list[Any] | tuple[Any, ...] = (),
) -> dict[str, Any]:
    try:
        package = _evidence_appraisal_module().validate_appraisal_package(
            copy.deepcopy(value),
            copy.deepcopy(approval),
            copy.deepcopy(prepared),
            copy.deepcopy(independent_review),
            copy.deepcopy(owner_bundle),
            expected_authority_sha256=copy.deepcopy(expected_authority_sha256),
            lineage=copy.deepcopy(lineage),
        )
    except (ValueError, TypeError) as exc:
        raise ContractError(f"invalid EvidenceAppraisalPackage/v1: {exc}") from exc
    challenges = package["challenges"]
    needs = package["targeted_evidence_need_set"]["needs"]
    for label, rows in (("challenge", challenges), ("need", needs)):
        for index, row in enumerate(rows):
            for objective, field in (
                ("confirm", "confirm_goal"),
                ("refute", "refute_goal"),
            ):
                if row[field] != _format_producer_observation_goal(
                    row["adversarial_observation_pair"], objective
                ):
                    raise ContractError(
                        f"producer {label}[{index}].{field} is not the canonical "
                        "structured projection"
                    )
    return package


def dispatch_evidence_appraisal_package(
    value: Any,
    approval: Any | None = None,
    prepared: Any | None = None,
    independent_review: Any | None = None,
    owner_bundle: Any | None = None,
    *,
    expected_authority_sha256: str | None = None,
    lineage: list[Any] | tuple[Any, ...] = (),
) -> dict[str, Any]:
    package = validate_evidence_appraisal_package(
        value,
        approval,
        prepared,
        independent_review,
        owner_bundle,
        expected_authority_sha256=expected_authority_sha256,
        lineage=lineage,
    )
    need_set = package["targeted_evidence_need_set"]
    needs = need_set["needs"]
    scholar_needs = [
        copy.deepcopy(need) for need in needs if need["route"] == "scholar_discovery"
    ]
    if scholar_needs:
        raise ContractError(
            "compact EvidenceAppraisalPackage/v1 scholar need lacks the bounded "
            "claim, scope, evidence-class, and criteria projection required for "
            "scholar discovery"
        )
    return {
        "schema": APPRAISAL_ROUTE_DISPATCH_SCHEMA,
        "package_ref": {
            "schema": package["schema"],
            "package_digest": package["package_digest"],
        },
        "appraisal_set_ref": {
            "appraisal_set_id": package["appraisal_set"]["appraisal_set_id"],
            "appraisal_set_digest": package["appraisal_set"]["appraisal_set_digest"],
        },
        "need_set_ref": {
            "schema": need_set["schema"],
            "need_set_digest": need_set["need_set_digest"],
        },
        "routed_needs": copy.deepcopy(needs),
        "scholar_discovery_needs": [],
        "mutation_authorized": False,
    }


def _challenge_seed(challenge: dict[str, Any]) -> dict[str, Any]:
    return {
        "target": {
            field: challenge["target"][field]
            for field in ("claim_id", "claim_digest", "evidence_id", "source_id")
        },
        "target_dimension": challenge["target_dimension"],
        "axis": challenge["axis"],
        "semantic_signature": copy.deepcopy(challenge["semantic_signature"]),
        "adversarial_observation_pair": copy.deepcopy(
            challenge["adversarial_observation_pair"]
        ),
    }


def validate_evidence_challenge(value: Any) -> dict[str, Any]:
    challenge = copy.deepcopy(require_dict(value, "evidence challenge"))
    expected_fields = {
        "schema",
        "challenge_id",
        "challenge_digest",
        "appraisal_set_ref",
        "target",
        "target_dimension",
        "axis",
        "severity",
        "status",
        "problem_statement",
        "falsifier",
        "discriminating_observation",
        "semantic_signature",
        "adversarial_observation_pair",
        "basis_refs",
        "resolution_route",
        "effect_on_overall",
        "supersedes",
    }
    if set(challenge) != expected_fields:
        raise ContractError(
            f"EvidenceChallenge/v1 field set must be exactly {sorted(expected_fields)}"
        )
    if challenge.get("schema") != EVIDENCE_CHALLENGE_SCHEMA:
        raise ContractError(
            f"evidence challenge.schema must equal {EVIDENCE_CHALLENGE_SCHEMA}"
        )
    _validate_appraisal_set_ref(
        challenge.get("appraisal_set_ref"), "evidence challenge.appraisal_set_ref"
    )
    target = require_dict(challenge.get("target"), "evidence challenge.target")
    target_fields = {
        "claim_id",
        "claim_digest",
        "evidence_id",
        "source_id",
        "appraisal_id",
        "appraisal_digest",
    }
    if set(target) != target_fields:
        raise ContractError(
            "evidence challenge.target field set must be exactly "
            f"{sorted(target_fields)}"
        )
    for field in sorted(target_fields):
        require_string(target.get(field), f"evidence challenge.target.{field}")
    ensure_sha256(target["claim_digest"], "evidence challenge.target.claim_digest")
    ensure_sha256(
        target["appraisal_digest"], "evidence challenge.target.appraisal_digest"
    )
    if challenge.get("target_dimension") not in EVIDENCE_TARGET_DIMENSIONS:
        raise ContractError("evidence challenge.target_dimension is invalid")
    if challenge.get("axis") not in EVIDENCE_CHALLENGE_AXES:
        raise ContractError("evidence challenge.axis is invalid")
    if challenge.get("severity") not in {"critical", "material", "minor"}:
        raise ContractError("evidence challenge.severity is invalid")
    if challenge.get("status") not in EVIDENCE_CHALLENGE_STATUSES:
        raise ContractError("evidence challenge.status is invalid")
    for field in ("problem_statement", "falsifier", "discriminating_observation"):
        _require_external_query_safe(
            challenge.get(field), f"evidence challenge.{field}"
        )
    signature = _validate_semantic_signature(
        challenge.get("semantic_signature"), "evidence challenge.semantic_signature"
    )
    _validate_adversarial_observation_pair(
        challenge.get("adversarial_observation_pair"),
        "evidence challenge.adversarial_observation_pair",
        signature,
    )
    if challenge.get("resolution_route") not in EVIDENCE_CHALLENGE_ROUTES:
        raise ContractError("evidence challenge.resolution_route is invalid")
    if challenge.get("effect_on_overall") not in {
        "blocks_decisive",
        "requires_scope_narrowing",
        "context_only",
    }:
        raise ContractError("evidence challenge.effect_on_overall is invalid")

    basis_refs = challenge.get("basis_refs")
    if not isinstance(basis_refs, list) or not basis_refs:
        raise ContractError("evidence challenge.basis_refs must be non-empty")
    for index, raw_ref in enumerate(basis_refs):
        ref = require_dict(raw_ref, f"evidence challenge.basis_refs[{index}]")
        if set(ref) != {"kind", "record_id", "record_digest", "locator_id"}:
            raise ContractError(
                "evidence challenge basis refs must contain exactly kind, record_id, "
                "record_digest, and locator_id"
            )
        require_string(ref.get("kind"), "evidence challenge basis kind")
        require_string(ref.get("record_id"), "evidence challenge basis record_id")
        ensure_sha256(ref.get("record_digest"), "evidence challenge basis digest")
        _require_string_allow_empty(
            ref.get("locator_id"), "evidence challenge basis locator_id"
        )
    if basis_refs != sorted(basis_refs, key=canonical_bytes) or len(
        {canonical_bytes(ref) for ref in basis_refs}
    ) != len(basis_refs):
        raise ContractError("evidence challenge.basis_refs must be sorted and unique")

    supersedes = challenge.get("supersedes")
    if not isinstance(supersedes, list):
        raise ContractError("evidence challenge.supersedes must be a list")
    for index, raw_ref in enumerate(supersedes):
        ref = require_dict(raw_ref, f"evidence challenge.supersedes[{index}]")
        if set(ref) != {"challenge_id", "challenge_digest"}:
            raise ContractError(
                "evidence challenge supersedes refs must contain exactly challenge_id "
                "and challenge_digest"
            )
        require_string(ref.get("challenge_id"), "superseded challenge_id")
        ensure_sha256(ref.get("challenge_digest"), "superseded challenge_digest")
    if supersedes != sorted(supersedes, key=canonical_bytes) or len(
        {canonical_bytes(ref) for ref in supersedes}
    ) != len(supersedes):
        raise ContractError("evidence challenge.supersedes must be sorted and unique")

    expected_id = "challenge-" + sha256_json(_challenge_seed(challenge))[:16]
    if challenge.get("challenge_id") != expected_id:
        raise ContractError("evidence challenge.challenge_id is invalid")
    digest = ensure_sha256(
        challenge.get("challenge_digest"), "evidence challenge.challenge_digest"
    )
    if digest != _canonical_own_digest(challenge, "challenge_digest"):
        raise ContractError("evidence challenge.challenge_digest is invalid")
    return challenge


def _validate_closed_ref(
    value: Any, label: str, id_field: str, digest_field: str
) -> dict[str, str]:
    ref = require_dict(value, label)
    if set(ref) != {id_field, digest_field}:
        raise ContractError(
            f"{label} must contain exactly {id_field} and {digest_field}"
        )
    require_string(ref.get(id_field), f"{label}.{id_field}")
    ensure_sha256(ref.get(digest_field), f"{label}.{digest_field}")
    return ref


def _need_seed(need: dict[str, Any]) -> dict[str, Any]:
    return {
        "challenge_ids": [ref["challenge_id"] for ref in need["challenge_refs"]],
        "claim_ref": copy.deepcopy(need["claim_ref"]),
        "route": need["route"],
        "target_scope": need["target_scope"],
        "required_evidence_class": need["required_evidence_class"],
        "semantic_signature": copy.deepcopy(need["semantic_signature"]),
        "adversarial_observation_pair": copy.deepcopy(
            need["adversarial_observation_pair"]
        ),
        "domain_anchors": copy.deepcopy(need["domain_anchors"]),
    }


def _validate_domain_anchors(value: Any, route: str, label: str) -> list[str]:
    if not isinstance(value, list):
        raise ContractError(f"{label} must be a list")
    anchors: list[str] = []
    for index, raw_anchor in enumerate(value):
        anchor = require_string(raw_anchor, f"{label}[{index}]")
        normalized = " ".join(anchor.casefold().split())
        if anchor != normalized:
            raise ContractError(f"{label}[{index}] must be a normalized phrase")
        token_count = len(anchor.split())
        if not 1 <= token_count <= 4:
            raise ContractError(f"{label}[{index}] must contain 1 to 4 tokens")
        _require_external_query_safe(anchor, f"{label}[{index}]")
        anchors.append(anchor)
    if anchors != list(dict.fromkeys(anchors)):
        raise ContractError(f"{label} must preserve order and contain no duplicates")
    if route == "scholar_discovery":
        if not 2 <= len(anchors) <= 6:
            raise ContractError(
                f"{label} must contain 2 to 6 phrases for scholar_discovery"
            )
    elif anchors:
        raise ContractError(f"{label} must be empty for non-scholar routes")
    return anchors


def validate_targeted_evidence_need_set(value: Any) -> dict[str, Any]:
    document = copy.deepcopy(require_dict(value, "targeted evidence need set"))
    expected_fields = {
        "schema",
        "need_set_id",
        "need_set_digest",
        "appraisal_set_ref",
        "needs",
    }
    if set(document) != expected_fields:
        raise ContractError(
            "TargetedEvidenceNeedSet/v1 field set must be exactly "
            f"{sorted(expected_fields)}"
        )
    if document.get("schema") != TARGETED_EVIDENCE_NEED_SET_SCHEMA:
        raise ContractError(
            "targeted evidence need set.schema must equal "
            f"{TARGETED_EVIDENCE_NEED_SET_SCHEMA}"
        )
    appraisal_set_ref = _validate_appraisal_set_ref(
        document.get("appraisal_set_ref"), "need set.appraisal_set_ref"
    )
    needs = document.get("needs")
    if not isinstance(needs, list) or not needs:
        raise ContractError("targeted evidence need set.needs must be non-empty")
    if len(needs) > 64:
        raise ContractError(
            "targeted evidence need set exceeds the bounded limit of 64"
        )

    seen_ids: set[str] = set()
    for index, raw_need in enumerate(needs):
        label = f"targeted evidence need set.needs[{index}]"
        need = require_dict(raw_need, label)
        expected_need_fields = {
            "need_id",
            "need_digest",
            "challenge_refs",
            "claim_ref",
            "appraisal_ref",
            "route",
            "status",
            "paper_need",
            "target_scope",
            "required_evidence_class",
            "must_criteria",
            "should_criteria",
            "must_not_criteria",
            "confirm_goal",
            "refute_goal",
            "falsifier",
            "semantic_signature",
            "adversarial_observation_pair",
            "domain_anchors",
            "acceptance_criterion",
            "exclusion_criterion",
            "decision_impact",
            "mutation_authorized",
            "supersedes",
        }
        if set(need) != expected_need_fields:
            raise ContractError(
                f"{label} field set must be exactly {sorted(expected_need_fields)}"
            )
        challenge_refs = need.get("challenge_refs")
        if not isinstance(challenge_refs, list) or not challenge_refs:
            raise ContractError(f"{label}.challenge_refs must be non-empty")
        for ref_index, ref in enumerate(challenge_refs):
            _validate_closed_ref(
                ref,
                f"{label}.challenge_refs[{ref_index}]",
                "challenge_id",
                "challenge_digest",
            )
        if challenge_refs != sorted(challenge_refs, key=canonical_bytes) or len(
            {canonical_bytes(ref) for ref in challenge_refs}
        ) != len(challenge_refs):
            raise ContractError(f"{label}.challenge_refs must be sorted and unique")
        _validate_closed_ref(
            need.get("claim_ref"), f"{label}.claim_ref", "claim_id", "claim_digest"
        )
        _validate_closed_ref(
            need.get("appraisal_ref"),
            f"{label}.appraisal_ref",
            "appraisal_id",
            "appraisal_digest",
        )
        if need.get("route") not in EVIDENCE_NEED_ROUTES:
            raise ContractError(f"{label}.route is invalid")
        if need.get("status") not in EVIDENCE_NEED_STATUSES:
            raise ContractError(f"{label}.status is invalid")
        for field in (
            "paper_need",
            "target_scope",
            "required_evidence_class",
            "falsifier",
            "acceptance_criterion",
            "exclusion_criterion",
        ):
            _require_external_query_safe(need.get(field), f"{label}.{field}")
        require_string(need.get("confirm_goal"), f"{label}.confirm_goal")
        require_string(need.get("refute_goal"), f"{label}.refute_goal")
        if " ".join(need["confirm_goal"].casefold().split()) == " ".join(
            need["refute_goal"].casefold().split()
        ):
            raise ContractError(f"{label} confirm_goal and refute_goal must differ")
        signature = _validate_semantic_signature(
            need.get("semantic_signature"), f"{label}.semantic_signature"
        )
        if signature["target_scope"] != need["target_scope"]:
            raise ContractError(f"{label}.target_scope must match semantic_signature")
        if signature["evidence_class"] != need["required_evidence_class"]:
            raise ContractError(
                f"{label}.required_evidence_class must match semantic_signature"
            )
        _validate_adversarial_observation_pair(
            need.get("adversarial_observation_pair"),
            f"{label}.adversarial_observation_pair",
            signature,
        )
        _validate_domain_anchors(
            need.get("domain_anchors"), need["route"], f"{label}.domain_anchors"
        )
        pair = need["adversarial_observation_pair"]
        for objective, field in (
            ("confirm", "confirm_goal"),
            ("refute", "refute_goal"),
        ):
            if need[field] != format_adversarial_observation_goal(pair, objective):
                raise ContractError(
                    f"{label}.{field} must equal the deterministic structured "
                    "observation projection"
                )
        for field in ("must_criteria", "should_criteria", "must_not_criteria"):
            values = _require_sorted_unique_strings(
                need.get(field), f"{label}.{field}", nonempty=field == "must_criteria"
            )
            for term_index, term in enumerate(values):
                _require_external_query_safe(term, f"{label}.{field}[{term_index}]")
        if need.get("decision_impact") not in LEVELS:
            raise ContractError(f"{label}.decision_impact is invalid")
        if need.get("mutation_authorized") is not False:
            raise ContractError(f"{label}.mutation_authorized must be false")
        supersedes = need.get("supersedes")
        if not isinstance(supersedes, list):
            raise ContractError(f"{label}.supersedes must be a list")
        for ref_index, ref in enumerate(supersedes):
            _validate_closed_ref(
                ref,
                f"{label}.supersedes[{ref_index}]",
                "need_id",
                "need_digest",
            )
        if supersedes != sorted(supersedes, key=canonical_bytes) or len(
            {canonical_bytes(ref) for ref in supersedes}
        ) != len(supersedes):
            raise ContractError(f"{label}.supersedes must be sorted and unique")

        expected_id = "need-" + sha256_json(_need_seed(need))[:16]
        if need.get("need_id") != expected_id:
            raise ContractError(f"{label}.need_id is invalid")
        digest = ensure_sha256(need.get("need_digest"), f"{label}.need_digest")
        if digest != _canonical_own_digest(need, "need_digest"):
            raise ContractError(f"{label}.need_digest is invalid")
        if need["need_id"] in seen_ids:
            raise ContractError("targeted evidence need IDs must be unique")
        seen_ids.add(need["need_id"])
    if [need["need_id"] for need in needs] != sorted(seen_ids):
        raise ContractError(
            "targeted evidence need set.needs must be sorted by need_id"
        )

    seed = {
        "appraisal_set_ref": copy.deepcopy(appraisal_set_ref),
        "need_ids": [need["need_id"] for need in needs],
    }
    expected_set_id = "need-set-" + sha256_json(seed)[:16]
    if document.get("need_set_id") != expected_set_id:
        raise ContractError("targeted evidence need set.need_set_id is invalid")
    digest = ensure_sha256(
        document.get("need_set_digest"), "targeted evidence need set.need_set_digest"
    )
    if digest != _canonical_own_digest(document, "need_set_digest"):
        raise ContractError("targeted evidence need set.need_set_digest is invalid")
    return document


def validate_reviewed_history_authority(value: Any) -> dict[str, Any]:
    try:
        return _scholar_discovery_module().validate_reviewed_history_authority(value)
    except ValueError as exc:
        raise ContractError(f"invalid ReviewedHistoryAuthority/v1: {exc}") from exc


def validate_history_authority_manifest(
    value: Any, reviewed_authority: Any
) -> dict[str, Any]:
    try:
        return _scholar_discovery_module().validate_history_authority_manifest(
            value, reviewed_authority
        )
    except ValueError as exc:
        raise ContractError(f"invalid HistoryAuthorityManifest/v1: {exc}") from exc


def validate_search_history_index(
    value: Any,
    authority_manifest: Any,
    reviewed_authority: Any,
    *,
    execution_authority_contexts: dict[str, dict[str, Any]] | None = None,
    artifact_file_sha256s: list[str] | None = None,
) -> dict[str, Any]:
    document = copy.deepcopy(value) if isinstance(value, dict) else value
    if artifact_file_sha256s is None:
        if isinstance(document, dict):
            raw_hashes = document.get("artifact_file_sha256s")
            if "artifact_file_sha256s" in document:
                document = copy.deepcopy(document)
                document.pop("artifact_file_sha256s", None)
            if raw_hashes is not None:
                artifact_file_sha256s = (
                    list(raw_hashes) if isinstance(raw_hashes, list) else None
                )
        else:
            raw_hashes = None
    else:
        if isinstance(document, dict) and "artifact_file_sha256s" in document:
            document = copy.deepcopy(document)
            document.pop("artifact_file_sha256s", None)
    try:
        return _scholar_discovery_module().validate_search_history_index(
            document,
            authority_manifest,
            reviewed_authority,
            execution_authority_contexts=execution_authority_contexts,
            artifact_file_sha256s=artifact_file_sha256s,
        )
    except ValueError as exc:
        raise ContractError(f"invalid SearchHistoryIndex: {exc}") from exc


def _semantic_terms(value: str) -> list[str]:
    try:
        return _scholar_discovery_module().canonical_semantic_terms(value)
    except ValueError as exc:
        raise ContractError(f"cannot derive semantic signature: {exc}") from exc


def _semantic_term_signature(terms: list[str]) -> str:
    try:
        return _scholar_discovery_module().semantic_signature_from_terms(terms)
    except ValueError as exc:
        raise ContractError(f"cannot derive semantic signature: {exc}") from exc


def _objective_terms(need: dict[str, Any], objective: str) -> list[str]:
    signature = need["semantic_signature"]
    pair = need["adversarial_observation_pair"]
    observation = pair[objective]
    common_context = " ".join(
        [
            need["target_scope"],
            signature["comparator"],
            signature["boundary_variable"],
            signature["evidence_class"],
            signature["independence_requirement"],
            pair["target_metric"],
            OBSERVATION_OPERATOR_QUERY_TEXT[observation["operator"]],
            observation["value_or_state"],
            observation["claim_implication"],
        ]
    )
    return _semantic_terms(
        f"{common_context} {format_adversarial_observation_goal(pair, objective)}"
    )


def _structured_query_slot_terms(value: str, label: str) -> list[str]:
    text = require_string(value, label)
    terms = [term for term in _semantic_terms(text) if term not in {"under"}]
    numeric_terms = re.findall(r"(?<![\w])\d+(?:\.\d+)?(?![\w])", text.casefold())
    normalized = list(dict.fromkeys([*terms, *numeric_terms]))
    if not normalized:
        raise ContractError(f"{label} has no query-preservable terms")
    return normalized


def _normalized_contiguous_phrase(value: str, label: str) -> str:
    """Normalize a human phrase without reducing it to a concept bag."""
    text = require_string(value, label)
    phrase = " ".join(re.findall(r"[^\W_]+", text.casefold(), flags=re.UNICODE))
    if not phrase:
        raise ContractError(f"{label} has no phrase-preservable terms")
    return phrase


def _structured_query_slot_phrase(value: str, label: str) -> str:
    return _normalized_contiguous_phrase(value, label)


def _contains_contiguous_phrase(text: str, phrase: str) -> bool:
    """Match whole normalized phrases, never an unordered token collection."""
    return f" {phrase} " in f" {text} "


def _has_structured_slot_prefix(text: str, slot_phrases: list[str]) -> bool:
    """Require every ordered structural slot occurrence, including duplicates."""
    prefix = " ".join(slot_phrases)
    return text == prefix or text.startswith(f"{prefix} ")


def _structured_appraisal_query_core(
    need: dict[str, Any], objective: str
) -> tuple[list[str], dict[str, list[str]]]:
    pair = need["adversarial_observation_pair"]
    observation = pair[objective]
    slots = {
        "target_metric": pair["target_metric"],
        "comparator": pair["comparator"],
        "boundary": pair["boundary"],
        "operator": OBSERVATION_OPERATOR_QUERY_TEXT[observation["operator"]],
        "value_or_state": observation["value_or_state"],
    }
    slot_terms = {
        field: _structured_query_slot_terms(
            value, f"{objective} structured query slot {field}"
        )
        for field, value in slots.items()
    }
    core_terms = [
        term
        for field in (
            "target_metric",
            "comparator",
            "boundary",
            "operator",
            "value_or_state",
        )
        for term in slot_terms[field]
    ]
    if len(core_terms) > SEMANTIC_QUERY_MAX_WORDS:
        raise ContractError(
            f"{objective} structured observation core exceeds the "
            f"{SEMANTIC_QUERY_MAX_WORDS}-term query budget"
        )
    return core_terms, slot_terms


def _appraisal_queries(need: dict[str, Any]) -> list[dict[str, str]]:
    raw_semantic_fields = [
        need["paper_need"],
        need["target_scope"],
        need["required_evidence_class"],
        need["confirm_goal"],
        need["refute_goal"],
        need["falsifier"],
        *need["must_criteria"],
        *need["should_criteria"],
        *need["must_not_criteria"],
        *need["domain_anchors"],
    ]
    if any(
        pattern.search(value)
        for value in raw_semantic_fields
        for pattern in STRUCTURAL_APPRAISAL_PATTERNS
    ):
        raise ContractError(
            "appraisal need contains a structural placeholder rather than evidence semantics"
        )
    confirm_goal_terms = _semantic_terms(need["confirm_goal"])
    refute_goal_terms = _semantic_terms(need["refute_goal"])
    if not confirm_goal_terms or not refute_goal_terms:
        raise ContractError("appraisal goals must contain semantic concepts")
    confirm_signature = _semantic_term_signature(confirm_goal_terms)
    refute_signature = _semantic_term_signature(refute_goal_terms)
    if confirm_signature == refute_signature:
        raise ContractError(
            "confirm/refute semantic signatures are identical; polarity-only or "
            "synonym-only rewrites are not adversarially orthogonal"
        )
    output: list[dict[str, str]] = []
    for objective in ("confirm", "refute"):
        terms = _objective_terms(need, objective)
        _, _ = _structured_appraisal_query_core(need, objective)
        anchor_phrases = [
            _normalized_contiguous_phrase(
                anchor, f"{objective} domain anchor {anchor_index}"
            )
            for anchor_index, anchor in enumerate(need["domain_anchors"])
        ]
        pair = need["adversarial_observation_pair"]
        observation = pair[objective]
        slot_phrases = {
            "target_metric": _structured_query_slot_phrase(
                pair["target_metric"],
                f"{objective} structured query slot target_metric",
            ),
            "comparator": _structured_query_slot_phrase(
                pair["comparator"], f"{objective} structured query slot comparator"
            ),
            "boundary": _structured_query_slot_phrase(
                pair["boundary"], f"{objective} structured query slot boundary"
            ),
            "operator": _structured_query_slot_phrase(
                OBSERVATION_OPERATOR_QUERY_TEXT[observation["operator"]],
                f"{objective} structured query slot operator",
            ),
            "value_or_state": _structured_query_slot_phrase(
                observation["value_or_state"],
                f"{objective} structured query slot value_or_state",
            ),
        }
        mandatory_fragments = [
            slot_phrases[field]
            for field in (
                "target_metric",
                "comparator",
                "boundary",
                "operator",
                "value_or_state",
            )
        ]
        mandatory_fragments.extend(anchor_phrases)
        mandatory_term_count = sum(
            len(fragment.split()) for fragment in mandatory_fragments
        )
        if mandatory_term_count > SEMANTIC_QUERY_MAX_WORDS:
            raise ContractError(
                f"{objective} structured observation and domain-anchor core exceeds "
                f"the {SEMANTIC_QUERY_MAX_WORDS}-term query budget"
            )
        goal = need["confirm_goal"] if objective == "confirm" else need["refute_goal"]
        free_terms = _semantic_terms(goal)
        if objective == "refute":
            falsifier_terms = _semantic_terms(need["falsifier"])
            terms = sorted(set(terms) | set(falsifier_terms))
            free_terms = sorted(set(free_terms) | set(falsifier_terms))
        free_terms = list(dict.fromkeys([*free_terms, *terms]))
        if len(terms) < 3:
            raise ContractError(
                f"{objective} goal is too structural or broad for targeted discovery"
            )
        remaining_budget = SEMANTIC_QUERY_MAX_WORDS - mandatory_term_count
        free_terms = [
            term for term in free_terms if term not in APPRAISAL_QUERY_LABEL_TERMS
        ]
        query = " ".join([*mandatory_fragments, *free_terms[:remaining_budget]])
        operator_state_phrase = (
            f"{slot_phrases['operator']} {slot_phrases['value_or_state']}"
        ).strip()
        normalized_query_phrase = _normalized_contiguous_phrase(
            query, f"{objective} normalized query"
        )
        if len(normalized_query_phrase.split()) > SEMANTIC_QUERY_MAX_WORDS:
            raise ContractError(
                f"{objective} final query exceeds the "
                f"{SEMANTIC_QUERY_MAX_WORDS}-term query budget"
            )
        if not _has_structured_slot_prefix(
            normalized_query_phrase, mandatory_fragments
        ):
            raise ContractError(
                f"{objective} normalized query does not preserve each ordered "
                "structured slot occurrence"
            )
        for required_field in (
            "target_metric",
            "comparator",
            "boundary",
            "operator",
            "value_or_state",
            "operator-state",
        ):
            phrase = (
                operator_state_phrase
                if required_field == "operator-state"
                else slot_phrases[required_field]
            )
            if not _contains_contiguous_phrase(normalized_query_phrase, phrase):
                raise ContractError(
                    f"{objective} normalized query does not preserve structured "
                    f"{required_field} terms"
                )
        for anchor_index, anchor_phrase in enumerate(anchor_phrases):
            if not _contains_contiguous_phrase(normalized_query_phrase, anchor_phrase):
                raise ContractError(
                    f"{objective} normalized query does not preserve domain anchor "
                    f"{anchor_index}"
                )
        if any(pattern.search(query) for pattern in STRUCTURAL_APPRAISAL_PATTERNS):
            raise ContractError(
                f"{objective} query contains a structural placeholder rather than evidence semantics"
            )
        output.append(
            {
                "objective": objective,
                "query": query,
                "semantic_signature": _semantic_term_signature(terms),
            }
        )
    if output[0]["semantic_signature"] == output[1]["semantic_signature"]:
        raise ContractError(
            "compiled confirm/refute queries are not semantically orthogonal"
        )
    return output


def _semantic_overlap(left: list[str], right: list[str]) -> tuple[float, float, int]:
    left_set = set(left)
    right_set = set(right)
    intersection = len(left_set & right_set)
    if not left_set or not right_set:
        return 0.0, 0.0, intersection
    containment = intersection / min(len(left_set), len(right_set))
    union = len(left_set | right_set)
    return containment, intersection / union, intersection


def _history_duplicate_matches(
    need: dict[str, Any], history_index: dict[str, Any]
) -> list[dict[str, Any]]:
    matches: list[dict[str, Any]] = []
    for objective in ("confirm", "refute"):
        terms = _objective_terms(need, objective)
        signature = _semantic_term_signature(terms)
        for entry in history_index["entries"]:
            containment, jaccard, shared = _semantic_overlap(
                terms, entry["canonical_terms"]
            )
            if signature == entry["semantic_signature"] or (
                shared >= 4 and containment >= 0.75 and jaccard >= 0.5
            ):
                matches.append(
                    {
                        "objective": objective,
                        "history_objective": entry["objective"],
                        "history_state": entry["state"],
                        "history_signature": entry["semantic_signature"],
                    }
                )
    return matches


def _validate_need_challenge_binding(
    need: dict[str, Any], challenges: dict[str, dict[str, Any]]
) -> list[dict[str, Any]]:
    bound: list[dict[str, Any]] = []
    for ref in need["challenge_refs"]:
        challenge = challenges.get(ref["challenge_id"])
        if (
            challenge is None
            or challenge["challenge_digest"] != ref["challenge_digest"]
        ):
            raise ContractError(
                f"need {need['need_id']} references an absent or digest-mismatched challenge"
            )
        if challenge["status"] != "open":
            raise ContractError("compile-appraisal-needs consumes only open challenges")
        if challenge["resolution_route"] != "targeted_evidence_need":
            raise ContractError(
                "a targeted need may only bind a challenge routed to targeted_evidence_need"
            )
        if need["claim_ref"] != {
            "claim_id": challenge["target"]["claim_id"],
            "claim_digest": challenge["target"]["claim_digest"],
        }:
            raise ContractError("targeted need claim_ref does not match its challenge")
        if need["appraisal_ref"] != {
            "appraisal_id": challenge["target"]["appraisal_id"],
            "appraisal_digest": challenge["target"]["appraisal_digest"],
        }:
            raise ContractError(
                "targeted need appraisal_ref does not match its challenge"
            )
        if need["semantic_signature"] != challenge["semantic_signature"]:
            raise ContractError(
                "targeted need semantic_signature does not match its challenge"
            )
        if (
            need["adversarial_observation_pair"]
            != challenge["adversarial_observation_pair"]
        ):
            raise ContractError(
                "targeted need adversarial_observation_pair does not match its challenge"
            )
        if need["falsifier"] != challenge["falsifier"]:
            raise ContractError("targeted need falsifier does not match its challenge")

        axis_field = CHALLENGE_AXIS_SIGNATURE_FIELD[challenge["axis"]]
        axis_terms = set(_semantic_terms(challenge["semantic_signature"][axis_field]))
        for objective in ("confirm", "refute"):
            if not axis_terms.intersection(_objective_terms(need, objective)):
                raise ContractError(
                    f"{objective} goal does not bind challenge axis {challenge['axis']}"
                )
        bound.append(challenge)
    return bound


def _appraisal_origin(need_set: dict[str, Any], need: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema": APPRAISAL_ORIGIN_SCHEMA,
        "appraisal_set_ref": copy.deepcopy(need_set["appraisal_set_ref"]),
        "need_set_ref": {
            "need_set_id": need_set["need_set_id"],
            "need_set_digest": need_set["need_set_digest"],
        },
        "need_ref": {
            "need_id": need["need_id"],
            "need_digest": need["need_digest"],
            "route": need["route"],
        },
        "challenge_refs": copy.deepcopy(need["challenge_refs"]),
        "claim_ref": copy.deepcopy(need["claim_ref"]),
        "appraisal_ref": copy.deepcopy(need["appraisal_ref"]),
    }


def _validate_appraisal_origin(value: Any, label: str) -> dict[str, Any]:
    origin = require_dict(value, label)
    expected = {
        "schema",
        "need_set_ref",
        "need_ref",
        "challenge_refs",
        "claim_ref",
        "appraisal_ref",
        "appraisal_set_ref",
    }
    if set(origin) != expected or origin.get("schema") != APPRAISAL_ORIGIN_SCHEMA:
        raise ContractError(f"{label} is not a closed {APPRAISAL_ORIGIN_SCHEMA}")
    _validate_appraisal_set_ref(
        origin.get("appraisal_set_ref"), f"{label}.appraisal_set_ref"
    )
    _validate_closed_ref(
        origin.get("need_set_ref"),
        f"{label}.need_set_ref",
        "need_set_id",
        "need_set_digest",
    )
    need_ref = require_dict(origin.get("need_ref"), f"{label}.need_ref")
    if set(need_ref) != {"need_id", "need_digest", "route"}:
        raise ContractError(f"{label}.need_ref has an invalid field set")
    require_string(need_ref.get("need_id"), f"{label}.need_ref.need_id")
    ensure_sha256(need_ref.get("need_digest"), f"{label}.need_ref.need_digest")
    if need_ref.get("route") != "scholar_discovery":
        raise ContractError(f"{label}.need_ref.route must equal scholar_discovery")
    refs = origin.get("challenge_refs")
    if not isinstance(refs, list) or not refs:
        raise ContractError(f"{label}.challenge_refs must be non-empty")
    for index, ref in enumerate(refs):
        _validate_closed_ref(
            ref, f"{label}.challenge_refs[{index}]", "challenge_id", "challenge_digest"
        )
    if refs != sorted(refs, key=canonical_bytes) or len(
        {canonical_bytes(ref) for ref in refs}
    ) != len(refs):
        raise ContractError(f"{label}.challenge_refs must be sorted and unique")
    _validate_closed_ref(
        origin.get("claim_ref"), f"{label}.claim_ref", "claim_id", "claim_digest"
    )
    _validate_closed_ref(
        origin.get("appraisal_ref"),
        f"{label}.appraisal_ref",
        "appraisal_id",
        "appraisal_digest",
    )
    return origin


def _hypothesis_from_appraisal_need(
    need_set: dict[str, Any],
    need: dict[str, Any],
    challenges: list[dict[str, Any]],
    network: dict[str, Any],
) -> dict[str, Any]:
    queries = _appraisal_queries(need)
    target_terms = _semantic_terms(" ".join(need["semantic_signature"].values()))
    source_tier = (
        "explicit_high_impact" if need["decision_impact"] == "high" else "explicit"
    )
    return {
        "hypothesis_id": f"KGH-APP-{need['need_digest'][:12]}",
        "gap_type": "implicit_candidate",
        "target_kind": "evidence",
        "target_signature": " ".join(target_terms[:8]),
        "scope_and_time_bounds": need["target_scope"],
        "semantic_label": need["paper_need"],
        "hypothesis": need["confirm_goal"],
        "grounds": [
            {
                "ref_id": f"network:{network['network_id']}",
                "statement": challenges[0]["problem_statement"],
            }
        ],
        "warrant": " ".join(challenge["problem_statement"] for challenge in challenges),
        "backing": [
            {
                "ref_id": f"network:{network['network_id']}",
                "locator": "EvidenceChallenge/v1 and TargetedEvidenceNeedSet/v1",
            }
        ],
        "qualifier": "bounded targeted need; absence is not novelty or nonexistence",
        "defeaters": sorted(set([need["falsifier"], need["refute_goal"]])),
        "search_test": {
            "queries": queries,
            "route_families": [
                "openalex",
                "semantic_scholar",
                "crossref",
                "google_scholar",
            ],
            "expected_confirming_observation": need["confirm_goal"],
            "expected_disconfirming_observation": need["falsifier"],
            "acceptance_criteria": need["acceptance_criterion"],
            "criteria": {
                "must": copy.deepcopy(need["must_criteria"]),
                "should": copy.deepcopy(need["should_criteria"]),
                "must_not": copy.deepcopy(need["must_not_criteria"]),
            },
            "metadata_filters": {},
            "seeds": {"titles": [], "arxiv": []},
        },
        "expected_information_gain": "resolves a specific appraisal challenge",
        "decision_impact": need["decision_impact"],
        "uncertainty": "high",
        "searchability": "high",
        "cross_branch_blocking": need["decision_impact"] == "high",
        "source_signal_kind": "appraisal_targeted_need",
        "source_signal_tier": source_tier,
        "source_priority": "P0" if need["decision_impact"] == "high" else "P1",
        "dependencies": [ref["challenge_id"] for ref in need["challenge_refs"]],
        "status": "proposed",
        "status_basis": [],
        "novelty_claimed": False,
        "structural_only": False,
        "next_action": "scholar_discovery",
        "appraisal_origin": _appraisal_origin(need_set, need),
        "domain_anchors": copy.deepcopy(need["domain_anchors"]),
    }


def compile_appraisal_needs(
    need_set_value: Any,
    challenge_values: list[Any],
    history_index_value: Any,
    history_authority_value: Any,
    history_authority_review_value: Any,
    network_value: Any,
    *,
    round_id: str,
    execution_authority_contexts: dict[str, dict[str, Any]] | None = None,
    artifact_file_sha256s: list[str] | None = None,
) -> dict[str, Any]:
    network = validate_network(network_value)
    need_set = validate_targeted_evidence_need_set(need_set_value)
    history_authority_review = validate_reviewed_history_authority(
        history_authority_review_value
    )
    history_authority = validate_history_authority_manifest(
        history_authority_value, history_authority_review
    )
    history_index = validate_search_history_index(
        history_index_value,
        history_authority,
        history_authority_review,
        execution_authority_contexts=execution_authority_contexts,
        artifact_file_sha256s=artifact_file_sha256s,
    )
    require_string(round_id, "compile-appraisal-needs round_id")
    if not isinstance(challenge_values, list) or not challenge_values:
        raise ContractError(
            "compile-appraisal-needs requires EvidenceChallenge/v1 inputs"
        )
    challenges_list = sorted(
        [validate_evidence_challenge(value) for value in challenge_values],
        key=lambda row: row["challenge_id"],
    )
    challenges = {row["challenge_id"]: row for row in challenges_list}
    if len(challenges) != len(challenges_list):
        raise ContractError("compile-appraisal-needs challenge IDs must be unique")
    if any(
        challenge["appraisal_set_ref"] != need_set["appraisal_set_ref"]
        for challenge in challenges_list
    ):
        raise ContractError(
            "compile-appraisal-needs appraisal_set_ref mismatch across inputs"
        )

    referenced_challenge_ids = {
        ref["challenge_id"]
        for need in need_set["needs"]
        for ref in need["challenge_refs"]
    }
    if referenced_challenge_ids != set(challenges):
        raise ContractError(
            "compile-appraisal-needs challenges must exactly match need challenge_refs"
        )

    hypotheses: list[dict[str, Any]] = []
    routed_needs: list[dict[str, Any]] = []
    repeated_needs: list[dict[str, Any]] = []
    scholar_count = 0
    for need in need_set["needs"]:
        if need["status"] != "proposed":
            raise ContractError("compile-appraisal-needs consumes only proposed needs")
        bound_challenges = _validate_need_challenge_binding(need, challenges)
        if need["route"] != "scholar_discovery":
            routed_needs.append(copy.deepcopy(need))
            continue
        scholar_count += 1
        _appraisal_queries(need)
        matches = _history_duplicate_matches(need, history_index)
        if matches:
            repeated_needs.append({"need_id": need["need_id"], "matches": matches})
            continue
        hypotheses.append(
            _hypothesis_from_appraisal_need(need_set, need, bound_challenges, network)
        )

    if repeated_needs:
        ratio = len(repeated_needs) / max(1, scholar_count)
        prefix = (
            "Round-style 9/10 history reuse" if ratio >= 0.9 else "search-history reuse"
        )
        raise ContractError(
            f"{prefix} rejected: {len(repeated_needs)}/{scholar_count} scholar needs "
            "repeat canonical, selection-leak, failed, partial, result, or candidate semantics"
        )

    output = {
        "schema": HYPOTHESES_SCHEMA,
        "network_ref": network_ref(network),
        "round_id": round_id,
        "generated_at": timestamp_now(),
        "method_families": [
            "adversarial_countercheck",
            "evidence_appraisal",
            "targeted_missing_content",
        ],
        "hypotheses": hypotheses,
        "appraisal_compilation": {
            "schema": APPRAISAL_COMPILATION_SCHEMA,
            "need_set": copy.deepcopy(need_set),
            "challenges": copy.deepcopy(challenges_list),
            "history_authority": copy.deepcopy(history_authority),
            "history_authority_review": copy.deepcopy(history_authority_review),
            "history_index": copy.deepcopy(history_index),
        },
        "routed_needs": routed_needs,
    }
    return validate_hypotheses(
        output,
        network,
        execution_authority_contexts=execution_authority_contexts,
        history_artifact_file_sha256s=artifact_file_sha256s,
    )


def _validate_appraisal_projection(
    document: dict[str, Any],
    network: dict[str, Any] | None,
    *,
    execution_authority_contexts: dict[str, dict[str, Any]] | None = None,
    history_artifact_file_sha256s: list[str] | None = None,
) -> None:
    compilation = require_dict(
        document.get("appraisal_compilation"), "hypotheses.appraisal_compilation"
    )
    if set(compilation) != {
        "schema",
        "need_set",
        "challenges",
        "history_authority",
        "history_authority_review",
        "history_index",
    }:
        raise ContractError("hypotheses.appraisal_compilation has an invalid field set")
    if compilation.get("schema") != APPRAISAL_COMPILATION_SCHEMA:
        raise ContractError("hypotheses.appraisal_compilation.schema is invalid")
    need_set = validate_targeted_evidence_need_set(compilation.get("need_set"))
    history_authority_review = validate_reviewed_history_authority(
        compilation.get("history_authority_review")
    )
    history_authority = validate_history_authority_manifest(
        compilation.get("history_authority"), history_authority_review
    )
    history_index = validate_search_history_index(
        compilation.get("history_index"),
        history_authority,
        history_authority_review,
        execution_authority_contexts=execution_authority_contexts,
        artifact_file_sha256s=history_artifact_file_sha256s,
    )
    raw_challenges = compilation.get("challenges")
    if not isinstance(raw_challenges, list) or not raw_challenges:
        raise ContractError(
            "hypotheses.appraisal_compilation.challenges must be non-empty"
        )
    challenges_list = [validate_evidence_challenge(value) for value in raw_challenges]
    if challenges_list != sorted(challenges_list, key=lambda row: row["challenge_id"]):
        raise ContractError("appraisal compilation challenges must be sorted")
    challenges = {row["challenge_id"]: row for row in challenges_list}
    if len(challenges) != len(challenges_list):
        raise ContractError("appraisal compilation challenges must be unique")
    if any(
        challenge["appraisal_set_ref"] != need_set["appraisal_set_ref"]
        for challenge in challenges_list
    ):
        raise ContractError("appraisal compilation appraisal_set_ref mismatch")

    scholar_needs = [
        need for need in need_set["needs"] if need["route"] == "scholar_discovery"
    ]
    routed_needs = [
        need for need in need_set["needs"] if need["route"] != "scholar_discovery"
    ]
    if document.get("routed_needs") != routed_needs:
        raise ContractError(
            "non-scholar appraisal needs must be preserved exactly in routed_needs"
        )
    by_need_id = {need["need_id"]: need for need in scholar_needs}
    observed_need_ids: list[str] = []
    for hypothesis in document["hypotheses"]:
        origin = _validate_appraisal_origin(
            hypothesis.get("appraisal_origin"),
            f"hypothesis {hypothesis.get('hypothesis_id')}.appraisal_origin",
        )
        need_id = origin["need_ref"]["need_id"]
        need = by_need_id.get(need_id)
        if need is None:
            raise ContractError(
                "only scholar_discovery appraisal needs may enter hypothesis selection"
            )
        _validate_need_challenge_binding(need, challenges)
        if origin != _appraisal_origin(need_set, need):
            raise ContractError(
                "appraisal hypothesis origin does not match its exact need"
            )
        if hypothesis.get("next_action") != "scholar_discovery":
            raise ContractError(
                "appraisal hypothesis next_action must be scholar_discovery"
            )
        if hypothesis.get("search_test", {}).get("queries") != _appraisal_queries(need):
            raise ContractError(
                "appraisal hypothesis queries do not match the exact need"
            )
        if hypothesis.get("semantic_label") != need["paper_need"]:
            raise ContractError(
                "appraisal hypothesis paper_need projection was mutated"
            )
        if hypothesis.get("scope_and_time_bounds") != need["target_scope"]:
            raise ContractError(
                "appraisal hypothesis target_scope projection was mutated"
            )
        if hypothesis.get("domain_anchors") != need["domain_anchors"]:
            raise ContractError(
                "appraisal hypothesis domain_anchors projection was mutated"
            )
        if _history_duplicate_matches(need, history_index):
            raise ContractError(
                "appraisal hypothesis repeats SearchHistoryIndex semantics"
            )
        observed_need_ids.append(need_id)
    if observed_need_ids != [need["need_id"] for need in scholar_needs]:
        raise ContractError(
            "appraisal hypotheses must be the complete ordered scholar_discovery projection"
        )
    if network is not None and document.get("network_ref") != network_ref(network):
        raise ContractError("appraisal compilation network_ref mismatch")


def generate_hypotheses_from_probe(
    probe: dict[str, Any], network: dict[str, Any], round_id: str | None = None
) -> dict[str, Any]:
    probe = validate_probe(probe)
    validate_network(network)
    if probe["network_ref"] != network_ref(network):
        raise ContractError("probe network_ref does not match network")
    index = network_reference_index(network)
    hypotheses: list[dict[str, Any]] = []
    selected_signals, generation_summary = _bounded_candidate_signals(
        probe["candidate_signals"], network
    )
    for offset, signal in enumerate(selected_signals):
        signature = signal_hypothesis_signature(signal)
        semantic_label = str(signal.get("semantic_label") or signature).strip()
        hypothesis_id = f"KGH-{offset + 1:03d}"
        tier = str(signal["tier"])
        if tier == "isolate":
            target_kind = "node"
            target_signature = signature
            decision_impact = "low"
            uncertainty = "medium"
        elif tier == "low_confidence":
            target_kind = "relation"
            target_signature = signature
            decision_impact = "medium"
            uncertainty = "high"
        elif tier in {"explicit_high_impact", "explicit"}:
            target_kind = "relation"
            target_signature = signature
            decision_impact = "high" if tier == "explicit_high_impact" else "medium"
            uncertainty = "medium"
        else:
            target_kind = "assumption"
            target_signature = signature
            decision_impact = "medium"
            uncertainty = "medium"

        search_terms, structural_only = _build_semantic_search_spec(signal, network)
        search_terms = _dedupe_terms(search_terms)
        if not search_terms:
            structural_only = True
        if search_terms:
            target_signature = " ".join(_dedupe_terms(search_terms)[:8])
        elif structural_only:
            target_signature = "semantic enrichment required"
        if not target_signature:
            target_signature = "semantic enrichment required"
        criteria_terms = search_terms[:8]

        if signal["kind"] == "explicit_open_gap":
            grounds_ref = signal["refs"][0]
        else:
            grounds_ref = signal["refs"][0]
        grounds = [{"ref_id": grounds_ref, "statement": semantic_label}]
        for ground in grounds:
            validate_hypothesis_reference(ground["ref_id"], index, "hypothesis.grounds")

        hypothesis = {
            "hypothesis_id": hypothesis_id,
            "gap_type": "implicit_candidate",
            "target_kind": target_kind,
            "target_signature": target_signature,
            "scope_and_time_bounds": "snapshot-local explicit contract scope",
            "semantic_label": semantic_label,
            "hypothesis": semantic_label,
            "grounds": grounds,
            "warrant": (
                "This is a deterministic candidate tied to explicit open-structure evidence "
                "from the same snapshot."
            ),
            "backing": [
                {
                    "ref_id": signal["signal_id"],
                    "locator": f"candidate_signal {signal['signal_id']}",
                }
            ],
            "qualifier": "deterministic, bounded, not a novelty claim",
            "defeaters": [
                "alias or existing node captures same meaning",
                "scope mismatch in benchmark definition",
            ],
            "search_test": {
                "queries": [
                    {
                        "objective": "confirm",
                        "query": _build_semantic_search_query(search_terms, "confirm"),
                    },
                    {
                        "objective": "refute",
                        "query": _build_semantic_search_query(search_terms, "refute"),
                    },
                ],
                "route_families": [
                    "openalex",
                    "semantic_scholar",
                    "crossref",
                    "google_scholar",
                ],
                "expected_confirming_observation": (
                    "a primary source with bounded comparison to the same network objects"
                ),
                "expected_disconfirming_observation": "a scope/alias explanation for absence",
                "acceptance_criteria": _semantic_acceptance_criteria(
                    semantic_label, criteria_terms
                ),
                "criteria": {
                    "must": criteria_terms,
                    "should": [],
                    "must_not": [],
                },
                "metadata_filters": {},
                "seeds": {
                    "titles": criteria_terms,
                    "arxiv": [],
                },
            },
            "expected_information_gain": "improves bounded completion reasoning",
            "decision_impact": decision_impact,
            "uncertainty": uncertainty,
            "searchability": "medium",
            "cross_branch_blocking": tier
            in {"explicit_high_impact", "explicit", "unmet_gate"},
            "source_signal_kind": signal["kind"],
            "source_signal_tier": tier,
            "source_priority": signal["source_priority"],
            "dependencies": [],
            "status": "proposed",
            "status_basis": [],
            "novelty_claimed": False,
            "structural_only": structural_only,
            "next_action": "scholar_discovery"
            if not structural_only
            else "structural_only",
        }
        validate_hypothesis_reference(grounds_ref, index, "hypothesis.grounds")
        hypothesis["backing"][0]["ref_id"] = f"network:{network['network_id']}"
        hypotheses.append(hypothesis)

    return {
        "schema": HYPOTHESES_SCHEMA,
        "network_ref": network_ref(network),
        "round_id": round_id or timestamp_now(),
        "generated_at": timestamp_now(),
        "method_families": [
            "competency_coverage",
            "abc_bridge",
            "counterevidence_boundary",
        ],
        "candidate_budget": {
            "max_total": CANDIDATE_SIGNAL_MAX_TOTAL,
            "tier_budgets": dict(CANDIDATE_SIGNAL_TIER_BUDGETS),
            "selection_summary": generation_summary,
        },
        "hypotheses": hypotheses,
    }


def validate_hypotheses(
    value: Any,
    network: dict[str, Any] | None = None,
    *,
    execution_authority_contexts: dict[str, dict[str, Any]] | None = None,
    history_artifact_file_sha256s: list[str] | None = None,
) -> dict[str, Any]:
    document = require_dict(value, "hypotheses")
    if document.get("schema") != HYPOTHESES_SCHEMA:
        raise ContractError(f"hypotheses.schema must equal {HYPOTHESES_SCHEMA}")
    validate_network_ref(document.get("network_ref"), "hypotheses.network_ref", network)
    require_string(document.get("round_id"), "hypotheses.round_id")
    require_timestamp(document.get("generated_at"), "hypotheses.generated_at")
    require_string_list(
        document.get("method_families"), "hypotheses.method_families", True
    )
    index = (
        network_reference_index(validate_network(network))
        if network is not None
        else None
    )

    hypotheses = document.get("hypotheses")
    if not isinstance(hypotheses, list):
        raise ContractError("hypotheses.hypotheses must be a list")
    seen: set[str] = set()
    for index_h, hypothesis in enumerate(hypotheses):
        label = f"hypotheses.hypotheses[{index_h}]"
        item = require_dict(hypothesis, label)
        hypothesis_id = require_string(
            item.get("hypothesis_id"), f"{label}.hypothesis_id"
        )
        if hypothesis_id in seen:
            raise ContractError(f"duplicate hypothesis_id: {hypothesis_id}")
        seen.add(hypothesis_id)
        if item.get("gap_type") != "implicit_candidate":
            raise ContractError(f"{label}.gap_type must equal implicit_candidate")
        if item.get("target_kind") not in TARGET_KINDS:
            raise ContractError(f"{label}.target_kind is invalid")
        for field in (
            "target_signature",
            "scope_and_time_bounds",
            "hypothesis",
            "warrant",
            "qualifier",
            "expected_information_gain",
            "next_action",
        ):
            require_string(item.get(field), f"{label}.{field}")
        grounds = item.get("grounds")
        if not isinstance(grounds, list) or not grounds:
            raise ContractError(f"{label}.grounds must be non-empty")
        for ground_index, ground in enumerate(grounds):
            entry = require_dict(ground, f"{label}.grounds[{ground_index}]")
            ref_id = require_string(
                entry.get("ref_id"), f"{label}.grounds[{ground_index}].ref_id"
            )
            require_string(
                entry.get("statement"), f"{label}.grounds[{ground_index}].statement"
            )
            if index is not None:
                validate_hypothesis_reference(
                    ref_id, index, f"{label}.grounds[{ground_index}].ref_id"
                )

        backing = item.get("backing")
        if not isinstance(backing, list) or not backing:
            raise ContractError(f"{label}.backing must be non-empty")
        for backing_index, basis in enumerate(backing):
            entry = require_dict(basis, f"{label}.backing[{backing_index}]")
            ref_id = require_string(
                entry.get("ref_id"), f"{label}.backing[{backing_index}].ref_id"
            )
            require_string(
                entry.get("locator"), f"{label}.backing[{backing_index}].locator"
            )
            if index is not None:
                validate_hypothesis_reference(
                    ref_id, index, f"{label}.backing[{backing_index}].ref_id"
                )

        require_string_list(item.get("defeaters"), f"{label}.defeaters", True)
        require_string_list(item.get("dependencies"), f"{label}.dependencies")
        if item.get("novelty_claimed") is not False:
            raise ContractError(f"{label}.novelty_claimed must be false")
        structural_only = item.get("structural_only")
        if structural_only is not None and structural_only not in {True, False}:
            raise ContractError(f"{label}.structural_only must be boolean if present")
        source_signal_tier = item.get("source_signal_tier")
        if (
            source_signal_tier is not None
            and source_signal_tier not in CANDIDATE_SIGNAL_TIER_BUDGETS
        ):
            raise ContractError(f"{label}.source_signal_tier is invalid")
        needs_semantic_enrichment = item.get("needs_semantic_enrichment")
        if needs_semantic_enrichment is not None and needs_semantic_enrichment not in {
            True,
            False,
        }:
            raise ContractError(
                f"{label}.needs_semantic_enrichment must be boolean if present"
            )
        skip_semantic_validation = bool(structural_only) or bool(
            needs_semantic_enrichment
        )
        for field in ("decision_impact", "uncertainty", "searchability"):
            if item.get(field) not in LEVELS:
                raise ContractError(f"{label}.{field} is invalid")
        if not isinstance(item.get("cross_branch_blocking"), bool):
            raise ContractError(f"{label}.cross_branch_blocking must be boolean")
        if item.get("status") not in STATUSES:
            raise ContractError(f"{label}.status is invalid")
        if not isinstance(item.get("status_basis"), list):
            raise ContractError(f"{label}.status_basis must be a list")

        search_test = require_dict(item.get("search_test"), f"{label}.search_test")
        queries = search_test.get("queries")
        if not isinstance(queries, list) or not queries:
            raise ContractError(f"{label}.search_test needs at least one query")
        if (not skip_semantic_validation) and len(queries) < 2:
            raise ContractError(f"{label}.search_test needs confirm and refute queries")
        objectives: set[str] = set()
        criteria = require_dict(
            search_test.get("criteria"), f"{label}.search_test.criteria"
        )
        required_terms = criteria.get("must", [])
        for query_index, query in enumerate(queries):
            entry = require_dict(query, f"{label}.search_test.queries[{query_index}]")
            objective = entry.get("objective")
            if objective not in QUERY_OBJECTIVES:
                raise ContractError(f"{label}.search_test query objective is invalid")
            objectives.add(objective)
            query_text = require_string(
                entry.get("query"), f"{label}.search_test.queries[{query_index}].query"
            )
            if not skip_semantic_validation and not _query_has_semantic_content(
                query_text, required_terms=required_terms
            ):
                raise ContractError(
                    f"{label}.search_test query lacks semantic content or contains internal markers"
                )
        if (not skip_semantic_validation) and not {"confirm", "refute"}.issubset(
            objectives
        ):
            raise ContractError(f"{label}.search_test requires confirm and refute")
        routes = require_string_list(
            search_test.get("route_families"),
            f"{label}.search_test.route_families",
            True,
        )
        if len(set(routes)) < 2:
            raise ContractError(f"{label}.search_test needs two route families")
        for field in (
            "expected_confirming_observation",
            "expected_disconfirming_observation",
            "acceptance_criteria",
        ):
            require_string(search_test.get(field), f"{label}.search_test.{field}")

        if item["status"] in {
            "content_found",
            "supported_gap",
            "contested",
            "refuted",
            "already_covered",
        }:
            if not item["status_basis"]:
                raise ContractError(
                    f"{label}.status_basis required for evidence states"
                )
            groups = set()
            has_full_text = False
            for basis_index, basis in enumerate(item["status_basis"]):
                entry = require_dict(basis, f"{label}.status_basis[{basis_index}]")
                require_string(
                    entry.get("hypothesis_id"),
                    f"{label}.status_basis[{basis_index}].hypothesis_id",
                )
                require_string(
                    entry.get("review_request_id"),
                    f"{label}.status_basis[{basis_index}].review_request_id",
                )
                require_string(
                    entry.get("review_request_digest"),
                    f"{label}.status_basis[{basis_index}].review_request_digest",
                )
                if entry.get("claim_support_eligible") not in {True, False}:
                    raise ContractError(
                        f"{label}.status_basis[{basis_index}].claim_support_eligible must be boolean"
                    )
                require_string(
                    entry.get("source_ref"),
                    f"{label}.status_basis[{basis_index}].source_ref",
                )
                require_string(
                    entry.get("locator"), f"{label}.status_basis[{basis_index}].locator"
                )
                read_depth = require_string(
                    entry.get("read_depth"),
                    f"{label}.status_basis[{basis_index}].read_depth",
                )
                if read_depth not in READ_DEPTHS:
                    raise ContractError(
                        f"{label}.status_basis[{basis_index}].read_depth invalid"
                    )
                has_full_text = has_full_text or read_depth == "full_text"
                groups.add(entry.get("independence_group") or entry.get("source_ref"))
            if item["status"] in {"content_found", "supported_gap", "contested"} and (
                item["decision_impact"] == "high"
                and (len(groups) < 2 or not has_full_text)
            ):
                raise ContractError(
                    f"{label} high-impact evidence states need two groups and full text"
                )
    if "appraisal_compilation" in document:
        _validate_appraisal_projection(
            document,
            network,
            execution_authority_contexts=execution_authority_contexts,
            history_artifact_file_sha256s=history_artifact_file_sha256s,
        )
    elif "routed_needs" in document:
        raise ContractError(
            "hypotheses.routed_needs requires a closed appraisal_compilation"
        )
    return document


def priority_components(hypothesis: dict[str, Any]) -> dict[str, int]:
    return {
        "decision_impact": {"high": 8, "medium": 4, "low": 1}[
            hypothesis["decision_impact"]
        ],
        "uncertainty": {"high": 3, "medium": 2, "low": 1}[hypothesis["uncertainty"]],
        "searchability": {"high": 2, "medium": 1, "low": 0}[
            hypothesis["searchability"]
        ],
        "cross_branch_blocking": 3 if hypothesis["cross_branch_blocking"] else 0,
        "signal_tier": {
            "explicit_high_impact": 12,
            "explicit": 6,
            "unmet_gate": 4,
            "single_source": 0,
            "isolate": -4,
            "low_confidence": -2,
            "structural": -2,
        }.get(str(hypothesis.get("source_signal_tier")), 0),
        "declared_priority": {
            "P0": 6,
            "decision_high": 5,
            "legacy_high": 5,
            "P1": 4,
            "legacy_medium": 3,
            "P2": 1,
            "P3": 0,
            "low": 0,
        }.get(str(hypothesis.get("source_priority")), 0),
        "terminal_status_penalty": -100
        if hypothesis["status"] not in ACTIVE_STATUSES
        else 0,
    }


def _is_search_request_candidate(hypothesis: dict[str, Any]) -> bool:
    appraisal_origin = hypothesis.get("appraisal_origin")
    appraisal_route_ok = True
    if appraisal_origin is not None:
        appraisal_route_ok = (
            _validate_appraisal_origin(appraisal_origin, "hypothesis.appraisal_origin")[
                "need_ref"
            ]["route"]
            == "scholar_discovery"
        )
    return (
        hypothesis["status"] in ACTIVE_STATUSES
        and not hypothesis.get("structural_only")
        and not hypothesis.get("needs_semantic_enrichment")
        and appraisal_route_ok
    )


def prioritize(
    value: Any,
    network: dict[str, Any] | None = None,
    *,
    execution_authority_contexts: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    document = validate_hypotheses(
        value,
        network,
        execution_authority_contexts=execution_authority_contexts,
    )
    output = json.loads(json.dumps(document))
    for hypothesis in output["hypotheses"]:
        components = priority_components(hypothesis)
        hypothesis["priority_components"] = components
        hypothesis["priority_score"] = sum(components.values())
    output["hypotheses"].sort(
        key=lambda item: (
            -item["priority_score"],
            CANDIDATE_SIGNAL_TIER_ORDER.index(item["source_signal_tier"])
            if item.get("source_signal_tier") in CANDIDATE_SIGNAL_TIER_ORDER
            else len(CANDIDATE_SIGNAL_TIER_ORDER),
            str(item.get("target_signature") or "").casefold(),
            item["hypothesis_id"],
        )
    )
    output["priority_order"] = [item["hypothesis_id"] for item in output["hypotheses"]]
    selected_ids: list[str] = []
    for hypothesis in output["hypotheses"]:
        if hypothesis["status"] == "proposed" and _is_search_request_candidate(
            hypothesis
        ):
            hypothesis["status"] = "selected"
        if hypothesis["status"] == "selected":
            selected_ids.append(hypothesis["hypothesis_id"])
    output["selection_summary"] = {
        "selected_count": len(selected_ids),
        "selected_hypothesis_ids": selected_ids,
        "unselected_proposed_hypothesis_ids": [
            hypothesis["hypothesis_id"]
            for hypothesis in output["hypotheses"]
            if hypothesis["status"] == "proposed"
        ],
    }
    return output


def optional_list(value: Any) -> list[str]:
    return [] if value is None else require_string_list(value, "optional list")


def validate_scholar_discovery_request(value: Any) -> dict[str, Any]:
    request = require_dict(value, "request")
    if request.get("schema") != REQUEST_SCHEMA:
        raise ContractError(f"request.schema must equal {REQUEST_SCHEMA}")
    request_id = require_string(request.get("request_id"), "request.request_id")
    require_string(request.get("paper_need"), "request.paper_need")
    intent = request.get("intent")
    if intent not in {
        "auto",
        "known_item",
        "topic_set",
        "author",
        "citation_graph",
        "update",
    }:
        raise ContractError("request.intent is invalid")
    if request.get("effort") not in {"fast", "diligent"}:
        raise ContractError("request.effort must be one of fast or diligent")

    criteria = require_dict(request.get("criteria"), "request.criteria")
    for key in ("must", "should", "must_not"):
        require_string_list(criteria.get(key), f"request.criteria.{key}")
    filters = require_dict(request.get("metadata_filters"), "request.metadata_filters")
    years = require_dict(filters.get("years", {}), "request.metadata_filters.years")
    year_from = years.get("from")
    year_to = years.get("to")
    for key, year in (("from", year_from), ("to", year_to)):
        if year is not None and (
            isinstance(year, bool)
            or not isinstance(year, int)
            or year < 1000
            or year > 3000
        ):
            raise ContractError(f"request.metadata_filters.years.{key} is invalid")
    if year_from is not None and year_to is not None and year_from > year_to:
        raise ContractError("request.metadata_filters.years.from exceeds years.to")
    for key in ("authors", "venues", "languages", "work_types"):
        require_string_list(filters.get(key, []), f"request.metadata_filters.{key}")
    if filters.get("open_access") not in {None, True, False}:
        raise ContractError(
            "request.metadata_filters.open_access must be true, false, or null"
        )

    seeds = require_dict(request.get("seeds"), "request.seeds")
    for key in ("doi", "arxiv", "pmid", "openalex", "semantic_scholar", "titles"):
        require_string_list(seeds.get(key, []), f"request.seeds.{key}")

    routes = require_dict(request.get("routes"), "request.routes")
    automatic = require_string_list(routes.get("automatic"), "request.routes.automatic")
    unknown = set(automatic) - AUTOMATIC_PROVIDERS
    if unknown:
        raise ContractError(f"unsupported automatic providers: {sorted(unknown)}")
    if "google_scholar" in automatic:
        raise ContractError("Google Scholar must never be an automatic provider")
    if routes.get("google_scholar") not in {
        "disabled",
        "manual_optional",
        "manual_required",
    }:
        raise ContractError("request.routes.google_scholar must be valid policy")

    budgets = require_dict(request.get("budgets"), "request.budgets")
    for key in ("max_rounds", "max_queries", "max_candidates", "timeout_seconds"):
        value = budgets.get(key)
        if not isinstance(value, int) or value <= 0:
            raise ContractError(f"request.budgets.{key} must be a positive integer")

    query_seeds = request.get("query_seeds")
    if not isinstance(query_seeds, list) or not query_seeds:
        raise ContractError("request.query_seeds must be a non-empty list")
    objectives: set[str] = set()
    for query_index, seed in enumerate(query_seeds):
        query = require_dict(seed, f"request.query_seeds[{query_index}]")
        objective = query.get("objective")
        if objective not in QUERY_OBJECTIVES:
            raise ContractError("request.query_seeds objective is invalid")
        objectives.add(objective)
        require_string(query.get("query"), f"request.query_seeds[{query_index}].query")
    if not {"confirm", "refute"}.issubset(objectives):
        raise ContractError("request.query_seeds must include confirm and refute")

    has_appraisal_origin = "appraisal_origin" in request
    if has_appraisal_origin:
        _validate_appraisal_origin(
            request.get("appraisal_origin"), "request.appraisal_origin"
        )
        if not request_id.startswith(APPRAISAL_REQUEST_ID_PREFIX):
            raise ContractError(
                "request with appraisal_origin must use the ASDR- appraisal request ID"
            )
    elif request_id.startswith(APPRAISAL_REQUEST_ID_PREFIX):
        raise ContractError(
            "request without appraisal_origin must not use the ASDR- appraisal request ID"
        )

    return request


REVIEWED_GAP_SELECTION_SCHEMA = "ReviewedGapSelection/v1"


def validate_reviewed_gap_selection(
    value: Any, prioritized: dict[str, Any]
) -> dict[str, Any]:
    selection = require_dict(value, "reviewed selection")
    expected_fields = {
        "schema",
        "input_ref",
        "network_ref",
        "round_id",
        "selected_hypothesis_ids",
        "review_status",
    }
    if set(selection) != expected_fields:
        raise ContractError(
            f"reviewed selection field set must be exactly {sorted(expected_fields)}"
        )
    if selection.get("schema") != REVIEWED_GAP_SELECTION_SCHEMA:
        raise ContractError(
            f"reviewed selection schema must be {REVIEWED_GAP_SELECTION_SCHEMA}"
        )
    if selection.get("review_status") != "approved":
        raise ContractError("reviewed selection review_status must be approved")

    input_ref = require_dict(selection.get("input_ref"), "reviewed selection.input_ref")
    if set(input_ref) != {"schema", "sha256"}:
        raise ContractError(
            "reviewed selection.input_ref field set must be exactly schema and sha256"
        )
    if input_ref.get("schema") != HYPOTHESES_SCHEMA:
        raise ContractError(
            f"reviewed selection input schema must be {HYPOTHESES_SCHEMA}"
        )
    input_sha256 = require_string(
        input_ref.get("sha256"), "reviewed selection.input_ref.sha256"
    )
    expected_sha256 = sha256_json(prioritized)
    if input_sha256 != expected_sha256:
        raise ContractError("reviewed selection input digest mismatch")
    if selection.get("network_ref") != prioritized.get("network_ref"):
        raise ContractError("reviewed selection network_ref mismatch")
    if selection.get("round_id") != prioritized.get("round_id"):
        raise ContractError("reviewed selection round_id mismatch")

    selected_ids = require_string_list(
        selection.get("selected_hypothesis_ids"),
        "reviewed selection.selected_hypothesis_ids",
    )
    if len(selected_ids) != len(set(selected_ids)):
        raise ContractError("reviewed selection selected_hypothesis_ids must be unique")
    return selection


def validate_unmodified_prioritize_output(
    document: dict[str, Any],
    network: dict[str, Any] | None,
    *,
    execution_authority_contexts: dict[str, dict[str, Any]] | None = None,
) -> None:
    if "reviewed_selection_ref" in document:
        raise ContractError(
            "select input must be a direct prioritize output, not a prior selection output"
        )
    statuses = [hypothesis.get("status") for hypothesis in document["hypotheses"]]
    if any(status not in {"proposed", "selected"} for status in statuses):
        raise ContractError(
            "select input must contain only proposed or selected scheduling statuses"
        )

    unscheduled = copy.deepcopy(document)
    unscheduled.pop("priority_order", None)
    unscheduled.pop("selection_summary", None)
    for hypothesis in unscheduled["hypotheses"]:
        hypothesis["status"] = "proposed"
    expected = prioritize(
        unscheduled,
        network,
        execution_authority_contexts=execution_authority_contexts,
    )

    observed_state = [
        (hypothesis["hypothesis_id"], hypothesis["status"])
        for hypothesis in document["hypotheses"]
    ]
    expected_state = [
        (hypothesis["hypothesis_id"], hypothesis["status"])
        for hypothesis in expected["hypotheses"]
    ]
    if (
        observed_state != expected_state
        or document.get("priority_order") != expected.get("priority_order")
        or document.get("selection_summary") != expected.get("selection_summary")
    ):
        raise ContractError(
            "select input scheduling status was manually changed; "
            "use the unmodified prioritize output"
        )


def select_hypotheses(
    value: Any,
    reviewed_selection: Any,
    network: dict[str, Any] | None = None,
    *,
    execution_authority_contexts: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    document = validate_hypotheses(
        value,
        network,
        execution_authority_contexts=execution_authority_contexts,
    )
    validate_unmodified_prioritize_output(
        document,
        network,
        execution_authority_contexts=execution_authority_contexts,
    )
    selection = validate_reviewed_gap_selection(reviewed_selection, document)
    selected_ids = selection["selected_hypothesis_ids"]
    selected_set = set(selected_ids)

    by_id = {
        hypothesis["hypothesis_id"]: hypothesis for hypothesis in document["hypotheses"]
    }
    unknown_ids = [
        hypothesis_id for hypothesis_id in selected_ids if hypothesis_id not in by_id
    ]
    if unknown_ids:
        raise ContractError(
            f"reviewed selection contains unknown hypothesis IDs: {unknown_ids}"
        )

    ordered_selected_ids = [
        hypothesis_id
        for hypothesis_id in document["priority_order"]
        if hypothesis_id in selected_set
    ]
    if selected_ids != ordered_selected_ids:
        raise ContractError(
            "reviewed selection IDs must preserve deterministic priority order"
        )

    for hypothesis_id in selected_ids:
        hypothesis = by_id[hypothesis_id]
        if hypothesis.get("structural_only"):
            raise ContractError(
                f"reviewed selection cannot select structural hypothesis {hypothesis_id}"
            )
        if hypothesis.get("needs_semantic_enrichment"):
            raise ContractError(
                "reviewed selection cannot select semantically unenriched hypothesis "
                f"{hypothesis_id}"
            )
        if hypothesis.get("status") != "selected":
            raise ContractError(
                f"reviewed selection hypothesis is not search eligible: {hypothesis_id}"
            )

    reviewed_ref = {
        "schema": REVIEWED_GAP_SELECTION_SCHEMA,
        "sha256": sha256_json(selection),
        "input_sha256": selection["input_ref"]["sha256"],
        "selected_hypothesis_ids": list(selected_ids),
        "review_status": "approved",
    }
    output = _apply_reviewed_selection_projection(document, selected_ids, reviewed_ref)
    validate_hypotheses(
        output,
        network,
        execution_authority_contexts=execution_authority_contexts,
    )
    selected_hypotheses_for_emission(output)
    reviewed_selection_ref_for_emission(output, selected_ids, network)
    return output


def _apply_reviewed_selection_projection(
    prioritized: dict[str, Any],
    selected_ids: list[str],
    reviewed_ref: dict[str, Any],
) -> dict[str, Any]:
    selected_set = set(selected_ids)
    output = copy.deepcopy(prioritized)
    for hypothesis in output["hypotheses"]:
        hypothesis_id = hypothesis["hypothesis_id"]
        baseline_status = hypothesis.get("status")
        if baseline_status not in {"proposed", "selected"}:
            raise ContractError(
                "reviewed selection baseline may contain only deterministic "
                "proposed/selected scheduling statuses"
            )
        if hypothesis_id in selected_set:
            if baseline_status != "selected":
                raise ContractError(
                    f"reviewed selection hypothesis is not baseline-eligible: {hypothesis_id}"
                )
            hypothesis["status"] = "selected"
        elif baseline_status == "selected":
            hypothesis["status"] = "proposed"
    output["selection_summary"] = {
        "selected_count": len(selected_ids),
        "selected_hypothesis_ids": [
            hypothesis["hypothesis_id"]
            for hypothesis in output["hypotheses"]
            if hypothesis["status"] == "selected"
        ],
        "unselected_proposed_hypothesis_ids": [
            hypothesis["hypothesis_id"]
            for hypothesis in output["hypotheses"]
            if hypothesis["status"] == "proposed"
        ],
    }
    output["reviewed_selection_ref"] = copy.deepcopy(reviewed_ref)
    return output


def _reconstruct_prioritized_selection_baseline(
    document: dict[str, Any], network: dict[str, Any] | None
) -> dict[str, Any]:
    unscheduled = copy.deepcopy(document)
    unscheduled.pop("reviewed_selection_ref", None)
    unscheduled.pop("priority_order", None)
    unscheduled.pop("selection_summary", None)
    for hypothesis in unscheduled["hypotheses"]:
        status = hypothesis.get("status")
        if status not in {"proposed", "selected"}:
            raise ContractError(
                "reviewed selection projection contains a non-scheduling status; "
                "no_signal, blocked, and other lifecycle states cannot be hidden"
            )
        hypothesis["status"] = "proposed"
    return prioritize(unscheduled, network)


def selected_hypotheses_for_emission(document: dict[str, Any]) -> list[dict[str, Any]]:
    summary = require_dict(
        document.get("selection_summary"), "hypotheses.selection_summary"
    )
    selected_count = summary.get("selected_count")
    if (
        isinstance(selected_count, bool)
        or not isinstance(selected_count, int)
        or selected_count < 0
    ):
        raise ContractError(
            "hypotheses.selection_summary.selected_count must be a non-negative integer"
        )
    selected_ids = require_string_list(
        summary.get("selected_hypothesis_ids"),
        "hypotheses.selection_summary.selected_hypothesis_ids",
    )
    if len(selected_ids) != len(set(selected_ids)):
        raise ContractError(
            "hypotheses.selection_summary.selected_hypothesis_ids must be unique"
        )
    actual_selected = [
        hypothesis
        for hypothesis in document["hypotheses"]
        if hypothesis["status"] == "selected"
    ]
    actual_selected_ids = [
        hypothesis["hypothesis_id"] for hypothesis in actual_selected
    ]
    if selected_count != len(selected_ids):
        raise ContractError(
            "hypotheses.selection_summary.selected_count must equal the selected ID count"
        )
    if selected_ids != actual_selected_ids:
        raise ContractError(
            "hypotheses.selection_summary.selected_hypothesis_ids must exactly match "
            "status=selected hypotheses in document order"
        )

    unselected_ids = require_string_list(
        summary.get("unselected_proposed_hypothesis_ids"),
        "hypotheses.selection_summary.unselected_proposed_hypothesis_ids",
    )
    actual_unselected_ids = [
        hypothesis["hypothesis_id"]
        for hypothesis in document["hypotheses"]
        if hypothesis["status"] == "proposed"
    ]
    if unselected_ids != actual_unselected_ids:
        raise ContractError(
            "hypotheses.selection_summary.unselected_proposed_hypothesis_ids must "
            "exactly match status=proposed hypotheses in document order"
        )

    invalid_selected = [
        hypothesis["hypothesis_id"]
        for hypothesis in actual_selected
        if hypothesis.get("structural_only")
        or hypothesis.get("needs_semantic_enrichment")
    ]
    if invalid_selected:
        raise ContractError(
            "selected hypotheses must be searchable and non-structural; invalid IDs: "
            f"{invalid_selected}"
        )
    return actual_selected


def reviewed_selection_ref_for_emission(
    document: dict[str, Any],
    selected_ids: list[str],
    network: dict[str, Any] | None,
) -> dict[str, Any]:
    ref = require_dict(
        document.get("reviewed_selection_ref"),
        "hypotheses.reviewed_selection_ref",
    )
    expected_fields = {
        "schema",
        "sha256",
        "input_sha256",
        "selected_hypothesis_ids",
        "review_status",
    }
    if set(ref) != expected_fields:
        raise ContractError(
            "hypotheses.reviewed_selection_ref field set must be exactly "
            f"{sorted(expected_fields)}"
        )
    if ref.get("schema") != REVIEWED_GAP_SELECTION_SCHEMA:
        raise ContractError(
            "hypotheses.reviewed_selection_ref schema must be "
            f"{REVIEWED_GAP_SELECTION_SCHEMA}"
        )
    if ref.get("review_status") != "approved":
        raise ContractError(
            "hypotheses.reviewed_selection_ref review_status must be approved"
        )
    for field in ("sha256", "input_sha256"):
        digest = require_string(ref.get(field), f"reviewed_selection_ref.{field}")
        if not SHA256_RE.fullmatch(digest):
            raise ContractError(
                f"hypotheses.reviewed_selection_ref.{field} must be 64 lowercase hex"
            )
    ref_ids = require_string_list(
        ref.get("selected_hypothesis_ids"),
        "hypotheses.reviewed_selection_ref.selected_hypothesis_ids",
    )
    if ref_ids != selected_ids:
        raise ContractError(
            "reviewed selection reference IDs must match selected hypotheses exactly"
        )

    prioritized = _reconstruct_prioritized_selection_baseline(document, network)
    expected_input_sha256 = sha256_json(prioritized)
    if ref["input_sha256"] != expected_input_sha256:
        raise ContractError(
            "reviewed selection reference input digest does not match the reconstructed "
            "prioritize output"
        )
    expected_selection = {
        "schema": REVIEWED_GAP_SELECTION_SCHEMA,
        "input_ref": {
            "schema": HYPOTHESES_SCHEMA,
            "sha256": expected_input_sha256,
        },
        "network_ref": copy.deepcopy(prioritized["network_ref"]),
        "round_id": prioritized["round_id"],
        "selected_hypothesis_ids": list(selected_ids),
        "review_status": "approved",
    }
    if ref["sha256"] != sha256_json(expected_selection):
        raise ContractError(
            "reviewed selection reference digest does not match the reconstructed "
            "ReviewedGapSelection/v1"
        )
    ordered_selected_ids = [
        hypothesis_id
        for hypothesis_id in prioritized["priority_order"]
        if hypothesis_id in set(selected_ids)
    ]
    if selected_ids != ordered_selected_ids:
        raise ContractError(
            "reviewed selection reference IDs do not preserve baseline priority order"
        )
    expected_projection = _apply_reviewed_selection_projection(
        prioritized, selected_ids, ref
    )
    if document != expected_projection:
        observed_ids = [row.get("hypothesis_id") for row in document["hypotheses"]]
        expected_ids = [
            row["hypothesis_id"] for row in expected_projection["hypotheses"]
        ]
        if observed_ids != expected_ids:
            raise ContractError(
                "reviewed selection projection must preserve every baseline hypothesis "
                "ID and deterministic order without deletion or insertion"
            )
        raise ContractError(
            "reviewed selection projection must preserve every baseline field; the only "
            "allowed unselected change is selected-to-proposed scheduling demotion"
        )
    return ref


def validate_request_projection_profile(value: Any) -> dict[str, Any]:
    profile = copy.deepcopy(require_dict(value, "request projection profile"))
    expected = {"schema", "max_rounds", "max_candidates", "timeout_seconds"}
    if set(profile) != expected:
        raise ContractError(
            f"request projection profile field set must be exactly {sorted(expected)}"
        )
    if profile.get("schema") != REQUEST_PROJECTION_PROFILE_SCHEMA:
        raise ContractError(
            "request projection profile.schema must equal "
            f"{REQUEST_PROJECTION_PROFILE_SCHEMA}"
        )
    limits = {
        "max_rounds": (1, 20),
        "max_candidates": (1, 1000),
        "timeout_seconds": (1, 86400),
    }
    for field, (minimum, maximum) in limits.items():
        raw = profile.get(field)
        if type(raw) is not int or not minimum <= raw <= maximum:
            raise ContractError(
                f"request projection profile.{field} must be an integer in "
                f"[{minimum}, {maximum}]"
            )
    return profile


def project_scholar_request(
    hypothesis: dict[str, Any],
    document: dict[str, Any],
    network_ref_value: dict[str, Any],
    google_scholar_policy: str,
    request_profile_value: Any | None = None,
) -> dict[str, Any]:
    request_profile = validate_request_projection_profile(
        request_profile_value
        or {
            "schema": REQUEST_PROJECTION_PROFILE_SCHEMA,
            "max_rounds": 3,
            "max_candidates": 100,
            "timeout_seconds": 900,
        }
    )
    search_test = hypothesis["search_test"]
    criteria = search_test.get("criteria", {})
    filters = search_test.get("metadata_filters", {})
    seeds = search_test.get("seeds", {})
    route_families = list(dict.fromkeys(search_test["route_families"]))
    automatic = [route for route in route_families if route in AUTOMATIC_PROVIDERS]
    if not automatic:
        automatic = ["openalex", "semantic_scholar", "crossref"]
    years = filters.get("years", {}) if isinstance(filters, dict) else {}
    google_scholar_route = (
        google_scholar_policy if "google_scholar" in route_families else "disabled"
    )
    paper_need = _semantic_paper_need(
        hypothesis.get("semantic_label", hypothesis["hypothesis"]),
        optional_list(criteria.get("must")),
        independent_evidence=(
            hypothesis.get("source_signal_kind") == "low_confidence_relation"
        ),
    )
    request = {
        "schema": REQUEST_SCHEMA,
        "request_id": (
            APPRAISAL_REQUEST_ID_PREFIX
            if "appraisal_origin" in hypothesis
            else GENERIC_REQUEST_ID_PREFIX
        )
        + hypothesis["hypothesis_id"],
        "paper_need": paper_need,
        "intent": "topic_set",
        "effort": "diligent" if hypothesis["decision_impact"] == "high" else "fast",
        "criteria": {
            "must": optional_list(criteria.get("must")),
            "should": optional_list(criteria.get("should")),
            "must_not": optional_list(criteria.get("must_not")),
        },
        "metadata_filters": {
            "years": {"from": years.get("from"), "to": years.get("to")},
            "authors": optional_list(filters.get("authors")),
            "venues": optional_list(filters.get("venues")),
            "languages": optional_list(filters.get("languages")),
            "work_types": optional_list(filters.get("work_types")),
            "open_access": filters.get("open_access"),
        },
        "seeds": {
            key: optional_list(seeds.get(key))
            for key in (
                "doi",
                "arxiv",
                "pmid",
                "openalex",
                "semantic_scholar",
                "titles",
            )
        },
        "routes": {
            "automatic": automatic,
            "google_scholar": google_scholar_route,
        },
        "budgets": {
            "max_rounds": request_profile["max_rounds"],
            "max_queries": min(
                30, max(6, len(search_test["queries"]) * len(automatic))
            ),
            "max_candidates": request_profile["max_candidates"],
            "timeout_seconds": request_profile["timeout_seconds"],
        },
        "query_seeds": copy.deepcopy(search_test["queries"]),
        "as_of": document["generated_at"],
        "gap_ref": {
            "gap_id": hypothesis["hypothesis_id"],
            "network_id": network_ref_value["network_id"],
        },
        "gap_hypothesis_id": hypothesis["hypothesis_id"],
    }
    if "appraisal_origin" in hypothesis:
        request["appraisal_origin"] = copy.deepcopy(hypothesis["appraisal_origin"])
    return validate_scholar_discovery_request(request)


def emit_search_requests(
    value: Any,
    network: dict[str, Any] | None = None,
    *,
    google_scholar_policy: str = "manual_optional",
    max_rounds: int = 3,
    max_candidates: int = 100,
    timeout_seconds: int = 900,
    execution_authority_contexts: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    if google_scholar_policy not in {"disabled", "manual_optional", "manual_required"}:
        raise ContractError(
            "google_scholar_policy must be disabled, manual_optional, or manual_required"
        )
    document = validate_hypotheses(
        value,
        network,
        execution_authority_contexts=execution_authority_contexts,
    )
    request_profile = validate_request_projection_profile(
        {
            "schema": REQUEST_PROJECTION_PROFILE_SCHEMA,
            "max_rounds": max_rounds,
            "max_candidates": max_candidates,
            "timeout_seconds": timeout_seconds,
        }
    )
    selected_hypotheses = selected_hypotheses_for_emission(document)
    selected_ids = [row["hypothesis_id"] for row in selected_hypotheses]
    reviewed_selection_ref = reviewed_selection_ref_for_emission(
        document, selected_ids, network
    )
    if not selected_hypotheses:
        raise ContractError(
            "reviewed selection contains zero selected hypotheses; no search request "
            "set may be emitted"
        )
    network_ref_value = document["network_ref"]

    requests: list[dict[str, Any]] = []
    seen_request_ids: set[str] = set()
    for hypothesis in selected_hypotheses:
        request = project_scholar_request(
            hypothesis,
            document,
            network_ref_value,
            google_scholar_policy,
            request_profile,
        )
        request_id = request["request_id"]
        if request_id in seen_request_ids:
            raise ContractError(f"duplicate request_id {request_id}")
        seen_request_ids.add(request_id)
        requests.append(request)

    set_payload: dict[str, Any] = {
        "schema_version": REQUEST_SET_SCHEMA_VERSION,
        "network_id": network_ref_value["network_id"],
        "network_snapshot_sha256": network_ref_value["sha256"],
        "generated_at": document["generated_at"],
        "schema": (
            APPRAISAL_REQUEST_SET_SCHEMA
            if "appraisal_compilation" in document
            else REQUEST_SET_SCHEMA
        ),
        "network_ref": network_ref_value,
        "reviewed_selection_ref": copy.deepcopy(reviewed_selection_ref),
        "selected_hypothesis_ids": selected_ids,
        "selected_hypotheses_sha256": sha256_json(document),
        "selected_hypotheses": copy.deepcopy(document),
        "google_scholar_policy": google_scholar_policy,
        "request_profile": copy.deepcopy(request_profile),
        "requests": requests,
    }
    set_payload["request_set_digest"] = canonical_request_set_digest(set_payload)
    set_payload["request_set_id"] = (
        REQUEST_SET_ID_PREFIX + set_payload["request_set_digest"][:16]
    )
    validate_request_set(
        set_payload,
        execution_authority_contexts=execution_authority_contexts,
    )
    return set_payload


def validate_request_set(
    value: Any,
    *,
    network: dict[str, Any] | None = None,
    execution_authority_contexts: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    document = require_dict(value, "request set")
    if document.get("schema") not in {
        REQUEST_SET_SCHEMA,
        APPRAISAL_REQUEST_SET_SCHEMA,
    }:
        raise ContractError(
            "request set schema must be a supported generic or appraisal schema"
        )
    require_string(document.get("schema_version"), "request set.schema_version")
    if document["schema_version"] != REQUEST_SET_SCHEMA_VERSION:
        raise ContractError("request set.schema_version must be v1")
    require_string(document.get("network_id"), "request set.network_id")
    require_string(document.get("request_set_id"), "request set.request_set_id")
    require_string(document.get("request_set_digest"), "request set.request_set_digest")
    ensure_sha256(document.get("request_set_digest"), "request set.request_set_digest")
    ensure_sha256(
        document.get("network_snapshot_sha256"),
        "request set.network_snapshot_sha256",
    )
    network_ref_value = validate_network_ref(
        document.get("network_ref"), "request set.network_ref"
    )
    if network_ref_value["network_id"] != document["network_id"]:
        raise ContractError(
            "request set network_id does not match request set network_ref"
        )
    if network_ref_value["sha256"] != document["network_snapshot_sha256"]:
        raise ContractError(
            "request set snapshot digest does not match request set network_ref"
        )
    requests = document.get("requests")
    if not isinstance(requests, list):
        raise ContractError("request set.requests must be a list")

    request_ids = set()
    for index_r, request in enumerate(requests):
        request = validate_scholar_discovery_request(request)
        request_id = request["request_id"]
        if request_id in request_ids:
            raise ContractError("request_set duplicate request_id")
        request_ids.add(request_id)

    is_appraisal_set = document.get("schema") == APPRAISAL_REQUEST_SET_SCHEMA
    for request in requests:
        has_appraisal_origin = "appraisal_origin" in request
        if is_appraisal_set and not has_appraisal_origin:
            raise ContractError(
                "appraisal request set requires appraisal_origin on every request"
            )
        if not is_appraisal_set and has_appraisal_origin:
            raise ContractError("generic request set must not contain appraisal_origin")

    projection_fields = {
        "reviewed_selection_ref",
        "selected_hypothesis_ids",
        "selected_hypotheses_sha256",
        "selected_hypotheses",
        "google_scholar_policy",
        "request_profile",
    }
    present_projection_fields = projection_fields.intersection(document)
    origin_profile_present = any(
        isinstance(request, dict) and "appraisal_origin" in request
        for request in requests
    )
    strict_projection_present = bool(
        present_projection_fields
        or origin_profile_present
        or document.get("schema") == APPRAISAL_REQUEST_SET_SCHEMA
    )
    if strict_projection_present and present_projection_fields != projection_fields:
        raise ContractError(
            "reviewed request set must contain the complete selected projection fields"
        )
    if strict_projection_present:
        selected_document = validate_hypotheses(
            copy.deepcopy(document["selected_hypotheses"]),
            network,
            execution_authority_contexts=execution_authority_contexts,
        )
        selected_rows = selected_hypotheses_for_emission(selected_document)
        appraisal_projection = "appraisal_compilation" in selected_document or any(
            "appraisal_origin" in row for row in selected_rows
        )
        if (
            appraisal_projection
            and document.get("schema") != APPRAISAL_REQUEST_SET_SCHEMA
        ):
            raise ContractError(
                "appraisal projection requires AppraisalScholarDiscoveryRequestSet/v1"
            )
        if (
            document.get("schema") == APPRAISAL_REQUEST_SET_SCHEMA
            and not appraisal_projection
        ):
            raise ContractError(
                "appraisal request-set schema requires an appraisal selection projection"
            )
        selected_ids = [row["hypothesis_id"] for row in selected_rows]
        reviewed_ref = reviewed_selection_ref_for_emission(
            selected_document, selected_ids, network
        )
        if document["reviewed_selection_ref"] != reviewed_ref:
            raise ContractError(
                "request set reviewed_selection_ref does not match selected hypotheses"
            )
        if document["selected_hypothesis_ids"] != selected_ids:
            raise ContractError(
                "request set selected_hypothesis_ids must exactly match selected hypotheses"
            )
        selected_digest = ensure_sha256(
            document["selected_hypotheses_sha256"],
            "request set.selected_hypotheses_sha256",
        )
        if selected_digest != sha256_json(selected_document):
            raise ContractError(
                "request set selected_hypotheses_sha256 does not bind selected hypotheses"
            )
        policy = require_string(
            document["google_scholar_policy"],
            "request set.google_scholar_policy",
        )
        if policy not in {"disabled", "manual_optional", "manual_required"}:
            raise ContractError("request set.google_scholar_policy is invalid")
        request_profile = validate_request_projection_profile(
            copy.deepcopy(document["request_profile"])
        )
        if selected_document["network_ref"] != network_ref_value:
            raise ContractError(
                "request set selected hypotheses network_ref does not match request set"
            )
        expected_requests = [
            project_scholar_request(
                row,
                selected_document,
                network_ref_value,
                policy,
                request_profile,
            )
            for row in selected_rows
        ]
        if document["requests"] != expected_requests:
            raise ContractError(
                "request set requests are not the exact owner-replayed selected projection"
            )
    request_set_digest = document["request_set_digest"]
    expected_digest = canonical_request_set_digest(document)
    if request_set_digest != expected_digest:
        raise ContractError(
            "request set.request_set_digest does not match request set content"
        )
    expected_id = REQUEST_SET_ID_PREFIX + request_set_digest[:16]
    if document.get("request_set_id") != expected_id:
        raise ContractError("request set.request_set_id must match request set digest")
    if network is not None:
        if document.get("network_id") != network["network_id"]:
            raise ContractError(
                "request set network_id does not match supplied network"
            )
        if document.get("network_snapshot_sha256") != network_ref(network)["sha256"]:
            raise ContractError("request set snapshot digest mismatch")
        if network_ref_value["snapshot_id"] != network_ref(network)["snapshot_id"]:
            raise ContractError(
                "request set network_ref snapshot_id does not match network"
            )
    return document


def validate_scholar_discovery_result(value: Any) -> dict[str, Any]:
    result = require_dict(value, "result")
    if result.get("schema") != RESULT_SCHEMA:
        raise ContractError(f"result.schema must equal {RESULT_SCHEMA}")
    require_string(result.get("request_id"), "result.request_id")
    require_string(result.get("hypothesis_id"), "result.hypothesis_id")
    ensure_sha256(result.get("request_digest"), "result.request_digest")
    require_timestamp(result.get("as_of"), "result.as_of")
    if result.get("discovery_status") not in DISCOVERY_STATUSES:
        raise ContractError("result.discovery_status is invalid")
    candidates = result.get("ranked_candidates")
    if not isinstance(candidates, list):
        raise ContractError("result.ranked_candidates must be a list")
    for candidate_index, candidate in enumerate(candidates):
        item = require_dict(candidate, f"result.ranked_candidates[{candidate_index}]")
        require_string(
            item.get("candidate_id"),
            f"result.ranked_candidates[{candidate_index}].candidate_id",
        )
        for optional_field in ("url", "doi", "exact_locator"):
            if item.get(optional_field) is not None:
                require_string(
                    item.get(optional_field),
                    f"result.ranked_candidates[{candidate_index}].{optional_field}",
                )
        screening = require_dict(item.get("screening"), "result.screening")
        if screening.get("decision") not in {
            "include",
            "exclude",
            "maybe",
            "unscreened",
        }:
            raise ContractError(
                "result.ranked_candidates[].screening.decision is invalid"
            )
        require_string(
            item.get("access_level"),
            f"result.ranked_candidates[{candidate_index}].access_level",
        )
        has_source_id = item.get("source_id") is not None
        has_source_digest = item.get("source_digest") is not None
        if has_source_id != has_source_digest:
            raise ContractError(
                "result candidate live source identity requires both source_id and source_digest"
            )
        if has_source_id:
            require_string(
                item.get("source_id"),
                f"result.ranked_candidates[{candidate_index}].source_id",
            )
            ensure_sha256(
                item.get("source_digest"),
                f"result.ranked_candidates[{candidate_index}].source_digest",
            )
    provider_failures = result.get("provider_failures")
    if provider_failures is not None and not isinstance(provider_failures, list):
        raise ContractError("result.provider_failures must be a list")
    unresolved_query_ids = result.get("unresolved_query_ids")
    if unresolved_query_ids is not None and (
        not isinstance(unresolved_query_ids, list)
        or not all(
            isinstance(item, str)
            or (isinstance(item, dict) and isinstance(item.get("provider"), str))
            for item in unresolved_query_ids
        )
    ):
        raise ContractError(
            "result.unresolved_query_ids must be a list of strings or provider maps"
        )
    return result


def validate_scholar_discovery_result_set(
    value: Any,
    *,
    request_set: dict[str, Any] | None = None,
    network: dict[str, Any] | None = None,
    execution_authority_contexts: dict[str, dict[str, Any]] | None = None,
    request_set_file_sha256: str | None = None,
) -> dict[str, Any]:
    document = copy.deepcopy(require_dict(value, "result set"))
    schema = document.get("schema")
    if schema not in {RESULT_SET_SCHEMA, RESULT_SET_V2_SCHEMA}:
        raise ContractError(
            "result set schema must equal ScholarDiscoveryResultSet/v1 or "
            "ScholarDiscoveryResultSet/v2"
        )
    if schema == RESULT_SET_V2_SCHEMA:
        if request_set is None or request_set_file_sha256 is None:
            raise ContractError(
                "ScholarDiscoveryResultSet/v2 requires its exact request set and "
                "request-set file SHA-256"
            )
        ref = require_dict(
            document.get("execution_authorization_ref"),
            "result_set.execution_authorization_ref",
        )
        authorization_id = require_string(
            ref.get("authorization_id"),
            "result_set.execution_authorization_ref.authorization_id",
        )
        context = (execution_authority_contexts or {}).get(authorization_id)
        if context is None:
            raise ContractError(
                "ScholarDiscoveryResultSet/v2 requires an external execution "
                "authorization context"
            )
        try:
            document = _scholar_discovery_module().validate_result_set(
                document,
                request_set_value=request_set,
                execution_authority=context.get("authorization"),
                expected_execution_authority_sha256=context.get(
                    "expected_execution_authority_sha256"
                ),
                execution_authority_file_sha256=context.get(
                    "execution_authority_file_sha256"
                ),
                request_set_file_sha256=request_set_file_sha256,
            )
        except ValueError as exc:
            raise ContractError(
                f"ScholarDiscoveryResultSet/v2 owner replay failed: {exc}"
            ) from exc
    request_set_id = require_string(
        document.get("request_set_id"), "result_set.request_set_id"
    )
    request_set_digest = require_string(
        document.get("request_set_digest"), "result_set.request_set_digest"
    )
    ensure_sha256(document.get("request_set_digest"), "result_set.request_set_digest")
    if request_set is not None:
        expected = require_string(
            request_set.get("request_set_id"), "request set.request_set_id"
        )
        if request_set_id != expected:
            raise ContractError("result_set.request_set_id does not match request set")
        expected_digest = require_string(
            request_set.get("request_set_digest"), "request set.request_set_digest"
        )
        if request_set_digest != expected_digest:
            raise ContractError(
                "result_set.request_set_digest does not match request set"
            )
    require_string(document.get("network_id"), "result_set.network_id")
    network_ref_value = validate_network_ref(
        document.get("network_ref"), "result_set.network_ref"
    )
    if network_ref_value["network_id"] != document.get("network_id"):
        raise ContractError(
            "result_set.network_id does not match result_set.network_ref"
        )
    if network_ref_value["sha256"] != document.get("network_snapshot_sha256"):
        raise ContractError(
            "result_set.network_snapshot_sha256 does not match result_set.network_ref"
        )
    ensure_sha256(
        document.get("network_snapshot_sha256"),
        "result_set.network_snapshot_sha256",
    )
    require_timestamp(document.get("generated_at"), "result_set.generated_at")
    if network is not None:
        if document.get("network_id") != network_ref(network)["network_id"]:
            raise ContractError("result_set.network_id does not match supplied network")
        if document.get("network_snapshot_sha256") != network_ref(network)["sha256"]:
            raise ContractError(
                "result_set.network_snapshot_sha256 does not match supplied network"
            )
    results = document.get("results")
    if not isinstance(results, list):
        raise ContractError("result_set.results must be a list")
    normalized_results = [validate_scholar_discovery_result(item) for item in results]
    if request_set is not None:
        request_ids = {
            request["request_id"] for request in request_set.get("requests", [])
        }
        request_by_id = {
            request["request_id"]: request
            for request in request_set.get("requests", [])
        }
        for result in normalized_results:
            if result["request_id"] not in request_ids:
                raise ContractError("result_set includes unknown request_id")
            request = request_by_id[result["request_id"]]
            expected = request_digest(request)
            if result["request_digest"] != expected:
                raise ContractError(
                    f"result.request_digest mismatch for request_id {result['request_id']}"
                )
            if normalize_hypothesis_id(
                result["hypothesis_id"]
            ) != normalize_hypothesis_id(request.get("gap_hypothesis_id", "")):
                raise ContractError(
                    "result.hypothesis_id does not match request gap hypothesis"
                )
    validated = dict(document)
    validated["results"] = normalized_results
    return validated


def normalize_result_set(
    value: Any,
    *,
    request_set: dict[str, Any] | None = None,
    network: dict[str, Any] | None = None,
    execution_authority_contexts: dict[str, dict[str, Any]] | None = None,
    request_set_file_sha256: str | None = None,
) -> list[dict[str, Any]]:
    # Result-set normalizer for consume-results.
    payload = require_dict(value, "result input")
    if payload.get("schema") == RESULT_SCHEMA:
        raise ContractError(
            "consume-results expects ScholarDiscoveryResultSet payloads only"
        )
    if payload.get("schema") not in {RESULT_SET_SCHEMA, RESULT_SET_V2_SCHEMA}:
        raise ContractError(f"unsupported result schema: {payload.get('schema')!r}")
    if payload.get("schema") != RESULT_SET_V2_SCHEMA:
        raise ContractError(
            "consume-results requires ScholarDiscoveryResultSet/v2 with execution "
            "authorization replay; v1 is legacy display-only"
        )
    return validate_scholar_discovery_result_set(
        payload,
        request_set=request_set,
        network=network,
        execution_authority_contexts=execution_authority_contexts,
        request_set_file_sha256=request_set_file_sha256,
    )["results"]


def validate_learn_from_papers_request(value: Any) -> dict[str, Any]:
    request = require_dict(value, "review request")
    if request.get("schema") != LEARN_FROM_PAPERS_REQUEST_SCHEMA:
        raise ContractError(
            f"review request.schema must equal {LEARN_FROM_PAPERS_REQUEST_SCHEMA}"
        )
    require_string(request.get("request_id"), "review request.request_id")
    require_string(request.get("source_request_id"), "review request.source_request_id")
    require_string(request.get("hypothesis_id"), "review request.hypothesis_id")
    validate_epistemic_task(request.get("epistemic_task"))
    sources = request.get("sources")
    if not isinstance(sources, list) or not sources:
        raise ContractError("review request.sources must be a non-empty list")
    for index, source in enumerate(sources):
        entry = require_dict(source, f"review request.sources[{index}]")
        require_string(
            entry.get("source_id"), f"review request.sources[{index}].source_id"
        )
        ensure_sha256(
            entry.get("source_digest"), f"review request.sources[{index}].source_digest"
        )
        require_string(
            entry.get("source_ref"), f"review request.sources[{index}].source_ref"
        )
        require_string(
            entry.get("exact_locator"),
            f"review request.sources[{index}].exact_locator",
        )
        acquisition_locator = require_string(
            entry.get("acquisition_locator"),
            f"review request.sources[{index}].acquisition_locator",
        )
        if acquisition_locator != entry["exact_locator"]:
            raise ContractError(
                f"review request.sources[{index}].acquisition_locator must match exact_locator"
            )
        read_depth = require_string(
            entry.get("read_depth"), f"review request.sources[{index}].read_depth"
        )
        if read_depth not in READ_DEPTHS:
            raise ContractError(f"review request.sources[{index}].read_depth invalid")
        required_read_depth = require_string(
            entry.get("required_read_depth"),
            f"review request.sources[{index}].required_read_depth",
        )
        if required_read_depth not in READ_DEPTHS:
            raise ContractError(
                f"review request.sources[{index}].required_read_depth invalid"
            )
        if required_read_depth != read_depth:
            raise ContractError(
                f"review request.sources[{index}].required_read_depth must match read_depth"
            )
        if entry.get("discovery_only") is not True:
            raise ContractError(
                f"review request.sources[{index}].discovery_only must be true"
            )
        if entry.get("claim_support_eligible") is not False:
            raise ContractError(
                f"review request.sources[{index}].claim_support_eligible must be false"
            )
        if not any((entry.get(field)) for field in ("url", "doi")):
            raise ContractError(
                f"review request.sources[{index}] must include url or doi"
            )
        for field in ("source_artifact_sha256", "source_bundle_digest"):
            if entry.get(field) is not None:
                ensure_sha256(
                    entry.get(field), f"review request.sources[{index}].{field}"
                )
        if entry.get("source_bundle_id") is not None:
            require_string(
                entry.get("source_bundle_id"),
                f"review request.sources[{index}].source_bundle_id",
            )
    return request


def validate_epistemic_task(value: Any) -> dict[str, Any]:
    task = require_dict(value, "review request.epistemic_task")
    expected_keys = {
        "question",
        "hypothesis",
        "target_signature",
        "scope_bounds",
        "scope",
        "defeaters",
        "falsifiers",
        "acceptance_criteria",
        "relation_vocabulary",
        "required_inspection_depth",
    }
    if set(task) != expected_keys:
        raise ContractError(
            "review request.epistemic_task must use the closed v1 field set"
        )
    for field in (
        "question",
        "hypothesis",
        "target_signature",
        "scope_bounds",
        "acceptance_criteria",
    ):
        require_string(task.get(field), f"review request.epistemic_task.{field}")
    require_string_list(
        task.get("defeaters"),
        "review request.epistemic_task.defeaters",
        nonempty=True,
    )
    require_string_list(
        task.get("falsifiers"),
        "review request.epistemic_task.falsifiers",
        nonempty=True,
    )
    vocabulary = require_string_list(
        task.get("relation_vocabulary"),
        "review request.epistemic_task.relation_vocabulary",
        nonempty=True,
    )
    if vocabulary != EPISTEMIC_RELATION_VOCABULARY:
        raise ContractError(
            "review request.epistemic_task.relation_vocabulary must use the canonical order"
        )
    depth = require_dict(
        task.get("required_inspection_depth"),
        "review request.epistemic_task.required_inspection_depth",
    )
    if set(depth) != {"minimum", "claim_bearing_components", "reconstruction"}:
        raise ContractError(
            "review request.epistemic_task.required_inspection_depth has invalid fields"
        )
    if (
        require_string(
            depth.get("minimum"),
            "review request.epistemic_task.required_inspection_depth.minimum",
        )
        != "full_text"
    ):
        raise ContractError(
            "review request.epistemic_task requires full_text inspection"
        )
    components = require_string_list(
        depth.get("claim_bearing_components"),
        "review request.epistemic_task.required_inspection_depth.claim_bearing_components",
        nonempty=True,
    )
    if components != ["figures", "tables", "equations", "appendices", "supplements"]:
        raise ContractError(
            "review request.epistemic_task claim-bearing components must use the canonical order"
        )
    require_string(
        depth.get("reconstruction"),
        "review request.epistemic_task.required_inspection_depth.reconstruction",
    )
    scope = require_dict(task.get("scope"), "review request.epistemic_task.scope")
    if set(scope) != {"assumptions", "conditions", "units", "exclusions"}:
        raise ContractError("review request.epistemic_task.scope field set invalid")
    for field in ("assumptions", "conditions", "units", "exclusions"):
        require_string_list(
            scope.get(field), f"review request.epistemic_task.scope.{field}"
        )
    return task


def _epistemic_task_from_hypothesis(hypothesis: dict[str, Any]) -> dict[str, Any]:
    search_test = require_dict(
        hypothesis.get("search_test"),
        f"hypothesis {hypothesis.get('hypothesis_id', '')}.search_test",
    )
    expected_disconfirming = require_string(
        search_test.get("expected_disconfirming_observation"),
        "hypothesis.search_test.expected_disconfirming_observation",
    )
    task = {
        "question": (
            "Does source-rooted evidence support, qualify, refute, or leave "
            f"untested this hypothesis: {hypothesis['hypothesis']}"
        ),
        "hypothesis": hypothesis["hypothesis"],
        "target_signature": hypothesis["target_signature"],
        "scope_bounds": hypothesis["scope_and_time_bounds"],
        "scope": {
            "assumptions": [],
            "conditions": [hypothesis["scope_and_time_bounds"]],
            "units": [],
            "exclusions": [],
        },
        "defeaters": list(hypothesis["defeaters"]),
        "falsifiers": [expected_disconfirming],
        "acceptance_criteria": search_test["acceptance_criteria"],
        "relation_vocabulary": list(EPISTEMIC_RELATION_VOCABULARY),
        "required_inspection_depth": {
            "minimum": "full_text",
            "claim_bearing_components": [
                "figures",
                "tables",
                "equations",
                "appendices",
                "supplements",
            ],
            "reconstruction": "execute only when required by acceptance criteria",
        },
    }
    return validate_epistemic_task(task)


def validate_learn_from_papers_request_set(
    value: Any,
    *,
    network: dict[str, Any] | None = None,
) -> dict[str, Any]:
    document = require_dict(value, "review request set")
    if document.get("schema") != LEARN_FROM_PAPERS_REQUEST_SET_SCHEMA:
        raise ContractError(
            f"review request set schema must equal {LEARN_FROM_PAPERS_REQUEST_SET_SCHEMA}"
        )
    require_string(document.get("request_set_id"), "review request set.request_set_id")
    require_string(
        document.get("request_set_digest"), "review request set.request_set_digest"
    )
    ensure_sha256(
        document.get("request_set_digest"), "review request set.request_set_digest"
    )
    expected_digest = canonical_request_set_digest(document)
    if document.get("request_set_digest") != expected_digest:
        raise ContractError(
            "review request set.request_set_digest does not match request set content"
        )
    expected_id = LEARN_REQUEST_SET_ID_PREFIX + expected_digest[:16]
    if document.get("request_set_id") != expected_id:
        raise ContractError(
            "review request set.request_set_id must match request set digest"
        )
    require_string(document.get("network_id"), "review request set.network_id")
    validate_network_ref(document.get("network_ref"), "review request set.network_ref")
    ensure_sha256(
        document.get("network_snapshot_sha256"),
        "review request set.network_snapshot_sha256",
    )
    network_ref_value = document.get("network_ref")
    if network_ref_value.get("network_id") != document.get("network_id"):
        raise ContractError(
            "review request set network_id does not match review request set network_ref"
        )
    if network_ref_value.get("sha256") != document.get("network_snapshot_sha256"):
        raise ContractError(
            "review request set snapshot digest does not match review request set network_ref"
        )
    require_timestamp(document.get("generated_at"), "review request set.generated_at")

    requests = document.get("requests")
    if not isinstance(requests, list):
        raise ContractError("review request set.requests must be a list")
    request_ids = set()
    for request in requests:
        item = validate_learn_from_papers_request(request)
        if item["request_id"] in request_ids:
            raise ContractError("review request set duplicate request_id")
        request_ids.add(item["request_id"])

    if network is not None:
        if document.get("network_id") != network_ref(network)["network_id"]:
            raise ContractError(
                "review request set network_id does not match supplied network"
            )
        if document.get("network_snapshot_sha256") != network_ref(network)["sha256"]:
            raise ContractError(
                "review request set network_snapshot_sha256 does not match supplied network"
            )
        if network_ref_value.get("snapshot_id") != network_ref(network)["snapshot_id"]:
            raise ContractError(
                "review request set network_ref snapshot_id does not match supplied network"
            )
    return document


def _is_unacceptable_locator(value: str) -> bool:
    lowered = value.lower()
    return (
        lowered.startswith("http://")
        or lowered.startswith("https://")
        or bool(re.fullmatch(r"10\.[0-9]+/.+", value))
    )


def validate_evidence_passage(
    value: Any, *, report_id: str | None = None
) -> dict[str, Any]:
    passage = require_dict(value, "paper reading report passage")
    if report_id is not None:
        pass_label = f"paper reading report {report_id} passage"
    else:
        pass_label = "paper reading report passage"
    require_string(passage.get("passage_id"), f"{pass_label}.passage_id")
    ensure_sha256(passage.get("passage_digest"), f"{pass_label}.passage_digest")
    locator_type = require_string(
        passage.get("locator_type"), f"{pass_label}.locator_type"
    )
    if locator_type not in LOCATOR_TYPES:
        raise ContractError(f"{pass_label}.locator_type invalid")
    exact_locator = require_string(
        passage.get("exact_locator"), f"{pass_label}.exact_locator"
    )
    if _is_unacceptable_locator(exact_locator):
        raise ContractError(f"{pass_label}.exact_locator must not be DOI/URL")
    require_string(passage.get("claim_summary"), f"{pass_label}.claim_summary")
    require_string(passage.get("evidence_summary"), f"{pass_label}.evidence_summary")
    if _is_unacceptable_locator(passage.get("passage_sha256", "")):
        raise ContractError(f"{pass_label}.passage_sha256 cannot be DOI/URL")
    ensure_sha256(passage.get("passage_sha256"), f"{pass_label}.passage_sha256")

    expected_digest = canonical_evidence_passage_digest(passage)
    if passage.get("passage_digest") != expected_digest:
        raise ContractError(
            f"{pass_label}.passage_digest does not match passage content"
        )
    expected_id = PASSAGE_ID_PREFIX + expected_digest[:16]
    if passage.get("passage_id") != expected_id:
        raise ContractError(f"{pass_label}.passage_id must match passage digest")
    return passage


def validate_paper_reading_report(
    value: Any,
    *,
    network: dict[str, Any] | None = None,
) -> dict[str, Any]:
    report = require_dict(value, "paper reading report")
    if report.get("schema") != PAPER_READING_REPORT_SCHEMA:
        raise ContractError(
            f"paper reading report.schema must equal {PAPER_READING_REPORT_SCHEMA}"
        )
    if report.get("review_request_set_id") is not None:
        require_string(
            report.get("review_request_set_id"),
            "paper reading report.review_request_set_id",
        )
    if report.get("review_request_set_digest") is not None:
        ensure_sha256(
            report.get("review_request_set_digest"),
            "paper reading report.review_request_set_digest",
        )
    require_string(report.get("report_id"), "paper reading report.report_id")
    require_string(report.get("report_digest"), "paper reading report.report_digest")
    ensure_sha256(report.get("report_digest"), "paper reading report.report_digest")
    require_string(
        report.get("review_request_id"), "paper reading report.review_request_id"
    )
    require_string(
        report.get("review_request_digest"),
        "paper reading report.review_request_digest",
    )
    ensure_sha256(
        report.get("review_request_digest"),
        "paper reading report.review_request_digest",
    )
    require_string(report.get("source_id"), "paper reading report.source_id")
    require_string(report.get("source_digest"), "paper reading report.source_digest")
    ensure_sha256(report.get("source_digest"), "paper reading report.source_digest")
    require_string(report.get("source_ref"), "paper reading report.source_ref")
    if report.get("exact_locator") is not None:
        require_string(
            report.get("exact_locator"), "paper reading report.exact_locator"
        )
    read_depth = require_string(
        report.get("read_depth"), "paper reading report.read_depth"
    )
    if read_depth != READING_DEPTH_ONLY_FULL_TEXT:
        raise ContractError("paper reading report.read_depth must be full_text")
    if report.get("producer") is not None and report.get("producer") != READER_PRODUCER:
        raise ContractError("paper reading report.producer must be learn-from-papers")
    if report.get("protocol_version") is not None:
        protocol_version = require_string(
            report.get("protocol_version"), "paper reading report.protocol_version"
        )
        if protocol_version != READING_REPORT_PROTOCOL:
            raise ContractError("paper reading report.protocol_version must be 1.0")
    ensure_sha256(
        report.get("source_artifact_sha256"),
        "paper reading report.source_artifact_sha256",
    )
    if "passages" in report:
        raise ContractError("paper reading report.passages is deprecated")
    passages = report.get("evidence_passages")
    if not isinstance(passages, list) or not passages:
        raise ContractError(
            "paper reading report.evidence_passages must be a non-empty list"
        )
    source_artifact = report.get("source_artifact_sha256")
    for index, passage in enumerate(passages):
        valid_passage = validate_evidence_passage(
            passage, report_id=report.get("report_id", "")
        )
        if source_artifact is None:
            raise ContractError(
                "paper reading report.source_artifact_sha256 is required"
            )
        if source_artifact != report.get("source_artifact_sha256"):
            raise ContractError("paper reading report source_artifact_sha256 mismatch")
        passages[index] = valid_passage

    expected_digest = canonical_reading_report_digest(report)
    if report.get("report_digest") != expected_digest:
        raise ContractError(
            "paper reading report.report_digest does not match report content"
        )
    expected_id = READING_REPORT_ID_PREFIX + expected_digest[:16]
    if report.get("report_id") != expected_id:
        raise ContractError("paper reading report.report_id must match report digest")
    if network is not None:
        if not isinstance(network, dict):
            raise ContractError("network must be an object")
    return report


def validate_paper_reading_report_set(
    value: Any,
    *,
    network: dict[str, Any] | None = None,
) -> dict[str, Any]:
    document = require_dict(value, "paper reading report set")
    if document.get("schema") != PAPER_READING_REPORT_SET_SCHEMA:
        raise ContractError(
            f"paper reading report set schema must equal {PAPER_READING_REPORT_SET_SCHEMA}"
        )
    require_string(
        document.get("schema_version"), "paper reading report set.schema_version"
    )
    if document["schema_version"] != PAPER_READING_REPORT_SET_SCHEMA_VERSION:
        raise ContractError("paper reading report set.schema_version must be v1")
    require_string(
        document.get("review_request_set_id"),
        "paper reading report set.review_request_set_id",
    )
    require_string(
        document.get("review_request_set_digest"),
        "paper reading report set.review_request_set_digest",
    )
    ensure_sha256(
        document.get("review_request_set_digest"),
        "paper reading report set.review_request_set_digest",
    )
    require_string(
        document.get("report_set_id"), "paper reading report set.report_set_id"
    )
    require_string(
        document.get("report_set_digest"), "paper reading report set.report_set_digest"
    )
    ensure_sha256(
        document.get("report_set_digest"), "paper reading report set.report_set_digest"
    )
    if document.get("source_artifact_sha256") is not None:
        ensure_sha256(
            document.get("source_artifact_sha256"),
            "paper reading report set.source_artifact_sha256",
        )
    require_string(document.get("producer"), "paper reading report set.producer")
    if document.get("producer") != READER_PRODUCER:
        raise ContractError(
            "paper reading report set.producer must be learn-from-papers"
        )
    require_string(
        document.get("protocol_version"), "paper reading report set.protocol_version"
    )
    require_timestamp(
        document.get("generated_at"), "paper reading report set.generated_at"
    )
    validate_network_ref(
        document.get("network_ref"), "paper reading report set.network_ref"
    )
    network_ref_value = document.get("network_ref")
    if not isinstance(network_ref_value, dict):
        raise ContractError("paper reading report set.network_ref must be an object")
    if document.get("network_id") is not None and network_ref_value.get(
        "network_id"
    ) != document.get("network_id"):
        raise ContractError(
            "paper reading report set network_id does not match network_ref"
        )
    if document.get("network_snapshot_sha256") is not None and network_ref_value.get(
        "sha256"
    ) != document.get("network_snapshot_sha256"):
        raise ContractError(
            "paper reading report set snapshot digest does not match network_ref"
        )

    reports = document.get("reports")
    if not isinstance(reports, list) or not reports:
        raise ContractError("paper reading report set.reports must be a non-empty list")
    report_ids: set[str] = set()
    for index, report in enumerate(reports):
        valid_report = validate_paper_reading_report(
            report,
            network=network,
        )
        reports[index] = valid_report
        if (
            valid_report.get("review_request_set_id") is not None
            and valid_report["review_request_set_id"]
            != document["review_request_set_id"]
        ):
            raise ContractError(
                "paper reading report set.review_request_set_id mismatch"
            )
        if (
            valid_report.get("review_request_set_digest") is not None
            and valid_report["review_request_set_digest"]
            != document["review_request_set_digest"]
        ):
            raise ContractError(
                "paper reading report set.review_request_set_digest mismatch"
            )
        if document.get("source_artifact_sha256") is not None and valid_report[
            "source_artifact_sha256"
        ] != document.get("source_artifact_sha256"):
            raise ContractError(
                "paper reading report set.source_artifact_sha256 mismatch"
            )
        if valid_report["report_id"] in report_ids:
            raise ContractError("paper reading report set duplicate report_id")
        report_ids.add(valid_report["report_id"])

    expected_digest = canonical_report_set_digest(document)
    if document.get("report_set_digest") != expected_digest:
        raise ContractError("paper reading report set report_set_digest mismatch")
    expected_id = REPORT_SET_ID_PREFIX + expected_digest[:16]
    if document.get("report_set_id") != expected_id:
        raise ContractError("paper reading report set.report_set_id mismatch")

    if network is not None:
        if network_ref_value.get("network_id") != network_ref(network)["network_id"]:
            raise ContractError("paper reading report set network_id mismatch")
        if network_ref_value.get("sha256") != network_ref(network)["sha256"]:
            raise ContractError("paper reading report set snapshot digest mismatch")
    return document


def validate_paper_reading_report_set_v2(
    value: Any,
    *,
    network: dict[str, Any] | None = None,
    verification_root: str | Path | None = None,
    require_finalized: bool = False,
) -> dict[str, Any]:
    document = require_dict(value, "paper reading report set v2")
    if document.get("schema") != PAPER_READING_REPORT_SET_V2_SCHEMA:
        raise ContractError(
            "decisive review requires PaperReadingReportSet/v2; v1 is audit-only"
        )
    module = _reading_dossier_module()
    try:
        validated = module.validate_report_set_v2(
            document,
            verification_root=verification_root,
            require_finalized=require_finalized,
        )
    except module.ContractError as exc:
        raise ContractError(f"invalid PaperReadingReportSet/v2: {exc}") from exc
    if network is not None and validated.get("network_ref") != network_ref(network):
        raise ContractError(
            "paper reading report set v2 network_ref does not match supplied network"
        )
    return validated


def validate_reviewed_evidence(value: Any) -> dict[str, Any]:
    item = require_dict(value, "reviewed evidence")
    if item.get("schema") != REVIEWED_EVIDENCE_SCHEMA:
        raise ContractError(
            f"reviewed evidence.schema must equal {REVIEWED_EVIDENCE_SCHEMA}"
        )
    require_string(item.get("request_set_id"), "reviewed evidence.request_set_id")
    require_string(item.get("reading_report_id"), "reviewed evidence.reading_report_id")
    if not item["reading_report_id"].startswith(READING_REPORT_ID_PREFIX):
        raise ContractError(
            "reviewed evidence.reading_report_id must start with reading-report-"
        )
    require_string(
        item.get("reading_report_digest"), "reviewed evidence.reading_report_digest"
    )
    ensure_sha256(
        item.get("reading_report_digest"), "reviewed evidence.reading_report_digest"
    )
    is_v2 = item["reading_report_id"].startswith(V2_READING_REPORT_ID_PREFIX)
    if is_v2:
        require_string(item.get("evidence_id"), "reviewed evidence.evidence_id")
        require_string(item.get("span_id"), "reviewed evidence.span_id")
        if not item["span_id"].startswith("source-passages-span-"):
            raise ContractError(
                "reviewed evidence.span_id must start with source-passages-span-"
            )
        ensure_sha256(item.get("span_hash"), "reviewed evidence.span_hash")
        require_string(
            item.get("acquisition_locator"),
            "reviewed evidence.acquisition_locator",
        )
        require_string(
            item.get("evidence_locator"), "reviewed evidence.evidence_locator"
        )
        require_string(item.get("relation"), "reviewed evidence.relation")
        if item["relation"] not in V2_RELATION_TO_OUTCOME:
            raise ContractError("reviewed evidence.relation is invalid")
        require_string(
            item.get("source_bundle_id"), "reviewed evidence.source_bundle_id"
        )
        ensure_sha256(
            item.get("source_bundle_digest"),
            "reviewed evidence.source_bundle_digest",
        )
        ensure_sha256(
            item.get("source_artifact_sha256"),
            "reviewed evidence.source_artifact_sha256",
        )
    else:
        require_string(item.get("passage_id"), "reviewed evidence.passage_id")
        if not item["passage_id"].startswith(PASSAGE_ID_PREFIX):
            raise ContractError("reviewed evidence.passage_id must start with passage-")
        require_string(item.get("passage_digest"), "reviewed evidence.passage_digest")
        ensure_sha256(item.get("passage_digest"), "reviewed evidence.passage_digest")
    require_string(item.get("review_request_id"), "reviewed evidence.review_request_id")
    require_string(
        item.get("review_request_digest"), "reviewed evidence.review_request_digest"
    )
    require_string(item.get("source_id"), "reviewed evidence.source_id")
    ensure_sha256(
        item.get("review_request_digest"), "reviewed evidence.review_request_digest"
    )
    ensure_sha256(item.get("source_digest"), "reviewed evidence.source_digest")
    require_string(item.get("request_id"), "reviewed evidence.request_id")
    require_string(item.get("hypothesis_id"), "reviewed evidence.hypothesis_id")
    require_string(item.get("source_ref"), "reviewed evidence.source_ref")
    require_string(item.get("exact_locator"), "reviewed evidence.exact_locator")
    if not any((item.get(field)) for field in ("doi", "url")):
        raise ContractError("reviewed evidence must include doi or url")
    read_depth = require_string(item.get("read_depth"), "reviewed evidence.read_depth")
    if read_depth not in READ_DEPTHS:
        raise ContractError(
            "reviewed evidence.read_depth must be full_text or evidence"
        )
    if item.get("review_completed") is not True:
        raise ContractError("reviewed evidence.review_completed must be true")

    if not isinstance(item.get("claim_support_eligible"), bool):
        raise ContractError("reviewed evidence.claim_support_eligible must be boolean")
    if item.get("discovery_only") is not False:
        raise ContractError("reviewed evidence.discovery_only must be false")
    outcome = item.get("outcome")
    if outcome not in {"supports", "contradicts", "already_covered", "unknown"}:
        raise ContractError(
            "reviewed evidence outcome must be supports, contradicts, already_covered, or unknown"
        )
    return item


def validate_reviewed_evidence_set(
    value: Any,
    *,
    network: dict[str, Any] | None = None,
) -> dict[str, Any]:
    document = require_dict(value, "reviewed evidence set")
    if document.get("schema") != REVIEWED_EVIDENCE_SET_SCHEMA:
        raise ContractError(
            f"reviewed evidence set schema must equal {REVIEWED_EVIDENCE_SET_SCHEMA}"
        )
    require_string(
        document.get("schema_version"), "reviewed evidence set.schema_version"
    )
    require_string(
        document.get("request_set_id"), "reviewed evidence set.request_set_id"
    )
    require_string(
        document.get("request_set_digest"), "reviewed evidence set.request_set_digest"
    )
    ensure_sha256(
        document.get("request_set_digest"), "reviewed evidence set.request_set_digest"
    )
    require_string(
        document.get("evidence_set_digest"), "reviewed evidence set.evidence_set_digest"
    )
    ensure_sha256(
        document.get("evidence_set_digest"), "reviewed evidence set.evidence_set_digest"
    )
    expected_evidence_set_digest = canonical_evidence_set_digest(document)
    if document["evidence_set_digest"] != expected_evidence_set_digest:
        raise ContractError(
            "reviewed evidence set.evidence_set_digest does not match reviewed evidence set content"
        )
    require_string(document.get("network_id"), "reviewed evidence set.network_id")
    validate_network_ref(
        document.get("network_ref"), "reviewed evidence set.network_ref"
    )
    ensure_sha256(
        document.get("network_snapshot_sha256"),
        "reviewed evidence set.network_snapshot_sha256",
    )
    network_ref_value = document.get("network_ref")
    if network_ref_value.get("network_id") != document.get("network_id"):
        raise ContractError(
            "reviewed evidence set network_id does not match reviewed evidence set network_ref"
        )
    if network_ref_value.get("sha256") != document.get("network_snapshot_sha256"):
        raise ContractError(
            "reviewed evidence set snapshot digest does not match reviewed evidence set network_ref"
        )
    require_timestamp(
        document.get("generated_at"), "reviewed evidence set.generated_at"
    )

    evidence_items = document.get("evidence")
    if not isinstance(evidence_items, list):
        raise ContractError("reviewed evidence set.evidence must be a list")
    for item in evidence_items:
        item = validate_reviewed_evidence(item)
        if item["request_set_id"] != document["request_set_id"]:
            raise ContractError(
                "reviewed evidence item request_set_id does not match set"
            )

    if network is not None:
        if document.get("network_id") != network_ref(network)["network_id"]:
            raise ContractError(
                "reviewed evidence set network_id does not match supplied network"
            )
        if document.get("network_snapshot_sha256") != network_ref(network)["sha256"]:
            raise ContractError(
                "reviewed evidence set network_snapshot_sha256 does not match supplied network"
            )
        if network_ref_value.get("snapshot_id") != network_ref(network)["snapshot_id"]:
            raise ContractError(
                "reviewed evidence set network_ref snapshot_id does not match supplied network"
            )
    return document


def _collect_candidate_sources(
    request_id: str,
    candidates: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    def _as_str(value: Any) -> str | None:
        if not isinstance(value, str):
            return None
        value = value.strip()
        return value or None

    def _collect_manifestation_url(candidate: dict[str, Any]) -> str | None:
        manifestations = candidate.get("manifestations")
        if not isinstance(manifestations, list):
            return None
        for item in manifestations:
            if not isinstance(item, dict):
                continue
            url = _as_str(item.get("landing_url"))
            if url:
                return url
        return None

    sources: list[dict[str, Any]] = []
    for index, candidate in enumerate(candidates[:3]):
        exact_locator = _as_str(candidate.get("exact_locator"))
        if exact_locator is None:
            exact_locator = _as_str(candidate.get("doi"))
        doi = _as_str(candidate.get("doi"))
        if doi is None and isinstance(candidate.get("identifiers"), dict):
            identifiers = candidate["identifiers"]
            doi = _as_str(identifiers.get("doi"))
            if doi:
                exact_locator = doi
            else:
                exact_locator = (
                    exact_locator
                    or _as_str(identifiers.get("arxiv"))
                    or _as_str(identifiers.get("pmid"))
                    or _as_str(identifiers.get("openalex"))
                )
        if exact_locator is None:
            exact_locator = _as_str(candidate.get("url"))
        if exact_locator is None:
            exact_locator = _collect_manifestation_url(candidate)
        if not exact_locator:
            continue
        exact_locator_text = str(exact_locator)
        access_level = candidate.get("access_level", "evidence")
        read_depth = access_to_read_depth(access_level)
        source_ref = f"{request_id}-candidate-{index}"
        source_payload: dict[str, Any] = {
            "request_id": request_id,
            "source_ref": source_ref,
            "candidate_id": candidate.get("candidate_id", source_ref),
            "exact_locator": exact_locator_text,
            "acquisition_locator": exact_locator_text,
            "read_depth": read_depth,
            "required_read_depth": read_depth,
            "screening_decision": candidate.get("screening", {}).get("decision"),
            "access_level": access_level,
            "query_seed_position": index,
            "title": candidate.get("title"),
        }
        provided_source_id = candidate.get("source_id")
        provided_source_digest = candidate.get("source_digest")
        if (provided_source_id is None) != (provided_source_digest is None):
            raise ContractError(
                "candidate live source identity requires both source_id and source_digest"
            )
        if provided_source_id is None:
            source_digest = sha256_json(source_payload)
            source_id = SOURCE_ID_PREFIX + source_digest[:16]
        else:
            source_id = require_string(provided_source_id, "candidate.source_id")
            source_digest = ensure_sha256(
                provided_source_digest, "candidate.source_digest"
            )
        item: dict[str, Any] = {
            "source_id": source_id,
            "source_digest": source_digest,
            "source_ref": source_ref,
            "exact_locator": exact_locator_text,
            "acquisition_locator": exact_locator_text,
            "read_depth": read_depth,
            "required_read_depth": read_depth,
            "discovery_only": True,
            "claim_support_eligible": False,
            "query_seed_position": index,
        }
        if candidate.get("doi"):
            item["doi"] = candidate["doi"]
        elif doi:
            item["doi"] = doi
        elif candidate.get("url"):
            item["url"] = candidate["url"]
        elif "://" in exact_locator_text:
            item["url"] = exact_locator_text
        else:
            item["doi"] = exact_locator_text
        manifest_url = _collect_manifestation_url(candidate)
        if manifest_url and "url" not in item:
            item["url"] = manifest_url
        screening_decision = candidate.get("screening", {}).get("decision")
        if screening_decision:
            item["screening_decision"] = screening_decision
        for field in (
            "source_bundle_id",
            "source_bundle_digest",
            "source_artifact_sha256",
        ):
            if candidate.get(field) is not None:
                item[field] = candidate[field]
        item["source_ref"] = source_ref
        sources.append(item)
    return sources


def _result_is_pending(
    result: dict[str, Any],
) -> bool:
    unresolved_query_ids = result.get("unresolved_query_ids") or []
    if unresolved_query_ids:
        return True
    provider_failures = result.get("provider_failures") or []
    if provider_failures:
        return True
    if result.get("discovery_status") in {
        "partial_provider",
        "partial_budget",
        "blocked_capability",
        "pending",
    }:
        return True
    return False


def _result_provider_from_entry(entry: Any) -> str | None:
    if isinstance(entry, dict):
        provider = entry.get("provider")
        return provider.strip() if isinstance(provider, str) else None
    if not isinstance(entry, str):
        return None
    if entry.startswith("provider:"):
        provider = entry.split(":", 1)[1]
        return provider.strip() or None
    if entry.startswith("provider="):
        provider = entry.split("=", 1)[1]
        return provider.strip() or None
    if entry.startswith("google_scholar:"):
        return "google_scholar"
    return None


def _has_provider_marker(value: Any, provider: str) -> bool:
    if not isinstance(value, list):
        return False
    for item in value:
        item_provider = _result_provider_from_entry(item)
        if item_provider and item_provider == provider:
            return True
    return False


def _review_evidence_identity(item: dict[str, Any]) -> tuple[str, str]:
    evidence_digest = sha256_json(item)
    return "EV-" + evidence_digest[:16], evidence_digest


def _derive_reviewed_hypothesis_status(
    evidence_items: list[dict[str, Any]],
) -> tuple[str, list[dict[str, Any]]]:
    supports = [item for item in evidence_items if item["outcome"] == "supports"]
    contradicted = [
        item
        for item in evidence_items
        if item["outcome"] in {"contradicts", "already_covered"}
    ]
    unknown = [item for item in evidence_items if item["outcome"] == "unknown"]

    if supports and contradicted:
        return "contested", supports + contradicted
    if supports:
        status = "content_found"
        if not any(item.get("read_depth") == "full_text" for item in supports):
            status = "supported_gap"
        return status, supports
    if any(item["outcome"] == "already_covered" for item in contradicted):
        return "already_covered", contradicted
    if contradicted:
        return "refuted", contradicted
    if unknown:
        return "unresolved", []
    return "results", []


def _execution_state_entry(
    request_id: str,
    execution_state: str,
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    entry = {
        "source_ref": request_id,
        "locator": "discovery result pending or captured",
        "read_depth": "evidence",
        "execution_state": execution_state,
    }
    if details:
        entry.update(details)
    return entry


def _candidate_matches_domain_anchor(
    candidate: dict[str, Any], anchors: list[str]
) -> bool:
    searchable_parts: list[str] = []
    for field in ("title", "venue", "work_type"):
        value = candidate.get(field)
        if isinstance(value, str) and value.strip():
            searchable_parts.append(value)
    authors = candidate.get("authors")
    if isinstance(authors, list):
        searchable_parts.extend(
            author for author in authors if isinstance(author, str) and author.strip()
        )
    if not searchable_parts:
        return False
    candidate_phrases = [
        _normalized_contiguous_phrase(part, "candidate searchable text")
        for part in searchable_parts
    ]
    return all(
        any(
            _contains_contiguous_phrase(candidate_phrase, anchor_phrase)
            for candidate_phrase in candidate_phrases
        )
        for anchor in anchors
        for anchor_phrase in [
            _normalized_contiguous_phrase(anchor, "candidate domain anchor")
        ]
    )


def consume_results(
    hypotheses_value: Any,
    network: dict[str, Any],
    request_set_value: Any,
    result_values: list[Any],
    *,
    round_id: str | None = None,
    execution_authority_contexts: dict[str, dict[str, Any]] | None = None,
    request_set_file_sha256: str | None = None,
) -> dict[str, Any]:
    hypotheses_doc = validate_hypotheses(
        hypotheses_value,
        network,
        execution_authority_contexts=execution_authority_contexts,
    )
    expected_request_schema = (
        APPRAISAL_REQUEST_SET_SCHEMA
        if "appraisal_compilation" in hypotheses_doc
        else REQUEST_SET_SCHEMA
    )
    raw_request_set = require_dict(request_set_value, "request set")
    if raw_request_set.get("schema") != expected_request_schema:
        raise ContractError(
            "request set schema does not match the generic/appraisal execution route"
        )
    request_set = validate_request_set(
        request_set_value,
        network=network,
        execution_authority_contexts=execution_authority_contexts,
    )
    request_map: dict[str, dict[str, Any]] = {}
    request_by_hypothesis: dict[str, dict[str, Any]] = {}
    for request in request_set["requests"]:
        request_map[request["request_id"]] = request
        hypothesis_id = request.get("gap_hypothesis_id")
        if hypothesis_id in request_by_hypothesis:
            raise ContractError(
                "request set contains multiple requests for one gap hypothesis"
            )
        request_by_hypothesis[hypothesis_id] = request

    request_ids = set(request_map)
    result_map: dict[str, dict[str, Any]] = {}
    for result in result_values:
        parsed = normalize_result_set(
            result,
            request_set=request_set,
            network=network,
            execution_authority_contexts=execution_authority_contexts,
            request_set_file_sha256=request_set_file_sha256,
        )
        for item in parsed:
            request_id = item["request_id"]
            if request_id not in request_ids:
                raise ContractError(
                    f"result.request_id {request_id} not in request set"
                )
            expected = request_digest(request_map[request_id])
            if item["request_digest"] != expected:
                raise ContractError(
                    f"result.request_digest mismatch for request_id {request_id}"
                )
            if normalize_hypothesis_id(
                item["hypothesis_id"]
            ) != normalize_hypothesis_id(
                request_map[request_id].get("gap_hypothesis_id", "")
            ):
                raise ContractError(
                    "result.hypothesis_id does not match request gap hypothesis"
                )
            if request_id in result_map:
                raise ContractError(f"duplicate result for request_id {request_id}")
            result_map[request_id] = item

    previous_cycle = hypotheses_doc.get("cycle_state", {})
    previous_round = previous_cycle.get("discovery_round", 0)
    if not isinstance(previous_round, int):
        previous_round = 0
    previous_no_progress = previous_cycle.get("consecutive_no_progress_rounds", 0)
    if not isinstance(previous_no_progress, int):
        previous_no_progress = 0

    max_rounds = max(
        (
            request.get("budgets", {}).get("max_rounds", 1)
            for request in request_set.get("requests", [])
        ),
        default=1,
    )

    cycle_state: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "round_id": round_id or hypotheses_doc.get("round_id", timestamp_now()),
        "generated_at": timestamp_now(),
        "network_snapshot_sha256": network_ref(network)["sha256"],
        "network_id": network_ref(network)["network_id"],
        "request_set_id": request_set.get("request_set_id"),
        "request_set_digest": request_set.get("request_set_digest"),
        "discovery_round": previous_round + 1 if result_values else previous_round,
        "results_consumed": 0,
        "awaiting_results": 0,
        "status_counts": {status: 0 for status in sorted(STATUSES)},
        "consecutive_no_progress_rounds": previous_no_progress,
        "max_rounds": max_rounds,
        "next_actions": [],
        "phase": "idle",
        "stop_reason": "",
        "pending_reason": "",
        "saturation": False,
    }

    review_requests: list[dict[str, Any]] = []
    updated: list[dict[str, Any]] = []
    has_progress = False
    provider_pending = False
    manual_pending = False

    for hypothesis in hypotheses_doc["hypotheses"]:
        hypothesis = json.loads(json.dumps(hypothesis))
        hypothesis_id = hypothesis["hypothesis_id"]
        request = request_by_hypothesis.get(hypothesis_id)
        request_id = (
            request["request_id"]
            if request is not None
            else (
                APPRAISAL_REQUEST_ID_PREFIX
                if expected_request_schema == APPRAISAL_REQUEST_SET_SCHEMA
                else GENERIC_REQUEST_ID_PREFIX
            )
            + hypothesis_id
        )
        result = result_map.get(request_id)
        previous_status = hypothesis["status"]
        if hypothesis.get("structural_only"):
            hypothesis["next_action"] = "structural_only"
            if previous_status in DISCOVERY_ACTIVE_STATUSES:
                if previous_status != "no_signal":
                    hypothesis["status"] = "no_signal"
                    if previous_status != "no_signal":
                        has_progress = True
                else:
                    hypothesis["status"] = "no_signal"
            hypothesis["status_basis"] = []
            cycle_state["status_counts"][hypothesis["status"]] += 1
            updated.append(hypothesis)
            continue

        if previous_status not in DISCOVERY_ACTIVE_STATUSES:
            cycle_state["status_counts"][previous_status] += 1
            updated.append(hypothesis)
            continue

        if result is None:
            if (
                request
                and request.get("routes", {}).get("google_scholar") == "manual_required"
            ):
                hypothesis["status"] = "awaiting"
                manual_pending = True
                cycle_state["awaiting_results"] += 1
                hypothesis["status_basis"] = [
                    _execution_state_entry(
                        request_id,
                        "pending_execution",
                        {
                            "discovery_status": "manual_capture_required",
                            "google_scholar_route": "manual_required",
                        },
                    )
                ]
                hypothesis["next_action"] = "consume-reviewed-evidence"
            else:
                hypothesis["status"] = "awaiting"
                provider_pending = True
                cycle_state["awaiting_results"] += 1
                hypothesis["status_basis"] = [
                    _execution_state_entry(request_id, "not_executed")
                ]
                hypothesis["next_action"] = "scholar_discovery"
        elif (
            hypothesis.get("appraisal_origin")
            and result.get("ranked_candidates")
            and not all(
                _candidate_matches_domain_anchor(
                    candidate, hypothesis["domain_anchors"]
                )
                for candidate in result["ranked_candidates"]
            )
        ):
            hypothesis["status"] = "unresolved"
            hypothesis["status_basis"] = [
                _execution_state_entry(
                    request_id,
                    "query_precision_failed",
                    {
                        "discovery_status": result["discovery_status"],
                        "domain_anchors": copy.deepcopy(hypothesis["domain_anchors"]),
                        "candidate_count": len(result["ranked_candidates"]),
                    },
                )
            ]
            hypothesis["next_action"] = "scholar_discovery"
            provider_pending = True
        elif _result_is_pending(result):
            ranked_candidates = result.get("ranked_candidates") or []
            has_ranked_candidates = bool(ranked_candidates)
            if has_ranked_candidates:
                sources = _collect_candidate_sources(request_id, ranked_candidates)
                if sources:
                    hypothesis["status"] = "results"
                    hypothesis["status_basis"] = [
                        _execution_state_entry(
                            request_id,
                            "retry_or_route_pending",
                            {
                                "discovery_status": result["discovery_status"],
                            },
                        )
                    ]
                    hypothesis["next_action"] = "learn_from_papers"
                    review_requests.append(
                        {
                            "schema": LEARN_FROM_PAPERS_REQUEST_SCHEMA,
                            "request_id": f"LFR-{request_id}",
                            "source_request_id": request_id,
                            "hypothesis_id": hypothesis_id,
                            "epistemic_task": _epistemic_task_from_hypothesis(
                                hypothesis
                            ),
                            "sources": sources,
                        }
                    )
                    provider_pending = True
                else:
                    has_ranked_candidates = False
            if not has_ranked_candidates:
                is_manual_required = False
                google_scholar_route = request.get("routes", {}).get("google_scholar")
                has_google_scholar_provider = _has_provider_marker(
                    result.get("unresolved_query_ids"),
                    "google_scholar",
                ) or _has_provider_marker(
                    result.get("provider_failures"), "google_scholar"
                )
                if (
                    google_scholar_route == "manual_required"
                    and has_google_scholar_provider
                ):
                    is_manual_required = True
                    manual_pending = True
                hypothesis["status"] = "awaiting"
                status_basis = {
                    "discovery_status": result["discovery_status"],
                }
                if result.get("unresolved_query_ids"):
                    status_basis["unresolved_query_ids"] = result[
                        "unresolved_query_ids"
                    ]
                if result.get("provider_failures"):
                    status_basis["provider_failures"] = result["provider_failures"]
                hypothesis["status_basis"] = [
                    _execution_state_entry(
                        request_id,
                        "retry_or_route_pending",
                        status_basis,
                    )
                ]
                if is_manual_required:
                    if google_scholar_route == "manual_required":
                        hypothesis["status_basis"][0]["google_scholar_route"] = (
                            "manual_required"
                        )
                    hypothesis["next_action"] = "manual_scholar_export"
                else:
                    provider_pending = True
                    hypothesis["next_action"] = "scholar_discovery"
                cycle_state["awaiting_results"] += 1
        elif not result.get("ranked_candidates"):
            if hypothesis.get("appraisal_origin"):
                hypothesis["status"] = "unresolved"
                hypothesis["status_basis"] = [
                    _execution_state_entry(
                        request_id,
                        "bounded_no_candidate_not_novelty",
                        {"discovery_status": result["discovery_status"]},
                    )
                ]
                hypothesis["next_action"] = "scholar_discovery"
            else:
                hypothesis["status"] = "no_signal"
                hypothesis["status_basis"] = []
                hypothesis["next_action"] = "scholar_discovery"
        else:
            sources = _collect_candidate_sources(
                request_id, result.get("ranked_candidates", [])
            )
            if sources:
                hypothesis["status"] = "results"
                hypothesis["status_basis"] = []
                hypothesis["next_action"] = "learn_from_papers"
                review_requests.append(
                    {
                        "schema": LEARN_FROM_PAPERS_REQUEST_SCHEMA,
                        "request_id": f"LFR-{request_id}",
                        "source_request_id": request_id,
                        "hypothesis_id": hypothesis_id,
                        "epistemic_task": _epistemic_task_from_hypothesis(hypothesis),
                        "sources": sources,
                    }
                )
            else:
                hypothesis["status"] = "no_signal"
                hypothesis["status_basis"] = []
                hypothesis["next_action"] = "scholar_discovery"

        if hypothesis["status"] != previous_status:
            has_progress = True

        if hypothesis["status"] in {
            "content_found",
            "supported_gap",
            "contested",
            "refuted",
            "already_covered",
        }:
            validate_hypotheses(
                {**hypotheses_doc, "hypotheses": [hypothesis]},
                execution_authority_contexts=execution_authority_contexts,
            )

        if hypothesis["status"] == "results":
            cycle_state["results_consumed"] += 1

        cycle_state["status_counts"][hypothesis["status"]] += 1
        updated.append(hypothesis)

    awaiting_review = any(
        item["status"] in CANDIDATE_FOR_REVIEW_STATUSES for item in updated
    )
    active = any(item["status"] in DISCOVERY_ACTIVE_STATUSES for item in updated)

    if awaiting_review:
        cycle_state["phase"] = "review_and_retry" if provider_pending else "review"
        cycle_state["next_actions"] = ["consume-reviewed-evidence"]
    elif active:
        cycle_state["phase"] = "discover"
        cycle_state["next_actions"] = ["discover"]
    else:
        cycle_state["phase"] = "idle"
        cycle_state["next_actions"] = []

    if manual_pending:
        cycle_state["stop_reason"] = "manual_required"
    elif awaiting_review:
        cycle_state["stop_reason"] = "review_pending"
    elif provider_pending:
        cycle_state["stop_reason"] = "provider_pending"
    elif active:
        cycle_state["stop_reason"] = "provider_pending"
    else:
        cycle_state["stop_reason"] = "provider_pending"
    if manual_pending:
        cycle_state["pending_reason"] = "manual_required"
    elif awaiting_review:
        cycle_state["pending_reason"] = (
            "provider_pending" if provider_pending else "review_pending"
        )
    elif provider_pending or active:
        cycle_state["pending_reason"] = "provider_pending"
    else:
        cycle_state["pending_reason"] = "provider_pending"

    if result_values:
        if has_progress:
            cycle_state["consecutive_no_progress_rounds"] = 0
        else:
            cycle_state["consecutive_no_progress_rounds"] = previous_no_progress + 1

    budget_exhausted = result_values and cycle_state["discovery_round"] >= max_rounds
    if budget_exhausted:
        cycle_state["stop_reason"] = "budget_exhausted"
    elif manual_pending:
        cycle_state["stop_reason"] = "manual_required"

    terminal_round = (
        result_values
        and not manual_pending
        and not awaiting_review
        and all(item["status"] in SATURATION_TERMINAL_STATUSES for item in updated)
    )

    if (
        result_values
        and not manual_pending
        and not awaiting_review
        and terminal_round
        and cycle_state["consecutive_no_progress_rounds"] >= 2
        and not budget_exhausted
    ):
        cycle_state["saturation"] = True
        cycle_state["stop_reason"] = "saturated"

    review_request_set: dict[str, Any] | None = None
    if review_requests:
        review_request_set = {
            "schema": LEARN_FROM_PAPERS_REQUEST_SET_SCHEMA,
            "schema_version": SCHEMA_VERSION,
            "network_id": network_ref(network)["network_id"],
            "network_snapshot_sha256": network_ref(network)["sha256"],
            "network_ref": network_ref(network),
            "generated_at": timestamp_now(),
            "source_discovery_set_id": request_set.get("request_set_id"),
            "source_discovery_set_digest": request_set.get("request_set_digest"),
            "requests": review_requests,
        }
        review_request_set["request_set_digest"] = canonical_request_set_digest(
            review_request_set
        )
        review_request_set["request_set_id"] = (
            LEARN_REQUEST_SET_ID_PREFIX + review_request_set["request_set_digest"][:16]
        )
        validate_learn_from_papers_request_set(review_request_set, network=network)
        cycle_state["review_request_set_id"] = review_request_set["request_set_id"]
        cycle_state["review_request_set_digest"] = review_request_set[
            "request_set_digest"
        ]

    output = {
        "schema": HYPOTHESES_SCHEMA,
        "network_ref": network_ref(network),
        "round_id": cycle_state["round_id"],
        "generated_at": timestamp_now(),
        "method_families": hypotheses_doc["method_families"],
        "hypotheses": updated,
        "cycle_state": cycle_state,
    }
    if review_request_set is not None:
        output["review_requests"] = review_request_set
    for preserved_field in ("appraisal_compilation", "routed_needs"):
        if preserved_field in hypotheses_doc:
            output[preserved_field] = copy.deepcopy(hypotheses_doc[preserved_field])
    return output


def canonical_report_subject_digest(report: dict[str, Any]) -> str:
    payload = json.loads(json.dumps(report))
    for field in (
        "report_id",
        "report_digest",
        "projection_status",
        "claim_support_eligible",
    ):
        payload.pop(field, None)
    verification = require_dict(payload.get("verification"), "report.verification")
    verification = dict(verification)
    for field in ("artifact_ref", "artifact_sha256", "subject_digest"):
        verification.pop(field, None)
    payload["verification"] = verification
    return sha256_json(payload)


def _pending_report_set_context(report_set: dict[str, Any]) -> dict[str, Any]:
    reports = report_set["reports"]
    context = {
        key: json.loads(json.dumps(value))
        for key, value in report_set.items()
        if key not in {"report_set_id", "report_set_digest", "reports"}
    }
    completion = require_dict(
        context.get("completion_matrix"), "report set attestation completion_matrix"
    )
    claims = require_dict(
        completion.get("claims"), "report set attestation completion_matrix.claims"
    )
    if set(claims) != {"total", "eligible", "non_eligible", "decisive", "terminal"}:
        raise ContractError("report set attestation completion_matrix.claims invalid")
    total = len(reports)
    completion["claims"] = {
        "total": total,
        "eligible": 0,
        "non_eligible": total,
        "decisive": 0,
        "terminal": total,
    }
    return context


def _expected_report_identities(report_set: dict[str, Any]) -> list[dict[str, str]]:
    identities = [
        {
            "claim_id": require_string(report.get("claim_id"), "report claim_id"),
            "hypothesis_id": require_string(
                report.get("hypothesis_id"), "report hypothesis_id"
            ),
            "target_id": require_string(report.get("target_id"), "report target_id"),
            "subject_digest": canonical_report_subject_digest(report),
        }
        for report in report_set["reports"]
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


def _safe_attestation_path(root: str | Path, artifact_ref: str) -> Path:
    root_path = Path(root)
    if root_path.is_symlink() or not root_path.is_dir():
        raise ContractError("verification_root must be a regular non-symlink directory")
    relative = Path(require_string(artifact_ref, "verification.artifact_ref"))
    if relative.is_absolute() or ".." in relative.parts:
        raise ContractError("verification.artifact_ref must be a safe relative path")
    current = root_path
    for part in relative.parts:
        current = current / part
        if current.is_symlink():
            raise ContractError(
                "verification attestation path must not traverse symlinks"
            )
    resolved_root = root_path.resolve()
    resolved = current.resolve()
    if resolved_root not in resolved.parents:
        raise ContractError("verification attestation escapes verification_root")
    if not resolved.is_file() or resolved.is_symlink():
        raise ContractError("verification attestation must be a regular file")
    return resolved


def _validate_attestation(
    report: dict[str, Any],
    *,
    report_set: dict[str, Any],
    verification_root: str | Path,
) -> dict[str, Any]:
    verification = require_dict(report.get("verification"), "report.verification")
    expected_verification_keys = {
        "mode",
        "verifier_id",
        "artifact_ref",
        "artifact_sha256",
        "subject_digest",
    }
    if set(verification) != expected_verification_keys:
        raise ContractError(
            "producer verification contract incomplete: expected mode, verifier_id, "
            "artifact_ref, artifact_sha256, and subject_digest"
        )
    mode = require_string(verification.get("mode"), "report.verification.mode")
    if mode not in {
        "independent_source_check",
        "same_context_diagnostic",
        "expert_review",
    }:
        raise ContractError("report.verification.mode invalid")
    verifier_id = require_string(
        verification.get("verifier_id"), "report.verification.verifier_id"
    )
    artifact_sha256 = ensure_sha256(
        verification.get("artifact_sha256"),
        "report.verification.artifact_sha256",
    )
    subject_digest = ensure_sha256(
        verification.get("subject_digest"), "report.verification.subject_digest"
    )
    expected_subject = canonical_report_subject_digest(report)
    if subject_digest != expected_subject:
        raise ContractError("report.verification.subject_digest mismatch")

    expected_artifact_ref = "verification-attestations/" + artifact_sha256 + ".json"
    if verification["artifact_ref"] != expected_artifact_ref:
        raise ContractError(
            "verification attestation artifact_ref is not the canonical content address"
        )
    artifact_path = _safe_attestation_path(verification_root, expected_artifact_ref)
    raw = artifact_path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != artifact_sha256:
        raise ContractError("verification attestation artifact SHA-256 mismatch")
    try:
        attestation = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ContractError("verification attestation must be UTF-8 JSON") from exc
    expected_bytes = canonical_bytes(attestation) + b"\n"
    if raw != expected_bytes:
        raise ContractError(
            "verification attestation must use canonical JSON plus newline"
        )
    attestation = require_dict(attestation, "verification attestation")
    expected_keys = {
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
    if set(attestation) != expected_keys:
        raise ContractError("verification attestation uses an invalid closed field set")
    if attestation.get("schema") != VERIFIER_ATTESTATION_SCHEMA:
        raise ContractError(
            f"verification attestation.schema must equal {VERIFIER_ATTESTATION_SCHEMA}"
        )
    require_timestamp(attestation.get("created_at"), "attestation.created_at")
    if attestation.get("origin") != "external_verifier":
        raise ContractError("verification attestation origin must be external_verifier")
    if attestation.get("verdict") != "passed":
        raise ContractError("verification attestation verdict must be passed")
    require_string(attestation.get("basis"), "attestation.basis")
    request_ref = require_string(
        attestation.get("request_ref"), "attestation.request_ref"
    )
    request_digest = ensure_sha256(
        attestation.get("request_digest"), "attestation.request_digest"
    )
    expected_request_ref = "verification-requests/" + request_digest + ".json"
    if request_ref != expected_request_ref:
        raise ContractError(
            "verification request artifact_ref is not the canonical content address"
        )
    request_path = _safe_attestation_path(verification_root, expected_request_ref)
    request_raw = request_path.read_bytes()
    if hashlib.sha256(request_raw).hexdigest() != request_digest:
        raise ContractError("verification request artifact SHA-256 mismatch")
    try:
        request = json.loads(request_raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ContractError("verification request must be UTF-8 JSON") from exc
    if request_raw != canonical_bytes(request) + b"\n":
        raise ContractError("verification request must use canonical JSON plus newline")
    request = require_dict(request, "verification request")
    request_keys = {
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
    if set(request) != request_keys:
        raise ContractError("verification request uses an invalid closed field set")
    if request.get("schema") != VERIFICATION_REQUEST_SCHEMA:
        raise ContractError(
            f"verification request.schema must equal {VERIFICATION_REQUEST_SCHEMA}"
        )
    producer_context_id = require_string(
        request.get("producer_context_id"),
        "verification request.producer_context_id",
    )
    verifier_context_id = require_string(
        attestation.get("verifier_context_id"), "attestation.verifier_context_id"
    )
    if verifier_context_id == producer_context_id:
        raise ContractError(
            "verification attestation verifier_context_id must differ from producer_context_id"
        )
    if attestation.get("producer_context_id") != producer_context_id:
        raise ContractError(
            "verification attestation producer_context_id binding mismatch"
        )
    expected_bindings = report["evidence_bindings"]
    expected_set_context = _pending_report_set_context(report_set)
    expected_identities = _expected_report_identities(report_set)
    expected = {
        "subject_digest": subject_digest,
        "claim_id": report["claim_id"],
        "hypothesis_id": report["hypothesis_id"],
        "target_id": report["target_id"],
        "scope_digest": sha256_json(report["scope"]),
        "evidence_bindings": expected_bindings,
        "dossier_id": report["dossier_id"],
        "dossier_digest": report["dossier_digest"],
        "source_bundle_id": report["source_bundle_id"],
        "source_bundle_digest": report["source_bundle_digest"],
        "source_artifact_sha256": report["source_artifact_sha256"],
        "mode": mode,
        "verifier_id": verifier_id,
        "support_candidate_eligible": report["claim_support_eligible"],
        "report_set_context": expected_set_context,
        "expected_report_identities": expected_identities,
    }
    for field, value in expected.items():
        if attestation.get(field) != value:
            raise ContractError(f"verification attestation {field} binding mismatch")
        if request.get(field) != value:
            raise ContractError(f"verification request {field} binding mismatch")
    for field in (
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
    ):
        if attestation.get(field) != request.get(field):
            raise ContractError(
                f"verification request/attestation {field} binding mismatch"
            )

    normalized_verifier = verifier_id.strip().lower().replace("_", "-")
    denied_verifier_markers = {
        "producer-self",
        "generated",
        "auto-generated",
        "learn-from-papers",
        "template",
    }
    if normalized_verifier in denied_verifier_markers or any(
        normalized_verifier.startswith(marker + ":")
        for marker in denied_verifier_markers
    ):
        raise ContractError(
            "obvious producer-generated or self-asserted verifier identity is not independent"
        )
    return {
        "mode": mode,
        "verifier_id": verifier_id,
        "artifact_ref": verification["artifact_ref"],
        "artifact_sha256": artifact_sha256,
        "subject_digest": subject_digest,
        "origin": attestation["origin"],
        "verdict": attestation["verdict"],
        "request_ref": request_ref,
        "request_digest": request_digest,
        "producer_context_id": producer_context_id,
        "verifier_context_id": verifier_context_id,
        "created_at": attestation["created_at"],
    }


def _verify_reading_artifacts(
    report_set_value: Any,
    dossier_value: Any,
    *,
    source_bundle_path: str | Path,
    source_artifact_path: str | Path,
    verification_root: str | Path,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    module = _reading_dossier_module()
    report_set = validate_paper_reading_report_set_v2(
        report_set_value,
        verification_root=verification_root,
        require_finalized=True,
    )
    dossier = require_dict(dossier_value, "paper reading dossier")
    try:
        verified_bundle = module.verify_bundle(
            bundle=str(source_bundle_path), source=str(source_artifact_path)
        )
        validated_dossier = module.validate_dossier(
            dossier,
            bundle=str(source_bundle_path),
            source=str(source_artifact_path),
        )
        projected = module.project_report_set(
            validated_dossier,
            bundle=str(source_bundle_path),
            source=str(source_artifact_path),
        )
    except (module.ContractError, module.SourceBundleContractError) as exc:
        raise ContractError(f"reading artifact verification failed: {exc}") from exc
    projected_top = _pending_report_set_context(projected)
    supplied_top = _pending_report_set_context(report_set)
    if projected_top != supplied_top:
        raise ContractError(
            "reading report set metadata must equal strict dossier projection"
        )
    projected_reports = {report["claim_id"]: report for report in projected["reports"]}
    supplied_reports = {report["claim_id"]: report for report in report_set["reports"]}
    if set(projected_reports) != set(supplied_reports):
        raise ContractError(
            "reading report claims must equal strict dossier projection"
        )
    for claim_id, supplied_report in supplied_reports.items():
        if canonical_report_subject_digest(
            supplied_report
        ) != canonical_report_subject_digest(projected_reports[claim_id]):
            raise ContractError(
                "reading report subject must equal strict dossier projection"
            )
    if verified_bundle["bundle_id"] != report_set["source_bundle_id"]:
        raise ContractError("verified source bundle id mismatch")
    if verified_bundle["bundle_digest"] != report_set["source_bundle_digest"]:
        raise ContractError("verified source bundle digest mismatch")
    if (
        verified_bundle["source"]["source_sha256"]
        != report_set["source_artifact_sha256"]
    ):
        raise ContractError("verified source artifact SHA-256 mismatch")
    return report_set, validated_dossier, verified_bundle


def _derive_review_records(
    network: dict[str, Any],
    review_requests_value: Any,
    report_set_value: Any,
    dossier_value: Any,
    *,
    source_bundle_path: str | Path,
    source_artifact_path: str | Path,
    verification_root: str | Path,
) -> tuple[
    dict[str, Any],
    dict[str, Any],
    dict[str, Any],
    dict[str, Any],
    list[dict[str, Any]],
]:
    review_requests = validate_learn_from_papers_request_set(
        review_requests_value, network=network
    )
    report_set, dossier, verified_bundle = _verify_reading_artifacts(
        report_set_value,
        dossier_value,
        source_bundle_path=source_bundle_path,
        source_artifact_path=source_artifact_path,
        verification_root=verification_root,
    )
    if report_set["network_ref"] != network_ref(network):
        raise ContractError("reading report set network_ref mismatch")
    if report_set["review_request_set_id"] != review_requests["request_set_id"]:
        raise ContractError("reading report set request id mismatch")
    if report_set["review_request_set_digest"] != review_requests["request_set_digest"]:
        raise ContractError("reading report set request digest mismatch")

    request_lookup = {
        request["request_id"]: request for request in review_requests["requests"]
    }
    request_digests = {
        request_id: sha256_json(request)
        for request_id, request in request_lookup.items()
    }
    source_lookup: dict[tuple[str, str], dict[str, Any]] = {}
    for request_id, request in request_lookup.items():
        for source in request["sources"]:
            source_lookup[(request_id, source["source_id"])] = source
    claims = {claim["claim_id"]: claim for claim in dossier["claims"]}
    evidence_records = {
        evidence["evidence_id"]: evidence for evidence in dossier["evidence_records"]
    }
    live_source_ids = _live_source_ids(network)

    records: list[dict[str, Any]] = []
    for report in report_set["reports"]:
        request_id = report["review_request_id"]
        request = request_lookup.get(request_id)
        if request is None:
            raise ContractError("reading report references unknown review request")
        if report["review_request_digest"] != request_digests[request_id]:
            raise ContractError("reading report request digest mismatch")
        if report["hypothesis_id"] != request["hypothesis_id"]:
            raise ContractError("reading report hypothesis mismatch")
        if report["target_id"] != request["epistemic_task"]["target_signature"]:
            raise ContractError("reading report target mismatch")
        if report["scope"] != request["epistemic_task"]["scope"]:
            scope_match = False
        else:
            scope_match = True
        review_source = report_set["review_source"]
        source = source_lookup.get((request_id, review_source["source_id"]))
        if source is None:
            raise ContractError("reading report review_source id mismatch")
        if review_source["source_digest"] != source["source_digest"]:
            raise ContractError("reading report review_source digest mismatch")
        if review_source["acquisition_locator"] != source["acquisition_locator"]:
            raise ContractError("reading report acquisition locator mismatch")
        source_onboarded = source["source_id"] in live_source_ids
        claim = claims.get(report["claim_id"])
        if claim is None:
            raise ContractError("reading report claim missing from verified dossier")
        if report["claim_statement"] != claim["statement"]:
            raise ContractError("reading report claim statement mismatch")
        attestation = _validate_attestation(
            report,
            report_set=report_set,
            verification_root=verification_root,
        )

        bindings = report["evidence_bindings"]
        if not bindings:
            records.append(
                {
                    "report": report,
                    "request": request,
                    "source": source,
                    "claim": claim,
                    "evidence": None,
                    "binding": None,
                    "verification": attestation,
                    "scope_match": scope_match,
                    "onboarding_required": not source_onboarded,
                    "patch_eligible": False,
                    "derived_outcome": "unknown",
                }
            )
            continue
        for binding in bindings:
            evidence = evidence_records.get(binding["evidence_id"])
            if evidence is None:
                raise ContractError(
                    "reading report evidence missing from verified dossier"
                )
            if evidence["span_id"] != binding["span_id"]:
                raise ContractError("verified evidence span_id mismatch")
            if evidence["span_hash"] != binding["span_hash"]:
                raise ContractError("verified evidence span_hash mismatch")
            if evidence["exact_locator"] != binding["exact_locator"]:
                raise ContractError("verified evidence locator mismatch")
            mode_ok = attestation["mode"] in {
                "independent_source_check",
                "expert_review",
            }
            depth_ok = report["inspection_depth"] in {"evidence", "reconstruction"}
            patch_eligible = all(
                (
                    report["relation"] == "supports",
                    report["access_level"] == "full_text",
                    depth_ok,
                    scope_match,
                    report["claim_support_eligible"] is True,
                    report["projection_status"] == "decisive",
                    report["verifier_status"] == "passed",
                    mode_ok,
                    source_onboarded,
                )
            )
            if patch_eligible:
                derived_outcome = "supports"
            elif (
                report["relation"] == "refutes"
                and report["access_level"] == "full_text"
                and depth_ok
                and scope_match
                and report["projection_status"] == "decisive"
                and report["verifier_status"] == "passed"
                and mode_ok
                and source_onboarded
            ):
                derived_outcome = "contradicts"
            else:
                derived_outcome = "unknown"
            records.append(
                {
                    "report": report,
                    "request": request,
                    "source": source,
                    "claim": claim,
                    "evidence": evidence,
                    "binding": binding,
                    "verification": attestation,
                    "scope_match": scope_match,
                    "onboarding_required": not source_onboarded,
                    "patch_eligible": patch_eligible,
                    "derived_outcome": derived_outcome,
                }
            )
    return review_requests, report_set, dossier, verified_bundle, records


def _review_derivation_digest(
    review_requests: dict[str, Any],
    report_set: dict[str, Any],
    dossier: dict[str, Any],
    verified_bundle: dict[str, Any],
    records: list[dict[str, Any]],
) -> str:
    return sha256_json(
        {
            "review_request_set_digest": review_requests["request_set_digest"],
            "report_set_digest": report_set["report_set_digest"],
            "dossier_digest": dossier["dossier_digest"],
            "source_bundle_digest": verified_bundle["bundle_digest"],
            "attestations": sorted(
                record["verification"]["artifact_sha256"] for record in records
            ),
        }
    )


def _status_basis_from_record(record: dict[str, Any]) -> dict[str, Any]:
    report = record["report"]
    source = record["source"]
    binding = record["binding"]
    evidence = record["evidence"]
    if binding is None or evidence is None:
        raise ContractError("decisive status basis requires evidence binding")
    return {
        "hypothesis_id": report["hypothesis_id"],
        "source_ref": source["source_ref"],
        "source_id": source["source_id"],
        "source_digest": source["source_digest"],
        "acquisition_locator": source["acquisition_locator"],
        "locator": binding["exact_locator"],
        "evidence_locator": binding["exact_locator"],
        "read_depth": report["access_level"],
        "review_request_id": report["review_request_id"],
        "review_request_digest": report["review_request_digest"],
        "report_set_id": record["report_set_id"],
        "report_set_digest": record["report_set_digest"],
        "dossier_id": report["dossier_id"],
        "dossier_digest": report["dossier_digest"],
        "reading_report_id": report["report_id"],
        "reading_report_digest": report["report_digest"],
        "claim_id": report["claim_id"],
        "claim_digest": sha256_json(record["claim"]),
        "evidence_id": binding["evidence_id"],
        "evidence_digest": sha256_json(evidence),
        "span_id": binding["span_id"],
        "span_hash": binding["span_hash"],
        "source_bundle_id": report["source_bundle_id"],
        "source_bundle_digest": report["source_bundle_digest"],
        "source_artifact_sha256": report["source_artifact_sha256"],
        "relation": report["relation"],
        "outcome": record["derived_outcome"],
        "projection_status": report["projection_status"],
        "claim_support_eligible": report["claim_support_eligible"],
        "scope_match": record["scope_match"],
        "verification": {
            "mode": record["verification"]["mode"],
            "verifier_id": record["verification"]["verifier_id"],
            "artifact_sha256": record["verification"]["artifact_sha256"],
        },
    }


def consume_reviewed_evidence(
    hypotheses_value: Any,
    network: dict[str, Any],
    review_requests_value: Any,
    reading_reports_value: Any,
    dossier_value: Any,
    *,
    source_bundle_path: str | Path,
    source_artifact_path: str | Path,
    verification_root: str | Path,
    round_id: str | None = None,
    execution_authority_contexts: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    hypotheses_doc = validate_hypotheses(
        hypotheses_value,
        network,
        execution_authority_contexts=execution_authority_contexts,
    )
    (
        review_requests,
        report_set,
        dossier,
        verified_bundle,
        records,
    ) = _derive_review_records(
        network,
        review_requests_value,
        reading_reports_value,
        dossier_value,
        source_bundle_path=source_bundle_path,
        source_artifact_path=source_artifact_path,
        verification_root=verification_root,
    )
    previous_cycle = hypotheses_doc.get("cycle_state", {})
    for field, actual in (
        ("review_request_set_id", review_requests["request_set_id"]),
        ("review_request_set_digest", review_requests["request_set_digest"]),
        ("report_set_id", report_set["report_set_id"]),
        ("report_set_digest", report_set["report_set_digest"]),
    ):
        expected = previous_cycle.get(field)
        if expected is not None and expected != actual:
            raise ContractError(f"{field} does not match active discovery cycle")

    derivation_digest = _review_derivation_digest(
        review_requests, report_set, dossier, verified_bundle, records
    )
    derivation_id = "review-derivation-" + derivation_digest[:16]
    records_by_hypothesis: dict[str, list[dict[str, Any]]] = {}
    for record in records:
        record["report_set_id"] = report_set["report_set_id"]
        record["report_set_digest"] = report_set["report_set_digest"]
        records_by_hypothesis.setdefault(record["report"]["hypothesis_id"], []).append(
            record
        )

    previous_round = previous_cycle.get("discovery_round", 0)
    previous_round = previous_round if isinstance(previous_round, int) else 0
    max_rounds = previous_cycle.get("max_rounds", 1)
    max_rounds = max_rounds if isinstance(max_rounds, int) else 1
    updated = []
    status_counts = {status: 0 for status in sorted(STATUSES)}
    consumed = 0
    for original in hypotheses_doc["hypotheses"]:
        hypothesis = json.loads(json.dumps(original))
        if hypothesis["status"] != "results":
            status_counts[hypothesis["status"]] += 1
            updated.append(hypothesis)
            continue
        relevant = records_by_hypothesis.get(hypothesis["hypothesis_id"], [])
        supports = [r for r in relevant if r["derived_outcome"] == "supports"]
        refutes = [r for r in relevant if r["derived_outcome"] == "contradicts"]
        onboarding = [r for r in relevant if r["onboarding_required"]]
        if supports and refutes:
            hypothesis["status"] = "contested"
            basis_records = supports + refutes
        elif supports:
            hypothesis["status"] = "content_found"
            basis_records = supports
        elif refutes:
            hypothesis["status"] = "refuted"
            basis_records = refutes
        elif onboarding:
            hypothesis["status"] = "blocked"
            basis_records = [
                record
                for record in onboarding
                if record["binding"] is not None and record["evidence"] is not None
            ]
        elif relevant:
            hypothesis["status"] = "unresolved"
            basis_records = []
        else:
            basis_records = []
        hypothesis["status_basis"] = [
            _status_basis_from_record(record) for record in basis_records
        ]
        hypothesis["next_action"] = (
            "onboarding_required"
            if hypothesis["status"] == "blocked" and onboarding
            else "discover"
        )
        if basis_records and hypothesis["status"] != "blocked":
            consumed += 1
        status_counts[hypothesis["status"]] += 1
        updated.append(hypothesis)

    blocked_hypothesis_ids = {
        hypothesis["hypothesis_id"]
        for hypothesis in updated
        if hypothesis["status"] == "blocked"
        and hypothesis["next_action"] == "onboarding_required"
    }
    onboarding_source_ids = sorted(
        {
            record["source"]["source_id"]
            for record in records
            if record["onboarding_required"]
            and record["report"]["hypothesis_id"] in blocked_hypothesis_ids
        }
    )
    onboarding_terminal = bool(onboarding_source_ids)
    cycle_state = {
        "schema_version": SCHEMA_VERSION,
        "round_id": round_id or hypotheses_doc.get("round_id", timestamp_now()),
        "generated_at": timestamp_now(),
        "network_snapshot_sha256": network_ref(network)["sha256"],
        "network_id": network_ref(network)["network_id"],
        "discovery_round": previous_round + (1 if records else 0),
        "results_consumed": consumed,
        "awaiting_results": sum(item["status"] == "results" for item in updated),
        "status_counts": status_counts,
        "consecutive_no_progress_rounds": 0 if consumed else 1,
        "max_rounds": max_rounds,
        "phase": "onboarding" if onboarding_terminal else "discover",
        "next_actions": ["onboarding_required"]
        if onboarding_terminal
        else ["discover"],
        "stop_reason": "onboarding_required"
        if onboarding_terminal
        else "provider_pending",
        "pending_reason": (
            "onboarding_required:" + ",".join(onboarding_source_ids)
            if onboarding_terminal
            else "provider_pending"
        ),
        "saturation": False,
        "review_request_set_id": review_requests["request_set_id"],
        "review_request_set_digest": review_requests["request_set_digest"],
        "report_set_id": report_set["report_set_id"],
        "report_set_digest": report_set["report_set_digest"],
        "dossier_id": dossier["dossier_id"],
        "dossier_digest": dossier["dossier_digest"],
        "source_bundle_id": verified_bundle["bundle_id"],
        "source_bundle_digest": verified_bundle["bundle_digest"],
        "review_derivation_id": derivation_id,
        "review_derivation_digest": derivation_digest,
        "request_set_id": previous_cycle.get(
            "request_set_id", review_requests["request_set_id"]
        ),
        "request_set_digest": previous_cycle.get(
            "request_set_digest", review_requests["request_set_digest"]
        ),
    }
    return {
        "schema": HYPOTHESES_SCHEMA,
        "network_ref": network_ref(network),
        "round_id": cycle_state["round_id"],
        "generated_at": timestamp_now(),
        "method_families": hypotheses_doc["method_families"],
        "hypotheses": updated,
        "cycle_state": cycle_state,
    }


def _basis_row(record: dict[str, Any]) -> dict[str, Any]:
    report = record["report"]
    binding = record["binding"]
    evidence = record["evidence"]
    source = record["source"]
    if not record["patch_eligible"] or binding is None or evidence is None:
        raise ContractError("NetworkPatchProposal/v2 basis is not patch eligible")
    row = {
        "basis_id": "",
        "basis_digest": "",
        "review_request_id": report["review_request_id"],
        "review_request_digest": report["review_request_digest"],
        "report_set_id": record["report_set_id"],
        "report_set_digest": record["report_set_digest"],
        "dossier_id": report["dossier_id"],
        "dossier_digest": report["dossier_digest"],
        "reading_report_id": report["report_id"],
        "reading_report_digest": report["report_digest"],
        "source_bundle_id": report["source_bundle_id"],
        "source_bundle_digest": report["source_bundle_digest"],
        "source_artifact_sha256": report["source_artifact_sha256"],
        "source_id": source["source_id"],
        "source_digest": source["source_digest"],
        "claim_id": report["claim_id"],
        "claim_digest": sha256_json(record["claim"]),
        "evidence_id": binding["evidence_id"],
        "evidence_digest": sha256_json(evidence),
        "span_id": binding["span_id"],
        "span_hash": binding["span_hash"],
        "source_ref": report["source_ref"],
        "acquisition_locator": source["acquisition_locator"],
        "evidence_locator": binding["exact_locator"],
        "relation": report["relation"],
        "access_level": report["access_level"],
        "inspection_depth": report["inspection_depth"],
        "claim_support_eligible": report["claim_support_eligible"],
        "projection_status": report["projection_status"],
        "verification": {
            "mode": record["verification"]["mode"],
            "verifier_id": record["verification"]["verifier_id"],
            "artifact_sha256": record["verification"]["artifact_sha256"],
        },
    }
    row["basis_digest"] = sha256_json(
        {
            key: value
            for key, value in row.items()
            if key not in {"basis_id", "basis_digest"}
        }
    )
    row["basis_id"] = "network-patch-basis-" + row["basis_digest"][:16]
    return row


def _patch_action_apply_eligible(
    target_kind: str,
    target_signature: dict[str, str],
    reviewed_evidence: list[dict[str, Any]],
) -> bool:
    """Return whether the closed target is safe for RKN materialization."""
    if target_kind == "relation":
        return True
    if target_kind == "evidence":
        return (
            len(reviewed_evidence) == 1
            and target_signature["signature"] == reviewed_evidence[0]["evidence_id"]
        )
    return False


def _patch_action_status(
    target_kind: str,
    target_signature: dict[str, str],
    reviewed_evidence: list[dict[str, Any]],
) -> str:
    if _patch_action_apply_eligible(
        target_kind,
        target_signature,
        reviewed_evidence,
    ):
        return "proposed"
    return "blocked"


def _target_claim_from_record(
    hypothesis: dict[str, Any],
    record: dict[str, Any],
    basis: dict[str, Any],
    target_signature: dict[str, str],
) -> dict[str, Any]:
    report = record["report"]
    request = record["request"]
    task = require_dict(request.get("epistemic_task"), "target claim epistemic task")
    request_scope = require_dict(task.get("scope"), "target claim request scope")
    if report["scope"] != request_scope:
        raise ContractError("target claim requires exact request/final-report scope")
    assumptions = require_string_list(
        request_scope.get("assumptions"), "target claim scope assumptions"
    )
    conditions = require_string_list(
        request_scope.get("conditions"), "target claim scope conditions"
    )
    units = require_string_list(request_scope.get("units"), "target claim scope units")
    exclusions = require_string_list(
        request_scope.get("exclusions"), "target claim scope exclusions"
    )
    defeaters = require_string_list(
        task.get("defeaters"), "target claim scope defeaters"
    )
    coverage_dimensions: list[str] = []
    benchmark_profiles: list[str] = []
    scope = {
        "scope_statement": require_string(
            task.get("scope_bounds"), "target claim scope statement"
        ),
        "assumptions": assumptions,
        "conditions": conditions,
        "units": units,
        "exclusions": exclusions,
        "defeaters": defeaters,
        "coverage_dimensions": coverage_dimensions,
        "benchmark_profiles": benchmark_profiles,
    }
    target = {
        "schema": TARGET_CLAIM_SCHEMA,
        "schema_version": "1.0",
        "claim_text": require_string(
            report.get("claim_statement"), "target claim claim_text"
        ),
        "entity_id": None,
        "impact": require_string(
            hypothesis.get("decision_impact"), "target claim impact"
        ),
        "coverage_dimensions": coverage_dimensions,
        "benchmark_profiles": benchmark_profiles,
        "supersedes": None,
        "epistemic_status": {
            "projection_status": basis["projection_status"],
            "claim_support_eligible": basis["claim_support_eligible"],
            "inspection_depth": basis["inspection_depth"],
            "relation": basis["relation"],
        },
        "gap_hypothesis_id": hypothesis["hypothesis_id"],
        "target_signature": target_signature,
        "report_claim_id": basis["claim_id"],
        "report_claim_digest": basis["claim_digest"],
        "scope": scope,
        "scope_digest": sha256_json(scope),
    }
    if target["impact"] not in LEVELS:
        raise ContractError("target claim impact must come from decision_impact")
    target["target_claim_digest"] = sha256_json(target)
    target["claim_id"] = "claim-target-" + target["target_claim_digest"][:16]
    return target


def _validate_patch_target_claim(
    action: dict[str, Any], rows: list[dict[str, Any]]
) -> dict[str, Any]:
    target = require_dict(action.get("target_claim"), "patch action target_claim")
    expected_fields = {
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
    }
    if set(target) != expected_fields:
        raise ContractError("patch target_claim field set invalid")
    if target["schema"] != TARGET_CLAIM_SCHEMA or target["schema_version"] != "1.0":
        raise ContractError("patch target_claim schema/version mismatch")
    require_string(target["claim_text"], "patch target_claim claim_text")
    if target["entity_id"] is not None:
        require_string(target["entity_id"], "patch target_claim entity_id")
    if target["impact"] not in LEVELS:
        raise ContractError("patch target_claim impact invalid")
    if target["supersedes"] is not None:
        raise ContractError("patch target_claim supersedes must be null")
    coverage = require_string_list(
        target["coverage_dimensions"],
        "patch target_claim coverage_dimensions",
    )
    profiles = require_string_list(
        target["benchmark_profiles"],
        "patch target_claim benchmark_profiles",
    )
    if coverage or profiles:
        raise ContractError(
            "patch target_claim coverage_dimensions and benchmark_profiles require "
            "explicit same-named request fields"
        )
    if len(coverage) != len(set(coverage)) or len(profiles) != len(set(profiles)):
        raise ContractError("patch target_claim scope/profile lists must be unique")
    scope = require_dict(target["scope"], "patch target_claim scope")
    if set(scope) != {
        "scope_statement",
        "assumptions",
        "conditions",
        "units",
        "exclusions",
        "defeaters",
        "coverage_dimensions",
        "benchmark_profiles",
    }:
        raise ContractError("patch target_claim scope field set invalid")
    require_string(scope["scope_statement"], "patch target_claim scope_statement")
    for field in (
        "assumptions",
        "conditions",
        "units",
        "exclusions",
        "defeaters",
        "coverage_dimensions",
        "benchmark_profiles",
    ):
        values = require_string_list(scope[field], f"patch target_claim scope.{field}")
        if len(values) != len(set(values)):
            raise ContractError(
                f"patch target_claim scope.{field} values must be unique"
            )
    if (
        scope["coverage_dimensions"] != coverage
        or scope["benchmark_profiles"] != profiles
    ):
        raise ContractError("patch target_claim scope/profile projection mismatch")
    if target["scope_digest"] != sha256_json(scope):
        raise ContractError("patch target_claim scope_digest mismatch")
    if target["gap_hypothesis_id"] != action["hypothesis_id"]:
        raise ContractError("patch target_claim hypothesis binding mismatch")
    if target["target_signature"] != action["target_signature"]:
        raise ContractError("patch target_claim target signature mismatch")
    ensure_sha256(
        target["report_claim_digest"], "patch target_claim report_claim_digest"
    )
    matches = [
        row
        for row in rows
        if row["claim_id"] == target["report_claim_id"]
        and row["claim_digest"] == target["report_claim_digest"]
    ]
    if not matches:
        raise ContractError("patch target_claim does not bind reviewed report claim")
    epistemic = require_dict(
        target["epistemic_status"], "patch target_claim epistemic_status"
    )
    if set(epistemic) != {
        "projection_status",
        "claim_support_eligible",
        "inspection_depth",
        "relation",
    }:
        raise ContractError("patch target_claim epistemic_status fields invalid")
    if not any(
        epistemic
        == {
            "projection_status": row["projection_status"],
            "claim_support_eligible": row["claim_support_eligible"],
            "inspection_depth": row["inspection_depth"],
            "relation": row["relation"],
        }
        for row in matches
    ):
        raise ContractError("patch target_claim epistemic status mismatch")
    expected_digest = sha256_json(
        {
            key: value
            for key, value in target.items()
            if key not in {"claim_id", "target_claim_digest"}
        }
    )
    if target["target_claim_digest"] != expected_digest:
        raise ContractError("patch target_claim_digest mismatch")
    if target["claim_id"] != "claim-target-" + expected_digest[:16]:
        raise ContractError("patch target_claim claim_id mismatch")
    return target


def propose_patch(
    document: Any,
    network: dict[str, Any],
    review_requests_value: Any,
    reading_reports_value: Any,
    dossier_value: Any,
    *,
    source_bundle_path: str | Path,
    source_artifact_path: str | Path,
    verification_root: str | Path,
    execution_authority_contexts: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    document = validate_hypotheses(
        document,
        network,
        execution_authority_contexts=execution_authority_contexts,
    )
    (
        review_requests,
        report_set,
        dossier,
        verified_bundle,
        records,
    ) = _derive_review_records(
        network,
        review_requests_value,
        reading_reports_value,
        dossier_value,
        source_bundle_path=source_bundle_path,
        source_artifact_path=source_artifact_path,
        verification_root=verification_root,
    )
    derivation_digest = _review_derivation_digest(
        review_requests, report_set, dossier, verified_bundle, records
    )
    cycle = require_dict(document.get("cycle_state"), "hypotheses.cycle_state")
    expected_cycle = {
        "review_request_set_id": review_requests["request_set_id"],
        "review_request_set_digest": review_requests["request_set_digest"],
        "report_set_id": report_set["report_set_id"],
        "report_set_digest": report_set["report_set_digest"],
        "dossier_id": dossier["dossier_id"],
        "dossier_digest": dossier["dossier_digest"],
        "source_bundle_id": verified_bundle["bundle_id"],
        "source_bundle_digest": verified_bundle["bundle_digest"],
        "review_derivation_digest": derivation_digest,
    }
    for field, expected in expected_cycle.items():
        if cycle.get(field) != expected:
            raise ContractError(f"proposal cycle {field} mismatch")
    for record in records:
        record["report_set_id"] = report_set["report_set_id"]
        record["report_set_digest"] = report_set["report_set_digest"]

    onboarding_ids = sorted(
        {
            record["source"]["source_id"]
            for record in records
            if record["onboarding_required"]
        }
    )
    if any(
        hypothesis["status"] == "blocked"
        and hypothesis["next_action"] == "onboarding_required"
        for hypothesis in document["hypotheses"]
    ):
        raise ContractError(
            "terminal onboarding_required: source must be added to the live network "
            f"before proposal generation: {onboarding_ids}"
        )

    actions = []
    for hypothesis in document["hypotheses"]:
        if hypothesis["status"] not in {"content_found", "supported_gap"}:
            continue
        eligible = [
            record
            for record in records
            if record["report"]["hypothesis_id"] == hypothesis["hypothesis_id"]
            and record["patch_eligible"]
        ]
        if not eligible:
            missing = sorted(
                {
                    record["source"]["source_id"]
                    for record in records
                    if record["report"]["hypothesis_id"] == hypothesis["hypothesis_id"]
                    and record["onboarding_required"]
                }
            )
            if missing:
                raise ContractError(
                    "terminal onboarding_required: source must be added to the live "
                    f"network before proposal generation: {missing}"
                )
            raise ContractError("accepted hypothesis lacks eligible v2 evidence")
        reviewed_evidence = [_basis_row(record) for record in eligible]
        target_kind = hypothesis["target_kind"]
        action_type = ACTION_FOR_TARGET_KIND[target_kind]
        target_signature = {
            "target_kind": target_kind,
            "signature": hypothesis["target_signature"],
        }
        action = {
            "action_id": "",
            "action_digest": "",
            "action_type": action_type,
            "action_status": _patch_action_status(
                target_kind,
                target_signature,
                reviewed_evidence,
            ),
            "hypothesis_id": hypothesis["hypothesis_id"],
            "target_signature": target_signature,
            "hypothesis": hypothesis["hypothesis"],
            "reviewed_evidence": reviewed_evidence,
        }
        if target_kind == "relation":
            action["target_claim"] = _target_claim_from_record(
                hypothesis,
                eligible[0],
                reviewed_evidence[0],
                target_signature,
            )
        action["action_digest"] = sha256_json(
            {
                key: value
                for key, value in action.items()
                if key not in {"action_id", "action_digest"}
            }
        )
        action["action_id"] = "network-patch-action-" + action["action_digest"][:16]
        actions.append(action)

    request_ref = {
        "request_set_id": require_string(
            cycle.get("request_set_id"), "cycle.request_set_id"
        ),
        "request_set_digest": ensure_sha256(
            cycle.get("request_set_digest"), "cycle.request_set_digest"
        ),
        "review_request_set_id": review_requests["request_set_id"],
        "review_request_set_digest": review_requests["request_set_digest"],
    }
    patch = {
        "schema": PATCH_SCHEMA,
        "schema_version": PATCH_SCHEMA_VERSION,
        "proposal_id": "",
        "proposal_digest": "",
        "network_ref": network_ref(network),
        "request_ref": request_ref,
        "generated_at": document["generated_at"],
        "proposal_only": True,
        "novelty_claimed": False,
        "review_gate": "pending_research_knowledge_network_acceptance",
        "actions": actions,
    }
    patch["proposal_digest"] = sha256_json(
        {
            key: value
            for key, value in patch.items()
            if key not in {"proposal_id", "proposal_digest"}
        }
    )
    patch["proposal_id"] = "network-patch-proposal-" + patch["proposal_digest"][:16]
    return validate_patch_v2(patch, network)


def validate_patch_v2(
    value: Any, network: dict[str, Any] | None = None
) -> dict[str, Any]:
    patch = require_dict(value, "NetworkPatchProposal/v2")
    expected_keys = {
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
    }
    if set(patch) != expected_keys or patch.get("schema") != PATCH_SCHEMA:
        raise ContractError("invalid NetworkPatchProposal/v2 top-level contract")
    if patch["schema_version"] != PATCH_SCHEMA_VERSION:
        raise ContractError("patch.schema_version must be 2.0")
    if patch["proposal_only"] is not True or patch["novelty_claimed"] is not False:
        raise ContractError("patch must remain proposal-only and non-novelty")
    if patch["review_gate"] != "pending_research_knowledge_network_acceptance":
        raise ContractError("patch review_gate invalid")
    validate_network_ref(patch["network_ref"], "patch.network_ref")
    if network is not None and patch["network_ref"] != network_ref(network):
        raise ContractError("patch network_ref mismatch")
    request_ref_value = require_dict(patch["request_ref"], "patch.request_ref")
    if set(request_ref_value) != {
        "request_set_id",
        "request_set_digest",
        "review_request_set_id",
        "review_request_set_digest",
    }:
        raise ContractError("patch.request_ref field set invalid")
    for field in ("request_set_id", "review_request_set_id"):
        require_string(request_ref_value.get(field), f"patch.request_ref.{field}")
    for field in ("request_set_digest", "review_request_set_digest"):
        ensure_sha256(request_ref_value.get(field), f"patch.request_ref.{field}")
    require_timestamp(patch["generated_at"], "patch.generated_at")
    actions = patch["actions"]
    if not isinstance(actions, list):
        raise ContractError("patch.actions must be a list")
    live_source_ids = _live_source_ids(network) if network is not None else None
    action_ids = set()
    hypothesis_ids = set()
    for action in actions:
        action = require_dict(action, "patch action")
        action_type = action.get("action_type")
        expected_action_fields = {
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
            expected_action_fields.add("target_claim")
        if set(action) != expected_action_fields:
            raise ContractError("patch action field set invalid")
        if action["action_type"] not in {
            "propose_node",
            "propose_relation",
            "propose_evidence",
        }:
            raise ContractError("patch action type invalid")
        if action["action_status"] not in PATCH_ACTION_STATUSES:
            raise ContractError("patch action status invalid")
        require_string(action["hypothesis_id"], "patch action hypothesis_id")
        require_string(action["hypothesis"], "patch action hypothesis")
        target = require_dict(
            action["target_signature"], "patch action target_signature"
        )
        if set(target) != {"target_kind", "signature"}:
            raise ContractError("patch action target_signature fields invalid")
        target_kind = target["target_kind"]
        if target_kind not in ACTION_FOR_TARGET_KIND:
            raise ContractError("patch action target kind unsupported")
        if action["action_type"] != ACTION_FOR_TARGET_KIND[target_kind]:
            raise ContractError("patch action target_signature kind mismatch")
        require_string(target["signature"], "patch action target signature")
        expected_action_digest = sha256_json(
            {
                key: item
                for key, item in action.items()
                if key not in {"action_id", "action_digest"}
            }
        )
        if action["action_digest"] != expected_action_digest:
            raise ContractError("patch action_digest mismatch")
        if action["action_id"] != "network-patch-action-" + expected_action_digest[:16]:
            raise ContractError("patch action_id mismatch")
        if (
            action["action_id"] in action_ids
            or action["hypothesis_id"] in hypothesis_ids
        ):
            raise ContractError("patch duplicate action or hypothesis identity")
        action_ids.add(action["action_id"])
        hypothesis_ids.add(action["hypothesis_id"])
        rows = action["reviewed_evidence"]
        if not isinstance(rows, list) or not rows:
            raise ContractError("patch action requires reviewed_evidence")
        basis_ids = set()
        for row in rows:
            if set(row) != {
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
            }:
                raise ContractError("patch reviewed_evidence field set invalid")
            for field in (
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
            ):
                ensure_sha256(row[field], f"patch basis {field}")
            for field in (
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
            ):
                require_string(row[field], f"patch basis {field}")
            if live_source_ids is not None and row["source_id"] not in live_source_ids:
                raise ContractError(
                    "terminal onboarding_required: patch basis.source_id is not in "
                    f"the live network: {row['source_id']}"
                )
            verification = require_dict(row["verification"], "patch basis verification")
            if set(verification) != {"mode", "verifier_id", "artifact_sha256"}:
                raise ContractError("patch basis verification fields invalid")
            if verification["mode"] not in {
                "independent_source_check",
                "expert_review",
            }:
                raise ContractError("patch basis verification mode ineligible")
            require_string(verification["verifier_id"], "patch verifier_id")
            ensure_sha256(verification["artifact_sha256"], "patch artifact_sha256")
            if (
                row["relation"] != "supports"
                or row["access_level"] != "full_text"
                or row["inspection_depth"] not in {"evidence", "reconstruction"}
                or row["claim_support_eligible"] is not True
                or row["projection_status"] != "decisive"
                or _is_unacceptable_locator(row["evidence_locator"])
            ):
                raise ContractError("patch basis is not graph eligible")
            expected_basis_digest = sha256_json(
                {
                    key: item
                    for key, item in row.items()
                    if key not in {"basis_id", "basis_digest"}
                }
            )
            if row["basis_digest"] != expected_basis_digest:
                raise ContractError("patch basis_digest mismatch")
            if row["basis_id"] != "network-patch-basis-" + expected_basis_digest[:16]:
                raise ContractError("patch basis_id mismatch")
            if row["basis_id"] in basis_ids:
                raise ContractError("patch duplicate basis identity")
            basis_ids.add(row["basis_id"])
        expected_status = _patch_action_status(target_kind, target, rows)
        if action["action_status"] != expected_status:
            raise ContractError(
                "patch action status does not match target materialization eligibility"
            )
        if action["action_type"] == "propose_relation":
            _validate_patch_target_claim(action, rows)
    expected_digest = sha256_json(
        {
            key: item
            for key, item in patch.items()
            if key not in {"proposal_id", "proposal_digest"}
        }
    )
    if patch["proposal_digest"] != expected_digest:
        raise ContractError("patch proposal_digest mismatch")
    if patch["proposal_id"] != "network-patch-proposal-" + expected_digest[:16]:
        raise ContractError("patch proposal_id mismatch")
    return patch


def validate_patch_v1(
    value: Any, network: dict[str, Any] | None = None
) -> dict[str, Any]:
    patch = require_dict(value, "patch")
    if patch.get("schema") != PATCH_V1_SCHEMA:
        raise ContractError(f"patch.schema must equal {PATCH_SCHEMA}")
    require_string(patch.get("proposal_id"), "patch.proposal_id")
    if network is not None:
        validate_network_ref(patch.get("network_ref"), "patch.network_ref", network)
    require_timestamp(patch.get("generated_at"), "patch.generated_at")
    require_string_list(patch.get("basis_gap_ids"), "patch.basis_gap_ids", True)
    if patch.get("proposal_only") is not True:
        raise ContractError("patch.proposal_only must be true")
    if patch.get("novelty_claimed") is not False:
        raise ContractError("patch.novelty_claimed must be false")
    if patch.get("review_gate") != "pending_research_knowledge_network_validation":
        raise ContractError("patch.review_gate must remain pending")
    for forbidden in ("apply", "auto_merge", "write_authorized"):
        if patch.get(forbidden):
            raise ContractError(f"patch must not authorize {forbidden}")
    for collection in ("nodes", "relations", "evidence"):
        rows = patch.get(collection)
        if not isinstance(rows, list):
            raise ContractError(f"patch.{collection} must be a list")
        for index, row in enumerate(rows):
            item = require_dict(row, f"patch.{collection}[{index}]")
            provenance = item.get("provenance")
            if not isinstance(provenance, list) or not provenance:
                raise ContractError(
                    f"patch.{collection}[{index}].provenance is required"
                )
            for source in provenance:
                entry = require_dict(source, "patch provenance")
                require_string(entry.get("source_ref"), "patch provenance source_ref")
                require_string(entry.get("locator"), "patch provenance locator")
                if "source_id" in entry:
                    require_string(entry.get("source_id"), "patch provenance source_id")
                if "source_digest" in entry:
                    ensure_sha256(
                        entry.get("source_digest"), "patch provenance source_digest"
                    )
                read_depth = require_string(
                    entry.get("read_depth"), "patch provenance read_depth"
                )
                if read_depth not in READ_DEPTHS:
                    raise ContractError(
                        "patch provenance needs full_text or evidence depth"
                    )
    return patch


def validate_any(
    value: Any,
    network: dict[str, Any] | None = None,
    *,
    history_authority: Any | None = None,
    history_authority_review: Any | None = None,
    execution_authority_contexts: dict[str, dict[str, Any]] | None = None,
    history_artifact_file_sha256s: list[str] | None = None,
) -> dict[str, Any]:
    schema = value.get("schema") if isinstance(value, dict) else None
    if schema == NETWORK_SCHEMA:
        return validate_network(value)
    if schema == PROBE_SCHEMA:
        return validate_probe(value)
    if schema == HYPOTHESES_SCHEMA:
        return validate_hypotheses(
            value,
            network,
            execution_authority_contexts=execution_authority_contexts,
            history_artifact_file_sha256s=history_artifact_file_sha256s,
        )
    if schema == PATCH_SCHEMA:
        return validate_patch_v2(value, network)
    if schema == PATCH_V1_SCHEMA:
        return validate_patch_v1(value, network)
    if schema in {REQUEST_SET_SCHEMA, APPRAISAL_REQUEST_SET_SCHEMA}:
        return validate_request_set(
            value,
            network=network,
            execution_authority_contexts=execution_authority_contexts,
        )
    if schema == REQUEST_SCHEMA:
        return validate_scholar_discovery_request(value)
    if schema == RESULT_SCHEMA:
        return validate_scholar_discovery_result(value)
    if schema in {RESULT_SET_SCHEMA, RESULT_SET_V2_SCHEMA}:
        return validate_scholar_discovery_result_set(value, network=network)
    if schema == LEARN_FROM_PAPERS_REQUEST_SCHEMA:
        return validate_learn_from_papers_request(value)
    if schema == LEARN_FROM_PAPERS_REQUEST_SET_SCHEMA:
        return validate_learn_from_papers_request_set(value, network=network)
    if schema == REVIEWED_EVIDENCE_SCHEMA:
        return validate_reviewed_evidence(value)
    if schema == REVIEWED_EVIDENCE_SET_SCHEMA:
        return validate_reviewed_evidence_set(value, network=network)
    if schema == PAPER_READING_REPORT_SCHEMA:
        return validate_paper_reading_report(value, network=network)
    if schema == PAPER_READING_REPORT_SET_SCHEMA:
        return validate_paper_reading_report_set(value, network=network)
    if schema == PAPER_READING_REPORT_SET_V2_SCHEMA:
        return validate_paper_reading_report_set_v2(value, network=network)
    if schema == PAPER_UNDERSTANDING_GAP_SCHEMA:
        return validate_paper_understanding_gap(value)
    if schema == EVIDENCE_CHALLENGE_SCHEMA:
        return validate_evidence_challenge(value)
    if schema == TARGETED_EVIDENCE_NEED_SET_SCHEMA:
        return validate_targeted_evidence_need_set(value)
    if schema == "EvidenceAppraisalPackage/v1":
        return validate_evidence_appraisal_package(value)
    if schema == REVIEWED_HISTORY_AUTHORITY_SCHEMA:
        return validate_reviewed_history_authority(value)
    if schema == HISTORY_AUTHORITY_MANIFEST_SCHEMA:
        if history_authority_review is None:
            raise ContractError(
                "HistoryAuthorityManifest/v1 validation requires "
                "--history-authority-review"
            )
        return validate_history_authority_manifest(value, history_authority_review)
    if schema in {SEARCH_HISTORY_INDEX_SCHEMA, SEARCH_HISTORY_INDEX_V2_SCHEMA}:
        if history_authority is None or history_authority_review is None:
            raise ContractError(
                "SearchHistoryIndex validation requires --history-authority "
                "and --history-authority-review"
            )
        return validate_search_history_index(
            value,
            history_authority,
            history_authority_review,
            execution_authority_contexts=execution_authority_contexts,
            artifact_file_sha256s=history_artifact_file_sha256s,
        )
    raise ContractError(f"unsupported schema: {schema!r}")


NETWORK_INPUT_HELP = (
    "Path to exported KnowledgeNetwork/v1 JSON; do not pass networks/<id>/network.json"
)


def load_exported_knowledge_network(path_value: str | Path) -> dict[str, Any]:
    value = load_json(path_value)
    if not isinstance(value, dict):
        raise ContractError("network must be a KnowledgeNetwork/v1 object")
    if value.get("schema") == NETWORK_SCHEMA:
        return validate_network(value)
    if "schema" not in value and "schema_version" in value and "network_id" in value:
        raise ContractError(
            "--network requires an exported KnowledgeNetwork/v1 JSON, not the "
            "RKN storage network.json/NetworkManifest; run the "
            "research-knowledge-network export command first"
        )
    raise ContractError("network.schema must equal KnowledgeNetwork/v1")


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description=__doc__)
    subcommands = root.add_subparsers(dest="command", required=True)

    scan = subcommands.add_parser("scan", help="scan a KnowledgeNetwork/v1")
    scan.add_argument("--network", required=True, help=NETWORK_INPUT_HELP)
    scan.add_argument("--output", required=True)

    generate = subcommands.add_parser(
        "generate-hypotheses",
        help="emit deterministic gap hypotheses from network scan",
    )
    generate.add_argument("--network", required=True, help=NETWORK_INPUT_HELP)
    generate.add_argument("--round-id")
    generate.add_argument("--output", required=True)

    compile_needs = subcommands.add_parser(
        "compile-appraisal-needs",
        help=(
            "compile finalized appraisal challenges and targeted needs into "
            "searchable hypotheses plus explicit non-search routes"
        ),
    )
    compile_needs.add_argument("--needs", required=True)
    compile_needs.add_argument("--challenge", action="append", required=True)
    compile_needs.add_argument("--history-index", required=True)
    compile_needs.add_argument("--history-authority", required=True)
    compile_needs.add_argument("--history-authority-review", required=True)
    compile_needs.add_argument("--execution-authority", action="append", default=[])
    compile_needs.add_argument(
        "--expected-execution-authority-sha256", action="append", default=[]
    )
    compile_needs.add_argument("--network", required=True, help=NETWORK_INPUT_HELP)
    compile_needs.add_argument("--round-id", required=True)
    compile_needs.add_argument("--output", required=True)

    dispatch_package = subcommands.add_parser(
        "dispatch-appraisal-package",
        help="validate a producer package and route compact non-search needs",
    )
    dispatch_package.add_argument("--package", required=True)
    dispatch_package.add_argument("--approval", required=True)
    dispatch_package.add_argument("--prepared", required=True)
    dispatch_package.add_argument("--review", required=True)
    dispatch_package.add_argument("--expected-authority-sha256", required=True)
    dispatch_package.add_argument("--lineage", action="append", default=[])
    dispatch_package.add_argument("--output", required=True)

    rank = subcommands.add_parser("prioritize", help="rank gap hypotheses")
    rank.add_argument("--input", required=True)
    rank.add_argument("--network", help=NETWORK_INPUT_HELP)
    rank.add_argument("--output", required=True)

    select = subcommands.add_parser(
        "select", help="apply a reviewed allowlist to prioritized hypotheses"
    )
    select.add_argument("--input", required=True)
    select.add_argument("--selection", required=True)
    select.add_argument("--network", required=True, help=NETWORK_INPUT_HELP)
    select.add_argument("--output", required=True)

    emit = subcommands.add_parser(
        "emit-search-requests", help="emit scholar-discovery requests"
    )
    emit.add_argument("--input", required=True)
    emit.add_argument("--network", required=True, help=NETWORK_INPUT_HELP)
    emit.add_argument("--output", required=True)
    emit.add_argument(
        "--google-scholar-policy",
        choices=["manual_optional", "manual_required", "disabled"],
        default="manual_optional",
    )
    emit.add_argument("--max-rounds", type=int, default=3)
    emit.add_argument("--max-candidates", type=int, default=100)
    emit.add_argument("--timeout-seconds", type=int, default=900)

    consume = subcommands.add_parser(
        "consume-results", help="consume result set and transition hypothesis status"
    )
    consume.add_argument("--hypotheses", required=True)
    consume.add_argument("--network", required=True, help=NETWORK_INPUT_HELP)
    consume.add_argument("--requests", required=True)
    consume.add_argument("--result", action="append", default=[], required=True)
    consume.add_argument("--execution-authority", action="append", default=[])
    consume.add_argument(
        "--expected-execution-authority-sha256", action="append", default=[]
    )
    consume.add_argument("--output", required=True)
    consume.add_argument("--round-id")

    consume_review = subcommands.add_parser(
        "consume-reviewed-evidence",
        help="consume reviewed evidence and transition hypothesis status",
    )
    consume_review.add_argument("--hypotheses", required=True)
    consume_review.add_argument("--network", required=True, help=NETWORK_INPUT_HELP)
    consume_review.add_argument("--review-requests", required=True)
    consume_review.add_argument("--reading-reports", required=True)
    consume_review.add_argument("--dossier", required=True)
    consume_review.add_argument("--source-bundle", required=True)
    consume_review.add_argument("--source-artifact", required=True)
    consume_review.add_argument("--verification-root", required=True)
    consume_review.add_argument("--output", required=True)
    consume_review.add_argument("--round-id")

    propose = subcommands.add_parser(
        "propose-patch", help="emit proposal-only NetworkPatchProposal/v2"
    )
    propose.add_argument("--input", required=True)
    propose.add_argument("--network", required=True, help=NETWORK_INPUT_HELP)
    propose.add_argument("--review-requests", required=True)
    propose.add_argument("--reading-reports", required=True)
    propose.add_argument("--dossier", required=True)
    propose.add_argument("--source-bundle", required=True)
    propose.add_argument("--source-artifact", required=True)
    propose.add_argument("--verification-root", required=True)
    propose.add_argument("--output", required=True)

    validate = subcommands.add_parser("validate", help="validate one contract")
    validate.add_argument("--input", required=True)
    validate.add_argument("--network", help=NETWORK_INPUT_HELP)
    validate.add_argument("--history-authority")
    validate.add_argument("--history-authority-review")
    validate.add_argument("--execution-authority", action="append", default=[])
    validate.add_argument(
        "--expected-execution-authority-sha256", action="append", default=[]
    )

    cycle = subcommands.add_parser("cycle", help="run bounded discovery cycle")
    cycle.add_argument("--network", required=True, help=NETWORK_INPUT_HELP)
    cycle.add_argument("--hypotheses-output", required=True)
    cycle.add_argument("--requests-output", required=True)
    cycle.add_argument(
        "--google-scholar-policy",
        choices=["manual_optional", "manual_required", "disabled"],
        default="manual_optional",
    )

    return root


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        if args.command == "scan":
            write_json(
                args.output, scan_network(load_exported_knowledge_network(args.network))
            )

        elif args.command == "generate-hypotheses":
            network = load_exported_knowledge_network(args.network)
            validate_network(network)
            probe = scan_network(network)
            write_json(
                args.output,
                generate_hypotheses_from_probe(
                    probe,
                    network,
                    round_id=args.round_id,
                ),
            )

        elif args.command == "compile-appraisal-needs":
            network = load_exported_knowledge_network(args.network)
            scholar = _scholar_discovery_module()
            execution_contexts = scholar.load_execution_authority_contexts(
                args.execution_authority,
                args.expected_execution_authority_sha256,
            )
            history_index = load_json(args.history_index)
            history_artifact_file_sha256s = None
            if isinstance(history_index, dict):
                raw_hashes = history_index.get("artifact_file_sha256s")
                if isinstance(raw_hashes, list):
                    history_artifact_file_sha256s = raw_hashes
            write_json(
                args.output,
                compile_appraisal_needs(
                    load_json(args.needs),
                    [load_json(path) for path in args.challenge],
                    history_index,
                    load_json(args.history_authority),
                    load_json(args.history_authority_review),
                    network,
                    round_id=args.round_id,
                    execution_authority_contexts=execution_contexts,
                    artifact_file_sha256s=history_artifact_file_sha256s,
                ),
            )

        elif args.command == "dispatch-appraisal-package":
            write_json(
                args.output,
                dispatch_evidence_appraisal_package(
                    load_json(args.package),
                    load_json(args.approval),
                    load_json(args.prepared),
                    load_json(args.review),
                    expected_authority_sha256=args.expected_authority_sha256,
                    lineage=[load_json(path) for path in args.lineage],
                ),
            )

        elif args.command == "prioritize":
            network = (
                load_exported_knowledge_network(args.network) if args.network else None
            )
            write_json(args.output, prioritize(load_json(args.input), network))

        elif args.command == "select":
            network = load_exported_knowledge_network(args.network)
            validate_network(network)
            write_json(
                args.output,
                select_hypotheses(
                    load_json(args.input),
                    load_json(args.selection),
                    network,
                ),
            )

        elif args.command == "emit-search-requests":
            network = load_exported_knowledge_network(args.network)
            validate_network(network)
            write_json(
                args.output,
                emit_search_requests(
                    load_json(args.input),
                    network,
                    google_scholar_policy=args.google_scholar_policy,
                    max_rounds=args.max_rounds,
                    max_candidates=args.max_candidates,
                    timeout_seconds=args.timeout_seconds,
                ),
            )

        elif args.command == "consume-results":
            network = load_exported_knowledge_network(args.network)
            validate_network(network)
            hypotheses = load_json(args.hypotheses)
            scholar = _scholar_discovery_module()
            request_set, request_set_file_sha256 = (
                scholar.load_request_set_artifact_file(args.requests)
            )
            execution_contexts = scholar.load_execution_authority_contexts(
                args.execution_authority,
                args.expected_execution_authority_sha256,
            )
            result_inputs = [load_json(path) for path in args.result]
            output = consume_results(
                hypotheses,
                network,
                request_set,
                result_inputs,
                round_id=args.round_id,
                execution_authority_contexts=execution_contexts,
                request_set_file_sha256=request_set_file_sha256,
            )
            write_json(args.output, output)

        elif args.command == "consume-reviewed-evidence":
            network = load_exported_knowledge_network(args.network)
            validate_network(network)
            output = consume_reviewed_evidence(
                load_json(args.hypotheses),
                network,
                load_json(args.review_requests),
                load_json(args.reading_reports),
                load_json(args.dossier),
                source_bundle_path=args.source_bundle,
                source_artifact_path=args.source_artifact,
                verification_root=args.verification_root,
                round_id=args.round_id,
            )
            write_json(args.output, output)

        elif args.command == "propose-patch":
            network = load_exported_knowledge_network(args.network)
            validate_network(network)
            write_json(
                args.output,
                propose_patch(
                    load_json(args.input),
                    network,
                    load_json(args.review_requests),
                    load_json(args.reading_reports),
                    load_json(args.dossier),
                    source_bundle_path=args.source_bundle,
                    source_artifact_path=args.source_artifact,
                    verification_root=args.verification_root,
                ),
            )

        elif args.command == "cycle":
            network = load_exported_knowledge_network(args.network)
            validate_network(network)
            probe = scan_network(network)
            hypotheses = generate_hypotheses_from_probe(probe, network)
            prioritized = prioritize(hypotheses, network)
            request_set = emit_search_requests(
                prioritized,
                network,
                google_scholar_policy=args.google_scholar_policy,
            )
            write_json(args.hypotheses_output, prioritized)
            write_json(args.requests_output, request_set)

        else:
            network = (
                load_exported_knowledge_network(args.network) if args.network else None
            )
            scholar = _scholar_discovery_module()
            execution_contexts = scholar.load_execution_authority_contexts(
                args.execution_authority,
                args.expected_execution_authority_sha256,
            )
            input_value = load_json(args.input)
            history_artifact_file_sha256s = None
            if isinstance(input_value, dict):
                raw_hashes = input_value.get("artifact_file_sha256s")
                if isinstance(raw_hashes, list):
                    history_artifact_file_sha256s = raw_hashes
            output = validate_any(
                input_value,
                network,
                history_authority=(
                    load_json(args.history_authority)
                    if args.history_authority
                    else None
                ),
                history_authority_review=(
                    load_json(args.history_authority_review)
                    if args.history_authority_review
                    else None
                ),
                execution_authority_contexts=execution_contexts,
                history_artifact_file_sha256s=history_artifact_file_sha256s,
            )
            print(
                json.dumps({"valid": True, "schema": output["schema"]}, sort_keys=True)
            )
        return 0

    except (
        ContractError,
        json.JSONDecodeError,
        OSError,
        ValueError,
        TypeError,
        re.error,
    ) as exc:
        print(f"network-gap-discovery validation failed: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
