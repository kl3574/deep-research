#!/usr/bin/env python3
"""Compose auditable scholarly-discovery contracts and execute legal API routes."""

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
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable


REQUEST_SCHEMA = "ScholarDiscoveryRequest/v1"
REQUEST_SET_SCHEMA = "ScholarDiscoveryRequestSet/v1"
APPRAISAL_REQUEST_SET_SCHEMA = "AppraisalScholarDiscoveryRequestSet/v1"
GENERIC_REQUEST_ID_PREFIX = "SDR-"
APPRAISAL_REQUEST_ID_PREFIX = "ASDR-"
SEARCH_EXECUTION_AUTHORIZATION_SCHEMA = "ReviewedSearchExecutionAuthorization/v1"
SEARCH_EXECUTION_AUTHORIZATION_ID_PREFIX = "search-execution-authorization-"
PLAN_SCHEMA = "ScholarQueryPlan/v1"
BATCH_SCHEMA = "ScholarResultBatch/v1"
RESULT_SCHEMA = "ScholarDiscoveryResult/v1"
RESULT_SET_SCHEMA = "ScholarDiscoveryResultSet/v1"
RESULT_SET_V2_SCHEMA = "ScholarDiscoveryResultSet/v2"
TOPIC_NEED_SET_SCHEMA = "ResearchTopicNeedSet/v1"
PREFLIGHT_SCHEMA = "ScholarDiscoveryPreflight/v1"
SEARCH_HISTORY_INDEX_SCHEMA = "SearchHistoryIndex/v1"
SEARCH_HISTORY_INDEX_V2_SCHEMA = "SearchHistoryIndex/v2"
SEARCH_HISTORY_INDEX_SCHEMAS = {
    SEARCH_HISTORY_INDEX_SCHEMA,
    SEARCH_HISTORY_INDEX_V2_SCHEMA,
}
HISTORY_AUTHORITY_MANIFEST_SCHEMA = "HistoryAuthorityManifest/v1"
HISTORY_AUTHORITY_CANDIDATE_SCHEMA = "HistoryAuthorityCandidate/v1"
REVIEWED_HISTORY_AUTHORITY_SCHEMA = "ReviewedHistoryAuthority/v1"
HISTORY_AUTHORITY_ID_PREFIX = "history-authority-"
HISTORY_AUTHORITY_APPROVAL_ID_PREFIX = "history-authority-approval-"
APPRAISAL_ORIGIN_SCHEMA = "EvidenceAppraisalNeedOrigin/v1"
REQUEST_SET_SCHEMA_VERSION = "v1"
PAPER_UNDERSTANDING_GAP_SCHEMA = "PaperUnderstandingGap/v1"

INTENTS = {"auto", "known_item", "topic_set", "author", "citation_graph", "update"}
EFFORTS = {"fast", "diligent"}
AUTOMATIC_PROVIDERS = {
    "openalex",
    "semantic_scholar",
    "crossref",
    "opencitations",
    "pubmed",
    "europepmc",
    "arxiv",
}
EXECUTABLE_PROVIDERS = {"openalex", "crossref", "semantic_scholar"}
GOOGLE_PROVIDER = "google_scholar"
GOOGLE_POLICIES = {"disabled", "manual_optional", "manual_required"}
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
BATCH_STATUSES = {
    "success",
    "partial",
    "empty",
    "blocked",
    "failed",
    "budget_exhausted",
    "succeeded",
}
BATCH_SUCCESS_STATUSES = {"success", "succeeded"}
SEARCH_SUCCESS_STATUSES = {"success", "succeeded", "empty"}
BATCH_INCOMPLETE_STATUSES = {"partial", "blocked", "failed", "budget_exhausted"}
BATCH_TERMINAL_STATUSES = {
    "success",
    "succeeded",
    "partial",
    "empty",
    "blocked",
    "failed",
    "budget_exhausted",
}
ACCESS_LEVELS = {"metadata_only", "abstract_only", "snippet_only", "full_text"}
OPENALEX_API_KEY_ENV = "OPENALEX_API_KEY"
SEMANTIC_SCHOLAR_API_KEY_ENV = "SEMANTIC_SCHOLAR_API_KEY"
OPENALEX_RESULTS_PER_PAGE = 10
SEMANTIC_SCHOLAR_RESULTS_LIMIT = 10
HTTP_USER_AGENT = "scholar-discovery/1.0 (+https://github.com/kl3574/deep-research)"
SEMANTIC_SCHOLAR_FIELDS = ",".join(
    [
        "title",
        "year",
        "venue",
        "publicationTypes",
        "externalIds",
        "authors",
        "isOpenAccess",
        "openAccessPdf",
        "url",
    ]
)
PUBLICATION_STATUSES = {
    "peer_reviewed",
    "preprint",
    "corrected",
    "retracted",
    "withdrawn",
    "unknown",
}
SCREENING_DECISIONS = {"include", "exclude", "maybe", "unscreened"}
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
IDENTIFIER_RE = re.compile(r"^([0-9A-Za-z_\-.:/]+)$")
DOI_RE = re.compile(r"^10\.\d{4,9}/\S+$")
MAX_FUTURE_SKEW = timedelta(minutes=5)

PAPER_UNDERSTANDING_GAP_QUERY_TERMS = {
    "missing_input_format": {
        "confirm": "input format data type schema interface",
        "refute": "unsupported input format incompatibility limitation",
    },
    "missing_data_flow": {
        "confirm": "data flow pipeline consumes produces intermediate output",
        "refute": "data flow ambiguity missing stage failure limitation",
    },
    "missing_derivation_step": {
        "confirm": "derivation proof equation intermediate step assumptions",
        "refute": "derivation gap omitted step limitation correction",
    },
    "missing_algorithm_detail": {
        "confirm": "algorithm pseudocode ordered steps state invariant stopping condition",
        "refute": "algorithm failure mode missing detail implementation limitation",
    },
    "missing_applicability_boundary": {
        "confirm": "applicability boundary assumptions conditions population regime",
        "refute": "out of scope boundary condition failure limitation",
    },
    "missing_conclusion_scope": {
        "confirm": "conclusion scope supported outcome conditions",
        "refute": "overgeneralization limitation scope qualification contradiction",
    },
}
SENSITIVE_GAP_QUERY_PATTERNS = (
    re.compile(r"(?:^|\s)(?:/(?:home|root|Users)/|~/|[A-Za-z]:[\\/])"),
    re.compile(r"\b(?:file://|ghp_|github_pat_|sk-|xox[baprs]-)[A-Za-z0-9_./-]+", re.I),
    re.compile(
        r"\b(?:api[_ -]?key|access[_ -]?token|authorization|cookie)\s*[:=]", re.I
    ),
    re.compile(r"\b(?=[A-Z0-9]{8}\b)(?=[A-Z0-9]*[A-Z])(?=[A-Z0-9]*[0-9])[A-Z0-9]{8}\b"),
    re.compile(r"\b[0-9a-f]{32,64}\b", re.I),
    re.compile(r"\b(?:gap|relation|node|entity)[:_-][A-Za-z0-9._-]+", re.I),
)
STRUCTURAL_PLACEHOLDER_PATTERNS = (
    re.compile(r"\bnetwork\s+dimension\b", re.I),
    re.compile(r"\bsemantic\s+enrichment\s+required\b", re.I),
    re.compile(
        r"\b(?:missing[-_ ]dimension|validation_target|surrogate_family|task_type)\b",
        re.I,
    ),
)

SEMANTIC_SIGNATURE_STOP_WORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "by",
    "confirm",
    "contradict",
    "contradiction",
    "evidence",
    "find",
    "for",
    "from",
    "in",
    "is",
    "limitation",
    "limitations",
    "of",
    "on",
    "or",
    "primary",
    "refute",
    "study",
    "support",
    "supports",
    "test",
    "tests",
    "that",
    "the",
    "this",
    "to",
    "under",
    "versus",
    "vs",
    "with",
    "without",
}
SEMANTIC_SIGNATURE_SYNONYMS = {
    "allocation": "attribution",
    "allocations": "attribution",
    "artifact": "artefact",
    "artifacts": "artefact",
    "baseline": "comparator",
    "baselines": "comparator",
    "codebase": "code",
    "correlated": "dependent",
    "correlation": "dependent",
    "correlations": "dependent",
    "covariate": "input",
    "covariates": "input",
    "dataset": "data",
    "datasets": "data",
    "independent": "independence",
    "independently": "independence",
    "indices": "index",
    "inputs": "input",
    "measure": "index",
    "measures": "index",
    "replicated": "replication",
    "reproduce": "replication",
    "reproduced": "replication",
    "reproduces": "replication",
    "results": "result",
    "variables": "input",
}
SEARCH_HISTORY_SOURCE_SCHEMAS = {
    REQUEST_SCHEMA,
    REQUEST_SET_SCHEMA,
    APPRAISAL_REQUEST_SET_SCHEMA,
    RESULT_SCHEMA,
    RESULT_SET_SCHEMA,
    RESULT_SET_V2_SCHEMA,
    "KnowledgeGapHypotheses/v1",
}
SEARCH_HISTORY_STATES = {
    "requested",
    "selection_leak",
    "succeeded",
    "partial",
    "empty",
    "failed",
    "blocked",
    "budget_exhausted",
    "candidate",
}

ENDPOINT_HINTS = {
    "openalex": "https://api.openalex.org/works",
    "crossref": "https://api.crossref.org/works",
    "semantic_scholar": "https://api.semanticscholar.org/graph/v1/paper/search",
    "opencitations": "https://api.opencitations.net/index/v2",
    "pubmed": "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/",
    "europepmc": "https://www.ebi.ac.uk/europepmc/webservices/rest/search",
    "arxiv": "https://export.arxiv.org/api/query",
}

SEARCH_EVENT_REQUIRED_FIELDS = {
    "endpoint",
    "redacted_request",
    "page_or_cursor",
    "expected_total",
    "retrieved",
    "truncated",
    "response_sha256",
    "limitations",
}
SEARCH_EVENT_OPTIONAL_FIELDS = {
    "artifact_origin",
    "rejected_candidate_count",
}
SEARCH_EVENT_FORBIDDEN_FIELDS = {
    "secret",
    "raw",
    "raw_query",
    "raw_request",
    "raw_response",
    "raw_payload",
    "raw_body",
    "full_text",
    "fulltext",
    "abstract",
    "snippet",
    "html",
    "token",
    "api_key",
    "apikey",
    "access_token",
    "authorization",
    "cookie",
    "session",
}
GOOGLE_NOT_PROVIDED_ORIGINS = {
    "not_provided_manual_optional",
    "not_provided_manual_required",
}
GOOGLE_USER_SUPPLIED_ORIGIN = "user_supplied_manual_export"

SCHOLAR_EXECUTION = "user_manual_export"
DOCUMENTED_EXECUTION = "documented_api"
GOOGLE_LIMITATION_MANUAL_EXPORT = "manual_export_not_provided"
ARXIV_V2_SUFFIX_RE = re.compile(r"v(\d+)$", flags=re.IGNORECASE)
ENDPOINT_WHITELIST = {
    "openalex": "https://api.openalex.org/works",
    "crossref": "https://api.crossref.org/works",
    "semantic_scholar": "https://api.semanticscholar.org/graph/v1/paper/search",
    "opencitations": "https://api.opencitations.net/index/v2",
    "pubmed": "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/",
    "europepmc": "https://www.ebi.ac.uk/europepmc/webservices/rest/search",
    "arxiv": "https://export.arxiv.org/api/query",
    "google_scholar": "https://scholar.google.com/scholar",
}

Transport = Callable[[str, int], bytes]


class ContractError(ValueError):
    """Raised when a discovery contract fails closed."""


_NETWORK_GAP_MODULE: Any | None = None


def _load_network_gap_module() -> Any:
    """Load the authoritative optional gap-contract validator on demand."""
    global _NETWORK_GAP_MODULE
    if _NETWORK_GAP_MODULE is not None:
        return _NETWORK_GAP_MODULE
    path = (
        Path(__file__).resolve().parents[2]
        / "network-gap-discovery"
        / "scripts"
        / "network_gap_discovery.py"
    )
    if not path.is_file():
        raise ContractError(
            "PaperUnderstanding gap compilation requires the "
            "network-gap-discovery skill"
        )
    spec = importlib.util.spec_from_file_location("scholar_network_gap_contract", path)
    if spec is None or spec.loader is None:
        raise ContractError(f"cannot load network-gap-discovery contract from {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    if not hasattr(module, "validate_paper_understanding_gap"):
        raise ContractError(
            "network-gap-discovery lacks validate_paper_understanding_gap"
        )
    _NETWORK_GAP_MODULE = module
    return module


def _validate_understanding_gap_contract(value: Any) -> dict[str, Any]:
    try:
        return _load_network_gap_module().validate_paper_understanding_gap(value)
    except ValueError as exc:
        raise ContractError(f"invalid PaperUnderstanding gap: {exc}") from exc


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def sha256_json(value: Any) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def now_iso_utc() -> str:
    return datetime.now(tz=timezone.utc).replace(microsecond=0).isoformat()


def load_json(path: str | Path) -> Any:
    candidate = Path(path)
    if candidate.is_symlink() or not candidate.is_file():
        raise ContractError(f"input must be a regular non-symlink file: {candidate}")
    with candidate.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _no_duplicate_json_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    output: dict[str, Any] = {}
    for key, value in pairs:
        if key in output:
            raise ContractError(f"artifact JSON has duplicate key: {key}")
        output[key] = value
    return output


def _load_raw_json_file(path: str | Path) -> tuple[dict[str, Any], str]:
    candidate = Path(path)
    if candidate.is_symlink() or not candidate.is_file():
        raise ContractError(f"input must be a regular non-symlink file: {candidate}")
    raw = candidate.read_bytes()
    try:
        parsed = json.loads(raw.decode("utf-8"), object_pairs_hook=_no_duplicate_json_pairs)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ContractError("artifact file is not UTF-8 JSON") from exc
    if not isinstance(parsed, dict):
        raise ContractError("artifact file root must be a JSON object")
    return parsed, hashlib.sha256(raw).hexdigest()


def _load_and_match_raw_json_file(
    path: str | Path, expected: dict[str, Any], *, label: str
) -> tuple[dict[str, Any], str]:
    parsed, file_sha256 = _load_raw_json_file(path)
    if parsed != expected:
        raise ContractError(
            f"{label} object does not exactly match the supplied in-memory object"
        )
    return parsed, file_sha256


def load_json_with_file_sha(path: str | Path) -> tuple[dict[str, Any], str]:
    parsed, file_sha256 = _load_raw_json_file(path)
    return require_dict(parsed, "artifact"), file_sha256


def load_request_set_artifact_file(
    path: str | Path,
) -> tuple[dict[str, Any], str]:
    request_set, raw_file_sha256 = load_json_with_file_sha(path)
    request_set = validate_request_set(request_set)
    return request_set, raw_file_sha256


def load_execution_authority_artifact_file(
    path: str | Path,
) -> tuple[dict[str, Any], str]:
    authorization, raw_file_sha256 = load_json_with_file_sha(path)
    return require_dict(
        authorization, "search execution authorization"
    ), raw_file_sha256


def load_execution_authority_contexts(
    paths: list[str | Path], expected_file_sha256s: list[str]
) -> dict[str, dict[str, Any]]:
    if len(paths) != len(expected_file_sha256s):
        raise ContractError(
            "execution authorization artifacts and external SHA-256 pins must "
            "have equal counts"
        )
    contexts: dict[str, dict[str, Any]] = {}
    for path, expected_sha256 in zip(paths, expected_file_sha256s, strict=True):
        authorization, actual_sha256 = load_execution_authority_artifact_file(path)
        authorization_id = require_string(
            authorization.get("authorization_id"),
            "execution authorization.authorization_id",
        )
        if authorization_id in contexts:
            raise ContractError("execution authorization artifacts must be unique")
        contexts[authorization_id] = {
            "authorization": authorization,
            "expected_execution_authority_sha256": ensure_sha256(
                expected_sha256, "expected execution authorization file SHA-256"
            ),
            "execution_authority_file_sha256": actual_sha256,
        }
    return contexts


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


def require_positive_int(value: Any, label: str, maximum: int) -> int:
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or not 0 < value <= maximum
    ):
        raise ContractError(f"{label} must be an integer in [1, {maximum}]")
    return value


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def require_timestamp(value: Any, label: str) -> str:
    text = require_string(value, label)
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ContractError(f"{label} must be an ISO-8601 timestamp") from exc
    if parsed.tzinfo is None:
        raise ContractError(f"{label} must include a timezone")
    if parsed.astimezone(timezone.utc) > utc_now() + MAX_FUTURE_SKEW:
        raise ContractError(
            f"{label} must not be more than {int(MAX_FUTURE_SKEW.total_seconds())} seconds in the future"
        )
    return text


def ensure_sha256(value: Any, label: str) -> str:
    text = require_string(value, label)
    if not SHA256_RE.fullmatch(text):
        raise ContractError(f"{label} must be 64 lowercase hex characters")
    return text


def canonical_request_set_digest(document: dict[str, Any]) -> str:
    normalized = {
        key: value
        for key, value in document.items()
        if key not in {"request_set_id", "request_set_digest"}
    }
    return sha256_json(normalized)


def validate_network_ref(
    value: Any,
    label: str,
    network_id: str | None = None,
    network_snapshot_sha256: str | None = None,
) -> dict[str, str]:
    ref = require_dict(value, label)
    network_id_in_ref = require_string(ref.get("network_id"), f"{label}.network_id")
    require_string(ref.get("snapshot_id"), f"{label}.snapshot_id")
    sha256 = ensure_sha256(ref.get("sha256"), f"{label}.sha256")
    ref["sha256"] = sha256
    if network_id is not None and network_id_in_ref != network_id:
        raise ContractError(
            f"{label}.network_id is inconsistent with parent network_id"
        )
    if network_snapshot_sha256 is not None and sha256 != network_snapshot_sha256:
        raise ContractError(
            f"{label}.sha256 is inconsistent with parent network_snapshot_sha256"
        )
    return ref


def validate_appraisal_origin(value: Any) -> dict[str, Any]:
    origin = require_dict(value, "request.appraisal_origin")
    expected_fields = {
        "schema",
        "appraisal_set_ref",
        "need_set_ref",
        "need_ref",
        "challenge_refs",
        "claim_ref",
        "appraisal_ref",
    }
    if set(origin) != expected_fields:
        raise ContractError(
            "request.appraisal_origin field set must be exactly "
            f"{sorted(expected_fields)}"
        )
    if origin.get("schema") != APPRAISAL_ORIGIN_SCHEMA:
        raise ContractError(
            f"request.appraisal_origin.schema must equal {APPRAISAL_ORIGIN_SCHEMA}"
        )

    closed_refs = {
        "appraisal_set_ref": {"appraisal_set_id", "appraisal_set_digest"},
        "need_set_ref": {"need_set_id", "need_set_digest"},
        "need_ref": {"need_id", "need_digest", "route"},
        "claim_ref": {"claim_id", "claim_digest"},
        "appraisal_ref": {"appraisal_id", "appraisal_digest"},
    }
    for field, expected in closed_refs.items():
        ref = require_dict(origin.get(field), f"request.appraisal_origin.{field}")
        if set(ref) != expected:
            raise ContractError(
                f"request.appraisal_origin.{field} field set must be exactly "
                f"{sorted(expected)}"
            )
        for key in expected:
            require_string(ref.get(key), f"request.appraisal_origin.{field}.{key}")
        for key in expected:
            if key.endswith("_digest"):
                ensure_sha256(ref.get(key), f"request.appraisal_origin.{field}.{key}")
    if origin["need_ref"]["route"] != "scholar_discovery":
        raise ContractError(
            "request.appraisal_origin.need_ref.route must equal scholar_discovery"
        )

    challenge_refs = origin.get("challenge_refs")
    if not isinstance(challenge_refs, list) or not challenge_refs:
        raise ContractError(
            "request.appraisal_origin.challenge_refs must be a non-empty list"
        )
    normalized_refs: list[tuple[str, str]] = []
    for index, raw_ref in enumerate(challenge_refs):
        ref = require_dict(raw_ref, f"request.appraisal_origin.challenge_refs[{index}]")
        if set(ref) != {"challenge_id", "challenge_digest"}:
            raise ContractError(
                "request.appraisal_origin.challenge_refs entries must contain exactly "
                "challenge_id and challenge_digest"
            )
        challenge_id = require_string(
            ref.get("challenge_id"),
            f"request.appraisal_origin.challenge_refs[{index}].challenge_id",
        )
        challenge_digest = ensure_sha256(
            ref.get("challenge_digest"),
            f"request.appraisal_origin.challenge_refs[{index}].challenge_digest",
        )
        normalized_refs.append((challenge_id, challenge_digest))
    if normalized_refs != sorted(set(normalized_refs)):
        raise ContractError(
            "request.appraisal_origin.challenge_refs must be sorted and unique"
        )
    return origin


def require_string_list(value: Any, label: str) -> list[str]:
    if not isinstance(value, list) or any(
        not isinstance(item, str) or not item.strip() for item in value
    ):
        raise ContractError(f"{label} must be a list of non-empty strings")
    return [item.strip() for item in value]


def normalize_provider(value: Any, label: str) -> str:
    provider = require_string(value, label).lower()
    if provider in AUTOMATIC_PROVIDERS | {GOOGLE_PROVIDER}:
        return provider
    raise ContractError(f"{label} is unknown: {provider}")


def validate_request(value: Any) -> dict[str, Any]:
    request = require_dict(value, "request")
    if request.get("schema") != REQUEST_SCHEMA:
        raise ContractError(f"request.schema must equal {REQUEST_SCHEMA}")

    request_id = require_string(request.get("request_id"), "request.request_id")
    require_string(request.get("paper_need"), "request.paper_need")
    if request.get("intent") not in INTENTS:
        raise ContractError(f"request.intent must be one of {sorted(INTENTS)}")
    if request.get("effort") not in EFFORTS:
        raise ContractError(f"request.effort must be one of {sorted(EFFORTS)}")

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
        require_string_list(seeds.get(key), f"request.seeds.{key}")

    routes = require_dict(request.get("routes"), "request.routes")
    raw_automatic = require_string_list(
        routes.get("automatic"), "request.routes.automatic"
    )
    automatic = [
        normalize_provider(provider, f"request.routes.automatic[{index}]")
        for index, provider in enumerate(raw_automatic)
    ]
    request["routes"]["automatic"] = list(dict.fromkeys(automatic))
    if GOOGLE_PROVIDER in request["routes"]["automatic"]:
        raise ContractError("Google Scholar must never be an automatic provider")

    raw_google = require_string(
        routes.get("google_scholar"), "request.routes.google_scholar"
    ).lower()
    if raw_google not in GOOGLE_POLICIES:
        raise ContractError(
            f"request.routes.google_scholar must be one of {sorted(GOOGLE_POLICIES)}"
        )
    request["routes"]["google_scholar"] = raw_google

    budgets = require_dict(request.get("budgets"), "request.budgets")
    require_positive_int(budgets.get("max_rounds"), "request.budgets.max_rounds", 20)
    require_positive_int(budgets.get("max_queries"), "request.budgets.max_queries", 100)
    require_positive_int(
        budgets.get("max_candidates"), "request.budgets.max_candidates", 5000
    )
    require_positive_int(
        budgets.get("timeout_seconds"), "request.budgets.timeout_seconds", 86400
    )

    query_seeds = request.get("query_seeds")
    if not isinstance(query_seeds, list) or not query_seeds:
        raise ContractError("request.query_seeds must be a non-empty list")
    for index, seed in enumerate(query_seeds):
        item = require_dict(seed, f"request.query_seeds[{index}]")
        if item.get("objective") not in QUERY_OBJECTIVES:
            raise ContractError(
                f"request.query_seeds[{index}].objective must be supported"
            )
        require_string(item.get("query"), f"request.query_seeds[{index}].query")

    require_timestamp(request.get("as_of"), "request.as_of")

    if "gap_ref" in request and "gap_hypothesis_id" not in request:
        gap_ref = require_dict(request["gap_ref"], "request.gap_ref")
        request["gap_hypothesis_id"] = require_string(
            gap_ref.get("gap_id"), "request.gap_ref.gap_id"
        )
    else:
        require_string(request.get("gap_hypothesis_id"), "request.gap_hypothesis_id")

    if "understanding_gap" in request:
        _validate_understanding_gap_request_binding(request)
    has_appraisal_origin = "appraisal_origin" in request
    if has_appraisal_origin:
        validate_appraisal_origin(request["appraisal_origin"])
        if not request_id.startswith(APPRAISAL_REQUEST_ID_PREFIX):
            raise ContractError(
                "request with appraisal_origin must use the ASDR- appraisal request ID"
            )
    elif request_id.startswith(APPRAISAL_REQUEST_ID_PREFIX):
        raise ContractError(
            "request without appraisal_origin must not use the ASDR- appraisal request ID"
        )

    # keep backward-compat for non-network fields if present
    if "schema_version" in request:
        if request["schema_version"] != REQUEST_SET_SCHEMA_VERSION:
            raise ContractError("request.schema_version is unsupported")
    return request


def _normalized_query_text(parts: list[str]) -> str:
    return " ".join(" ".join(parts).split())


def _assert_safe_gap_query_text(value: str, label: str) -> None:
    if any(pattern.search(value) for pattern in SENSITIVE_GAP_QUERY_PATTERNS):
        raise ContractError(
            f"{label} must not expose secrets, private paths, keys, or internal IDs"
        )


def _understanding_gap_query_seeds(gap: dict[str, Any]) -> list[dict[str, str]]:
    gap_type = gap["gap_type"]
    vocabulary = PAPER_UNDERSTANDING_GAP_QUERY_TERMS.get(gap_type)
    if vocabulary is None:
        raise ContractError(f"unsupported PaperUnderstanding gap type: {gap_type}")
    search_terms = gap["search_terms"]
    base_terms = [*search_terms["must"], *search_terms["should"]]
    queries = [
        {
            "objective": objective,
            "query": _normalized_query_text([*base_terms, vocabulary[objective]]),
        }
        for objective in ("confirm", "refute")
    ]
    for index, query in enumerate(queries):
        _assert_safe_gap_query_text(
            query["query"], f"PaperUnderstanding gap query_seeds[{index}].query"
        )
    return queries


def _validate_understanding_gap_request_binding(
    request: dict[str, Any],
) -> dict[str, Any]:
    gap = _validate_understanding_gap_contract(request.get("understanding_gap"))
    expected_request_keys = {
        "schema",
        "request_id",
        "paper_need",
        "intent",
        "effort",
        "criteria",
        "metadata_filters",
        "seeds",
        "routes",
        "budgets",
        "query_seeds",
        "as_of",
        "gap_ref",
        "gap_hypothesis_id",
        "understanding_gap",
    }
    if set(request) != expected_request_keys:
        raise ContractError(
            "a PaperUnderstanding gap request must contain only the bounded "
            "discovery fields and understanding_gap"
        )
    gap_ref = require_dict(request.get("gap_ref"), "request.gap_ref")
    if set(gap_ref) != {"gap_id", "gap_digest", "gap_type"}:
        raise ContractError(
            "a PaperUnderstanding request gap_ref must contain exactly "
            "gap_id, gap_digest, and gap_type"
        )
    if gap_ref != {
        "gap_id": gap["gap_id"],
        "gap_digest": gap["gap_digest"],
        "gap_type": gap["gap_type"],
    }:
        raise ContractError("request.gap_ref does not match understanding_gap")
    if request.get("gap_hypothesis_id") != gap["gap_id"]:
        raise ContractError(
            "request.gap_hypothesis_id does not match understanding_gap.gap_id"
        )
    if request.get("paper_need") != gap["question"]:
        raise ContractError(
            "request.paper_need must preserve understanding_gap.question exactly"
        )
    _assert_safe_gap_query_text(request["paper_need"], "request.paper_need")
    if request.get("criteria") != gap["search_terms"]:
        raise ContractError(
            "request.criteria must preserve understanding_gap.search_terms exactly"
        )
    for group, values in request["criteria"].items():
        for index, value in enumerate(values):
            _assert_safe_gap_query_text(value, f"request.criteria.{group}[{index}]")
    if request.get("query_seeds") != _understanding_gap_query_seeds(gap):
        raise ContractError(
            "request.query_seeds must be the canonical targeted queries for the gap"
        )
    return request


def compile_understanding_gap_request(
    value: Any,
    *,
    as_of: str,
    google_scholar_policy: str = "manual_optional",
) -> dict[str, Any]:
    """Compile a validated missing-detail observation into discovery-only queries."""
    gap = copy.deepcopy(_validate_understanding_gap_contract(value))
    if google_scholar_policy not in GOOGLE_POLICIES:
        raise ContractError(
            f"google_scholar_policy must be one of {sorted(GOOGLE_POLICIES)}"
        )
    request = {
        "schema": REQUEST_SCHEMA,
        "request_id": f"SDR-{gap['gap_digest'][:16]}",
        "paper_need": gap["question"],
        "intent": "topic_set",
        "effort": "diligent",
        "criteria": copy.deepcopy(gap["search_terms"]),
        "metadata_filters": {
            "years": {},
            "authors": [],
            "venues": [],
            "languages": [],
            "work_types": [],
            "open_access": None,
        },
        "seeds": {
            "doi": [],
            "arxiv": [],
            "pmid": [],
            "openalex": [],
            "semantic_scholar": [],
            "titles": [],
        },
        "routes": {
            "automatic": ["openalex", "crossref", "semantic_scholar"],
            "google_scholar": google_scholar_policy,
        },
        "budgets": {
            "max_rounds": 2,
            "max_queries": 12,
            "max_candidates": 100,
            "timeout_seconds": 900,
        },
        "query_seeds": _understanding_gap_query_seeds(gap),
        "as_of": as_of,
        "gap_ref": {
            "gap_id": gap["gap_id"],
            "gap_digest": gap["gap_digest"],
            "gap_type": gap["gap_type"],
        },
        "gap_hypothesis_id": gap["gap_id"],
        "understanding_gap": gap,
    }
    return validate_request(request)


def _topic_defaults(value: Any, label: str) -> dict[str, Any]:
    if value is None:
        value = {}
    result = copy.deepcopy(require_dict(value, label))
    result.setdefault("years", {"from": None, "to": None})
    for key in ("authors", "venues", "languages", "work_types"):
        result.setdefault(key, [])
    result.setdefault("open_access", None)
    return result


def _seed_defaults(value: Any, label: str) -> dict[str, Any]:
    if value is None:
        value = {}
    result = copy.deepcopy(require_dict(value, label))
    for key in ("doi", "arxiv", "pmid", "openalex", "semantic_scholar", "titles"):
        result.setdefault(key, [])
    return result


def _budget_defaults(value: Any, label: str) -> dict[str, Any]:
    if value is None:
        value = {}
    result = copy.deepcopy(require_dict(value, label))
    result.setdefault("max_rounds", 2)
    result.setdefault("max_queries", 12)
    result.setdefault("max_candidates", 100)
    result.setdefault("timeout_seconds", 900)
    return result


def _assert_topic_query_is_semantic(
    query: str,
    criteria_must: list[str],
    label: str,
) -> None:
    _assert_safe_gap_query_text(query, label)
    if any(pattern.search(query) for pattern in STRUCTURAL_PLACEHOLDER_PATTERNS):
        raise ContractError(
            f"{label} contains a structural placeholder instead of domain terms"
        )
    normalized = " ".join(query.casefold().split())
    anchors = [" ".join(term.casefold().split()) for term in criteria_must]
    if not anchors or not any(anchor in normalized for anchor in anchors):
        raise ContractError(
            f"{label} must contain at least one criteria.must domain anchor"
        )
    if len(normalized.split()) < 3:
        raise ContractError(f"{label} is too broad for targeted discovery")


def compile_topic_need_set(value: Any) -> dict[str, Any]:
    """Compile domain-grounded topic needs into one validated request set."""
    document = copy.deepcopy(require_dict(value, "topic_need_set"))
    if document.get("schema") != TOPIC_NEED_SET_SCHEMA:
        raise ContractError(f"topic_need_set.schema must equal {TOPIC_NEED_SET_SCHEMA}")
    if (
        document.get("schema_version", REQUEST_SET_SCHEMA_VERSION)
        != REQUEST_SET_SCHEMA_VERSION
    ):
        raise ContractError("topic_need_set.schema_version is unsupported")
    require_string(document.get("topic_id"), "topic_need_set.topic_id")
    require_string(document.get("question"), "topic_need_set.question")
    as_of = require_timestamp(document.get("as_of"), "topic_need_set.as_of")
    google_policy = require_string(
        document.get("google_scholar_policy", "manual_optional"),
        "topic_need_set.google_scholar_policy",
    ).lower()
    if google_policy not in GOOGLE_POLICIES:
        raise ContractError(
            f"topic_need_set.google_scholar_policy must be one of {sorted(GOOGLE_POLICIES)}"
        )
    automatic = [
        normalize_provider(provider, f"topic_need_set.automatic_providers[{index}]")
        for index, provider in enumerate(
            require_string_list(
                document.get("automatic_providers", ["crossref", "semantic_scholar"]),
                "topic_need_set.automatic_providers",
            )
        )
    ]
    if GOOGLE_PROVIDER in automatic:
        raise ContractError("Google Scholar must never be an automatic provider")

    network_ref_value = validate_network_ref(
        document.get("network_ref"), "topic_need_set.network_ref"
    )
    needs = document.get("needs")
    if not isinstance(needs, list) or not needs:
        raise ContractError("topic_need_set.needs must be a non-empty list")
    if len(needs) > 50:
        raise ContractError("topic_need_set.needs exceeds the bounded limit of 50")

    requests: list[dict[str, Any]] = []
    seen_gap_ids: set[str] = set()
    for index, raw_need in enumerate(needs):
        label = f"topic_need_set.needs[{index}]"
        need = require_dict(raw_need, label)
        gap_id = require_string(need.get("gap_id"), f"{label}.gap_id")
        if gap_id in seen_gap_ids:
            raise ContractError(f"duplicate topic need gap_id: {gap_id}")
        seen_gap_ids.add(gap_id)
        if gap_id.startswith("derived:missing-dimension:"):
            raise ContractError(
                f"{label}.gap_id is structural and must be semantically seeded first"
            )
        paper_need = require_string(need.get("paper_need"), f"{label}.paper_need")
        _assert_safe_gap_query_text(paper_need, f"{label}.paper_need")
        criteria = copy.deepcopy(
            require_dict(need.get("criteria"), f"{label}.criteria")
        )
        for group in ("must", "should", "must_not"):
            criteria[group] = require_string_list(
                criteria.get(group, []), f"{label}.criteria.{group}"
            )
            for term_index, term in enumerate(criteria[group]):
                _assert_safe_gap_query_text(
                    term, f"{label}.criteria.{group}[{term_index}]"
                )
        if not criteria["must"]:
            raise ContractError(f"{label}.criteria.must must contain a domain anchor")

        query_seeds = copy.deepcopy(need.get("query_seeds"))
        if not isinstance(query_seeds, list) or not query_seeds:
            raise ContractError(f"{label}.query_seeds must be a non-empty list")
        objectives: set[str] = set()
        for query_index, seed in enumerate(query_seeds):
            seed = require_dict(seed, f"{label}.query_seeds[{query_index}]")
            objective = require_string(
                seed.get("objective"), f"{label}.query_seeds[{query_index}].objective"
            )
            if objective not in QUERY_OBJECTIVES:
                raise ContractError(
                    f"{label}.query_seeds[{query_index}].objective is unsupported"
                )
            query = require_string(
                seed.get("query"), f"{label}.query_seeds[{query_index}].query"
            )
            _assert_topic_query_is_semantic(
                query,
                criteria["must"],
                f"{label}.query_seeds[{query_index}].query",
            )
            objectives.add(objective)
        if not {"confirm", "refute"}.issubset(objectives):
            raise ContractError(f"{label}.query_seeds must include confirm and refute")

        stable_need = {
            "gap_id": gap_id,
            "paper_need": paper_need,
            "criteria": criteria,
            "query_seeds": query_seeds,
        }
        request_id = "SDR-TOPIC-" + sha256_json(stable_need)[:16]
        request = {
            "schema": REQUEST_SCHEMA,
            "request_id": request_id,
            "paper_need": paper_need,
            "intent": need.get("intent", "topic_set"),
            "effort": need.get("effort", "diligent"),
            "criteria": criteria,
            "metadata_filters": _topic_defaults(
                need.get("metadata_filters"), f"{label}.metadata_filters"
            ),
            "seeds": _seed_defaults(need.get("seeds"), f"{label}.seeds"),
            "routes": {
                "automatic": list(dict.fromkeys(automatic)),
                "google_scholar": google_policy,
            },
            "budgets": _budget_defaults(need.get("budgets"), f"{label}.budgets"),
            "query_seeds": query_seeds,
            "as_of": as_of,
            "gap_ref": {
                "gap_id": gap_id,
                "network_id": network_ref_value["network_id"],
            },
            "gap_hypothesis_id": gap_id,
        }
        requests.append(validate_request(request))

    request_set = {
        "schema": REQUEST_SET_SCHEMA,
        "schema_version": REQUEST_SET_SCHEMA_VERSION,
        "request_set_id": "",
        "request_set_digest": "",
        "requests": requests,
        "network_id": network_ref_value["network_id"],
        "network_snapshot_sha256": network_ref_value["sha256"],
        "network_ref": network_ref_value,
        "generated_at": as_of,
    }
    digest = canonical_request_set_digest(request_set)
    request_set["request_set_digest"] = digest
    request_set["request_set_id"] = f"request-set-{digest[:16]}"
    return validate_request_set(request_set)


def _provider_preflight_check(provider: str) -> dict[str, Any]:
    configured = True
    limitations: list[str] = []
    if provider == "openalex" and not os.getenv(OPENALEX_API_KEY_ENV, "").strip():
        configured = False
        limitations = ["missing_api_key"]
    elif (
        provider == "semantic_scholar"
        and not os.getenv(SEMANTIC_SCHOLAR_API_KEY_ENV, "").strip()
    ):
        limitations = ["anonymous_rate_limit_risk"]
    elif provider not in EXECUTABLE_PROVIDERS:
        configured = False
        limitations = ["provider_not_implemented"]
    return {
        "provider": provider,
        "configured": configured,
        "limitations": limitations,
    }


def build_preflight(value: Any) -> dict[str, Any]:
    request_set = validate_request_set(copy.deepcopy(value))
    providers = sorted(
        {
            provider
            for request in request_set["requests"]
            for provider in request["routes"]["automatic"]
        }
    )
    checks = [_provider_preflight_check(provider) for provider in providers]
    checks_by_provider = {row["provider"]: row for row in checks}
    google_policies = sorted(
        {request["routes"]["google_scholar"] for request in request_set["requests"]}
    )
    provider_coverage: list[dict[str, Any]] = []
    for request in request_set["requests"]:
        request_checks = [
            copy.deepcopy(checks_by_provider[provider])
            for provider in request["routes"]["automatic"]
        ]
        ready_count = sum(1 for row in request_checks if row["configured"])
        manual_policy = request["routes"]["google_scholar"]
        any_route_ready = ready_count > 0 or manual_policy != "disabled"
        if not any_route_ready:
            status = "blocked"
        elif ready_count != len(request_checks) or manual_policy == "manual_required":
            status = "partial"
        else:
            status = "ready"
        provider_coverage.append(
            {
                "request_id": request["request_id"],
                "automatic_providers": request_checks,
                "google_scholar_policy": manual_policy,
                "status": status,
            }
        )
    statuses = {row["status"] for row in provider_coverage}
    overall_status = (
        "blocked"
        if "blocked" in statuses
        else "partial"
        if "partial" in statuses
        else "ready"
    )
    return {
        "schema": PREFLIGHT_SCHEMA,
        "schema_version": REQUEST_SET_SCHEMA_VERSION,
        "request_set_id": request_set["request_set_id"],
        "request_set_digest": request_set["request_set_digest"],
        "request_projection": [
            {
                "request_id": request["request_id"],
                "request_digest": sha256_json(request),
                "queries": copy.deepcopy(request["query_seeds"]),
            }
            for request in request_set["requests"]
        ],
        "automatic_providers": checks,
        "provider_coverage": provider_coverage,
        "google_scholar": {
            "execution": "user_manual_export",
            "policies": google_policies,
            "automatic": False,
            "manual_artifact_required": any(
                policy == "manual_required" for policy in google_policies
            ),
        },
        "ready_automatic_provider_count": sum(
            1 for check in checks if check["configured"]
        ),
        "status": overall_status,
    }


def validate_preflight(value: Any, request_set_value: Any) -> dict[str, Any]:
    document = copy.deepcopy(require_dict(value, "scholar discovery preflight"))
    expected = build_preflight(request_set_value)
    if document != expected:
        raise ContractError(
            "ScholarDiscoveryPreflight/v1 is not the owner-replayed exact "
            "request/query/provider/status projection"
        )
    return document


def _validate_reviewed_request_projection(
    request_set: dict[str, Any], network_ref_value: dict[str, str]
) -> None:
    projection_fields = {
        "reviewed_selection_ref",
        "selected_hypothesis_ids",
        "selected_hypotheses_sha256",
        "selected_hypotheses",
        "google_scholar_policy",
        "request_profile",
    }
    present = projection_fields.intersection(request_set)
    origin_profile_present = any(
        isinstance(request, dict) and "appraisal_origin" in request
        for request in request_set.get("requests", [])
    )
    strict_projection_present = bool(
        present
        or origin_profile_present
        or request_set.get("schema") == APPRAISAL_REQUEST_SET_SCHEMA
    )
    if not strict_projection_present:
        return
    if present != projection_fields:
        raise ContractError(
            "reviewed request set must contain the complete selected projection fields"
        )
    module = _load_network_gap_module()
    required = {
        "validate_hypotheses",
        "selected_hypotheses_for_emission",
        "reviewed_selection_ref_for_emission",
        "project_scholar_request",
        "validate_request_projection_profile",
    }
    if any(not callable(getattr(module, name, None)) for name in required):
        raise ContractError(
            "network-gap-discovery lacks reviewed request projection replay"
        )
    try:
        selected_document = module.validate_hypotheses(
            copy.deepcopy(request_set["selected_hypotheses"]), None
        )
        selected_rows = module.selected_hypotheses_for_emission(selected_document)
        appraisal_projection = "appraisal_compilation" in selected_document or any(
            "appraisal_origin" in row for row in selected_rows
        )
        if (
            appraisal_projection
            and request_set.get("schema") != APPRAISAL_REQUEST_SET_SCHEMA
        ):
            raise ContractError(
                "appraisal projection requires AppraisalScholarDiscoveryRequestSet/v1"
            )
        if (
            request_set.get("schema") == APPRAISAL_REQUEST_SET_SCHEMA
            and not appraisal_projection
        ):
            raise ContractError(
                "appraisal request-set schema requires an appraisal selection projection"
            )
        selected_ids = [row["hypothesis_id"] for row in selected_rows]
        reviewed_ref = module.reviewed_selection_ref_for_emission(
            selected_document, selected_ids, None
        )
        policy = require_string(
            request_set["google_scholar_policy"],
            "request_set.google_scholar_policy",
        )
        profile = module.validate_request_projection_profile(
            copy.deepcopy(request_set["request_profile"])
        )
        expected_requests = [
            module.project_scholar_request(
                row, selected_document, network_ref_value, policy, profile
            )
            for row in selected_rows
        ]
    except ValueError as exc:
        raise ContractError(f"invalid reviewed request projection: {exc}") from exc
    if request_set["reviewed_selection_ref"] != reviewed_ref:
        raise ContractError(
            "request_set.reviewed_selection_ref does not match selected hypotheses"
        )
    if request_set["selected_hypothesis_ids"] != selected_ids:
        raise ContractError(
            "request_set.selected_hypothesis_ids must exactly match selected hypotheses"
        )
    selected_digest = ensure_sha256(
        request_set["selected_hypotheses_sha256"],
        "request_set.selected_hypotheses_sha256",
    )
    if selected_digest != sha256_json(selected_document):
        raise ContractError(
            "request_set.selected_hypotheses_sha256 does not bind selected hypotheses"
        )
    if selected_document.get("network_ref") != network_ref_value:
        raise ContractError(
            "request_set selected hypotheses network_ref does not match request set"
        )
    if request_set["requests"] != expected_requests:
        raise ContractError(
            "request_set.requests are not the exact owner-replayed selected projection"
        )


def validate_request_set(value: Any) -> dict[str, Any]:
    request_set = require_dict(value, "request_set")
    if request_set.get("schema") not in {
        REQUEST_SET_SCHEMA,
        APPRAISAL_REQUEST_SET_SCHEMA,
    }:
        raise ContractError(
            "request_set.schema must be a supported generic or appraisal request-set schema"
        )

    if "schema_version" not in request_set:
        request_set["schema_version"] = REQUEST_SET_SCHEMA_VERSION
    if request_set["schema_version"] != REQUEST_SET_SCHEMA_VERSION:
        raise ContractError("request_set.schema_version is unsupported")

    requests = request_set.get("requests")
    if not isinstance(requests, list) or not requests:
        raise ContractError("request_set.requests must be a non-empty list")

    validated_requests = [validate_request(item) for item in requests]
    request_set["requests"] = validated_requests
    local_request_ids = [request["request_id"] for request in validated_requests]
    if len(local_request_ids) != len(set(local_request_ids)):
        raise ContractError(
            "request_set.requests must contain unique request_id values"
        )

    is_appraisal_set = request_set["schema"] == APPRAISAL_REQUEST_SET_SCHEMA
    for request in validated_requests:
        has_appraisal_origin = "appraisal_origin" in request
        if is_appraisal_set and not has_appraisal_origin:
            raise ContractError(
                "appraisal request set requires appraisal_origin on every request"
            )
        if not is_appraisal_set and has_appraisal_origin:
            raise ContractError("generic request set must not contain appraisal_origin")

    request_set["request_set_id"] = require_string(
        request_set.get("request_set_id"), "request_set.request_set_id"
    )
    request_set["request_set_digest"] = ensure_sha256(
        request_set.get("request_set_digest"), "request_set.request_set_digest"
    )
    request_set["network_ref"] = validate_network_ref(
        request_set.get("network_ref"),
        "request_set.network_ref",
        request_set.get("network_id"),
        request_set.get("network_snapshot_sha256"),
    )
    request_set_id = request_set["request_set_id"]
    request_set_digest = request_set["request_set_digest"]
    expected_request_set_id = f"request-set-{request_set_digest[:16]}"
    if request_set_id != expected_request_set_id:
        raise ContractError("request_set.request_set_id is invalid")

    if request_set_digest != canonical_request_set_digest(request_set):
        raise ContractError("request_set.request_set_digest is invalid")

    if "network_id" in request_set:
        require_string(request_set.get("network_id"), "request_set.network_id")
    if "network_snapshot_sha256" in request_set:
        ensure_sha256(
            request_set["network_snapshot_sha256"],
            "request_set.network_snapshot_sha256",
        )
    if "generated_at" in request_set:
        require_timestamp(request_set.get("generated_at"), "request_set.generated_at")
    _validate_reviewed_request_projection(request_set, request_set["network_ref"])
    return request_set


def validate_appraisal_request_set(value: Any) -> dict[str, Any]:
    request_set = validate_request_set(value)
    if request_set["schema"] != APPRAISAL_REQUEST_SET_SCHEMA:
        raise ContractError(
            "appraisal execution requires AppraisalScholarDiscoveryRequestSet/v1"
        )
    return request_set


def canonical_search_execution_authorization_digest(
    document: dict[str, Any],
) -> str:
    normalized = copy.deepcopy(document)
    normalized["authorization_digest"] = ""
    return sha256_json(normalized)


def canonical_search_execution_authorization_file_sha256(value: Any) -> str:
    document = require_dict(value, "search execution authorization")
    return hashlib.sha256(canonical_bytes(document) + b"\n").hexdigest()


def canonical_request_set_file_sha256(request_set_value: Any) -> str:
    request_set = validate_request_set(copy.deepcopy(request_set_value))
    return hashlib.sha256(canonical_bytes(request_set) + b"\n").hexdigest()


def _execution_request_set_binding(
    request_set: dict[str, Any], request_set_file_sha256: str
) -> dict[str, Any]:
    file_sha256 = ensure_sha256(
        request_set_file_sha256,
        "execution authorization.request_set_file_sha256",
    )
    return {
        "request_set_file_sha256": file_sha256,
        "request_set_content_sha256": sha256_json(request_set),
        "request_set_schema": request_set["schema"],
        "request_set_ref": {
            "request_set_id": request_set["request_set_id"],
            "request_set_digest": request_set["request_set_digest"],
        },
        "request_set_profile": {
            "schema_version": request_set["schema_version"],
            "google_scholar_policy": request_set.get("google_scholar_policy"),
            "request_projection_profile": copy.deepcopy(
                request_set.get("request_profile")
            ),
            "ordered_execution_profiles": [
                {
                    "request_id": request["request_id"],
                    "intent": request["intent"],
                    "effort": request["effort"],
                    "routes": copy.deepcopy(request["routes"]),
                    "budgets": copy.deepcopy(request["budgets"]),
                }
                for request in request_set["requests"]
            ],
        },
        "ordered_requests": [
            {
                "request_id": request["request_id"],
                "request_digest": sha256_json(request),
                "queries": copy.deepcopy(request["query_seeds"]),
            }
            for request in request_set["requests"]
        ],
    }


def _execution_authorization_seed(document: dict[str, Any]) -> dict[str, Any]:
    return {
        "request_set_binding": copy.deepcopy(document["request_set_binding"]),
        "reviewer_context": copy.deepcopy(document["reviewer_context"]),
        "decision": document["decision"],
    }


def authorize_request_set(
    request_set_value: Any,
    *,
    reviewer_id: str,
    reviewer_role: str,
    reviewed_at: str,
    independent_reviewer_attested: bool,
    request_set_file: str | Path,
    request_set_file_sha256: str | None = None,
) -> dict[str, Any]:
    request_set = validate_request_set(copy.deepcopy(request_set_value))
    _, file_sha256 = _load_and_match_raw_json_file(
        request_set_file,
        request_set,
        label="request_set",
    )
    if request_set_file_sha256 is not None:
        if request_set_file_sha256 != file_sha256:
            raise ContractError(
                "request-set SHA-256 does not match the loaded request-set file"
            )
    require_string(reviewer_id, "execution authorization.reviewer_id")
    require_string(reviewer_role, "execution authorization.reviewer_role")
    require_timestamp(reviewed_at, "execution authorization.reviewed_at")
    if independent_reviewer_attested is not True:
        raise ContractError(
            "execution authorization requires an independent reviewer attestation"
        )
    document = {
        "schema": SEARCH_EXECUTION_AUTHORIZATION_SCHEMA,
        "authorization_id": "",
        "authorization_digest": "",
        "request_set_binding": _execution_request_set_binding(request_set, file_sha256),
        "reviewer_context": {
            "reviewer_id": reviewer_id,
            "reviewer_role": reviewer_role,
            "reviewed_at": reviewed_at,
            "independent_from_request_builder": True,
        },
        "decision": "approved",
    }
    document["authorization_id"] = (
        SEARCH_EXECUTION_AUTHORIZATION_ID_PREFIX
        + sha256_json(_execution_authorization_seed(document))[:16]
    )
    document["authorization_digest"] = canonical_search_execution_authorization_digest(
        document
    )
    return validate_search_execution_authorization(
        document,
        request_set,
        request_set_file_sha256=file_sha256,
    )


def validate_search_execution_authorization(
    value: Any,
    request_set_value: Any,
    *,
    expected_execution_authority_sha256: str | None = None,
    execution_authority_file_sha256: str | None = None,
    request_set_file_sha256: str | None = None,
) -> dict[str, Any]:
    document = copy.deepcopy(require_dict(value, "search execution authorization"))
    expected_fields = {
        "schema",
        "authorization_id",
        "authorization_digest",
        "request_set_binding",
        "reviewer_context",
        "decision",
    }
    if set(document) != expected_fields:
        raise ContractError(
            "search execution authorization field set must be exactly "
            f"{sorted(expected_fields)}"
        )
    if document.get("schema") != SEARCH_EXECUTION_AUTHORIZATION_SCHEMA:
        raise ContractError(
            "search execution authorization.schema must equal "
            f"{SEARCH_EXECUTION_AUTHORIZATION_SCHEMA}"
        )
    if document.get("decision") != "approved":
        raise ContractError("search execution authorization.decision must be approved")
    context = require_dict(
        document.get("reviewer_context"),
        "search execution authorization.reviewer_context",
    )
    if set(context) != {
        "reviewer_id",
        "reviewer_role",
        "reviewed_at",
        "independent_from_request_builder",
    }:
        raise ContractError(
            "search execution authorization reviewer_context field set is invalid"
        )
    require_string(context.get("reviewer_id"), "execution authorization.reviewer_id")
    require_string(
        context.get("reviewer_role"), "execution authorization.reviewer_role"
    )
    require_timestamp(context.get("reviewed_at"), "execution authorization.reviewed_at")
    if context.get("independent_from_request_builder") is not True:
        raise ContractError(
            "search execution authorization reviewer must be independent"
        )

    request_set = validate_request_set(copy.deepcopy(request_set_value))
    if request_set_file_sha256 is None:
        raise ContractError(
            "search execution authorization validation requires raw request-set file "
            "SHA-256"
        )
    file_sha256 = ensure_sha256(
        request_set_file_sha256, "execution authorization.request_set_file_sha256"
    )
    expected_binding = _execution_request_set_binding(request_set, file_sha256)
    if document.get("request_set_binding") != expected_binding:
        raise ContractError(
            "search execution authorization is not the owner-replayed exact request-set binding"
        )
    expected_id = (
        SEARCH_EXECUTION_AUTHORIZATION_ID_PREFIX
        + sha256_json(_execution_authorization_seed(document))[:16]
    )
    if document.get("authorization_id") != expected_id:
        raise ContractError(
            "search execution authorization.authorization_id is invalid"
        )
    digest = ensure_sha256(
        document.get("authorization_digest"),
        "search execution authorization.authorization_digest",
    )
    if digest != canonical_search_execution_authorization_digest(document):
        raise ContractError(
            "search execution authorization.authorization_digest is invalid"
        )
    if expected_execution_authority_sha256 is not None:
        expected_file_sha256 = ensure_sha256(
            expected_execution_authority_sha256,
            "expected_execution_authority_sha256",
        )
        if execution_authority_file_sha256 is None:
            raise ContractError(
                "external execution authorization pin validation requires the "
                "actual authorization file SHA-256"
            )
        actual_file_sha256 = ensure_sha256(
            execution_authority_file_sha256,
            "execution_authority_file_sha256",
        )
        if actual_file_sha256 != expected_file_sha256:
            raise ContractError(
                "actual search execution authorization file SHA-256 is outside "
                "the caller-provided external trust boundary"
            )
    return document


def scholar_url(query: str, filters: dict[str, Any]) -> str:
    params: dict[str, Any] = {"q": query}
    years = filters.get("years", {})
    if years.get("from") is not None:
        params["as_ylo"] = years["from"]
    if years.get("to") is not None:
        params["as_yhi"] = years["to"]
    return "https://scholar.google.com/scholar?" + urllib.parse.urlencode(params)


def _normalize_endpoint(url: Any, label: str) -> str:
    text = require_string(url, label)
    parsed = urllib.parse.urlsplit(text)
    if not parsed.scheme or not parsed.netloc:
        raise ContractError(f"{label} must be a valid absolute HTTP(S) URL")
    if parsed.username or parsed.password:
        raise ContractError(f"{label} must not contain credentials")
    return urllib.parse.urlunsplit(
        (parsed.scheme, parsed.netloc, parsed.path or "", "", "")
    )


def _validate_endpoint_for_provider(endpoint: str, provider: str, label: str) -> str:
    normalized = _normalize_endpoint(endpoint, label)
    allowed = ENDPOINT_WHITELIST.get(provider, normalized)
    if provider == GOOGLE_PROVIDER:
        allowed = ENDPOINT_WHITELIST["google_scholar"]
    if normalized != allowed and not normalized.startswith(f"{allowed}/"):
        raise ContractError(f"{label} is not permitted for provider {provider}")
    return normalized


def _scan_forbidden_keys(value: Any, label: str) -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str):
                raise ContractError(f"{label} keys must be strings")
            if key.strip().lower() in SEARCH_EVENT_FORBIDDEN_FIELDS:
                raise ContractError(f"{label} contains forbidden key '{key}'")
            _scan_forbidden_keys(item, f"{label}.{key}")
        return
    if isinstance(value, list):
        for index, item in enumerate(value):
            _scan_forbidden_keys(item, f"{label}[{index}]")


def _contains_credential_parameter(keys: list[str]) -> None:
    credential_keys = {
        "token",
        "access_token",
        "api_key",
        "apikey",
        "authorization",
        "cookie",
        "password",
        "secret",
        "session",
    }
    for key in keys:
        if key.strip().lower() in credential_keys:
            raise ContractError(f"{key!r} is a credential-bearing parameter")


def _scan_search_event_credentials(
    label: str, provider: str, endpoint: str, redacted_request: dict[str, Any]
) -> None:
    parsed = urllib.parse.urlsplit(endpoint)

    credential_query_keys = [
        name.lower() for name in urllib.parse.parse_qs(parsed.query).keys()
    ]
    _contains_credential_parameter(credential_query_keys)

    redacted_query = redacted_request.get("query")
    if isinstance(redacted_query, str):
        redacted_query_keys = set(urllib.parse.parse_qs(redacted_query).keys())
        _contains_credential_parameter(list(redacted_query_keys))


def _expected_query_ids(
    request: dict[str, Any], max_queries: int | None = None
) -> set[str]:
    request_digest = sha256_json(request)
    routes = request["routes"]
    provider_order = request["routes"]["automatic"]
    query_ids: set[str] = set()
    autonomous_count = 0

    for seed_index, seed in enumerate(request["query_seeds"], start=1):
        for provider in provider_order:
            if max_queries is not None and autonomous_count >= max_queries:
                break
            identity = {
                "request_digest": request_digest,
                "seed_index": seed_index,
                "objective": seed["objective"],
                "provider": provider,
                "query": seed["query"],
            }
            query_ids.add("query-" + sha256_json(identity)[:16])
            autonomous_count += 1

        if routes["google_scholar"] != "disabled":
            identity = {
                "request_digest": request_digest,
                "seed_index": seed_index,
                "objective": seed["objective"],
                "provider": GOOGLE_PROVIDER,
                "query": seed["query"],
            }
            query_ids.add("query-" + sha256_json(identity)[:16])

    return query_ids


def _build_plan(request: dict[str, Any]) -> dict[str, Any]:
    request_digest = sha256_json(request)
    routes = request["routes"]
    provider_order = request["routes"]["automatic"]
    max_queries = request["budgets"]["max_queries"]
    queries: list[dict[str, Any]] = []
    autonomous_count = 0
    autonomous_covered: set[int] = set()

    for seed_index, seed in enumerate(request["query_seeds"], start=1):
        for provider in provider_order:
            if autonomous_count >= max_queries:
                break
            identity = {
                "request_digest": request_digest,
                "seed_index": seed_index,
                "objective": seed["objective"],
                "provider": provider,
                "query": seed["query"],
            }
            row: dict[str, Any] = {
                "query_id": "query-" + sha256_json(identity)[:16],
                "seed_index": seed_index,
                "objective": seed["objective"],
                "provider": provider,
                "execution": DOCUMENTED_EXECUTION,
                "query": seed["query"],
                "filters": request["metadata_filters"],
            }
            row["endpoint_hint"] = ENDPOINT_HINTS[provider]
            queries.append(row)
            autonomous_count += 1
            autonomous_covered.add(seed_index)

        if routes["google_scholar"] != "disabled":
            identity = {
                "request_digest": request_digest,
                "seed_index": seed_index,
                "objective": seed["objective"],
                "provider": GOOGLE_PROVIDER,
                "query": seed["query"],
            }
            queries.append(
                {
                    "query_id": "query-" + sha256_json(identity)[:16],
                    "seed_index": seed_index,
                    "objective": seed["objective"],
                    "provider": GOOGLE_PROVIDER,
                    "execution": SCHOLAR_EXECUTION,
                    "query": seed["query"],
                    "filters": request["metadata_filters"],
                    "search_url": scholar_url(
                        seed["query"], request["metadata_filters"]
                    ),
                    "policy": routes["google_scholar"],
                }
            )

    missing_autonomous_seeds = (
        set(range(1, len(request["query_seeds"]) + 1)) - autonomous_covered
    )
    return {
        "schema": PLAN_SCHEMA,
        "request_id": request["request_id"],
        "request_digest": request_digest,
        "coverage_promise": "bounded_targeted_discovery",
        "compiled_as_of": request["as_of"],
        "google_scholar_policy": routes["google_scholar"],
        "queries": queries,
        "truncation": {
            "max_queries": max_queries,
            "query_budget_reached": bool(missing_autonomous_seeds),
            "unplanned_seed_indices": sorted(missing_autonomous_seeds),
        },
    }


def compile_plan(request_value: Any) -> dict[str, Any]:
    request = validate_request(request_value)
    return validate_plan(_build_plan(request), request)


def validate_plan(value: Any, request: dict[str, Any] | None = None) -> dict[str, Any]:
    plan = require_dict(value, "plan")
    if plan.get("schema") != PLAN_SCHEMA:
        raise ContractError(f"plan.schema must equal {PLAN_SCHEMA}")

    request_id = require_string(plan.get("request_id"), "plan.request_id")
    digest = require_string(plan.get("request_digest"), "plan.request_digest")
    if not SHA256_RE.fullmatch(digest):
        raise ContractError("plan.request_digest must be 64 lowercase hex characters")

    if request is not None:
        canonical_request = validate_request(request)
        expected_plan = _build_plan(canonical_request)
        expected_digest = expected_plan["request_digest"]
        if request_id != canonical_request["request_id"]:
            raise ContractError("plan.request_id does not match validated request")
        if digest != expected_digest:
            raise ContractError("plan.request_digest does not match validated request")
        if canonical_bytes(plan) != canonical_bytes(expected_plan):
            raise ContractError(
                "plan fields (queries/filters/provider/policy) do not match canonical rebuild"
            )
        plan = expected_plan

    if plan.get("google_scholar_policy") not in GOOGLE_POLICIES:
        raise ContractError("plan.google_scholar_policy is invalid")

    queries = plan.get("queries")
    if not isinstance(queries, list) or not queries:
        raise ContractError("plan.queries must be a non-empty list")

    seen: set[str] = set()
    for index, query in enumerate(queries):
        item = require_dict(query, f"plan.queries[{index}]")
        query_id = require_string(
            item.get("query_id"), f"plan.queries[{index}].query_id"
        )
        if query_id in seen:
            raise ContractError(f"duplicate query_id: {query_id}")
        seen.add(query_id)

        provider = normalize_provider(
            item.get("provider"), f"plan.queries[{index}].provider"
        )
        execution = require_string(
            item.get("execution"), f"plan.queries[{index}].execution"
        )
        if provider == GOOGLE_PROVIDER:
            if execution != SCHOLAR_EXECUTION:
                raise ContractError(
                    "Google Scholar plan entries must be user_manual_export"
                )
            if item.get("policy") not in GOOGLE_POLICIES:
                raise ContractError(
                    "Google Scholar plan entries must include a valid policy"
                )
        else:
            if execution != DOCUMENTED_EXECUTION:
                raise ContractError(
                    "automatic provider plan entries must be documented_api"
                )
            if provider not in ENDPOINT_HINTS:
                raise ContractError("plan provider is unsupported")
            endpoint_hint = _validate_endpoint_for_provider(
                require_string(
                    item.get("endpoint_hint"), f"plan.queries[{index}].endpoint_hint"
                ),
                provider,
                f"plan.queries[{index}].endpoint_hint",
            )
            item["endpoint_hint"] = endpoint_hint

        require_string(item.get("query"), f"plan.queries[{index}].query")
    return plan


def validate_candidate(value: Any, label: str) -> dict[str, Any]:
    candidate = require_dict(value, label)
    _scan_forbidden_keys(candidate, label)

    require_string(candidate.get("title"), f"{label}.title")
    require_string_list(candidate.get("authors", []), f"{label}.authors")

    year = candidate.get("year")
    if year is not None and (
        isinstance(year, bool)
        or not isinstance(year, int)
        or year < 1000
        or year > 3000
    ):
        raise ContractError(f"{label}.year is invalid")

    if candidate.get("venue") is not None and not isinstance(
        candidate.get("venue"), str
    ):
        raise ContractError(f"{label}.venue must be a string or null")

    identifiers = require_dict(candidate.get("identifiers", {}), f"{label}.identifiers")
    for key, identifier in identifiers.items():
        require_string(key, f"{label}.identifiers key")
        require_string(identifier, f"{label}.identifiers.{key}")
        if key.casefold() == "doi":
            normalized = normalize_identifier(key, identifier)
            if not DOI_RE.fullmatch(normalized):
                raise ContractError(f"{label}.identifiers.{key} has invalid format")
            identifiers[key] = normalized
        elif not IDENTIFIER_RE.fullmatch(identifier):
            raise ContractError(f"{label}.identifiers.{key} has invalid format")

    relations = candidate.get("relations")
    if relations is not None:
        if not isinstance(relations, list):
            raise ContractError(f"{label}.relations must be a list")
        normalized_relations: list[str] = []
        for relation_index, relation in enumerate(relations):
            if isinstance(relation, str):
                rel = relation.strip()
                if not rel:
                    raise ContractError(
                        f"{label}.relations[{relation_index}] must be non-empty"
                    )
                normalized_relations.append(rel.lower())
                continue
            if not isinstance(relation, dict):
                raise ContractError(
                    f"{label}.relations[{relation_index}] must be string or object"
                )
            rel_id = relation.get("id")
            if not isinstance(rel_id, str) or not rel_id.strip():
                raise ContractError(
                    f"{label}.relations[{relation_index}].id must be a non-empty string"
                )
            rel_kind = relation.get("kind", "relation")
            if not isinstance(rel_kind, str) or not rel_kind.strip():
                raise ContractError(
                    f"{label}.relations[{relation_index}].kind must be a non-empty string"
                )
            normalized_relations.append(f"{rel_kind.lower()}:{rel_id.strip()}")
        candidate["relations"] = sorted(set(normalized_relations))

    if "work_family_hint" in candidate and candidate["work_family_hint"] is not None:
        if not isinstance(candidate["work_family_hint"], str):
            raise ContractError("candidate.work_family_hint must be a string")
        candidate["work_family_hint"] = candidate["work_family_hint"].strip()
        if not candidate["work_family_hint"]:
            raise ContractError("candidate.work_family_hint must be non-empty")

    if "manifestation_id" in candidate and candidate["manifestation_id"] is not None:
        if (
            not isinstance(candidate["manifestation_id"], str)
            or not candidate["manifestation_id"].strip()
        ):
            raise ContractError("candidate.manifestation_id must be a non-empty string")

    require_string(candidate.get("work_type"), f"{label}.work_type")
    if candidate.get("publication_status") not in PUBLICATION_STATUSES:
        raise ContractError(f"{label}.publication_status is invalid")

    if candidate.get("access_level") not in ACCESS_LEVELS:
        raise ContractError(f"{label}.access_level is invalid")

    rank = candidate.get("native_rank")
    if isinstance(rank, bool) or not isinstance(rank, int) or rank < 1:
        raise ContractError(f"{label}.native_rank must be positive")

    score = candidate.get("native_score")
    if score is not None and (
        isinstance(score, bool) or not isinstance(score, (int, float))
    ):
        raise ContractError(f"{label}.native_score must be numeric or null")

    screening = require_dict(candidate.get("screening"), f"{label}.screening")
    if screening.get("decision") not in SCREENING_DECISIONS:
        raise ContractError(f"{label}.screening.decision is invalid")
    require_string(screening.get("reason"), f"{label}.screening.reason")
    return candidate


def validate_search_event(
    event: dict[str, Any], label: str, provider: str | None = None
) -> dict[str, Any]:
    event = require_dict(event, label)
    _scan_forbidden_keys(event, label)
    redacted = event.get("redacted_request")
    if not isinstance(redacted, dict):
        raise ContractError(f"{label}.redacted_request must be an object")
    if not redacted:
        raise ContractError(f"{label}.redacted_request must be a non-empty object")

    _scan_forbidden_keys(redacted, f"{label}.redacted_request")

    unexpected = set(event.keys()) - (
        SEARCH_EVENT_REQUIRED_FIELDS | SEARCH_EVENT_OPTIONAL_FIELDS
    )
    if unexpected:
        raise ContractError(f"{label} has unsupported keys: {sorted(unexpected)}")

    for field in SEARCH_EVENT_REQUIRED_FIELDS:
        if field not in event:
            raise ContractError(f"{label}.{field} is required")

    raw_endpoint = require_string(event.get("endpoint"), f"{label}.endpoint")
    event["endpoint"] = _validate_endpoint_for_provider(
        raw_endpoint,
        provider or "",
        f"{label}.endpoint",
    )
    redacted_query = redacted.get("query")
    if not isinstance(redacted_query, str) or not redacted_query.strip():
        raise ContractError(f"{label}.redacted_request.query must be non-empty")

    if not isinstance(event.get("limitations"), list):
        raise ContractError(f"{label}.limitations must be a list")
    if not isinstance(event.get("page_or_cursor"), str):
        raise ContractError(f"{label}.page_or_cursor must be a string")
    for field_name in ("expected_total", "retrieved"):
        value = event.get(field_name)
        if not isinstance(value, int) or value < 0:
            raise ContractError(f"{label}.{field_name} must be a non-negative integer")
    if not isinstance(event.get("truncated"), bool):
        raise ContractError(f"{label}.truncated must be boolean")
    if not isinstance(event.get("response_sha256"), str) or not SHA256_RE.fullmatch(
        event["response_sha256"]
    ):
        raise ContractError(f"{label}.response_sha256 must be 64 lowercase hex chars")
    rejected_candidate_count = event.get("rejected_candidate_count", 0)
    if not isinstance(rejected_candidate_count, int) or rejected_candidate_count < 0:
        raise ContractError(
            f"{label}.rejected_candidate_count must be a non-negative integer"
        )
    if provider in {GOOGLE_PROVIDER} and event.get("page_or_cursor") not in {
        "manual",
        "*",
        "1",
    }:
        raise ContractError(f"{label}.page_or_cursor is invalid for Google Scholar")

    if not isinstance(event.get("limitations"), list):
        raise ContractError(f"{label}.limitations must be a list")

    redacted_provider = redacted.get("provider")
    if redacted_provider is not None and not isinstance(redacted_provider, str):
        raise ContractError(f"{label}.redacted_request.provider must be a string")

    redacted_query = redacted.get("query")
    if not isinstance(redacted_query, str):
        raise ContractError(f"{label}.redacted_request.query must be a string")
    if not redacted_query.strip():
        raise ContractError(f"{label}.redacted_request.query must be non-empty")

    if provider:
        _scan_search_event_credentials(label, provider, raw_endpoint, redacted)
    return event


def validate_batch(
    value: Any, plan_queries: dict[str, dict[str, Any]] | None = None
) -> dict[str, Any]:
    batch = require_dict(value, "batch")
    if batch.get("schema") != BATCH_SCHEMA:
        raise ContractError(f"batch.schema must equal {BATCH_SCHEMA}")

    digest = require_string(batch.get("request_digest"), "batch.request_digest")
    if not SHA256_RE.fullmatch(digest):
        raise ContractError("batch.request_digest must be 64 lowercase hex")

    query_id = require_string(batch.get("query_id"), "batch.query_id")
    provider = normalize_provider(batch.get("provider"), "batch.provider")
    execution = require_string(batch.get("execution"), "batch.execution")
    status = require_string(batch.get("status"), "batch.status")
    if status == "succeeded":
        status = "success"
    if status not in BATCH_STATUSES:
        raise ContractError(f"batch.status must be one of {sorted(BATCH_STATUSES)}")
    batch["status"] = status
    if execution not in {DOCUMENTED_EXECUTION, SCHOLAR_EXECUTION}:
        raise ContractError(
            "batch.execution must be documented_api or user_manual_export"
        )

    require_timestamp(batch.get("accessed_at"), "batch.accessed_at")
    require_string(batch.get("query"), "batch.query")

    event = validate_search_event(
        require_dict(batch.get("search_event"), "batch.search_event"),
        "batch.search_event",
        provider,
    )
    if provider != GOOGLE_PROVIDER:
        if event.get("endpoint") != _validate_endpoint_for_provider(
            event["endpoint"], provider, "batch.search_event.endpoint"
        ):
            event["endpoint"] = _validate_endpoint_for_provider(
                event["endpoint"], provider, "batch.search_event.endpoint"
            )
    else:
        _validate_endpoint_for_provider(
            event["endpoint"], GOOGLE_PROVIDER, "batch.search_event.endpoint"
        )

    if provider == GOOGLE_PROVIDER:
        if execution != SCHOLAR_EXECUTION:
            raise ContractError("Google Scholar batches must be user_manual_export")
        artifact_origin = event.get("artifact_origin")
        if batch["status"] == "blocked":
            if artifact_origin not in GOOGLE_NOT_PROVIDED_ORIGINS:
                raise ContractError(
                    "Google manual search events must carry not_provided_manual_* origin"
                )
            if artifact_origin == "not_provided_manual_optional":
                if plan_queries is not None:
                    policy = plan_queries.get(query_id, {}).get("policy")
                    if policy != "manual_optional":
                        raise ContractError(
                            "not_provided_manual_optional only allowed for manual_optional policy"
                        )
            elif artifact_origin == "not_provided_manual_required":
                if plan_queries is not None:
                    policy = plan_queries.get(query_id, {}).get("policy")
                    if policy != "manual_required":
                        raise ContractError(
                            "not_provided_manual_required only allowed for manual_required policy"
                        )
        elif artifact_origin in GOOGLE_NOT_PROVIDED_ORIGINS:
            raise ContractError("Google Scholar placeholder origin is blocked-only")
        elif (
            artifact_origin is not None
            and artifact_origin != GOOGLE_USER_SUPPLIED_ORIGIN
        ):
            raise ContractError(
                f"Google manual search events support only '{GOOGLE_USER_SUPPLIED_ORIGIN}' when not blocked"
            )
    elif execution != DOCUMENTED_EXECUTION:
        raise ContractError("automatic provider batches must be documented_api")

    if provider == GOOGLE_PROVIDER:
        batch["provider"] = GOOGLE_PROVIDER
    if plan_queries is not None:
        planned = plan_queries.get(query_id)
        if planned is None:
            raise ContractError(f"batch query_id was not planned: {query_id}")
        for field in ("provider", "execution", "query"):
            if batch.get(field) != planned.get(field):
                raise ContractError(f"batch.{field} does not match plan")

    candidates = batch.get("candidates")
    if not isinstance(candidates, list):
        raise ContractError("batch.candidates must be a list")
    for index, candidate in enumerate(candidates):
        validate_candidate(candidate, f"batch.candidates[{index}]")

    return batch


def normalize_text(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).casefold()
    normalized = re.sub(r"[^\w]+", " ", normalized, flags=re.UNICODE)
    return " ".join(normalized.split())


def _normalize_arxiv_identifier(value: str, keep_version: bool = True) -> str:
    text = value.strip()
    text = re.sub(r"^(?:arxiv:|https?://arxiv\.org/abs/)", "", text, flags=re.I)
    if not keep_version:
        text = ARXIV_V2_SUFFIX_RE.sub("", text)
    return text.casefold()


def normalize_identifier(kind: str, value: str) -> str:
    text = value.strip()
    if kind.casefold() == "doi":
        text = re.sub(r"^https?://(?:dx\.)?doi\.org/", "", text, flags=re.I)
        text = re.sub(r"^doi:\s*", "", text, flags=re.I)
    if kind.casefold() == "arxiv":
        text = _normalize_arxiv_identifier(text, keep_version=True)
    return text.casefold()


def _first_author_key(candidates: list[str]) -> str:
    return normalize_text(candidates[0]) if candidates else ""


def _collect_identifier_value(
    identifiers: dict[str, str],
    kind: str,
    value: Any,
) -> bool:
    if not isinstance(value, str):
        return False

    normalized = (
        _normalize_arxiv_identifier(value, keep_version=True)
        if kind == "arxiv"
        else normalize_identifier(kind, value)
    )
    if kind == "doi":
        if not DOI_RE.fullmatch(normalized):
            return True
    elif not IDENTIFIER_RE.fullmatch(normalized):
        return True

    identifiers[kind] = normalized
    return False


def _family_weak_signature(candidate: dict[str, Any], fallback: str) -> str:
    title = normalize_text(candidate["title"])
    authors = candidate.get("authors", [])
    year = candidate.get("year")
    first_author = _first_author_key(authors) if isinstance(authors, list) else ""
    if title and first_author and year:
        return f"weak:{sha256_json([title, first_author, year])}"
    return f"weak:{sha256_json([fallback])}"


def family_signatures(
    candidate: dict[str, Any], fallback: str
) -> tuple[list[str], str]:
    identifiers = candidate.get("identifiers", {})
    signatures: set[str] = set()

    for kind in ("doi", "pmid", "semantic_scholar", "openalex"):
        identifier = identifiers.get(kind)
        if identifier:
            signatures.add(f"{kind}:{normalize_identifier(kind, identifier)}")

    arxiv_identifier = identifiers.get("arxiv")
    if arxiv_identifier:
        signatures.add(
            f"arxiv:{_normalize_arxiv_identifier(arxiv_identifier, keep_version=False)}"
        )

    for relation in normalize_relation_ids(candidate):
        signatures.add(f"relation:{relation}")

    signatures.add(_family_weak_signature(candidate, fallback))

    if candidate.get("work_family_hint"):
        signatures.add(f"hint:{normalize_text(candidate['work_family_hint'])}")

    sorted_signatures = sorted(signatures)
    confidence = "low"
    if any(
        signature.startswith(
            ("doi:", "pmid:", "semantic_scholar:", "openalex:", "arxiv:")
        )
        for signature in sorted_signatures
    ):
        confidence = "high"
    return sorted_signatures, confidence


def _collect_identifiers_from_value(value: Any, identifiers: dict[str, str]) -> bool:
    rejected = False
    if isinstance(value, str):
        lowered = value.lower()
        if "arxiv.org/abs/" in lowered:
            rejected = rejected or _collect_identifier_value(
                identifiers, "arxiv", value
            )
            return rejected
        if "doi.org/" in lowered:
            rejected = rejected or _collect_identifier_value(identifiers, "doi", value)
            return rejected
        if "openalex.org/" in lowered:
            rejected = rejected or _collect_identifier_value(
                identifiers, "openalex", value
            )
            return rejected
    if isinstance(value, dict):
        for val in value.values():
            if _collect_identifiers_from_value(val, identifiers):
                rejected = True
    elif isinstance(value, list):
        for item in value:
            if _collect_identifiers_from_value(item, identifiers):
                rejected = True
    return rejected


def _extract_openalex_identifiers(item: dict[str, Any]) -> tuple[dict[str, str], int]:
    identifiers: dict[str, str] = {}
    rejected_candidates = 0

    def _mark_rejected() -> None:
        nonlocal rejected_candidates
        rejected_candidates += 1

    def add_from_mapping(
        mapping: Any, kind_hints: dict[str, str] | None = None
    ) -> None:
        if not isinstance(mapping, dict):
            return
        for key, value in mapping.items():
            if not isinstance(key, str) or not isinstance(value, str):
                continue
            normalized_key = key.strip().lower()
            normalized_value = value.strip()
            if not normalized_value:
                continue
            if kind_hints and normalized_key in kind_hints:
                if _collect_identifier_value(
                    identifiers, kind_hints[normalized_key], normalized_value
                ):
                    _mark_rejected()
                continue
            if "doi" in normalized_key:
                if _collect_identifier_value(identifiers, "doi", normalized_value):
                    _mark_rejected()
            elif "pmid" in normalized_key:
                if _collect_identifier_value(identifiers, "pmid", normalized_value):
                    _mark_rejected()
            elif "openalex" in normalized_key:
                if _collect_identifier_value(identifiers, "openalex", normalized_value):
                    _mark_rejected()
            elif "arxiv" in normalized_key:
                if _collect_identifier_value(identifiers, "arxiv", normalized_value):
                    _mark_rejected()
            elif normalized_key in {
                "semantic_scholar",
                "semantic scholar",
                "semanticscholar",
                "s2",
            }:
                if _collect_identifier_value(
                    identifiers, "semantic_scholar", normalized_value
                ):
                    _mark_rejected()

            if _collect_identifiers_from_value(normalized_value, identifiers):
                _mark_rejected()

    add_from_mapping(
        item.get("ids"),
        {
            "doi": "doi",
            "pmid": "pmid",
            "openalex": "openalex",
            "openalexid": "openalex",
        },
    )
    add_from_mapping(
        item.get("primary_location"), {"source_id": "openalex", "id": "openalex"}
    )
    for location in item.get("locations") or []:
        if isinstance(location, dict):
            add_from_mapping(
                location.get("source"), {"source_id": "openalex", "id": "openalex"}
            )
            add_from_mapping(location, {"landing_page_url": "openalex"})
            add_from_mapping(
                location.get("source", {}).get("ids")
                if isinstance(location.get("source"), dict)
                else None
            )
    for venue in item.get("alternative_host_venues") or []:
        if isinstance(venue, dict):
            add_from_mapping(venue.get("ids"), {"openalex": "openalex"})
            if _collect_identifiers_from_value(venue.get("id"), identifiers):
                _mark_rejected()
    relations = item.get("relation")
    if isinstance(relations, dict):
        for related in relations.values():
            if _collect_identifiers_from_value(related, identifiers):
                _mark_rejected()
    for rel in item.get("link", []) if isinstance(item.get("link"), list) else []:
        if _collect_identifiers_from_value(rel, identifiers):
            _mark_rejected()

    return identifiers, min(rejected_candidates, 1)


def _extract_crossref_identifiers(item: dict[str, Any]) -> tuple[dict[str, str], int]:
    identifiers: dict[str, str] = {}
    rejected_candidates = 0
    direct = item.get("DOI")
    if isinstance(direct, str):
        if _collect_identifier_value(identifiers, "doi", direct):
            rejected_candidates += 1

    for relation in (
        (item.get("relation") or {}).values()
        if isinstance(item.get("relation"), dict)
        else []
    ):
        if isinstance(relation, dict):
            relation = [relation]
        if isinstance(relation, list):
            for related in relation:
                if _collect_identifiers_from_value(related, identifiers):
                    rejected_candidates += 1

    for relation in item.get("relation", {}).values():
        if _collect_identifiers_from_value(relation, identifiers):
            rejected_candidates += 1

    for link in item.get("link", []) if isinstance(item.get("link"), list) else []:
        if _collect_identifiers_from_value(link, identifiers):
            rejected_candidates += 1

    for alternative in (
        item.get("alternative-id", [])
        if isinstance(item.get("alternative-id"), list)
        else []
    ):
        if isinstance(alternative, str) and alternative:
            if _collect_identifier_value(identifiers, "doi", alternative):
                rejected_candidates += 1

    if item.get("URL") and isinstance(item["URL"], str):
        if _collect_identifiers_from_value(item["URL"], identifiers):
            rejected_candidates += 1

    if item.get("id") and isinstance(item["id"], str):
        if _collect_identifiers_from_value(item["id"], identifiers):
            rejected_candidates += 1

    return identifiers, min(rejected_candidates, 1)


def _extract_semantic_scholar_identifiers(
    item: dict[str, Any],
) -> tuple[dict[str, str], int]:
    identifiers: dict[str, str] = {}
    rejected_candidates = 0

    direct = item.get("paperId")
    if isinstance(direct, str):
        if _collect_identifier_value(identifiers, "semantic_scholar", direct):
            rejected_candidates += 1

    external_ids = item.get("externalIds")
    if isinstance(external_ids, dict):
        if doi := external_ids.get("DOI"):
            if isinstance(doi, str):
                if _collect_identifier_value(identifiers, "doi", doi):
                    rejected_candidates += 1
        if pmid := external_ids.get("PMID"):
            if isinstance(pmid, str):
                if _collect_identifier_value(identifiers, "pmid", pmid):
                    rejected_candidates += 1
        if arxiv := external_ids.get("ArXiv"):
            if isinstance(arxiv, str):
                if _collect_identifier_value(identifiers, "arxiv", arxiv):
                    rejected_candidates += 1

    for key in ("url", "publicationVenue"):
        if _collect_identifiers_from_value(item.get(key), identifiers):
            rejected_candidates += 1

    return identifiers, min(rejected_candidates, 1)


def normalize_relation_ids(candidate: dict[str, Any]) -> list[str]:
    relations = candidate.get("relations") or []
    normalized: list[str] = []
    for relation in relations:
        relation_value = relation if isinstance(relation, str) else relation
        if isinstance(relation_value, str):
            normalized.append(normalize_text(relation_value))
    return sorted(set(normalized))


def choose_field(values: list[Any]) -> Any:
    encoded = [
        json.dumps(value, ensure_ascii=False, sort_keys=True) for value in values
    ]
    winner, _ = sorted(Counter(encoded).items(), key=lambda item: (-item[1], item[0]))[
        0
    ]
    return json.loads(winner)


def compute_manifestation_id(candidate: dict[str, Any], fallback: str) -> str:
    if "manifestation_id" in candidate and candidate.get("manifestation_id"):
        return "man-" + str(candidate["manifestation_id"]).strip()

    identifiers = candidate.get("identifiers", {})
    for kind in ("doi", "pmid", "arxiv", "semantic_scholar", "openalex"):
        identifier = identifiers.get(kind)
        if identifier:
            if kind == "arxiv":
                return f"man-arxiv:{normalize_identifier('arxiv', identifier)}"
            return f"man-{kind}:{normalize_identifier(kind, identifier)}"

    return f"man-{fallback[:16]}"


def compute_family_key(candidate: dict[str, Any], fallback: str) -> tuple[str, str]:
    work_family_hint = candidate.get("work_family_hint")
    if work_family_hint:
        return f"hint:{normalize_text(work_family_hint)}", "high"

    relation_ids = normalize_relation_ids(candidate)
    if relation_ids:
        return f"relation:{sha256_json(relation_ids)}", "high"

    identifiers = candidate.get("identifiers", {})
    for kind in ("doi", "pmid", "semantic_scholar", "openalex"):
        identifier = identifiers.get(kind)
        if identifier:
            return f"{kind}:{normalize_identifier(kind, identifier)}", "high"
    arxiv_identifier = identifiers.get("arxiv")
    if arxiv_identifier:
        return (
            f"arxiv:{_normalize_arxiv_identifier(arxiv_identifier, keep_version=False)}",
            "high",
        )

    signatures, confidence = family_signatures(candidate, fallback)
    return signatures[0], confidence


def _is_manual_export_blocking_failure(
    batch: dict[str, Any], plan: dict[str, Any]
) -> bool:
    if batch["provider"] != GOOGLE_PROVIDER:
        return batch["status"] in {"blocked", "failed", "partial", "budget_exhausted"}

    if batch["status"] != "blocked":
        return False

    artifact_origin = batch["search_event"].get("artifact_origin")
    if artifact_origin == "not_provided_manual_optional":
        return False
    if artifact_origin == "not_provided_manual_required":
        return True
    return plan.get("google_scholar_policy") == "manual_required"


def build_result(
    request_value: Any, plan_value: Any, batch_values: list[Any]
) -> dict[str, Any]:
    request = validate_request(request_value)
    plan = validate_plan(plan_value, request)
    plan_queries = {query["query_id"]: query for query in plan["queries"]}
    request_digest = sha256_json(request)

    batches: list[dict[str, Any]] = []
    seen_query_ids: set[str] = set()
    for value in batch_values:
        batch = validate_batch(value, plan_queries)
        if batch["request_digest"] != request_digest:
            raise ContractError("batch is not bound to request")
        if batch["query_id"] in seen_query_ids:
            raise ContractError(f"duplicate batch for {batch['query_id']}")
        seen_query_ids.add(batch["query_id"])
        batches.append(batch)

    order = {query["query_id"]: index for index, query in enumerate(plan["queries"])}
    batches.sort(key=lambda batch: order[batch["query_id"]])

    manifestation_clusters: dict[str, list[dict[str, Any]]] = {}
    for batch in batches:
        ranked_candidates = sorted(
            batch["candidates"], key=lambda item: item["native_rank"]
        )
        for candidate in ranked_candidates:
            fallback = f"{batch['query_id']}:{candidate['native_rank']}"
            manifestation_id = compute_manifestation_id(
                candidate, sha256_json(fallback)
            )
            family_key, _ = compute_family_key(candidate, sha256_json(fallback))
            signature_set, signature_confidence = family_signatures(
                candidate, sha256_json(fallback)
            )
            observation = {
                "batch": batch,
                "candidate": candidate,
                "manifestation_id": manifestation_id,
                "family_key": family_key,
                "family_confidence": signature_confidence,
                "family_signatures": signature_set,
            }
            manifestation_clusters.setdefault(manifestation_id, []).append(observation)

    family_map: dict[str, set[str]] = {}

    class _UnionFind:
        def __init__(self) -> None:
            self.parent: dict[str, str] = {}
            self.size: dict[str, int] = {}

        def add(self, node: str) -> None:
            self.parent.setdefault(node, node)
            self.size.setdefault(node, 1)

        def find(self, node: str) -> str:
            while self.parent[node] != node:
                self.parent[node] = self.parent[self.parent[node]]
                node = self.parent[node]
            return node

        def union(self, left: str, right: str) -> None:
            left_root = self.find(left)
            right_root = self.find(right)
            if left_root == right_root:
                return
            if self.size[left_root] < self.size[right_root]:
                left_root, right_root = right_root, left_root
            self.parent[right_root] = left_root
            self.size[left_root] += self.size[right_root]

    union_find = _UnionFind()
    for manifestation_id in manifestation_clusters:
        union_find.add(manifestation_id)

    signature_to_members: dict[str, list[str]] = {}
    weak_signature_to_members: dict[str, list[str]] = {}
    for manifestation_id, observations in manifestation_clusters.items():
        for observation in observations:
            for signature in observation["family_signatures"]:
                if signature.startswith("weak:"):
                    weak_signature_to_members.setdefault(signature, []).append(
                        manifestation_id
                    )
                else:
                    signature_to_members.setdefault(signature, []).append(
                        manifestation_id
                    )

    for signature, members in signature_to_members.items():
        if len(members) < 2:
            continue
        first_member = members[0]
        for member in members[1:]:
            union_find.union(first_member, member)

    weak_duplicate_families: set[str] = set()
    for members in weak_signature_to_members.values():
        if len(members) < 2:
            continue
        roots = {union_find.find(member) for member in members}
        if len(roots) > 1:
            weak_duplicate_families.update(roots)

    for manifestation_id in manifestation_clusters:
        family_map.setdefault(union_find.find(manifestation_id), set()).add(
            manifestation_id
        )

    root_to_family_id: dict[str, str] = {
        root: "family-" + sha256_json(sorted(manifestation_ids))[:16]
        for root, manifestation_ids in family_map.items()
    }

    weak_duplicate_family_ids = {
        root_to_family_id.get(root)
        for root in weak_duplicate_families
        if root_to_family_id.get(root) is not None
    }

    for root, manifestation_ids in list(family_map.items()):
        family_id = root_to_family_id[root]
        for manifestation_id in manifestation_ids:
            for observation in manifestation_clusters[manifestation_id]:
                observation["family_id"] = family_id

    ranked: list[dict[str, Any]] = []
    for root, manifestation_ids in list(family_map.items()):
        family_id = root_to_family_id[root]
        observations = [
            obs
            for manifestation_id in sorted(manifestation_ids)
            for obs in manifestation_clusters[manifestation_id]
        ]
        fields = (
            "title",
            "authors",
            "year",
            "venue",
            "work_type",
            "publication_status",
        )
        canonical = {
            field: choose_field([obs["candidate"][field] for obs in observations])
            for field in fields
        }
        conflicts: dict[str, list[Any]] = {}
        for field in fields:
            distinct = sorted(
                {
                    json.dumps(
                        obs["candidate"][field], ensure_ascii=False, sort_keys=True
                    )
                    for obs in observations
                }
            )
            if len(distinct) > 1:
                conflicts[field] = [json.loads(item) for item in distinct]

        identifiers: dict[str, str] = {}
        for obs in observations:
            for kind, identifier in obs["candidate"].get("identifiers", {}).items():
                if kind == "arxiv":
                    normalized = _normalize_arxiv_identifier(
                        identifier, keep_version=False
                    )
                else:
                    normalized = normalize_identifier(kind, identifier)
                previous = identifiers.get(kind)
                if previous is not None and previous != normalized:
                    conflicts[f"identifier:{kind}"] = sorted({previous, normalized})
                else:
                    identifiers[kind] = normalized

        provenance = [
            {
                "query_id": obs["batch"]["query_id"],
                "provider": obs["batch"]["provider"],
                "execution": obs["batch"]["execution"],
                "accessed_at": obs["batch"]["accessed_at"],
                "native_rank": obs["candidate"]["native_rank"],
                "native_score": obs["candidate"].get("native_score"),
            }
            for obs in observations
        ]
        unique_ranks = {(row["query_id"], row["native_rank"]) for row in provenance}
        rrf = round(sum(1.0 / (60 + rank) for _, rank in unique_ranks), 12)

        access_level = max(
            (obs["candidate"]["access_level"] for obs in observations),
            key={
                "snippet_only": 0,
                "metadata_only": 1,
                "abstract_only": 2,
                "full_text": 3,
            }.get,
        )

        screenings = [obs["candidate"]["screening"] for obs in observations]
        has_retracted = any(
            obs["candidate"].get("publication_status") in {"retracted", "withdrawn"}
            for obs in observations
        )
        if has_retracted:
            decision = "exclude"
        else:
            decision = max(
                (screening["decision"] for screening in screenings),
                key={"exclude": 0, "unscreened": 1, "maybe": 2, "include": 3}.get,
            )

        flags: list[str] = []
        if has_retracted or canonical["publication_status"] in {
            "retracted",
            "withdrawn",
        }:
            flags.append("retracted_or_withdrawn")
        if canonical["publication_status"] == "preprint":
            flags.append("preprint")
        if access_level in {"metadata_only", "snippet_only"}:
            flags.append("insufficient_for_claim_evidence")
        if len({row["provider"] for row in provenance}) == 1:
            flags.append("single_provider")
        if family_id in weak_duplicate_family_ids:
            flags.append("possible_duplicate")
            flags.append("needs_review")
        if not identifiers:
            flags.append("no_stable_identifier")
        if conflicts:
            flags.append("identity_or_metadata_conflict")

        manifestation_ids = sorted({obs["manifestation_id"] for obs in observations})
        candidate_id = "candidate-" + sha256_json(family_id)[:16]
        quality_flags = sorted(set(flags))

        ranked.append(
            {
                "candidate_id": candidate_id,
                "manifestation_key": family_id,
                "manifestation_ids": manifestation_ids,
                "work_family_id": family_id,
                "work_family_manifestation_count": len(manifestation_ids),
                **canonical,
                "identifiers": identifiers,
                "access_level": access_level,
                "screening": {
                    "decision": decision,
                    "observations": screenings,
                },
                "field_conflicts": conflicts,
                "discovery_provenance": provenance,
                "rrf_score": rrf,
                "quality_flags": quality_flags,
                "discovery_only": True,
                "claim_support_eligible": False,
                "manifestation_count": len(manifestation_ids),
            }
        )

    decision_order = {"include": 0, "maybe": 1, "unscreened": 2, "exclude": 3}
    ranked.sort(
        key=lambda item: (
            decision_order[item["screening"]["decision"]],
            "retracted_or_withdrawn" in item["quality_flags"],
            -item["rrf_score"],
            normalize_text(item["title"]),
            item["candidate_id"],
        )
    )
    max_candidates = request["budgets"]["max_candidates"]
    pre_truncation_count = sum(len(batch["candidates"]) for batch in batches)
    candidate_budget_reached = pre_truncation_count > max_candidates
    ranked = ranked[:max_candidates]
    for index, item in enumerate(ranked, start=1):
        item["rank"] = index

    expected_query_ids = _expected_query_ids(request)
    planned_query_ids = {query["query_id"] for query in plan["queries"]}
    missing = sorted(expected_query_ids - planned_query_ids)

    def batch_incomplete(batch_item: dict[str, Any]) -> bool:
        if batch_item["provider"] == GOOGLE_PROVIDER:
            return _is_manual_export_blocking_failure(batch_item, plan)
        return batch_item["status"] in BATCH_INCOMPLETE_STATUSES

    failures = [
        {
            "query_id": batch["query_id"],
            "provider": batch["provider"],
            "execution": batch["execution"],
            "status": batch["status"],
            "limitations": batch["search_event"].get("limitations", []),
        }
        for batch in batches
        if batch_incomplete(batch)
    ]

    query_budget_reached = bool(expected_query_ids - planned_query_ids)
    unresolved = sorted(planned_query_ids - seen_query_ids)

    any_signal = any(
        (
            batch["status"] in {"success", "partial", "empty", "budget_exhausted"}
            if batch["provider"] != GOOGLE_PROVIDER
            else (
                batch["status"] == "success"
                or (
                    batch["status"] == "blocked"
                    and batch["search_event"].get("artifact_origin")
                    == "not_provided_manual_optional"
                )
            )
        )
        for batch in batches
    )

    if not batches or not any_signal:
        status = "blocked_capability"
    elif query_budget_reached or candidate_budget_reached:
        status = "partial_budget"
    elif failures or unresolved:
        status = "partial_provider"
    else:
        status = "complete_bounded"

    result = {
        "schema": RESULT_SCHEMA,
        "request_id": request["request_id"],
        "request_digest": request_digest,
        "plan_digest": sha256_json(plan),
        "discovery_status": status,
        "coverage_promise": "bounded_targeted_discovery_not_systematic_completeness",
        "as_of": max([batch["accessed_at"] for batch in batches] + [request["as_of"]]),
        "query_plan": plan["queries"],
        "search_events": [
            {
                "query_id": batch["query_id"],
                "provider": batch["provider"],
                "execution": batch["execution"],
                "status": batch["status"],
                "accessed_at": batch["accessed_at"],
                "query": batch["query"],
                "search_event": batch["search_event"],
                "candidate_count": len(batch["candidates"]),
            }
            for batch in batches
        ],
        "paper_clusters": [
            {
                "work_family_id": item["work_family_id"],
                "manifestation_ids": item["manifestation_ids"],
                "candidate_id": item["candidate_id"],
            }
            for item in ranked
        ],
        "ranked_candidates": ranked,
        "exclusions": [
            {
                "candidate_id": item["candidate_id"],
                "reason": (
                    "retracted_or_withdrawn"
                    if "retracted_or_withdrawn" in item["quality_flags"]
                    else "screening_excluded"
                ),
            }
            for item in ranked
            if item["screening"]["decision"] == "exclude"
            or "retracted_or_withdrawn" in item["quality_flags"]
        ],
        "provider_failures": failures,
        "unresolved_query_ids": unresolved,
        "stop_reason": status,
        "limits": {
            "pre_truncation_candidate_count": pre_truncation_count,
            "query_budget_reached": query_budget_reached,
            "candidate_budget_reached": candidate_budget_reached,
            "missing_query_ids": missing,
            "google_scholar_manual_only": True,
        },
    }
    return validate_result(result)


def validate_result(value: Any) -> dict[str, Any]:
    result = require_dict(value, "result")
    if result.get("schema") != RESULT_SCHEMA:
        raise ContractError(f"result.schema must equal {RESULT_SCHEMA}")
    require_string(result.get("request_id"), "result.request_id")
    for field in ("request_digest", "plan_digest"):
        digest = require_string(result.get(field), f"result.{field}")
        if not SHA256_RE.fullmatch(digest):
            raise ContractError(f"result.{field} must be 64 lowercase hex")

    if result.get("discovery_status") not in {
        "complete_bounded",
        "partial_provider",
        "partial_budget",
        "blocked_capability",
    }:
        raise ContractError("result.discovery_status is invalid")

    stop_reason = require_string(result.get("stop_reason"), "result.stop_reason")
    if stop_reason not in {
        "complete_bounded",
        "partial_provider",
        "partial_budget",
        "blocked_capability",
    }:
        raise ContractError("result.stop_reason is invalid")
    if stop_reason != result.get("discovery_status"):
        raise ContractError("result.stop_reason does not match discovery_status")

    candidates = result.get("ranked_candidates")
    if not isinstance(candidates, list):
        raise ContractError("result.ranked_candidates must be a list")

    provider_failures = result.get("provider_failures")
    if not isinstance(provider_failures, list):
        raise ContractError("result.provider_failures must be a list")

    unresolved_query_ids = result.get("unresolved_query_ids")
    if not isinstance(unresolved_query_ids, list):
        raise ContractError("result.unresolved_query_ids must be a list")

    query_plan = result.get("query_plan")
    if not isinstance(query_plan, list):
        raise ContractError("result.query_plan must be a list")
    planned_queries: dict[str, dict[str, Any]] = {}
    for index, query in enumerate(query_plan):
        item = require_dict(query, f"result.query_plan[{index}]")
        query_id = require_string(
            item.get("query_id"), f"result.query_plan[{index}].query_id"
        )
        if query_id in planned_queries:
            raise ContractError("result.query_plan must not repeat query_id")
        provider = normalize_provider(item.get("provider"), f"result.query_plan[{index}].provider")
        execution = require_string(
            item.get("execution"), f"result.query_plan[{index}].execution"
        )
        if provider == GOOGLE_PROVIDER:
            if execution != SCHOLAR_EXECUTION:
                raise ContractError(
                    f"result.query_plan[{index}].execution must be {SCHOLAR_EXECUTION}"
                )
        else:
            if execution != DOCUMENTED_EXECUTION:
                raise ContractError(
                    f"result.query_plan[{index}].execution must be {DOCUMENTED_EXECUTION}"
                )
        planned_queries[query_id] = {
            "provider": provider,
            "execution": execution,
            "query": require_string(
                item.get("query"), f"result.query_plan[{index}].query"
            ),
        }
    planned_id_set = set(planned_queries)

    search_events = result.get("search_events")
    if not isinstance(search_events, list):
        raise ContractError("result.search_events must be a list")
    event_ids: list[str] = []
    incomplete_event_ids: set[str] = set()
    search_event_statuses: dict[str, str] = {}
    incomplete_event_signatures: dict[
        str, tuple[str, str, str, tuple[str, ...]]
    ] = {}
    for index, event in enumerate(search_events):
        item = require_dict(event, f"result.search_events[{index}]")
        query_id = require_string(
            item.get("query_id"), f"result.search_events[{index}].query_id"
        )
        planned = planned_queries.get(query_id)
        if planned is None:
            raise ContractError("result.search_events references an unplanned query")
        event_provider = normalize_provider(
            item.get("provider"), f"result.search_events[{index}].provider"
        )
        event_execution = require_string(
            item.get("execution"), f"result.search_events[{index}].execution"
        )
        if event_provider != planned["provider"]:
            raise ContractError(
                "result.search_events provider does not match its planned provider"
            )
        if event_execution != planned["execution"]:
            raise ContractError(
                "result.search_events execution does not match its planned execution"
            )
        status = require_string(
            item.get("status"), f"result.search_events[{index}].status"
        )
        if status not in BATCH_TERMINAL_STATUSES:
            raise ContractError("result.search_events status is invalid")
        if item.get("query") != planned["query"]:
            raise ContractError("result.search_events query must match query_plan query")

        event_detail = validate_search_event(
            require_dict(
                item.get("search_event"), f"result.search_events[{index}].search_event"
            ),
            f"result.search_events[{index}].search_event",
            event_provider,
        )
        optional_manual_absence = (
            event_provider == GOOGLE_PROVIDER
            and status == "blocked"
            and event_detail.get("artifact_origin") == "not_provided_manual_optional"
        )
        if (
            (status in BATCH_INCOMPLETE_STATUSES and not optional_manual_absence)
            or event_detail.get("truncated") is True
        ):
            incomplete_event_ids.add(query_id)
            incomplete_event_signatures[query_id] = (
                event_provider,
                event_execution,
                status,
                tuple(event_detail.get("limitations", [])),
            )
        candidate_count = item.get("candidate_count")
        if not isinstance(candidate_count, int) or candidate_count < 0:
            raise ContractError(
                f"result.search_events[{index}].candidate_count must be a non-negative integer"
            )
        event_ids.append(query_id)
        search_event_statuses[query_id] = status
    if len(event_ids) != len(set(event_ids)):
        raise ContractError("result.search_events must not repeat query_id")

    unresolved_ids: list[str] = []
    for index, query_id in enumerate(unresolved_query_ids):
        normalized = require_string(
            query_id, f"result.unresolved_query_ids[{index}]"
        )
        if normalized not in planned_id_set:
            raise ContractError("result.unresolved_query_ids references an unknown query")
        unresolved_ids.append(normalized)
    if len(unresolved_ids) != len(set(unresolved_ids)):
        raise ContractError("result.unresolved_query_ids must not contain duplicates")

    failure_ids: list[str] = []
    for index, failure in enumerate(provider_failures):
        item = require_dict(failure, f"result.provider_failures[{index}]")
        query_id = require_string(
            item.get("query_id"), f"result.provider_failures[{index}].query_id"
        )
        planned = planned_queries.get(query_id)
        if planned is None:
            raise ContractError("result.provider_failures references an unplanned query")

        provider = normalize_provider(
            item.get("provider"), f"result.provider_failures[{index}].provider"
        )
        execution = require_string(
            item.get("execution"), f"result.provider_failures[{index}].execution"
        )
        if provider != planned["provider"]:
            raise ContractError(
                "result.provider_failures provider does not match its planned provider"
            )
        if execution != planned["execution"]:
            raise ContractError(
                "result.provider_failures execution does not match its planned execution"
            )
        status = require_string(
            item.get("status"), f"result.provider_failures[{index}].status"
        )
        if status not in BATCH_INCOMPLETE_STATUSES:
            raise ContractError("result.provider_failures must describe an incomplete status")
        limitations: list[str] = []
        if "limitations" in item:
            if not isinstance(item["limitations"], list):
                raise ContractError(
                    f"result.provider_failures[{index}].limitations must be a list"
                )
            for limitation_index, limitation in enumerate(item["limitations"]):
                if not isinstance(limitation, str):
                    raise ContractError(
                        f"result.provider_failures[{index}].limitations[{limitation_index}] must be a string"
                    )
            limitations = list(item["limitations"])

        expected_signature = incomplete_event_signatures.get(query_id)
        actual_signature = (
            provider,
            execution,
            status,
            tuple(limitations),
        )
        if expected_signature != actual_signature:
            raise ContractError(
                "result.provider_failures must be supported by an "
                "incomplete search_event with matching query_id, provider, execution, "
                "status, and limitations"
            )
        failure_ids.append(query_id)
    if len(failure_ids) != len(set(failure_ids)):
        raise ContractError("result.provider_failures must not repeat query_id")

    limits = require_dict(result.get("limits"), "result.limits")
    for field in ("query_budget_reached", "candidate_budget_reached"):
        if not isinstance(limits.get(field), bool):
            raise ContractError(f"result.limits.{field} must be boolean")
    missing_query_ids = limits.get("missing_query_ids")
    if not isinstance(missing_query_ids, list):
        raise ContractError("result.limits.missing_query_ids must be a list")
    normalized_missing_query_ids: list[str] = []
    for index, query_id in enumerate(missing_query_ids):
        normalized = require_string(
            query_id, f"result.limits.missing_query_ids[{index}]"
        )
        normalized_missing_query_ids.append(normalized)
    if len(normalized_missing_query_ids) != len(set(normalized_missing_query_ids)):
        raise ContractError("result.limits.missing_query_ids must not contain duplicates")
    missing_id_set = set(normalized_missing_query_ids)
    event_id_set = set(event_ids)
    unresolved_id_set = set(unresolved_ids)
    failure_id_set = set(failure_ids)
    terminal_event_ids = {
        query_id
        for query_id, status in search_event_statuses.items()
        if status in {"success", "succeeded", "empty"}
    }
    if terminal_event_ids & unresolved_id_set:
        raise ContractError(
            "terminal search events cannot coexist with unresolved query ids"
        )
    if missing_id_set & (event_id_set | unresolved_id_set | failure_id_set):
        raise ContractError(
            "result.limits.missing_query_ids must not overlap completed or unresolved query ids"
        )

    status = result["discovery_status"]
    has_incomplete = bool(
        provider_failures
        or unresolved_ids
        or incomplete_event_ids
        or normalized_missing_query_ids
    )
    has_budget_limit = bool(
        limits["query_budget_reached"]
        or limits["candidate_budget_reached"]
        or normalized_missing_query_ids
    )
    if status == "complete_bounded":
        if has_incomplete or has_budget_limit:
            raise ContractError(
                "complete_bounded results require complete untruncated query coverage "
                "with no provider failure, unresolved query, or budget limit"
            )
        if set(event_ids) != planned_id_set:
            raise ContractError(
                "complete_bounded results require one terminal event per planned query"
            )
    elif status == "partial_budget":
        if not has_budget_limit:
            raise ContractError("partial_budget results require a recorded budget limit")
    elif status in {"partial_provider", "blocked_capability"}:
        if not has_incomplete:
            raise ContractError(
                f"{status} results require an incomplete provider/query condition"
            )

    for index, candidate in enumerate(candidates):
        item = require_dict(candidate, f"result.ranked_candidates[{index}]")
        if item.get("discovery_only") is not True:
            raise ContractError("result candidates must remain discovery_only")
        if item.get("claim_support_eligible") is not False:
            raise ContractError("discovery candidates cannot be claim evidence")
        require_string(
            item.get("candidate_id"), f"result.ranked_candidates[{index}].candidate_id"
        )
    return result


def _validate_result_budget_binding(
    result: dict[str, Any], request: dict[str, Any], expected_plan: dict[str, Any]
) -> None:
    limits = require_dict(result.get("limits"), "result.limits")
    query_budget_reached = limits.get("query_budget_reached")
    if not isinstance(query_budget_reached, bool):
        raise ContractError("result.limits.query_budget_reached must be boolean")
    candidate_budget_reached = limits.get("candidate_budget_reached")
    if not isinstance(candidate_budget_reached, bool):
        raise ContractError("result.limits.candidate_budget_reached must be boolean")

    missing_query_ids = limits.get("missing_query_ids")
    if not isinstance(missing_query_ids, list):
        raise ContractError("result.limits.missing_query_ids must be a list")
    missing_query_ids_list: list[str] = []
    for index, query_id in enumerate(missing_query_ids):
        missing_query_ids_list.append(
            require_string(
                query_id, f"result.limits.missing_query_ids[{index}]"
            )
        )
    if len(missing_query_ids_list) != len(set(missing_query_ids_list)):
        raise ContractError("result.limits.missing_query_ids must not contain duplicates")

    planned_query_ids = {query["query_id"] for query in expected_plan["queries"]}
    expected_query_ids = _expected_query_ids(request)
    expected_missing_query_ids = sorted(expected_query_ids - planned_query_ids)
    if sorted(missing_query_ids_list) != expected_missing_query_ids:
        raise ContractError(
            "search result limits.missing_query_ids does not match request budget "
            "replay"
        )
    if bool(missing_query_ids_list) != query_budget_reached:
        raise ContractError(
            "search result limits.query_budget_reached does not match missing queries"
        )

    pre_truncation_candidate_count = limits.get("pre_truncation_candidate_count")
    if pre_truncation_candidate_count is None:
        raise ContractError(
            "result.limits.pre_truncation_candidate_count is required for request "
            "replay"
        )
    if (
        isinstance(pre_truncation_candidate_count, bool)
        or not isinstance(pre_truncation_candidate_count, int)
        or pre_truncation_candidate_count < 0
    ):
        raise ContractError(
            "result.limits.pre_truncation_candidate_count must be a non-negative int"
        )

    event_candidate_count = 0
    for event in result.get("search_events", []):
        search_event = require_dict(event, "search result.search_events")
        candidate_count = search_event.get("candidate_count")
        if not isinstance(candidate_count, int) or candidate_count < 0:
            raise ContractError(
                "search result.search_events candidate_count must be a non-negative "
                "integer"
            )
        event_candidate_count += candidate_count

    if pre_truncation_candidate_count != event_candidate_count:
        raise ContractError(
            "result.limits.pre_truncation_candidate_count does not match the sum of "
            "search_event candidate_count"
        )

    if pre_truncation_candidate_count < len(result.get("ranked_candidates", [])):
        raise ContractError(
            "result.limits.pre_truncation_candidate_count must be at least the number "
            "of ranked candidates"
        )
    expected_candidate_budget_reached = (
        pre_truncation_candidate_count > request["budgets"]["max_candidates"]
    )
    if candidate_budget_reached != expected_candidate_budget_reached:
        raise ContractError(
            "search result candidate budget flag does not match replayed pre-truncation "
            "candidate count"
        )


def _execution_authorization_ref(
    authorization: dict[str, Any],
    *,
    authorization_file_sha256: str,
    request_set_file_sha256: str,
) -> dict[str, str]:
    return {
        "schema": SEARCH_EXECUTION_AUTHORIZATION_SCHEMA,
        "authorization_id": require_string(
            authorization.get("authorization_id"),
            "execution authorization.authorization_id",
        ),
        "authorization_digest": ensure_sha256(
            authorization.get("authorization_digest"),
            "execution authorization.authorization_digest",
        ),
        "authorization_file_sha256": ensure_sha256(
            authorization_file_sha256, "execution authorization raw file SHA-256"
        ),
        "request_set_file_sha256": ensure_sha256(
            request_set_file_sha256, "request-set raw file SHA-256"
        ),
    }


def validate_result_set(
    value: Any,
    *,
    request_set_value: Any | None = None,
    execution_authority: Any | None = None,
    expected_execution_authority_sha256: str | None = None,
    execution_authority_file_sha256: str | None = None,
    request_set_file_sha256: str | None = None,
) -> dict[str, Any]:
    result_set = copy.deepcopy(require_dict(value, "result_set"))
    schema = result_set.get("schema")
    if schema not in {RESULT_SET_SCHEMA, RESULT_SET_V2_SCHEMA}:
        raise ContractError(
            "result_set.schema must equal ScholarDiscoveryResultSet/v1 or "
            "ScholarDiscoveryResultSet/v2"
        )
    is_current = schema == RESULT_SET_V2_SCHEMA
    if is_current:
        expected_fields = {
            "schema",
            "schema_version",
            "request_set_id",
            "request_set_digest",
            "network_id",
            "network_snapshot_sha256",
            "network_ref",
            "generated_at",
            "execution_authorization_ref",
            "results",
            "failures",
            "request_count",
        }
        if set(result_set) != expected_fields:
            raise ContractError(
                "ScholarDiscoveryResultSet/v2 field set must be exactly "
                f"{sorted(expected_fields)}"
            )
    if result_set.get("schema_version") != REQUEST_SET_SCHEMA_VERSION:
        raise ContractError("result_set.schema_version is unsupported")
    request_set_id = require_string(
        result_set.get("request_set_id"), "result_set.request_set_id"
    )
    request_set_digest = ensure_sha256(
        result_set.get("request_set_digest"), "result_set.request_set_digest"
    )
    if request_set_id != f"request-set-{request_set_digest[:16]}":
        raise ContractError("result_set.request_set_id is invalid")

    if "generated_at" in result_set:
        require_timestamp(result_set.get("generated_at"), "result_set.generated_at")
    if "network_ref" not in result_set:
        raise ContractError("result_set.network_ref is required")
    result_set["network_ref"] = validate_network_ref(
        result_set.get("network_ref"),
        "result_set.network_ref",
        result_set.get("network_id"),
        result_set.get("network_snapshot_sha256"),
    )
    if "network_id" in result_set:
        require_string(result_set.get("network_id"), "result_set.network_id")
    if "network_snapshot_sha256" in result_set:
        ensure_sha256(
            result_set["network_snapshot_sha256"], "result_set.network_snapshot_sha256"
        )

    results = result_set.get("results")
    if not isinstance(results, list):
        raise ContractError("result_set.results must be a list")
    request_ids = set()
    for index, result in enumerate(results):
        validate_result(result)
        request_id = require_string(
            result.get("request_id"), f"result_set.results[{index}].request_id"
        )
        if request_id in request_ids:
            raise ContractError(
                "result_set.results must contain unique request_id values"
            )
        request_ids.add(request_id)
        require_string(
            result.get("hypothesis_id"), f"result_set.results[{index}].hypothesis_id"
        )
        gap_hypothesis_id = require_string(
            result.get("gap_hypothesis_id"),
            f"result_set.results[{index}].gap_hypothesis_id",
        )
        if gap_hypothesis_id != result["hypothesis_id"]:
            raise ContractError(
                f"result_set.results[{index}].hypothesis_id must match gap_hypothesis_id"
            )

    failures = result_set.get("failures", [])
    if not isinstance(failures, list):
        raise ContractError("result_set.failures must be a list")
    failure_request_ids: set[str] = set()
    for index, failure in enumerate(failures):
        item = require_dict(failure, f"result_set.failures[{index}]")
        if item.get("request_set_id") not in {None, request_set_id}:
            raise ContractError(
                f"result_set.failures[{index}].request_set_id is invalid"
            )
        request_id = require_string(
            item.get("request_id"), f"result_set.failures[{index}].request_id"
        )
        if request_id in failure_request_ids:
            raise ContractError(
                "result_set.failures must contain unique request_id values"
            )
        if request_id in request_ids:
            raise ContractError("a request cannot appear in both results and failures")
        failure_request_ids.add(request_id)

    request_count = result_set.get("request_count")
    if (
        isinstance(request_count, bool)
        or not isinstance(request_count, int)
        or request_count < 0
    ):
        raise ContractError("result_set.request_count must be a nonnegative integer")
    represented_request_count = len(request_ids) + len(failure_request_ids)
    if request_count != represented_request_count:
        raise ContractError(
            "result_set.request_count must equal represented results plus failures"
        )

    if not is_current:
        return result_set

    if (
        request_set_value is None
        or execution_authority is None
        or expected_execution_authority_sha256 is None
        or execution_authority_file_sha256 is None
        or request_set_file_sha256 is None
    ):
        raise ContractError(
            "ScholarDiscoveryResultSet/v2 validation requires the exact request "
            "set, ReviewedSearchExecutionAuthorization/v1, caller-provided external "
            "authorization file SHA-256, actual authorization file SHA-256, and "
            "request-set file SHA-256"
        )
    request_set = validate_request_set(copy.deepcopy(request_set_value))
    authorization = validate_search_execution_authorization(
        execution_authority,
        request_set,
        expected_execution_authority_sha256=expected_execution_authority_sha256,
        execution_authority_file_sha256=execution_authority_file_sha256,
        request_set_file_sha256=request_set_file_sha256,
    )
    if result_set["request_set_id"] != request_set["request_set_id"]:
        raise ContractError("result_set.request_set_id does not match request set")
    if result_set["request_set_digest"] != request_set["request_set_digest"]:
        raise ContractError("result_set.request_set_digest does not match request set")
    if result_set["network_ref"] != request_set["network_ref"]:
        raise ContractError("result_set.network_ref does not match request set")
    expected_authorization_ref = _execution_authorization_ref(
        authorization,
        authorization_file_sha256=execution_authority_file_sha256,
        request_set_file_sha256=request_set_file_sha256,
    )
    raw_ref = require_dict(
        result_set.get("execution_authorization_ref"),
        "result_set.execution_authorization_ref",
    )
    if (
        set(raw_ref) != set(expected_authorization_ref)
        or raw_ref != expected_authorization_ref
    ):
        raise ContractError(
            "result_set.execution_authorization_ref is not the owner-replayed "
            "authorization projection"
        )
    requests = {request["request_id"]: request for request in request_set["requests"]}
    for result in result_set["results"]:
        _validate_history_result_binding(result, requests)
        _validate_result_budget_binding(
            result, requests[result["request_id"]], compile_plan(requests[result["request_id"]])
        )
        request = requests[result["request_id"]]
        if result["hypothesis_id"] != request.get("gap_hypothesis_id"):
            raise ContractError("result hypothesis_id does not match its request")
    represented_ids = {result["request_id"] for result in result_set["results"]} | {
        failure["request_id"] for failure in result_set["failures"]
    }
    if represented_ids != set(requests):
        raise ContractError(
            "ScholarDiscoveryResultSet/v2 must represent every and only authorized request"
        )
    return result_set


def _http_transport(url: str, timeout_seconds: int = 30) -> bytes:
    parsed = urllib.parse.urlsplit(url)
    headers = {
        "User-Agent": HTTP_USER_AGENT,
        "Accept": "application/json",
    }
    if parsed.netloc == "api.semanticscholar.org":
        semantic_key = os.getenv(SEMANTIC_SCHOLAR_API_KEY_ENV, "").strip()
        if semantic_key:
            headers["x-api-key"] = semantic_key

    request = urllib.request.Request(
        url,
        headers=headers,
    )
    with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
        return response.read()


def _query_url_openalex(query: str, filters: dict[str, Any]) -> str:
    api_key = os.getenv(OPENALEX_API_KEY_ENV, "").strip()
    filter_values = []
    years = filters.get("years", {})
    if years.get("from") is not None or years.get("to") is not None:
        year_from = years.get("from", "")
        year_to = years.get("to", "")
        if year_from and year_to:
            filter_values.append(f"publication_year:{year_from}-{year_to}")
        elif year_from:
            filter_values.append(f"publication_year:>={year_from}")
        elif year_to:
            filter_values.append(f"publication_year:<={year_to}")

    params = {"search": query, "per-page": OPENALEX_RESULTS_PER_PAGE}
    if api_key:
        params["api_key"] = api_key
    if filter_values:
        params["filter"] = ",".join(filter_values)
    return ENDPOINT_HINTS["openalex"] + "?" + urllib.parse.urlencode(params)


def _query_url_crossref(query: str, filters: dict[str, Any]) -> str:
    years = filters.get("years", {})
    params: dict[str, Any] = {
        "query.title": query,
        "rows": 10,
    }
    if years.get("from") is not None:
        params["filter"] = f"from-pub-date:{years['from']}-01-01"
    if years.get("to") is not None:
        existing = params.get("filter", "")
        params["filter"] = (
            f"{existing},until-pub-date:{years['to']}-12-31"
            if existing
            else f"until-pub-date:{years['to']}-12-31"
        )
    return ENDPOINT_HINTS["crossref"] + "?" + urllib.parse.urlencode(params)


def _query_url_semantic_scholar(query: str, filters: dict[str, Any]) -> str:
    params: dict[str, Any] = {
        "query": query,
        "limit": SEMANTIC_SCHOLAR_RESULTS_LIMIT,
        "fields": SEMANTIC_SCHOLAR_FIELDS,
    }
    return ENDPOINT_HINTS["semantic_scholar"] + "?" + urllib.parse.urlencode(params)


def _parse_openalex_candidates(
    payload: dict[str, Any],
) -> tuple[list[dict[str, Any]], int]:
    results = []
    rejected_candidate_count = 0
    for rank, item in enumerate(payload.get("results", []), start=1):
        authors = [
            author.get("author", {}).get("display_name")
            for author in item.get("authorships", [])
            if isinstance(author, dict)
            and isinstance(author.get("author"), dict)
            and author["author"].get("display_name")
        ]
        venue = None
        if item.get("host_venue", {}).get("display_name"):
            venue = item["host_venue"]["display_name"]
        if venue is None and item.get("primary_location", {}).get("source", {}).get(
            "display_name"
        ):
            venue = item["primary_location"]["source"]["display_name"]

        identifiers, rejected_candidate = _extract_openalex_identifiers(item)
        rejected_candidate_count += rejected_candidate

        publication_status = "peer_reviewed"
        if item.get("is_retracted"):
            publication_status = "retracted"
        elif item.get("raw_type") == "preprint":
            publication_status = "preprint"

        results.append(
            {
                "title": item.get("title", "") or item.get("display_name", ""),
                "authors": authors or ["Unknown"],
                "year": item.get("publication_year"),
                "venue": venue,
                "identifiers": identifiers,
                "work_type": item.get("type", "primary_study"),
                "publication_status": publication_status,
                "access_level": "abstract_only"
                if item.get("abstract_inverted_index")
                else "metadata_only",
                "landing_url": item.get("primary_location", {}).get("landing_page_url")
                or item.get("id"),
                "native_rank": rank,
                "native_score": item.get("relevance_score"),
                "screening": {"decision": "include", "reason": "openalex auto-match"},
            }
        )
    return results, rejected_candidate_count


def _parse_crossref_candidates(
    payload: dict[str, Any],
) -> tuple[list[dict[str, Any]], int]:
    results = []
    rejected_candidate_count = 0
    items = payload.get("message", {}).get("items", [])
    for rank, item in enumerate(items, start=1):
        authors = []
        for author in item.get("author", []):
            family = author.get("family")
            given = author.get("given")
            if given and family:
                authors.append(f"{given} {family}")
            elif family:
                authors.append(family)
        year_parts = item.get("issued", {}).get("date-parts", [[]])[0]
        year = year_parts[0] if year_parts else None
        venue = None
        containers = item.get("container-title", [])
        if isinstance(containers, list) and containers:
            venue = containers[0]

        publication_status = "peer_reviewed"
        raw_type = (item.get("type") or "").lower()
        if "preprint" in raw_type:
            publication_status = "preprint"

        identifiers, rejected_candidate = _extract_crossref_identifiers(item)
        rejected_candidate_count += rejected_candidate

        results.append(
            {
                "title": item.get("title", [""])[0],
                "authors": authors or ["Unknown"],
                "year": year,
                "venue": venue,
                "identifiers": identifiers,
                "work_type": item.get("type", "primary_study"),
                "publication_status": publication_status,
                "access_level": "metadata_only",
                "landing_url": item.get("URL"),
                "native_rank": rank,
                "native_score": None,
                "screening": {"decision": "include", "reason": "crossref auto-match"},
            }
        )
    return results, rejected_candidate_count


def _parse_semantic_scholar_candidates(
    payload: dict[str, Any],
) -> tuple[list[dict[str, Any]], int]:
    items = payload.get("data", [])
    results = []
    rejected_candidate_count = 0
    for rank, item in enumerate(items, start=1):
        authors = []
        for author in item.get("authors", []):
            name = author.get("name") if isinstance(author, dict) else None
            if isinstance(name, str) and name:
                authors.append(name)

        year = item.get("year")
        venue = item.get("venue")
        if isinstance(venue, dict):
            venue = venue.get("name")

        publication_status = "peer_reviewed"
        raw_types = item.get("publicationTypes")
        if isinstance(raw_types, list):
            lowered = ",".join(
                value.lower() for value in raw_types if isinstance(value, str)
            )
            if "preprint" in lowered:
                publication_status = "preprint"

        identifiers, rejected_candidate = _extract_semantic_scholar_identifiers(item)
        rejected_candidate_count += rejected_candidate

        results.append(
            {
                "title": item.get("title", ""),
                "authors": authors or ["Unknown"],
                "year": year,
                "venue": venue,
                "identifiers": identifiers,
                "work_type": item.get("type", "primary_study"),
                "publication_status": publication_status,
                "access_level": "abstract_only"
                if item.get("openAccessPdf")
                else "metadata_only",
                "landing_url": item.get("url"),
                "native_rank": rank,
                "native_score": item.get("score"),
                "screening": {
                    "decision": "include",
                    "reason": "semantic_scholar auto-match",
                },
            }
        )
    return results, rejected_candidate_count


def _build_search_event(
    provider: str,
    query: str,
    url: str,
    payload: bytes,
    candidates: list[dict[str, Any]],
    expected_total: int,
    limitations: list[str],
    status: str,
    rejected_candidate_count: int = 0,
) -> dict[str, Any]:
    redacted_request = {"query": query, "provider": provider, "route": "search"}
    if provider in EXECUTABLE_PROVIDERS:
        redacted_request["filters"] = {"provider": provider}
    response_sha = (
        hashlib.sha256(payload or b"{}").hexdigest()
        if status not in {"blocked"}
        else "0" * 64
    )

    return {
        "endpoint": _normalize_endpoint(url, "batch.search_event.endpoint"),
        "redacted_request": redacted_request,
        "page_or_cursor": "1",
        "expected_total": int(expected_total),
        "retrieved": len(candidates),
        "truncated": len(candidates) < expected_total if expected_total else False,
        "response_sha256": response_sha,
        "limitations": limitations,
        **(
            {"rejected_candidate_count": int(rejected_candidate_count)}
            if rejected_candidate_count
            else {}
        ),
    }


def _build_manual_google_batch(
    request_digest: str,
    query: dict[str, Any],
    access_time: str,
    policy: str,
) -> dict[str, Any]:
    if policy == "manual_required":
        origin = "not_provided_manual_required"
    else:
        origin = "not_provided_manual_optional"
    return {
        "schema": BATCH_SCHEMA,
        "request_digest": request_digest,
        "query_id": query["query_id"],
        "provider": GOOGLE_PROVIDER,
        "execution": SCHOLAR_EXECUTION,
        "status": "blocked",
        "accessed_at": access_time,
        "query": query["query"],
        "search_event": {
            "endpoint": "https://scholar.google.com/scholar",
            "redacted_request": {
                "query": query["query"],
                "provider": GOOGLE_PROVIDER,
                "policy": policy,
                "route": "manual_export",
            },
            "page_or_cursor": "manual",
            "expected_total": 0,
            "retrieved": 0,
            "truncated": False,
            "response_sha256": "0" * 64,
            "artifact_origin": origin,
            "limitations": [GOOGLE_LIMITATION_MANUAL_EXPORT],
        },
        "candidates": [],
    }


def _execute_provider_query(
    provider: str,
    query: dict[str, Any],
    request_digest: str,
    transport: Transport,
    timeout_seconds: int,
) -> dict[str, Any]:
    access_time = now_iso_utc()
    provider_accessed = now_iso_utc()
    if provider == GOOGLE_PROVIDER:
        raise ContractError("Google Scholar must never be automatically executed")

    if provider == "openalex":
        if not os.getenv(OPENALEX_API_KEY_ENV, "").strip():
            return {
                "schema": BATCH_SCHEMA,
                "request_digest": request_digest,
                "query_id": query["query_id"],
                "provider": provider,
                "execution": DOCUMENTED_EXECUTION,
                "status": "blocked",
                "accessed_at": access_time,
                "query": query["query"],
                "search_event": {
                    "endpoint": ENDPOINT_HINTS["openalex"],
                    "redacted_request": {
                        "query": query["query"],
                        "provider": provider,
                        "route": "search",
                    },
                    "page_or_cursor": "1",
                    "expected_total": 0,
                    "retrieved": 0,
                    "truncated": False,
                    "response_sha256": "0" * 64,
                    "limitations": ["blocked_configuration", "missing_api_key"],
                },
                "candidates": [],
            }
        url = _query_url_openalex(query["query"], query["filters"])
        parser = _parse_openalex_candidates
    elif provider == "crossref":
        url = _query_url_crossref(query["query"], query["filters"])
        parser = _parse_crossref_candidates
    elif provider == "semantic_scholar":
        url = _query_url_semantic_scholar(query["query"], query["filters"])
        parser = _parse_semantic_scholar_candidates
    else:
        return {
            "schema": BATCH_SCHEMA,
            "request_digest": request_digest,
            "query_id": query["query_id"],
            "provider": provider,
            "execution": DOCUMENTED_EXECUTION,
            "status": "failed",
            "accessed_at": access_time,
            "query": query["query"],
            "search_event": {
                "endpoint": ENDPOINT_HINTS.get(provider, ""),
                "redacted_request": {
                    "query": query["query"],
                    "provider": provider,
                    "route": "search",
                },
                "page_or_cursor": "1",
                "expected_total": 0,
                "retrieved": 0,
                "truncated": False,
                "response_sha256": "0" * 64,
                "limitations": ["provider_not_implemented"],
            },
            "candidates": [],
        }

    try:
        payload = transport(url, timeout_seconds)
        payload_obj = json.loads(payload.decode("utf-8"))
        candidates, rejected_candidate_count = parser(payload_obj)
        status = "success" if candidates else "empty"
        limitations: list[str] = []
        if rejected_candidate_count:
            limitations.append("rejected_candidate_records")
        if provider == "openalex":
            expected_total = payload_obj.get("meta", {}).get("count", len(candidates))
        elif provider == "crossref":
            expected_total = payload_obj.get("message", {}).get(
                "total-results", len(candidates)
            )
        else:
            expected_total = payload_obj.get("total", len(candidates))
        if expected_total and len(candidates) < expected_total:
            limitations.append("results_truncated")
            status = "partial"

        query_params = urllib.parse.parse_qs(urllib.parse.urlsplit(url).query)
        for key in ("per-page", "rows", "limit"):
            limit_values = query_params.get(key)
            if not limit_values:
                continue
            try:
                limit = int(limit_values[0])
            except (TypeError, ValueError):
                limit = None
            if (
                limit
                and len(candidates) >= limit
                and expected_total
                and len(candidates) < expected_total
            ):
                limitations.append("one_page_truncation")
                break

        search_event = _build_search_event(
            provider,
            query["query"],
            url,
            payload,
            candidates,
            int(expected_total or 0),
            limitations,
            status,
            rejected_candidate_count,
        )
    except (
        urllib.error.HTTPError,
        urllib.error.URLError,
        OSError,
        ValueError,
        json.JSONDecodeError,
    ) as exc:
        status = "failed"
        if isinstance(exc, urllib.error.HTTPError):
            limitations = [f"transport_http_{exc.code}"]
        else:
            limitations = [f"transport_error:{exc.__class__.__name__}"]
        candidates = []
        search_event = {
            "endpoint": _normalize_endpoint(url, "batch.search_event.endpoint"),
            "redacted_request": {
                "query": query["query"],
                "provider": provider,
                "route": "search",
            },
            "page_or_cursor": "1",
            "expected_total": 0,
            "retrieved": 0,
            "truncated": False,
            "response_sha256": "0" * 64,
            "limitations": limitations,
        }
    return {
        "schema": BATCH_SCHEMA,
        "request_digest": request_digest,
        "query_id": query["query_id"],
        "provider": provider,
        "execution": DOCUMENTED_EXECUTION,
        "status": status,
        "accessed_at": provider_accessed,
        "query": query["query"],
        "search_event": search_event,
        "candidates": candidates,
    }


def execute_plan(
    request_value: Any,
    plan_value: Any,
    transport: Transport,
    timeout_seconds: int | None = None,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    request = validate_request(request_value)
    plan = validate_plan(plan_value, request)
    request_digest = sha256_json(request)

    batches: list[dict[str, Any]] = []
    if timeout_seconds is None:
        timeout_seconds = request["budgets"]["timeout_seconds"]

    for query in plan["queries"]:
        if query["provider"] == GOOGLE_PROVIDER:
            batches.append(
                _build_manual_google_batch(
                    request_digest,
                    query,
                    now_iso_utc(),
                    query.get("policy", request["routes"]["google_scholar"]),
                )
            )
            continue

        if query["provider"] not in EXECUTABLE_PROVIDERS:
            batch = {
                "schema": BATCH_SCHEMA,
                "request_digest": request_digest,
                "query_id": query["query_id"],
                "provider": query["provider"],
                "execution": DOCUMENTED_EXECUTION,
                "status": "failed",
                "accessed_at": now_iso_utc(),
                "query": query["query"],
                "search_event": {
                    "endpoint": _normalize_endpoint(
                        query.get("endpoint_hint", ""), "batch.search_event.endpoint"
                    ),
                    "redacted_request": {
                        "query": query["query"],
                        "provider": query["provider"],
                        "route": "search",
                    },
                    "page_or_cursor": "1",
                    "expected_total": 0,
                    "retrieved": 0,
                    "truncated": False,
                    "response_sha256": "0" * 64,
                    "limitations": ["provider_not_implemented"],
                },
                "candidates": [],
            }
        else:
            batch = _execute_provider_query(
                query["provider"], query, request_digest, transport, timeout_seconds
            )

        batches.append(batch)

    discovery = build_result(request, plan, batches)
    return discovery, batches


def _execute_validated_request_set(
    request_set: dict[str, Any],
    transport: Transport,
    timeout_seconds: int | None = None,
    *,
    execution_authority: dict[str, Any],
    expected_execution_authority_sha256: str,
    execution_authority_file_sha256: str,
    request_set_file_sha256: str,
) -> dict[str, Any]:
    request_set_id = request_set.get("request_set_id")
    request_set_digest = request_set.get("request_set_digest")
    network_id = request_set.get("network_id")
    network_snapshot_sha256 = request_set.get("network_snapshot_sha256")
    network_ref = request_set.get("network_ref")

    results: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []

    for request in request_set["requests"]:
        try:
            request_copy = validate_request(dict(request))
            plan = compile_plan(request_copy)
            discovery, _ = execute_plan(request_copy, plan, transport, timeout_seconds)
            discovery["hypothesis_id"] = request_copy.get("gap_hypothesis_id")
            discovery["gap_hypothesis_id"] = request_copy.get("gap_hypothesis_id")
            results.append(discovery)
        except ContractError as exc:
            failures.append(
                {
                    "request_id": request.get("request_id"),
                    "request_set_id": request_set_id,
                    "gap_hypothesis_id": request.get("gap_hypothesis_id"),
                    "error": str(exc),
                }
            )

    result_set = {
        "schema": RESULT_SET_V2_SCHEMA,
        "schema_version": REQUEST_SET_SCHEMA_VERSION,
        "request_set_id": request_set_id,
        "request_set_digest": request_set_digest,
        "network_id": network_id,
        "network_snapshot_sha256": network_snapshot_sha256,
        "network_ref": network_ref,
        "generated_at": request_set.get("generated_at", now_iso_utc()),
        "execution_authorization_ref": _execution_authorization_ref(
            execution_authority,
            authorization_file_sha256=execution_authority_file_sha256,
            request_set_file_sha256=request_set_file_sha256,
        ),
        "results": results,
        "failures": failures,
        "request_count": len(request_set["requests"]),
    }
    return validate_result_set(
        result_set,
        request_set_value=request_set,
        execution_authority=execution_authority,
        expected_execution_authority_sha256=expected_execution_authority_sha256,
        execution_authority_file_sha256=execution_authority_file_sha256,
        request_set_file_sha256=request_set_file_sha256,
    )


def execute_request_set(
    request_set_value: Any,
    transport: Transport,
    timeout_seconds: int | None = None,
    *,
    execution_authority: Any | None = None,
    expected_execution_authority_sha256: str | None = None,
    execution_authority_file: str | Path | None = None,
    execution_authority_file_sha256: str | None = None,
    request_set_file: str | Path,
    request_set_file_sha256: str | None = None,
) -> dict[str, Any]:
    request_set = validate_request_set(request_set_value)
    if request_set["schema"] != REQUEST_SET_SCHEMA:
        raise ContractError(
            "generic execute does not accept appraisal request sets; "
            "use execute-appraisal"
        )
    if (
        execution_authority is None
        or expected_execution_authority_sha256 is None
        or execution_authority_file is None
        or request_set_file is None
    ):
        raise ContractError(
            "provider execution requires ReviewedSearchExecutionAuthorization/v1 "
            "plus expected_execution_authority_sha256, execution_authority_file, and "
            "request_set_file"
        )
    loaded_execution_authority, loaded_execution_authority_file_sha256 = (
        _load_and_match_raw_json_file(
            execution_authority_file,
            require_dict(execution_authority, "execution_authority"),
            label="execution_authority",
        )
    )
    if execution_authority_file_sha256 is not None:
        if (
            execution_authority_file_sha256
            != loaded_execution_authority_file_sha256
        ):
            raise ContractError(
                "execution_authority_file_sha256 does not match execution authority file"
            )
    loaded_request_set, request_file_sha256 = _load_and_match_raw_json_file(
        request_set_file,
        request_set,
        label="request_set",
    )
    request_file_sha256 = ensure_sha256(
        request_file_sha256,
        "execution request-set raw file SHA-256",
    )
    _ = loaded_execution_authority
    _ = loaded_request_set
    if request_set_file_sha256 is not None:
        if request_set_file_sha256 != request_file_sha256:
            raise ContractError(
                "request_set_file_sha256 does not match the loaded request-set file"
            )
    if expected_execution_authority_sha256 is not None:
        expected_execution_authority_sha256 = ensure_sha256(
            expected_execution_authority_sha256,
            "expected_execution_authority_sha256",
        )
    execution_authority_file_sha256 = loaded_execution_authority_file_sha256
    authorization = validate_search_execution_authorization(
        execution_authority,
        request_set,
        expected_execution_authority_sha256=expected_execution_authority_sha256,
        execution_authority_file_sha256=execution_authority_file_sha256,
        request_set_file_sha256=request_file_sha256,
    )
    return _execute_validated_request_set(
        request_set,
        transport,
        timeout_seconds,
        execution_authority=authorization,
        expected_execution_authority_sha256=expected_execution_authority_sha256,
        execution_authority_file_sha256=execution_authority_file_sha256,
        request_set_file_sha256=request_file_sha256,
    )


def execute_appraisal_request_set(
    request_set_value: Any,
    transport: Transport,
    timeout_seconds: int | None = None,
    *,
    execution_authority: Any | None = None,
    expected_execution_authority_sha256: str | None = None,
    execution_authority_file: str | Path | None = None,
    execution_authority_file_sha256: str | None = None,
    request_set_file: str | Path,
    request_set_file_sha256: str | None = None,
) -> dict[str, Any]:
    request_set = validate_appraisal_request_set(request_set_value)
    if (
        execution_authority is None
        or expected_execution_authority_sha256 is None
        or execution_authority_file is None
        or request_set_file is None
    ):
        raise ContractError(
            "provider execution requires ReviewedSearchExecutionAuthorization/v1 "
            "plus expected_execution_authority_sha256, execution_authority_file, and "
            "request_set_file"
        )
    loaded_execution_authority, loaded_execution_authority_file_sha256 = (
        _load_and_match_raw_json_file(
            execution_authority_file,
            require_dict(execution_authority, "execution_authority"),
            label="execution_authority",
        )
    )
    if execution_authority_file_sha256 is not None:
        if (
            execution_authority_file_sha256
            != loaded_execution_authority_file_sha256
        ):
            raise ContractError(
                "execution_authority_file_sha256 does not match execution authority file"
            )
    loaded_request_set, request_file_sha256 = _load_and_match_raw_json_file(
        request_set_file,
        request_set,
        label="request_set",
    )
    request_file_sha256 = ensure_sha256(
        request_file_sha256,
        "execution request-set raw file SHA-256",
    )
    _ = loaded_execution_authority
    _ = loaded_request_set
    if request_set_file_sha256 is not None:
        if request_set_file_sha256 != request_file_sha256:
            raise ContractError(
                "request_set_file_sha256 does not match the loaded request-set file"
            )
    if expected_execution_authority_sha256 is not None:
        expected_execution_authority_sha256 = ensure_sha256(
            expected_execution_authority_sha256,
            "expected_execution_authority_sha256",
        )
    execution_authority_file_sha256 = loaded_execution_authority_file_sha256
    authorization = validate_search_execution_authorization(
        execution_authority,
        request_set,
        expected_execution_authority_sha256=expected_execution_authority_sha256,
        execution_authority_file_sha256=execution_authority_file_sha256,
        request_set_file_sha256=request_file_sha256,
    )
    return _execute_validated_request_set(
        request_set,
        transport,
        timeout_seconds,
        execution_authority=authorization,
        expected_execution_authority_sha256=expected_execution_authority_sha256,
        execution_authority_file_sha256=execution_authority_file_sha256,
        request_set_file_sha256=request_file_sha256,
    )


def canonical_semantic_terms(value: Any) -> list[str]:
    """Return a conservative bag-of-concepts for history and overlap gates."""
    text = require_string(value, "semantic text")
    normalized = unicodedata.normalize("NFKC", text).casefold().replace("'", " ")
    raw_tokens = re.findall(r"[^\W_]+", normalized, flags=re.UNICODE)
    terms: list[str] = []
    for raw_token in raw_tokens:
        token = SEMANTIC_SIGNATURE_SYNONYMS.get(raw_token, raw_token)
        if token in SEMANTIC_SIGNATURE_STOP_WORDS or token.isnumeric():
            continue
        if len(token) > 4 and token.endswith("ies"):
            token = token[:-3] + "y"
        elif len(token) > 4 and token.endswith("s") and not token.endswith("ss"):
            token = token[:-1]
        token = SEMANTIC_SIGNATURE_SYNONYMS.get(token, token)
        if token and token not in SEMANTIC_SIGNATURE_STOP_WORDS:
            terms.append(token)
    return sorted(set(terms))


def semantic_signature_from_terms(terms: list[str]) -> str:
    normalized = sorted(set(require_string_list(terms, "semantic terms")))
    if not normalized:
        raise ContractError("semantic terms must not be empty")
    return sha256_json({"algorithm": "semantic-concept-bag-v1", "terms": normalized})


def semantic_signature(value: Any) -> tuple[str, list[str]]:
    terms = canonical_semantic_terms(value)
    if not terms:
        raise ContractError("semantic text does not contain indexable concepts")
    return semantic_signature_from_terms(terms), terms


def canonical_search_history_digest(document: dict[str, Any]) -> str:
    return sha256_json(
        {
            key: value
            for key, value in document.items()
            if key not in {"history_id", "history_digest"}
        }
    )


def canonical_history_authority_digest(document: dict[str, Any]) -> str:
    normalized = copy.deepcopy(document)
    normalized["authority_digest"] = ""
    return sha256_json(normalized)


def canonical_reviewed_history_authority_digest(document: dict[str, Any]) -> str:
    normalized = copy.deepcopy(document)
    normalized["approval_digest"] = ""
    return sha256_json(normalized)


def history_authority_candidate_file_sha256(
    candidate_value: Any,
    *,
    execution_authority_contexts: dict[str, dict[str, Any]] | None = None,
    replay_artifact_universe: bool = False,
) -> str:
    candidate = validate_history_authority_candidate(
        candidate_value,
        execution_authority_contexts=execution_authority_contexts,
        replay_artifact_universe=replay_artifact_universe,
    )
    return hashlib.sha256(canonical_bytes(candidate) + b"\n").hexdigest()


def load_history_authority_candidate_file(path_value: str | Path) -> dict[str, Any]:
    path = Path(path_value)
    raw = path.read_bytes()
    try:
        parsed = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ContractError(
            "history authority candidate file is not UTF-8 JSON"
        ) from exc
    candidate = validate_history_authority_candidate(parsed)
    if raw != canonical_bytes(candidate) + b"\n":
        raise ContractError(
            "history authority candidate file must use canonical JSON bytes"
        )
    return candidate


def validate_history_authority_candidate(
    value: Any,
    *,
    execution_authority_contexts: dict[str, dict[str, Any]] | None = None,
    replay_artifact_universe: bool = False,
    artifact_file_sha256s: list[str] | None = None,
) -> dict[str, Any]:
    document = copy.deepcopy(require_dict(value, "history authority candidate"))
    base_fields = {
        "schema",
        "schema_version",
        "authority_id",
        "issued_at",
        "artifact_refs",
    }
    constructible_fields = base_fields | {"artifact_universe"}
    private_projection_fields = constructible_fields | {"artifact_file_sha256s"}
    if (
        set(document) != base_fields
        and set(document) != constructible_fields
        and set(document) != private_projection_fields
    ):
        raise ContractError(
            "history authority candidate field set must be exactly "
            f"{sorted(base_fields)} or {sorted(constructible_fields)}"
        )
    if document.get("schema") != HISTORY_AUTHORITY_CANDIDATE_SCHEMA:
        raise ContractError(
            "history authority candidate.schema must equal "
            f"{HISTORY_AUTHORITY_CANDIDATE_SCHEMA}"
        )
    if document.get("schema_version") != REQUEST_SET_SCHEMA_VERSION:
        raise ContractError("history authority candidate.schema_version must equal v1")
    require_timestamp(
        document.get("issued_at"), "history authority candidate.issued_at"
    )
    refs = document.get("artifact_refs")
    if not isinstance(refs, list) or not refs:
        raise ContractError(
            "history authority candidate.artifact_refs must be non-empty"
        )
    keys: list[tuple[str, str]] = []
    for index, raw_ref in enumerate(refs):
        label = f"history authority candidate.artifact_refs[{index}]"
        ref = require_dict(raw_ref, label)
        if set(ref) != {"schema", "sha256"}:
            raise ContractError(f"{label} must contain exactly schema and sha256")
        schema = require_string(ref.get("schema"), f"{label}.schema")
        if schema not in SEARCH_HISTORY_SOURCE_SCHEMAS:
            raise ContractError(f"{label}.schema is unsupported")
        digest = ensure_sha256(ref.get("sha256"), f"{label}.sha256")
        keys.append((schema, digest))
    if keys != sorted(set(keys)):
        raise ContractError(
            "history authority candidate.artifact_refs must be sorted and unique"
        )
    expected_id = (
        HISTORY_AUTHORITY_ID_PREFIX + sha256_json({"artifact_refs": refs})[:16]
    )
    if document.get("authority_id") != expected_id:
        raise ContractError("history authority candidate.authority_id is invalid")

    if "artifact_universe" not in document:
        return document

    universe = document.get("artifact_universe")
    if not isinstance(universe, list) or not universe:
        raise ContractError(
            "history authority candidate.artifact_universe must be non-empty"
        )
    raw_artifacts: list[dict[str, Any]] = []
    universe_keys: list[tuple[str, str]] = []
    for index, raw_member in enumerate(universe):
        label = f"history authority candidate.artifact_universe[{index}]"
        member = require_dict(raw_member, label)
        if set(member) != {"schema", "sha256", "artifact"}:
            raise ContractError(
                f"{label} must contain exactly schema, sha256, and artifact"
            )
        artifact = copy.deepcopy(
            require_dict(member.get("artifact"), f"{label}.artifact")
        )
        schema = require_string(member.get("schema"), f"{label}.schema")
        digest = ensure_sha256(member.get("sha256"), f"{label}.sha256")
        if schema != artifact.get("schema") or digest != sha256_json(artifact):
            raise ContractError(f"{label} does not bind its validated artifact")
        raw_artifacts.append(artifact)
        universe_keys.append((schema, digest))
    if universe_keys != sorted(set(universe_keys)):
        raise ContractError(
            "history authority candidate.artifact_universe must be sorted and unique"
        )
    if universe_keys != keys:
        raise ContractError(
            "history authority candidate.artifact_universe must exactly match artifact_refs"
        )
    if replay_artifact_universe:
        candidate_file_sha256s = artifact_file_sha256s
        if candidate_file_sha256s is None:
            candidate_file_sha256s = document.get("artifact_file_sha256s")
        if (
            candidate_file_sha256s is not None
            and artifact_file_sha256s is not None
            and candidate_file_sha256s != artifact_file_sha256s
        ):
            raise ContractError(
                "history authority candidate artifact-file SHA-256s cannot be supplied twice"
            )
        if candidate_file_sha256s is not None and not isinstance(
            candidate_file_sha256s, list
        ):
            raise ContractError(
                "history authority candidate.artifact_file_sha256s must be a list"
            )
        if candidate_file_sha256s is not None and len(candidate_file_sha256s) != len(
            raw_artifacts
        ):
            raise ContractError(
                "history authority candidate artifact-file SHA-256s must have the same "
                "count as artifact_universe"
            )
        artifacts = _validate_history_source_artifacts(
            raw_artifacts,
            artifact_file_sha256s=candidate_file_sha256s,
            execution_authority_contexts=execution_authority_contexts,
        )
        _validate_history_universe_bindings(artifacts)
        expected_universe = sorted(
            [
                {
                    "schema": artifact["schema"],
                    "sha256": sha256_json(artifact),
                    "artifact": copy.deepcopy(artifact),
                }
                for artifact in artifacts
            ],
            key=lambda row: (row["schema"], row["sha256"]),
        )
        if universe != expected_universe:
            raise ContractError(
                "history authority candidate.artifact_universe is not the owner-replayed projection"
            )
    return document


def build_history_authority_candidate(
    artifact_values: list[Any],
    *,
    issued_at: str,
    execution_authority_contexts: dict[str, dict[str, Any]] | None = None,
    artifact_file_sha256s: list[str] | None = None,
) -> dict[str, Any]:
    require_timestamp(issued_at, "history authority candidate issued_at")
    if not isinstance(artifact_values, list) or not artifact_values:
        raise ContractError("history authority candidate requires source artifacts")
    artifacts = _validate_history_source_artifacts(
        artifact_values,
        artifact_file_sha256s=artifact_file_sha256s,
        execution_authority_contexts=execution_authority_contexts,
    )
    if artifact_file_sha256s is not None and len(artifact_file_sha256s) != len(
        artifacts
    ):
        raise ContractError(
            "history authority candidate artifact-file SHA-256s must have the same "
            "count as source artifacts"
        )
    artifact_rows = [
        (artifact, file_sha256)
        for artifact, file_sha256 in zip(
            artifacts,
            artifact_file_sha256s or [None for _ in range(len(artifacts))],
        )
    ]
    artifact_rows = sorted(
        (
            (
                artifact,
                sha256_json(artifact),
                file_sha256,
            )
            for artifact, file_sha256 in artifact_rows
        ),
        key=lambda row: (row[0]["schema"], row[1]),
    )
    artifact_universe = [
        {
            "schema": artifact["schema"],
            "sha256": artifact_sha256,
            "artifact": copy.deepcopy(artifact),
        }
        for artifact, artifact_sha256, _ in artifact_rows
    ]
    artifact_file_sha256s_universe = [
        file_sha256 for _, _, file_sha256 in artifact_rows
    ] if artifact_file_sha256s is not None else None
    refs = [
        {"schema": row["schema"], "sha256": row["sha256"]} for row in artifact_universe
    ]
    if len({row["sha256"] for row in refs}) != len(refs):
        raise ContractError("history authority candidate artifacts must be unique")
    document = {
        "schema": HISTORY_AUTHORITY_CANDIDATE_SCHEMA,
        "schema_version": REQUEST_SET_SCHEMA_VERSION,
        "authority_id": HISTORY_AUTHORITY_ID_PREFIX
        + sha256_json({"artifact_refs": refs})[:16],
        "issued_at": issued_at,
        "artifact_refs": refs,
        "artifact_universe": artifact_universe,
    }
    if artifact_file_sha256s is not None:
        document["artifact_file_sha256s"] = artifact_file_sha256s_universe
    return validate_history_authority_candidate(
        document,
        execution_authority_contexts=execution_authority_contexts,
        replay_artifact_universe=True,
        artifact_file_sha256s=artifact_file_sha256s_universe,
    )


def review_history_authority_candidate(
    candidate_value: Any,
    *,
    reviewer_id: str,
    reviewer_role: str,
    reviewed_at: str,
    complete_universe_attested: bool,
    independent_reviewer_attested: bool,
    execution_authority_contexts: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    candidate = validate_history_authority_candidate(
        candidate_value,
        execution_authority_contexts=execution_authority_contexts,
        replay_artifact_universe=True,
    )
    if "artifact_universe" not in candidate:
        raise ContractError(
            "history authority approval requires a constructible artifact_universe"
        )
    require_string(reviewer_id, "history authority reviewer_id")
    require_string(reviewer_role, "history authority reviewer_role")
    require_timestamp(reviewed_at, "history authority reviewed_at")
    if complete_universe_attested is not True:
        raise ContractError("complete-universe omission attestation is required")
    if independent_reviewer_attested is not True:
        raise ContractError("independent reviewer attestation is required")
    seed = {
        "candidate_manifest_file_sha256": history_authority_candidate_file_sha256(
            candidate,
            execution_authority_contexts=execution_authority_contexts,
        ),
        "authority_id": candidate["authority_id"],
        "exact_artifact_refs": copy.deepcopy(candidate["artifact_refs"]),
        "decision": "approved",
        "complete_universe_omission_attestation": {
            "complete_universe_attested": True,
            "known_omissions": [],
        },
        "independent_reviewer_context": {
            "reviewer_id": reviewer_id,
            "reviewer_role": reviewer_role,
            "independent_from_history_builder": True,
            "reviewed_at": reviewed_at,
        },
    }
    document = {
        "schema": REVIEWED_HISTORY_AUTHORITY_SCHEMA,
        "approval_id": HISTORY_AUTHORITY_APPROVAL_ID_PREFIX + sha256_json(seed)[:16],
        "approval_digest": "",
        **seed,
    }
    document["approval_digest"] = canonical_reviewed_history_authority_digest(document)
    return validate_reviewed_history_authority(document)


def validate_reviewed_history_authority(value: Any) -> dict[str, Any]:
    document = copy.deepcopy(require_dict(value, "reviewed history authority"))
    expected_fields = {
        "schema",
        "approval_id",
        "approval_digest",
        "candidate_manifest_file_sha256",
        "authority_id",
        "exact_artifact_refs",
        "decision",
        "complete_universe_omission_attestation",
        "independent_reviewer_context",
    }
    if set(document) != expected_fields:
        raise ContractError(
            "reviewed history authority field set must be exactly "
            f"{sorted(expected_fields)}"
        )
    if document.get("schema") != REVIEWED_HISTORY_AUTHORITY_SCHEMA:
        raise ContractError(
            f"reviewed history authority.schema must equal {REVIEWED_HISTORY_AUTHORITY_SCHEMA}"
        )
    ensure_sha256(
        document.get("candidate_manifest_file_sha256"),
        "reviewed history authority.candidate_manifest_file_sha256",
    )
    require_string(
        document.get("authority_id"), "reviewed history authority.authority_id"
    )
    refs = document.get("exact_artifact_refs")
    if not isinstance(refs, list) or not refs:
        raise ContractError(
            "reviewed history authority.exact_artifact_refs must be non-empty"
        )
    keys: list[tuple[str, str]] = []
    for index, raw_ref in enumerate(refs):
        label = f"reviewed history authority.exact_artifact_refs[{index}]"
        ref = require_dict(raw_ref, label)
        if set(ref) != {"schema", "sha256"}:
            raise ContractError(f"{label} must contain exactly schema and sha256")
        schema = require_string(ref.get("schema"), f"{label}.schema")
        if schema not in SEARCH_HISTORY_SOURCE_SCHEMAS:
            raise ContractError(f"{label}.schema is unsupported")
        keys.append((schema, ensure_sha256(ref.get("sha256"), f"{label}.sha256")))
    if keys != sorted(set(keys)):
        raise ContractError(
            "reviewed history authority.exact_artifact_refs must be sorted and unique"
        )
    if document.get("decision") != "approved":
        raise ContractError("reviewed history authority.decision must equal approved")
    attestation = require_dict(
        document.get("complete_universe_omission_attestation"),
        "reviewed history authority.complete_universe_omission_attestation",
    )
    if set(attestation) != {"complete_universe_attested", "known_omissions"}:
        raise ContractError(
            "reviewed history authority omission attestation is invalid"
        )
    if attestation["complete_universe_attested"] is not True:
        raise ContractError(
            "reviewed history authority must attest a complete universe"
        )
    if attestation["known_omissions"] != []:
        raise ContractError("approved history authority cannot declare known omissions")
    context = require_dict(
        document.get("independent_reviewer_context"),
        "reviewed history authority.independent_reviewer_context",
    )
    if set(context) != {
        "reviewer_id",
        "reviewer_role",
        "independent_from_history_builder",
        "reviewed_at",
    }:
        raise ContractError("reviewed history authority reviewer context is invalid")
    require_string(context.get("reviewer_id"), "reviewed history authority.reviewer_id")
    require_string(
        context.get("reviewer_role"), "reviewed history authority.reviewer_role"
    )
    require_timestamp(
        context.get("reviewed_at"), "reviewed history authority.reviewed_at"
    )
    if context["independent_from_history_builder"] is not True:
        raise ContractError("reviewed history authority reviewer must be independent")
    seed = {
        key: copy.deepcopy(value)
        for key, value in document.items()
        if key not in {"schema", "approval_id", "approval_digest"}
    }
    expected_id = HISTORY_AUTHORITY_APPROVAL_ID_PREFIX + sha256_json(seed)[:16]
    if document.get("approval_id") != expected_id:
        raise ContractError("reviewed history authority.approval_id is invalid")
    digest = ensure_sha256(
        document.get("approval_digest"),
        "reviewed history authority.approval_digest",
    )
    if digest != canonical_reviewed_history_authority_digest(document):
        raise ContractError("reviewed history authority.approval_digest is invalid")
    return document


def _history_authority_candidate_from_manifest(
    document: dict[str, Any],
) -> dict[str, Any]:
    return {
        "schema": HISTORY_AUTHORITY_CANDIDATE_SCHEMA,
        "schema_version": document["schema_version"],
        "authority_id": document["authority_id"],
        "issued_at": document["issued_at"],
        "artifact_refs": copy.deepcopy(document["artifact_refs"]),
    }


def finalize_history_authority_manifest(
    candidate_value: Any, reviewed_authority_value: Any
) -> dict[str, Any]:
    candidate = validate_history_authority_candidate(candidate_value)
    if "artifact_universe" not in candidate:
        raise ContractError(
            "history authority finalization requires a constructible artifact_universe"
        )
    reviewed = validate_reviewed_history_authority(reviewed_authority_value)
    if reviewed[
        "candidate_manifest_file_sha256"
    ] != history_authority_candidate_file_sha256(candidate):
        raise ContractError("history authority approval does not bind candidate file")
    if reviewed["authority_id"] != candidate["authority_id"]:
        raise ContractError("history authority approval authority_id mismatch")
    if reviewed["exact_artifact_refs"] != candidate["artifact_refs"]:
        raise ContractError("history authority approval exact refs mismatch")
    document = {
        "schema": HISTORY_AUTHORITY_MANIFEST_SCHEMA,
        "schema_version": candidate["schema_version"],
        "authority_id": candidate["authority_id"],
        "authority_digest": "",
        "issued_at": candidate["issued_at"],
        "candidate_manifest_file_sha256": history_authority_candidate_file_sha256(
            candidate
        ),
        "approval_ref": {
            "approval_id": reviewed["approval_id"],
            "approval_digest": reviewed["approval_digest"],
        },
        "artifact_refs": copy.deepcopy(candidate["artifact_refs"]),
    }
    document["authority_digest"] = canonical_history_authority_digest(document)
    return validate_history_authority_manifest(document, reviewed)


def validate_history_authority_manifest(
    value: Any, reviewed_authority_value: Any
) -> dict[str, Any]:
    document = copy.deepcopy(require_dict(value, "history authority manifest"))
    reviewed = validate_reviewed_history_authority(reviewed_authority_value)
    legacy_fields = {
        "schema",
        "schema_version",
        "authority_id",
        "authority_digest",
        "issued_at",
        "approval_ref",
        "artifact_refs",
    }
    constructible_fields = legacy_fields | {"candidate_manifest_file_sha256"}
    if set(document) != legacy_fields and set(document) != constructible_fields:
        raise ContractError(
            "history authority manifest field set must be exactly "
            f"{sorted(legacy_fields)} or {sorted(constructible_fields)}"
        )
    if document.get("schema") != HISTORY_AUTHORITY_MANIFEST_SCHEMA:
        raise ContractError(
            "history authority manifest.schema must equal "
            f"{HISTORY_AUTHORITY_MANIFEST_SCHEMA}"
        )
    if document.get("schema_version") != REQUEST_SET_SCHEMA_VERSION:
        raise ContractError("history authority manifest.schema_version must equal v1")
    require_timestamp(document.get("issued_at"), "history authority manifest.issued_at")
    refs = document.get("artifact_refs")
    if not isinstance(refs, list) or not refs:
        raise ContractError(
            "history authority manifest.artifact_refs must be non-empty"
        )
    keys: list[tuple[str, str]] = []
    for index, raw_ref in enumerate(refs):
        label = f"history authority manifest.artifact_refs[{index}]"
        ref = require_dict(raw_ref, label)
        if set(ref) != {"schema", "sha256"}:
            raise ContractError(f"{label} must contain exactly schema and sha256")
        schema = require_string(ref.get("schema"), f"{label}.schema")
        if schema not in SEARCH_HISTORY_SOURCE_SCHEMAS:
            raise ContractError(f"{label}.schema is unsupported")
        digest = ensure_sha256(ref.get("sha256"), f"{label}.sha256")
        keys.append((schema, digest))
    if keys != sorted(set(keys)):
        raise ContractError(
            "history authority manifest.artifact_refs must be sorted and unique"
        )
    approval_ref = require_dict(
        document.get("approval_ref"), "history authority manifest.approval_ref"
    )
    if set(approval_ref) != {"approval_id", "approval_digest"}:
        raise ContractError(
            "history authority manifest.approval_ref must contain exactly "
            "approval_id and approval_digest"
        )
    if approval_ref != {
        "approval_id": reviewed["approval_id"],
        "approval_digest": reviewed["approval_digest"],
    }:
        raise ContractError(
            "history authority manifest.approval_ref does not match reviewed approval"
        )
    if "candidate_manifest_file_sha256" in document:
        candidate_file_sha256 = ensure_sha256(
            document.get("candidate_manifest_file_sha256"),
            "history authority manifest.candidate_manifest_file_sha256",
        )
        if candidate_file_sha256 != reviewed["candidate_manifest_file_sha256"]:
            raise ContractError(
                "history authority approval does not bind the candidate manifest file"
            )
    else:
        candidate = _history_authority_candidate_from_manifest(document)
        validate_history_authority_candidate(candidate)
        if reviewed[
            "candidate_manifest_file_sha256"
        ] != history_authority_candidate_file_sha256(candidate):
            raise ContractError(
                "history authority approval does not bind the candidate manifest file"
            )
    if reviewed["authority_id"] != document["authority_id"]:
        raise ContractError("history authority approval authority_id mismatch")
    if reviewed["exact_artifact_refs"] != refs:
        raise ContractError("history authority approval exact refs mismatch")
    expected_id = (
        HISTORY_AUTHORITY_ID_PREFIX + sha256_json({"artifact_refs": refs})[:16]
    )
    if document.get("authority_id") != expected_id:
        raise ContractError("history authority manifest.authority_id is invalid")
    digest = ensure_sha256(
        document.get("authority_digest"),
        "history authority manifest.authority_digest",
    )
    if digest != canonical_history_authority_digest(document):
        raise ContractError("history authority manifest.authority_digest is invalid")
    return document


def history_authority_ref(authority: dict[str, Any]) -> dict[str, str]:
    return {
        "authority_id": authority["authority_id"],
        "authority_digest": authority["authority_digest"],
    }


def _history_source_ref(artifact: dict[str, Any], locator: str) -> dict[str, str]:
    return {
        "schema": artifact["schema"],
        "sha256": sha256_json(artifact),
        "locator": locator,
    }


def _history_request_occurrence(
    artifact: dict[str, Any], locator: str, local_request_id: str
) -> dict[str, Any]:
    scope_ref = _history_source_ref(artifact, locator)
    occurrence_id = (
        "request-occurrence-"
        + sha256_json(
            {
                "request_scope_ref": scope_ref,
                "local_request_id": local_request_id,
            }
        )[:16]
    )
    return {
        "request_occurrence_id": occurrence_id,
        "local_request_id": local_request_id,
        "request_scope_ref": scope_ref,
    }


def _history_entry(
    *,
    text: str,
    objective: str,
    state: str,
    request_id: str,
    source_ref: dict[str, str],
    selection_leak: bool = False,
    request_occurrence: dict[str, Any] | None = None,
) -> dict[str, Any]:
    signature, terms = semantic_signature(text)
    if state not in SEARCH_HISTORY_STATES:
        raise ContractError(f"unsupported search-history state: {state}")
    entry = {
        "semantic_signature": signature,
        "canonical_terms": terms,
        "objective": objective,
        "state": state,
        "source_ref": source_ref,
        "selection_leak": selection_leak,
    }
    if request_occurrence is None:
        entry["request_id"] = request_id
        return entry
    if request_occurrence.get("local_request_id") != request_id:
        raise ContractError("history request occurrence local ID does not match entry")
    entry.update(request_occurrence)
    return entry


def _validate_hypotheses_history_source(value: Any) -> dict[str, Any]:
    document = copy.deepcopy(require_dict(value, "history hypotheses artifact"))
    if document.get("schema") != "KnowledgeGapHypotheses/v1":
        raise ContractError(
            "history hypotheses artifact.schema must equal KnowledgeGapHypotheses/v1"
        )
    require_string(document.get("round_id"), "history hypotheses artifact.round_id")
    hypotheses = document.get("hypotheses")
    if not isinstance(hypotheses, list):
        raise ContractError("history hypotheses artifact.hypotheses must be a list")
    seen_ids: set[str] = set()
    for index, raw_hypothesis in enumerate(hypotheses):
        label = f"history hypotheses artifact.hypotheses[{index}]"
        hypothesis = require_dict(raw_hypothesis, label)
        hypothesis_id = require_string(
            hypothesis.get("hypothesis_id"), f"{label}.hypothesis_id"
        )
        if hypothesis_id in seen_ids:
            raise ContractError(
                "history hypotheses artifact has duplicate hypothesis IDs"
            )
        seen_ids.add(hypothesis_id)
        require_string(hypothesis.get("status"), f"{label}.status")
        search_test = require_dict(
            hypothesis.get("search_test"), f"{label}.search_test"
        )
        queries = search_test.get("queries")
        if not isinstance(queries, list) or not queries:
            raise ContractError(f"{label}.search_test.queries must be non-empty")
        for query_index, raw_query in enumerate(queries):
            query = require_dict(
                raw_query, f"{label}.search_test.queries[{query_index}]"
            )
            require_string(
                query.get("objective"),
                f"{label}.search_test.queries[{query_index}].objective",
            )
            require_string(
                query.get("query"),
                f"{label}.search_test.queries[{query_index}].query",
            )
    return document


def _validate_history_source_artifact(
    value: Any,
    *,
    request_sets: dict[tuple[str, str], dict[str, Any]] | None = None,
    execution_authority_contexts: dict[str, dict[str, Any]] | None = None,
    request_set_file_sha256s: dict[tuple[str, str], str] | None = None,
) -> dict[str, Any]:
    artifact = copy.deepcopy(require_dict(value, "search-history source artifact"))
    schema = artifact.get("schema")
    if schema not in SEARCH_HISTORY_SOURCE_SCHEMAS:
        raise ContractError(f"unsupported search-history source schema: {schema!r}")
    if schema == REQUEST_SCHEMA:
        return validate_request(artifact)
    if schema in {REQUEST_SET_SCHEMA, APPRAISAL_REQUEST_SET_SCHEMA}:
        return validate_request_set(artifact)
    if schema in {RESULT_SCHEMA, RESULT_SET_SCHEMA}:
        # Legacy result payloads in history are display-only read artifacts.
        # Keep source identity and avoid coupling to execution/candidate semantics.
        return artifact
    if schema == RESULT_SET_V2_SCHEMA:
        request_set_id = require_string(
            artifact.get("request_set_id"), "result set.request_set_id"
        )
        request_set_digest = ensure_sha256(
            artifact.get("request_set_digest"), "result set.request_set_digest"
        )
        request_set = (request_sets or {}).get((request_set_id, request_set_digest))
        if request_set is None:
            raise ContractError(
                "ScholarDiscoveryResultSet/v2 history requires its exact request-set artifact"
            )
        if request_set_file_sha256s is not None:
            request_set_file_sha256 = request_set_file_sha256s.get(
                (request_set_id, request_set_digest)
            )
            if request_set_file_sha256 is None:
                raise ContractError(
                    "ScholarDiscoveryResultSet/v2 history requires request-set file sha256 "
                    "from the source artifact loader"
                )
            request_set_file_sha256 = ensure_sha256(
                request_set_file_sha256,
                "search history source request-set file SHA-256",
            )
        else:
            raise ContractError(
                "ScholarDiscoveryResultSet/v2 history requires request-set file sha256 "
                "from the source artifact loader"
            )
        ref = require_dict(
            artifact.get("execution_authorization_ref"),
            "result_set.execution_authorization_ref",
        )
        authorization_id = require_string(
            ref.get("authorization_id"),
            "result_set.execution_authorization_ref.authorization_id",
        )
        context = (execution_authority_contexts or {}).get(authorization_id)
        if context is None:
            raise ContractError(
                "ScholarDiscoveryResultSet/v2 history requires an external "
                "execution authorization context"
            )
        return validate_result_set(
            artifact,
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
    return _validate_hypotheses_history_source(artifact)


def _validate_history_source_artifacts(
    artifact_values: list[Any],
    artifact_file_sha256s: list[str] | None = None,
    execution_authority_contexts: dict[str, dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    raw_artifacts = [
        copy.deepcopy(require_dict(value, "search-history source artifact"))
        for value in artifact_values
    ]
    if artifact_file_sha256s is not None:
        if len(raw_artifacts) != len(artifact_file_sha256s):
            raise ContractError(
                "search history source artifacts and source-artifact file SHA-256s must "
                "have equal counts"
            )
        requested_file_sha256s = [
            ensure_sha256(value, "search history source-artifact file SHA-256")
            for value in artifact_file_sha256s
        ]
    else:
        requested_file_sha256s = None

    request_sets: dict[tuple[str, str], dict[str, Any]] = {}
    request_set_file_sha256s: dict[tuple[str, str], str] | None = None
    for index, artifact in enumerate(raw_artifacts):
        if artifact.get("schema") in {
            REQUEST_SET_SCHEMA,
            APPRAISAL_REQUEST_SET_SCHEMA,
        }:
            validated = validate_request_set(copy.deepcopy(artifact))
            key = (validated["request_set_id"], validated["request_set_digest"])
            if key in request_sets:
                raise ContractError(
                    "search history has duplicate request-set artifacts"
                )
            request_sets[key] = validated
            if requested_file_sha256s is not None:
                if request_set_file_sha256s is None:
                    request_set_file_sha256s = {}
                request_set_file_sha256s[key] = requested_file_sha256s[index]
    return [
        _validate_history_source_artifact(
            artifact,
            request_sets=request_sets,
            execution_authority_contexts=execution_authority_contexts,
            request_set_file_sha256s=request_set_file_sha256s,
        )
        for artifact in raw_artifacts
    ]


def _request_history_entries(
    request: dict[str, Any],
    artifact: dict[str, Any],
    prefix: str,
    *,
    request_occurrence: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    request_id = require_string(request.get("request_id"), "history request_id")
    entries: list[dict[str, Any]] = []
    for index, seed in enumerate(request["query_seeds"]):
        entries.append(
            _history_entry(
                text=seed["query"],
                objective=seed["objective"],
                state="requested",
                request_id=request_id,
                source_ref=_history_source_ref(
                    artifact, f"{prefix}query_seeds[{index}]"
                ),
                request_occurrence=request_occurrence,
            )
        )
    return entries


def _result_history_entries(
    result: dict[str, Any],
    artifact: dict[str, Any],
    prefix: str,
    *,
    request_occurrence: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    request_id = require_string(result.get("request_id"), "history result.request_id")
    objective_by_query_id = {
        row.get("query_id"): row.get("objective", "unknown")
        for row in result.get("query_plan", [])
        if isinstance(row, dict)
    }
    entries: list[dict[str, Any]] = []
    state_map = {
        "success": "succeeded",
        "succeeded": "succeeded",
        "partial": "partial",
        "empty": "empty",
        "failed": "failed",
        "blocked": "blocked",
        "budget_exhausted": "budget_exhausted",
    }
    seen_query_ids: set[str] = set()
    for index, event in enumerate(result.get("search_events", [])):
        if not isinstance(event, dict):
            raise ContractError("result.search_events entries must be objects")
        query = require_string(event.get("query"), "result.search_events[].query")
        query_id = require_string(
            event.get("query_id"), "result.search_events[].query_id"
        )
        status = require_string(event.get("status"), "result.search_events[].status")
        state = state_map.get(status)
        if state is None:
            raise ContractError(f"unsupported result search-event status: {status}")
        seen_query_ids.add(query_id)
        entries.append(
            _history_entry(
                text=query,
                objective=str(objective_by_query_id.get(query_id, "unknown")),
                state=state,
                request_id=request_id,
                source_ref=_history_source_ref(
                    artifact, f"{prefix}search_events[{index}]"
                ),
                request_occurrence=request_occurrence,
            )
        )
    missing_plan_state = {
        "partial_provider": "partial",
        "partial_budget": "budget_exhausted",
        "blocked_capability": "blocked",
        "complete_bounded": "empty",
    }.get(result.get("discovery_status"), "partial")
    for index, plan_query in enumerate(result.get("query_plan", [])):
        if not isinstance(plan_query, dict):
            raise ContractError("result.query_plan entries must be objects")
        query_id = require_string(
            plan_query.get("query_id"), "result.query_plan[].query_id"
        )
        if query_id in seen_query_ids:
            continue
        query = require_string(plan_query.get("query"), "result.query_plan[].query")
        entries.append(
            _history_entry(
                text=query,
                objective=str(plan_query.get("objective", "unknown")),
                state=missing_plan_state,
                request_id=request_id,
                source_ref=_history_source_ref(
                    artifact, f"{prefix}query_plan[{index}]"
                ),
                request_occurrence=request_occurrence,
            )
        )
    for index, candidate in enumerate(result.get("ranked_candidates", [])):
        if not isinstance(candidate, dict):
            raise ContractError("result.ranked_candidates entries must be objects")
        title = require_string(candidate.get("title"), "result candidate.title")
        entries.append(
            _history_entry(
                text=title,
                objective="candidate",
                state="candidate",
                request_id=request_id,
                source_ref=_history_source_ref(
                    artifact, f"{prefix}ranked_candidates[{index}].title"
                ),
                request_occurrence=request_occurrence,
            )
        )
    return entries


def _history_request_universe(
    artifacts: list[dict[str, Any]],
) -> tuple[
    dict[tuple[str, str, str], dict[str, Any]],
    dict[tuple[str, str], dict[str, Any]],
    dict[str, list[dict[str, Any]]],
]:
    requests: dict[tuple[str, str, str], dict[str, Any]] = {}
    request_sets: dict[tuple[str, str], dict[str, Any]] = {}
    requests_by_local_id: dict[str, list[dict[str, Any]]] = {}
    for artifact in artifacts:
        artifact_sha256 = sha256_json(artifact)
        if artifact["schema"] == REQUEST_SCHEMA:
            request = artifact
            local_request_id = request["request_id"]
            context = {
                "request": request,
                "request_occurrence": _history_request_occurrence(
                    artifact, "request", local_request_id
                ),
            }
            key = (artifact["schema"], artifact_sha256, local_request_id)
            if key in requests:
                raise ContractError("search history has duplicate request occurrences")
            requests[key] = context
            requests_by_local_id.setdefault(local_request_id, []).append(context)
        elif artifact["schema"] in {REQUEST_SET_SCHEMA, APPRAISAL_REQUEST_SET_SCHEMA}:
            request_set = artifact
            set_key = (
                request_set["request_set_id"],
                request_set["request_set_digest"],
            )
            if set_key in request_sets:
                raise ContractError(
                    "search history has duplicate request-set artifacts"
                )
            request_by_local_id: dict[str, dict[str, Any]] = {}
            for index, request in enumerate(request_set["requests"]):
                local_request_id = request["request_id"]
                if local_request_id in request_by_local_id:
                    raise ContractError(
                        "request set contains duplicate local request_id values"
                    )
                context = {
                    "request": request,
                    "request_occurrence": _history_request_occurrence(
                        request_set, f"requests[{index}]", local_request_id
                    ),
                }
                request_by_local_id[local_request_id] = context
                request_key = (
                    request_set["schema"],
                    artifact_sha256,
                    local_request_id,
                )
                requests[request_key] = context
                requests_by_local_id.setdefault(local_request_id, []).append(context)
            request_sets[set_key] = {
                "artifact": request_set,
                "request_by_local_id": request_by_local_id,
            }
    return requests, request_sets, requests_by_local_id


def _query_ids_from_status_rows(
    rows: Any, label: str, planned_ids: set[str]
) -> set[str]:
    if rows is None:
        return set()
    if not isinstance(rows, list):
        raise ContractError(f"{label} must be a list")
    output: list[str] = []
    for index, row in enumerate(rows):
        query_id: str | None = None
        if isinstance(row, dict):
            raw_query_id = row.get("query_id")
            if raw_query_id is not None:
                query_id = require_string(raw_query_id, f"{label}[{index}].query_id")
        elif isinstance(row, str) and row in planned_ids:
            query_id = row
        elif isinstance(row, str) and (
            row.startswith("provider:") or row.startswith("provider=")
        ):
            continue
        else:
            raise ContractError(f"{label}[{index}] does not identify a planned query")
        if query_id not in planned_ids:
            raise ContractError(f"{label}[{index}] references an unplanned query")
        output.append(query_id)
    if len(output) != len(set(output)):
        raise ContractError(f"{label} must not repeat a query_id")
    return set(output)


def _validate_history_result_binding(
    result: dict[str, Any], request_context: dict[str, Any]
) -> None:
    request_id = result["request_id"]
    if "request" in request_context:
        request = request_context["request"]
    elif "request_id" in request_context:
        request = request_context
    else:
        request = request_context.get(request_id)
        if request is None:
            raise ContractError(
                "search result history requires its matching request artifact: "
                f"{request_id}"
            )
    if request["request_id"] != request_id:
        raise ContractError("search result history request occurrence is mismatched")
    if result["request_digest"] != sha256_json(request):
        raise ContractError("search result request_digest does not bind its request")
    expected_plan = compile_plan(request)
    _validate_result_budget_binding(result, request, expected_plan)
    if result["plan_digest"] != sha256_json(expected_plan):
        raise ContractError("search result plan_digest does not bind the compiled plan")
    if result.get("query_plan") != expected_plan["queries"]:
        raise ContractError("search result query_plan is not the exact compiled plan")

    planned_by_id = {row["query_id"]: row for row in expected_plan["queries"]}
    planned_ids = set(planned_by_id)
    search_events = result.get("search_events")
    if not isinstance(search_events, list):
        raise ContractError("search result.search_events must be a list")
    event_ids: list[str] = []
    for index, event in enumerate(search_events):
        item = require_dict(event, f"search result.search_events[{index}]")
        query_id = require_string(
            item.get("query_id"), f"search result.search_events[{index}].query_id"
        )
        if query_id not in planned_ids:
            raise ContractError("search result event references an unplanned query")
        if item.get("query") != planned_by_id[query_id]["query"]:
            raise ContractError("search result event query does not match its plan")
        event_ids.append(query_id)
    if len(event_ids) != len(set(event_ids)):
        raise ContractError("search result.search_events must not repeat query_id")

    unresolved_ids = _query_ids_from_status_rows(
        result.get("unresolved_query_ids"),
        "search result.unresolved_query_ids",
        planned_ids,
    )
    failure_ids = _query_ids_from_status_rows(
        result.get("provider_failures"),
        "search result.provider_failures",
        planned_ids,
    )
    covered_ids = set(event_ids) | unresolved_ids | failure_ids
    if covered_ids != planned_ids:
        missing = sorted(planned_ids - covered_ids)
        raise ContractError(
            f"search result does not account for every planned query; missing {missing}"
        )
    if (
        result["discovery_status"]
        in {
            "partial_provider",
            "partial_budget",
            "blocked_capability",
        }
        and not covered_ids
    ):
        raise ContractError("partial or blocked result has no query-level history")


def _validate_history_universe_bindings(
    artifacts: list[dict[str, Any]],
) -> tuple[
    dict[tuple[str, str, str], dict[str, Any]],
    dict[tuple[str, str], dict[str, Any]],
    dict[str, list[dict[str, Any]]],
]:
    requests, request_sets, requests_by_local_id = _history_request_universe(artifacts)
    for artifact in artifacts:
        if artifact["schema"] == RESULT_SCHEMA:
            # Legacy result artifacts are display-only in history.
            continue
        elif artifact["schema"] == RESULT_SET_V2_SCHEMA:
            set_key = (artifact["request_set_id"], artifact["request_set_digest"])
            request_set_context = request_sets.get(set_key)
            if request_set_context is None:
                raise ContractError(
                    "result-set history requires its matching request-set artifact"
                )
            for result in artifact["results"]:
                local_request_id = result["request_id"]
                request_context = request_set_context["request_by_local_id"].get(
                    local_request_id
                )
                if request_context is None:
                    raise ContractError(
                        "result-set history requires the matching request occurrence"
                    )
                _validate_history_result_binding(result, request_context)
            for failure in artifact.get("failures", []):
                if (
                    failure["request_id"]
                    not in request_set_context["request_by_local_id"]
                ):
                    raise ContractError(
                        "failed result history requires the matching request artifact "
                        f"for request_id {failure['request_id']}"
                    )
    return requests, request_sets, requests_by_local_id


def build_search_history_index(
    artifact_values: list[Any],
    authority_manifest: Any,
    reviewed_authority: Any,
    *,
    generated_at: str,
    execution_authority_contexts: dict[str, dict[str, Any]] | None = None,
    artifact_file_sha256s: list[str] | None = None,
    _validate_output: bool = True,
) -> dict[str, Any]:
    require_timestamp(generated_at, "search history generated_at")
    authority_review = validate_reviewed_history_authority(reviewed_authority)
    authority = validate_history_authority_manifest(
        authority_manifest, authority_review
    )
    if not isinstance(artifact_values, list) or not artifact_values:
        raise ContractError("search history requires at least one source artifact")
    artifacts = _validate_history_source_artifacts(
        artifact_values,
        artifact_file_sha256s=artifact_file_sha256s,
        execution_authority_contexts=execution_authority_contexts,
    )
    request_contexts, request_sets, _ = _validate_history_universe_bindings(artifacts)
    use_occurrence_identity = "candidate_manifest_file_sha256" in authority
    artifact_rows = [
        (artifact, file_sha256)
        for artifact, file_sha256 in zip(
            artifacts,
            artifact_file_sha256s
            if artifact_file_sha256s is not None
            else [None for _ in artifacts],
        )
    ]
    artifact_rows = sorted(
        (
            (
                artifact,
                sha256_json(artifact),
                file_sha256,
            )
            for artifact, file_sha256 in artifact_rows
        ),
        key=lambda row: (row[0]["schema"], row[1]),
    )
    source_artifacts = sorted(
        [
            {"schema": artifact["schema"], "sha256": sha256_json(artifact)}
            for artifact in artifacts
        ],
        key=lambda row: (row["schema"], row["sha256"]),
    )
    if len({row["sha256"] for row in source_artifacts}) != len(source_artifacts):
        raise ContractError("search history source artifacts must be unique")
    if source_artifacts != authority["artifact_refs"]:
        raise ContractError(
            "search history artifacts must exactly match the reviewed authority universe"
        )
    artifact_universe = sorted(
        [
            {
                "schema": artifact["schema"],
                "sha256": sha256_json(artifact),
                "artifact": copy.deepcopy(artifact),
            }
            for artifact in artifacts
        ],
        key=lambda row: (row["schema"], row["sha256"]),
    )
    artifact_file_sha256s_universe = (
        [file_sha256 for _, _, file_sha256 in artifact_rows]
        if artifact_file_sha256s is not None
        else None
    )

    def request_history_key(context: dict[str, Any]) -> str:
        if use_occurrence_identity:
            return context["request_occurrence"]["request_occurrence_id"]
        return context["request"]["request_id"]

    request_queries: dict[str, list[tuple[str, str]]] = {}
    for artifact in artifacts:
        if artifact["schema"] == REQUEST_SCHEMA:
            key = (artifact["schema"], sha256_json(artifact), artifact["request_id"])
            context = request_contexts[key]
            request_queries[request_history_key(context)] = [
                (row["objective"], row["query"]) for row in artifact["query_seeds"]
            ]
        elif artifact["schema"] in {REQUEST_SET_SCHEMA, APPRAISAL_REQUEST_SET_SCHEMA}:
            set_context = request_sets[
                (artifact["request_set_id"], artifact["request_set_digest"])
            ]
            for request in artifact["requests"]:
                context = set_context["request_by_local_id"][request["request_id"]]
                request_queries[request_history_key(context)] = [
                    (row["objective"], row["query"]) for row in request["query_seeds"]
                ]

    entries: list[dict[str, Any]] = []
    for artifact in artifacts:
        schema = artifact["schema"]
        if schema == REQUEST_SCHEMA:
            key = (artifact["schema"], sha256_json(artifact), artifact["request_id"])
            context = request_contexts[key]
            entries.extend(
                _request_history_entries(
                    artifact,
                    artifact,
                    "",
                    request_occurrence=(
                        context["request_occurrence"]
                        if use_occurrence_identity
                        else None
                    ),
                )
            )
        elif schema in {REQUEST_SET_SCHEMA, APPRAISAL_REQUEST_SET_SCHEMA}:
            set_context = request_sets[
                (artifact["request_set_id"], artifact["request_set_digest"])
            ]
            for index, request in enumerate(artifact["requests"]):
                context = set_context["request_by_local_id"][request["request_id"]]
                entries.extend(
                    _request_history_entries(
                        request,
                        artifact,
                        f"requests[{index}].",
                        request_occurrence=(
                            context["request_occurrence"]
                            if use_occurrence_identity
                            else None
                        ),
                    )
                )
        elif schema == RESULT_SET_V2_SCHEMA:
            set_context = request_sets[
                (artifact["request_set_id"], artifact["request_set_digest"])
            ]
            for index, result in enumerate(artifact["results"]):
                context = set_context["request_by_local_id"][result["request_id"]]
                entries.extend(
                    _result_history_entries(
                        result,
                        artifact,
                        f"results[{index}].",
                        request_occurrence=(
                            context["request_occurrence"]
                            if use_occurrence_identity
                            else None
                        ),
                    )
                )
            for failure_index, failure in enumerate(artifact.get("failures", [])):
                request_id = require_string(
                    failure.get("request_id"), "result_set.failures[].request_id"
                )
                context = set_context["request_by_local_id"].get(request_id)
                if context is None:
                    raise ContractError(
                        "failed result history requires the matching request occurrence"
                    )
                bound_queries = request_queries.get(request_history_key(context))
                if not bound_queries:
                    raise ContractError(
                        "failed result history requires the matching request artifact "
                        f"for request_id {request_id}"
                    )
                for query_index, (objective, query) in enumerate(bound_queries):
                    entries.append(
                        _history_entry(
                            text=query,
                            objective=objective,
                            state="failed",
                            request_id=request_id,
                            source_ref=_history_source_ref(
                                artifact,
                                "failures["
                                f"{failure_index}].request_id->query_seeds[{query_index}]",
                            ),
                            request_occurrence=(
                                context["request_occurrence"]
                                if use_occurrence_identity
                                else None
                            ),
                        )
                    )
        elif schema in {RESULT_SCHEMA, RESULT_SET_SCHEMA}:
            # Legacy result payloads remain displayable audit members only.  They
            # cannot establish a provider outcome, candidate, or query history.
            continue
        else:
            selected_ids = set(
                artifact.get("selection_summary", {}).get("selected_hypothesis_ids", [])
            )
            has_selection = "selection_summary" in artifact
            for hypothesis_index, hypothesis in enumerate(artifact["hypotheses"]):
                hypothesis_id = hypothesis["hypothesis_id"]
                leaked = has_selection and hypothesis_id not in selected_ids
                state = "selection_leak" if leaked else "requested"
                for query_index, query in enumerate(
                    hypothesis["search_test"]["queries"]
                ):
                    entries.append(
                        _history_entry(
                            text=query["query"],
                            objective=query["objective"],
                            state=state,
                            request_id=f"SDR-{hypothesis_id}",
                            source_ref=_history_source_ref(
                                artifact,
                                f"hypotheses[{hypothesis_index}].search_test."
                                f"queries[{query_index}]",
                            ),
                            selection_leak=leaked,
                            request_occurrence=(
                                _history_request_occurrence(
                                    artifact,
                                    f"hypotheses[{hypothesis_index}]",
                                    f"SDR-{hypothesis_id}",
                                )
                                if use_occurrence_identity
                                else None
                            ),
                        )
                    )

    entries.sort(
        key=lambda row: (
            row["semantic_signature"],
            row["objective"],
            row["state"],
            (
                row["request_occurrence_id"]
                if use_occurrence_identity
                else row["request_id"]
            ),
            row["source_ref"]["sha256"],
            row["source_ref"]["locator"],
        )
    )
    document = {
        "schema": (
            SEARCH_HISTORY_INDEX_V2_SCHEMA
            if use_occurrence_identity
            else SEARCH_HISTORY_INDEX_SCHEMA
        ),
        "schema_version": REQUEST_SET_SCHEMA_VERSION,
        "history_id": "",
        "history_digest": "",
        "generated_at": generated_at,
        "authority_ref": history_authority_ref(authority),
        "source_artifacts": source_artifacts,
        "artifact_universe": artifact_universe,
        "entries": entries,
    }
    digest = canonical_search_history_digest(document)
    document["history_digest"] = digest
    document["history_id"] = f"search-history-{digest[:16]}"
    if _validate_output:
        return validate_search_history_index(
            document,
            authority,
            authority_review,
            execution_authority_contexts=execution_authority_contexts,
            artifact_file_sha256s=artifact_file_sha256s_universe,
            _replay=False,
        )
    return document


def validate_search_history_index(
    value: Any,
    authority_manifest: Any,
    reviewed_authority: Any,
    *,
    execution_authority_contexts: dict[str, dict[str, Any]] | None = None,
    artifact_file_sha256s: list[str] | None = None,
    _replay: bool = True,
) -> dict[str, Any]:
    document = copy.deepcopy(require_dict(value, "search history index"))
    authority_review = validate_reviewed_history_authority(reviewed_authority)
    authority = validate_history_authority_manifest(
        authority_manifest, authority_review
    )
    expected_fields = {
        "schema",
        "schema_version",
        "history_id",
        "history_digest",
        "generated_at",
        "authority_ref",
        "source_artifacts",
        "artifact_universe",
        "entries",
    }
    if set(document) != expected_fields:
        raise ContractError(
            f"search history index field set must be exactly {sorted(expected_fields)}"
        )
    history_schema = require_string(
        document.get("schema"), "search history index.schema"
    )
    if history_schema not in SEARCH_HISTORY_INDEX_SCHEMAS:
        raise ContractError(
            "search history index.schema must equal SearchHistoryIndex/v1 or "
            "SearchHistoryIndex/v2"
        )
    uses_occurrence_identity = history_schema == SEARCH_HISTORY_INDEX_V2_SCHEMA
    if document.get("schema_version") != REQUEST_SET_SCHEMA_VERSION:
        raise ContractError("search history index.schema_version must equal v1")
    require_timestamp(document.get("generated_at"), "search history index.generated_at")
    authority_ref = require_dict(
        document.get("authority_ref"), "search history index.authority_ref"
    )
    if set(authority_ref) != {"authority_id", "authority_digest"}:
        raise ContractError(
            "search history index.authority_ref must contain exactly authority_id "
            "and authority_digest"
        )
    if authority_ref != history_authority_ref(authority):
        raise ContractError(
            "search history index.authority_ref does not match the supplied authority"
        )

    sources = document.get("source_artifacts")
    if not isinstance(sources, list) or not sources:
        raise ContractError("search history index.source_artifacts must be non-empty")
    normalized_sources: list[tuple[str, str]] = []
    for index, raw_source in enumerate(sources):
        source = require_dict(raw_source, f"search history source[{index}]")
        if set(source) != {"schema", "sha256"}:
            raise ContractError(
                "search history source entries must contain exactly schema and sha256"
            )
        schema = require_string(source.get("schema"), "search history source.schema")
        if schema not in SEARCH_HISTORY_SOURCE_SCHEMAS:
            raise ContractError("search history source schema is unsupported")
        digest = ensure_sha256(source.get("sha256"), "search history source.sha256")
        normalized_sources.append((schema, digest))
    if normalized_sources != sorted(set(normalized_sources)):
        raise ContractError("search history sources must be sorted and unique")
    authority_sources = [
        (row["schema"], row["sha256"]) for row in authority["artifact_refs"]
    ]
    if normalized_sources != authority_sources:
        raise ContractError(
            "search history sources do not exactly match the reviewed authority universe"
        )

    universe = document.get("artifact_universe")
    if not isinstance(universe, list) or not universe:
        raise ContractError("search history index.artifact_universe must be non-empty")
    raw_artifacts: list[dict[str, Any]] = []
    universe_keys: list[tuple[str, str]] = []
    for index, raw_member in enumerate(universe):
        label = f"search history index.artifact_universe[{index}]"
        member = require_dict(raw_member, label)
        if set(member) != {"schema", "sha256", "artifact"}:
            raise ContractError(
                f"{label} must contain exactly schema, sha256, and artifact"
            )
        artifact = copy.deepcopy(
            require_dict(member.get("artifact"), f"{label}.artifact")
        )
        schema = require_string(member.get("schema"), f"{label}.schema")
        digest = ensure_sha256(member.get("sha256"), f"{label}.sha256")
        if schema != artifact["schema"] or digest != sha256_json(artifact):
            raise ContractError(f"{label} does not bind its validated artifact")
        raw_artifacts.append(artifact)
        universe_keys.append((schema, digest))
    if universe_keys != sorted(set(universe_keys)):
        raise ContractError(
            "search history artifact_universe must be sorted and unique"
        )
    if universe_keys != normalized_sources:
        raise ContractError(
            "search history source_artifacts must exactly project artifact_universe"
        )
    validated_artifacts = _validate_history_source_artifacts(
        raw_artifacts,
        artifact_file_sha256s=artifact_file_sha256s,
        execution_authority_contexts=execution_authority_contexts,
    )
    _validate_history_universe_bindings(validated_artifacts)
    entries = document.get("entries")
    if not isinstance(entries, list):
        raise ContractError("search history index.entries must be a list")
    entry_sort_keys: list[tuple[str, str, str, str, str, str]] = []
    for index, raw_entry in enumerate(entries):
        label = f"search history index.entries[{index}]"
        entry = require_dict(raw_entry, label)
        base_entry_fields = {
            "semantic_signature",
            "canonical_terms",
            "objective",
            "state",
            "source_ref",
            "selection_leak",
        }
        expected_entry_fields = base_entry_fields | (
            {
                "request_occurrence_id",
                "local_request_id",
                "request_scope_ref",
            }
            if uses_occurrence_identity
            else {"request_id"}
        )
        if set(entry) != expected_entry_fields:
            raise ContractError(
                f"{label} field set must be exactly {sorted(expected_entry_fields)}"
            )
        signature_value = ensure_sha256(
            entry.get("semantic_signature"), f"{label}.semantic_signature"
        )
        terms = require_string_list(
            entry.get("canonical_terms"), f"{label}.canonical_terms"
        )
        if not terms or terms != sorted(set(terms)):
            raise ContractError(
                f"{label}.canonical_terms must be sorted, unique, and non-empty"
            )
        if semantic_signature_from_terms(terms) != signature_value:
            raise ContractError(
                f"{label}.semantic_signature does not match canonical_terms"
            )
        objective = require_string(entry.get("objective"), f"{label}.objective")
        state = require_string(entry.get("state"), f"{label}.state")
        if state not in SEARCH_HISTORY_STATES:
            raise ContractError(f"{label}.state is unsupported")
        if entry.get("selection_leak") not in {True, False}:
            raise ContractError(f"{label}.selection_leak must be boolean")
        if entry["selection_leak"] != (state == "selection_leak"):
            raise ContractError(f"{label}.selection_leak must match state")
        source_ref = require_dict(entry.get("source_ref"), f"{label}.source_ref")
        if set(source_ref) != {"schema", "sha256", "locator"}:
            raise ContractError(
                f"{label}.source_ref must contain exactly schema, sha256, and locator"
            )
        source_schema = require_string(
            source_ref.get("schema"), f"{label}.source_ref.schema"
        )
        source_digest = ensure_sha256(
            source_ref.get("sha256"), f"{label}.source_ref.sha256"
        )
        locator = require_string(
            source_ref.get("locator"), f"{label}.source_ref.locator"
        )
        if (source_schema, source_digest) not in set(normalized_sources):
            raise ContractError(
                f"{label}.source_ref is not declared in source_artifacts"
            )
        if uses_occurrence_identity:
            local_request_id = require_string(
                entry.get("local_request_id"), f"{label}.local_request_id"
            )
            scope_ref = require_dict(
                entry.get("request_scope_ref"), f"{label}.request_scope_ref"
            )
            if set(scope_ref) != {"schema", "sha256", "locator"}:
                raise ContractError(
                    f"{label}.request_scope_ref must contain exactly schema, sha256, and locator"
                )
            scope_schema = require_string(
                scope_ref.get("schema"), f"{label}.request_scope_ref.schema"
            )
            scope_digest = ensure_sha256(
                scope_ref.get("sha256"), f"{label}.request_scope_ref.sha256"
            )
            require_string(
                scope_ref.get("locator"), f"{label}.request_scope_ref.locator"
            )
            if (scope_schema, scope_digest) not in set(normalized_sources):
                raise ContractError(
                    f"{label}.request_scope_ref is not declared in source_artifacts"
                )
            expected_occurrence_id = (
                "request-occurrence-"
                + sha256_json(
                    {
                        "request_scope_ref": scope_ref,
                        "local_request_id": local_request_id,
                    }
                )[:16]
            )
            if entry.get("request_occurrence_id") != expected_occurrence_id:
                raise ContractError(
                    f"{label}.request_occurrence_id does not match its scoped local ID"
                )
            request_identity = expected_occurrence_id
        else:
            request_identity = require_string(
                entry.get("request_id"), f"{label}.request_id"
            )
        entry_sort_keys.append(
            (
                signature_value,
                objective,
                state,
                request_identity,
                source_digest,
                locator,
            )
        )
    if entry_sort_keys != sorted(entry_sort_keys):
        raise ContractError("search history index.entries must be canonically sorted")

    digest = ensure_sha256(
        document.get("history_digest"), "search history index.history_digest"
    )
    if digest != canonical_search_history_digest(document):
        raise ContractError("search history index.history_digest is invalid")
    if document.get("history_id") != f"search-history-{digest[:16]}":
        raise ContractError("search history index.history_id is invalid")
    if _replay:
        expected = build_search_history_index(
            validated_artifacts,
            authority,
            authority_review,
            generated_at=document["generated_at"],
            execution_authority_contexts=execution_authority_contexts,
            artifact_file_sha256s=artifact_file_sha256s,
            _validate_output=False,
        )
        if document != expected:
            raise ContractError(
                "search history index is not the owner-replayed projection of its "
                "complete artifact_universe"
            )
    return document


def validate_any(
    value: Any,
    *,
    history_authority: Any | None = None,
    history_authority_review: Any | None = None,
    execution_request_set: Any | None = None,
    execution_request_set_file_sha256: str | None = None,
    execution_authority: Any | None = None,
    expected_execution_authority_sha256: str | None = None,
    execution_authority_file_sha256: str | None = None,
    execution_authority_contexts: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    schema = value.get("schema") if isinstance(value, dict) else None
    if schema == REQUEST_SCHEMA:
        return validate_request(value)
    if schema == REQUEST_SET_SCHEMA:
        return validate_request_set(value)
    if schema == APPRAISAL_REQUEST_SET_SCHEMA:
        return validate_appraisal_request_set(value)
    if schema == SEARCH_EXECUTION_AUTHORIZATION_SCHEMA:
        if execution_request_set is None:
            raise ContractError(
                "ReviewedSearchExecutionAuthorization/v1 validation requires "
                "the bound request set"
            )
        return validate_search_execution_authorization(
            value,
            execution_request_set,
            request_set_file_sha256=execution_request_set_file_sha256,
        )
    if schema == PREFLIGHT_SCHEMA:
        if execution_request_set is None:
            raise ContractError(
                "ScholarDiscoveryPreflight/v1 validation requires the bound request set"
            )
        return validate_preflight(value, execution_request_set)
    if schema == PLAN_SCHEMA:
        return validate_plan(value)
    if schema == BATCH_SCHEMA:
        return validate_batch(value)
    if schema == RESULT_SCHEMA:
        return validate_result(value)
    if schema == RESULT_SET_SCHEMA:
        return validate_result_set(value)
    if schema == RESULT_SET_V2_SCHEMA:
        return validate_result_set(
            value,
            request_set_value=execution_request_set,
            execution_authority=execution_authority,
            expected_execution_authority_sha256=(expected_execution_authority_sha256),
            execution_authority_file_sha256=execution_authority_file_sha256,
            request_set_file_sha256=execution_request_set_file_sha256,
        )
    if schema == HISTORY_AUTHORITY_CANDIDATE_SCHEMA:
        return validate_history_authority_candidate(value)
    if schema == REVIEWED_HISTORY_AUTHORITY_SCHEMA:
        return validate_reviewed_history_authority(value)
    if schema == HISTORY_AUTHORITY_MANIFEST_SCHEMA:
        if history_authority_review is None:
            raise ContractError(
                "HistoryAuthorityManifest/v1 validation requires "
                "--history-authority-review"
            )
        return validate_history_authority_manifest(value, history_authority_review)
    if schema in SEARCH_HISTORY_INDEX_SCHEMAS:
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
        )
    raise ContractError(f"unsupported schema: {schema!r}")


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description=__doc__)
    subcommands = root.add_subparsers(dest="command", required=True)

    plan = subcommands.add_parser("plan", help="compile a bounded query plan")
    plan.add_argument("--request", required=True)
    plan.add_argument("--output", required=True)

    handoff = subcommands.add_parser("handoff", help="merge normalized batches")
    handoff.add_argument("--request", required=True)
    handoff.add_argument("--plan", required=True)
    handoff.add_argument("--batch", action="append", default=[], required=True)
    handoff.add_argument("--output", required=True)

    execute = subcommands.add_parser("execute", help="execute request-set batches")
    execute.add_argument("--request-set", required=True)
    execute.add_argument("--execution-authority", required=True)
    execute.add_argument("--expected-execution-authority-sha256", required=True)
    execute.add_argument("--output", required=True)

    execute_appraisal = subcommands.add_parser(
        "execute-appraisal", help="execute an appraisal-only request set"
    )
    execute_appraisal.add_argument("--request-set", required=True)
    execute_appraisal.add_argument("--execution-authority", required=True)
    execute_appraisal.add_argument(
        "--expected-execution-authority-sha256", required=True
    )
    execute_appraisal.add_argument("--output", required=True)

    authorize = subcommands.add_parser(
        "authorize-request-set",
        help="independently authorize one exact request-set artifact for execution",
    )
    authorize.add_argument("--request-set", required=True)
    authorize.add_argument("--reviewer-id", required=True)
    authorize.add_argument("--reviewer-role", required=True)
    authorize.add_argument("--reviewed-at", required=True)
    authorize.add_argument("--attest-independent-reviewer", action="store_true")
    authorize.add_argument("--output", required=True)

    compile_gap = subcommands.add_parser(
        "compile-understanding-gap",
        help="compile a PaperUnderstandingGap/v1 into targeted discovery queries",
    )
    compile_gap.add_argument("--gap", required=True)
    compile_gap.add_argument("--as-of", required=True)
    compile_gap.add_argument(
        "--google-scholar-policy",
        choices=sorted(GOOGLE_POLICIES),
        default="manual_optional",
    )
    compile_gap.add_argument("--output", required=True)

    compile_topic = subcommands.add_parser(
        "compile-topic",
        help="compile a domain-grounded ResearchTopicNeedSet/v1",
    )
    compile_topic.add_argument("--topic-needs", required=True)
    compile_topic.add_argument("--output", required=True)

    preflight = subcommands.add_parser(
        "preflight", help="report provider configuration without network access"
    )
    preflight.add_argument("--request-set", required=True)
    preflight.add_argument("--output", required=True)

    history = subcommands.add_parser(
        "build-history",
        help="compile canonical and historical search semantics without network access",
    )
    history.add_argument("--artifact", action="append", required=True)
    history.add_argument("--authority-manifest", required=True)
    history.add_argument("--authority-review", required=True)
    history.add_argument("--execution-authority", action="append", default=[])
    history.add_argument(
        "--expected-execution-authority-sha256", action="append", default=[]
    )
    history.add_argument("--generated-at", required=True)
    history.add_argument("--output", required=True)

    validate = subcommands.add_parser("validate", help="validate one contract")
    validate.add_argument("--input", required=True)
    validate.add_argument("--history-authority")
    validate.add_argument("--history-authority-review")
    validate.add_argument("--request-set")
    validate.add_argument("--execution-authority")
    validate.add_argument("--expected-execution-authority-sha256")

    candidate = subcommands.add_parser(
        "build-history-authority-candidate",
        help="build an exact candidate history universe for independent review",
    )
    candidate.add_argument("--artifact", action="append", required=True)
    candidate.add_argument("--execution-authority", action="append", default=[])
    candidate.add_argument(
        "--expected-execution-authority-sha256", action="append", default=[]
    )
    candidate.add_argument("--issued-at", required=True)
    candidate.add_argument("--output", required=True)

    approve = subcommands.add_parser(
        "approve-history-authority",
        help="independently approve one exact history authority candidate",
    )
    approve.add_argument("--candidate", required=True)
    approve.add_argument("--reviewer-id", required=True)
    approve.add_argument("--reviewer-role", required=True)
    approve.add_argument("--reviewed-at", required=True)
    approve.add_argument("--attest-complete-universe", action="store_true")
    approve.add_argument("--attest-independent-reviewer", action="store_true")
    approve.add_argument("--execution-authority", action="append", default=[])
    approve.add_argument(
        "--expected-execution-authority-sha256", action="append", default=[]
    )
    approve.add_argument("--output", required=True)

    finalize_authority = subcommands.add_parser(
        "finalize-history-authority",
        help="bind an approved review into a final history authority manifest",
    )
    finalize_authority.add_argument("--candidate", required=True)
    finalize_authority.add_argument("--approval", required=True)
    finalize_authority.add_argument("--output", required=True)

    return root


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        if args.command == "plan":
            write_json(args.output, compile_plan(load_json(args.request)))
        elif args.command == "handoff":
            write_json(
                args.output,
                build_result(
                    load_json(args.request),
                    load_json(args.plan),
                    [load_json(path) for path in args.batch],
                ),
            )
        elif args.command == "authorize-request-set":
            request_set, request_set_file_sha256 = load_request_set_artifact_file(
                args.request_set
            )
            write_json(
                args.output,
                authorize_request_set(
                    request_set,
                    reviewer_id=args.reviewer_id,
                    reviewer_role=args.reviewer_role,
                    reviewed_at=args.reviewed_at,
                    independent_reviewer_attested=args.attest_independent_reviewer,
                    request_set_file=args.request_set,
                    request_set_file_sha256=request_set_file_sha256,
                ),
            )
        elif args.command == "execute":
            request_set, request_set_file_sha256 = load_request_set_artifact_file(
                args.request_set
            )
            (
                execution_authority,
                execution_authority_file_sha256,
            ) = load_execution_authority_artifact_file(args.execution_authority)
            write_json(
                args.output,
                    execute_request_set(
                        request_set,
                        _http_transport,
                        execution_authority=execution_authority,
                        expected_execution_authority_sha256=(
                            args.expected_execution_authority_sha256
                        ),
                        execution_authority_file=args.execution_authority,
                        execution_authority_file_sha256=(execution_authority_file_sha256),
                        request_set_file=args.request_set,
                        request_set_file_sha256=request_set_file_sha256,
                    ),
                )
        elif args.command == "execute-appraisal":
            request_set, request_set_file_sha256 = load_request_set_artifact_file(
                args.request_set
            )
            (
                execution_authority,
                execution_authority_file_sha256,
            ) = load_execution_authority_artifact_file(args.execution_authority)
            write_json(
                args.output,
                    execute_appraisal_request_set(
                        request_set,
                        _http_transport,
                        execution_authority=execution_authority,
                        expected_execution_authority_sha256=(
                            args.expected_execution_authority_sha256
                        ),
                        execution_authority_file=args.execution_authority,
                        execution_authority_file_sha256=(execution_authority_file_sha256),
                        request_set_file=args.request_set,
                        request_set_file_sha256=request_set_file_sha256,
                    ),
                )
        elif args.command == "compile-understanding-gap":
            write_json(
                args.output,
                compile_understanding_gap_request(
                    load_json(args.gap),
                    as_of=args.as_of,
                    google_scholar_policy=args.google_scholar_policy,
                ),
            )
        elif args.command == "compile-topic":
            write_json(
                args.output,
                compile_topic_need_set(load_json(args.topic_needs)),
            )
        elif args.command == "preflight":
            write_json(
                args.output,
                build_preflight(load_json(args.request_set)),
            )
        elif args.command == "build-history":
            execution_contexts = load_execution_authority_contexts(
                args.execution_authority,
                args.expected_execution_authority_sha256,
            )
            artifacts = []
            artifact_file_sha256s = []
            for artifact_path in args.artifact:
                artifact, artifact_file_sha256 = load_json_with_file_sha(artifact_path)
                artifacts.append(artifact)
                artifact_file_sha256s.append(artifact_file_sha256)
            write_json(
                args.output,
                build_search_history_index(
                    artifacts,
                    load_json(args.authority_manifest),
                    load_json(args.authority_review),
                    generated_at=args.generated_at,
                    execution_authority_contexts=execution_contexts,
                    artifact_file_sha256s=artifact_file_sha256s,
                ),
            )
        elif args.command == "build-history-authority-candidate":
            execution_contexts = load_execution_authority_contexts(
                args.execution_authority,
                args.expected_execution_authority_sha256,
            )
            artifacts = []
            artifact_file_sha256s = []
            for artifact_path in args.artifact:
                artifact, artifact_file_sha256 = load_json_with_file_sha(artifact_path)
                artifacts.append(artifact)
                artifact_file_sha256s.append(artifact_file_sha256)
            write_json(
                args.output,
                build_history_authority_candidate(
                    artifacts,
                    issued_at=args.issued_at,
                    execution_authority_contexts=execution_contexts,
                    artifact_file_sha256s=artifact_file_sha256s,
                ),
            )
        elif args.command == "approve-history-authority":
            execution_contexts = load_execution_authority_contexts(
                args.execution_authority,
                args.expected_execution_authority_sha256,
            )
            write_json(
                args.output,
                review_history_authority_candidate(
                    load_history_authority_candidate_file(args.candidate),
                    reviewer_id=args.reviewer_id,
                    reviewer_role=args.reviewer_role,
                    reviewed_at=args.reviewed_at,
                    complete_universe_attested=args.attest_complete_universe,
                    independent_reviewer_attested=args.attest_independent_reviewer,
                    execution_authority_contexts=execution_contexts,
                ),
            )
        elif args.command == "finalize-history-authority":
            write_json(
                args.output,
                finalize_history_authority_manifest(
                    load_history_authority_candidate_file(args.candidate),
                    load_json(args.approval),
                ),
            )
        else:
            execution_request_set = None
            execution_request_set_file_sha256 = None
            execution_authority = None
            execution_authority_file_sha256 = None
            if args.request_set:
                (
                    execution_request_set,
                    execution_request_set_file_sha256,
                ) = load_request_set_artifact_file(args.request_set)
            if args.execution_authority:
                (
                    execution_authority,
                    execution_authority_file_sha256,
                ) = load_execution_authority_artifact_file(args.execution_authority)
                if not args.expected_execution_authority_sha256:
                    raise ContractError(
                        "--execution-authority requires "
                        "--expected-execution-authority-sha256"
                    )
            execution_contexts = {}
            if execution_authority is not None:
                execution_contexts = {
                    execution_authority["authorization_id"]: {
                        "authorization": execution_authority,
                        "expected_execution_authority_sha256": (
                            args.expected_execution_authority_sha256
                        ),
                        "execution_authority_file_sha256": (
                            execution_authority_file_sha256
                        ),
                    }
                }
            validated = validate_any(
                load_json(args.input),
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
                execution_request_set=execution_request_set,
                execution_request_set_file_sha256=(execution_request_set_file_sha256),
                execution_authority=execution_authority,
                expected_execution_authority_sha256=(
                    args.expected_execution_authority_sha256
                ),
                execution_authority_file_sha256=(execution_authority_file_sha256),
                execution_authority_contexts=execution_contexts,
            )
            print(
                json.dumps(
                    {"valid": True, "schema": validated["schema"]}, sort_keys=True
                )
            )
        return 0
    except (ContractError, json.JSONDecodeError, OSError) as exc:
        print(f"scholar-discovery validation failed: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
